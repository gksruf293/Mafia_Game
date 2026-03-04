# project/test_integration.py
import logging
import warnings
import os

# 1. Python 기본 경고 무시 (주로 라이브러리 내부 Deprecation 경고)
warnings.filterwarnings("ignore")

# 2. HTTPX (OpenAI API call) 로그 수준 조정 (Request/Response 로그 숨기기)
logging.getLogger("httpx").setLevel(logging.WARNING)

# 3. Neo4j Driver 로그 수준 조정 (알림 및 쿼리 정보 숨기기)
# INFO 레벨에서 쏟아지는 SCHEMA 알림과 PERFORMANCE 알림을 차단합니다.
logging.getLogger("neo4j").setLevel(logging.WARNING)

# 4. 루트 로거 설정 (기타 라이브러리의 INFO 로그 차단)
logging.basicConfig(level=logging.WARNING)

import random
from database.neo4j_setup import MafiaGraphManager
from database.milvus_setup import MafiaVectorManager
from rag.hybrid_engine import MafiaHybridRAG
from agents.state_manager import MafiaStateManager
from agents.speaker_selection import make_speaker_selection_func

# 1. 환경 변수 설정 (본인의 정보를 입력하세요)
import os
from dotenv import load_dotenv

# .env 파일로부터 환경 변수를 로드합니다.
load_dotenv()
API_KEY = os.environ.get("OPENAI_API_KEY")
NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PWD = os.environ.get("NEO4J_PWD")
MILVUS_ENDPOINT = os.environ.get("MILVUS_ENDPOINT")
MILVUS_TOKEN = os.environ.get("MILVUS_TOKEN")

def run_mafia_test():
    # 2. 인스턴스 초기화
    neo4j_mgr = MafiaGraphManager(
        NEO4J_URI, 
        NEO4J_USER, 
        NEO4J_PWD
    )
    milvus_mgr = MafiaVectorManager(
        MILVUS_ENDPOINT, 
        MILVUS_TOKEN
    )
    rag_engine = MafiaHybridRAG(neo4j_mgr, milvus_mgr, API_KEY)
    state_mgr = MafiaStateManager(neo4j_mgr)

    # 3. 게임 초기 세팅 (8인)
    print("\n--- [Step 1] 게임 초기화 및 역할 할당 ---")
    neo4j_mgr.initialize_schema()
    
    roles = ["마피아", "마피아", "경찰", "의사", "시민", "시민", "시민", "시민"]
    random.shuffle(roles)
    agent_names = [f"Player_{i+1}" for i in range(8)]
    
    mafia_team = []
    for name, role in zip(agent_names, roles):
        neo4j_mgr.create_agent(name, role)
        state_mgr.scores[name] = {"suspicion": 0, "framing": 0} # 메모리 스코어 초기화
        if role == "마피아":
            mafia_team.append(name)
    
    # 마피아 팀 관계 설정
    neo4j_mgr.setup_mafia_team(mafia_team)
    print(f"배정 완료: {list(zip(agent_names, roles))}")

    # 4. 시나리오 테스트: 마피아의 경찰 사칭 및 누명 씌우기
    print("\n--- [Step 2] 마피아의 전략적 발언 시뮬레이션 ---")
    active_mafia = mafia_team[0]
    target_citizen = next(name for name, role in zip(agent_names, roles) if role == "시민")
    
    # 마피아 발언: "내가 경찰인데, target_citizen이 마피아다!"
    statement = f"제가 진짜 경찰입니다. 어제 조사 결과 {target_citizen}님이 마피아로 나왔어요."
    
    # DB 기록 (Graph & Vector)
    # 실제 연동 시에는 OpenAI 임베딩을 가져와야 하지만, 테스트를 위해 mock_embedding 사용 가능
    mock_embedding = [0.1] * 1536 
    neo4j_mgr.record_statement(active_mafia, statement, turn=1, claimed_role="경찰")
    milvus_mgr.insert_statement(active_mafia, statement, turn=1, embedding=mock_embedding, claimed_role="경찰")
    
    # 수치 업데이트 (마피아가 시민을 공격했으므로 시민의 framing_score 상승)
    state_mgr.update_scores(active_mafia, statement, target_name=target_citizen)
    print(f"발언자: {active_mafia} (마피아)")
    print(f"내용: {statement}")
    print(f"결과: {target_citizen}의 누명 수치(Framing) 상승")

    # 5. 화자 선택 로직 테스트
    print("\n--- [Step 3] 다음 화자 선택 (누명 수치 기반) ---")
    # AutoGen의 GroupChat 객체를 모사한 Mock 클래스
    class MockGroupChat:
        def __init__(self, agents): self.agents = agents
    
    class MockAgent:
        def __init__(self, name): self.name = name

    mock_chat = MockGroupChat([MockAgent(n) for n in agent_names])
    selector_func = make_speaker_selection_func(state_mgr)
    
    next_speaker = selector_func(MockAgent(active_mafia), mock_chat)
    print(f"다음 예상 화자 (반박 기회): {next_speaker.name if hasattr(next_speaker, 'name') else next_speaker}")

    # 6. Hybrid RAG 추론 테스트
    print("\n--- [Step 4] Hybrid RAG를 통한 상황 분석 ---")
    # 시민 입장에서 질문
    detective_query = f"현재 가장 의심스러운 사람은 누구이며, 이유는 무엇인가?"
    analysis = rag_engine.query(detective_query, requester_name=target_citizen)
    print(f"RAG 분석 결과:\n{analysis}")

    neo4j_mgr.close()

if __name__ == "__main__":
    try:
        run_mafia_test()
    except Exception as e:
        print(f"❌ 테스트 중 오류 발생: {e}")