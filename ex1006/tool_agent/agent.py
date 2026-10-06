from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import AIMessage
from langchain_openai import ChatOpenAI

from tools import tools

load_dotenv()


# 1. @tool로 만든 도구가 어떤 정보를 갖는지 확인 (LLM 호출 없음)
print("=== 등록된 도구 ===")
for t in tools:
    print(f"- {t.name}: {t.description.splitlines()[0]}")
    print(f"  args: {t.args}")

print()
print("=== 도구 직접 호출 ===")
print(tools[1].invoke({"a": 3, "b": 5, "operator": "*"}))
print()


# 2. create_agent로 에이전트 생성
#    모델이 도구 호출 여부를 판단하고, 도구 결과를 받아 최종 답변을 만들 때까지 반복한다.
# gpt-6-luna는 Chat Completions API에서 도구 호출을 지원하지 않으므로
# Responses API(/v1/responses)를 사용하도록 지정한다.
llm = ChatOpenAI(model="gpt-6-luna", use_responses_api=True)

agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt="당신은 친절한 한국어 비서입니다. 필요하면 도구를 사용해서 답하세요.",
)


def ask(question: str) -> None:
    print("=" * 60)
    response = agent.invoke({"messages": [{"role": "user", "content": question}]})

    # 사용자 질문 → AI의 도구 호출 → 도구 결과 → 최종 답변 순서로 출력
    for msg in response["messages"]:
        if isinstance(msg, AIMessage):
            # Responses API는 content를 블록 리스트(reasoning, text 등)로 주므로
            # 텍스트와 도구 호출만 골라서 출력한다.
            AIMessage(content=msg.text, tool_calls=msg.tool_calls).pretty_print()
        else:
            msg.pretty_print()


ask("지금 몇 시야?")
ask("서울이랑 제주 날씨 알려줘.")
ask("123 곱하기 45는 얼마고, 거기에 7을 더하면?")
ask("안녕하세요!")  # 도구가 필요 없는 질문
