import random

def make_speaker_selection_func(state_mgr):
    """
    상태 기반 대립 감지, 지루함 감지, 중재자 선정이 통합된 고도화 화자 선택 함수.
    자기 자신에 대한 역공(Self-Counter) 방지 로직이 추가되었습니다.
    """
    def custom_selector(last_speaker, groupchat):
        # 1. 기본 데이터 준비
        all_agents = groupchat.agents
        agent_names = [a.name for a in all_agents]
        last_speaker_name = last_speaker.name

        # 현재 Neo4j에 기록된 직업 주장 현황 가져오기
        claimed_roles = state_mgr.neo4j.get_all_claimed_roles()
        police_claimants = [name for name, role in claimed_roles.items() if role == "경찰"]

        # 2. [사칭 역공 로직] 
        # 누군가 경찰을 주장했을 때, '나 자신'이 아닌 다른 사칭 마피아가 아직 조용하다면 등판
        if police_claimants:
            # 사칭 역할(fake_role)이 '경찰'이지만 아직 대외적으로 주장하지 않은 마피아 탐색
            target_mafia = next(
                (a for a in all_agents if getattr(a, 'fake_role', None) == "경찰" 
                 and a.name not in police_claimants), 
                None
            )
            
            # 중요: 방금 경찰이라고 말한 사람이 '나 자신'이 아닐 때만 역공 수행
            # 이 조건이 없으면 Player_1이 말하자마자 시스템이 다시 Player_1을 불러서 자기 반박을 시킵니다.
            if target_mafia and last_speaker_name in police_claimants and target_mafia.name != last_speaker_name:
                print(f"⚡ [대립 발생] {target_mafia.name}가 {last_speaker_name}의 주장에 역공을 시도합니다!")
                return target_mafia

        # 3. [지루함 감지] 유력 용의자가 해명(1회 발언)을 마쳤다면 즉시 투표로!
        suspects = []
        for target in agent_names:
            others_scores = [
                state_mgr.scores[voter][target] 
                for voter in agent_names if target in state_mgr.scores[voter]
            ]
            avg_suspicion = sum(others_scores) / len(others_scores) if others_scores else 0
            if avg_suspicion >= 75: # 문턱값을 살짝 높여 충분한 대화 유도
                suspects.append(target)

        if last_speaker_name in suspects:
            # 용의자가 이미 발언을 1회 이상 기록했다면 (상태 매니저의 history 확인)
            if state_mgr.speaker_history.get(last_speaker_name, 0) >= 1:
                # 단, 경찰 대립 구도일 때는 조금 더 대화를 지켜봄 (최소 2명 이상의 경찰 주장자가 있을 때 제외)
                if len(police_claimants) < 2:
                    print(f"\n🚫 [사회자] 유력 용의자 {last_speaker_name}의 해명이 끝났습니다.")
                    print("📢 투표 단계로 진입합니다.")
                    return None 

        # 4. [중재자 선정] 대립 구도가 심화되었을 때(서로 90점 이상 의심) 중립 시민 등판
        high_conflict_agents = set()
        for me in agent_names:
            for opponent, score in state_mgr.scores[me].items():
                if score >= 90:
                    high_conflict_agents.add(me)
                    high_conflict_agents.add(opponent)

        if last_speaker_name in high_conflict_agents:
            # 대립 당사자가 아닌 중립적인 시민들 중 아직 발언 안 한 사람 우선
            neutrals = [
                a for a in all_agents 
                if a.name not in high_conflict_agents 
                and state_mgr.speaker_history.get(a.name, 0) == 0
            ]
            if neutrals:
                next_speaker = random.choice(neutrals)
                print(f"🎤 [중재] {next_speaker.name}이(가) 상황을 정리하기 위해 발언합니다.")
                return next_speaker

        # 5. [기본 로직] 아직 발언하지 않은 사람 중 '타인에게 의심을 많이 받는 순'으로 선정
        eligible_speakers = [
            a for a in all_agents 
            if a.name != last_speaker_name and state_mgr.speaker_history.get(a.name, 0) == 0
        ]
        
        if eligible_speakers:
            # 타인들로부터의 의심 총합이 가장 높은 에이전트 선택
            next_speaker = max(eligible_speakers, key=lambda a: sum(
                state_mgr.scores[other][a.name] for other in agent_names if a.name in state_mgr.scores[other]
            ))
            return next_speaker

        # 더 이상 발언할 사람이 없으면 자동 종료(투표)
        return None

    return custom_selector