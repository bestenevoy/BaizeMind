from typing import Any

from langchain_core.messages import AIMessage

from src.llm.deepseek import get_chat_llm
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.reranker import Reranker
from config.settings import settings


class RetrievalAgent:
    def __init__(self, retriever: HybridRetriever = None, reranker: Reranker = None):
        self._retriever = retriever or HybridRetriever()
        self._reranker = reranker or Reranker()
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm(temperature=0.0)
        return self._llm

    def search(
        self,
        query: str,
        top_k: int = 20,
        doc_ids: list[str] | None = None,
        dense_query: str | None = None,
        bm25_query: str | None = None,
    ) -> list[dict[str, Any]]:
        doc_filter = None
        if doc_ids:
            id_list = " ".join(f'"{d}"' for d in doc_ids)
            doc_filter = f"doc_id in [{id_list}]"
        results = self._retriever.retrieve(
            query, top_k=top_k, doc_filter=doc_filter,
            dense_query=dense_query, bm25_query=bm25_query,
        )
        rerank_query = dense_query if dense_query else query
        ranked = self._reranker.rerank(rerank_query, results, top_k=min(10, len(results)))

        threshold = settings.reranker_score_threshold
        if threshold > 0:
            ranked = [r for r in ranked if r.get("rerank_score", r.get("score", 0)) >= threshold]
            if not ranked:
                return []

        return self._dedup_by_chunk_id(ranked)

    @staticmethod
    def _dedup_by_chunk_id(results: list[dict]) -> list[dict]:
        """Deduplicate by chunk_id, keeping first (highest-ranked) occurrence."""
        seen = set()
        out = []
        for r in results:
            cid = r.get("chunk_id", "")
            if cid and cid not in seen:
                seen.add(cid)
                out.append(r)
            elif not cid:
                out.append(r)  # Keep items without chunk_id
        return out

    @staticmethod
    def _dedup_by_text(results: list[dict]) -> list[dict]:
        """Deduplicate near-identical chunks using text hash."""
        seen = set()
        out = []
        for r in results:
            text = r.get("text", "").strip()
            h = hash(text)
            if h not in seen:
                seen.add(h)
                out.append(r)
        return out

    def extract_context(self, results: list[dict]) -> str:
        deduped = self._dedup_by_text(self._dedup_by_chunk_id(results))
        parts = []
        for i, r in enumerate(deduped):
            source = f"[{i + 1}]"
            parts.append(f"{source}\n{r.get('text', '')}")
        return "\n\n---\n\n".join(parts)
