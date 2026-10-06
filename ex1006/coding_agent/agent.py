from dotenv import load_dotenv

from langchain.agents import create_agent, AgentState
from langchain_openai import ChatOpenAI

from tools import python_exec_tool, file_write_tool


load_dotenv()

tools = [python_exec_tool, file_write_tool]


llm = ChatOpenAI(model="gpt-6-luna", use_responses_api=True)



graph = create_agent(
    model=llm,
    tools=tools
)


if __name__ == "__main__":
    while True:
        user_input = input("<< ")
        if user_input == "fibonacci":
            response = graph.stream(
                {
                    "messages": [
                        "첫번째 항이 1인 피보나치 수열을 출력하는 파이썬 코드를 작성해주세요. 정상적으로 실행되는지 확인도 해주세요.",
                        "확인했다면 그 코드는 .py 파일로 저장하세요."
                    ]
                }
            )

            for chunk in response:
                for node, value in chunk.items():
                    if node:
                        print("---", node, "---")
                    if "messages" in value:
                        print(value['messages'][0].content)
        
        elif user_input == 'exit':
            exit()

        else:
            response = graph.stream({"messages": [user_input, ]})

            for chunk in response:
                for node, value in chunk.items():
                    if node:
                        print("---", node, "---")
                    if "messages" in value:
                        print(value['messages'][0].content)