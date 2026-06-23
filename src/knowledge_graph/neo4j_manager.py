from typing import Any, Optional

from neo4j import GraphDatabase
from config.settings import settings


class Neo4jManager:
    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self._uri = uri or settings.neo4j_uri
        self._user = user or settings.neo4j_user
        self._password = password or settings.neo4j_password
        self._driver = None

    def connect(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
            self._driver.verify_connectivity()
        return self._driver

    def get_neighbors(self, entity_name: str, max_hops: int = 2) -> list[dict]:
        """Query entity neighbors supporting both legacy (:RELATES_TO) and new (:SUBJECT_OF/:OBJECT_OF) models."""
        self.connect()
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (s:Entity)
                WHERE toLower(s.name) CONTAINS toLower($name) OR toLower(s.entity_key) CONTAINS toLower($name)
                MATCH path = (s)-[*1..%d]-(o:Entity)
                WHERE s <> o
                RETURN s.name as subject_name, coalesce(s.type, '') as subject_type,
                       o.name as object_name, coalesce(o.type, '') as object_type,
                       [r in relationships(path) | coalesce(r.type, r.predicate, type(r))] as relation_types,
                       length(path) as distance
                LIMIT 50
                """ % max_hops,
                name=entity_name,
            )
            return [
                {
                    "subject_name": r["subject_name"],
                    "subject_type": r["subject_type"],
                    "object_name": r["object_name"],
                    "object_type": r["object_type"],
                    "relation_types": r["relation_types"],
                    "distance": r["distance"],
                    "path_string": f"{r['subject_name']} --{r['relation_types']}--> {r['object_name']} (dist={r['distance']})",
                }
                for r in result
            ]

    def find_paths(self, subject: str, object_: str, max_depth: int = 3) -> list[dict]:
        self.connect()
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH path = shortestPath((s:Entity)-[*..%d]-(o:Entity))
                WHERE toLower(s.name) CONTAINS toLower($subject)
                AND toLower(o.name) CONTAINS toLower($object)
                RETURN [n in nodes(path) | n.name] as nodes,
                       [r in relationships(path) | r.type] as relations,
                       length(path) as distance
                LIMIT 10
                """ % max_depth,
                subject=subject, object=object_,
            )
            return [
                {
                    "nodes": r["nodes"],
                    "relations": r["relations"],
                    "distance": r["distance"],
                }
                for r in result
            ]

    def query(self, cypher: str, params: Optional[dict] = None) -> list[dict]:
        self.connect()
        with self._driver.session() as session:
            result = session.run(cypher, params or {})
            return [dict(r) for r in result]

    def get_stats(self) -> dict:
        self.connect()
        with self._driver.session() as session:
            nodes = session.run("MATCH (n:Entity) RETURN count(n) as count").single()
            facts = session.run("MATCH (n:Fact) RETURN count(n) as count").single()
            attrs = session.run("MATCH (n:Attribute) RETURN count(n) as count").single()
            rels = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()
            return {
                "entity_count": nodes["count"] if nodes else 0,
                "fact_count": facts["count"] if facts else 0,
                "attribute_count": attrs["count"] if attrs else 0,
                "relation_count": rels["count"] if rels else 0,
            }

    # ═══════════════════════════════════════════════════════
    # Evidence-driven schema — Entity / Fact / Attribute
    # ═══════════════════════════════════════════════════════

    def init_evidence_schema(self):
        self.connect()
        with self._driver.session() as session:
            # Drop old constraints that conflict with the new model
            for c in ["Entity_name", "entity_name_unique", "e.name IS UNIQUE"]:
                try:
                    session.run(f"DROP CONSTRAINT {c} IF EXISTS")
                except Exception:
                    pass
            # Drop old constraint by label if the name-based one still exists
            try:
                result = session.run("SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties WHERE labelsOrTypes = ['Entity']")
                for r in result:
                    if "name" in r.get("properties", []):
                        session.run(f"DROP CONSTRAINT {r['name']}")
            except Exception:
                pass
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_key IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (f:Fact) REQUIRE f.fact_key IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (a:Attribute) REQUIRE a.attr_full_key IS UNIQUE")
            session.run("CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.name)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.type)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.active)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (f:Fact) ON (f.active)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (a:Attribute) ON (a.owner_key)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (a:Attribute) ON (a.active)")

    def sync_entity(self, entity_key: str, support_count: int):
        self.connect()
        with self._driver.session() as session:
            if support_count > 0:
                session.run(
                    """
                    MERGE (e:Entity {entity_key: $entity_key})
                    SET e.support_count = $support_count, e.active = true
                    """,
                    entity_key=entity_key, support_count=support_count,
                )
            else:
                session.run(
                    "MATCH (e:Entity {entity_key: $entity_key}) SET e.active = false, e.support_count = 0",
                    entity_key=entity_key,
                )

    def sync_entity_with_name(self, entity_key: str, name: str, entity_type: str, support_count: int):
        self.connect()
        with self._driver.session() as session:
            if support_count > 0:
                session.run(
                    """
                    MERGE (e:Entity {entity_key: $entity_key})
                    SET e.name = $name, e.type = $entity_type, e.support_count = $support_count, e.active = true
                    """,
                    entity_key=entity_key, name=name, entity_type=entity_type, support_count=support_count,
                )
            else:
                session.run(
                    "MATCH (e:Entity {entity_key: $entity_key}) SET e.active = false, e.support_count = 0",
                    entity_key=entity_key,
                )

    def sync_fact(self, fact_key: str, subject_key: str, predicate: str, object_key: str, support_count: int):
        self.connect()
        with self._driver.session() as session:
            if support_count > 0:
                session.run(
                    """
                    MERGE (s:Entity {entity_key: $subject_key})
                    MERGE (o:Entity {entity_key: $object_key})
                    MERGE (f:Fact {fact_key: $fact_key})
                    SET f.subject_key = $subject_key, f.predicate = $predicate, f.object_key = $object_key,
                        f.support_count = $support_count, f.active = true
                    MERGE (s)-[:SUBJECT_OF]->(f)
                    MERGE (f)-[:OBJECT_OF]->(o)
                    """,
                    fact_key=fact_key, subject_key=subject_key, predicate=predicate,
                    object_key=object_key, support_count=support_count,
                )
            else:
                session.run(
                    "MATCH (f:Fact {fact_key: $fact_key}) SET f.active = false, f.support_count = 0",
                    fact_key=fact_key,
                )

    def sync_entity_attribute(self, attr_full_key: str, owner_key: str, attr_key: str, attr_value: str, support_count: int):
        self.connect()
        with self._driver.session() as session:
            if support_count > 0:
                session.run(
                    """
                    MERGE (e:Entity {entity_key: $owner_key})
                    MERGE (a:Attribute {attr_full_key: $attr_full_key})
                    SET a.owner_key = $owner_key, a.owner_type = 'ENTITY',
                        a.key = $attr_key, a.value = $attr_value,
                        a.support_count = $support_count, a.active = true
                    MERGE (e)-[:HAS_ATTRIBUTE]->(a)
                    """,
                    attr_full_key=attr_full_key, owner_key=owner_key,
                    attr_key=attr_key, attr_value=attr_value, support_count=support_count,
                )
            else:
                session.run(
                    "MATCH (a:Attribute {attr_full_key: $attr_full_key}) SET a.active = false, a.support_count = 0",
                    attr_full_key=attr_full_key,
                )

    def sync_fact_attribute(self, attr_full_key: str, fact_key: str, attr_key: str, attr_value: str, support_count: int):
        self.connect()
        with self._driver.session() as session:
            if support_count > 0:
                session.run(
                    """
                    MATCH (f:Fact {fact_key: $fact_key})
                    MERGE (a:Attribute {attr_full_key: $attr_full_key})
                    SET a.owner_key = $fact_key, a.owner_type = 'FACT',
                        a.key = $attr_key, a.value = $attr_value,
                        a.support_count = $support_count, a.active = true
                    MERGE (f)-[:HAS_ATTRIBUTE]->(a)
                    """,
                    attr_full_key=attr_full_key, fact_key=fact_key,
                    attr_key=attr_key, attr_value=attr_value, support_count=support_count,
                )
            else:
                session.run(
                    "MATCH (a:Attribute {attr_full_key: $attr_full_key}) SET a.active = false, a.support_count = 0",
                    attr_full_key=attr_full_key,
                )

    def sync_from_affected(self, affected_key: str, affected_type: str, support_count: int) -> bool:
        """Unified sync entry. Parses affected_key based on affected_type."""
        self.connect()
        if support_count > 0:
            if affected_type == "ENTITY":
                entity_type, sep, entity_name = affected_key.partition(":")
                count = support_count
                self.sync_entity_with_name(affected_key, entity_name, entity_type, count)
            elif affected_type == "FACT":
                parts = affected_key.split("|")
                if len(parts) >= 3:
                    self.sync_fact(affected_key, parts[0], parts[1], parts[2], support_count)
            elif affected_type == "ENTITY_ATTRIBUTE":
                parts = affected_key.split("|")
                if len(parts) >= 3:
                    self.sync_entity_attribute(affected_key, parts[0], parts[1], parts[2], support_count)
            elif affected_type == "FACT_ATTRIBUTE":
                parts = affected_key.split("|")
                if len(parts) >= 5:
                    fact_key = "|".join(parts[:3])
                    self.sync_fact_attribute(affected_key, fact_key, parts[3], parts[4], support_count)
            return True
        else:
            if affected_type == "ENTITY":
                self.sync_entity(affected_key, 0)
            elif affected_type == "FACT":
                self.sync_fact(affected_key, "", "", "", 0)
            elif affected_type in ("ENTITY_ATTRIBUTE", "FACT_ATTRIBUTE"):
                parts = affected_key.split("|")
                if affected_type == "ENTITY_ATTRIBUTE":
                    self.sync_entity_attribute(affected_key, "", "", "", 0)
                else:
                    self.sync_fact_attribute(affected_key, "", "", "", 0)
            return True

    def get_all_entities_evidence(self) -> list[dict]:
        self.connect()
        with self._driver.session() as session:
            result = session.run(
                "MATCH (e:Entity) WHERE e.active = true RETURN e.entity_key AS entity_key, e.name AS name, e.type AS type, e.support_count AS support_count"
            )
            return [dict(r) for r in result]

    def get_all_facts_evidence(self) -> list[dict]:
        self.connect()
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (f:Fact) WHERE f.active = true
                MATCH (s:Entity {entity_key: f.subject_key})
                MATCH (o:Entity {entity_key: f.object_key})
                RETURN f.fact_key AS fact_key, s.name AS subject_name, f.predicate AS predicate,
                       o.name AS object_name, f.support_count AS support_count
                """
            )
            return [dict(r) for r in result]
