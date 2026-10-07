import asyncio

from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()


'''
직접 만든 서버 대신 이미 공개된 MCP 서버들을 연결합니다. 모두 API 키 없이 사용할 수 있습니다.

1) time, fetch: MCP 공식 레퍼런스 서버(Python 패키지)입니다.
   uvx가 패키지를 내려받아 바로 실행하므로 따로 pip install 할 필요가 없습니다. (최초 실행 시 다운로드로 시간이 조금 걸립니다.)
   - mcp-server-time  : 현재 시간 조회, 시간대 변환
   - mcp-server-fetch : URL의 웹페이지를 가져와 마크다운으로 변환

2) deepwiki: 인터넷에 떠 있는 원격 MCP 서버입니다.
   로컬에서 프로세스를 띄우지 않고 "streamable_http" transport로 URL에 접속합니다.
   - GitHub 공개 저장소의 문서(위키)를 조회하고 질문할 수 있습니다.

이처럼 stdio(로컬)와 streamable_http(원격) 서버를 하나의 클라이언트에 섞어서 연결할 수 있습니다.
'''
client = MultiServerMCPClient(
    {
        "time": {
            "command": "uvx",
            "args": ["mcp-server-time", "--local-timezone=Asia/Seoul"],
            "transport": "stdio",
        },
        "fetch": {
            "command": "uvx",
            "args": ["mcp-server-fetch"],
            "transport": "stdio",
        },
        "deepwiki": {
            "url": "https://mcp.deepwiki.com/mcp",
            "transport": "streamable_http",
        },
    }
)

model = ChatOpenAI(model="gpt-4o-mini")

QUESTIONS = [
    "서울이 지금 몇 시야? 뉴욕은 몇 시인지도 알려줘.",
    "https://modelcontextprotocol.io/docs/getting-started/intro 페이지를 읽고 MCP가 뭔지 3줄로 요약해줘.",
    "DeepWiki로 langchain-ai/langgraph 저장소를 찾아보고, checkpointer가 무슨 역할인지 간단히 설명해줘.",
]


async def main():
    '''
    get_tools()는 연결된 모든 서버의 도구를 한 리스트로 모아서 반환합니다.
    특정 서버의 도구만 쓰고 싶다면 get_tools(server_name="time")처럼 서버 이름을 지정할 수 있습니다.
    '''
    tools = await client.get_tools()
    print("불러온 MCP 도구:", [tool.name for tool in tools])

    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt="너는 친절한 한국어 어시스턴트야. 필요한 경우 제공된 도구를 사용해서 답변해.",
    )

    for question in QUESTIONS:
        print(f"\n\n========== [질문] {question} ==========")

        '''
        fetch, deepwiki 도구의 결과는 매우 길기 때문에 도구 결과 전체는 출력하지 않고,
        모델이 어떤 도구를 어떤 인자로 호출했는지와 최종 답변만 출력합니다.
        '''
        async for chunk in agent.astream(
            {"messages": [{"role": "user", "content": question}]},
            stream_mode="updates",
        ):
            for message in chunk.get("model", {}).get("messages", []):
                for tool_call in message.tool_calls:
                    print(f"[도구 호출] {tool_call['name']}({tool_call['args']})")
                if not message.tool_calls:
                    print(f"\n[답변]\n{message.content}")


if __name__ == "__main__":
    asyncio.run(main())
