import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

SERVER_PATH = Path(__file__).parent / "server.py"


'''
MultiServerMCPClient에 연결할 MCP 서버 목록을 딕셔너리로 전달합니다.
"stdio" transport는 command/args로 지정한 프로세스(여기서는 server.py)를 하위 프로세스로 실행하고 표준 입출력으로 통신합니다.
sys.executable을 사용해 현재 가상환경의 파이썬으로 서버를 실행합니다.
여러 서버를 연결하려면 딕셔너리에 항목을 추가하면 됩니다. (예: "streamable_http" transport로 원격 서버 연결)
'''
client = MultiServerMCPClient(
    {
        "demo": {
            "command": sys.executable,
            "args": [str(SERVER_PATH)],
            "transport": "stdio",
        }
    }
)

model = ChatOpenAI(model="gpt-4o-mini")


async def main():
    '''
    client.get_tools()는 MCP 서버의 도구 목록을 받아와 LangChain 도구(BaseTool)로 변환해 줍니다.
    MCP 도구는 비동기로 동작하므로 에이전트도 ainvoke/astream으로 실행합니다.
    '''
    tools = await client.get_tools()
    print("불러온 MCP 도구:", [tool.name for tool in tools])

    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt="너는 친절한 한국어 어시스턴트야. 필요한 경우 제공된 도구를 사용해서 답변해.",
    )

    question = "지금 몇 시야? 그리고 서울 날씨 알려주고, (12 + 30) * 3 도 계산해줘."
    print(f"\n[질문] {question}\n")

    async for chunk in agent.astream(
        {"messages": [{"role": "user", "content": question}]},
        stream_mode="updates",
    ):
        for node, update in chunk.items():
            for message in update.get("messages", []):
                print(f"----- [{node}] -----")
                message.pretty_print()


if __name__ == "__main__":
    asyncio.run(main())
