from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import AIMessage
from langchain_openai import ChatOpenAI
from langchain_community.agent_toolkits import FileManagementToolkit
from langchain_tavily import TavilySearch

from tools import tools as my_tools

load_dotenv()


# 1. 웹 검색 도구 (TAVILY_API_KEY 필요)
search_tool = TavilySearch(max_results=3)

# 2. 파일 관리 도구 모음 (Toolkit)
#    root_dir 밖의 파일에는 접근할 수 없다.
#    삭제/이동 같은 위험한 도구는 빼고 읽기·쓰기·목록 도구만 사용한다.
workspace = Path(__file__).parent / "workspace"
workspace.mkdir(exist_ok=True)

file_tools = FileManagementToolkit(
    root_dir=str(workspace),
    selected_tools=["read_file", "write_file", "list_directory"],
).get_tools()

# 직접 만든 도구 + LangChain이 제공하는 도구
tools = my_tools + [search_tool] + file_tools

print("=== 등록된 도구 ===")
for t in tools:
    print(f"- {t.name}")
print()


# gpt-6-luna는 Chat Completions API에서 도구 호출을 지원하지 않으므로
# Responses API(/v1/responses)를 사용하도록 지정한다.
llm = ChatOpenAI(model="gpt-6-luna", use_responses_api=True)

agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt=(
        "당신은 친절한 한국어 비서입니다. 필요하면 도구를 사용해서 답하세요. "
        "최신 정보가 필요하면 웹 검색을 사용하세요."
    ),
)


def ask(question: str) -> None:
    print("=" * 60)
    response = agent.invoke({"messages": [{"role": "user", "content": question}]})
    for msg in response["messages"]:
        if isinstance(msg, AIMessage):
            # Responses API는 content를 블록 리스트(reasoning, text 등)로 주므로
            # 텍스트와 도구 호출만 골라서 출력한다.
            AIMessage(content=msg.text, tool_calls=msg.tool_calls).pretty_print()
        else:
            msg.pretty_print()


while True:
    user_input = input(">> ")
    if user_input == 'exit':
        exit()

    else:
        ask(user_input)