from autogen import ConversableAgent
from typing import Dict, List, Optional, Union, Any

class MafiaRAGAgent(ConversableAgent):
    def __init__(self, name, role, rag_engine, state_mgr, session_id, **kwargs):
        super().__init__(name, **kwargs)
        self.real_role = role      # 실제 정체 (마피아, 경찰, 의사, 시민)
        self.fake_role = None      # 사칭 중인 역할 (주로 마피아가 사용)
        self.rag_engine = rag_engine
        self.state_mgr = state_mgr
        self.session_id = session_id  # 현재 게임 세션 고유 ID
        self.turn_count = 0

    def generate_reply(self, messages=None, sender=None, **kwargs) -> Union[str, Dict, None]:
        if self.is_dead: return "..."
        
        # 1. 메시지 정규화
        if messages is None:
            messages = self._oai_messages[sender] if sender else []
            
        self.turn_count += 1
        
        # 2. 답변 생성 (부모 클래스 호출)
        reply = super().generate_reply(messages=messages, sender=sender, **kwargs)
        
        # 3. [에러 해결] 리스트/딕셔너리/문자열 형식에 따른 안전한 텍스트 추출
        reply_text = ""
        if isinstance(reply, list):
            # 리스트인 경우 첫 번째 요소의 content 추출
            if len(reply) > 0 and isinstance(reply[0], dict):
                reply_text = reply[0].get("content", "")
            else:
                reply_text = str(reply[0]) if reply else ""
        elif isinstance(reply, dict):
            reply_text = reply.get("content", "")
        else:
            reply_text = str(reply) if reply else ""

        # 4. 후속 처리 (에러가 나도 게임이 멈추지 않도록 try-except 처리)
        if reply_text:
            try:
                self._record_and_update(reply_text[:3900])
            except Exception as e:
                print(f"⚠️ [{self.name}] 사후 처리 중 오류(무시 가능): {e}")
            
        return reply_text # 문자열로 반환하여 GroupChatManager와의 호환성 확보

    def _set_mafia_persona(self):
        # 1. 강력한 정체성 주입 (이름을 대괄호로 강조)
        base_instruction = f"당신은 마피아 게임의 플레이어 **{self.name}**입니다. 절대로 본인을 제3자처럼 말하지 마십시오."
        
        if getattr(self, "fake_role", "") == "경찰":
            persona_extension = f"""
            [🚨 사칭 마피아 필수 행동 지침]
            - 당신({self.name})은 지금 '경찰'을 사칭하고 있습니다.
            - 만약 **당신({self.name}) 이외의 다른 사람**이 경찰이라고 주장하면, 즉시 반박하십시오.
            - 방금 당신이 한 말을 부정하거나 본인에게 질문하지 마십시오.
            - 당신은 어제 [허위 조사 대상]을 조사했다고 주장해야 합니다.
            """
            self.update_system_message(base_instruction + persona_extension)

    def _record_and_update(self, reply_content):
        """발언 내용을 DB에 기록하고 상태 매니저를 업데이트합니다."""
        try:
            emb = self.rag_engine._get_embedding(reply_content)
            
            # 주장 직업 판단 (사칭 중이면 사칭 역할 우선, 아니면 키워드 추출)
            claimed = self.fake_role if self.fake_role else "시민"
            for role in ["경찰", "의사", "마피아"]:
                if role in reply_content:
                    claimed = role
                    break
            
            # Neo4j 기록 (그래프 상에 주장 정보 업데이트)
            self.rag_engine.neo4j.record_statement(
                self.name, 
                reply_content, 
                self.turn_count, 
                claimed_role=claimed
            )
            
            # Milvus 기록 (Vector DB에 세션 ID와 함께 저장)
            self.rag_engine.milvus.insert_statement(
                agent_name=self.name, 
                text=reply_content, 
                turn=self.turn_count, 
                embedding=emb, 
                claimed_role=claimed,
                session_id=self.session_id
            )
            
            # 전체 게임 상태(의심 수치 등) 업데이트
            self.state_mgr.update_scores(self.name, reply_content)
            
        except Exception as e:
            print(f"⚠️ [{self.name}] DB 기록 중 오류 발생: {e}")