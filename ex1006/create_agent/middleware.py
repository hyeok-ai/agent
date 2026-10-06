from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse


from tools import tools

load_dotenv()

basic_model = ChatOpenAI(model="gpt-4o-mini")
advanced_model = ChatOpenAI(model="gpt-4o")


'''
@wrap_model_call 데코레이터로 정의한 dynamic_model_selection 함수를 통해 미들웨어를 구현합니다.
이는 에이전트가 모델을 호출하려는 시점에 실행됩니다. 함수는 request와 handler 두 개의 파라미터를 받는데, request는 ModelRequest 객체로 모델 호출 시점의 모든 정보를 담습니다.
이때 request.state에서 에이전트 상태의 messages 키를 통해 현재 대화 메시지 수를 확인합니다. 만약 메시지가 10개를 초과했다면 advanced_model, 즉 gpt-4o 모델을 사용하도록 하고, 그렇지 않은 경우는 basic_model을 사용합니다.
'''
@wrap_model_call
def dynamic_model_selection(request: ModelRequest, handler) -> ModelResponse:
    """대화 복잡도에 따라 모델을 동적으로 선택하는 미들웨어"""
    message_count = len(request.state["messages"])
    print(f"현재 대화 메시지 수: {message_count}")

    if message_count > 10:
        model = advanced_model
        print("복잡한 대화 감지: 고급 모델(gpt-4o) 사용")
    else:
        model = basic_model

    return handler(request.override(model=model))
    '''
    request.override(model=model)을 통해, 현재 모델 호출 요청에서 사용할 모델을 새로 지정하여 새 요청 객체를 만듭니다. 
    이때 호출하는 handler는 원래 create_agent가 수행하려던 실제 모델 호출 함수로, 변경된 모델로 모델 호출을 이어나갑니다.
    '''


'''
에이전트를 생성할 때는 create_agent의 middleware 파라미터에 미들웨어를 리스트로 전달합니다.
여러 미들웨어를 사용할 경우 리스트에 추가한 순서대로 실행됩니다.
'''
agent = create_agent(
    model=basic_model,
    tools=tools,
    middleware=[dynamic_model_selection]
)

if __name__ == "__main__":
    from pathlib import Path
    from langgraph.checkpoint.memory import MemorySaver

    save_path = Path(__file__).parent / "middleware_wrap_model_call.png"
    graph_image = agent.get_graph().draw_mermaid_png()
    with open(save_path, "wb") as f:
        f.write(graph_image)

    agent_with_memory = create_agent(
        model = basic_model,
        tools = tools,
        middleware = [dynamic_model_selection],
        checkpointer = MemorySaver()
    )

    config = {"configurable": {"thread_id": "test_thread"}}

    # 여러 턴의 대화 시뮬레이션
    questions = [
        "15와 7을 더해주세요.",
        "결과에 3을 곱해주세요.",
        "그 결과에서 10을 빼주세요.",
        "100을 5로 나눠주세요.",
        "25와 25를 더해주세요.",
        "1000에서 500을 빼주세요.",  # 이 시점에서 메시지 10개 초과 예상
    ]

    for i, question in enumerate(questions, 1):
        print(f"\n{'='*50}")
        print(f"🔄 턴 {i}: {question}")
        print('='*50)

        response = agent_with_memory.invoke(
            {"messages": [question]},
            config=config
        )

        # 마지막 AI 응답만 출력
        print(f"🤖 응답: {response['messages'][-1].content}")