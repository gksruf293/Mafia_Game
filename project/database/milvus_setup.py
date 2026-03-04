# project/database/milvus_setup.py

from pymilvus import connections, FieldSchema, CollectionSchema, DataType, Collection, utility
import os

class MafiaVectorManager:
    def __init__(self, cluster_endpoint, token):
        """
        Zilliz Cloud(Milvus) 연결 관리자.
        8인 게임의 방대한 발언 데이터를 저장하고, 유사도 기반 검색을 수행합니다.
        """
        self.cluster_endpoint = cluster_endpoint
        self.token = token
        self.collection_name = "mafia_statements"
        self.dim = 1536  # OpenAI text-embedding-3-small 모델 차원
        
        self._connect()
        self._setup_collection()

    def _connect(self):
        """Milvus 클러스터에 연결합니다."""
        connections.connect(
            alias="default",
            uri=self.cluster_endpoint,
            token=self.token
        )
        print("✅ Milvus(Zilliz) 클라우드 연결 완료.")

    def _setup_collection(self):
        """
        발언 데이터를 저장할 컬렉션 스키마를 설계합니다.
        추후 '의심 수치' 분석을 위해 발언 당시의 정황 정보를 포함합니다.
        """
        if utility.has_collection(self.collection_name):
            # 초기화 시 기존 데이터 삭제 (필요에 따라 주석 처리)
            utility.drop_collection(self.collection_name)

        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="session_id", dtype=DataType.VARCHAR, max_length=100), # 세션 식별자 추가
            FieldSchema(name="agent_name", dtype=DataType.VARCHAR, max_length=100),
            FieldSchema(name="statement_text", dtype=DataType.VARCHAR, max_length=4000),
            FieldSchema(name="turn", dtype=DataType.INT64),
            FieldSchema(name="claimed_role", dtype=DataType.VARCHAR, max_length=50), # 발언자가 주장한 직업
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.dim)
        ]

        schema = CollectionSchema(fields, description="마피아 게임 에이전트 발언 로그 및 메타데이터")
        self.collection = Collection(self.collection_name, schema)

        # 고성능 검색을 위한 HNSW 인덱스 설정
        index_params = {
            "metric_type": "COSINE",
            "index_type": "HNSW",
            "params": {"M": 8, "efConstruction": 64}
        }
        self.collection.create_index(field_name="embedding", index_params=index_params)
        self.collection.load()
        print(f"✅ Milvus 컬렉션 '{self.collection_name}' 설정 및 로드 완료 (8인 모드 준비).")

    def insert_statement(self, agent_name, text, turn, embedding, claimed_role="시민", session_id="session_001"):
        """
        에이전트의 발언, 주장하는 직업, 임베딩 벡터를 삽입합니다.
        """
        data = [[session_id], [agent_name], [text], [turn], [claimed_role], [embedding]]
        self.collection.insert(data)
        self.collection.flush()

    def search_similar_statements(self, query_embedding, limit=5, expr=None):
        """
        질의와 유사한 과거 발언을 검색하여 논리적 일관성을 체크할 근거를 마련합니다.
        """
        search_params = {"metric_type": "COSINE", "params": {"ef": 64}}
        
        results = self.collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=limit,
            expr=expr, # 필터링 표현식 적용
            output_fields=["agent_name", "statement_text", "turn", "claimed_role"]
        )
        
        retrieved_data = []
        for hits in results:
            for hit in hits:
                retrieved_data.append({
                    "agent": hit.entity.get("agent_name"),
                    "text": hit.entity.get("statement_text"),
                    "turn": hit.entity.get("turn"),
                    "claimed_role": hit.entity.get("claimed_role"),
                    "score": hit.score
                })
        return retrieved_data

# --- 실행부 (테스트용) ---
if __name__ == "__main__":
    # 실제 연동 시 환경 변수나 설정 파일에서 로드 권장
    CLUSTER_ENDPOINT = "https://your-cluster-uri.zillizcloud.com"
    TOKEN = "your-zilliz-api-key"

    import random
    def get_mock_embedding():
        return [random.uniform(-1, 1) for _ in range(1536)]

    vector_mgr = MafiaVectorManager(CLUSTER_ENDPOINT, TOKEN)

    # 마피아의 경찰 사칭 시나리오 데이터 삽입
    vector_mgr.insert_statement(
        agent_name="Agent_1",
        text="내가 진짜 경찰입니다. 어제 조사 결과 Agent_3은 마피아입니다.",
        turn=1,
        embedding=get_mock_embedding(),
        claimed_role="경찰"
    )

    # 유사도 검색
    query_vector = get_mock_embedding()
    search_results = vector_mgr.search_similar_statements(query_vector)

    print("\n🔍 Milvus 검색 결과 (Context Retrieval):")
    for res in search_results:
        print(f"[{res['agent']}] (주장: {res['claimed_role']}, Turn {res['turn']}): {res['text']} (Score: {res['score']:.4f})")