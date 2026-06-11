from typing import Any, Optional

from src.knowledge_graph.neo4j_manager import Neo4jManager


class GraphExpander:
    def __init__(self, neo4j: Optional[Neo4jManager] = None):
        self._neo4j = neo4j

    def _get_neo4j(self) -> Neo4jManager:
        if self._neo4j is None:
            self._neo4j = Neo4jManager()
            self._neo4j.connect()
        return self._neo4j

    def expand_entities(
        self, entities: list[str], max_hops: int = 2
    ) -> list[dict[str, Any]]:
        neo4j = self._get_neo4j()
        results = []
        seen = set()

        for entity in entities:
            paths = neo4j.get_neighbors(entity, max_hops=max_hops)
            for path in paths:
                path_key = path.get("path_string", "")
                if path_key not in seen:
                    seen.add(path_key)
                    results.append(path)

        return results

    def query_paths(
        self, subject: str, object_: str, max_depth: int = 3
    ) -> list[dict[str, Any]]:
        neo4j = self._get_neo4j()
        return neo4j.find_paths(subject, object_, max_depth=max_depth)

    def format_context(self, paths: list[dict]) -> str:
        parts = []
        for p in paths:
            parts.append(
                f"[Graph] {p.get('subject_name', '?')}"
                f" --[{p.get('relation_type', '?')}]-->"
                f" {p.get('object_name', '?')}"
            )
        return "\n".join(parts)
