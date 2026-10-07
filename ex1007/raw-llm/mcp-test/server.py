from datetime import datetime

from mcp.server.fastmcp import FastMCP


'''
FastMCP로 간단한 MCP 서버를 만듭니다.
@mcp.tool() 데코레이터를 붙인 함수는 MCP 도구로 등록되며,
함수의 이름, 타입 힌트, docstring이 그대로 도구의 이름/입력 스키마/설명이 되어 클라이언트(에이전트)에게 전달됩니다.
'''
mcp = FastMCP("demo", log_level="WARNING")


@mcp.tool()
def add(a: int, b: int) -> int:
    """두 정수를 더합니다."""
    return a + b


@mcp.tool()
def multiply(a: int, b: int) -> int:
    """두 정수를 곱합니다."""
    return a * b


@mcp.tool()
def get_current_time() -> str:
    """현재 날짜와 시간을 'YYYY-MM-DD HH:MM:SS' 형식으로 반환합니다."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@mcp.tool()
def get_weather(city: str) -> str:
    """도시 이름을 받아 해당 도시의 날씨를 반환합니다. (예제용 가짜 데이터)"""
    fake_weather = {
        "서울": "맑음, 18°C",
        "부산": "흐림, 21°C",
        "제주": "비, 19°C",
    }
    return fake_weather.get(city, f"{city}의 날씨 정보가 없습니다.")


if __name__ == "__main__":
    '''
    transport="stdio"로 실행하면 표준 입출력으로 클라이언트와 통신합니다.
    이 파일은 직접 실행하기보다는 agent.py에서 MultiServerMCPClient가 하위 프로세스로 띄워서 사용합니다.
    '''
    mcp.run(transport="stdio")
