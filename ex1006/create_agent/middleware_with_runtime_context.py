from typing import TypedDict
from langchain.agents import create_agent
from langchain.agents.middleware import dynamic_prompt, ModelRequest
from langchain_openai import ChatOpenAI

class UserContext(TypedDict):
    user_role: str # "expert" | "begineer"

@dynamic_prompt
def role_based_prompt(request: ModelRequest) -> str:
    """사용자 역할에 따른 시스템 프롬프트 생성"""
    role = request.runtime.context.get("user_role", "user")

    if role == "expert":
        return "전문 용어를 사용하여 상세하게 답변하세요."

    elif role == "beginner":
        return "쉬운 말로 간단하게 설명하세요."

    return "친절하게 답변하세요."

model = ChatOpenAI(model="gpt-6-luna")

agent = create_agent(
    model = model,
    middleware = [role_based_prompt],
    context_schema=UserContext
)

question = "함수가 뭐에요?"
response = agent.invoke({"messages": [question]}, context={"user_role": "expert"})

print("전문가용")
'''
print(type(response))
print(dir(response))
print(response)
print(response['messages'])
'''
for message in response['messages']:
    print(message.content)

response = agent.invoke({"messages": [question]}, context={"user_role": "beginner"})

print("초보자용")
'''
print(type(response))
print(dir(response))
print(response)
print(response['messages'])
'''
for message in response['messages']:
    print(message.content)