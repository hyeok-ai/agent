# LangGraph State · StateGraph 정리

## 1. StateGraph

`StateGraph`는 그래프(워크플로우)를 조립하는 빌더 클래스다. `compile()` 전까지는 실행할 수 없다.

| 단계 | 의미 |
|---|---|
| `StateGraph(State)` | 빈 설계도 생성 + 상태 형태(state schema) 지정 |
| `add_node` / `add_edge` | 설계도에 작업과 흐름 추가 |
| `compile()` | 실행 가능한 객체로 변환 |
| `invoke()` / `stream()` | 실행 |

```python
def chatbot(state: State):
    return {"messages": [llm_with_tools.invoke(state["messages"])]}

graph_builder = StateGraph(State)
graph_builder.add_node("chatbot", chatbot)   # 노드 = 작업 단위(함수)
graph_builder.add_edge(START, "chatbot")     # 엣지 = 실행 순서
graph_builder.add_edge("chatbot", END)

graph = graph_builder.compile()              # 실행 가능한 그래프로 변환
graph.invoke({"messages": [("user", "안녕")]})
```

`StateGraph`가 하는 일:

1. **상태 스키마 등록**: 넘긴 `State`가 그래프 전체가 공유하는 데이터 구조가 된다. 모든 노드는 이 State를 입력으로 받고, 바꿀 부분만 딕셔너리로 반환한다.
2. **리듀서 적용**: 키마다 정해진 업데이트 규칙에 따라 노드의 반환값을 State에 반영한다.
3. **노드와 엣지를 붙일 틀 제공**

도구를 바인딩한 LLM을 쓸 때는 보통 `ToolNode`를 노드로 추가하고 `tools_condition`으로 조건부 엣지를 걸어, "LLM이 도구 호출을 요청하면 도구 노드로, 아니면 종료"하는 흐름을 만든다.

---

## 2. 스키마 (State schema)

스키마는 그래프가 공유하는 State의 구조를 정의한 것이다. 다음 세 가지를 정한다.

- 어떤 키가 있는가
- 각 키의 타입이 무엇인가
- 노드가 값을 반환했을 때 기존 값과 어떻게 합칠 것인가(리듀서)

```python
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

class State(TypedDict):
    messages: Annotated[list, add_messages]  # 기존 리스트에 추가
    user_name: str                           # 덮어쓰기

graph = StateGraph(State)  # 이 State가 스키마
```

### 2.1 정의 방식에 따른 종류

| 방식 | 특징 | 언제 쓰나 |
|---|---|---|
| `TypedDict` | 가장 기본적인 방식, 가볍고 빠름 | 대부분의 경우 |
| `dataclass` | 필드에 기본값을 줄 수 있음 | 기본값이 필요할 때 |
| Pydantic `BaseModel` | 런타임에 데이터 검증, 대신 더 느림 | 입력 검증(재귀적 검증)이 중요할 때 |

- Pydantic은 나머지 둘보다 성능이 떨어진다.
- 상위 레벨의 `create_agent`는 Pydantic state 스키마를 지원하지 않는다.

### 2.2 역할에 따른 종류

| 스키마 | 역할 |
|---|---|
| `OverallState` | 그래프 동작에 필요한 모든 키를 담는 내부 전체 State |
| `InputState` | `invoke()`가 받는 키를 제한 |
| `OutputState` | `invoke()`가 반환하는 키를 제한 |
| `PrivateState` | 노드끼리만 주고받는 내부 통신용 채널. 그래프 입출력에 나타나지 않음 |

```python
builder = StateGraph(OverallState, input_schema=InputState, output_schema=OutputState)
```

- 기본적으로 입력 스키마와 출력 스키마는 같으며, 필요할 때 따로 지정한다.
- private 채널은 `invoke` 결과에서는 숨겨지지만, 스트리밍할 때는 기본적으로 그대로 노출된다.

### 2.3 내장 State: `MessagesState`

`messages` 키 하나와 `add_messages` 리듀서로 구성된 내장 State. 보통 상속해서 필드를 추가한다.

```python
from langgraph.graph import MessagesState

class State(MessagesState):
    documents: list[str]
```

### 2.4 Managed value

남은 스텝 수를 자동으로 채워주는 `RemainingSteps` 같은 managed value도 State 필드로 쓸 수 있다.

---

## 3. 리듀서 (Reducer)

State의 각 키(channel)는 업데이트 방식이 따로 정해진다. `Annotated[타입, 함수]`로 지정한다.

| 종류 | 동작 |
|---|---|
| 기본(지정 없음) | 새 값이 기존 값을 덮어씀 |
| 커스텀 리듀서 | `Annotated[list[str], add]`처럼 지정하면 값이 누적됨 |
| `add_messages` | 새 메시지는 추가하고, ID가 같은 기존 메시지는 갱신 |
| `Overwrite` | 리듀서를 우회해 값을 직접 덮어씀. 누적된 리스트를 비울 때 유용 |

