from langchain.tools import tool

@tool
def add(a: int, b: int) -> int:
    """Adds a and b.

    Args:
        a: first int
        b: second int
    """
    return a + b

@tool
def multiply(a: int, b: int) -> int:
    """Multiplies a and b.

    Args:
        a: first int
        b: second int
    """
    return a * b

tools = [add, multiply]


from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o")
llm_with_tools = llm.bind_tools(tools)


query = "3 곱하기 5 는 뭔가요? 그리고 2 더하기 4 는 뭔가요?"

response = llm_with_tools.invoke(query)
print(response)
print(response.tool_calls)


query="안녕하세요."

response = llm_with_tools.invoke(query)
print(response)

print(response.tool_calls)