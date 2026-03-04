import json
import pandas as pd
from database.neo4j_setup import MafiaGraphManager

class MafiaStateManager:
    def __init__(self, neo4j_mgr: MafiaGraphManager, agent_names: list, client):
        self.neo4j = neo4j_mgr
        self.agent_names = agent_names
        self.client = client
        # 초기 의심도 20점
        self.scores = {me: {other: 20 for other in agent_names} for me in agent_names}
        
        # [수정] 에러 해결을 위해 speaker_history 속성 추가
        self.speaker_history = {name: 0 for name in agent_names}
        
        self.dead_agents = []
        self.mafia_team = []
        # 대립 구도 추적 (진경 vs 가경)
        self.police_claims = [] 

    def set_mafia_team(self, mafia_names):
        """마피아 팀 정보 설정 (시스템용)"""
        self.mafia_team = mafia_names

    def update_state_from_text(self, speaker_name, content):
        if speaker_name in self.dead_agents: return
        
        # 발언 횟수 기록
        self.speaker_history[speaker_name] = self.speaker_history.get(speaker_name, 0) + 1

        # GPT에게 정확한 타겟팅 형식을 강조
        prompt = f"""
        분석 대상: {speaker_name}의 발언
        규칙:
        1. target_info의 name은 반드시 {self.agent_names} 중 하나여야 합니다.
        2. 상대방을 의심하면 'ACCUSE', 믿으면 'VOUCH'로 분류하세요.
        """

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "Return ONLY JSON."},
                          {"role": "user", "content": prompt + f"\nContent: {content}"}],
                response_format={"type": "json_object"}
            )
            res = json.loads(response.choices[0].message.content)

            # 1. 본인 주장 업데이트 (대립 구도 감지 포함)
            claim = res.get("self_claim")
            if claim:
                self.neo4j.record_claim(speaker_name, speaker_name, claim)
                if claim == "경찰" and speaker_name not in self.police_claims:
                    self.police_claims.append(speaker_name)
                    print(f"🚨 [대립 감지] {speaker_name} 경찰 선언!")
                    if len(self.police_claims) > 1:
                        print(f"🔥 [진검 승부] {', '.join(self.police_claims)} 맞경 구도 형성!")

            # 2. 타인 지목 및 점수 업데이트
            t_info = res.get("target_info", {})
            target = t_info.get("name")
            if target and target in self.agent_names and target != speaker_name:
                action = t_info.get("action", "NONE")
                is_mafia = True if action == "ACCUSE" else (False if action == "VOUCH" else None)
                self.neo4j.record_claim(speaker_name, target, t_info.get("inferred_role") or "미표명", is_mafia_claim=is_mafia)

                if action in ["ACCUSE", "VOUCH"]:
                    self.update_scores(speaker_name, target, action)

            t_info = res.get("target_info", {})
            target = t_info.get("name")
            if target and target in self.agent_names:
                print(f"✅ {speaker_name} -> {target} 상호작용 감지 ({t_info.get('action')})")
                self.update_scores(speaker_name, target, t_info.get("action"))

        except Exception as e:
            print(f"⚠️ [분석 에러] {speaker_name}: {e}")

    def update_scores(self, speaker, target, action_type):
        """대립 상황 시 가중치 반영하여 점수 업데이트"""
        multiplier = 1.5 if speaker in self.police_claims else 1.0
        impact = (25 if action_type == "ACCUSE" else -30) * multiplier

        for observer in self.agent_names:
            if observer in [speaker, target] or observer in self.dead_agents: continue
            trust_factor = (100 - self.scores[observer][speaker]) / 100
            change = int(impact * max(0.2, trust_factor))
            new_val = self.scores[observer][target] + change
            self.scores[observer][target] = max(0, min(100, new_val))

    def handle_night_death(self, victim_name, actual_role):
        """사망자 발생 처리 및 정체 공개에 따른 점수 전수 보정"""
        if victim_name not in self.dead_agents:
            self.dead_agents.append(victim_name)
        if victim_name in self.police_claims:
            self.police_claims.remove(victim_name)

        print(f"\n💀 [밤의 결과] {victim_name}님 사망 (정체: {actual_role})")

        opinions = self.neo4j.get_opinions_on_target(victim_name)
        for speaker, data in opinions.items():
            if speaker in self.dead_agents: continue
            was_accusing = data.get('is_mafia_claim')
            
            for observer in self.agent_names:
                if observer in self.dead_agents or observer == speaker: continue
                curr = self.scores[observer][speaker]
                if actual_role != "마피아":
                    self.scores[observer][speaker] = min(100, curr + 40) if was_accusing else max(0, curr - 25)
                else:
                    self.scores[observer][speaker] = max(0, curr - 45) if was_accusing else min(100, curr + 50)

    def get_summary_table(self, agents_actual_roles):
        """매트릭스 도표 생성"""
        claimed_roles = self.neo4j.get_all_claimed_roles()
        data = []
        for name in self.agent_names:
            status = "💀" if name in self.dead_agents else "ALIVE"
            short_me = name.replace("Player_", "P")
            row = {"Name": f"{short_me}({status})", "Actual": agents_actual_roles.get(name), "Claim": claimed_roles.get(name, "-")}
            for target in self.agent_names:
                short_target = target.replace("Player_", "P")
                row[f"vs {short_target}"] = "Me" if name == target else self.scores[name].get(target, 20)
            data.append(row)
        return pd.DataFrame(data)