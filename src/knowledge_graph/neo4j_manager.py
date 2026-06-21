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

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    def init_schema(self):
        self.connect()
        with self._driver.session() as session:
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE")
            session.run("CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.type)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.doc_id)")

    def upsert_entity(self, entity: dict):
        self.connect()
        with self._driver.session() as session:
            session.run(
                """
                MERGE (e:Entity {name: $name})
                SET e.type = $type, e.description = $description, e.chunk_id = $chunk_id, e.doc_id = $doc_id
                """,
                name=entity["name"],
                type=entity.get("type", "Unknown"),
                description=entity.get("description", ""),
                chunk_id=entity.get("chunk_id", ""),
                doc_id=entity.get("doc_id", ""),
            )

    def upsert_relation(self, relation: dict):
        self.connect()
        with self._driver.session() as session:
            session.run(
                """
                MATCH (s:Entity {name: $subject})
                MATCH (o:Entity {name: $object})
                MERGE (s)-[r:RELATES_TO {type: $predicate}]->(o)
                """,
                subject=relation.get("subject", relation.get("subject_obj", "").split(" ", 1)[0]),
                predicate=relation.get("predicate", "relates_to").upper().replace(" ", "_"),
                object=relation.get("object", ""),
            )

    def batch_import(self, entities: list[dict], relations: list[dict], doc_id: str = ""):
        self.connect()
        with self._driver.session() as session:
            if entities:
                entity_params = [
                    {"name": e["name"], "type": e.get("type", "Unknown"), "description": e.get("description", "")}
                    for e in entities
                ]
                session.run(
                    """
                    UNWIND $entities AS e
                    MERGE (n:Entity {name: e.name})
                    SET n.type = e.type, n.description = e.description, n.doc_id = $doc_id
                    """,
                    entities=entity_params,
                    doc_id=doc_id,
                )
            if relations:
                rel_params = [
                    {
                        "subject": rel.get("subject", ""),
                        "predicate": rel.get("predicate", "RELATES_TO").upper().replace(" ", "_"),
                        "object": rel.get("object", ""),
                    }
                    for rel in relations
                    if rel.get("subject") and rel.get("object")
                ]
                if rel_params:
                    session.run(
                        """
                        UNWIND $relations AS r
                        MATCH (s:Entity {name: r.subject})
                        MATCH (o:Entity {name: r.object})
                        MERGE (s)-[rel:RELATES_TO {type: r.predicate}]->(o)
                        """,
                        relations=rel_params,
                    )

    def get_neighbors(self, entity_name: str, max_hops: int = 2) -> list[dict]:
        self.connect()
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH path = (s:Entity)-[*1..%d]-(o:Entity)
                WHERE toLower(s.name) CONTAINS toLower($name)
                RETURN s.name as subject_name, s.type as subject_type,
                       o.name as object_name, o.type as object_type,
                       [r in relationships(path) | type(r)] as relation_types,
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
                       [r in relationships(path) | type(r)] as relations,
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

    def delete_entities_by_doc(self, doc_id: str):
        self.connect()
        with self._driver.session() as session:
            session.run(
                "MATCH (n:Entity) WHERE n.doc_id = $doc_id DETACH DELETE n",
                doc_id=doc_id,
            )

    def get_stats(self) -> dict:
        self.connect()
        with self._driver.session() as session:
            nodes = session.run("MATCH (n:Entity) RETURN count(n) as count").single()
            rels = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()
            return {
                "entity_count": nodes["count"] if nodes else 0,
                "relation_count": rels["count"] if rels else 0,
            }
