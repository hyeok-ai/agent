import ast
import json
import operator
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()


'''
OpenAI SDK 없이 HTTP 요청만으로 tool calling을 구현한 예제입니다.
tool calling은 모델이 함수를 직접 실행하는 기능이 아닙니다. 실제 흐름은 이렇습니다.
  1. 클라이언트가 요청 본문의 "tools"에 사용할 수 있는 함수 목록(이름, 설명, 인자 JSON Schema)을 담아 보낸다.
  2. 모델은 함수가 필요하다고 판단하면, 답변 대신 "이 함수를 이 인자로 호출해 줘"(tool_calls)라고 응답한다.
  3. 클라이언트가 그 함수를 직접 실행하고, 결과를 role "tool" 메시지로 대화에 추가해 다시 요청한다.
  4. 모델이 결과를 보고 최종 답변을 하거나, 필요하면 다른 함수를 또 요청한다. (2~4 반복)
'''
API_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-6-luna"
API_KEY = os.environ.get("OPENAI_API_KEY")

SYSTEM_PROMPT = "너는 도구를 활용하는 한국어 비서야. 계산이나 시간, 날씨 질문에는 반드시 도구를 사용해. 답변은 간결하게 해."

# 모델이 도구 호출을 끝없이 반복하는 경우를 막기 위한 한도입니다.
MAX_STEPS = 5

LOG_PATH = Path(__file__).parent / "http_debug.log"


# ---------------------------------------------------------------------------
# 1. 실제로 실행될 파이썬 함수들
# ---------------------------------------------------------------------------

def get_current_time(utc_offset):
    tz = timezone(timedelta(hours=utc_offset))
    now = datetime.now(tz)
    return {"utc_offset": utc_offset, "datetime": now.strftime("%Y-%m-%d %H:%M:%S"), "weekday": now.strftime("%A")}


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


# 예제용 가짜 데이터입니다. 실제 서비스라면 여기서 날씨 API를 호출합니다.
FAKE_WEATHER = {
    "서울": {"condition": "맑음", "temperature_c": 18},
    "부산": {"condition": "흐림", "temperature_c": 21},
    "제주": {"condition": "비", "temperature_c": 20},
}


def get_weather(city):
    if city not in FAKE_WEATHER:
        return {"error": f"{city}의 날씨 정보가 없습니다. 지원 도시: {', '.join(FAKE_WEATHER)}"}
    return {"city": city, **FAKE_WEATHER[city]}


TOOL_FUNCTIONS = {
    "get_current_time": get_current_time,
    "calculate": calculate,
    "get_weather": get_weather,
}


