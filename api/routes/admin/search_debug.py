"""检索调试路由：/search 端点供检索测试页使用，访客受字数限制。

从 management.py 拆分而来，统一挂在 /api/v1/system 前缀下。
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


@router.post("/search")
async def search_debug(body: SearchDebugRequest, current: User = Depends(get_current_user_optional)):
    enforce_guest_query_limit(body.query, current)
    query = body.query
    # 未指定 top_k 时用运行时配置（可被 runtime 页 / 检索测试页编辑覆盖），
    # 这样编辑 hybrid_top_k 能直接影响 Rerank 数量与最终输出
    top_k = body.top_k if body.top_k is not None else settings.hybrid_top_k

    doc_ids = None
    if body.doc_id:
        doc_ids = [body.doc_id]
    elif body.folder or body.tags:
        ids = doc_store.get_doc_ids_by_filter(folder=body.folder or None, tags=body.tags or None)
        if not ids:
            return {
                "query": query,
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

    return build_search_debug_response(query, debug, dense_queries, bm25_query, top_k=top_k)
