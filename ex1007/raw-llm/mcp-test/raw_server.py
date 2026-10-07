import json
import sys
from datetime import datetime


'''
MCP SDK(FastMCP) 없이 표준 입출력만으로 만든 MCP 서버입니다. server.py와 같은 도구를 제공합니다.

MCP의 stdio transport 규칙은 단순합니다.
  - 클라이언트가 이 프로그램을 하위 프로세스로 실행한다.
  - 클라이언트 -> 서버: stdin으로 JSON-RPC 메시지를 한 줄에 하나씩 보낸다.
  - 서버 -> 클라이언트: stdout으로 JSON-RPC 메시지를 한 줄에 하나씩 보낸다.
  - stdout은 프로토콜 전용이다. 로그는 반드시 stderr로 출력해야 한다.
    (stdout에 print 한 줄만 섞여도 클라이언트는 그 줄을 JSON으로 해석하려다 실패합니다)

JSON-RPC 2.0 메시지는 세 종류입니다.
  - 요청(request):      {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {...}}  -> 응답 필요
  - 응답(response):     {"jsonrpc": "2.0", "id": 1, "result": {...}}  또는  {"jsonrpc": "2.0", "id": 1, "error": {...}}
  - 알림(notification): {"jsonrpc": "2.0", "method": "notifications/initialized"}  -> id가 없고 응답하지 않음
'''

# 지원하는 프로토콜 버전입니다. 클라이언트가 요청한 버전을 지원하면 그대로, 아니면 가장 최신 버전으로 답합니다.
SUPPORTED_PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
SERVER_INFO = {"name": "raw-demo", "version": "1.0.0"}


def log(message):
    print(f"[raw_server] {message}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# 도구 정의
# ---------------------------------------------------------------------------

def add(a, b):
    return a + b


def multiply(a, b):
    return a * b


def get_current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_weather(city):
    fake_weather = {
        "서울": "맑음, 18°C",
        "부산": "흐림, 21°C",
        "제주": "비, 19°C",
    }
    return fake_weather.get(city, f"{city}의 날씨 정보가 없습니다.")


'''
FastMCP는 함수의 타입 힌트와 docstring을 읽어 아래 정보를 자동으로 만들어 줍니다.
SDK 없이 만들 때는 이름, 설명, 입력 JSON Schema(inputSchema)를 직접 적어야 합니다.
'''
TOOLS = {
    "add": {
        "description": "두 정수를 더합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
        "function": add,
    },
    "multiply": {
        "description": "두 정수를 곱합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
        "function": multiply,
    },
    "get_current_time": {
        "description": "현재 날짜와 시간을 'YYYY-MM-DD HH:MM:SS' 형식으로 반환합니다.",
        "inputSchema": {"type": "object", "properties": {}},
        "function": get_current_time,
    },
    "get_weather": {
        "description": "도시 이름을 받아 해당 도시의 날씨를 반환합니다. (예제용 가짜 데이터)",
        "inputSchema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        "function": get_weather,
    },
}


# ---------------------------------------------------------------------------
# JSON-RPC 메시지 처리
# ---------------------------------------------------------------------------

class JsonRpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def handle_initialize(params):
    '''
    연결 직후 클라이언트가 가장 먼저 보내는 요청입니다. 서로의 프로토콜 버전과 기능(capabilities)을 맞춥니다.
    capabilities에 "tools"가 있어야 클라이언트가 이 서버에 도구가 있다는 것을 압니다.
    '''
    requested = params.get("protocolVersion")
    version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
    client_info = params.get("clientInfo", {})
    log(f"initialize: client={client_info.get('name')} requested={requested} -> {version}")
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {}},
        "serverInfo": SERVER_INFO,
    }


def handle_tools_list(params):
    return {
        "tools": [
            {"name": name, "description": tool["description"], "inputSchema": tool["inputSchema"]}
            for name, tool in TOOLS.items()
        ]
    }


def handle_tools_call(params):
    '''
    에러를 돌려주는 방법이 두 가지라는 점이 중요합니다.
      - 없는 도구 이름: 프로토콜 수준의 잘못이라 JSON-RPC error로 응답합니다.
      - 도구 실행 중 에러: result의 isError를 true로 두고 에러 내용을 content에 담습니다.
        그래야 클라이언트가 에러 내용을 LLM에게 전달하고, LLM이 다른 방법을 시도할 수 있습니다.
    '''
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name not in TOOLS:
        raise JsonRpcError(-32602, f"Unknown tool: {name}")

    log(f"tools/call: {name}({arguments})")
    try:
        value = TOOLS[name]["function"](**arguments)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    return {"content": [{"type": "text", "text": str(value)}], "isError": False}


HANDLERS = {
    "initialize": handle_initialize,
    "ping": lambda params: {},
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
}


def handle_message(message):
    method = message.get("method")

    # id가 없으면 알림입니다. 응답하지 않습니다.
    if "id" not in message:
        log(f"notification: {method}")
        return None

    try:
        if method not in HANDLERS:
            raise JsonRpcError(-32601, f"Method not found: {method}")
        result = HANDLERS[method](message.get("params") or {})
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}
    except JsonRpcError as e:
        return {"jsonrpc": "2.0", "id": message["id"], "error": {"code": e.code, "message": e.message}}


def send(message):
    # ensure_ascii=False로 한글을 그대로 보내고, 줄바꿈 문자 하나로 메시지의 끝을 표시합니다.
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    # Windows의 기본 인코딩(cp949)과 줄바꿈(\r\n) 변환을 피하기 위해 UTF-8과 \n으로 고정합니다.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    log("started (stdio)")

    # 클라이언트가 stdin을 닫으면 for 루프가 끝나고 서버도 종료됩니다.
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue

        response = handle_message(message)
        if response is not None:
            send(response)

    log("stdin closed, exiting")


if __name__ == "__main__":
    main()
