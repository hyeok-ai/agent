from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str
    email: str

user_data = {
    'id': 1,
    'name': 'nayeon_park',
    'email': 'example@gmail.com'
}

user1 = User(**user_data)
print(user1)



import traceback

wrong_user_data = {
    'id': 1,
    'name': 123,
    'email': 'example@gmail.com'
}

try:
    wrong_user = User(**wrong_user_data)
except Exception as e:
    print(f'에러 발생: {e}')
    traceback.format_exc()