import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()


'''
MCP SDK와 OpenAI SDK 없이 만든 MCP 에이전트입니다. agent.py(langchain-mcp-adapters 사용)와 하는 일은 같습니다.
  1. MCP 서버에 연결해 도구 목록을 받아온다.          (MCP: initialize -> tools/list)
  2. 그 도구들을 LLM의 tools 형식으로 바꿔서 전달한다.  (OpenAI /v1/responses)
  3. LLM이 도구를 요청하면 MCP 서버에 실행을 맡긴다.     (MCP: tools/call)
  4. 결과를 LLM에게 돌려주고, 최종 답변이 나올 때까지 반복한다.

LLM은 MCP의 존재를 모릅니다. LLM 입장에서는 그냥 function tool이고,
MCP는 "도구를 어디서 가져오고 누가 실행하는가"를 표준화한 클라이언트-서버 사이의 프로토콜입니다.

모든 통신은 mcp_debug.log 파일에 항상 기록됩니다. --debug 또는 /debug로 화면에도 출력할 수 있습니다.
'''
LLM_API_URL = "https://api.openai.com/v1/responses"
MODEL = "gpt-6-luna"
API_KEY = os.environ.get("OPENAI_API_KEY")
REASONING_EFFORT = "medium"

INSTRUCTIONS = """너는 MCP 서버의 도구를 활용하는 한국어 비서야.
- 계산, 시간, 날씨 질문에는 반드시 도구를 사용해.
- GitHub 저장소에 대한 질문은 deepwiki 도구로 조사해.
- 답변은 간결하게 해."""

MAX_STEPS = 15
# deepwiki 결과처럼 아주 긴 도구 결과는 잘라서 LLM에 보냅니다. (토큰 비용과 컨텍스트 한도 때문)
MAX_TOOL_OUTPUT_CHARS = 20000

BASE_DIR = Path(__file__).parent
LOG_PATH = BASE_DIR / "mcp_debug.log"

MCP_PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "raw-mcp-agent", "version": "1.0.0"}

'''
연결할 MCP 서버 목록입니다. agent.py의 MultiServerMCPClient 설정과 같은 모양입니다.
  - demo: SDK 없이 만든 raw_server.py를 하위 프로세스로 실행하고 stdin/stdout으로 통신합니다.
          "args"를 server.py로 바꾸면 FastMCP로 만든 서버에도 똑같이 연결됩니다. (프로토콜이 같기 때문)
  - deepwiki: 인터넷의 원격 MCP 서버에 HTTP로 접속합니다. (Streamable HTTP transport)
'''
SERVERS = {
    "demo": {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(BASE_DIR / "raw_server.py")],
    },
    "deepwiki": {
        "transport": "streamable_http",
        "url": "https://mcp.deepwiki.com/mcp",
    },
}


# ---------------------------------------------------------------------------
# 1. 통신 로깅
# ---------------------------------------------------------------------------

class CommLogger:
    '''
    모든 통신을 채널 이름과 함께 시간순으로 기록합니다. 채널은 이런 것들이 있습니다.
      [LLM HTTP]          OpenAI API와의 HTTP 요청/응답
      [MCP demo stdio]    demo 서버와 주고받은 JSON-RPC 메시지 (→ 보냄, ← 받음)
      [MCP demo stderr]   demo 서버가 stderr로 출력한 로그
      [MCP deepwiki]      deepwiki 서버와 주고받은 JSON-RPC 메시지
      [MCP deepwiki HTTP] deepwiki 서버와의 HTTP 요청/응답 헤더
    MCP 서버의 stderr는 별도 스레드에서 읽기 때문에, 파일 쓰기를 Lock으로 보호합니다.
    '''

    MAX_CONSOLE_CHARS = 3000

    def __init__(self, console=False):
        self.console = console
        self.lock = threading.Lock()
        self._write(f"\n\n########## 세션 시작 {datetime.now():%Y-%m-%d %H:%M:%S} ##########")

    def _write(self, text):
        with self.lock:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(text + "\n")

    def log(self, channel, text):
        entry = f"[{datetime.now():%H:%M:%S.%f}"[:-3] + f"] [{channel}] {text}"
        self._write(entry)
        if self.console:
            # 화면에서는 너무 긴 내용을 줄여서 보여주고, 파일에는 전체를 남깁니다.
            if len(entry) > self.MAX_CONSOLE_CHARS:
                entry = entry[:self.MAX_CONSOLE_CHARS] + f"\n...({len(entry)}자 중 화면 출력 생략, 전체는 {LOG_PATH.name} 참고)"
            print(entry)

    def echo(self, text):
        # 항상 화면에 보여줄 내용입니다. 로그 파일에도 남겨 전체 흐름을 이어서 볼 수 있게 합니다.
        print(text)
        self._write(text)


