import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()


'''
OpenAI SDK 없이 HTTP 요청만으로 LLM 서버와 대화하는 챗봇입니다.
SDK(openai, langchain 등)가 내부에서 하는 일은 결국 아래 세 가지입니다.
  1. 엔드포인트 URL로 POST 요청을 보낸다.
  2. 헤더에 API 키(Authorization: Bearer ...)를 담는다.
  3. 본문(body)에 모델 이름과 지금까지의 대화(messages)를 JSON으로 담는다.
httpx는 단순 HTTP 클라이언트이며, requests나 표준 라이브러리 urllib로 바꿔도 동작은 같습니다.
'''
API_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-6-luna"
API_KEY = os.environ.get("OPENAI_API_KEY")

SYSTEM_PROMPT = "너는 친절한 한국어 챗봇이야. 답변은 간결하게 해."

LOG_PATH = Path(__file__).parent / "http_debug.log"


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
        응답 헤더까지 받은 시점에 호출됩니다. 본문은 아직 읽기 전입니다.
        (여기서 본문을 읽어 버리면 스트리밍이 깨지므로, 본문은 chat()/chat_stream()에서 따로 기록합니다.)
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
        같은 Client로 두 번째 요청을 보내면 connect_tcp/start_tls가 보이지 않습니다.
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


def build_headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def build_body(messages, stream):
    '''
    LLM 서버는 대화를 기억하지 않습니다(stateless).
    그래서 매 요청마다 system 프롬프트부터 지금까지의 모든 user/assistant 메시지를 통째로 보냅니다.
    "챗봇이 이전 대화를 기억한다"는 것은 클라이언트가 messages 리스트를 계속 쌓아서 다시 보내는 것일 뿐입니다.
    '''
    body = {
        "model": MODEL,
        "messages": messages,
        "stream": stream,
    }
    if stream:
        # 스트리밍 모드에서는 기본적으로 토큰 사용량이 오지 않으므로, 마지막 청크에 포함해 달라고 요청합니다.
        body["stream_options"] = {"include_usage": True}
    return body


def chat(client, debugger, messages):
    '''
    일반(non-stream) 요청입니다.
    서버가 답변을 끝까지 생성한 뒤, 한 번에 하나의 JSON 응답을 돌려줍니다.
    응답 구조: {"choices": [{"message": {"role": "assistant", "content": "..."}}], "usage": {...}, ...}
    '''
    body = build_body(messages, stream=False)
    response = client.post(API_URL, headers=build_headers(), json=body)
    debugger.log_body(response.text)

    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}\n{response.text}")

    data = response.json()
    content = data["choices"][0]["message"]["content"]
    print(f"AI: {content}")
    return content, data.get("usage")


def chat_stream(client, debugger, messages):
    '''
    스트리밍 요청입니다. (ChatGPT 화면에서 글자가 한 토큰씩 나타나는 방식)
    서버는 SSE(Server-Sent Events) 형식으로 응답을 조금씩 흘려보냅니다. 실제로 오는 텍스트는 이렇습니다.

        data: {"choices":[{"delta":{"role":"assistant","content":""}}], ...}

        data: {"choices":[{"delta":{"content":"안녕"}}], ...}

        data: {"choices":[{"delta":{"content":"하세요"}}], ...}

        data: {"choices":[], "usage":{...}}

        data: [DONE]

    한 줄씩 읽으면서 "data: " 뒤의 JSON을 파싱하고, delta.content 조각을 이어 붙이면 전체 답변이 됩니다.
    '''
    body = build_body(messages, stream=True)
    full_content = ""
    usage = None

    with client.stream("POST", API_URL, headers=build_headers(), json=body) as response:
        if response.status_code != 200:
            response.read()
            debugger.log_body(response.text)
            raise RuntimeError(f"HTTP {response.status_code}\n{response.text}")

        if not debugger.enabled:
            print("AI: ", end="", flush=True)

        for line in response.iter_lines():
            # 디버그 모드에서는 서버가 보낸 SSE 줄을 가공 없이 그대로 기록합니다.
            if debugger.enabled and line:
                debugger.log(f"[+{debugger.elapsed_ms():5.0f}ms] {line}")

            # SSE는 이벤트 사이를 빈 줄로 구분합니다. 데이터가 담긴 줄만 처리합니다.
            if not line.startswith("data: "):
                continue

            payload = line[len("data: "):]
            # [DONE]은 스트림 끝 표시입니다. 여기서 break하지 않고 본문을 끝까지 읽어야
            # httpcore가 응답을 정상 종료로 보고 연결을 다음 요청에 재사용(keep-alive)합니다.
            if payload == "[DONE]":
                continue

            chunk = json.loads(payload)
            if chunk.get("usage"):
                usage = chunk["usage"]

            for choice in chunk.get("choices", []):
                piece = choice.get("delta", {}).get("content")
                if piece:
                    full_content += piece
                    if not debugger.enabled:
                        print(piece, end="", flush=True)

    if debugger.enabled:
        print(f"\nAI: {full_content}")
    else:
        print()
    return full_content, usage


def print_help():
    print("명령어: /stream (스트리밍 on/off)  /debug (HTTP 통신 로그 on/off)")
    print("        /history (보내는 messages 보기)  /reset (대화 초기화)  /exit (종료)")


def main():
    if not API_KEY:
        print("OPENAI_API_KEY 환경 변수가 없습니다. .env 파일에 OPENAI_API_KEY=sk-... 를 추가하세요.")
        sys.exit(1)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    stream = True
    debugger = HttpDebugger(enabled="--debug" in sys.argv)

    print(f"모델: {MODEL}  엔드포인트: {API_URL}")
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
            if user_input == "/stream":
                stream = not stream
                print(f"스트리밍: {'ON' if stream else 'OFF'}")
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

            messages.append({"role": "user", "content": user_input})

            try:
                if stream:
                    content, usage = chat_stream(client, debugger, messages)
                else:
                    content, usage = chat(client, debugger, messages)
            except (RuntimeError, httpx.HTTPError) as e:
                print(f"[요청 실패] {e}")
                # 실패한 질문은 대화 기록에서 제거해, 다음 요청에 섞이지 않도록 합니다.
                messages.pop()
                continue

            # 모델의 답변도 기록에 추가해야 다음 요청에서 모델이 앞의 대화를 "기억"할 수 있습니다.
            messages.append({"role": "assistant", "content": content})

            if usage:
                print(
                    f"(토큰: 입력 {usage.get('prompt_tokens')} / 출력 {usage.get('completion_tokens')}"
                    f" / 합계 {usage.get('total_tokens')})"
                )


if __name__ == "__main__":
    main()
