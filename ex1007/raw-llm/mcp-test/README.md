# mcp-test

| 파일 | 설명 |
| --- | --- |
| `server.py` | FastMCP(SDK)로 만든 MCP 서버 |
| `agent.py` | langchain-mcp-adapters(SDK)로 `server.py`에 연결하는 에이전트 |
| `existing_mcp_agent.py` | 공개 MCP 서버(time, fetch, deepwiki)에 연결하는 에이전트 (SDK) |
| **`raw_server.py`** | SDK 없이 stdin/stdout JSON-RPC로 직접 만든 MCP 서버 (`server.py`와 같은 도구) |
| **`raw_agent.py`** | SDK 없이 만든 MCP 클라이언트 + AI 에이전트. 모든 통신을 `mcp_debug.log`에 기록 |

## raw_agent.py 실행

```powershell
cd ex1007\mcp-test
uv run python raw_agent.py           # 통신 로그는 파일에만 기록
uv run python raw_agent.py --debug   # 통신 로그를 화면에도 출력
```

| 명령어 | 설명 |
| --- | --- |
| `/debug` | 통신 로그 화면 출력 on/off (파일에는 항상 기록) |
| `/tools` | LLM에 전달된 도구 목록 |
| `/history` | 지금까지 쌓인 `input` 아이템 |
| `/reset` | 대화 초기화 |
| `/exit` | 종료 |

연결하는 서버는 `raw_agent.py`의 `SERVERS`에서 바꿉니다.
- `demo`: `raw_server.py`를 하위 프로세스로 실행합니다(stdio). `args`를 `server.py`로 바꿔도 똑같이 동작합니다. SDK로 만든 서버든 아니든 프로토콜이 같기 때문입니다.
- `deepwiki`: 원격 서버 `https://mcp.deepwiki.com/mcp`에 HTTP로 접속합니다(Streamable HTTP). 연결에 실패하면 이 서버만 빼고 계속 진행합니다.

## 전체 구조

```
                 OpenAI /v1/responses (HTTPS)
        ┌──────────────────────────────────────┐
        │              [LLM HTTP]              │
        ▼                                      │
   raw_agent.py ──── MCP JSON-RPC ────┬── raw_server.py   (stdio: 하위 프로세스의 stdin/stdout)
   (MCP 클라이언트)                    │     [MCP demo stdio] [MCP demo stderr]
                                      │
                                      └── mcp.deepwiki.com (Streamable HTTP: POST + SSE)
                                            [MCP deepwiki] [MCP deepwiki HTTP]
```

LLM은 MCP를 모릅니다. LLM에게는 그냥 function tool로 보입니다. MCP는 **에이전트(클라이언트)와 도구 서버 사이**의 프로토콜입니다.

## 통신 흐름

### 1. 연결 (핸드셰이크)

```
→ {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{...}}}
← {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{}},"serverInfo":{...}}}
→ {"jsonrpc":"2.0","method":"notifications/initialized"}       ← id가 없음 = 알림, 응답하지 않음
```

### 2. 도구 목록 → LLM 도구로 변환

```
→ {"jsonrpc":"2.0","id":2,"method":"tools/list"}
← {"result":{"tools":[{"name":"get_weather","description":"...","inputSchema":{...JSON Schema...}}]}}
```

MCP의 `inputSchema`는 이미 JSON Schema라서 LLM 도구의 `parameters`에 그대로 넣습니다. 서버끼리 이름이 겹치지 않도록 `demo__get_weather`처럼 서버 이름을 앞에 붙입니다.

### 3. 질문 하나 처리

```
[LLM HTTP]       요청 1 → 응답: function_call demo__get_weather({"city":"서울"})
[MCP demo stdio] → {"id":3,"method":"tools/call","params":{"name":"get_weather","arguments":{"city":"서울"}}}
[MCP demo stdio] ← {"id":3,"result":{"content":[{"type":"text","text":"맑음, 18°C"}],"isError":false}}
[LLM HTTP]       요청 2 (function_call_output 추가) → 응답: 최종 답변
```

## stdio와 Streamable HTTP의 차이

| | stdio | Streamable HTTP |
| --- | --- | --- |
| 서버 위치 | 내 컴퓨터의 하위 프로세스 | 원격 URL |
| 메시지 전달 | stdin/stdout에 **한 줄에 JSON 하나** | 모든 메시지를 같은 URL로 POST |
| 응답 형식 | stdout의 한 줄 | `application/json` 또는 `text/event-stream`(SSE) |
| 알림 전송 | 한 줄 쓰기 | POST → `202 Accepted` (본문 없음) |
| 서버 로그 | stderr (stdout은 프로토콜 전용) | 서버 쪽에 남음. `notifications/message`로 보내 주기도 함 |
| 세션 | 프로세스 하나 = 세션 하나 | `Mcp-Session-Id` 헤더 (DeepWiki는 발급하지 않음) |

## 로그에서 볼 만한 것

- **`[MCP demo stderr]`**: 서버는 로그를 stderr로만 출력합니다. stdout에 `print` 한 줄만 섞여도 클라이언트가 그 줄을 JSON으로 해석하려다 실패합니다.
- **DeepWiki의 SSE 응답**: `tools/call`의 응답 헤더는 0.5초 만에 오지만, 결과는 15초쯤 뒤에 같은 스트림으로 옵니다. 그 사이에 `: ping` 줄(연결 유지용)과 `notifications/message`(서버의 진행 로그)가 끼어 옵니다.
- **에러 두 종류**: 없는 도구를 부르면 JSON-RPC `error`로 응답합니다. 도구 실행 중 에러는 `result`의 `"isError": true`로 응답하고, 이 내용은 LLM에게 전달되어 LLM이 대응합니다.
- **FastMCP 응답과의 차이**: `server.py`(FastMCP)는 `content` 외에 `structuredContent`(구조화된 결과)도 보냅니다. `raw_server.py`는 `content`만 보냅니다. 둘 다 프로토콜에 맞는 응답입니다.

API 키는 로그에 앞뒤 일부만 남습니다. `mcp_debug.log`는 `.gitignore`의 `*.log` 규칙 때문에 커밋되지 않습니다.
