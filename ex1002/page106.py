from dotenv import load_dotenv

load_dotenv()

from typing import TypedDict, Annotated
from operator import add

class InputState(TypedDict):
    question: str

class OutputState(TypedDict):
    answer: str

class OverallState(TypedDict):
    messages: Annotated[list[str], add]
    question: str
    answer: str


from langgraph.graph import StateGraph

graph_builder = StateGraph(
    OverallState,
    input_schema = InputState,
    output_schema=OutputState
)


from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o")

def chatbot(state: InputState) -> OverallState:
    question = state["question"]
    response = llm.invoke(question)
    return {
        "answer":response.content,
        "messages":[question, response.content]
    }

graph_builder.add_node("chatbot", chatbot)


from langgraph.graph import START, END

graph_builder.add_edge(START, "chatbot")
graph_builder.add_edge("chatbot", END)
graph = graph_builder.compile()


graph.invoke({"question": "대한민국의 수도는 어디인가요?"})