```python
messages: Annotated[list, add_messages]
```

노드가 `{"messages": [새 메시지]}`를 반환하면 기존 리스트를 덮어쓰지 않고 뒤에 이어 붙인다. 대화 기록이 누적되는 이유다.

---

## 4. 노드 (Node)

### 4.1 예제

```python
from typing import TypedDict, Annotated
from operator import add
from langgraph.graph import StateGraph

class State(TypedDict):
    messages: Annotated[list[str], add]
    question_length: int

graph_builder = StateGraph(State)

def guardrail(state: State) -> State:
    question_length = len(state["messages"][-1])
    return {
        "question_length": question_length
    }

graph_builder.add_node("guardrail", guardrail)
```

### 4.2 용어별 분석

| 축 | LangGraph 용어 | 이 코드에서 |
|---|---|---|
| 무엇인가 | **Node** | `add_node("guardrail", guardrail)`: 첫 인자가 node 이름, 둘째 인자가 실행할 함수. "guardrail"은 LangGraph 용어가 아니라 작성자가 붙인 이름 |
| 어디에 속하는가 | **StateGraph** | `State`를 state schema로 갖는 `graph_builder`에 등록. `compile()` 전이므로 builder 단계 |
| 무엇을 받는가 | **State** | 두 개의 **channel**(`messages`, `question_length`) 중 `messages`만 읽어 마지막 문자열의 글자 수를 구함 |
| 무엇을 내놓는가 | **State update** | State 전체가 아니라 partial state를 반환. `question_length` 키만 반환하며 `messages`는 그대로 유지. 반환 타입이 `-> State`여도 실제 의미는 일부에 대한 update |
| 어떻게 반영되는가 | **Reducer** | 아래 표 참고 |
| 언제 실행되는가 | **Edge**, **super-step** | 4.3 참고 |
| 왜 있는가 | **Conditional edge**를 위한 State 준비 | 4.4 참고 |

Reducer에 의한 반영:

| Channel | Reducer | 이 node의 update가 반영되는 방식 |
|---|---|---|
| `question_length` | 지정 없음 (default reducer) | 기존 값을 덮어씀 (overwrite) |
| `messages` | `operator.add` | 이 node가 쓰지 않으므로 변화 없음 |

`guardrail`이 `messages`도 반환했다면 `Annotated[list[str], add]`에 따라 기존 리스트에 이어 붙였을 것이다.

### 4.3 Edge와 super-step

- node는 자신을 가리키는 **edge**를 통해 활성화되고, 하나의 **super-step** 안에서 실행된다.
- super-step이 끝날 때 update가 State에 적용되고, 나가는 edge가 다음 super-step에서 실행될 node를 정한다.
- 위 예제에는 edge가 없다. `START`에서 들어오는 edge(entry point)가 없으므로 `guardrail`은 실행될 수 없고 `compile()`도 통과하지 못한다. 최소한 아래가 필요하다.

```python
from langgraph.graph import START, END

graph_builder.add_edge(START, "guardrail")
graph_builder.add_edge("guardrail", END)
graph = graph_builder.compile()
```

### 4.4 Conditional edge

값을 계산해 State에 기록만 하고 스스로 흐름을 바꾸지 않는 node는 보통 뒤에 conditional edge를 붙여 쓴다.

`add_conditional_edges("guardrail", routing_function)`의 **routing function**이 `state["question_length"]`를 읽어 다음 node를 고른다.

---

## 5. 실행과 반환값

### 5.1 `invoke()`의 반환값

`graph.invoke()`는 딕셔너리를 반환한다. 변수에 받아 키로 꺼낸다.

```python
result = graph.invoke({"question": "대한민국의 수도는 어디인가요?"})

print(result)            # {'answer': '대한민국의 수도는 서울입니다.'}
print(result["answer"])  # 대한민국의 수도는 서울입니다.
```

`graph.invoke(...)`만 써두면 Jupyter에서는 셀의 마지막 줄이라 결과가 보이지만, `.py` 파일로 실행하면 아무것도 출력되지 않는다.

### 5.2 입력/출력 스키마에 의한 필터링

| 스키마 | 역할 | 들어있는 키 |
|---|---|---|
| `InputState` | `invoke()`에 넣을 수 있는 값 | `question` |
| `OverallState` | 노드들이 공유하는 전체 상태 | `messages`, `question`, `answer` |
| `OutputState` | `invoke()`가 돌려주는 값 | `answer` |

실행 흐름:

1. `invoke({"question": ...})`로 `question`이 State에 들어간다.
2. `chatbot` 노드가 실행되고, 반환한 `answer`와 `messages`가 내부 State에 기록된다.
3. 종료 시 내부 State를 `OutputState`로 걸러 `answer`만 반환한다.

