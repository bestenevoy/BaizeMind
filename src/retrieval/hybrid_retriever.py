from typing import Any, Optional

import numpy as np

from src.retrieval.vector_retriever import MilvusVectorRetriever
from src.retrieval.bm25_retriever import BM25Retriever
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
        dense_weight: Optional[float] = None,
        sparse_weight: Optional[float] = None,
        bm25_weight: Optional[float] = None,
        doc_filter: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        dense_weight = dense_weight or settings.hybrid_dense_weight
        sparse_weight = sparse_weight or settings.hybrid_sparse_weight
        bm25_weight = bm25_weight or settings.hybrid_bm25_weight

        dense_results = self._dense_search(query, top_k, doc_filter)
        bm25_results = self._bm25_search(query, top_k)

        return self._rrf_fusion(
            {"dense": dense_results, "bm25": bm25_results},
            {"dense": dense_weight, "bm25": bm25_weight},
            top_k,
        )

    def _dense_search(self, query: str, top_k: int, doc_filter: Optional[str] = None) -> list[dict]:
        query_vec = self.embedding.encode_query_dense(query)
        expr = f'doc_id == "{doc_filter}"' if doc_filter else None
        return self.vector_retriever.search(query_vec, top_k=top_k, expr=expr)

    def _bm25_search(self, query: str, top_k: int) -> list[dict]:
        return self.bm25_retriever.search(query, top_k=top_k)

    def _rrf_fusion(
        self,
        result_sets: dict[str, list[dict]],
        weights: dict[str, float],
        top_k: int,
    ) -> list[dict]:
        k = settings.hybrid_rrf_k
        scores: dict[str, tuple[dict, float]] = {}

        for source, results in result_sets.items():
            weight = weights.get(source, 1.0)
            for rank, doc in enumerate(results):
                chunk_id = doc.get("chunk_id", "")
                if chunk_id not in scores:
                    scores[chunk_id] = (doc, 0.0)
                scores[chunk_id] = (doc, scores[chunk_id][1] + weight / (k + rank + 1))

        ranked = sorted(scores.values(), key=lambda x: x[1], reverse=True)
        return [doc for doc, _ in ranked[:top_k]]
