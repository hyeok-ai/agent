import ast
import json
import operator
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()


'''
OpenAI SDK 없이 HTTP 요청만으로 만든 파일 작업 AI 에이전트입니다.
tool_calling 예제와 같은 "요청 -> 도구 실행 -> 결과를 붙여 다시 요청" 루프를 쓰지만, 세 가지가 다릅니다.
  1. /v1/responses 엔드포인트를 사용해 추론(reasoning)을 켭니다. 모델이 여러 단계를 계획하고,
     도구 결과를 볼 때마다 다음 행동을 다시 생각합니다.
  2. 조회만 하는 도구가 아니라 파일을 쓰는 도구가 있어서, 에이전트가 실제로 결과물을 만듭니다.
  3. 안전장치를 둡니다. 파일 접근은 workspace 폴더 안으로 제한하고, 파일 쓰기 전에는 사용자 승인을 받습니다.
'''
API_URL = "https://api.openai.com/v1/responses"
MODEL = "gpt-6-luna"
API_KEY = os.environ.get("OPENAI_API_KEY")

# 추론 강도입니다. "low"로 낮추면 빠르고 저렴하지만 계획이 단순해지고, "high"로 높이면 그 반대입니다.
REASONING_EFFORT = "medium"

INSTRUCTIONS = """너는 workspace 폴더 안의 파일을 다루는 한국어 작업 에이전트야.
- 작업을 시작하기 전에 list_files로 어떤 파일이 있는지 먼저 확인해.
- 파일 내용을 추측하지 말고 read_file로 직접 읽어.
- 숫자 계산은 암산하지 말고 calculate 도구를 사용해. 합계나 개수도 머릿속으로 미리 더하지 말고,
  원본 데이터의 숫자를 수식에 그대로 넣어 계산해. (예: 판매량 합계는 "28 + 16 + 9")
- 다른 값에서 파생된 숫자(증감률 등)는 앞서 calculate로 얻은 결과만 사용해.
- 작업이 끝나면 무엇을 했는지 짧게 보고해."""

# 에이전트가 도구 호출을 끝없이 반복하는 경우를 막기 위한 한도입니다.
MAX_STEPS = 20

BASE_DIR = Path(__file__).parent
WORKSPACE = (BASE_DIR / "workspace").resolve()
LOG_PATH = BASE_DIR / "http_debug.log"

MAX_READ_CHARS = 20000


# ---------------------------------------------------------------------------
# 1. HTTP 통신 로깅 (chatbot, tool_calling 예제와 같은 방식)
# ---------------------------------------------------------------------------

class HttpDebugger:
    '''
    디버그 모드에서 HTTP 통신 내용을 화면에 출력하고, 같은 내용을 http_debug.log 파일에도 남깁니다.
    httpx가 제공하는 두 가지 관찰 지점을 사용합니다.
      - event_hooks: 요청을 보내기 직전(request)과 응답 헤더를 받은 직후(response)에 호출되는 콜백
      - trace 확장: httpx 아래의 httpcore가 TCP 연결, TLS 핸드셰이크, 헤더/본문 송수신 같은
                    단계를 지날 때마다 호출하는 콜백
    '''

    def __init__(self, enabled=False):
        self.enabled = enabled
        self.started_at = 0.0

    def log(self, text):
        print(text)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    def echo(self, text):
        # 항상 화면에 보여줄 내용입니다. 디버그 모드라면 로그 파일에도 남겨 전체 흐름을 이어서 볼 수 있게 합니다.
        if self.enabled:
            self.log(text)
        else:
            print(text)

    def elapsed_ms(self):
        return (time.perf_counter() - self.started_at) * 1000

    def on_request(self, request):
        if not self.enabled:
            return
        self.started_at = time.perf_counter()
        # 이 요청이 지나가는 httpcore 단계들을 trace 콜백으로 받아보도록 등록합니다.
        request.extensions["trace"] = self.trace

        lines = [
            "",
            f"===== [{datetime.now():%H:%M:%S}] >>> HTTP REQUEST =====",
            f"{request.method} {request.url.raw_path.decode()} HTTP/1.1",
        ]
        for name, value in request.headers.items():
            lines.append(f"{name}: {mask_secret(name, value)}")
        lines.append("")
        lines.append(pretty_json(request.content.decode("utf-8")))
        self.log("\n".join(lines))

    def on_response(self, response):
        '''
        응답 헤더까지 받은 시점에 호출됩니다. 본문은 아직 읽기 전이라 request_llm()에서 따로 기록합니다.
        content-encoding: gzip 헤더가 보인다면 실제 전송은 압축된 바이트이고, httpx가 자동으로 풀어 준 것입니다.
        '''
        if not self.enabled:
            return
        lines = [
            "",
            f"===== [+{self.elapsed_ms():.0f}ms] <<< HTTP RESPONSE =====",
            f"{response.http_version} {response.status_code} {response.reason_phrase}",
        ]
        for name, value in response.headers.items():
            lines.append(f"{name}: {value}")
        lines.append("")
        self.log("\n".join(lines))

    def log_body(self, text):
        if self.enabled:
            self.log(pretty_json(text))

    def trace(self, event_name, info):
        '''
        event_name 예시: "connection.connect_tcp.started", "http11.send_request_headers.complete"
        에이전트는 작업 하나에 요청을 여러 번 보내는데, 두 번째 요청부터는 connect_tcp/start_tls가 보이지 않습니다.
        이미 열린 연결을 재사용(keep-alive)하기 때문입니다.
        '''
        if event_name == "connection.connect_tcp.started":
            self.log(f"[trace +{self.elapsed_ms():5.0f}ms] TCP 연결 시작 -> {info['host']}:{info['port']}")
        elif event_name.endswith(".complete") or event_name.endswith(".failed"):
            step, result = event_name.rsplit(".", 1)
            self.log(f"[trace +{self.elapsed_ms():5.0f}ms] {step} {result}")


