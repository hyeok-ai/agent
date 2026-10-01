from .page86 import page86_ai_msg


def sub():
    print("메인에서 실행하는 서브함수")

def main() -> None:
    print("메인화면: app.py")
    sub()

    ai_msg = page86_ai_msg()
    print("~~~" + ai_msg + "여기는 app.py의 main()")

    from . import page95
    from . import page97
    from . import page99