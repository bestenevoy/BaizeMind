"""Shared function to build search debug response from raw hybrid retriever debug data.

Used by both the /system/search API endpoint and the chat workflow's
_retrieval_agent node (to attach full debug data to stream steps for
the "分析" button in the frontend).
"""

from src.storage import doc_store
from config.settings import settings


def _build_rewrite_info(query: str, dense_query: str, bm25_query: str) -> dict:
    try:
        from src.retrieval.bm25_retriever import tokenize
        dense_tokens = list(tokenize(dense_query))
        bm25_tokens = list(tokenize(bm25_query))
        query_tokens = list(tokenize(query)) if dense_query != query else []
    except Exception:
        dense_tokens, bm25_tokens, query_tokens = [], [], []

    return {
        "original": query,
        "dense_query": dense_query,
        "bm25_query": bm25_query,
        "dense_tokens": dense_tokens,
        "bm25_tokens": bm25_tokens,
        "query_tokens": query_tokens,
        "enabled": settings.query_rewrite_enabled,
    }


def build_search_debug_response(
    query: str,
    debug: dict,
    dense_query: str = "",
    bm25_query: str = "",
    top_k: int = 20,
) -> dict:
    """Build a full SearchDebugResponse dict from raw hybrid retriever debug data."""
    rrf_threshold = settings.rrf_score_threshold
    dense_threshold = settings.dense_vector_threshold
    rerank_threshold = settings.reranker_score_threshold

    rewrite_info = _build_rewrite_info(query, dense_query or query, bm25_query or query)

    max_rrf = debug["rrf_max_raw"]
    rrf_debug = []
    for cid, (doc, raw_score) in debug.get("rrf_ranked", []):
        normalized = raw_score / max_rrf if max_rrf > 0 else 0
        rrf_debug.append({
            "chunk_id": cid,
            "doc_id": doc.get("doc_id", ""),
            "text_preview": doc.get("text", ""),
            "rrf_raw": round(raw_score, 8),
            "rrf_normalized": round(normalized, 4),
            "rrf_pass_threshold": rrf_threshold == 0 or normalized >= rrf_threshold,
            "dense_score": round(debug.get("dense_scores", {}).get(cid, 0), 6),
            "bm25_score": round(debug.get("bm25_scores", {}).get(cid, 0), 6),
        })

    rerank_debug = []
    for r in debug.get("reranked", []):
        rs = r.get("rerank_score", r.get("score", 0))
        rerank_debug.append({
            "chunk_id": r.get("chunk_id", ""),
            "doc_id": r.get("doc_id", ""),
            "text_preview": r.get("text", ""),
            "rerank_score": round(rs, 4) if isinstance(rs, (int, float)) else 0,
            "rerank_pass_threshold": rerank_threshold == 0 or (isinstance(rs, (int, float)) and rs >= rerank_threshold),
        })

    # Build filename cache
    doc_name_cache: dict[str, str] = {}
    for item in rrf_debug + rerank_debug:
        did = item.get("doc_id", "")
        if did and did not in doc_name_cache:
            d = doc_store.get_document(did)
            doc_name_cache[did] = d["filename"] if d else did

    for item in rrf_debug + rerank_debug:
        item["filename"] = doc_name_cache.get(item.get("doc_id", ""), "")

    final = [r for r in rerank_debug if r["rerank_pass_threshold"]]

    return {
        "query": query,
        "threshold": dense_threshold,
        "rrf_threshold": rrf_threshold,
        "dense_threshold": dense_threshold,
        "rerank_threshold": rerank_threshold,
        "rrf_k": settings.hybrid_rrf_k,
        "over_fetch_multiplier": settings.retrieval_over_fetch_multiplier,
        "top_k": top_k,
        "rewrite": rewrite_info,
        "stages": {
            "dense_top5": [{
                "chunk_id": d.get("chunk_id", ""),
                "doc_id": d.get("doc_id", ""),
                "filename": doc_name_cache.get(d.get("doc_id", ""), ""),
                "text_preview": d.get("text", ""),
                "score": round(d.get("score", 0), 4),
            } for d in debug.get("dense_results", [])[:top_k]],
            "bm25_top5": [{
                "chunk_id": d.get("chunk_id", ""),
                "doc_id": d.get("doc_id", ""),
                "filename": doc_name_cache.get(d.get("doc_id", ""), ""),
                "text_preview": d.get("text", ""),
                "score": round(d.get("score", 0), 4),
            } for d in debug.get("bm25_results", [])[:top_k]],
            "rrf": rrf_debug[:20],
            "rerank": rerank_debug,
        },
        "final_count": len(final),
        "filtered_out_by_rerank_threshold": len(rerank_debug) - len(final),
    }
