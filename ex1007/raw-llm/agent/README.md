# raw-llm agent

OpenAI SDK 없이 HTTP 요청(httpx)만으로 만든 파일 작업 AI 에이전트입니다.
`workspace/` 폴더 안의 파일을 읽고, 계산하고, 결과물을 파일로 저장합니다.

## 실행

```powershell
cd ex1007\raw-llm\agent
uv run python agent.py           # 기본
uv run python agent.py --debug   # HTTP 통신 로그를 켠 상태로 시작
```

예시 작업: `memo.txt의 요청대로 보고서를 만들어줘`
→ 에이전트가 `memo.txt`와 `sales.csv`를 읽고 매출을 계산해서 `workspace/reports/q3_report.md`를 만듭니다.

| 명령어 | 설명 |
| --- | --- |
| `/debug` | HTTP 통신 로그 on/off (화면 출력 + `http_debug.log` 파일 기록) |
| `/history` | 지금까지 쌓인 `input` 아이템 출력 |
| `/reset` | 대화 초기화 |
| `/exit` | 종료 |

## 도구

| 도구 | 설명 |
| --- | --- |
| `list_files` | workspace 안의 파일 목록 |
| `read_file` | 텍스트 파일 읽기 (최대 20,000자) |
| `write_file` | 파일 저장. **실행 전에 미리보기를 보여주고 y/n 승인을 받음** |
| `calculate` | 사칙연산 (AST로 숫자와 연산자만 허용, `eval` 사용 안 함) |

모든 파일 경로는 `workspace/` 기준이며, `../agent.py`나 `C:/Windows/...`처럼 밖을 가리키는 경로는 거부합니다.

## tool_calling 예제와 다른 점

반복문 구조는 같습니다. 차이는 모델이 **스스로 계획을 세우고 여러 단계를 이어 간다**는 점입니다.

```
You: memo.txt의 요청대로 보고서를 만들어줘

(요청 1) list_files(".")                         ← 어떤 파일이 있는지 먼저 확인
(요청 2) read_file("memo.txt")                   ← 요구사항 파악
(요청 3) read_file("sales.csv")                  ← memo에서 알게 된 데이터 파일 읽기
(요청 4) calculate(...) x 8                       ← 지역별/월별 매출 계산
(요청 5) calculate(...) x 6                       ← 앞 결과로 증감률 계산
  [생각] Calculating growth percentages ...       ← 추론 요약
(요청 6) write_file("reports/q3_report.md", ...)  ← 사용자 승인 후 저장
(요청 7) 최종 보고                                 ← 도구 호출 없음 = 작업 끝
```

사람이 순서를 정해 주지 않았는데도, 모델이 앞 단계의 결과를 보고 다음 행동을 결정합니다. 단계 수는 실행할 때마다 달라질 수 있습니다.

## `/v1/responses` 엔드포인트

`gpt-6-luna`는 chat completions에서 추론과 tools를 함께 쓸 수 없어서(tool_calling 예제 README 참고), 이 예제는 `/v1/responses`를 사용합니다. 형식이 이렇게 다릅니다.

| | `/v1/chat/completions` | `/v1/responses` |
| --- | --- | --- |
| system 프롬프트 | `messages`의 `role: "system"` | `instructions` 필드 |
| 대화 기록 | `messages` (메시지 배열) | `input` (아이템 배열) |
| 응답 | `choices[0].message` | `output` (아이템 배열) |
| 도구 정의 | `{"type": "function", "function": {...}}` | `{"type": "function", "name": ..., "parameters": ...}` |
| 도구 호출 | `message.tool_calls[]` | `type: "function_call"` 아이템 |
| 도구 결과 | `role: "tool"` + `tool_call_id` | `type: "function_call_output"` + `call_id` |
| 토큰 사용량 | `prompt_tokens` / `completion_tokens` | `input_tokens` / `output_tokens` (+ `reasoning_tokens`) |

응답의 `output`에는 여러 종류의 아이템이 섞여 옵니다.

- `reasoning`: 모델의 추론. `summary`에 사람이 읽을 수 있는 요약이 있고(`[생각]`으로 출력), `encrypted_content`에 암호화된 추론 원본이 있습니다. 요약은 영어로 오는 경우가 많습니다.
- `function_call`: 도구 호출 요청
- `message`: 모델이 사용자에게 하는 말

### 서버에 저장하지 않는 방식 (`store: false`)

이 예제는 `store: false`로 서버에 대화를 저장하지 않고, 매번 전체 `input`을 다시 보냅니다. chatbot 예제와 같은 방식입니다.
이때 응답의 `output`을 **reasoning 아이템까지 전부** 다음 요청의 `input`에 이어 붙여야, 모델이 앞에서 세운 계획을 이어서 생각합니다. `include: ["reasoning.encrypted_content"]`는 그 추론 원본을 암호화된 형태로 받아오기 위한 옵션입니다. 로그에서는 이 값이 길어서 앞 40자만 보여줍니다.

참고로 `/v1/responses`는 `store: true`와 `previous_response_id`를 쓰면 서버가 대화를 기억하게 할 수도 있습니다. 그 경우에는 새 아이템만 보내면 되지만, 실제로 무엇이 모델에 들어가는지가 서버 뒤로 숨겨집니다.

## 테스트하면서 발견한 것: 프롬프트를 지키는 척하는 실패

처음에는 instructions에 "숫자 계산은 calculate 도구를 사용해"라고만 썼습니다. 그랬더니 모델이 판매량 합계를 **머릿속으로 미리 더한 뒤** 그 결과만 `calculate("(37-36)/36*100")`에 넣었습니다. 9월 모니터 판매량 53대를 37대로 잘못 계산한 보고서가 나왔습니다.
지금은 "합계도 원본 숫자를 수식에 그대로 넣어 계산해"라고 구체적으로 지시해서, 모델이 `calculate("28 + 16 + 9")`처럼 계산합니다.

에이전트는 도구를 쥐여 주는 것만으로는 부족하고, **언제 어떻게 써야 하는지**까지 알려 줘야 합니다. 로그로 도구 호출 인자를 확인하는 것이 이런 실수를 찾는 가장 확실한 방법입니다.
