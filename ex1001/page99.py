from typing import TypedDict, Annotated

def add(left, right):
    return left + right

class State(TypedDict):
    messages: Annotated[list[str], add]



from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages

msg1 = [HumanMessage(content="Hello", id="1")]
msg2 = [AIMessage(content="Hi there!", id="2")]

reduced_message = add_messages(msg1, msg2) # 리듀서의 'reduce'는 졸이다(졸여내다) 라는 의미, 메시지 두 개를 하나로 졸이는거

print(reduced_message)


from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing import TypedDict, Annotated

class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]