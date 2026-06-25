import logging
from typing import Any, Optional

from src.retrieval.vector_retriever import MilvusVectorRetriever
from src.retrieval.bm25_retriever import BM25Retriever
from src.retrieval.reranker import Reranker
from src.embeddings.bge_m3 import BGEM3Embedding
from config.settings import settings

logger = logging.getLogger(__name__)


class HybridRetriever:
    def __init__(
        self,
        vector_retriever: Optional[MilvusVectorRetriever] = None,
        bm25_retriever: Optional[BM25Retriever] = None,
        embedding: Optional[BGEM3Embedding] = None,
        reranker: Optional[Reranker] = None,
    ):
        self.vector_retriever = vector_retriever or MilvusVectorRetriever()
        self.bm25_retriever = bm25_retriever or BM25Retriever()
        self.embedding = embedding or BGEM3Embedding()
        self.reranker = reranker or Reranker()

    def retrieve(
        self,
        query: str,
        top_k: int = 20,
        dense_query: Optional[str] = None,
        bm25_query: Optional[str] = None,
        dense_weight: Optional[float] = None,
        bm25_weight: Optional[float] = None,
        doc_ids: Optional[list[str]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Returns (final_results, debug_info). Debug info always computed; caller decides what to use."""
        dense_weight = dense_weight or settings.hybrid_dense_weight
        bm25_weight = bm25_weight or settings.hybrid_bm25_weight
        dense_q = dense_query or query
        bm25_q = bm25_query or query

        # Over-fetch from each source to improve recall, then narrow down after RRF + rerank
        fetch_k = min(top_k * settings.retrieval_over_fetch_multiplier, 100)

        dense_results = self._dense_search(dense_q, fetch_k, doc_ids)
        bm25_results = self._bm25_search(bm25_q, fetch_k, doc_ids)

        rrf_data = self._rrf_fusion(
            {"dense": dense_results, "bm25": bm25_results},
            {"dense": dense_weight, "bm25": bm25_weight},
        )

        # Reranker stage — use the ORIGINAL user query for cross-encoder.
        # 原始 query 最贴近用户真实意图；改写 query 已在 dense/bm25 召回阶段
        # 发挥作用，rerank 阶段回到原始 query 可避免改写偏差放大。
        all_for_rerank = [doc for _, (doc, _) in rrf_data["ranked"][:top_k]]
        reranked_full = self.reranker.rerank(query, all_for_rerank, top_k=min(settings.rerank_top_k, len(all_for_rerank)))

        threshold = settings.reranker_score_threshold
        reranked = [r for r in reranked_full if r.get("rerank_score", r.get("score", 0)) >= threshold] if threshold > 0 else list(reranked_full)

        debug = {
            "multi_query": False,
            "query_count": 1,
            "dense_results": dense_results,
            "bm25_results": bm25_results,
            "rrf_ranked": rrf_data["ranked"],
            "rrf_max_raw": rrf_data["max_raw"],
            "dense_scores": rrf_data["dense_scores"],
            "bm25_scores": rrf_data["bm25_scores"],
            "reranked": reranked_full,
        }
        return reranked, debug

    def retrieve_multi(
        self,
        original_query: str,
        dense_queries: list[str],
        bm25_query: str,
        top_k: int = 20,
        doc_ids: Optional[list[str]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Multi-Query Retrieval.

        对每条 dense_query 各跑一次稠密检索，BM25 只跑一次（关键词无需多样化），
        跨所有 dense query 把 RRF 分数累加、BM25 贡献只计一次，最后用
        ``original_query``（用户原始问题）做 rerank。

        每条结果会带上 ``source_queries`` 字段（贡献该 chunk 的 dense query
        下标列表），便于前端在检索测试页按 query 筛选审查；不筛选即为汇总结果。

        Returns (final_results, debug_info)。
        """
        dense_weight = settings.hybrid_dense_weight
        bm25_weight = settings.hybrid_bm25_weight
        rrf_k = settings.hybrid_rrf_k
        fetch_k = min(top_k * settings.retrieval_over_fetch_multiplier, 100)

        # BM25 只跑一次
        bm25_results = self._bm25_search(bm25_query, fetch_k, doc_ids)

        per_query: list[dict] = []
        # 全局聚合：chunk_id -> (doc, 累计 RRF 分数)
        global_scores: dict[str, tuple[dict, float]] = {}
        source_queries: dict[str, set[int]] = {}
        dense_scores_global: dict[str, float] = {}
        bm25_scores_global: dict[str, float] = {}

        # BM25 贡献只计一次
        for rank, r in enumerate(bm25_results):
            cid = r.get("chunk_id", "")
            if not cid:
                continue
            bs = r.get("score", 0)
            bm25_scores_global[cid] = max(bs, bm25_scores_global.get(cid, 0))
            contrib = bm25_weight / (rrf_k + rank + 1)
            if cid not in global_scores:
                global_scores[cid] = (r, 0.0)
            global_scores[cid] = (global_scores[cid][0], global_scores[cid][1] + contrib)

        # 每个 dense query 各跑一次，累加 RRF 贡献
        for idx, dq in enumerate(dense_queries):
            dense_results = self._dense_search(dq, fetch_k, doc_ids)
            per_query.append({
                "index": idx,
                "dense_query": dq,
                "dense_results": dense_results,
            })
            for rank, r in enumerate(dense_results):
                cid = r.get("chunk_id", "")
                if not cid:
                    continue
                ds = r.get("score", 0)
                if ds > dense_scores_global.get(cid, 0):
                    dense_scores_global[cid] = ds
                contrib = dense_weight / (rrf_k + rank + 1)
                if cid not in global_scores:
                    global_scores[cid] = (r, 0.0)
                global_scores[cid] = (global_scores[cid][0], global_scores[cid][1] + contrib)
                source_queries.setdefault(cid, set()).add(idx)

        global_ranked = sorted(global_scores.items(), key=lambda x: x[1][1], reverse=True)
        max_raw = global_ranked[0][1][1] if global_ranked else 0.0

        # 把 source_queries 与最佳 dense/bm25 分数写回代表 doc
        sq_map = {cid: sorted(s) for cid, s in source_queries.items()}
        for cid, (doc, _) in global_ranked:
            doc["source_queries"] = sq_map.get(cid, [])
            doc["dense_score"] = dense_scores_global.get(cid, 0)
            doc["bm25_score"] = bm25_scores_global.get(cid, 0)

        # Rerank 用原始 query（贴近用户真实意图）
        all_for_rerank = [doc for _, (doc, _) in global_ranked[:top_k]]
        reranked_full = self.reranker.rerank(
            original_query, all_for_rerank,
            top_k=min(settings.rerank_top_k, len(all_for_rerank)),
        )
        # 确保 rerank 结果带 source_queries（不同 rerank 实现可能复制/引用 doc）
        for r in reranked_full:
            cid = r.get("chunk_id", "")
            if not r.get("source_queries"):
                r["source_queries"] = sq_map.get(cid, [])

        threshold = settings.reranker_score_threshold
        reranked = [r for r in reranked_full if r.get("rerank_score", r.get("score", 0)) >= threshold] if threshold > 0 else list(reranked_full)

        debug = {
            "multi_query": True,
            "query_count": len(dense_queries),
            "bm25_query": bm25_query,
            "bm25_results": bm25_results,
            "per_query": per_query,
            "rrf_ranked": global_ranked,
            "rrf_max_raw": max_raw,
            "dense_scores": dense_scores_global,
            "bm25_scores": bm25_scores_global,
            "source_queries": sq_map,
            "reranked": reranked_full,
        }
        return reranked, debug

    def _dense_search(self, query: str, top_k: int, doc_ids: Optional[list[str]] = None) -> list[dict]:
        query_vec = self.embedding.encode_query_dense(query)
        expr = _build_milvus_doc_filter(doc_ids)
        results = self.vector_retriever.search(query_vec, top_k=top_k, expr=expr)
        threshold = settings.dense_vector_threshold
        if threshold > 0:
            results = [r for r in results if r.get("score", 0) >= threshold]
        return results

    def _bm25_search(self, query: str, top_k: int, doc_ids: Optional[list[str]] = None) -> list[dict]:
        return self.bm25_retriever.search(query, top_k=top_k, doc_ids=doc_ids)

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

        # Annotate each doc with its dense/bm25 scores so they survive through reranker
        for cid, (doc, _) in scores.items():
            doc["dense_score"] = dense_scores.get(cid, 0)
            doc["bm25_score"] = bm25_scores.get(cid, 0)

        ranked = sorted(scores.items(), key=lambda x: x[1][1], reverse=True)
        max_raw = ranked[0][1][1] if ranked else 0.0
        return {"ranked": ranked, "max_raw": max_raw, "dense_scores": dense_scores, "bm25_scores": bm25_scores}


def _build_milvus_doc_filter(doc_ids: Optional[list[str]]) -> Optional[str]:
    """Build a Milvus filter expression from a list of doc_ids.

    Returns None if no filter is needed. Handles edge cases:
    - Empty list → None (no filter)
    - Very long lists → None with warning (avoid exceeding Milvus expr length limit)
    """
    if not doc_ids:
        return None
    # Milvus expression has a practical length limit (~4096 bytes).
    # Each doc_id entry adds ~len(id)+4 bytes. For safety, skip filter if too long.
    if len(doc_ids) > 500:
        logger.warning(
            f"doc_ids list too long ({len(doc_ids)}), skipping Milvus filter to avoid "
            f"expression length limit. Consider using partition-based filtering instead."
        )
        return None
    id_list = ", ".join(f'"{d}"' for d in doc_ids)
    return f"doc_id in [{id_list}]"