def mask_secret(name, value):
    # 로그에 API 키가 그대로 남지 않도록 앞뒤 일부만 보여줍니다.
    if name.lower() == "authorization" and len(value) > 20:
        return f"{value[:14]}...{value[-4:]}"
    return value


def shorten_encrypted(data):
    '''
    reasoning 아이템의 encrypted_content는 수천 자짜리 암호화된 문자열이라 로그를 읽기 어렵게 만듭니다.
    화면과 로그에서만 앞부분만 보여주고, 실제로 서버에 보내는 값은 건드리지 않습니다.
    '''
    if isinstance(data, dict):
        return {
            key: f"{value[:40]}...({len(value)}자 생략)"
            if key == "encrypted_content" and isinstance(value, str) and len(value) > 40
            else shorten_encrypted(value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [shorten_encrypted(item) for item in data]
    return data


def pretty_json(text):
    try:
        return json.dumps(shorten_encrypted(json.loads(text)), ensure_ascii=False, indent=2)
    except ValueError:
        return text


# ---------------------------------------------------------------------------
# 2. 에이전트가 사용할 도구 (실제로 실행되는 파이썬 함수)
# ---------------------------------------------------------------------------

def resolve_path(path):
    '''
    모델이 넘긴 경로를 workspace 기준으로 해석합니다.
    "../agent.py"나 "C:/Windows" 같은 경로로 workspace 밖에 접근하려 하면 에러를 냅니다.
    모델이 만든 값은 신뢰할 수 없는 입력이므로, 도구 쪽에서 반드시 검사해야 합니다.
    '''
    resolved = (WORKSPACE / path).resolve()
    if not resolved.is_relative_to(WORKSPACE):
        raise ValueError(f"workspace 밖의 경로는 사용할 수 없습니다: {path}")
    return resolved


def list_files(path):
    target = resolve_path(path)
    if not target.is_dir():
        raise ValueError(f"폴더가 아닙니다: {path}")

    entries = []
    for item in sorted(target.rglob("*")):
        relative = item.relative_to(WORKSPACE).as_posix()
        if item.is_dir():
            entries.append({"path": relative + "/", "type": "dir"})
        else:
            entries.append({"path": relative, "type": "file", "size_bytes": item.stat().st_size})
    return {"root": path, "entries": entries}


def read_file(path):
    target = resolve_path(path)
    content = target.read_text(encoding="utf-8")
    return {
        "path": path,
        "content": content[:MAX_READ_CHARS],
        "truncated": len(content) > MAX_READ_CHARS,
    }


def write_file(path, content):
    '''
    파일 쓰기는 되돌리기 어려운 작업이라 실행 전에 사용자에게 승인을 받습니다.
    거부하면 에러를 결과로 돌려주고, 모델은 그 결과를 보고 다른 방법을 찾거나 작업을 멈춥니다.
    '''
    target = resolve_path(path)
    exists = target.exists()

    preview = "\n".join(f"    | {line}" for line in content.splitlines()[:15])
    print(f"\n  [승인 필요] write_file: {path} ({'덮어쓰기' if exists else '새 파일'}, {len(content)}자)")
    print(preview)
    if len(content.splitlines()) > 15:
        print("    | ...")
    try:
        answer = input("  이 파일을 저장할까요? (y/n): ").strip().lower()
    except EOFError:
        answer = "n"
    if answer != "y":
        return {"error": "사용자가 파일 저장을 거부했습니다."}

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": path, "chars": len(content), "overwritten": exists}


ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def calculate(expression):
    '''
    eval()은 모델이 만든 문자열을 그대로 실행하므로 위험합니다.
    대신 수식을 구문 트리(AST)로 파싱해서 숫자와 사칙연산만 직접 계산합니다.
    '''
    def evaluate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPERATORS:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("지수가 너무 큽니다.")
            return ALLOWED_OPERATORS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_OPERATORS:
            return ALLOWED_OPERATORS[type(node.op)](evaluate(node.operand))
        raise ValueError(f"지원하지 않는 수식입니다: {ast.unparse(node)}")

    return {"expression": expression, "result": evaluate(ast.parse(expression, mode="eval").body)}


TOOL_FUNCTIONS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "calculate": calculate,
}


# ---------------------------------------------------------------------------
# 3. 모델에게 보낼 도구 설명서
# ---------------------------------------------------------------------------
'''
/v1/responses의 tools 형식은 chat completions와 조금 다릅니다.
  chat completions: {"type": "function", "function": {"name": ..., "parameters": ...}}
  responses:        {"type": "function", "name": ..., "parameters": ..., "strict": true}
strict를 true로 두면 서버가 arguments를 parameters 스키마에 정확히 맞춰 생성하도록 강제합니다.
대신 모든 속성을 required에 넣고 additionalProperties를 false로 지정해야 합니다.
'''
TOOLS = [
    {
        "type": "function",
        "name": "list_files",
        "description": "workspace 안의 폴더에 있는 파일과 하위 폴더를 재귀적으로 나열한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "workspace 기준 폴더 경로. 최상위는 \".\""},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "read_file",
        "description": "workspace 안의 텍스트 파일(UTF-8) 내용을 읽는다.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "workspace 기준 파일 경로. 예: sales.csv"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "write_file",
        "description": "workspace 안에 텍스트 파일을 저장한다. 없는 폴더는 자동으로 만들고, 같은 이름의 파일은 덮어쓴다. 실행 전에 사용자 승인을 받는다.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "workspace 기준 파일 경로. 예: reports/summary.md"},
                "content": {"type": "string", "description": "저장할 파일 전체 내용"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "calculate",
        "description": "사칙연산 수식을 계산한다. + - * / // % ** 와 괄호를 지원한다. 여러 값을 더할 때도 한 수식으로 계산할 수 있다.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "계산할 수식. 예: 12*1500000 + 30*320000"},
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


# ---------------------------------------------------------------------------
# 4. LLM 요청과 에이전트 루프
# ---------------------------------------------------------------------------

def request_llm(client, debugger, input_items):
    '''
    /v1/responses 요청 본문의 주요 필드입니다.
      - instructions: chat completions의 system 메시지 역할
      - input: 대화 기록. chat completions의 messages와 달리 "아이템" 배열입니다.
               (user 메시지, reasoning, function_call, function_call_output, assistant 메시지 등)
      - reasoning.summary: 모델이 무슨 생각을 했는지 요약해서 돌려달라는 옵션
      - store: false로 두면 서버에 대화를 저장하지 않습니다. 그래서 매번 전체 input을 다시 보냅니다.
      - include: store가 false일 때 추론 내용을 다음 요청에 이어 붙일 수 있도록,
                 암호화된 추론 내용(encrypted_content)을 응답에 포함해 달라는 옵션
    '''
    body = {
        "model": MODEL,
        "instructions": INSTRUCTIONS,
        "input": input_items,
        "tools": TOOLS,
        "reasoning": {"effort": REASONING_EFFORT, "summary": "auto"},
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    response = client.post(
        API_URL,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json=body,
    )
    debugger.log_body(response.text)

    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}\n{response.text}")
    return response.json()


def run_tool(debugger, call):
    '''
    function_call 아이템 하나를 실행합니다. 구조는 이렇습니다.
        {"type": "function_call", "call_id": "call_abc", "name": "read_file", "arguments": "{\"path\": \"memo.txt\"}"}
    arguments는 JSON "문자열"이라 json.loads로 풀어야 합니다.
    실행 중 에러가 나도 프로그램을 멈추지 않고, 에러 내용을 결과로 돌려줘서 모델이 대응하게 합니다.
    '''
    name = call["name"]
    try:
        args = json.loads(call["arguments"])
        result = TOOL_FUNCTIONS[name](**args)
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}

    # read_file 결과처럼 긴 내용은 화면에서는 줄여서 보여줍니다. 모델에게는 전체를 보냅니다.
    summary = json.dumps(result, ensure_ascii=False)
    if len(summary) > 200:
        summary = summary[:200] + f"...({len(summary)}자)"
    debugger.echo(f"  [도구 실행] {name}({call['arguments'][:100]}) -> {summary}")
    return result


def message_text(item):
    return "".join(part.get("text", "") for part in item.get("content", []) if part.get("type") == "output_text")


def run_agent(client, debugger, input_items):
    for step in range(1, MAX_STEPS + 1):
        data = request_llm(client, debugger, input_items)
        output = data.get("output", [])

        usage = data.get("usage", {})
        reasoning_tokens = usage.get("output_tokens_details", {}).get("reasoning_tokens")
        debugger.echo(
            f"\n  (요청 {step}: 입력 토큰 {usage.get('input_tokens')} / 출력 토큰 {usage.get('output_tokens')}"
            f", 그중 추론 {reasoning_tokens})"
        )

        '''
        응답의 output 배열을 그대로 input 끝에 이어 붙입니다.
        reasoning 아이템까지 함께 돌려보내야 모델이 이전 단계에서 세운 계획을 이어서 생각할 수 있습니다.
        '''
        input_items.extend(output)

        if data.get("status") != "completed":
            return f"(응답이 완료되지 않았습니다: {data.get('status')} {data.get('incomplete_details')})"

        calls = []
        final_text = ""
        for item in output:
            if item["type"] == "reasoning":
                for part in item.get("summary", []):
                    debugger.echo(f"  [생각] {part['text']}")
            elif item["type"] == "function_call":
                calls.append(item)
            elif item["type"] == "message":
                final_text += message_text(item)

        # 도구 호출이 없으면 모델이 작업을 끝냈다고 판단한 것입니다.
        if not calls:
            return final_text

        # 도구를 호출하면서 중간 설명을 함께 보내는 경우도 있습니다.
        if final_text:
            debugger.echo(f"  [모델] {final_text}")

        '''
        각 결과는 function_call_output 아이템으로 추가하고, call_id로 어느 호출의 결과인지 짝을 맞춥니다.
        (chat completions의 role "tool" 메시지 + tool_call_id에 해당합니다)
        '''
        for call in calls:
            result = run_tool(debugger, call)
            input_items.append({
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": json.dumps(result, ensure_ascii=False),
            })

    return f"(도구 호출이 {MAX_STEPS}번을 넘어 중단했습니다.)"


def print_help():
    print("명령어: /debug (HTTP 통신 로그 on/off)  /history (input 아이템 보기)")
    print("        /reset (대화 초기화)  /exit (종료)")
    print("예시 작업: memo.txt의 요청대로 보고서를 만들어줘")


def main():
    if not API_KEY:
        print("OPENAI_API_KEY 환경 변수가 없습니다. .env 파일에 OPENAI_API_KEY=sk-... 를 추가하세요.")
        sys.exit(1)

    WORKSPACE.mkdir(exist_ok=True)
    input_items = []
    debugger = HttpDebugger(enabled="--debug" in sys.argv)

    print(f"모델: {MODEL} (추론: {REASONING_EFFORT})  작업 폴더: {WORKSPACE}")
    print(f"도구: {', '.join(TOOL_FUNCTIONS)}")
    print_help()
    if debugger.enabled:
        print(f"디버그 모드 ON (로그 파일: {LOG_PATH})")

    event_hooks = {"request": [debugger.on_request], "response": [debugger.on_response]}
    # 추론을 켜면 응답이 오래 걸릴 수 있어서 타임아웃을 넉넉히 둡니다.
    with httpx.Client(timeout=300, event_hooks=event_hooks) as client:
        while True:
            try:
                user_input = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue
            if user_input == "/exit":
                break
            if user_input == "/help":
                print_help()
                continue
            if user_input == "/debug":
                debugger.enabled = not debugger.enabled
                print(f"디버그 모드: {'ON' if debugger.enabled else 'OFF'} (로그 파일: {LOG_PATH})")
                continue
            if user_input == "/history":
                print(json.dumps(shorten_encrypted(input_items), ensure_ascii=False, indent=2))
                continue
            if user_input == "/reset":
                input_items = []
                print("대화를 초기화했습니다.")
                continue

            # 실패하면 이번 턴에 추가된 아이템을 모두 되돌리기 위해 시작 위치를 기억합니다.
            turn_start = len(input_items)
            input_items.append({"role": "user", "content": user_input})

            try:
                answer = run_agent(client, debugger, input_items)
            except (RuntimeError, httpx.HTTPError) as e:
                print(f"[요청 실패] {e}")
                del input_items[turn_start:]
                continue

            debugger.echo(f"\nAI: {answer}")


if __name__ == "__main__":
    main()
