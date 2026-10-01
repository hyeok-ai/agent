# 예제 실행 가이드 (uv 환경 기준)

예제를 **uv로 환경을 맞춘 상태**에서 챕터별로 실행하는 방법을 정리한 문서입니다.
Windows PowerShell 기준으로 작성했습니다.

---

## 목차

1. [먼저 알아둘 공통 규칙 3가지](#1-먼저-알아둘-공통-규칙-3가지)
2. [챕터별 .env 준비](#2-챕터별-env-준비)
3. [챕터별 실행 방법](#3-챕터별-실행-방법)
4. [LangGraph Studio(`langgraph dev`) 사용하기](#4-langgraph-studiolanggraph-dev-사용하기)
5. [자주 만나는 에러](#5-자주-만나는-에러)

---

## 1. 먼저 알아둘 공통 규칙 3가지

### 규칙 ① 실행은 `uv run`으로

```powershell
uv run python agent.py
```

`uv run`은 현재 폴더에서 상위로 올라가며 `pyproject.toml`을 찾아 저장소 루트의 `.venv`를 자동으로 사용합니다.
그래서 **하위 폴더 어디에서 실행해도** 같은 가상환경이 잡힙니다.

가상환경을 직접 활성화하는 방식도 괜찮습니다. 이 경우 `uv run` 없이 `python ...`으로 실행하면 됩니다.

```powershell
# 저장소 루트에서 한 번만
.venv\Scripts\Activate.ps1
```

### 규칙 ② 스크립트가 있는 폴더로 `cd` 한 뒤 실행

**가장 중요한 규칙입니다.** 예제 코드가 두 가지 방식으로 "현재 작업 폴더"에 의존하기 때문입니다.

- **같은 폴더 모듈을 바로 import합니다.** 패키지 형태가 아닙니다.
  ```python
  from tools import python_exec_tool      # CHAP6 coding_agent
  from settings import get_model          # CHAP7
  from agent_executor import ...          # CHAP10, CHAP11
  ```
- **상대 경로를 사용합니다.**
  ```python
  args=["./server.py"]                    # CHAP9 client.py
  load_dotenv(dotenv_path="../.env")      # CHAP10 multi_agent
  ```

따라서 아래처럼 루트에서 경로를 붙여 실행하면 `ModuleNotFoundError`나 파일을 찾지 못하는 에러가 납니다.

```powershell
# ❌ 루트에서 경로를 붙여 실행
uv run python CHAP6_single-agent/coding_agent/agent.py

# ✅ 해당 폴더로 이동 후 실행
cd CHAP6_single-agent\coding_agent
uv run python agent.py
```

> ⚠️ **예외:** CHAP7 `supervisor_agent_triple`은 반대로 **챕터 루트(`CHAP7_multi-agent`)** 에서 실행해야 합니다.
> 코드가 `./supervisor_agent_triple/chroma_db`처럼 챕터 루트를 기준으로 한 경로를 쓰기 때문입니다. 자세한 내용은 [CHAP7](#chap7_multi-agent--멀티-에이전트)을 참고하세요.

### 규칙 ③ 챕터마다 `.env`가 필요

API 키는 각 챕터 폴더의 `.env`에서 읽습니다. 다음 절에서 설명합니다.

---

## 2. 챕터별 .env 준비

`.env.example`이 있는 폴더마다 `.env`를 만들고 키 값을 채웁니다.

```powershell
Copy-Item .env.example .env
```

| `.env`를 만들 위치 | 필요한 키 |
|---|---|
| `PART2/` | `OPENAI_API_KEY` *(이미 있음)* |
| `CHAP6_single-agent/` | `OPENAI_API_KEY`, `TAVILY_API_KEY` |
| `CHAP7_multi-agent/` | `OPENAI_API_KEY`, `TAVILY_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` |
| `CHAP8_memory/` | `OPENAI_API_KEY` |
| `CHAP9_MCP/mcp_agent/` | `OPENAI_API_KEY` |
| `CHAP9_MCP/mcp_multi_agent/` | `OPENAI_API_KEY`, `TAVILY_API_KEY` |
| `CHAP10_A2A/` | `OPENAI_API_KEY`, `TAVILY_API_KEY` |
| `CHAP11_final-project/` | `OPENAI_API_KEY`, `TAVILY_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` |

> 💡 **챕터 루트에 `.env` 하나만 둬도 하위 폴더 스크립트가 읽을 수 있는 이유**
> 인자 없이 호출한 `load_dotenv()`는 *실행 중인 스크립트 파일이 있는 폴더*부터 상위로 올라가며 `.env`를 찾습니다.
> 그래서 `CHAP6_single-agent/web_agent/agent.py`를 실행해도 `CHAP6_single-agent/.env`가 로드됩니다.
> 반면 CHAP10 `multi_agent`는 `load_dotenv(dotenv_path="../.env")`처럼 **현재 작업 폴더** 기준 상대 경로를 쓰므로, 반드시 해당 폴더로 이동한 다음 실행해야 합니다.

> ⚠️ `.env`에는 실제 API 키가 들어가므로 git에 커밋하지 않도록 주의하세요.

---

## 3. 챕터별 실행 방법

### 노트북(`.ipynb`) 공통

PART2, CHAP6, CHAP7, CHAP8에는 노트북이 있습니다.

1. VS Code에서 `.ipynb` 파일을 엽니다.
2. 오른쪽 위 **Select Kernel**을 누르고 **Python Environments**에서 저장소의 `.venv`를 선택합니다.
3. 셀을 위에서부터 순서대로 실행합니다.

`ipykernel`은 이미 `.venv`에 설치되어 있어서 따로 설치할 필요가 없습니다.

---

### PART2 — 랭그래프 기초 (4~5장)

```powershell
cd PART2
uv run python 4.4_main.py
```

- `5.2_랭그래프 기본 개념 이해하기.ipynb`, `5.3_랭그래프로 에이전트 설계하고 구현하기.ipynb`는 노트북으로 실행합니다.

---

### CHAP6_single-agent — 싱글 에이전트

에이전트마다 `if __name__ == "__main__":` 블록이 있어서 **직접 실행할 수 있습니다.**

| 절 | 폴더 | 실행 |
|---|---|---|
| 6.2 웹 검색 에이전트 | `web_agent` | `uv run python agent.py` |
| 6.3 코딩 에이전트 | `coding_agent` | `uv run python agent.py` |
| 6.4 create_agent 구조 | `create_agent` | `uv run python middleware.py` 또는 `uv run python middleware_with_node.py` |
| 6.5 RAG 에이전트 | `rag_agent` | `uv run python agent.py` (리트리버만 확인하려면 `uv run python retriever.py`) |

```powershell
cd CHAP6_single-agent\web_agent
uv run python agent.py
```

- 노트북: `coding_agent/custom_tools.ipynb`, `rag_agent/vector_retriever.ipynb`, `web_agent/tavilysearch_tool.ipynb`
- `web_agent/agent.py`의 `__main__`에서 `ainvoke()`와 `astream()` 중 하나를 골라 실행하도록 되어 있습니다. 주석을 바꿔서 전환할 수 있습니다.

---

### CHAP7_multi-agent — 멀티 에이전트

CHAP7의 `make_graph.py`에는 `__main__` 블록이 없습니다. 그래서 `python make_graph.py`로 실행하면 그래프만 만들어지고 아무 일도 일어나지 않습니다.
**LangGraph Studio로 실행합니다.**

```powershell
cd CHAP7_multi-agent
uv run langgraph dev
```

현재 `langgraph.json`은 **7.6 `supervisor_planning_agent`** 를 가리키고 있습니다. 다른 예제를 보려면 [4절](#4-langgraph-studiolanggraph-dev-사용하기)처럼 `langgraph.json`을 수정하세요.

| 절 | 폴더 | `graphs` 경로 |
|---|---|---|
| 7.3 차트 생성 에이전트 | `network_agent` | `./network_agent/make_graph.py:graph` |
| 7.4 웹 요약 → DB 저장 | `supervisor_agent_web` | `./supervisor_agent_web/make_graph.py:graph` |
| 7.5 3중 멀티 에이전트 | `supervisor_agent_triple` | `./supervisor_agent_triple/make_graph.py:graph` |
| 7.6 조사 + 문서 작성 | `supervisor_planning_agent` | `./supervisor_planning_agent/make_graph.py:graph` |

#### 7.5 `supervisor_agent_triple`은 문서 인덱싱을 먼저 실행

DB 검색 에이전트가 Chroma 벡터 DB를 사용합니다. 따라서 Studio를 띄우기 전에 문서를 한 번 인덱싱해야 합니다.
이 스크립트는 **챕터 루트에서** 실행합니다(규칙 ②의 예외).

```powershell
cd CHAP7_multi-agent
uv run python supervisor_agent_triple/setup_documents.py
# → supervisor_agent_triple/chroma_db 가 생성됨
```

- 노트북: `how_to_use_command.ipynb`
- 7.4 예제는 Supabase(`SUPABASE_URL`, `SUPABASE_KEY`)가 필요합니다.

---

### CHAP8_memory — 메모리

노트북 두 개로 구성되어 있습니다.

- `short-term memory.ipynb`
- `long-term memory.ipynb`

---

### CHAP9_MCP — Model Context Protocol

클라이언트(`client.py`)가 MCP 서버(`server.py`)를 **자식 프로세스로 직접 띄웁니다.** 그래서 서버를 따로 실행할 필요가 없습니다.

```powershell
# 9.3 ~ 9.4
cd CHAP9_MCP\mcp_agent
uv run python client.py

# 9.5 MCP 기반 멀티 에이전트
cd CHAP9_MCP\mcp_multi_agent
uv run python client.py
```

- 클라이언트가 `python ./server.py`로 서버를 띄우므로 **반드시 해당 폴더에서 실행**해야 합니다.
- `uv run`으로 실행하면 `.venv`의 `python`이 PATH 맨 앞에 오기 때문에, 서버도 같은 가상환경에서 실행됩니다.

---

### CHAP10_A2A — Agent-to-Agent

A2A는 **서버와 클라이언트를 각각 다른 터미널에서** 실행합니다. 서버를 먼저 띄운 다음 클라이언트를 실행하세요.

#### 10.3 hello_world

```powershell
# 터미널 1 — 서버 (http://localhost:9999)
cd CHAP10_A2A\hello_world
uv run python agent_server.py

# 터미널 2 — 클라이언트
cd CHAP10_A2A\hello_world
uv run python test_client.py
```

#### 10.4 multi_agent

```powershell
# 터미널 1 — LangGraph 에이전트 (http://localhost:10001)
cd CHAP10_A2A\multi_agent\langgraph_agent
uv run python agent_server.py

# 터미널 2 — MCP 에이전트 (http://localhost:10002)
cd CHAP10_A2A\multi_agent\mcp_agent
uv run python agent_server.py

# 터미널 3 — 오케스트레이터
cd CHAP10_A2A\multi_agent
uv run python agent_orchestrator.py
```

- 서버 각각을 단독으로 테스트하려면 해당 폴더에서 `uv run python test_agent.py`를 실행합니다.

---

### CHAP11_final-project — 실전형 멀티 에이전트

터미널 **5개**가 필요합니다. 원격 에이전트 3개를 먼저 띄우고, 다음에 오케스트레이터, 마지막으로 클라이언트를 실행합니다.

```powershell
# 터미널 1 — Web Research Agent (10011)
cd CHAP11_final-project\web_research_agent
uv run python agent_server.py

# 터미널 2 — Internal RAG Agent (10012)
cd CHAP11_final-project\internal_rag_agent
uv run python agent_server.py

# 터미널 3 — File Management Agent (10013)
cd CHAP11_final-project\file_management_agent
uv run python agent_server.py

# 터미널 4 — Orchestrator Agent (10010)
cd CHAP11_final-project\orchestrator_agent
uv run python agent_server.py

# 터미널 5 — 클라이언트
cd CHAP11_final-project
uv run python test_client.py
```

#### 사전 준비

- **Supabase (Internal RAG Agent)**
  1. Supabase SQL Editor에서 `internal_rag_agent/index.sql`을 실행해 pgvector 테이블과 함수를 만듭니다.
  2. 인덱싱이 잘 되는지 확인하려면 다음을 실행합니다.
     ```powershell
     cd CHAP11_final-project\internal_rag_agent
     uv run python test_index.py
     ```
- **Google Drive (File Management Agent)**
  1. Google Cloud Console에서 OAuth 클라이언트를 만들고 `credentials.json`을 다운로드합니다.
  2. 파일을 `file_management_agent/credentials.json` 위치에 둡니다.
  3. 처음 실행하면 브라우저 인증 창이 뜨고, 인증을 마치면 같은 폴더에 `token.json`이 생성됩니다.

---

## 4. LangGraph Studio(`langgraph dev`) 사용하기

`langgraph.json`이 있는 챕터(CHAP6, CHAP7)에서 그래프를 시각화하고 대화형으로 테스트할 수 있습니다. 책 6.2.5절을 참고하세요.

```powershell
cd CHAP6_single-agent     # 또는 CHAP7_multi-agent
uv run langgraph dev
```

> ⚠️ 원본 README에 적힌 `uv run langraph dev`는 오타입니다. **`langgraph`** 로 입력하세요.

### 다른 에이전트로 전환하기

`langgraph.json`의 `dependencies`와 `graphs` **두 곳을 모두** 바꿔야 합니다.

```json
{
  "dependencies": ["./web_agent"],
  "graphs": {
    "agent": "./web_agent/agent.py:graph"
  },
  "env": ".env"
}
```

| 키 | 의미 |
|---|---|
| `dependencies` | 에이전트 코드가 있는 폴더. 이 폴더가 import 경로에 추가되므로 `from tools import ...` 같은 import가 동작합니다. |
| `graphs` | `파일경로:변수명` 형식으로 컴파일된 그래프 객체를 지정합니다. |
| `env` | 로드할 `.env` 파일 |

여러 그래프를 한 번에 띄우는 것도 가능합니다. 다만 폴더마다 `settings.py`, `tools.py`처럼 **이름이 같은 모듈**이 있으면 서로 충돌할 수 있어서, 한 번에 하나씩 띄우는 쪽이 안전합니다.

---

## 5. 자주 만나는 에러

| 증상 | 원인 | 해결 |
|---|---|---|
| `ModuleNotFoundError: No module named 'tools'` (또는 `settings`, `agent_executor`) | 스크립트 폴더가 아닌 곳에서 실행함 | 해당 폴더로 `cd`한 뒤 실행 |
| `OpenAIError: The api_key client option must be set` | `.env`가 없거나 키가 비어 있음 | 챕터 폴더에 `.env` 생성 ([2절](#2-챕터별-env-준비)) |
| CHAP9 `client.py`가 멈추거나 서버 연결 실패 | `./server.py`를 찾지 못함 | `mcp_agent` 또는 `mcp_multi_agent` 폴더에서 실행 |
| CHAP10/11 클라이언트에서 `Connection refused` | 서버가 아직 안 떠 있음 | 서버 터미널에서 `Uvicorn running on ...` 메시지를 확인한 뒤 클라이언트 실행 |
| CHAP10/11 `address already in use` | 이전에 띄운 서버가 아직 실행 중 | 이전 터미널에서 `Ctrl+C`로 종료 |
| CHAP7 7.5 DB 검색 결과가 비어 있음 | Chroma DB를 만들지 않음 | `setup_documents.py`를 챕터 루트에서 실행 |
| `make_graph.py`를 실행해도 아무 출력이 없음 | `__main__` 블록이 없는 파일 | `uv run langgraph dev`로 실행 |
| `langraph: command not found` | 명령어 오타 | `langgraph`로 입력 |
