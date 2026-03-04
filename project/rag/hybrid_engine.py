# project/rag/hybrid_engine.py

import openai
from database.neo4j_setup import MafiaGraphManager
from database.milvus_setup import MafiaVectorManager

class MafiaHybridRAG:
    def __init__(self, neo4j_mgr, milvus_mgr, openai_api_key):
        """
        Neo4j(그래프)와 Milvus(벡터)를 결합하여 하이브리드 검색을 수행합니다.
        수치 기반의 사회적 상호작용 및 팀 관계 추론 기능을 포함합니다.
        """
        self.neo4j = neo4j_mgr
        self.milvus = milvus_mgr
        self.client = openai.OpenAI(api_key=openai_api_key)

    def _generate_cypher(self, question):
        """
        자연어 질의를 고도화된 스키마 기반의 Cypher 쿼리로 변환합니다. (Text-to-Cypher)
        """
        system_prompt = """
        당신은 마피아 게임 분석 전문가이자 Neo4j 전문가입니다. 아래 스키마를 바탕으로 자연어 질문을 Cypher 쿼리로 변환하세요.
        
        [Nodes]
        - Agent {name, status, suspicion_score, framing_score}
        - Statement {content, turn}
        - Role {name}
        
        [Relationships]
        - (Agent)-[:STATED]->(Statement)
        - (Agent)-[:CLAIMED_ROLE]->(Role)
        - (Agent)-[:IS_TEAM_WITH]->(Agent) : 마피아 팀원 간의 비밀 관계
        
        [Query Rules]
        1. 의심스러운 사람을 찾을 때는 suspicion_score가 높은 순으로 정렬하세요.
        2. 마피아 팀원 관계(IS_TEAM_WITH)는 발언자 본인에게만 유효한 정보임을 명심하세요.
        3. 결과값은 반드시 Cypher 쿼리문만 반환하세요.
        """
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"질문: {question}"}
            ]
        )
        return response.choices[0].message.content.strip().replace("```cypher", "").replace("```", "")

    def _get_embedding(self, text):
        """텍스트 임베딩 생성 (OpenAI v3 small)"""
        response = self.client.embeddings.create(
            input=[text],
            model="text-embedding-3-small"
        )
        return response.data[0].embedding

    def query(self, question, requester_name=None, session_id=None):
        """
        Hybrid Retrieval 수행:
        1. Graph Search: 논리적 모순, 수치(의심/누명), 팀 관계 분석.
        2. Vector Search: 과거 발언의 맥락적 유사성 검색.
        """
        # 1. Graph Retrieval
        cypher_query = self._generate_cypher(question)
        graph_results = []
        try:
            # 드라이버 세션 방식 업데이트 (execute_read 사용 권장)
            with self.neo4j.driver.session(database="neo4j") as session:
                graph_results = session.execute_read(lambda tx: tx.run(cypher_query).data())
        except Exception as e:
            graph_results = [{"error": str(e)}]

        # 2. Vector Retrieval
        query_embedding = self._get_embedding(question)
        # 현재 세션 데이터만 가져오도록 expr 설정
        filter_expr = f"session_id == '{session_id}'"
        vector_results = self.milvus.search_similar_statements(
            query_embedding, 
            limit=5,
            expr=filter_expr
        )

        # 3. 결과 융합 및 최종 답변 생성
        # 요청자가 누구인지에 따라 '팀 정보' 노출 여부를 판단할 수 있도록 컨텍스트 구성
        context = f"""
        [요청자]: {requester_name if requester_name else '시스템'}
        
        [그래프 DB 분석 결과]:
        {graph_results}
        
        [벡터 DB 유사 발언 결과]:
        {[{'agent': r['agent'], 'text': r['text'], 'claimed': r.get('claimed_role')} for r in vector_results]}
        """
        
        final_response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "당신은 마피아 게임의 전략적 분석가입니다. "
                        "그래프의 수치(suspicion_score 등)와 벡터 검색된 과거 발언의 모순을 비교하여 "
                        "매우 논리적이고 설득력 있는 답변을 제공하세요."
                    )
                },
                {"role": "user", "content": f"질문: {question}\n\n배경 정보: {context}"}
            ]
        )
        
        return final_response.choices[0].message.content

# --- 실행 예시 ---
if __name__ == "__main__":
    # 설정 정보 및 인스턴스 초기화 가정
    # rag_engine = MafiaHybridRAG(neo4j_mgr, milvus_mgr, "api-key")
    
    # 예시 질문: "현재 의심 수치가 가장 높은 3명과 그들이 과거에 한 수상한 발언을 대조해줘."
    # answer = rag_engine.query("가장 의심 수치가 높은 에이전트들의 목록과 모순되는 과거 발언을 찾아줘.")
    pass