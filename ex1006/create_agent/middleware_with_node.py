from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.middleware import before_model, dynamic_prompt, AgentState, ModelRequest
from langgraph.runtime import Runtime

from tools import tools

load_dotenv()

model = ChatOpenAI(model="gpt-4o-mini")

BLOCKED_WORDS = ["바보", "멍청이", "나쁜말"]

'''
@before_model을 통해 모델로 입력이 들어가기 전 부적절한 입력이 있는지 확인하는 기능을 추가합니다.
이 미들웨어는 하나의 실행 노드로 추가되며 그래프 실행 흐름의 한 단계로 명시적으로 포함됩니다.
함수의 입력으로 현재 에이전트의 상태인 state를 받아, messages 키를 통해 대화 히스토리를 확인합니다.
이때 입력에 금지어 목록에 포함된 단어가 있는지 검사하고, 금지어가 감지되면 예외를 발생시켜 모델 호출 이전에 에이전트 실행을 즉시 중단합니다.
'''
@before_model
def content_filter_middleware(state: AgentState, runtime: Runtime):
    """
    금지어를 필터링하는 미들웨어
    - 그래프에 'content_filter_middleware' 노드가 추가됨
    - 금지어 감지 시 예외 발생으로 중단
    """

    if state["messages"]:
        last_msg = state["messages"][-1]
        content = getattr(last_msg, 'content', str(last_msg))

        for word in BLOCKED_WORDS:
            if word in content:
                print(f"[before_model] 금지어 감지: '{word}'")
                raise ValueError(f"부적절한 표현이 감지되었습니다: '{word}'")

        print(f"[before_model] 입력 검증 통과")

    return None

'''
@dynamic_prompt 데코레이터를 사용해 정의한 동적 프롬프트를 위한 미들웨어입니다.
이는 모델 호출 시점에 동적으로 시스템 프롬프트를 생성하기 위한 훅으로, 새로운 노드를 별도로 추가하지는 않습니다.
여기서는 랜덤으로 존댓말, 반말, 영어, 거울 프롬프트를 생성해 문자열로 반환하도록 하며, 현재 모델 호출에 적용되는 시스템 프롬프트로 사용됩니다.
'''
@dynamic_prompt
def random_tone_prompt(request: ModelRequest) -> str:
    """
    랜덤하게 말투를 변경하는 미들웨어
    - 존댓말, 반말, 영어, 거울 프롬프트를 랜덤 선택
    - @wrap_model_call 기반이므로 노드 추가 X
    """
    import random

    prompt = [
        ("존댓말", "당신은 친절한 AI입니다. 항상 존댓말로 정중하게 답변하세요."),
        ("반말", "너는 친근한 AI야. 항상 반말로 편하게 답변해."),
        ("영어", "너는 영어로만 말하는 AI야. 항상 영어로 답변해."),
        ("거울", "너는 문장의 문자를 뒤에서부터 거꾸로 출력하는 AI야. 항상 거꾸로 출력해서 답변해.")
    ]

    random_number = random.randrange(0, 4)
    print(f"[dynamic_prompt] {prompt[random_number][0]}")
    return prompt[random_number][1]

# 마지막으로 create_agent 호출 시 middleware 파라미터에 두 개의 미들웨어를 리스트 형태로 전달합니다.
agent = create_agent(
    model=model,
    tools=tools,
    middleware=[
        content_filter_middleware,
        random_tone_prompt
    ]
)

if __name__ == "__main__":
    from pathlib import Path

    save_path = Path(__file__).parent / "middleware_with_node.png"
    graph_image = agent.get_graph().draw_mermaid_png()

    with open(save_path, "wb") as f:
        f.write(graph_image)

    print("=" * 50)
    print("테스트 1: 정상 입력")
    print("=" * 50)
    response = agent.stream({"messages": ["15와 7을 더해주세요."]})
    for chunk in response:
        for node, value in chunk.items():
            if node:
                print(f"\n--- {node} ---")
            if value and "messages" in value:
                print(value['messages'][0].content)

    print('\n' + '='*50)
    print('테스트 2: 금지어 포함 입력')
    print('='*50)

    try:
        response = agent.stream({"messages": ["바보야 10과 5를 더해줘"]})
        for chunk in response:
            for node, value in chunk.items():
                if node:
                    print(f"\n--- {node} ---")
                if value and "messages" in value:
                    print(value['messages'][0].content)

    except ValueError as e:
        print(f"차단됨: {e}")