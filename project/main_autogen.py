import os
import random
import uuid
import logging
import pandas as pd
import openai
from typing import Dict, List, Optional, Union, Any
from dotenv import load_dotenv # 추가된 라이브러리
from autogen import GroupChat, GroupChatManager, ConversableAgent

# 사용자 정의 모듈 임포트
from database.neo4j_setup import MafiaGraphManager
from database.milvus_setup import MafiaVectorManager
from rag.hybrid_engine import MafiaHybridRAG
from agents.state_manager import MafiaStateManager
from agents.speaker_selection import make_speaker_selection_func

# ---------------------------------------------------------
# [보안 설정] .env 파일에서 환경 변수 로드
# ---------------------------------------------------------
load_dotenv()

API_KEY = os.environ.get("OPENAI_API_KEY")
NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PWD = os.environ.get("NEO4J_PWD")
MILVUS_ENDPOINT = os.environ.get("MILVUS_ENDPOINT")
MILVUS_TOKEN = os.environ.get("MILVUS_TOKEN")

logging.getLogger("neo4j").setLevel(logging.ERROR)

# =================================================================
# 1. MafiaRAGAgent: 에러 방지 및 팀 인지 로직 통합
# =================================================================
class MafiaRAGAgent(ConversableAgent):
    def __init__(self, name, role, rag_engine, state_mgr, session_id, **kwargs):
        super().__init__(name, **kwargs)
        self.real_role = role      
        self.fake_role = None      
        self.rag_engine = rag_engine
        self.state_mgr = state_mgr
        self.session_id = session_id
        self.turn_count = 0
        self.is_dead = False
        self.teammates = []

    def generate_reply(self, messages=None, sender=None, **kwargs) -> Union[str, Dict, None]:
        if self.is_dead: return "..."
        if messages is None:
            messages = self._oai_messages[sender] if sender else []
            
        self.turn_count += 1
        last_message = messages[-1]['content'] if messages else "게임 시작"
        alive_players = [n for n in self.state_mgr.agent_names if n not in self.state_mgr.dead_agents]
        
        # 역할별 특수 지침 생성
        special_instruction = ""
        if self.real_role == "마피아":
            tm_info = f"동료 마피아: {self.teammates}"
            if self.fake_role == "경찰":
                special_instruction = f"\n[🚨 사칭 마피아]: {tm_info}. 가짜 경찰 연기를 하세요. 동료는 시민이라고 거짓 보고하세요."
            else:
                special_instruction = f"\n[💀 마피아]: {tm_info}. 시민인 척하며 동료를 보호하세요."
        elif self.real_role == "경찰":
            special_instruction = "\n[📢 경찰]: 조사 결과를 발표하고 사칭자를 찾아내세요."
        elif self.real_role == "의사":
            special_instruction = "\n[💉 의사]: 살해 대상을 예측해 치료하세요."
        else:
            special_instruction = "\n[🧐 시민]: 논리적인 모순을 찾아 마피아를 검거하세요."

        persona_guide = f"현 생존자: {alive_players}. 당신은 {self.name}({self.real_role})입니다. {special_instruction}"
        
        # RAG 엔진 쿼리
        rag_context = self.rag_engine.query(f"{persona_guide}\n상황: {last_message}", requester_name=self.name, session_id=self.session_id)
        self.update_system_message(f"당신은 {self.name}입니다.\n분석: {rag_context}\n지침: {special_instruction}")
        
        # 부모 클래스 호출 및 에러 방지 (List vs Dict 처리)
        reply = super().generate_reply(messages=messages, sender=sender, **kwargs)
        
        reply_text = ""
        if isinstance(reply, dict):
            reply_text = reply.get("content", "")
        elif isinstance(reply, list):
            reply_text = reply[0].get("content", "") if len(reply) > 0 else ""
        else:
            reply_text = str(reply) if reply else ""

        if reply_text:
            self._record_and_update(reply_text[:3900])
        return reply_text

    def _record_and_update(self, content):
        try:
            emb = self.rag_engine._get_embedding(content)
            claimed = self.fake_role if self.fake_role else "시민"
            self.rag_engine.neo4j.record_statement(self.name, content, self.turn_count, claimed_role=claimed)
            self.rag_engine.milvus.insert_statement(self.name, content, self.turn_count, emb, claimed, self.session_id)
            self.state_mgr.update_state_from_text(self.name, content)
        except Exception as e:
            print(f"⚠️ [{self.name}] 데이터 갱신 실패: {e}")

# =================================================================
# 2. 게임 보조 함수 (종료 체크, 밤 단계, 투표)
# =================================================================
def check_game_over(agents):
    alive = [a for a in agents if not a.is_dead]
    mafias = [a for a in alive if a.real_role == "마피아"]
    citizens = [a for a in alive if a.real_role != "마피아"]
    if not mafias: print("\n🏆 [결과] 시민 승리!"); return True
    if len(mafias) >= len(citizens): print("\n💀 [결과] 마피아 승리!"); return True
    return False

