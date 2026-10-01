from typing import TypedDict

class State(TypedDict):
    messages: list[str]


class User(TypedDict):
    id: int
    name: str
    email: str

user1: User = {
    'id': 1,
    'name': 'nayeon_park',
    'email': 'example@gmail.com'
}

print(user1)

wrong_user: User = {
    'id': 1,
    'name': 123, # 문자열 키에 정수를 넣었음
    'email': 'example@gmail.com'
}

print(wrong_user) # 잘못된 타입을 넣었지만 실행이 되는 것을 확인할 수 있음. 왜냐하면, TypedDict는 타입 '힌트'용이기 때문