# ---------------------------------------------------------------------------
# 2. 모델에게 보낼 도구 설명서 (요청 본문의 "tools")
# ---------------------------------------------------------------------------
'''
모델은 파이썬 코드를 볼 수 없고, 오직 이 JSON만 보고 어떤 도구를 언제, 어떤 인자로 부를지 결정합니다.
그래서 description을 잘 쓰는 것이 중요합니다. parameters는 표준 JSON Schema 형식입니다.
'''
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "지정한 UTC 시차 기준의 현재 날짜와 시각을 반환한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "utc_offset": {
                        "type": "integer",
                        "description": "UTC 기준 시차(시간 단위). 예: 서울 9, 런던 0, 뉴욕 -4",
                    },
                },
                "required": ["utc_offset"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "사칙연산 수식을 계산한다. + - * / // % ** 와 괄호를 지원한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "계산할 수식. 예: (1200 * 3) / 7"},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "도시의 현재 날씨를 반환한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "도시 이름(한글). 예: 서울"},
                },
                "required": ["city"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# 3. HTTP 통신 로깅 (chatbot 예제와 같은 방식)
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
        tool calling은 질문 하나에 요청이 여러 번 오가는데, 두 번째 요청부터는 connect_tcp/start_tls가 보이지 않습니다.
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


def pretty_json(text):
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except ValueError:
        return text


# ---------------------------------------------------------------------------
# 4. LLM 요청과 tool calling 루프
# ---------------------------------------------------------------------------

def request_llm(client, debugger, messages):
    '''
    chatbot 예제와 같은 엔드포인트에 "tools"만 추가해서 보냅니다.
    서버는 대화뿐 아니라 도구 목록도 기억하지 않으므로, 매 요청마다 tools를 함께 보내야 합니다.

    gpt-6-luna는 /v1/chat/completions에서 추론(reasoning)과 function tools를 함께 쓸 수 없습니다.
    빼면 HTTP 400 "Function tools with reasoning_effort are not supported ..." 에러가 납니다.
    그래서 reasoning_effort를 "none"으로 끄고 사용합니다. 추론까지 쓰려면 /v1/responses 엔드포인트를 써야 합니다.
    '''
    body = {
        "model": MODEL,
        "messages": messages,
        "tools": TOOLS,
        "reasoning_effort": "none",
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


def run_tool(debugger, tool_call):
    '''
    모델이 보낸 tool_call 하나를 실행합니다. 구조는 이렇습니다.
        {"id": "call_abc", "type": "function",
         "function": {"name": "get_weather", "arguments": "{\"city\": \"서울\"}"}}
    arguments는 객체가 아니라 JSON "문자열"이라서 직접 json.loads로 풀어야 합니다.
    실행 중 에러가 나도 프로그램을 멈추지 않고, 에러 내용을 결과로 돌려줘서 모델이 대응하게 합니다.
    '''
    name = tool_call["function"]["name"]
    try:
        args = json.loads(tool_call["function"]["arguments"])
        func = TOOL_FUNCTIONS[name]
        result = func(**args)
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}

    debugger.echo(f"  [도구 실행] {name}({tool_call['function']['arguments']}) -> {json.dumps(result, ensure_ascii=False)}")
    return result


def run_agent(client, debugger, messages):
    for step in range(1, MAX_STEPS + 1):
        data = request_llm(client, debugger, messages)
        message = data["choices"][0]["message"]
        tool_calls = message.get("tool_calls")

        usage = data.get("usage", {})
        debugger.echo(f"  (요청 {step}: 입력 토큰 {usage.get('prompt_tokens')} / 출력 토큰 {usage.get('completion_tokens')})")

        '''
        모델의 응답은 tool_calls가 있든 없든 assistant 메시지로 대화 기록에 추가합니다.
        특히 tool_calls가 담긴 assistant 메시지가 빠지면, 뒤에 붙는 tool 메시지가 어느 호출의 결과인지
        서버가 알 수 없어 400 에러가 납니다.
        '''
        assistant_message = {"role": "assistant", "content": message.get("content")}
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        messages.append(assistant_message)

        # tool_calls가 없으면 모델이 최종 답변을 한 것입니다. (finish_reason도 "tool_calls"가 아니라 "stop")
        if not tool_calls:
            return message.get("content")

        '''
        모델은 한 번에 여러 도구를 요청할 수 있습니다. (예: "서울이랑 부산 날씨 알려줘")
        각 결과는 role "tool" 메시지로 추가하고, tool_call_id로 어느 요청에 대한 결과인지 짝을 맞춥니다.
        content는 문자열이어야 하므로 결과를 JSON 문자열로 바꿔서 넣습니다.
        '''
        for tool_call in tool_calls:
            result = run_tool(debugger, tool_call)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })

    return f"(도구 호출이 {MAX_STEPS}번을 넘어 중단했습니다.)"


def print_help():
    print("명령어: /debug (HTTP 통신 로그 on/off)  /history (messages 보기)")
    print("        /reset (대화 초기화)  /exit (종료)")
    print("예시 질문: 서울이랑 부산 날씨 알려줘 / 지금 뉴욕은 몇 시야? / 1234 * 5678 은?")


def main():
    if not API_KEY:
        print("OPENAI_API_KEY 환경 변수가 없습니다. .env 파일에 OPENAI_API_KEY=sk-... 를 추가하세요.")
        sys.exit(1)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    debugger = HttpDebugger(enabled="--debug" in sys.argv)

    print(f"모델: {MODEL}  도구: {', '.join(TOOL_FUNCTIONS)}")
    print_help()
    if debugger.enabled:
        print(f"디버그 모드 ON (로그 파일: {LOG_PATH})")

    event_hooks = {"request": [debugger.on_request], "response": [debugger.on_response]}
    with httpx.Client(timeout=120, event_hooks=event_hooks) as client:
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
                print(json.dumps(messages, ensure_ascii=False, indent=2))
                continue
            if user_input == "/reset":
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                print("대화를 초기화했습니다.")
                continue

            # 실패하면 이번 턴에 추가된 메시지를 모두 되돌리기 위해 시작 위치를 기억합니다.
            turn_start = len(messages)
            messages.append({"role": "user", "content": user_input})

            try:
                answer = run_agent(client, debugger, messages)
            except (RuntimeError, httpx.HTTPError) as e:
                print(f"[요청 실패] {e}")
                del messages[turn_start:]
                continue

            debugger.echo(f"AI: {answer}")


if __name__ == "__main__":
    main()
