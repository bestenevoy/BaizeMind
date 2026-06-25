"""Shared function to build search debug response from raw hybrid retriever debug data.

Used by both the /system/search API endpoint and the chat workflow's
_retrieval_agent node (to attach full debug data to stream steps for
the "分析" button in the frontend).

Supports both single-query retrieval (``retrieve``) and Multi-Query
Retrieval (``retrieve_multi``)。多 query 模式下输出 N 条 dense query + 1 条
共享 bm25 query，以及 ``source_queries`` 标记，便于前端按改写 query 筛选审查。
"""

from src.storage import doc_store
from config.settings import settings


def _tokenize_query(text: str) -> list[str]:
    try:
        from src.retrieval.bm25_retriever import tokenize
        return list(tokenize(text))
    except Exception:
        return []


def _split_tokens(text: str) -> list[str]:
    """BM25 通道在 query_rewrite 开启时按空格切分（保留实体词）。"""
    if settings.query_rewrite_enabled:
        return text.split()
    return _tokenize_query(text)


def _dense_query_info(index: int, dense_query: str, original: str) -> dict:
    return {
        "index": index,
        "dense_query": dense_query,
        "dense_tokens": _tokenize_query(dense_query),
        "query_tokens": _tokenize_query(original) if dense_query != original else [],
    }


def _enrich_doc_name(item: dict, doc_name_cache: dict[str, str]) -> None:
    did = item.get("doc_id", "")
    if did and did not in doc_name_cache:
        d = doc_store.get_document(did)
        doc_name_cache[did] = d["filename"] if d else did
    item["filename"] = doc_name_cache.get(did, "")


