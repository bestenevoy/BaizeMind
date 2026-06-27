"""检索调试路由：/search 端点供检索测试页使用，访客受字数限制。

从 management.py 拆分而来，统一挂在 /api/v1/system 前缀下。

[UNIFIED] 三种调试模式：
- unified (默认): 复用主工作流 astream，展示完整执行轨迹（统一召回→条件触发SQL Tool Call）
- doc: 仅文本 RAG 调试（HybridRetriever 独立调用，不经过 LangGraph）
- sql: 仅 NL2SQL 调试（ExcelQA.retrieve 独立调用，不经过 LangGraph）
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
    # [UNIFIED] 调试模式："unified"(默认) / "doc" / "sql"
    # unified = 复用主工作流 astream，展示完整执行轨迹
    # doc = 仅文本 RAG 调试（独立调用 HybridRetriever）
    # sql = 仅 NL2SQL 调试（独立调用 ExcelQA.retrieve）
    force_path: str | None = "unified"


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
        # error 值映射为可读的 fallback_reason，便于前端展示降级原因
        err = r.get("error", "")
        fallback_reason_map = {
            "no_sheets": "无任何结构化数据（Excel 未入库）",
            "no_relevant_sheet": "未召回相关 Sheet",
        }
        fallback_reason = fallback_reason_map.get(err, "")
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
                    "summary": (sheet_meta.get("summary") or "")[:500],
                } if sheet_meta else None,
                "sql": r.get("sql", ""),
                "sql_result_columns": sql_result.get("columns", []) if isinstance(sql_result, dict) else [],
                "sql_result_rows": sql_result.get("rows", []) if isinstance(sql_result, dict) else [],
                "sql_result_row_count": sql_result.get("row_count", 0) if isinstance(sql_result, dict) else 0,
                "attempts": attempts,
                "error": err,
                "fallback_reason": fallback_reason,
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


async def _run_unified_debug(query: str, folder: str | None, tags: list[str] | None,
                              doc_id: str | None) -> dict:
    """[UNIFIED] 复用主工作流 astream，收集完整执行轨迹。

    与 chat 路由的区别：
    - chat 是 SSE 流式返回，前端实时渲染；本函数同步收集所有事件后一次性返回
    - 保留 intermediate=True 的 answer_generator 事件（展示"信息不足"中间状态）
    - 保留所有原始 debug 数据（search_debug_data, retrieval_debug 等）

    返回 UnifiedSearchDebugResponse 结构，包含：
    - steps: 所有节点执行的完整轨迹
    - sql_triggered: 是否触发了 SQL Tool Call
    - final_answer / citations / retrieval_path
    """
    from src.agents.workflow import get_workflow

    doc_ids = [doc_id] if doc_id else None
    workflow = get_workflow()

    steps: list[dict] = []
    final_answer = ""
    citations: list[str] = []
    retrieval_path = ""
    query_type = "simple_fact"
    sql_triggered = False

    NODE_LABELS = {
        "query_router": ("查询路由", "语义意图分类"),
        "retrieval_agent": ("混合检索", "统一召回: doc+table+sheet 同库"),
        "lightrag_agent": ("LightRAG 检索", "实体→关系→图谱→chunk"),
        "graph_agent": ("图谱扩展", "LLM NER + Neo4j expand"),
        "sql_agent": ("SQL Tool Call", "条件触发: NL2SQL → 执行"),
        "answer_generator": ("答案生成", "生成 + 自检（合并 validator）"),
        "chitchat": ("闲聊直答", "直接 LLM，无检索"),
    }

    try:
        async for event in workflow.astream(query, folder=folder, tags=tags, doc_ids=doc_ids):
            if not isinstance(event, dict) or not event:
                continue
            (node_name, node_output), = event.items()
            label, detail_label = NODE_LABELS.get(node_name, (node_name, node_name))

            step = {
                "node": node_name,
                "label": label,
                "detail": detail_label,
                "status": "error" if node_output.get("error") else "done",
                "error": node_output.get("error", ""),
                "intermediate": node_output.get("intermediate", False),
                "result": {},
            }

            # 收集各节点关键输出（保留原始 debug 数据，不截断）
            if node_name == "query_router":
                query_type = node_output.get("query_type", "simple_fact")
                step["result"] = {
                    "query_type": query_type,
                    "confidence": node_output.get("confidence", 0.0),
                    "graph_eligible": node_output.get("graph_eligible", False),
                }
            elif node_name in ("retrieval_agent", "lightrag_agent"):
                docs = node_output.get("documents", [])
                retrieval_path = node_output.get("retrieval_path", "")
                has_excel = any(
                    (d.get("metadata", {}) or {}).get("source") == "excel_sheet"
                    or (d.get("chunk_id", "") or "").startswith("excel:")
                    for d in docs if isinstance(d, dict)
                )
                step["result"] = {
                    "count": len(docs),
                    "retrieval_path": retrieval_path,
                    "has_excel_sheet": has_excel,
                    "search_debug_data": node_output.get("search_debug_data"),
                    "documents": docs[:10],
                }
            elif node_name == "sql_agent":
                sql_triggered = True
                retrieval_path = node_output.get("retrieval_path", "")
                retrieval_debug = node_output.get("retrieval_debug", {}) or {}
                docs = node_output.get("documents", [])
                step["result"] = {
                    "count": len(docs),
                    "retrieval_path": retrieval_path,
                    "rerouted_to_sql": node_output.get("rerouted_to_sql", True),
                    "sql_query": retrieval_debug.get("sql_query", ""),
                    "sql_sheet_name": retrieval_debug.get("sql_sheet_name", ""),
                    "sql_result_row_count": retrieval_debug.get("sql_result_row_count", 0),
                    "sql_result_columns": retrieval_debug.get("sql_result_columns", []),
                    "sql_result_rows": retrieval_debug.get("sql_result_rows", []),
                    "sql_recalled_sheets": retrieval_debug.get("sql_recalled_sheets", []),
                    "sql_attempts": retrieval_debug.get("sql_attempts", []),
                    "sql_error": retrieval_debug.get("sql_error", ""),
                    "sql_fallback_reason": retrieval_debug.get("sql_fallback_reason", ""),
                    "documents": docs[:10],
                }
            elif node_name == "answer_generator":
                answer = node_output.get("final_answer", node_output.get("draft_answer", ""))
                if not node_output.get("intermediate", False):
                    final_answer = answer
                    citations = node_output.get("citations", [])
                step["result"] = {
                    "answer": answer,
                    "final_answer": answer,
                    "citations": node_output.get("citations", []),
                    "iteration": node_output.get("iteration", 0),
                    "intermediate": node_output.get("intermediate", False),
                    "rerouted_to_sql": node_output.get("rerouted_to_sql", False),
                }
            elif node_name == "chitchat":
                final_answer = node_output.get("final_answer", "")
                step["result"] = {"answer": final_answer}
            elif node_name == "graph_agent":
                step["result"] = {
                    "graph_context": node_output.get("graph_context", "")[:500],
                    "graph_entities": node_output.get("graph_entities", []),
                    "sub_queries": node_output.get("sub_queries", []),
                }

            steps.append(step)

    except Exception as e:
        logger.error("unified debug failed: %s", e, exc_info=True)
        return {
            "query": query,
            "mode": "unified",
            "query_type": query_type,
            "steps": steps,
            "sql_triggered": sql_triggered,
            "final_answer": final_answer or f"调试失败: {e}",
            "citations": citations,
            "retrieval_path": retrieval_path,
            "error": str(e),
        }

    return {
        "query": query,
        "mode": "unified",
        "query_type": query_type,
        "steps": steps,
        "sql_triggered": sql_triggered,
        "final_answer": final_answer,
        "citations": citations,
        "retrieval_path": retrieval_path,
        "error": "",
    }


@router.post("/search")
async def search_debug(body: SearchDebugRequest, current: User = Depends(get_current_user_optional)):
    enforce_guest_query_limit(body.query, current)
    query = body.query
    # 未指定 top_k 时用运行时配置（可被 runtime 页 / 检索测试页编辑覆盖），
    # 这样编辑 hybrid_top_k 能直接影响 Rerank 数量与最终输出
    top_k = body.top_k if body.top_k is not None else settings.hybrid_top_k

    # [UNIFIED] 三种调试模式分流
    force_path = (body.force_path or "unified").lower()

    # unified 模式：复用主工作流 astream，展示完整执行轨迹
    if force_path == "unified":
        return await _run_unified_debug(query, body.folder, body.tags, body.doc_id)

    # sql 模式：仅 NL2SQL 调试（独立调用 ExcelQA.retrieve）
    if force_path == "sql":
        return _run_sql_debug(query, body.folder, body.tags)

    # doc 模式：仅文本 RAG 调试（独立调用 HybridRetriever）
    query_type = "simple_fact"

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
