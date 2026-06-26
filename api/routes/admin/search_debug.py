"""检索调试路由：/search 端点供检索测试页使用，访客受字数限制。

从 management.py 拆分而来，统一挂在 /api/v1/system 前缀下。

支持混合 pipeline：先判断 query_type，sql_query 走 NL2SQL 检索路径，
其他走文本 RAG（HybridRetriever）。前端按 query_type 分支渲染。
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config.settings import settings
from src.auth import User, enforce_guest_query_limit, get_current_user_optional
from src.storage import doc_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/system", tags=["system"])


class SearchDebugRequest(BaseModel):
    query: str
    folder: str | None = None
    tags: list[str] | None = None
    doc_id: str | None = None
    top_k: int | None = None
    # 强制指定检索路径："auto"(默认) / "doc" / "sql"
    # auto = 走 query_router 自动判断；doc = 强制文本 RAG；sql = 强制 NL2SQL
    force_path: str | None = "auto"


def _empty_doc_debug(query: str, message: str = "") -> dict:
    """文本 RAG 路径的空响应骨架（用于 SQL 路径返回时占位，保持响应结构一致）。"""
    return {
        "query": query,
        "query_type": "sql_query",
        "multi_query": False,
        "query_count": 1,
        "threshold": settings.retrieval_similarity_threshold,
        "dense_threshold": settings.dense_vector_threshold,
        "rerank_threshold": settings.reranker_score_threshold,
        "rewrite": {"enabled": settings.query_rewrite_enabled, "original": query, "pairs": [], "dense_query": query, "bm25_query": query, "query_tokens": [], "dense_tokens": [], "bm25_tokens": []},
        "stages": {"per_query": [], "dense_top5": [], "bm25_top5": [], "rrf": [], "rerank": []},
        "source_queries": {},
        "final_count": 0,
        "filtered_out_by_rerank_threshold": 0,
        "message": message,
    }


def _classify_query_type(query: str) -> str:
    """调用 query_router 判断 query_type。失败时回退到 simple_fact（文本 RAG）。"""
    try:
        from src.agents.workflow import get_workflow
        result = get_workflow().query_router.classify(query)
        return result.get("query_type", "simple_fact")
    except Exception as e:
        logger.warning("query_router classify failed, fallback to simple_fact: %s", e)
        return "simple_fact"


def _run_sql_debug(query: str, folder, tags) -> dict:
    """走 NL2SQL 检索路径，返回 SQL 调试数据。"""
    try:
        from src.excel_rag.qa import ExcelQA
        qa = ExcelQA()
        r = qa.retrieve(query, folder=folder or None, tags=tags or None)

        recalled = r.get("recalled_sheets", [])
        selected = r.get("selected_sheet") or {}
        sheet_meta = selected.get("sheet_meta", {}) if selected else {}
        sql_result = r.get("sql_result") or {}
        attempts = r.get("attempts", []) or []

        # 提取每张召回 sheet 的摘要信息（供前端展示召回效果）
        recalled_summary = []
        for s in recalled:
            sm = s.get("sheet_meta", s) if isinstance(s, dict) else {}
            recalled_summary.append({
                "meta_id": sm.get("meta_id", ""),
                "doc_id": sm.get("doc_id", ""),
                "sheet_name": sm.get("sheet_name", ""),
                "score": s.get("score", 0.0) if isinstance(s, dict) else 0.0,
                "summary": (sm.get("summary") or "")[:200],
                "selected": sm.get("meta_id") == sheet_meta.get("meta_id"),
            })

        resp = _empty_doc_debug(query, message="SQL 检索路径（NL2SQL）")
        resp.update({
            "query_type": "sql_query",
            "sql_debug": {
                "recalled_sheets": recalled_summary,
                "selected_sheet": {
                    "meta_id": sheet_meta.get("meta_id", ""),
                    "doc_id": sheet_meta.get("doc_id", ""),
                    "sheet_name": sheet_meta.get("sheet_name", ""),
                    "score": selected.get("score", 0.0) if selected else 0.0,
                    "columns": sheet_meta.get("columns", []),
                    "row_count": sheet_meta.get("row_count", 0),
                } if sheet_meta else None,
                "sql": r.get("sql", ""),
                "sql_result_columns": sql_result.get("columns", []) if isinstance(sql_result, dict) else [],
                "sql_result_rows": sql_result.get("rows", []) if isinstance(sql_result, dict) else [],
                "sql_result_row_count": sql_result.get("row_count", 0) if isinstance(sql_result, dict) else 0,
                "attempts": attempts,
                "error": r.get("error", ""),
                "fallback_reason": "",
            },
            "final_count": 1 if sheet_meta and r.get("sql") else 0,
        })
        return resp
    except Exception as e:
        logger.error("SQL debug failed: %s", e, exc_info=True)
        resp = _empty_doc_debug(query, message=f"SQL 检索失败: {e}")
        resp["sql_debug"] = {
            "recalled_sheets": [], "selected_sheet": None,
            "sql": "", "sql_result_columns": [], "sql_result_rows": [],
            "sql_result_row_count": 0, "attempts": [], "error": str(e),
            "fallback_reason": "",
        }
        return resp


@router.post("/search")
async def search_debug(body: SearchDebugRequest, current: User = Depends(get_current_user_optional)):
    enforce_guest_query_limit(body.query, current)
    query = body.query
    # 未指定 top_k 时用运行时配置（可被 runtime 页 / 检索测试页编辑覆盖），
    # 这样编辑 hybrid_top_k 能直接影响 Rerank 数量与最终输出
    top_k = body.top_k if body.top_k is not None else settings.hybrid_top_k

    # ── 混合 pipeline：按 query_type 分流 ──
    force_path = (body.force_path or "auto").lower()
    query_type = "simple_fact"
    if force_path == "sql":
        query_type = "sql_query"
    elif force_path == "doc":
        query_type = "simple_fact"
    else:  # auto
        query_type = _classify_query_type(query)

    if query_type == "sql_query":
        return _run_sql_debug(query, body.folder, body.tags)

    # ── 文本 RAG 路径 ──
    doc_ids = None
    if body.doc_id:
        doc_ids = [body.doc_id]
    elif body.folder or body.tags:
        ids = doc_store.get_doc_ids_by_filter(folder=body.folder or None, tags=body.tags or None)
        if not ids:
            return {
                "query": query,
                "query_type": query_type,
                "multi_query": False,
                "query_count": 1,
                "threshold": settings.retrieval_similarity_threshold,
                "dense_threshold": settings.dense_vector_threshold,
                "rerank_threshold": settings.reranker_score_threshold,
                "rewrite": {"enabled": settings.query_rewrite_enabled, "original": query, "pairs": [], "dense_query": query, "bm25_query": query, "query_tokens": [], "dense_tokens": [], "bm25_tokens": []},
                "stages": {"per_query": [], "dense_top5": [], "bm25_top5": [], "rrf": [], "rerank": []},
                "source_queries": {},
                "final_count": 0,
                "filtered_out_by_rerank_threshold": 0,
                "message": "No documents match the folder/tag filter",
            }
        doc_ids = ids

    # Query rewriting (Multi-Query Retrieval)
    # 原始 query 作为 Q0 参与 dense 检索 + RRF 融合（兜底 + 多信号源）
    dense_queries: list[str] = [query]
    bm25_query = query
    if settings.query_rewrite_enabled:
        try:
            from src.agents.workflow import get_workflow
            rewrites, bm25_query = get_workflow()._rewrite_query(query)
            dense_queries = [query] + [q for q in rewrites if q and q != query]
        except Exception:
            dense_queries, bm25_query = [query], query

    from src.retrieval.hybrid_retriever import HybridRetriever
    from src.retrieval.debug_formatter import build_search_debug_response

    hybrid = HybridRetriever()
    _, debug = hybrid.retrieve_multi(
        query, dense_queries, bm25_query, top_k=top_k, doc_ids=doc_ids,
    )

    resp = build_search_debug_response(query, debug, dense_queries, bm25_query, top_k=top_k)
    resp["query_type"] = query_type
    return resp
