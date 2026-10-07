# raw-llm chatbot

OpenAI SDK 없이 HTTP 요청(httpx)만으로 `gpt-6-luna`와 대화하는 챗봇입니다.
LLM 서버와 실제로 어떤 데이터를 주고받는지 확인하는 것이 목적입니다.

## 실행

```powershell
cd ex1007\raw-llm\chatbot
uv run python chatbot.py
```

`OPENAI_API_KEY`가 환경 변수나 `.env` 파일에 있어야 합니다.
처음부터 디버그 모드로 시작하려면 `--debug`를 붙입니다.

```powershell
uv run python chatbot.py --debug
```

## 명령어

| 명령어 | 설명 |
| --- | --- |
| `/debug` | HTTP 통신 로그 on/off (화면 출력 + `http_debug.log` 파일 기록) |
| `/stream` | 스트리밍 모드 on/off (기본값 ON) |
| `/history` | 서버로 보내는 `messages` 배열 출력 |
| `/reset` | 대화 초기화 |
| `/exit` | 종료 |

## 통신 흐름

```
POST https://api.openai.com/v1/chat/completions
Authorization: Bearer sk-...
Content-Type: application/json

{
  "model": "gpt-6-luna",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "안녕?"},
    {"role": "assistant", "content": "안녕하세요!"},
    {"role": "user", "content": "내가 방금 뭐라고 했지?"}
  ],
  "stream": true
}
```

- **서버는 대화를 기억하지 않습니다(stateless).** 매 요청마다 전체 대화 기록을 다시 보냅니다. 그래서 대화가 길어질수록 입력 토큰이 늘어납니다.
- **non-stream**: 답변이 완성된 뒤 JSON 하나로 응답합니다. 답변 위치는 `choices[0].message.content`입니다.
- **stream**: SSE 형식으로 `data: {...}` 줄이 계속 옵니다. 각 줄의 `choices[0].delta.content` 조각을 이어 붙이고, `data: [DONE]`이 오면 끝납니다.

`/debug`를 켜고 같은 질문을 `/stream` ON과 OFF로 각각 보내 보면 두 방식의 차이를 직접 확인할 수 있습니다.

## 디버그 모드

`/debug`를 켜면 요청 하나마다 아래 순서로 로그가 찍힙니다. 같은 내용이 `http_debug.log`에도 쌓입니다. 이 파일은 `.gitignore`의 `*.log` 규칙 때문에 커밋되지 않습니다.

```
===== >>> HTTP REQUEST =====          ← 요청 줄, 헤더, JSON 본문 (API 키는 앞뒤 일부만 표시)
[trace +    1ms] TCP 연결 시작 -> api.openai.com:443
[trace +   37ms] connection.connect_tcp complete     ← TCP 연결
[trace +   54ms] connection.start_tls complete       ← TLS(HTTPS) 핸드셰이크
[trace +   56ms] http11.send_request_body complete   ← 요청 전송 끝
[trace + 1288ms] http11.receive_response_headers complete   ← 모델이 생각하는 시간
===== <<< HTTP RESPONSE =====          ← 상태 줄, 응답 헤더
[+ 1290ms] data: {...}                 ← (stream) SSE 줄을 받은 시각과 원본
[trace + 1348ms] http11.receive_response_body complete
```

볼 만한 것들:

- **연결 재사용(keep-alive)**: 두 번째 요청부터는 `connect_tcp`와 `start_tls` 단계가 없습니다. 이미 열린 연결을 그대로 쓰기 때문입니다.
- **스트리밍과 일반 요청의 차이**: 스트리밍은 응답 헤더가 먼저 오고(`content-type: text/event-stream`), 본문 조각이 시간차를 두고 들어옵니다. 일반 요청은 헤더(`content-type: application/json`)가 오기까지 오래 걸리고, 본문은 한 번에 옵니다.
- **응답 헤더**: `openai-processing-ms`(서버 처리 시간), `x-ratelimit-remaining-*`(남은 요청/토큰 한도), `x-request-id`(문의할 때 쓰는 요청 ID), `content-encoding: gzip`(압축 전송. 압축은 httpx가 자동으로 풉니다).
