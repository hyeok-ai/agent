from langgraph.graph import MessagesState


'''
messages 키를 기본으로 포함하는 사전 구축 상태인 MessagesState를 제공
MessagesState는 messages라는 단일 키를 가지며, 이는 AnyMessage 객체의 리스트로 정의되어 있고, 
메시지를 누적하는 add_messages 리듀서를 사용
'''
class AgentState(MessagesState):
    question: str
    context: str
    answer: str
    retry_num: int