def simulate_night_phase(agents, neo4j_mgr):
    alive = [a for a in agents if not a.is_dead]
    mafias = [a for a in alive if a.real_role == "마피아"]
    citizens = [a for a in alive if a.real_role != "마피아"]
    victim = None
    if mafias and citizens:
        victim = random.choice(citizens)
        victim.is_dead = True
        print(f"\n🌙 [NIGHT] {victim.name}님이 마피아에게 살해당했습니다.")
    police = next((a for a in alive if a.real_role == "경찰"), None)
    p_info = None
    if police:
        target = random.choice([a for a in alive if a.name != police.name])
        p_info = {"target": target.name, "role": neo4j_mgr.get_actual_role(target.name)}
    return victim, p_info

def conduct_vote(state_mgr, agents):
    alive = [a for a in agents if not a.is_dead]
    if not alive: return None
    print("\n🗳️ [투표 시작]")
    votes = {a.name: 0 for a in alive}
    for a in alive:
        voted_for = state_mgr.decide_vote(a.name)
        if voted_for in votes:
            votes[voted_for] += 1
            print(f"- {a.name} -> {voted_for}")
    exiled_name = max(votes, key=votes.get)
    exiled_agent = next(a for a in agents if a.name == exiled_name)
    exiled_agent.is_dead = True
    print(f"💀 [추방] {exiled_name} (정체: {exiled_agent.real_role})")
    return exiled_name

# =================================================================
# 3. 메인 세션 실행
# =================================================================
def start_mafia_session():
    current_session = f"game_{uuid.uuid4().hex[:8]}"
    neo4j_mgr = MafiaGraphManager(NEO4J_URI, NEO4J_USER, NEO4J_PWD)
    milvus_mgr = MafiaVectorManager(MILVUS_ENDPOINT, MILVUS_TOKEN)
    rag_engine = MafiaHybridRAG(neo4j_mgr, milvus_mgr, API_KEY)
    
    player_names = [f"Player_{i+1}" for i in range(8)]
    state_mgr = MafiaStateManager(neo4j_mgr, player_names, client=openai.OpenAI(api_key=API_KEY))
    neo4j_mgr.initialize_schema()
    
    roles = ["마피아", "마피아", "경찰", "의사", "시민", "시민", "시민", "시민"]
    random.shuffle(roles)
    agents, mafia_names = [], []

    for i, role in enumerate(roles):
        name = f"Player_{i+1}"
        agent = MafiaRAGAgent(name, role, rag_engine, state_mgr, current_session,
                              llm_config={"config_list": [{"model": "gpt-4o-mini", "api_key": API_KEY}]})
        agents.append(agent)
        if role == "마피아": mafia_names.append(name)
        neo4j_mgr.create_agent(name, role)

    for a in agents:
        if a.real_role == "마피아": a.teammates = [m for m in mafia_names if m != a.name]

    actual_roles_map = {a.name: a.real_role for a in agents}
    state_mgr.set_mafia_team(mafia_names)

    class MafiaGroupChatManager(GroupChatManager):
        def _process_message_before_send(self, message, recipient, silent=False):
            last_msg = self.groupchat.messages[-1] if self.groupchat.messages else {}
            sender, content = last_msg.get("name"), last_msg.get("content")
            if sender and content and recipient.name == player_names[0]:
                print(f"\n📝 [{sender}] 발언 분석 중...")
                df = state_mgr.get_summary_table(actual_roles_map)
                print(df.to_markdown(index=False))
            return super()._process_message_before_send(message, recipient, silent)

    # --- GAME LOOP ---
    day = 1
    while not check_game_over(agents):
        print(f"\n" + "★"*25 + f" DAY {day} START " + "★"*25)
        
        # 밤 단계
        victim, p_info = simulate_night_phase(agents, neo4j_mgr)
        if victim: state_mgr.handle_night_death(victim.name, victim.real_role)
        if check_game_over(agents): break

        # 정보 주입
        alive_agents = [a for a in agents if not a.is_dead]
        for a in alive_agents:
            if a.real_role == "경찰" and p_info:
                a.update_system_message(f"{a.system_message}\n[조사 결과]: {p_info['target']}은 {p_info['role']}입니다.")
            if day == 1 and a.real_role == "마피아" and not a.fake_role:
                a.fake_role = "경찰"

        # 낮 토론
        groupchat = GroupChat(agents=alive_agents, messages=[], max_round=8, speaker_selection_method=make_speaker_selection_func(state_mgr))
        manager = MafiaGroupChatManager(groupchat=groupchat, name="chat_manager", llm_config={"config_list": [{"model": "gpt-4o-mini", "api_key": API_KEY}]})
        
        starter = random.choice(alive_agents)
        starter.initiate_chat(recipient=manager, message="어젯밤 사건에 대해 토론을 시작합시다.")

        # 투표
        exiled = conduct_vote(state_mgr, agents)
        if exiled:
            exiled_agent = next(a for a in agents if a.name == exiled)
            state_mgr.handle_night_death(exiled, exiled_agent.real_role)
        
        day += 1

if __name__ == "__main__":
    start_mafia_session()