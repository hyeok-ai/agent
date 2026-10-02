from dotenv import load_dotenv
load_dotenv()


from typing import TypedDict, Annotated
from operator import add

class State(TypedDict):
    messages: Annotated[list[str], add]
    question_length: int


from langgraph.graph import StateGraph

graph_builder = StateGraph(State)



def guardrail(state: State) -> State:
    question_length = len(state["messages"][-1])
    return {
        "question_length": question_length
    }

graph_builder.add_node("guardrail", guardrail)


from langgraph.graph import START, END
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o")

def chatbot(state: State) -> State:
    question = state["message"][-1]
    response = llm.invoke(question)
    return {
        "messages": [response.content]
    }

graph_builder.add_node("chatbot", chatbot)

def routing_function(state: State) -> str:
    if state["question_length"] > 3:
        return "chatbot"
    else:
        return END

graph_builder.add_conditional_edges(
    "guardrail",
    routing_function,
    {"chatbot": "chatbot", END: END}
)

graph_builder.add_edge(START, "guardrail")
graph_builder.add_edge("chatbot", END)
graph = graph_builder.compile()


graph.invoke({"messages":["ㅇ"]})
graph.invoke({"messages":["안녕하세요"]})