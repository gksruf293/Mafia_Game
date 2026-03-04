from neo4j import GraphDatabase, basic_auth
import logging

logging.getLogger("neo4j").setLevel(logging.WARNING)

class MafiaGraphManager:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=basic_auth(user, password))

    def close(self):
        self.driver.close()

    def initialize_schema(self):
        """데이터베이스 초기화 및 기본 제약 조건/역할 생성"""
        with self.driver.session(database="neo4j") as session:
            session.execute_write(lambda tx: tx.run("MATCH (n) DETACH DELETE n"))
            session.execute_write(lambda tx: tx.run(
                "CREATE CONSTRAINT agent_name_unique IF NOT EXISTS FOR (a:Agent) REQUIRE a.name IS UNIQUE"
            ))
            roles = ["마피아", "경찰", "의사", "시민"]
            for role in roles:
                session.execute_write(lambda tx: tx.run("MERGE (r:Role {name: $name})", name=role))
            logging.info("✅ Neo4j 스키마 및 기본 역할 노드 초기화 완료.")

    def create_agent(self, name, actual_role):
        """새로운 에이전트 노드 생성 및 실제 직업 연결"""
        query = """
        MATCH (r:Role {name: $actual_role})
        CREATE (a:Agent {
            name: $name, 
            status: 'ALIVE', 
            suspicion_score: 0, 
            trust_score: 50,
            fake_persona: '시민'
        })
        CREATE (a)-[:HAS_ACTUAL_ROLE]->(r)
        """
        with self.driver.session(database="neo4j") as session:
            session.execute_write(lambda tx: tx.run(query, name=name, actual_role=actual_role))

    def record_statement(self, speaker_name, content, turn, claimed_role=None, target_name=None, action_type=None):
        """발언 내용과 그에 따른 관계(주장, 비난, 보증)를 기록"""
        with self.driver.session(database="neo4j") as session:
            # 1. 발언 노드 생성
            session.execute_write(lambda tx: tx.run("""
                MATCH (speaker:Agent {name: $speaker_name})
                CREATE (s:Statement {content: $content, turn: $turn, timestamp: timestamp()})
                CREATE (speaker)-[:STATED]->(s)
            """, speaker_name=speaker_name, content=content, turn=turn))

            # 2. 본인의 직업 주장 기록
            if claimed_role:
                session.execute_write(lambda tx: tx.run("""
                    MATCH (a:Agent {name: $name})
                    MATCH (r:Role {name: $role})
                    MERGE (a)-[rel:CLAIMED_ROLE]->(r)
                    SET rel.turn = $turn
                """, name=speaker_name, role=claimed_role, turn=turn))

            # 3. 타인에 대한 비난/보증 기록
            if target_name and target_name != speaker_name and action_type in ['ACCUSE', 'VOUCH']:
                rel_type = "ACCUSES" if action_type == 'ACCUSE' else "VOUCHES_FOR"
                session.execute_write(lambda tx: tx.run(f"""
                    MATCH (a:Agent {{name: $speaker}})
                    MATCH (t:Agent {{name: $target}})
                    MERGE (a)-[r:{rel_type}]->(t)
                    SET r.turn = $turn, r.content = $content
                """, speaker=speaker_name, target=target_name, turn=turn, content=content))

    def record_claim(self, actor_name, target_name, claimed_role, is_mafia_claim=None):
        """StateManager에서 호출하는 메서드. 직업 주장과 관계 형성을 분리"""
        if actor_name == target_name:
            return self.record_statement(
                speaker_name=actor_name,
                content=f"System: {actor_name} claims to be {claimed_role}",
                turn=1,
                claimed_role=claimed_role,
                target_name=None,
                action_type=None
            )
        
        action_type = 'ACCUSE' if is_mafia_claim is True else ('VOUCH' if is_mafia_claim is False else None)
        return self.record_statement(
            speaker_name=actor_name,
            content=f"System: {actor_name} claims {target_name} is {claimed_role}",
            turn=1,
            claimed_role=None,
            target_name=target_name,
            action_type=action_type
        )

    # --- 추가 및 강화된 핵심 쿼리 메서드 ---

    def get_opinions_on_target(self, target_name):
        """
        [핵심] 특정 대상(사망자)에 대해 비난하거나 보증했던 모든 발언자들을 찾습니다.
        사망자의 정체가 공개되었을 때 신뢰도 보정의 근거 데이터가 됩니다.
        """
        query = """
        MATCH (speaker:Agent)-[r:ACCUSES|VOUCHES_FOR]->(target:Agent {name: $target_name})
        RETURN speaker.name AS speaker_name, type(r) AS action_type
        """
        with self.driver.session(database="neo4j") as session:
            results = session.execute_read(lambda tx: list(tx.run(query, target_name=target_name)))
            # return 형태: {'Player_1': {'is_mafia_claim': True}, 'Player_2': {'is_mafia_claim': False}}
            return {
                res["speaker_name"]: {"is_mafia_claim": True if res["action_type"] == "ACCUSES" else False}
                for res in results
            }

    def update_agent_status(self, agent_name, status="DEAD"):
        """사망한 에이전트의 상태를 DB에 업데이트"""
        query = "MATCH (a:Agent {name: $name}) SET a.status = $status"
        with self.driver.session(database="neo4j") as session:
            session.execute_write(lambda tx: tx.run(query, name=agent_name, status=status))

    def get_all_claimed_roles(self):
        """현재 모든 에이전트가 주장하고 있는 직업 현황 조회"""
        query = """
        MATCH (a:Agent)-[r:CLAIMED_ROLE]->(role:Role)
        RETURN a.name AS name, role.name AS role_name
        """
        with self.driver.session(database="neo4j") as session:
            results = session.execute_read(lambda tx: list(tx.run(query)))
            return {record["name"]: record["role_name"] for record in results}

    def get_actual_role(self, agent_name):
        """에이전트의 실제 정체 확인"""
        query = "MATCH (a:Agent {name: $name})-[:HAS_ACTUAL_ROLE]->(r:Role) RETURN r.name AS role"
        with self.driver.session(database="neo4j") as session:
            result = session.execute_read(lambda tx: tx.run(query, name=agent_name).single())
            return result["role"] if result else "시민"

    def setup_mafia_team(self, mafia_names):
        """마피아 팀 간의 관계 설정"""
        query = """
        MATCH (a:Agent {name: $name1}), (b:Agent {name: $name2})
        MERGE (a)-[:IS_TEAM_WITH]->(b)
        """
        with self.driver.session(database="neo4j") as session:
            for i, name1 in enumerate(mafia_names):
                for name2 in mafia_names[i+1:]:
                    session.execute_write(lambda tx: tx.run(query, name1=name1, name2=name2))
                    session.execute_write(lambda tx: tx.run(query, name1=name2, name2=name1))