class HttpLogger:
    '''
    httpx의 event_hooks와 httpcore의 trace 확장으로 HTTP 통신을 기록합니다. (raw-llm 예제들과 같은 방식)
    log_bodies가 False이면 헤더만 기록합니다. MCP HTTP는 본문(JSON-RPC)을 MCP 채널에서 따로 기록하기 때문입니다.
    '''

    def __init__(self, logger, channel, log_bodies):
        self.logger = logger
        self.channel = channel
        self.log_bodies = log_bodies
        self.started_at = 0.0

    def hooks(self):
        return {"request": [self.on_request], "response": [self.on_response]}

    def elapsed_ms(self):
        return (time.perf_counter() - self.started_at) * 1000

    def on_request(self, request):
        self.started_at = time.perf_counter()
        request.extensions["trace"] = self.trace

        lines = [f">>> {request.method} {request.url} HTTP/1.1"]
        for name, value in request.headers.items():
            lines.append(f"    {name}: {mask_secret(name, value)}")
        if self.log_bodies and request.content:
            lines.append("")
            lines.append(pretty_json(request.content.decode("utf-8")))
        self.logger.log(self.channel, "\n".join(lines))

    def on_response(self, response):
        lines = [f"<<< {response.http_version} {response.status_code} {response.reason_phrase} (+{self.elapsed_ms():.0f}ms)"]
        for name, value in response.headers.items():
            lines.append(f"    {name}: {value}")
        self.logger.log(self.channel, "\n".join(lines))

    def log_body(self, text):
        if self.log_bodies:
            self.logger.log(self.channel, "<<< body\n" + pretty_json(text))

    def trace(self, event_name, info):
        if event_name == "connection.connect_tcp.started":
            self.logger.log(self.channel, f"trace +{self.elapsed_ms():.0f}ms TCP 연결 시작 -> {info['host']}:{info['port']}")
        elif event_name.endswith(".complete") or event_name.endswith(".failed"):
            step, result = event_name.rsplit(".", 1)
            self.logger.log(self.channel, f"trace +{self.elapsed_ms():.0f}ms {step} {result}")


def mask_secret(name, value):
    # 로그에 API 키가 그대로 남지 않도록 앞뒤 일부만 보여줍니다.
    if name.lower() == "authorization" and len(value) > 20:
        return f"{value[:14]}...{value[-4:]}"
    return value


def shorten_encrypted(data):
    # reasoning 아이템의 encrypted_content는 수천 자짜리라 로그에서만 앞부분만 보여줍니다.
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
# 2. MCP 클라이언트 (JSON-RPC 2.0)
# ---------------------------------------------------------------------------

class McpError(Exception):
    pass


