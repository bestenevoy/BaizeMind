from typing import Any, Optional

from src.retrieval.vector_retriever import MilvusVectorRetriever
from src.retrieval.bm25_retriever import BM25Retriever
from src.retrieval.reranker import Reranker
from src.embeddings.bge_m3 import BGEM3Embedding
from config.settings import settings


class HybridRetriever:
    def __init__(
        self,
        vector_retriever: Optional[MilvusVectorRetriever] = None,
        bm25_retriever: Optional[BM25Retriever] = None,
        embedding: Optional[BGEM3Embedding] = None,
    ):
        self.vector_retriever = vector_retriever or MilvusVectorRetriever()
        self.bm25_retriever = bm25_retriever or BM25Retriever()
        self.embedding = embedding or BGEM3Embedding()

    def retrieve(
        self,
        query: str,
        top_k: int = 20,
        dense_query: Optional[str] = None,
        bm25_query: Optional[str] = None,
        dense_weight: Optional[float] = None,
        bm25_weight: Optional[float] = None,
        doc_filter: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Returns (final_results, debug_info). Debug info always computed; caller decides what to use."""
        dense_weight = dense_weight or settings.hybrid_dense_weight
        bm25_weight = bm25_weight or settings.hybrid_bm25_weight
        dense_q = dense_query or query
        bm25_q = bm25_query or query

        dense_results = self._dense_search(dense_q, top_k, doc_filter)
        bm25_results = self._bm25_search(bm25_q, top_k)

        rrf_data = self._rrf_fusion(
            {"dense": dense_results, "bm25": bm25_results},
            {"dense": dense_weight, "bm25": bm25_weight},
        )

        # Reranker stage
        rrf_passed = [doc for cid, (doc, s) in rrf_data["ranked"]
                      if rrf_data["max_raw"] == 0 or (s / rrf_data["max_raw"]) >= settings.retrieval_similarity_threshold]
        all_for_rerank = rrf_passed[:top_k] if rrf_passed else [doc for _, (doc, _) in rrf_data["ranked"][:top_k]]
        reranker = Reranker()
        reranked = reranker.rerank(dense_q, all_for_rerank, top_k=min(10, len(all_for_rerank)))

        threshold = settings.reranker_score_threshold
        if threshold > 0:
            reranked = [r for r in reranked if r.get("rerank_score", r.get("score", 0)) >= threshold]

        debug = {
            "dense_results": dense_results,
            "bm25_results": bm25_results,
            "rrf_ranked": rrf_data["ranked"],
            "rrf_max_raw": rrf_data["max_raw"],
            "dense_scores": rrf_data["dense_scores"],
            "bm25_scores": rrf_data["bm25_scores"],
            "reranked": reranked,
        }
        return reranked, debug

    def _dense_search(self, query: str, top_k: int, doc_filter: Optional[str] = None) -> list[dict]:
        query_vec = self.embedding.encode_query_dense(query)
        results = self.vector_retriever.search(query_vec, top_k=top_k, expr=doc_filter)
        threshold = settings.dense_vector_threshold
        if threshold > 0:
            results = [r for r in results if r.get("score", 0) >= threshold]
        return results

    def _bm25_search(self, query: str, top_k: int) -> list[dict]:
        return self.bm25_retriever.search(query, top_k=top_k)

    def _rrf_fusion(
        self,
        result_sets: dict[str, list[dict]],
        weights: dict[str, float],
    ) -> dict[str, Any]:
        k = settings.hybrid_rrf_k
        scores: dict[str, tuple[dict, float]] = {}
        dense_scores: dict[str, float] = {}
        bm25_scores: dict[str, float] = {}

        for source, results in result_sets.items():
            weight = weights.get(source, 1.0)
            for rank, doc in enumerate(results):
                cid = doc.get("chunk_id", "")
                if cid not in scores:
                    scores[cid] = (doc, 0.0)
                scores[cid] = (doc, scores[cid][1] + weight / (k + rank + 1))
                if source == "dense":
                    dense_scores[cid] = doc.get("score", 0)
                else:
                    bm25_scores[cid] = doc.get("score", 0)

        ranked = sorted(scores.items(), key=lambda x: x[1][1], reverse=True)
        max_raw = ranked[0][1][1] if ranked else 0.0
        return {"ranked": ranked, "max_raw": max_raw, "dense_scores": dense_scores, "bm25_scores": bm25_scores}
