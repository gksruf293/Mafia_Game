# 🕵️‍♂️ Graph-RAG 기반 다자간 논리 추론 및 사회적 상호작용 프레임워크
> **Multi-Agent Logical Reasoning & Social Interaction Framework powered by Graph-RAG**

본 프로젝트는 **AutoGen** 에이전트 환경 내에서 **Neo4j(Graph)**와 **Milvus(Vector)**를 결합한 **Hybrid RAG** 엔진을 통해, 고도의 전략적 판단과 논리적 추론이 요구되는 마피아 게임 시나리오를 시뮬레이션합니다.



---

## 🚀 Key Features

### 1. Hybrid RAG Engine (Module C)
- **Text-to-Cypher:** 자연어 쿼리를 Cypher 문으로 변환하여 Neo4j의 정형화된 논리 팩트 추출.
- **Vector Search:** Milvus를 활용하여 발언의 맥락과 감정적 정황 증거를 `COSINE` 유사도 기반으로 검색.
- **Context Fusion:** 그래프의 관계 데이터와 벡터의 비정형 데이터를 결합하여 에이전트에게 최적화된 추론 근거 제공.

### 2. Graph-based Logical Reasoning (Module A & D)
- **Real-time Contradiction Detection:** `:CLAIMED_ROLE` 관계를 통해 에이전트 간 역할 주장의 모순을 실시간 추적.
- **Social Graph Modeling:** `:KNOWS_PARTNER`, `:VOTED_FOR`, `:SUSPECTS` 등의 관계를 통해 동적인 사회적 상호작용 기록.
- **Strategic Deception:** 마피아 에이전트가 특정 역할을 사칭하거나 파트너와 정보를 공유하는 전략적 초기화 로직 반영.

### 3. Dynamic Multi-Agent Orchestration (Module D)
- **8-Player Environment:** 마피아(2), 경찰(1), 의사(1), 시민(4)의 동적 역할 할당 및 관리.
- **Agentic Workflow:** AutoGen을 기반으로 한 에이전트 간 자율 토론 및 의사결정 프로세스.

---

## 🛠 Tech Stack

| Category | Technology |
| :--- | :--- |
| **Agent Framework** | `AutoGen` |
| **Graph Database** | `Neo4j` (Cypher Query Language) |
| **Vector Database** | `Milvus` / `Zilliz` |
| **LLM & Embedding** | `OpenAI GPT-4o`, `text-embedding-3-small` |
| **Language** | `Python 3.10+` |

---

## 🏗 System Architecture

### Knowledge Graph Schema (Neo4j)


```cypher
// 핵심 관계 구조 예시
(Agent)-[:CLAIMED_ROLE]->(Role)
(Mafia)-[:KNOWS_PARTNER]->(Mafia)
(Agent)-[:VOTED_FOR {round: 1}]->(Agent)
(Agent)-[:SAID {context_id: "..."}]->(Statement)