`messages`는 내부에 저장되지만 결과에는 없으므로 `result["messages"]`는 `KeyError`가 난다.

`messages`도 받으려면:

```python
# 방법 1: OutputState에 키를 추가
class OutputState(TypedDict):
    answer: str
    messages: list[str]

# 방법 2: output_schema를 빼기 (OverallState 전체가 반환됨)
graph_builder = StateGraph(OverallState, input_schema=InputState)
```

### 5.3 `END`의 의미

- `END`는 실행되는 노드가 아니라 "이 뒤로는 갈 곳이 없다"는 표시다.
- `END`가 값을 반환하는 것이 아니다. 더 실행할 노드가 없어지면 그래프가 끝나고, 그 시점의 State가 `invoke()`의 반환값이 된다.
- `add_edge("chatbot", END)`는 "chatbot 다음엔 실행할 노드가 없다"는 뜻이다. chatbot이 끝나면 예약된 노드가 0개가 되어 종료된다.

분기가 있으면 "END를 만나면 반환"과 차이가 난다.

```
START → A → END
      ↘ B → C → END
```

A 쪽이 먼저 `END`에 닿아도 바로 반환되지 않고, B → C까지 모두 끝난 뒤 최종 State가 반환된다.

---

## 6. 개념적 배경: State와 Reduce

### 6.1 State — 오토마타 이론

유한 상태 기계(finite state machine)나 튜링 기계에서 상태는 "지금까지 일어난 일 중, 앞으로의 동작을 결정하는 데 필요한 정보"를 뜻한다. 상태 기계는 전이 함수로 정의된다.

```
δ(현재 상태, 입력) → 다음 상태
```

`StateGraph`라는 이름의 출처다. 노드와 엣지로 이루어진 상태 기계다.

### 6.2 Reduce — 함수형 프로그래밍

`reduce`는 리스트를 하나의 값으로 접는 연산이며, 이론에서는 보통 fold라고 부른다. 1960년대 APL과 Lisp에 이미 있었고, Haskell의 `foldl`/`foldr`, JavaScript의 `Array.reduce`, 구글의 MapReduce가 같은 계열이다.

```javascript
[1, 2, 3].reduce((acc, x) => acc + x, 0)  // 6
```

`(누적값, 새 항목) → 새 누적값` 형태의 함수가 리듀서다. "리듀서"라는 명칭은 학술 용어라기보다 Redux(2015)가 "reduce에 넘기는 함수"라는 뜻으로 퍼뜨린 이름이다.

### 6.3 두 개념의 접점

두 함수는 모양이 같다.

- 전이 함수: `(상태, 입력) → 다음 상태`
- 리듀서: `(누적값, 새 항목) → 새 누적값`

즉 현재 상태는 초기 상태에서 시작해 지금까지의 모든 이벤트를 차례로 fold한 결과다.

```
현재상태 = 이벤트들.reduce(리듀서, 초기상태)
```

React/Redux와 LangGraph가 모두 이 관점을 쓰기 때문에 용어가 겹친다.

### 6.4 이름만 같은 다른 개념

- 람다 계산의 reduction: 식을 단순화하는 것
- 복잡도 이론의 reduction: 문제를 다른 문제로 환원하는 것

---

## 7. 부록: Jupyter에서 예외와 커널 상태

- 예외가 나도 해당 셀의 실행만 중단된다. 커널(파이썬 프로세스)은 살아 있으므로 그때까지 만든 변수, 함수, import는 유지된다.
- 일반 `.py` 실행은 처리되지 않은 예외가 나면 프로세스가 종료되어 메모리 상태가 사라진다. Jupyter 커널은 각 셀 실행을 감싸서 예외를 잡고 traceback만 출력한 뒤 다음 입력을 기다린다(파이썬 REPL과 같은 원리).
- 예외가 난 셀에서도 예외 발생 이전 줄까지의 결과는 남는다.

```python
a = 10
b = 1 / 0   # 여기서 ZeroDivisionError
c = 30
```

실행 후 `a`는 10으로 정의되어 있고, `b`와 `c`는 정의되지 않는다.

- 롤백은 없다. 리스트에 `append`하다가 중간에 죽으면 반쯤 추가된 상태가 그대로 남으므로, 셀을 고쳐 다시 실행할 때 중복 추가 같은 문제가 생길 수 있다.
- "Run All" 중이었다면 예외가 난 셀에서 멈추고 그 뒤 셀들은 실행되지 않는다.
- 상태가 실제로 사라지는 경우: 커널 재시작, 또는 커널이 죽는 경우(메모리 부족, C 확장의 segfault, `os._exit()` 호출 등).
- 예외 직후 `%debug`를 실행하면 예외가 난 시점의 스택으로 들어가 변수 값을 확인할 수 있다.

---

## 출처

- Graph API overview — LangChain Docs