def build_search_debug_response(
    query: str,
    debug: dict,
    dense_queries=None,
    bm25_query: str = "",
    top_k: int = 20,
) -> dict:
    """Build a full SearchDebugResponse dict from raw hybrid retriever debug data.

    ``dense_queries`` 为 Multi-Query Retrieval 的多条等价 dense query 列表，
    ``bm25_query`` 为共享的单条关键词 query。若 ``dense_queries`` 未提供则
    回退到单 query 模式（使用 debug 中的 dense_results/bm25_results）。
    """
    dense_threshold = settings.dense_vector_threshold
    rerank_threshold = settings.reranker_score_threshold
    doc_name_cache: dict[str, str] = {}

    # ── 归一化 dense_queries ──
    if dense_queries is None:
        dense_queries = [query]
    is_multi = bool(debug.get("multi_query")) and len(dense_queries) > 1

    dense_queries_info = [
        _dense_query_info(i, dq, query) for i, dq in enumerate(dense_queries)
    ]

    # ── RRF（全局聚合，多 query 模式下为跨 dense query 累加 + bm25 一次）──
    max_rrf = debug.get("rrf_max_raw", 0)
    rrf_debug = []
    source_queries_map: dict[str, list[int]] = {}
    for cid, (doc, raw_score) in debug.get("rrf_ranked", []):
        normalized = raw_score / max_rrf if max_rrf > 0 else 0
        sq = doc.get("source_queries", debug.get("source_queries", {}).get(cid, []))
        source_queries_map[cid] = list(sq) if isinstance(sq, list) else []
        rrf_debug.append({
            "chunk_id": cid,
            "doc_id": doc.get("doc_id", ""),
            "text_preview": doc.get("text", ""),
            "rrf_raw": round(raw_score, 8),
            "rrf_normalized": round(normalized, 4),
            "dense_score": round(debug.get("dense_scores", {}).get(cid, 0), 6),
            "bm25_score": round(debug.get("bm25_scores", {}).get(cid, 0), 6),
            "source_queries": source_queries_map[cid],
        })

    # ── Rerank（用原始 query 的 rerank 结果）──
    rerank_debug = []
    for r in debug.get("reranked", []):
        rs = r.get("rerank_score", r.get("score", 0))
        cid = r.get("chunk_id", "")
        sq = r.get("source_queries", source_queries_map.get(cid, []))
        rerank_debug.append({
            "chunk_id": cid,
            "doc_id": r.get("doc_id", ""),
            "text_preview": r.get("text", ""),
            "rerank_score": round(rs, 4) if isinstance(rs, (int, float)) else 0,
            "rerank_pass_threshold": rerank_threshold == 0 or (isinstance(rs, (int, float)) and rs >= rerank_threshold),
            "source_queries": list(sq) if isinstance(sq, list) else [],
        })

    # ── 文件名补全 ──
    for item in rrf_debug + rerank_debug:
        _enrich_doc_name(item, doc_name_cache)

    # ── bm25 结果（多 query 模式从 debug 顶层取；单 query 模式从 debug["bm25_results"] 取）──
    bm25_results = debug.get("bm25_results", [])
    bm25_top = [{
        "chunk_id": d.get("chunk_id", ""),
        "doc_id": d.get("doc_id", ""),
        "text_preview": d.get("text", ""),
        "score": round(d.get("score", 0), 4),
    } for d in bm25_results[:top_k]]
    for item in bm25_top:
        _enrich_doc_name(item, doc_name_cache)

    # ── per-query 明细（仅多 query 模式，每条 dense query 的召回）──
    per_query_stages = []
    dense_union_count = 0
    dense_union_top: list[dict] = []  # 汇总：去重并集按最高 score 排序
    if is_multi:
        # 所有 Q 完整 dense 召回的去重并集 chunk（用于汇总列表 + 标签数字）
        union_map: dict[str, dict] = {}
        union_source: dict[str, list[int]] = {}
        for q_info in debug.get("per_query", []):
            idx = q_info.get("index", 0)
            dense_results = q_info.get("dense_results", [])
            for d in dense_results:
                cid = d.get("chunk_id", "")
                if not cid:
                    continue
                existing = union_map.get(cid)
                if existing is None:
                    union_map[cid] = {
                        "chunk_id": cid,
                        "doc_id": d.get("doc_id", ""),
                        "text_preview": d.get("text", ""),
                        "score": round(d.get("score", 0), 4),
                    }
                    union_source[cid] = [idx]
                else:
                    # 多 query 命中同一 chunk，取最高分并合并 source
                    sc = round(d.get("score", 0), 4)
                    if sc > existing["score"]:
                        existing["score"] = sc
                    union_source.setdefault(cid, []).append(idx) if idx not in union_source.get(cid, []) else None
            dense_top = [{
                "chunk_id": d.get("chunk_id", ""),
                "doc_id": d.get("doc_id", ""),
                "text_preview": d.get("text", ""),
                "score": round(d.get("score", 0), 4),
            } for d in dense_results[:top_k]]
            for item in dense_top:
                _enrich_doc_name(item, doc_name_cache)
            per_query_stages.append({
                "index": idx,
                "dense_query": q_info.get("dense_query", ""),
                "dense_top": dense_top,
                "dense_count": len(dense_results),
            })
        dense_union_count = len(union_map)
        # 汇总列表：按 score 降序，带 source_queries（不截断，显示完整去重并集）
        dense_union_top = sorted(union_map.values(), key=lambda x: x["score"], reverse=True)
        for item in dense_union_top:
            _enrich_doc_name(item, doc_name_cache)
            item["source_queries"] = sorted(set(union_source.get(item["chunk_id"], [])))

    # ── 全局 dense top（multi 模式 = 去重并集；单 query 模式 = 原始列表）──
    if is_multi:
        global_dense_top: list[dict] = dense_union_top
    else:
        global_dense_top = [{
            "chunk_id": d.get("chunk_id", ""),
            "doc_id": d.get("doc_id", ""),
            "text_preview": d.get("text", ""),
            "score": round(d.get("score", 0), 4),
        } for d in debug.get("dense_results", [])[:top_k]]
        for item in global_dense_top:
            _enrich_doc_name(item, doc_name_cache)

    final = [r for r in rerank_debug if r["rerank_pass_threshold"]]

    return {
        "query": query,
        "multi_query": is_multi,
        "query_count": len(dense_queries),
        "dense_union_count": dense_union_count,
        "threshold": dense_threshold,
        "dense_threshold": dense_threshold,
        "rerank_threshold": rerank_threshold,
        "rrf_k": settings.hybrid_rrf_k,
        "over_fetch_multiplier": settings.retrieval_over_fetch_multiplier,
        "top_k": top_k,
        "rerank_top_k": settings.rerank_top_k,
        "rewrite": {
            "enabled": settings.query_rewrite_enabled,
            "original": query,
            "dense_queries": dense_queries_info,
            "bm25_query": bm25_query,
            "bm25_tokens": _split_tokens(bm25_query),
            # 兼容旧字段：取首条 dense query
            "dense_query": dense_queries_info[0]["dense_query"] if dense_queries_info else query,
            "dense_tokens": dense_queries_info[0]["dense_tokens"] if dense_queries_info else [],
            "query_tokens": dense_queries_info[0]["query_tokens"] if dense_queries_info else [],
        },
        "stages": {
            "per_query": per_query_stages,
            "dense_top5": global_dense_top,
            "bm25_top5": bm25_top,
            "rrf": rrf_debug[:20],
            "rerank": rerank_debug,
        },
        "source_queries": source_queries_map,
        "final_count": len(final),
        "filtered_out_by_rerank_threshold": len(rerank_debug) - len(final),
    }
