from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.tools import tool

'''
에이전트가 반환해야 할 구조화된 출력의 형태를 파이단틱 모델로 정의합니다.
ContactInfo는 이름, 이메일, 전화번호라는 세 개의 필드를 가지며, 각 필드는 타입과 설명을 함께 지정합니다.
'''
class ContactInfo(BaseModel):
    """연락처 정보 스키마"""
    name: str = Field(description="이름")
    email: str = Field(description="이메일 주소")
    phone: str = Field(description="전화번호")

model = ChatOpenAI(model = "gpt-6-luna", use_responses_api=True)

'''
create_agent 호출 시 response_format에 ToolStrategy(ContactInfo)를 전달합니다.
이를 통해 에이전트는 최종 응답을 생성할 때 항상 ContactInfo 스키마를 만족하는 구조화된 결과를 반환하도록 동작합니다.
이때 ToolStrategy는 내부적으로 이 파이단틱 모델을 가상의 도구(tool)로 변환하고, 모델이 해당 도구를 호출하도록 유도하는 방식으로 구조화 출력을 구현합니다.
'''
agent = create_agent(
    model=model,
    response_format=ToolStrategy(ContactInfo)
)

'''
사용자가 텍스트에서 연락처 정보를 추출해달라는 요청을 했습니다.
이때 response_format 설정에 따라 구조화된 결과가 함께 생성됩니다.
'''
result = agent.invoke({
    "messages": [{
        "role": "user",
        "content": "다음 텍스트에서 연락처 정보를 추출해줘: John Doe, john@example.com, (555) 123-4567"
    }]
})


'''
구조화된 출력은 최종 상태의 structured_response 키를 통해 접근할 수 있습니다.
이때 structured_response 키는 6.4.1 절에서 살펴본 것처럼, create_agent에서 사용하는 AgentState에 포함된 상태 필드입니다.
'''
contact = result["structured_response"]
print(f"이름: {contact.name}")
print(f"이메일: {contact.email}")
print(f"전화번호: {contact.phone}")