class McpClient:
    '''
    transport(stdio, HTTP)와 상관없는 MCP 공통 로직입니다.
    하위 클래스는 _exchange(요청을 보내고 같은 id의 응답 받기)와 _send_notification만 구현합니다.
    '''

    def __init__(self, name, logger):
        self.name = name
        self.logger = logger
        self.next_id = 1
        self.server_info = {}

    def request(self, method, params=None):
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            message["params"] = params
        self.next_id += 1

        response = self._exchange(message)
        if "error" in response:
            raise McpError(f"{method} 실패: {response['error']}")
        return response["result"]

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send_notification(message)

    def initialize(self):
        '''
        MCP 연결은 항상 이 세 단계로 시작합니다. (핸드셰이크)
          1. 클라이언트 -> initialize 요청 (내 프로토콜 버전, 기능, 이름)
          2. 서버 -> initialize 응답 (서버가 고른 프로토콜 버전, 서버 기능, 이름)
          3. 클라이언트 -> notifications/initialized 알림 (준비 완료. 이제부터 다른 요청 가능)
        '''
        self.server_info = self.request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self.notify("notifications/initialized")
        return self.server_info

    def list_tools(self):
        # 도구가 많으면 서버가 여러 페이지로 나눠 보냅니다. nextCursor가 없을 때까지 이어서 요청합니다.
        tools, cursor = [], None
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else None)
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, tool_name, arguments):
        return self.request("tools/call", {"name": tool_name, "arguments": arguments})

    def handle_server_message(self, message, waiting_id):
        '''
        서버가 보낸 메시지가 지금 기다리는 응답인지 판별합니다. 응답이 아니면 None을 돌려줍니다.
        MCP는 양방향이라 서버도 클라이언트에게 요청(예: sampling, roots/list)이나 알림(예: 로그, 진행률)을 보낼 수 있습니다.
        이 클라이언트는 initialize에서 아무 기능(capabilities)도 선언하지 않았으므로, 서버의 요청에는 "지원 안 함"으로 답합니다.
        '''
        if "method" in message:
            if "id" in message:
                self._reply_error(message["id"], -32601, f"Method not supported by client: {message['method']}")
            return None
        if message.get("id") == waiting_id:
            return message
        return None

    def _reply_error(self, request_id, code, text):
        raise NotImplementedError

    def close(self):
        pass


