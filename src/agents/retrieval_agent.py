from typing import Any

from langchain_core.messages import AIMessage

from src.llm.deepseek import get_chat_llm
from src.retrieval.hybrid_retriever import HybridRetriever
from config.settings import settings


class RetrievalAgent:
    def __init__(self, retriever: HybridRetriever = None):
        self._retriever = retriever or HybridRetriever()
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
        results, _ = self._retriever.retrieve(
            query, top_k=top_k, doc_ids=doc_ids,
            dense_query=dense_query, bm25_query=bm25_query,
        )
        return self._dedup_by_chunk_id(results)

    @staticmethod
    def _dedup_by_chunk_id(results: list[dict]) -> list[dict]:
        seen = set()
        out = []
        for r in results:
            cid = r.get("chunk_id", "")
            if cid and cid not in seen:
                seen.add(cid)
                out.append(r)
            elif not cid:
                out.append(r)
        return out

    @staticmethod
    def _dedup_by_text(results: list[dict]) -> list[dict]:
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
