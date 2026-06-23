from typing import Any, Optional

from src.llm.deepseek import get_chat_llm
from src.knowledge_graph.graph_query import GraphQuery
from src.knowledge_graph.neo4j_manager import Neo4jManager


class GraphAgent:
    def __init__(
        self,
        graph_query: Optional[GraphQuery] = None,
        neo4j: Optional[Neo4jManager] = None,
    ):
        self._graph_query = graph_query or GraphQuery()
        self._neo4j = neo4j or Neo4jManager()
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm(temperature=0.0)
        return self._llm

    def query(self, question: str) -> dict[str, Any]:
        return self._graph_query.query_natural_language(question)

    def extract_entities_from_query(self, query: str) -> list[str]:
        llm = self._get_llm()
        prompt = (
            f"Extract key entity names (people, companies, products, technologies, concepts) "
            f"from this query. Return ONLY a JSON array of strings. "
            f"Just the entity names, nothing else.\n\nQuery: {query}\n\nEntities:"
        )
        resp = llm.invoke(prompt)
        try:
            import json, re
            match = re.search(r"\[.*?\]", resp.content, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return []

    def expand(self, entities: list[str], max_hops: int = 2) -> list[dict[str, Any]]:
        results = []
        seen = set()
        self._neo4j.connect()
        for entity in entities:
            paths = self._neo4j.get_neighbors(entity, max_hops=max_hops)
            for path in paths:
                key = path.get("path_string", "")
                if key not in seen:
                    seen.add(key)
                    results.append(path)
        return results

    def format_context(self, paths: list[dict]) -> str:
        parts = []
        for p in paths:
            parts.append(f"[Graph] {p.get('path_string', p)}")
        return "\n".join(parts)

    def enrich_search_results(self, results: list[dict]) -> list[dict[str, Any]]:
        all_entities = set()
        for r in results:
            text = r.get("text", "")
            entities = self.extract_entities_from_query(text)
            all_entities.update(entities)

        graph_context = []
        if all_entities:
            paths = self.expand(list(all_entities)[:10])
            graph_context = paths

        return [
            {**r, "graph_context": self.format_context(graph_context)}
            for r in results
        ]

    def generate_sub_questions(
        self, query: str, entities: list[str], paths: list[dict]
    ) -> list[str]:
        """Generate targeted sub-questions from graph entities and relations.

        Instead of blindly appending entity names to the query (which helps BM25
        but can distort dense embeddings), we generate focused sub-questions for
        multi-query retrieval. Each sub-question addresses one aspect of the
        original query, using graph-discovered entities and relations as anchors.
        """
        if not entities and not paths:
            return []

        relations_text = self.format_context(paths[:15]) if paths else ""
        entities_text = ", ".join(entities[:10]) if entities else ""

        llm = self._get_llm()
        prompt = (
            f"Given a user question and relevant entities/relations from a knowledge graph, "
            f"generate 2-4 specific sub-questions for document retrieval. "
            f"Each sub-question should focus on one aspect and use natural language "
            f"(suitable for semantic search), not just keyword lists. "
            f"Return ONLY a JSON array of strings.\n\n"
            f"Original question: {query}\n\n"
            f"Relevant entities: {entities_text}\n\n"
            f"Graph relations:\n{relations_text}\n\n"
            f"Sub-questions (JSON array):"
        )
        resp = llm.invoke(prompt)
        try:
            import json, re
            match = re.search(r"\[.*?\]", resp.content, re.DOTALL)
            if match:
                subs = json.loads(match.group())
                return [s for s in subs if isinstance(s, str)][:4]
        except Exception:
            pass
        return []
