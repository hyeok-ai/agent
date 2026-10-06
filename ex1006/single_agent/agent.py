from typing import Annotated
from typing_extensions import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from tools import tools

load_dotenv()


# 1. 상태(State) 정의
#    add_messages 리듀서 덕분에 노드가 반환한 메시지가 기존 목록 뒤에 추가된다.
class State(TypedDict):
    messages: Annotated[list, add_messages]


# 2. 모델에 도구 목록을 알려준다 (bind_tools)
# gpt-6-luna는 Chat Completions API에서 도구 호출을 지원하지 않으므로
# Responses API(/v1/responses)를 사용하도록 지정한다.
llm = ChatOpenAI(model="gpt-6-luna", use_responses_api=True)
llm_with_tools = llm.bind_tools(tools)

SYSTEM_PROMPT = SystemMessage("당신은 친절한 한국어 비서입니다. 필요하면 도구를 사용해서 답하세요.")


# 3. 노드 정의
def agent(state: State):
    """LLM이 답변하거나, 도구 호출(tool_calls)을 요청하는 노드"""
    response = llm_with_tools.invoke([SYSTEM_PROMPT] + state["messages"])
    return {"messages": [response]}


# ToolNode: 마지막 AIMessage의 tool_calls를 실행하고 ToolMessage를 돌려준다.
tool_node = ToolNode(tools)


# 4. 그래프 구성
#    START → agent ─(도구 호출 있음)→ tools → agent → ... ─(없음)→ END
graph_builder = StateGraph(State)
graph_builder.add_node("agent", agent)
graph_builder.add_node("tools", tool_node)

graph_builder.add_edge(START, "agent")
# tools_condition: 마지막 메시지에 tool_calls가 있으면 "tools", 없으면 END로 보낸다.
graph_builder.add_conditional_edges("agent", tools_condition)
graph_builder.add_edge("tools", "agent")

# 체크포인터를 붙이면 같은 thread_id 안에서 이전 대화를 기억한다.
graph = graph_builder.compile(checkpointer=InMemorySaver())


def ask(question: str, thread_id: str = "1") -> None:
    config = {"configurable": {"thread_id": thread_id}}

    # stream_mode="updates": 노드가 실행될 때마다 그 노드가 반환한 값을 받는다.
    for chunk in graph.stream(
        {"messages": [{"role": "user", "content": question}]},
        config,
        stream_mode="updates",
    ):
        for node, update in chunk.items():
            for msg in update["messages"]:
                # Responses API는 content가 블록 리스트라서 msg.text로 텍스트만 꺼낸다.
                if msg.type == "ai" and msg.tool_calls:
                    for call in msg.tool_calls:
                        print(f"[{node}] 도구 호출: {call['name']}({call['args']})")
                elif msg.type == "tool":
                    print(f"[{node}] {msg.name} 결과: {msg.text}")
                else:
                    print(f"[{node}] 답변: {msg.text}")
    print()


if __name__ == "__main__":
    print("=== 그래프 구조 ===")
    print(graph.get_graph().draw_mermaid())

    print("종료하려면 exit 입력")
    while True:
        user_input = input(">> ").strip()
        if user_input == "exit":
            break
        if user_input:
            ask(user_input)
