# raw-llm tool calling

OpenAI SDK 없이 HTTP 요청(httpx)만으로 tool calling을 구현한 예제입니다.
모델 `gpt-6-luna`에 도구 3개(`get_current_time`, `calculate`, `get_weather`)를 주고, 모델이 요청한 도구를 직접 실행해 결과를 돌려줍니다.

## 실행

```powershell
cd ex1007\raw-llm\tool_calling
uv run python agent.py           # 기본
uv run python agent.py --debug   # HTTP 통신 로그를 켠 상태로 시작
```

| 명령어 | 설명 |
| --- | --- |
| `/debug` | HTTP 통신 로그 on/off (화면 출력 + `http_debug.log` 파일 기록) |
| `/history` | 지금까지 쌓인 `messages` 배열 출력 (tool 메시지 포함) |
| `/reset` | 대화 초기화 |
| `/exit` | 종료 |

## 통신 흐름

질문 하나에 HTTP 요청이 **최소 두 번** 오갑니다.

```
You: 서울이랑 부산 날씨 알려줘

[요청 1]  messages = [system, user]  +  tools = [...도구 설명서...]
[응답 1]  finish_reason: "tool_calls"
          message.tool_calls = [
            {"id": "call_A", "function": {"name": "get_weather", "arguments": "{\"city\": \"서울\"}"}},
            {"id": "call_B", "function": {"name": "get_weather", "arguments": "{\"city\": \"부산\"}"}}
          ]

          ← 클라이언트(agent.py)가 get_weather를 두 번 직접 실행

[요청 2]  messages = [system, user,
                      assistant(tool_calls),
                      tool(call_A 결과), tool(call_B 결과)]  +  tools
[응답 2]  finish_reason: "stop"
          message.content = "서울은 맑음 18°C, 부산은 흐림 21°C입니다."
```

## 핵심 포인트

- **모델은 함수를 실행하지 않습니다.** "이 함수를 이 인자로 불러 달라"는 JSON을 돌려줄 뿐이고, 실행은 클라이언트가 합니다.
- **모델이 보는 것은 `TOOLS`의 JSON 설명서뿐입니다.** 파이썬 코드는 보지 못합니다. `description`이 도구 선택의 근거가 됩니다.
- **`arguments`는 JSON 문자열입니다.** 객체가 아니므로 `json.loads`로 풀어야 합니다. 모델이 만든 값이므로 검증 없이 `eval` 같은 곳에 넣으면 위험합니다. (`calculate`는 AST로 숫자와 연산자만 허용합니다)
- **`tool_call_id`로 결과와 호출의 짝을 맞춥니다.** tool_calls가 담긴 assistant 메시지를 기록에서 빠뜨리면 HTTP 400 에러가 납니다.
- **도구 에러도 결과로 돌려줍니다.** `대구 날씨는?`처럼 실패해도 에러 내용을 tool 메시지로 넣어 주면, 모델이 상황을 이해하고 답변합니다.
- **토큰이 빨리 늘어납니다.** 매 요청마다 tools 설명서와 도구 결과까지 전부 다시 보내기 때문입니다. 실행 중 출력되는 `(요청 N: 입력 토큰 ...)`에서 확인할 수 있습니다.

## 참고: `reasoning_effort: "none"`

`gpt-6-luna`는 `/v1/chat/completions`에서 추론(reasoning)과 function tools를 함께 쓸 수 없습니다. 이 옵션을 빼면 이런 에러가 납니다.

```
HTTP 400  "Function tools with reasoning_effort are not supported for gpt-6-luna in /v1/chat/completions.
           To use function tools, use /v1/responses or set reasoning_effort to 'none'."
```

이 예제는 chatbot 예제와 같은 엔드포인트와 메시지 형식을 유지하려고 추론을 껐습니다. 추론까지 쓰려면 `/v1/responses` 엔드포인트를 사용해야 합니다.

## 디버그 모드

chatbot 예제와 같은 방식으로 HTTP 요청/응답의 헤더와 본문, 연결 단계별 시각을 기록합니다. API 키는 `sk-proj...XJgA`처럼 일부만 남깁니다. 같은 내용이 `http_debug.log`에도 쌓이고, 이 파일은 `.gitignore`의 `*.log` 규칙 때문에 커밋되지 않습니다.
도구 실행 줄도 로그 파일에 같이 남아서, 질문 하나의 흐름을 처음부터 끝까지 이어서 볼 수 있습니다.

```
===== >>> HTTP REQUEST =====              ← 요청 1: messages + tools
[trace +    1ms] TCP 연결 시작 -> api.openai.com:443
[trace +   38ms] connection.start_tls complete
[trace + 3374ms] http11.receive_response_headers complete
===== <<< HTTP RESPONSE =====
{ ... "tool_calls": [...], "finish_reason": "tool_calls" }
  [도구 실행] get_weather({"city": "서울"}) -> {...}
  [도구 실행] get_weather({"city": "부산"}) -> {...}

===== >>> HTTP REQUEST =====              ← 요청 2: messages에 assistant(tool_calls) + tool 결과 추가
[trace +    2ms] http11.send_request_headers complete    ← TCP/TLS 단계 없음 (연결 재사용)
[trace + 2067ms] http11.receive_response_headers complete
===== <<< HTTP RESPONSE =====
{ ... "content": "서울은 맑고 ...", "finish_reason": "stop" }
AI: 서울은 맑고 18°C, 부산은 흐리고 21°C예요.
```

두 요청의 본문을 비교해 보면, 두 번째 요청에서 `messages`가 어떻게 늘어났는지 확인할 수 있습니다.
