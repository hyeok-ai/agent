# 기술 노트 정리 (10/06)

## 목차

1. [LLM 대화와 컨텍스트 윈도우](#1-llm-대화와-컨텍스트-윈도우)
2. [임베딩 벡터 하나의 정보 용량](#2-임베딩-벡터-하나의-정보-용량)
3. [문장 길이와 임베딩 공간의 분포](#3-문장-길이와-임베딩-공간의-분포)
4. [메시지 구성에 따른 Responses API 페이로드](#4-메시지-구성에-따른-responses-api-페이로드)
5. [LangChain v1 / LangGraph v1 계층 구조](#5-langchain-v1--langgraph-v1-계층-구조)
6. [참고 자료](#6-참고-자료)

---

## 1. LLM 대화와 컨텍스트 윈도우

- LLM은 이전 대화를 기억하지 못한다(stateless). 매 턴마다 지금까지의 대화 전체를 다시 입력으로 넣어야 하므로, 대화가 길어질수록 컨텍스트 윈도우가 찬다.
- 컨텍스트 윈도우는 넘을 수 없는 상한선이다. 그 전에도 대화가 길어지면 비용과 응답 속도가 나빠지고, 모델이 앞쪽 내용을 놓치는 경향이 생긴다.

### 대화 길이를 다루는 기법

| 기법 | 방식 | 한계 |
| --- | --- | --- |
| 잘라내기 (sliding window) | 오래된 메시지부터 버리고 최근 N개 또는 N토큰만 전송 | 앞 내용을 완전히 잊음 |
| 요약 (compaction) | 오래된 대화를 LLM으로 요약하고 최근 메시지만 원문 유지 | 세부 정보 일부 손실 |
| 검색 (RAG, 메모리) | 과거 대화를 외부 저장소에 두고 현재 질문과 관련된 부분만 삽입 | 검색 품질에 의존 |
| 프롬프트 캐싱 | 반복되는 앞부분의 계산 결과를 재사용 | 보내는 양은 줄지 않음 (비용·속도만 개선) |

### 비용

- 매 턴마다 전체 내역을 다시 보내므로 입력 토큰은 턴마다 누적 과금된다.
- 대화 전체의 총비용은 대화 길이에 비례하지 않고 대략 제곱에 가깝게 늘어난다. 위 기법들이 실무에서 중요한 이유다.

---

## 2. 임베딩 벡터 하나의 정보 용량

**핵심:** "점 하나 = 단어 N개"라는 고정된 숫자는 없다. 용량은 단어 수가 아니라 비트(불확실성)로 재야 하고, 아래 세 가지가 서로 크게 다르다.

| 관점 | 용량 | 근거 |
| --- | --- | --- |
| 이론적 상한 | 차원 × 정밀도 비트 (수만 비트, 토큰 수천 개) | Kuratov et al. 2025 |
| 실제 임베딩 모델에서 복원 | 32토큰 정도는 거의 완벽 | Morris et al. 2023 |
| 벡터를 텍스트별로 최적화 | 최대 1,568토큰 무손실 | Kuratov et al. 2025 |
| 검색 용도 | 차원 d가 표현 가능한 관련성 조합에 수학적 한계 | Weller et al. 2025 |

### 2.1 이론적 상한: 차원 × 정밀도

- 벡터는 유한 정밀도의 실수 d개이므로 담을 수 있는 정보는 최대 d × (실수당 비트 수).
- 예: 16비트 실수 2,048차원 → 32,768비트. 어휘 크기 128,256 기준 약 1,931토큰 분량 (토큰 하나가 log₂(128,256) ≈ 17비트).
- 이는 토큰이 완전히 무작위일 때의 계산이다. 자연어는 예측 가능해서 글자당 정보량이 훨씬 작으므로(Shannon 1951 추정: 영어 글자당 약 1비트 안팎) 같은 비트에 더 긴 글이 들어간다. 대략 계산으로 32,768비트면 영어 수천 단어 분량.

### 2.2 실제 임베딩 모델: 짧은 글은 거의 무손실

- "손실압축"이라는 직관은 긴 글에서는 맞지만 짧은 글에서는 생각보다 손실이 없다.
- vec2text 연구: 임베딩을 반복적으로 수정하고 재임베딩하는 방법으로 32토큰 입력의 92%를 정확히 복원.
  - 대상 모델: GTR-base, OpenAI text-embedding-ada-002
  - 32토큰과 128토큰까지 실험
  - 128토큰에서는 정확 복원률이 크게 떨어지는 것으로 기억되나, 이 수치는 **미확인**. 논문 Table 1 확인 필요.
- 저자들의 결론: 임베딩은 원문과 같은 수준의 개인정보로 취급해야 한다.

### 2.3 벡터를 직접 최적화하면: 1,568토큰

- 인코더를 거치지 않고 텍스트 하나마다 벡터를 직접 학습시키면 훨씬 많이 들어간다.
  - Llama-3.1-8B: 벡터 하나에서 최대 1,568토큰 무손실 복원
  - 1B급 모델: 384~512토큰 수준
- 핵심 발견: 압축 한계는 입력 길이가 아니라 줄여야 할 불확실성의 양, 즉 그 텍스트의 cross-entropy로 결정된다. 뻔한 문장은 길게 들어가고, 무작위 문자열은 짧게만 들어간다.
- 주의: RAG용 임베딩 모델의 출력이 아니라 LLM의 입력 벡터에 대한 실험이다. 디코더인 LLM이 언어 지식을 이미 갖고 있어서 가능한 수치이며, 벡터 공간 자체의 잠재 용량을 보여주는 근거로 봐야 한다.

### 2.4 RAG에서 진짜 중요한 한계

- RAG에서 임베딩의 목적은 복원이 아니라 유사도 비교다. 한계는 "몇 단어를 담나"가 아니라 "몇 가지 관련성 패턴을 구분하나"다.
- DeepMind 연구(Weller et al.)는 이를 관련성 행렬의 sign-rank로 정리했다. 차원 d가 고정되면 표현 불가능한 top-k 조합이 반드시 존재하므로, 그 차원의 단일 벡터 임베딩으로는 풀 수 없는 검색 과제가 생긴다.
- LIMIT 데이터셋:
  - 문서 46개에서 가능한 모든 쌍을 찾는 1,035개 쿼리가 핵심
  - 쿼리는 "누가 X를 좋아해?" 수준으로 단순
  - 최신 단일 벡터 모델들이 전체 과제에서 Recall@100 20% 미만
  - cross-encoder, multi-vector 모델, BM25 같은 고차원 sparse 방식은 더 잘 풂

### 2.5 전제 보정

- **점 하나가 텍스트 하나는 아니다.** 매핑은 다대일이라서, 겹치는 단어가 전혀 없는 서로 다른 두 문장이 비슷한 임베딩으로 충돌할 수 있다.
- **무엇이 손실되는지는 학습 목표가 정한다.** 검색용 모델은 "의미가 비슷하면 가깝게"로 학습되므로, 글이 길어지면 주제는 남고 세부 사실(숫자, 고유명사, 어순)부터 흐려진다.

### 2.6 RAG 설계에 주는 의미

청킹을 하고 reranker나 hybrid search를 붙이는 이유는 2.3과 2.4 사이의 간극 때문이다. 공간 자체는 넉넉하지만, 인코더가 그 용량을 "검색에 쓸모 있는 구분"으로 다 쓰지는 못한다.

---

## 3. 문장 길이와 임베딩 공간의 분포

**핵심:** 그릇의 크기는 모든 점이 똑같고, 실제로 담긴 정보량은 점마다 다르다. "짧은 문장 전용 점, 긴 문장 전용 점"처럼 깔끔하게 나뉘지는 않지만, 길이에 따라 점이 놓이는 위치가 쏠리는 경향은 실제로 관측된다.

### 3.1 그릇은 같고, 내용물은 다르다

- 모든 점은 같은 차원, 같은 정밀도의 숫자 묶음이므로 그릇 크기(비트 수)는 동일하다.
- 하지만 "이 점이 원문에 대해 알려주는 정보량"은 다르다. 임베딩은 다대일 매핑이라서, 그 점 근처로 모이는 텍스트 후보가 적을수록 원문을 더 정확히 특정할 수 있다.
  - 짧은 문장의 점: 후보가 적어서 원문이 거의 그대로 복원된다 (32토큰 92% 복원 사례).
  - 긴 글의 점: 같은 비트에 더 많은 내용을 눌러 담았으므로 그 점으로 모이는 서로 다른 글이 훨씬 많다. 점이 알려주는 건 주제 수준이고 세부는 사라진다.
- 이 대비 자체는 **추론**이지만 근거는 있다.
  - 단어가 하나도 안 겹치는 두 문장이 임베딩 공간에서 충돌할 수 있음이 선행 연구로 확인됨
  - 반대로 서로 다른 여러 벡터가 같은 텍스트를 완벽히 복원하며, 그 벡터들이 한곳에 뭉치지 않고 공간 여기저기에 퍼져 있다는 결과도 있음
  - 즉 텍스트와 점의 대응은 양방향 모두 일대일이 아니다.

### 3.2 길이 정보는 벡터에 들어 있다

- 문장 임베딩 프로빙 연구(Conneau et al. 2018)는 임베딩만 보고 문장의 단어 수를 맞히는 과제(SentLen)를 표준 과제로 포함했다. 길이가 벡터에서 읽힌다는 건 길이별로 점의 위치가 체계적으로 다르다는 뜻이다.
- 다만 모델마다 다르다. 같은 연구에서 번역 모델은 학습이 진행될수록 길이 예측 성능이 떨어졌다. 길이는 학습 목표에 쓸모가 있으면 남고 없으면 버려지는 정보다.

### 3.3 긴 글은 좁은 영역에 몰린다 (Length Collapse)

- 텍스트가 길어질수록 서로 다른 글끼리의 코사인 유사도가 올라가고, 긴 글의 임베딩이 좁은 공간으로 뭉친다. 그 결과 길이가 다른 텍스트 사이에 분포 불일치가 생겨 성능이 떨어진다.
  - 짧은 글: 공간에 넓게 퍼져 있고 서로 잘 구분됨
  - 긴 글: 좁은 영역에 몰려 있고 서로 비슷해 보임
- 원인이 길이 그 자체인지는 논쟁 중이다. 2026년 후속 연구는 진짜 원인이 길이가 아니라 글 안에서 의미가 얼마나 이동하고 흩어지는지(semantic shift)라고 주장한다.
  - 내용이 다양할수록 풀링된 벡터가 어느 문장과도 멀어져 뭉툭해진다.
  - 이 지표는 뭉침의 정도를 예측하지만, 길이만으로는 예측하지 못한다.
  - 따라서 "긴 글 구역"보다 "여러 주제가 평균된 글이 모이는 구역"이 더 정확한 표현이다. 한 주제만 길게 쓴 글은 덜 뭉친다.

### 3.4 공간 대부분은 아무 텍스트도 없는 빈 땅

- 실제 텍스트가 쓰는 영역은 공간의 일부다. BERT, ELMo, GPT-2의 표현은 공간 전체에 퍼지지 않고 좁은 원뿔 안에 몰려 있다(이방성, anisotropy).
- 이는 단어 수준 표현에 대한 결과지만, 문장 임베딩 모델에서도 같은 이방성이 잘 알려진 문제로 다뤄진다.

### 3.5 RAG 설계에 주는 의미

- 짧은 쿼리와 긴 청크는 공간에서 놓이는 방식이 다르다.
- 청크를 한 주제 단위로 자르면 3.3의 뭉침이 줄어든다.

---

## 4. 메시지 구성에 따른 Responses API 페이로드

전제: `use_responses_api=True`이므로 OpenAI Responses API 형식으로 요청이 나간다. 아래 필드 구성은 대략적인 형태이며 langchain-openai 버전에 따라 조금 다를 수 있다.

메시지를 나누느냐 합치느냐의 차이는 `input` 배열에 user 항목이 2개 들어가느냐 1개 들어가느냐뿐이다.

### 4.1 메시지를 두 개로 나눈 경우

```json
{
  "model": "gpt-6-luna",
  "input": [
    {"type": "message", "role": "user", "content": "첫번째 항이 1인 피보나치 수열을 ... 확인도 해주세요."},
    {"type": "message", "role": "user", "content": "확인했다면 그 코드는 .py 파일로 저장하세요."}
  ],
  "tools": [
    {"type": "function", "name": "python_exec_tool", "description": "...", "parameters": {...}},
    {"type": "function", "name": "file_write_tool", "description": "...", "parameters": {...}}
  ]
}
```

### 4.2 하나로 합친 경우

```json
{
  "model": "gpt-6-luna",
  "input": [
    {"type": "message", "role": "user", "content": "첫번째 항이 1인 ... 확인한 뒤, .py 파일로 저장하세요."}
  ],
  "tools": [ ...동일... ]
}
```

모델 내부에서는 이 배열이 역할 구분 토큰이 붙은 하나의 토큰 시퀀스로 펼쳐진다. 4.1은 "user 턴이 두 번 연속", 4.2는 "user 턴 한 번"으로 보이는 정도의 차이다.

### 4.3 에이전트 루프 중의 호출

어느 경우든 요청은 한 번으로 끝나지 않는다. 모델이 도구를 호출할 때마다 그 결과가 `input` 뒤에 누적되고 전체가 다시 전송된다. 4.1의 두 번째 요청 예:

```json
"input": [
  {"type": "message", "role": "user", "content": "첫번째 항이 1인 ..."},
  {"type": "message", "role": "user", "content": "확인했다면 ..."},
  {"type": "function_call", "call_id": "call_abc", "name": "python_exec_tool", "arguments": "{\"code\": \"...\"}"},
  {"type": "function_call_output", "call_id": "call_abc", "output": "1 1 2 3 5 8 ..."}
]
```

### 4.4 checkpointer로 호출을 두 번 나눈 경우

- 첫 번째 `invoke`: 첫 지시만 들어간다.
- 두 번째 `invoke`: 앞선 대화 전체(user, function_call, function_call_output, assistant 답변) 뒤에 새 user 메시지가 붙어서 들어간다.
- 즉 모델이 실행 결과와 자신의 답변까지 본 상태에서 저장 지시를 받는다.

### 4.5 실제 페이로드 확인 방법

```python
from langchain_core.messages import HumanMessage

payload = llm.bind_tools(tools).bound._get_request_payload(
    [HumanMessage("첫번째 ..."), HumanMessage("확인했다면 ...")],
    **llm.bind_tools(tools).kwargs,
)
print(payload)
```

- `_get_request_payload`는 내부 메서드라 버전에 따라 바뀔 수 있다.
- 더 확실한 방법:
  - LangSmith 트레이싱 켜기
  - `logging.getLogger("openai").setLevel(logging.DEBUG)`로 HTTP 요청 로그 보기

---

## 5. LangChain v1 / LangGraph v1 계층 구조

**한 줄 요약:** v1.0에서 역할을 **LangGraph = 저수준 런타임, LangChain = 그 위의 고수준 에이전트 추상화**로 나눴다. 에이전트 프리빌트는 고수준 쪽이라 langchain으로 옮겨갔다.

### 5.1 패키지 스택

```
langchain (v1)      create_agent, 미들웨어                       ← 고수준
langgraph           StateGraph, 노드/엣지, 체크포인터              ← 저수준 런타임
langchain-core      Runnable(LCEL), 메시지, 툴, 모델 인터페이스     ← 최하단 기반
```

- `langchain_classic`은 이 스택의 옆가지다. 예전 langchain의 체인들(`RetrievalQA`, `AgentExecutor` 등)을 레거시로 떼어 놓은 패키지로, core 위에 있지만 langgraph와는 상관이 없다.

### 5.2 에이전트 프리빌트가 langchain으로 간 이유

- **계층 분리**
  - LangGraph는 커스터마이징과 제어가 필요한 에이전트를 위한 저수준 프레임워크이자 런타임으로 정의됐다.
  - LangChain의 `create_agent`는 LangGraph 위에서 돌아간다.
  - 빠르게 시작할 땐 LangChain, 커스텀 오케스트레이션이 필요하면 LangGraph로 내려가는 구도다.
  - 그래프 프리미티브(state, node, edge)만 다루는 패키지 안에 "완성형 에이전트"가 `prebuilt`로 들어 있던 것이 오히려 어색한 상태였다.
- **이전 위치는 deprecated**
  - v1.0 이전 권장: `langgraph.prebuilt.create_react_agent`
  - v1.0 이후 권장: `langchain.agents.create_agent`
  - LangGraph 1.0의 유일하게 눈에 띄는 변경이 `langgraph.prebuilt` 모듈의 deprecation이고, 강화된 기능이 `langchain.agents`로 옮겨갔다.
- **미들웨어 추가**
  - `create_agent`는 더 단순한 인터페이스에 미들웨어를 통한 커스터마이징을 제공한다.
  - 요약, human-in-the-loop, 동적 프롬프트 같은 미들웨어는 모델·툴·메시지 같은 LangChain 쪽 추상화에 의존하는 "의견이 들어간" 기능이라, 런타임 패키지보다 langchain에 두는 게 자연스럽다.
- **langchain 패키지의 정체성 재정의**
  - 1.0에서 langchain은 핵심 추상화만 남기고 레거시 기능을 `langchain-classic`으로 옮겼다.
  - 예전 chain, `AgentExecutor` 등이 빠진 자리에 "에이전트 만드는 패키지"라는 역할이 들어갔다.

### 5.3 의존성 방향

- langchain → langgraph → langchain-core 순으로 의존한다. langgraph는 langchain을 몰라도 된다.
- `create_agent`가 반환하는 것도 결국 컴파일된 LangGraph 그래프다. 체크포인터·스트리밍 등은 그대로 쓸 수 있고, 다른 그래프의 노드로 끼워 넣을 수도 있다.

### 5.4 "langchain이 langgraph보다 로우레벨"이라는 직감에 대해

- 반은 맞다. "langchain"이라는 이름이 서로 다른 층 두 개를 가리키기 때문에 헷갈린다.
- RAG에서 쓰는 `prompt | llm | parser`, retriever, 메시지 타입 등은 대부분 **langchain-core**에서 온 것이다. 이는 실제로 langgraph보다 아래층이다.
- 반면 v1의 **langchain 패키지**는 core가 아니라 langgraph 위에 얹힌 층이다. langgraph로 직접 그리던 "모델 호출 → 툴 실행 → 다시 모델" 루프를 `create_agent` 한 줄로 만들어주므로 langgraph보다 고수준이다.
- langgraph는 루프, 상태, 분기를 다뤄서 더 어려운 주제지만, 추상화 수준으로 보면 노드와 엣지를 직접 다 짜야 하므로 오히려 저수준이다.
- langgraph로 에이전트를 먼저 짜보면 `create_agent`가 내부에서 하는 일을 이미 손으로 구현해본 셈이라, 나중에 써도 블랙박스로 느껴지지 않는다.

---

## 6. 참고 자료

### 임베딩 용량·검색 한계

- [Cramming 1568 Tokens into a Single Vector and Back Again (Kuratov et al., ACL 2025)](https://aclanthology.org/2025.acl-long.948)
- [Text Embeddings Reveal (Almost) As Much As Text (Morris et al., EMNLP 2023)](https://aclanthology.org/2023.emnlp-main.765)
- [On the Theoretical Limitations of Embedding-Based Retrieval (Weller et al., arXiv 2508.21038)](https://www.arxiv.org/abs/2508.21038)
- [DAIR.AI 논문 요약: LIMIT 결과](https://academy.dair.ai/papers/on-the-theoretical-limitations-of-embedding-based-retrieval)
- [Shaped 블로그: The Vector Bottleneck](https://shaped.ai/blog/the-vector-bottleneck-limitations-of-embedding-based-retrieval)

### 임베딩 공간 분포

- [Length-Induced Embedding Collapse in PLM-based Models (arXiv 2410.24200)](https://arxiv.org/html/2410.24200v2)
- [Semantic Shift: the Fundamental Challenge in Text Embedding and Retrieval (arXiv 2603.21437)](https://arxiv.org/pdf/2603.21437)
- [What you can cram into a single $&!#* vector (Conneau et al., ACL 2018)](https://arxiv.org/abs/1805.01070)
- [How Contextual are Contextualized Word Representations? (Ethayarajh, EMNLP 2019)](https://ai.stanford.edu/blog/contextual)

### LangChain / LangGraph v1

- [LangChain v1 migration guide](https://docs.langchain.com/oss/python/migrate/langchain-v1)
- [What's new in LangGraph v1](https://docs.langchain.com/oss/python/releases/langgraph-v1)
- [LangChain and LangGraph Agent Frameworks Reach v1.0 Milestones](https://www.langchain.com/blog/langchain-langgraph-1dot0)
- [GeekNews: LangChain 1.0 / LangGraph 1.0 요약](https://news.hada.io/topic?id=23886)