class StdioMcpClient(McpClient):
    '''
    stdio transport: MCP 서버를 하위 프로세스로 실행하고, 파이프로 한 줄에 JSON 메시지 하나씩 주고받습니다.
    stdout을 읽는 일은 별도 스레드가 맡아 큐에 넣습니다. 그래야 응답이 늦어질 때 타임아웃을 걸 수 있고,
    stderr도 동시에 읽을 수 있습니다. (stderr를 읽지 않으면 파이프 버퍼가 가득 차서 서버가 멈출 수 있습니다)
    '''

    def __init__(self, name, command, args, logger):
        super().__init__(name, logger)
        self.channel = f"MCP {name} stdio"
        self.logger.log(self.channel, f"프로세스 실행: {command} {' '.join(args)}")
        # 텍스트 모드 대신 바이트 모드로 열어, UTF-8 인코딩과 \n 줄바꿈을 직접 제어합니다.
        self.process = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        self.inbox = queue.Queue()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for raw_line in self.process.stdout:
            self.inbox.put(raw_line.decode("utf-8"))
        self.inbox.put(None)

    def _read_stderr(self):
        for raw_line in self.process.stderr:
            self.logger.log(f"MCP {self.name} stderr", raw_line.decode("utf-8", errors="replace").rstrip())

    def _write(self, message):
        line = json.dumps(message, ensure_ascii=False)
        self.logger.log(self.channel, f"→ {line}")
        self.process.stdin.write((line + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def _send_notification(self, message):
        self._write(message)

    def _reply_error(self, request_id, code, text):
        self._write({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": text}})

    def _exchange(self, message, timeout=60):
        self._write(message)
        while True:
            try:
                line = self.inbox.get(timeout=timeout)
            except queue.Empty:
                raise McpError(f"{self.name} 서버가 {timeout}초 동안 응답하지 않았습니다.")
            if line is None:
                raise McpError(f"{self.name} 서버 프로세스가 종료되었습니다. (exit code {self.process.poll()})")

            self.logger.log(self.channel, f"← {line.rstrip()}")
            response = self.handle_server_message(json.loads(line), message["id"])
            if response is not None:
                return response

    def close(self):
        # stdin을 닫으면 서버의 읽기 루프가 끝나면서 스스로 종료합니다. 끝나지 않으면 강제로 종료합니다.
        try:
            self.process.stdin.close()
            self.process.wait(timeout=5)
        except Exception:
            self.process.kill()
        self.logger.log(self.channel, f"프로세스 종료 (exit code {self.process.poll()})")


class HttpMcpClient(McpClient):
    '''
    Streamable HTTP transport: 모든 JSON-RPC 메시지를 하나의 URL로 POST합니다.
      - 요청 헤더 Accept에 application/json과 text/event-stream을 모두 적어야 합니다.
        서버는 둘 중 하나로 응답합니다. (JSON 한 덩어리, 또는 SSE 스트림)
      - initialize 응답 헤더에 Mcp-Session-Id가 오면, 이후 모든 요청에 그 값을 다시 담아 보냅니다.
        HTTP는 요청마다 독립적이라, 서버가 이 값으로 같은 세션인지 알아봅니다.
      - 알림(notification)에는 본문 없이 202 Accepted로 응답합니다.
    '''

    def __init__(self, name, url, logger):
        super().__init__(name, logger)
        self.url = url
        self.channel = f"MCP {name}"
        self.session_id = None
        self.protocol_version = None
        self.http = httpx.Client(timeout=120, event_hooks=HttpLogger(logger, f"MCP {name} HTTP", log_bodies=False).hooks())

    def _headers(self):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    def _post(self, message):
        line = json.dumps(message, ensure_ascii=False)
        self.logger.log(self.channel, f"→ {line}")

        received = []
        with self.http.stream("POST", self.url, headers=self._headers(), content=line.encode("utf-8")) as response:
            if response.headers.get("mcp-session-id"):
                self.session_id = response.headers["mcp-session-id"]

            if response.status_code == 202:
                return received
            if response.status_code >= 400:
                response.read()
                raise McpError(f"HTTP {response.status_code}: {response.text[:500]}")

            if "text/event-stream" in response.headers.get("content-type", ""):
                # SSE 응답: "data: {...}" 줄마다 JSON-RPC 메시지가 하나씩 들어 있습니다.
                for sse_line in response.iter_lines():
                    if not sse_line:
                        continue
                    self.logger.log(self.channel, f"← (SSE) {sse_line}")
                    if sse_line.startswith("data:"):
                        received.append(json.loads(sse_line[len("data:"):].strip()))
            else:
                body = response.read().decode("utf-8")
                self.logger.log(self.channel, f"← {body}")
                received.append(json.loads(body))
        return received

    def _send_notification(self, message):
        self._post(message)

    def _reply_error(self, request_id, code, text):
        self._post({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": text}})

    def _exchange(self, message):
        for received in self._post(message):
            response = self.handle_server_message(received, message["id"])
            if response is not None:
                if message["method"] == "initialize" and "result" in response:
                    self.protocol_version = response["result"].get("protocolVersion")
                return response
        raise McpError(f"{self.name} 서버 응답에 id {message['id']}가 없습니다.")

    def close(self):
        # 세션을 명시적으로 끝냅니다. 서버가 지원하지 않으면 405를 돌려주는데, 그래도 괜찮습니다.
        if self.session_id:
            try:
                self.http.delete(self.url, headers=self._headers())
            except httpx.HTTPError:
                pass
        self.http.close()


def connect_servers(logger):
    clients = {}
    for name, config in SERVERS.items():
        try:
            if config["transport"] == "stdio":
                client = StdioMcpClient(name, config["command"], config["args"], logger)
            else:
                client = HttpMcpClient(name, config["url"], logger)
            info = client.initialize()
            clients[name] = client
            server = info.get("serverInfo", {})
            logger.echo(f"  [MCP 연결] {name} ({config['transport']}): {server.get('name')} {server.get('version')}, 프로토콜 {info.get('protocolVersion')}")
        except Exception as e:
            # 서버 하나가 실패해도 나머지 서버로 계속 진행합니다. (예: 인터넷이 안 될 때 deepwiki)
            logger.echo(f"  [MCP 연결 실패] {name}: {e}")
    return clients


# ---------------------------------------------------------------------------
# 3. MCP 도구 -> LLM 도구 변환
# ---------------------------------------------------------------------------

def build_llm_tools(clients, logger):
    '''
    MCP 도구 정의 {"name", "description", "inputSchema"}를 /v1/responses의 function tool 형식으로 바꿉니다.
    inputSchema가 이미 JSON Schema라서 parameters에 그대로 넣으면 됩니다.

    여러 서버에 같은 이름의 도구가 있을 수 있으므로 "서버이름__도구이름"으로 이름을 붙이고,
    LLM이 이 이름으로 호출하면 어느 서버의 어떤 도구인지 tool_index에서 찾습니다.
    strict는 false로 둡니다. MCP 서버의 스키마가 strict 모드의 규칙(모든 속성 required 등)을 지킨다는 보장이 없기 때문입니다.
    '''
    llm_tools, tool_index = [], {}
    for server_name, client in clients.items():
        for tool in client.list_tools():
            # function 이름에는 영문, 숫자, _, - 만 쓸 수 있고 최대 64자입니다.
            llm_name = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{server_name}__{tool['name']}")[:64]
            tool_index[llm_name] = (client, tool["name"])
            llm_tools.append({
                "type": "function",
                "name": llm_name,
                "description": tool.get("description") or "",
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
                "strict": False,
            })
        logger.echo(f"  [MCP 도구] {server_name}: {', '.join(name for name, (c, _) in tool_index.items() if c is client)}")
    return llm_tools, tool_index


def call_mcp_tool(tool_index, logger, call):
    '''
    LLM의 function_call을 MCP tools/call로 바꿔서 실행하고, 결과를 LLM에 보낼 문자열로 만듭니다.
    MCP 결과의 content는 여러 조각(text, image 등)의 배열입니다. 이 예제는 text만 이어 붙입니다.
    '''
    try:
        client, tool_name = tool_index[call["name"]]
        arguments = json.loads(call["arguments"] or "{}")
        result = client.call_tool(tool_name, arguments)

        parts = []
        for content in result.get("content", []):
            if content.get("type") == "text":
                parts.append(content["text"])
            else:
                parts.append(f"[{content.get('type')} 콘텐츠 생략]")
        output = "\n".join(parts)
        if result.get("isError"):
            output = f"[도구 실행 에러] {output}"
    except Exception as e:
        output = f"[도구 호출 실패] {type(e).__name__}: {e}"

    if len(output) > MAX_TOOL_OUTPUT_CHARS:
        output = output[:MAX_TOOL_OUTPUT_CHARS] + f"\n...(전체 {len(output)}자 중 {MAX_TOOL_OUTPUT_CHARS}자만 전달)"

    preview = output.replace("\n", " ")
    if len(preview) > 150:
        preview = preview[:150] + f"...({len(output)}자)"
    logger.echo(f"  [도구 실행] {call['name']}({call['arguments'][:100]}) -> {preview}")
    return output


# ---------------------------------------------------------------------------
# 4. LLM 요청과 에이전트 루프 (raw-llm/agent 예제와 같은 구조)
# ---------------------------------------------------------------------------

def request_llm(client, http_logger, llm_tools, input_items):
    body = {
        "model": MODEL,
        "instructions": INSTRUCTIONS,
        "input": input_items,
        "tools": llm_tools,
        "reasoning": {"effort": REASONING_EFFORT, "summary": "auto"},
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    response = client.post(
        LLM_API_URL,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json=body,
    )
    http_logger.log_body(response.text)

    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}\n{response.text}")
    return response.json()


def message_text(item):
    return "".join(part.get("text", "") for part in item.get("content", []) if part.get("type") == "output_text")


def run_agent(llm_client, http_logger, logger, llm_tools, tool_index, input_items):
    for step in range(1, MAX_STEPS + 1):
        data = request_llm(llm_client, http_logger, llm_tools, input_items)
        output = data.get("output", [])

        usage = data.get("usage", {})
        reasoning_tokens = usage.get("output_tokens_details", {}).get("reasoning_tokens")
        logger.echo(
            f"\n  (LLM 요청 {step}: 입력 토큰 {usage.get('input_tokens')} / 출력 토큰 {usage.get('output_tokens')}"
            f", 그중 추론 {reasoning_tokens})"
        )

        # 응답의 output을 reasoning 아이템까지 그대로 input에 이어 붙여야 모델이 앞의 생각을 이어 갑니다.
        input_items.extend(output)

        if data.get("status") != "completed":
            return f"(응답이 완료되지 않았습니다: {data.get('status')} {data.get('incomplete_details')})"

        calls, final_text = [], ""
        for item in output:
            if item["type"] == "reasoning":
                for part in item.get("summary", []):
                    logger.echo(f"  [생각] {part['text']}")
            elif item["type"] == "function_call":
                calls.append(item)
            elif item["type"] == "message":
                final_text += message_text(item)

        if not calls:
            return final_text
        if final_text:
            logger.echo(f"  [모델] {final_text}")

        for call in calls:
            input_items.append({
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": call_mcp_tool(tool_index, logger, call),
            })

    return f"(도구 호출이 {MAX_STEPS}번을 넘어 중단했습니다.)"


def print_help():
    print("명령어: /debug (통신 로그 화면 출력 on/off. 파일에는 항상 기록)  /tools (도구 목록)")
    print("        /history (input 아이템 보기)  /reset (대화 초기화)  /exit (종료)")
    print("예시 질문: 지금 몇 시야? 그리고 서울 날씨 알려주고, (12 + 30) * 3 도 계산해줘.")
    print("           DeepWiki로 langchain-ai/langgraph 저장소의 checkpointer가 무슨 역할인지 알려줘.")


def main():
    if not API_KEY:
        print("OPENAI_API_KEY 환경 변수가 없습니다. .env 파일에 OPENAI_API_KEY=sk-... 를 추가하세요.")
        sys.exit(1)

    logger = CommLogger(console="--debug" in sys.argv)
    print(f"모델: {MODEL} (추론: {REASONING_EFFORT})  통신 로그: {LOG_PATH}")

    clients = connect_servers(logger)
    llm_http_logger = HttpLogger(logger, "LLM HTTP", log_bodies=True)
    llm_client = httpx.Client(timeout=300, event_hooks=llm_http_logger.hooks())

    try:
        llm_tools, tool_index = build_llm_tools(clients, logger)
        print_help()
        input_items = []

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
                logger.console = not logger.console
                print(f"통신 로그 화면 출력: {'ON' if logger.console else 'OFF'}")
                continue
            if user_input == "/tools":
                for tool in llm_tools:
                    print(f"  {tool['name']}: {tool['description']}")
                continue
            if user_input == "/history":
                print(json.dumps(shorten_encrypted(input_items), ensure_ascii=False, indent=2))
                continue
            if user_input == "/reset":
                input_items = []
                print("대화를 초기화했습니다.")
                continue

            logger.echo(f"\n[You] {user_input}")
            turn_start = len(input_items)
            input_items.append({"role": "user", "content": user_input})

            try:
                answer = run_agent(llm_client, llm_http_logger, logger, llm_tools, tool_index, input_items)
            except (RuntimeError, httpx.HTTPError) as e:
                print(f"[요청 실패] {e}")
                del input_items[turn_start:]
                continue

            logger.echo(f"\nAI: {answer}")
    finally:
        llm_client.close()
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    main()
