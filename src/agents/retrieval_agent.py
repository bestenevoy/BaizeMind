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

    def search(self, query: str, top_k: int = 20, doc_ids: list[str] | None = None) -> list[dict[str, Any]]:
        doc_filter = None
        if doc_ids:
            id_list = " ".join(f'"{d}"' for d in doc_ids)
            doc_filter = f"doc_id in [{id_list}]"
        results = self._retriever.retrieve(query, top_k=top_k, doc_filter=doc_filter)
        ranked = self._reranker.rerank(query, results, top_k=min(10, len(results)))

        # Apply relevance threshold AFTER reranking
        threshold = settings.retrieval_similarity_threshold
        if threshold > 0:
            filtered = [r for r in ranked if r.get("rerank_score", r.get("score", 0)) >= threshold]
            if filtered:
                return filtered
        return ranked

    def extract_context(self, results: list[dict]) -> str:
        parts = []
        for r in results:
            source = f"[Source: {r.get('doc_id', '?')}_{r.get('chunk_id', '?')}]"
            parts.append(f"{source}\n{r.get('text', '')}")
        return "\n\n---\n\n".join(parts)
