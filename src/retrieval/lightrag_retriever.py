"""LightRAG Retriever — Graph-Navigated Hybrid Retrieval.

Core pattern (from LightRAG paper):
  Query → Entity Index Search → Relation Index Search → Graph Expansion → Chunk Retrieval → LLM

Instead of LLM-based NER at query time, we use vector search over pre-indexed entity
and relation embeddings to navigate the knowledge graph. The graph serves as a
navigation layer that guides chunk retrieval, NOT as a direct answer source.

Three retrieval modes:
  - local:  entity_index → graph neighbors → local chunks (for specific facts)
  - global: relation_index → theme relations → global context (for overviews)
  - hybrid: both local + global merged (default, most robust)
"""
import logging
from typing import Any, Optional

from src.retrieval.entity_index import EntityIndex
from src.retrieval.relation_index import RelationIndex
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.reranker import Reranker
from src.knowledge_graph.neo4j_manager import Neo4jManager
from src.embeddings.bge_m3 import BGEM3Embedding
from config.settings import settings

logger = logging.getLogger(__name__)


class LightRAGRetriever:
    def __init__(
        self,
        entity_index: Optional[EntityIndex] = None,
        relation_index: Optional[RelationIndex] = None,
        neo4j: Optional[Neo4jManager] = None,
        chunk_retriever: Optional[HybridRetriever] = None,
        reranker: Optional[Reranker] = None,
        embedding: Optional[BGEM3Embedding] = None,
    ):
        self.entity_index = entity_index or EntityIndex()
        self.relation_index = relation_index or RelationIndex()
        self._neo4j = neo4j
        self.chunk_retriever = chunk_retriever or HybridRetriever()
        self.reranker = reranker or Reranker()
        self._embedding = embedding or BGEM3Embedding()

    def _get_neo4j(self) -> Neo4jManager:
        if self._neo4j is None:
            self._neo4j = Neo4jManager()
            self._neo4j.connect()
        return self._neo4j

    def retrieve(
        self,
        query: str,
        mode: Optional[str] = None,
        top_k: int = 20,
        doc_filter: Optional[str] = None,
    ) -> dict[str, Any]:
        """Main entry point: LightRAG retrieval with entity/relation navigation.

        Returns a dict with keys:
          - documents: list of retrieved chunk dicts
          - graph_context: str — formatted graph paths for the LLM
          - entities_found: list[str] — matched entity names
          - relations_found: list[dict] — matched relations
          - retrieval_path: str — description of the retrieval path taken
        """
        mode = mode or settings.lightrag_retrieval_mode

        # Step 1: Entity Index Search — find relevant entities by semantic match
        entity_results = self.entity_index.search(
            query, top_k=settings.lightrag_entity_top_k
        )
        entity_names = [e["entity_name"] for e in entity_results if e.get("entity_name")]

        # Step 2: Relation Index Search — find relevant relations
        relation_results = self.relation_index.search(
            query, top_k=settings.lightrag_relation_top_k
        )

        # Step 3: Graph Navigation — expand from matched entities
        graph_paths = []
        all_related_entities = set(entity_names)
        neo4j = self._get_neo4j()

        if entity_names and mode in ("local", "hybrid"):
            for name in entity_names[:5]:
                paths = neo4j.get_neighbors(name, max_hops=settings.lightrag_graph_hops)
                for p in paths:
                    graph_paths.append(p)
                    all_related_entities.add(p.get("subject_name", ""))
                    all_related_entities.add(p.get("object_name", ""))

        # Also expand from relation subjects/objects
        for rel in relation_results[:5]:
            if rel.get("subject"):
                paths = neo4j.get_neighbors(rel["subject"], max_hops=1)
                graph_paths.extend(paths)
                all_related_entities.add(rel["subject"])
                all_related_entities.add(rel["object"])

        # Step 4: Build graph context
        graph_context = self._format_graph_context(graph_paths)

        # Step 5: Chunk Retrieval — guided by graph-discovered entities
        # Build entity-enriched BM25 query while keeping dense query natural
        dense_query = query
        bm25_query = query
        if all_related_entities:
            entity_suffix = " ".join(sorted(all_related_entities)[:15])
            bm25_query = f"{query} {entity_suffix}"

        results = self.chunk_retriever.retrieve(
            query,
            top_k=top_k,
            dense_query=dense_query,
            bm25_query=bm25_query,
            doc_filter=doc_filter,
        )

        # Rerank with original query
        ranked = self.reranker.rerank(query, results, top_k=min(10, len(results)))

        # Dedup
        seen_ids = set()
        documents = []
        for r in ranked:
            cid = r.get("chunk_id", "")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                documents.append(r)

        mode_label = {"local": "Local", "global": "Global", "hybrid": "Hybrid"}.get(mode, mode)

        return {
            "documents": documents[:top_k],
            "graph_context": graph_context,
            "entities_found": list(all_related_entities)[:20],
            "relations_found": relation_results[:10],
            "retrieval_path": (
                f"[LightRAG {mode_label}] "
                f"entity_index→{len(entity_results)} entities, "
                f"relation_index→{len(relation_results)} relations, "
                f"graph_expand→{len(graph_paths)} paths, "
                f"chunk_retrieval→{len(documents)} chunks"
            ),
        }

    def retrieve_local(
        self, query: str, top_k: int = 20, doc_filter: Optional[str] = None
    ) -> dict[str, Any]:
        """Local retrieval: entity index → neighbors → local chunks."""
        return self.retrieve(query, mode="local", top_k=top_k, doc_filter=doc_filter)

    def retrieve_global(
        self, query: str, top_k: int = 20, doc_filter: Optional[str] = None
    ) -> dict[str, Any]:
        """Global retrieval: relation index → theme relations → global context."""
        return self.retrieve(query, mode="global", top_k=top_k, doc_filter=doc_filter)

    def _format_graph_context(self, paths: list[dict]) -> str:
        if not paths:
            return ""
        seen = set()
        lines = []
        for p in paths:
            key = p.get("path_string", "")
            if key and key not in seen:
                seen.add(key)
                lines.append(f"[Graph] {key}")
        return "\n".join(lines[:40])
