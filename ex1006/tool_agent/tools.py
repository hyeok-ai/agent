from datetime import datetime

from langchain.tools import tool


@tool
def get_current_time() -> str:
    """현재 날짜와 시간을 알려줍니다."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def calculate(a: float, b: float, operator: str) -> float:
    """두 숫자를 사칙연산합니다.

    Args:
        a: 첫 번째 숫자
        b: 두 번째 숫자
        operator: 연산자. "+", "-", "*", "/" 중 하나
    """
    if operator == "+":
        return a + b
    if operator == "-":
        return a - b
    if operator == "*":
        return a * b
    if operator == "/":
        if b == 0:
            raise ValueError("0으로 나눌 수 없습니다.")
        return a / b
    raise ValueError(f"지원하지 않는 연산자입니다: {operator}")


# 실제 API 대신 사용하는 가짜 날씨 데이터
FAKE_WEATHER = {
    "서울": "맑음, 22도",
    "부산": "흐림, 24도",
    "제주": "비, 20도",
}


@tool
def get_weather(city: str) -> str:
    """도시 이름을 받아 오늘의 날씨를 알려줍니다.

    Args:
        city: 날씨를 조회할 도시 이름 (예: 서울, 부산, 제주)
    """
    return FAKE_WEATHER.get(city, f"{city}의 날씨 정보가 없습니다.")


tools = [get_current_time, calculate, get_weather]
