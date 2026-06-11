import json
import re
from typing import Any, Optional

from src.llm.deepseek import get_chat_llm
from src.knowledge_graph.neo4j_manager import Neo4jManager
from config.prompts import TEXT_TO_CYPHER_SYSTEM


class GraphQuery:
    def __init__(self, neo4j: Optional[Neo4jManager] = None):
        self._neo4j = neo4j
        self._llm = None

    def _get_neo4j(self) -> Neo4jManager:
        if self._neo4j is None:
            self._neo4j = Neo4jManager()
            self._neo4j.connect()
        return self._neo4j

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm(temperature=0.0)
        return self._llm

    def query_natural_language(self, question: str) -> dict[str, Any]:
        cypher = self._text_to_cypher(question)
        if not cypher:
            return {"results": [], "cypher": "", "error": "Could not generate Cypher query"}

        neo4j = self._get_neo4j()
        try:
            results = neo4j.query(cypher)
            return {"results": results, "cypher": cypher, "count": len(results)}
        except Exception as e:
            return {"results": [], "cypher": cypher, "error": str(e)}

    def _text_to_cypher(self, question: str) -> str:
        llm = self._get_llm()
        prompt = TEXT_TO_CYPHER_SYSTEM.format(question=question)
        resp = llm.invoke(prompt)
        content = resp.content.strip()
        content = re.sub(r"```(?:cypher)?\s*", "", content).strip()
        return content

    def search_by_entity_name(self, name: str, limit: int = 20) -> list[dict]:
        neo4j = self._get_neo4j()
        return neo4j.query(
            """
            MATCH (e:Entity)
            WHERE toLower(e.name) CONTAINS toLower($name)
            RETURN e.name as entity_name, e.type as entity_type, e.description as description
            LIMIT $limit
            """,
            {"name": name, "limit": limit},
        )

    def get_entity_detail(self, name: str) -> dict[str, Any]:
        neo4j = self._get_neo4j()
        entity = neo4j.query(
            """
            MATCH (e:Entity)
            WHERE e.name = $name
            RETURN e.name as name, e.type as type, e.description as description
            """,
            {"name": name},
        )
        neighbors = neo4j.get_neighbors(name, max_hops=1)
        return {
            "entity": entity[0] if entity else None,
            "neighbors": neighbors,
        }
