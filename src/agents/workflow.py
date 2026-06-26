import operator
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import StateGraph, START, END

from src.agents.query_router import QueryRouter
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.graph_agent import GraphAgent
from src.agents.answer_validator import AnswerValidator
from src.retrieval.lightrag_retriever import LightRAGRetriever
from src.llm.deepseek import get_chat_llm
from config.prompts import ANSWER_GENERATION_SYSTEM, CHITCHAT_SYSTEM, QUERY_REWRITE_SYSTEM, SQL_ANSWER_GENERATION_SYSTEM
from config.settings import settings

import logging

logger = logging.getLogger(__name__)



def _serialize_debug(debug: dict, dense_query: str) -> dict:
    """Strip large text fields from debug info to keep state lightweight."""
    if debug.get("multi_query"):
        per_query = debug.get("per_query", [])
        dense_count = sum(len(q.get("dense_results", [])) for q in per_query)
        bm25_count = sum(len(q.get("bm25_results", [])) for q in per_query)
    else:
        dense_count = len(debug.get("dense_results", []))
        bm25_count = len(debug.get("bm25_results", []))
    reranked = debug.get("reranked", debug.get("reranked_filtered", []))
    result = {
        "multi_query": debug.get("multi_query", False),
        "query_count": debug.get("query_count", 1),
        "dense_count": dense_count,
        "bm25_count": bm25_count,
        "rrf_total": len(debug.get("rrf_ranked", [])),
        "rrf_top5_scores": [
            {
                "chunk_id": cid,
                "rrf_normalized": round(s / debug["rrf_max_raw"], 4) if debug["rrf_max_raw"] else 0,
                "dense_score": round(debug["dense_scores"].get(cid, 0), 4),
                "bm25_score": round(debug["bm25_scores"].get(cid, 0), 4),
            }
            for cid, (_, s) in debug.get("rrf_ranked", [])[:5]
        ],
        "reranked_count": len(reranked),
        "rerank_top3_scores": [
            {
                "chunk_id": r.get("chunk_id", ""),
                "rerank_score": round(r.get("rerank_score", r.get("score", 0)), 4),
                "text_preview": r.get("text", "")[:100],
            }
            for r in reranked[:3]
        ],
        "dense_query_used": dense_query,
    }
    return result


class AgentState(TypedDict):
    query: str
    query_type: str
    confidence: float
    graph_eligible: bool
    documents: Annotated[list[dict], operator.add]
    graph_context: str
    graph_entities: list[str]
    sub_queries: list[str]
    graphrag_context: str
    retrieval_path: str
    retrieval_debug: dict  # debug info from hybrid retriever
    search_debug_data: dict  # full SearchDebugResponse for frontend "分析" button
    draft_answer: str
    final_answer: str
    citations: list[str]
    validation: dict
    validation_feedback: str
    iteration: int
    max_iterations: int
    error: str
    folder: str
    tags: list[str]
    # 单文件筛选（前端选中具体文件时传入；优先于 folder/tags 用于检索过滤）
    doc_ids: list[str]
    # Excel 强制路由相关：
    # force_sql=True 时（folder/tags 过滤后文档全为 Excel 文件），强制走 sql_agent
    # 且 sql_agent 失败时不再 fallback 到文本检索（用户明确只看 Excel）
    force_sql: bool
    # 重判防死循环：从 retrieval_agent → answer_validator → sql_agent 自动重判后置 True
    # 防止 sql_agent → answer_generator → answer_validator → sql_agent 循环
    rerouted_to_sql: bool


# [DISABLED] GraphRAG pipeline: holistic queries now route to retrieval_agent.
# Original routing: "holistic" → "graphrag_search"
# The graphrag_search node and _route_after_graphrag edge remain in the graph
# for compilation integrity but are unreachable.
def _format_sql_result_as_document(
    sheet_meta: dict,
    sql: str,
    sql_result: dict,
    err: str,
    score: float,
) -> dict:
    """把 SQL 检索结果格式化为一个 document，注入 documents 列表。

    answer_generator / validator 拿到这个 document 的 text 字段即可生成回答，
    与文本 RAG 的 chunk document 同构，便于统一评估与引用溯源。
    """
    columns = sheet_meta.get("columns", []) or []
    schema_lines = []
    for c in columns:
        if isinstance(c, dict):
            cn = c.get("cn", "")
            en = c.get("en", "")
            ctype = c.get("type", "TEXT")
            schema_lines.append(f"- {en} ({ctype}): {cn}")
    schema_text = "\n".join(schema_lines) if schema_lines else "(no schema)"

    # 结果行格式化
    result_cols = sql_result.get("columns", []) if isinstance(sql_result, dict) else []
    result_rows = sql_result.get("rows", []) if isinstance(sql_result, dict) else []
    row_count = sql_result.get("row_count", len(result_rows)) if isinstance(sql_result, dict) else 0
    if result_rows:
        preview = []
        for i, row in enumerate(result_rows[:50], 1):
            parts = [f"{col}={val}" for col, val in zip(result_cols, row)]
            preview.append(f"  {i}. {', '.join(parts)}")
        result_text = "\n".join(preview)
        if row_count > 50:
            result_text += f"\n  ... ({row_count} rows total, showing first 50)"
    else:
        result_text = "(empty result)"

    err_note = f"\n[SQL 执行告警] {err}" if err else ""

    text = (
        f"[数据源: Excel Sheet \"{sheet_meta.get('sheet_name', '')}\"]\n"
        f"[表结构]\n{schema_text}\n\n"
        f"[执行的 SQL]\n{sql}\n\n"
        f"[查询结果] ({row_count} 行)\n{result_text}{err_note}"
    )

    return {
        "doc_id": sheet_meta.get("doc_id", ""),
        "chunk_id": sheet_meta.get("meta_id", ""),  # 用 sheet meta_id 作为检索单元标识
        "text": text,
        "score": score,
        "source_type": "sql",  # 标记来源类型，便于评估/前端区分
        "sheet_meta_id": sheet_meta.get("meta_id", ""),
        "sheet_name": sheet_meta.get("sheet_name", ""),
        "sql": sql,
        "sql_result_columns": result_cols,
        "sql_result_row_count": row_count,
    }


def _route_by_query_type(state: AgentState) -> str:
    query_type = state.get("query_type", "simple_fact")
    graph_eligible = state.get("graph_eligible", False)

    if query_type == "chitchat":
        return "chitchat"
    if query_type == "sql_query":
        return "sql_agent"
    if query_type == "holistic":
        return "retrieval_agent"  # DISABLED: was "graphrag_search"

    # LightRAG path: multi-hop/comparison/graph-eligible → vector-based entity navigation
    needs_graph = query_type in ("multi_hop", "comparison") or (
        query_type in ("simple_fact", "definition") and graph_eligible
    )
    if needs_graph:
        return "lightrag_agent"

    return "retrieval_agent"


def _route_for_multi_hop(state: AgentState) -> str:
    query_type = state.get("query_type", "simple_fact")
    graph_eligible = state.get("graph_eligible", False)

    if query_type in ("multi_hop", "comparison"):
        return "retrieval_agent"
    # simple_fact/definition w/ graph_eligible also needs retrieval after graph enrich
    if query_type in ("simple_fact", "definition") and graph_eligible:
        return "retrieval_agent"
    return "answer_generator"


# [DISABLED] GraphRAG — retained for graph compilation, unreachable via routing
def _route_after_graphrag(state: AgentState) -> str:
    if state.get("graphrag_context"):
        return "answer_generator"
    return "retrieval_agent"


# 检测回答中"信息不足"标识的短语（answer_generator prompt 固定输出"提供的文档中没有足够的信息..."）
_INSUFFICIENT_PHRASES = (
    "没有足够的信息",
    "无法回答",
    "无法找到",
    "信息不足",
    "不足以回答",
    "缺乏相关信息",
    "未提供足够",
    "insufficient information",
    "cannot answer",
    "no information",
    "not enough information",
)


def _answer_indicates_insufficient(answer: str) -> bool:
    """检测 LLM 回答是否表示"信息不足以回答"。

    answer_generator 的 prompt 在 context 不足时固定输出"提供的文档中没有足够的信息来回答这个问题。"
    这种情况 answer_validator 通常会判 is_valid=true（因为回答说了实话），
    但实际上用户问题没被解决，应该尝试走 nl2sql 拿真实数据。
    """
    if not answer:
        return False
    text = answer.lower()
    return any(p.lower() in text for p in _INSUFFICIENT_PHRASES)


def _has_excel_sheet_chunk(documents: list[dict]) -> bool:
    """检测 documents 中是否存在 excel_sheet 类型的 chunk。"""
    for d in documents:
        meta = d.get("metadata", {}) or {}
        if meta.get("source") == "excel_sheet":
            return True
        if d.get("source_type") == "excel_sheet":
            return True
        # 兜底：chunk_id 前缀 excel: 也是 excel_sheet chunk（_build_sheet_summary_chunk 的格式）
        cid = d.get("chunk_id", "") or ""
        if cid.startswith("excel:"):
            return True
    return False


def _route_after_validation(state: AgentState) -> str:
    validation = state.get("validation", {})
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", settings.agent_max_iterations)
    is_valid = validation.get("is_valid", True)
    failure_reasons = validation.get("failure_reasons", [])
    docs = state.get("documents", [])
    has_excel_chunk = _has_excel_sheet_chunk(docs)

    # 重判场景的最终保护：已经重判到 sql_agent 跑过了（rerouted_to_sql=True），
    # validator 还说不通过 → 直接 END，避免 retrieval↔sql_agent 死循环。
    # 因为此时已经穷尽了 doc rag + nl2sql 两条路径：
    #   - doc rag: context_insufficient 触发了重判
    #   - sql_agent: 跑了 NL2SQL（或 fallback 到 retrieval）
    #   - 再走 retrieval_agent / answer_generator 重试不会带来新信息
    # 同一份文档库检索结果一样，继续烧 token 无意义。
    if state.get("rerouted_to_sql", False) and not is_valid:
        logger.info(
            "rerouted_to_sql=True + still invalid → END "
            "(avoid retrieval↔sql_agent loop, iteration=%d/%d)",
            iteration, max_iter,
        )
        return END

    # 自动重判触发条件（优先于正常 END/重试路径）：
    # 1. 尚未重判过（防死循环）
    # 2. 检索到了 excel_sheet 类型的 chunk（之前 doc rag 检索到了 sheet 摘要 chunk）
    # 3. validator 标 context_insufficient，OR 回答文本本身含"信息不足"标识
    #    （后者用于 validator 误判 is_valid=true 的兜底场景）
    if (
        not state.get("rerouted_to_sql", False)
        and has_excel_chunk
        and iteration < max_iter
    ):
        answer = state.get("final_answer") or state.get("draft_answer") or ""
        if "context_insufficient" in failure_reasons or _answer_indicates_insufficient(answer):
            logger.info(
                "Rerouting to sql_agent: excel_sheet chunk + %s detected",
                "context_insufficient" if "context_insufficient" in failure_reasons
                else "answer indicates insufficiency",
            )
            return "sql_agent"

    if not is_valid and iteration < max_iter:
        if "context_insufficient" in failure_reasons:
            return "retrieval_agent"
        return "answer_generator"
    return END


def _should_force_sql(
    folder: str | None,
    tags: list[str] | None,
    doc_ids: list[str] | None = None,
) -> bool:
    """检测 folder/tags/doc_ids 过滤后的文档是否全为 Excel 文件。

    - folder/tags/doc_ids 都为空 → False（不强制，走正常路由）
    - 过滤后无文档 → False（让 sql_agent 自然 fallback 处理"无数据"场景）
    - 过滤后文档全为 .xlsx/.xls → True（强制 sql_agent，且失败时不 fallback 到文本检索）
    - 含其他类型文档 → False（保持正常路由）

    doc_ids 优先于 folder/tags：用户在前端选中具体文件时走 doc_ids 路径。
    """
    if not folder and not tags and not doc_ids:
        return False
    try:
        from src.storage.doc_store import list_documents, get_document
        if doc_ids:
            # 单/多文件筛选：逐个查 doc 元数据
            docs = []
            for did in doc_ids:
                d = get_document(did)
                if d:
                    docs.append(d)
        else:
            docs = list_documents(folder=folder, tags=tags, limit=1000)
        if not docs:
            return False
        excel_exts = {".xlsx", ".xls"}
        for d in docs:
            fn = d.get("filename", "")
            ext = "." + fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if ext not in excel_exts:
                return False
        logger.info(
            "force_sql=True: all %d docs in filter are Excel files", len(docs)
        )
        return True
    except Exception as e:
        logger.warning("force_sql detection failed: %s", e)
        return False


class AgenticRAGWorkflow:
    def __init__(self):
        self.query_router = QueryRouter()
        self.retrieval_agent = RetrievalAgent()
        self.graph_agent = GraphAgent()
        self.answer_validator = AnswerValidator()
        self.lightrag_retriever = LightRAGRetriever()
        self._llm = None
        self._graphrag_query = None
        self._graph = self._build_graph()

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm()
        return self._llm

    def _rewrite_query(self, query: str) -> tuple[list[str], str]:
        """Use LLM to rewrite a query into multiple dense rephrases + one bm25 query.

        Multi-Query Retrieval：把一个问题改写成多条等价 dense query（语义召回靠
        多样性），并提取一份共享的 bm25 query（关键词无需多样化）。返回
        ``(dense_queries, bm25_query)``，dense 数量由 LLM 在
        ``[query_rewrite_count-1, query_rewrite_count+1]`` 区间内自行决定。

        缓存由 ``CachedLLM`` 自动处理（相同 prompt 字符串命中即返回）。
        prompt 包含 ``query_rewrite_language`` 和 ``query_rewrite_count``，
        切换任一参数会让 prompt 字符串变化 → CachedLLM 的 key 自然失效。
        是否启用缓存由全局 ``settings.cache_enabled`` 决定。

        LLM 调用失败时回退 ``([query], query)``，CachedLLM 失败时不会写入缓存，
        下次仍会重试。
        """
        import json

        n = max(1, int(settings.query_rewrite_count))
        min_n = max(1, n - 1)
        max_n = n + 1

        try:
            prompt = QUERY_REWRITE_SYSTEM.format(
                language=settings.query_rewrite_language,
                n=n,
                min_n=min_n,
                max_n=max_n,
            )
            prompt += f"\n\nUser question: {query}"
            resp = self._get_llm().invoke(prompt)
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("\n```", 1)[0]
            result = json.loads(text)
            dense_queries = [str(x) for x in result.get("dense_queries", []) if x]
            bm25_query = str(result.get("bm25_query", query)) or query

            # 约束 dense 数量到 [min_n, max_n]；LLM 偶发越界时截断/补足
            if len(dense_queries) > max_n:
                dense_queries = dense_queries[:max_n]
            while len(dense_queries) < min_n:
                dense_queries.append(query)

            return dense_queries if dense_queries else [query], bm25_query
        except Exception:
            return [query], query

    # [DISABLED] GraphRAG query instance — retained for graph compilation
    def _get_graphrag(self):
        if self._graphrag_query is None:
            from src.knowledge_graph.graphrag_query import GraphRAGQuery
            self._graphrag_query = GraphRAGQuery()
        return self._graphrag_query

    def _build_graph(self) -> Any:
        builder = StateGraph(AgentState)

        builder.add_node("query_router", self._node_query_router)
        builder.add_node("chitchat", self._node_chitchat)
        builder.add_node("sql_agent", self._node_sql_agent)
        builder.add_node("retrieval_agent", self._node_retrieval_agent)
        builder.add_node("graph_agent", self._node_graph_agent)
        builder.add_node("lightrag_agent", self._node_lightrag_agent)
        # [DISABLED] GraphRAG node — retained for graph compilation, unreachable via routing
        builder.add_node("graphrag_search", self._node_graphrag_search)
        builder.add_node("answer_generator", self._node_answer_generator)
        builder.add_node("answer_validator", self._node_answer_validator)

        builder.add_edge(START, "query_router")
        builder.add_conditional_edges("query_router", _route_by_query_type)
        builder.add_edge("chitchat", END)
        # sql_agent 是纯检索节点（NL2SQL+执行），结果转 documents 后交给统一生成链路
        builder.add_edge("sql_agent", "answer_generator")
        builder.add_conditional_edges("graph_agent", _route_for_multi_hop)
        # [DISABLED] GraphRAG edge — retained for graph compilation
        builder.add_conditional_edges("graphrag_search", _route_after_graphrag)
        builder.add_edge("retrieval_agent", "answer_generator")
        builder.add_edge("lightrag_agent", "answer_generator")
        builder.add_edge("answer_generator", "answer_validator")
        builder.add_conditional_edges("answer_validator", _route_after_validation)

        return builder.compile()

    def invoke(
        self,
        query: str,
        folder: str | None = None,
        tags: list[str] | None = None,
        doc_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        force_sql = _should_force_sql(folder, tags, doc_ids)
        state: AgentState = {
            "query": query,
            "query_type": "simple_fact",
            "confidence": 0.0,
            "graph_eligible": False,
            "documents": [],
            "graph_context": "",
            "graph_entities": [],
            "sub_queries": [],
            "graphrag_context": "",
            "retrieval_path": "",
            "retrieval_debug": {},
            "draft_answer": "",
            "final_answer": "",
            "citations": [],
            "validation": {},
            "validation_feedback": "",
            "iteration": 0,
            "max_iterations": settings.agent_max_iterations,
            "error": "",
            "folder": folder or "",
            "tags": tags or [],
            "doc_ids": doc_ids or [],
            "force_sql": force_sql,
            "rerouted_to_sql": False,
        }
        return self._graph.invoke(state)

    async def astream(
        self,
        query: str,
        folder: str | None = None,
        tags: list[str] | None = None,
        doc_ids: list[str] | None = None,
    ):
        force_sql = _should_force_sql(folder, tags, doc_ids)
        state: AgentState = {
            "query": query,
            "query_type": "simple_fact",
            "confidence": 0.0,
            "graph_eligible": False,
            "documents": [],
            "graph_context": "",
            "graph_entities": [],
            "sub_queries": [],
            "graphrag_context": "",
            "retrieval_path": "",
            "retrieval_debug": {},
            "draft_answer": "",
            "final_answer": "",
            "citations": [],
            "validation": {},
            "validation_feedback": "",
            "iteration": 0,
            "max_iterations": settings.agent_max_iterations,
            "error": "",
            "folder": folder or "",
            "tags": tags or [],
            "doc_ids": doc_ids or [],
            "force_sql": force_sql,
            "rerouted_to_sql": False,
        }
        async for event in self._graph.astream(state):
            yield event

    def _node_chitchat(self, state: AgentState) -> dict:
        try:
            llm = self._get_llm()
            system = CHITCHAT_SYSTEM.format(language=settings.query_rewrite_language)
            resp = llm.invoke([("system", system), ("human", state["query"])])
            return {"final_answer": resp.content, "draft_answer": resp.content}
        except Exception as e:
            return {"final_answer": f"Chat failed: {e}", "error": str(e)}

    def _node_sql_agent(self, state: AgentState) -> dict:
        """SQL 检索节点（纯检索阶段）：向量召回 Sheet → 多表选择 → NL2SQL → 执行（含重试）。

        不生成最终回答。把执行结果格式化为 documents 注入 state，
        交给 answer_generator → validator 统一生成链路。

        失败处理：
        - force_sql=True（用户明确选了 Excel 文件）→ 不 fallback，返回空 documents
          让 answer_generator 看到"无数据"信号自己组织回答
        - 否则 → 自动 fallback 到 retrieval_agent（文本 RAG）

        重判场景（从 answer_validator 路由过来）：设置 rerouted_to_sql=True 防死循环。
        此时之前 retrieval_agent 检索到的 sheet 摘要 chunk 仍在 documents 中，
        sql_agent 返回的 SQL 结果会追加进去（operator.add），让 answer_generator 看到
        "sheet 摘要 + 真实 SQL 结果" 双重信息生成更好的回答。
        """
        # 判断是否为重判场景：已有 documents 且不是 force_sql 模式（force_sql 首次进入时 documents 为空）
        is_reroute = bool(state.get("documents")) and not state.get("force_sql", False)

        try:
            from src.excel_rag.qa import ExcelQA
            qa = ExcelQA()
            r = qa.retrieve(
                state["query"],
                folder=state.get("folder") or None,
                tags=state.get("tags") or None,
                doc_ids=state.get("doc_ids") or None,
            )

            # 没有任何结构化数据或召回失败
            if r.get("error") in ("no_sheets", "no_relevant_sheet"):
                if state.get("force_sql"):
                    # 用户明确选了 Excel 文件，不 fallback 到文本检索
                    logger.info("force_sql=True, no sheet recalled, skipping fallback: %s", r["error"])
                    return {
                        "documents": [],
                        "retrieval_path": "sql_no_sheet_forced",
                        "error": r["error"],
                        "rerouted_to_sql": is_reroute,
                        "retrieval_debug": {
                            "sql_fallback_reason": f"forced_sql_{r['error']}",
                            "sql_recalled_sheets": r.get("recalled_sheets", []),
                        },
                    }
                logger.info("sql_agent fallback to retrieval_agent: %s", r["error"])
                retrieval_result = self._node_retrieval_agent(state)
                retrieval_result["retrieval_path"] = "sql_fallback"
                # 补充检索调试信息，便于评估分析 fallback 情况
                retrieval_result["retrieval_debug"] = {
                    **retrieval_result.get("retrieval_debug", {}),
                    "sql_fallback_reason": r["error"],
                    "sql_recalled_sheets": r.get("recalled_sheets", []),
                }
                retrieval_result["rerouted_to_sql"] = is_reroute
                return retrieval_result

            selected = r["selected_sheet"]
            sheet_meta = selected["sheet_meta"]
            sql = r["sql"]
            sql_result = r["sql_result"] or {}
            recalled = r["recalled_sheets"]
            attempts = r["attempts"]
            err = r["error"]

            # 把 SQL 执行结果格式化为一个 document，注入 documents
            documents = [_format_sql_result_as_document(
                sheet_meta=sheet_meta,
                sql=sql,
                sql_result=sql_result,
                err=err,
                score=selected.get("score", 0.0),
            )]

            return {
                "documents": documents,
                "retrieval_path": "sql_nl2sql" if not is_reroute else "sql_rerouted",
                "rerouted_to_sql": is_reroute,
                "retrieval_debug": {
                    "sql_query": sql,
                    "sql_sheet_meta_id": selected["meta_id"],
                    "sql_sheet_name": sheet_meta["sheet_name"],
                    "sql_recalled_sheets": recalled,
                    "sql_attempts": attempts,
                    "sql_error": err,
                    "sql_result_columns": sql_result.get("columns", []) if isinstance(sql_result, dict) else [],
                    "sql_result_row_count": sql_result.get("row_count", 0) if isinstance(sql_result, dict) else 0,
                },
            }
        except Exception as e:
            logger.error("sql_agent failed: %s", e, exc_info=True)
            if state.get("force_sql"):
                # force_sql 模式下异常也不 fallback，保留错误信息给 answer_generator
                return {
                    "documents": [],
                    "retrieval_path": "sql_error_forced",
                    "error": str(e),
                    "rerouted_to_sql": is_reroute,
                }
            # 任何异常都降级到文本检索，保证不阻断主流程
            retrieval_result = self._node_retrieval_agent(state)
            retrieval_result["retrieval_path"] = "sql_fallback_error"
            retrieval_result["error"] = str(e)
            retrieval_result["rerouted_to_sql"] = is_reroute
            return retrieval_result

    def _node_query_router(self, state: AgentState) -> dict:
        result = self.query_router.classify(state["query"])
        # force_sql=True（用户筛选的文档全为 Excel 文件）→ 强制走 sql_agent
        # chitchat 例外：闲聊仍走 chitchat，否则 "你好" 也会跑去 NL2SQL
        if state.get("force_sql") and result["query_type"] != "chitchat":
            logger.info(
                "force_sql=True, overriding query_type %s → sql_query",
                result["query_type"],
            )
            result["query_type"] = "sql_query"
        return {
            "query_type": result["query_type"],
            "confidence": result["confidence"],
            "graph_eligible": result.get("graph_eligible", False),
        }

    def _node_retrieval_agent(self, state: AgentState) -> dict:
        try:
            folder = state.get("folder", "") or None
            tags = state.get("tags", []) or None
            # doc_ids 优先于 folder/tags：前端选中具体文件时直接用，避免被文件夹稀释
            doc_ids = state.get("doc_ids") or None
            if not doc_ids and (folder or tags):
                from src.storage.doc_store import get_doc_ids_by_filter
                doc_ids = get_doc_ids_by_filter(folder=folder, tags=tags)
                if not doc_ids:
                    return {"documents": [], "error": "No documents match the filter"}

            original_query = state["query"]
            graph_entities = state.get("graph_entities", [])
            sub_queries = state.get("sub_queries", [])
            extra_terms = " ".join(graph_entities[:10]) if graph_entities else ""

            # 构建 Multi-Query 改写：(dense_queries, bm25_query)
            if sub_queries:
                # 图谱子问题路径：每个子问题各自改写，dense 汇总，bm25 取首条
                all_dense: list[str] = []
                shared_bm25 = original_query
                for sq in sub_queries[:3]:
                    if settings.query_rewrite_enabled:
                        dqs, bq = self._rewrite_query(sq)
                        all_dense.extend(dqs)
                        if not shared_bm25 or shared_bm25 == original_query:
                            shared_bm25 = bq
                    else:
                        all_dense.append(sq)
                # 子问题 × 多改写可能产生过多 dense query，封顶避免检索开销爆炸
                max_pairs = max(3, settings.query_rewrite_count * 2)
                dense_queries = all_dense[:max_pairs]
                path_label = f"[Multi-query] {len(sub_queries)} sub-queries × rewrite → {len(dense_queries)} dense queries"
            else:
                # 单问题路径：原始 query 作为 Q0 + 改写 dense query + 一条共享 bm25 query
                # 原始 query 参与 dense 检索 + RRF 融合（兜底 + 多信号源，与 rerank 用原始 query 对齐）
                if settings.query_rewrite_enabled:
                    rewrites, shared_bm25 = self._rewrite_query(original_query)
                    dense_queries = [original_query] + [
                        q for q in rewrites if q and q != original_query
                    ]
                else:
                    dense_queries, shared_bm25 = [original_query], original_query
                path_label = f"[Multi-query] {len(dense_queries)} dense (Q0=原始) + 1 bm25"

            # 图谱实体关键词追加到 bm25 query（仅 BM25 通道，保留 dense 语义方向）
            if extra_terms:
                shared_bm25 = f"{shared_bm25} {extra_terms}".strip()

            results, debug = self.retrieval_agent._retriever.retrieve_multi(
                original_query,
                dense_queries,
                shared_bm25,
                top_k=settings.hybrid_top_k,
                doc_ids=doc_ids,
            )
            results = self.retrieval_agent._dedup_by_chunk_id(results)

            from src.retrieval.debug_formatter import build_search_debug_response
            search_debug_data = build_search_debug_response(
                original_query, debug, dense_queries, shared_bm25, top_k=settings.hybrid_top_k,
            )

            return {
                "documents": results,
                "retrieval_path": path_label,
                "retrieval_debug": _serialize_debug(debug, original_query),
                "search_debug_data": search_debug_data,
            }
        except Exception as e:
            return {"error": f"Retrieval failed: {e}"}

    def _filter_relevant_entities(self, query: str, paths: list[dict]) -> list[str]:
        """Use LLM to select only query-relevant entities from graph expansion results."""
        if not paths:
            return []

        # Pre-filter: only keep paths with whitelisted relation types (if whitelist is set)
        whitelist = set(settings.graph_relation_whitelist) if settings.graph_relation_whitelist else None
        if whitelist:
            filtered_paths = []
            for p in paths:
                rel_types = p.get("relation_types", [])
                if any(rt in whitelist for rt in rel_types):
                    filtered_paths.append(p)
            if filtered_paths:
                paths = filtered_paths

        path_lines = []
        for p in paths:
            s = p.get("subject_name", "")
            o = p.get("object_name", "")
            rel = ", ".join(p.get("relation_types", []))
            path_lines.append(f"- {s} --[{rel}]--> {o}")
        paths_text = "\n".join(path_lines[:30])

        prompt = (
            f"Given a user query and a set of graph relationships found, "
            f"select ONLY the entity names that are directly relevant to answering the query. "
            f"Ignore irrelevant entities. Return a JSON array of entity name strings.\n\n"
            f"Query: {query}\n\n"
            f"Graph relationships:\n{paths_text}\n\n"
            f"Relevant entities (JSON array):"
        )
        resp = self._get_llm().invoke(prompt)
        try:
            import json, re
            match = re.search(r"\[.*?\]", resp.content, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return []

    def _node_graph_agent(self, state: AgentState) -> dict:
        try:
            entities = self.graph_agent.extract_entities_from_query(state["query"])
            if entities:
                paths = self.graph_agent.expand(entities)
                graph_context = self.graph_agent.format_context(paths)

                graph_entities = list(entities)
                sub_queries: list[str] = []
                if paths:
                    relevant = self._filter_relevant_entities(state["query"], paths)
                    for name in relevant:
                        if name not in graph_entities:
                            graph_entities.append(name)
                    # Generate targeted sub-questions for multi-query retrieval
                    if relevant:
                        sub_queries = self.graph_agent.generate_sub_questions(
                            state["query"], graph_entities, paths
                        )
            else:
                graph_context = "No entities found for graph expansion."
                graph_entities = []
                sub_queries = []
            return {
                "graph_context": graph_context,
                "graph_entities": graph_entities,
                "sub_queries": sub_queries,
            }
        except Exception as e:
            return {
                "graph_context": f"Graph query failed: {e}",
                "graph_entities": [],
                "sub_queries": [],
                "error": str(e),
            }

    def _node_lightrag_agent(self, state: AgentState) -> dict:
        """LightRAG pipeline: entity_index → relation_index → graph_expand → chunk_retrieve.

        Replaces the LLM-based NER + separate graph_expand + retrieval steps.
        Falls back to existing graph_agent + retrieval if LightRAG indexes are empty.
        """
        try:
            folder = state.get("folder", "") or None
            tags = state.get("tags", []) or None
            doc_ids = None
            if folder or tags:
                from src.storage.doc_store import get_doc_ids_by_filter
                doc_ids = get_doc_ids_by_filter(folder=folder, tags=tags)
                if not doc_ids:
                    return {"documents": [], "retrieval_path": "No documents match filter"}

            # Check if LightRAG indexes are populated; fall back if not
            if self.lightrag_retriever.entity_index.count() == 0:
                # Fallback: use existing graph_agent + retrieval pipeline
                graph_result = self._node_graph_agent(state)
                if graph_result.get("graph_entities"):
                    state_with_enrich = {**state, **graph_result}
                    retrieval_result = self._node_retrieval_agent(state_with_enrich)
                    return {
                        **graph_result,
                        **retrieval_result,
                        "retrieval_path": "[Fallback] graph_agent→retrieval (LightRAG index empty)",
                    }
                # No entities at all — go straight to retrieval
                retrieval_result = self._node_retrieval_agent(state)
                return {
                    **retrieval_result,
                    "graph_context": "",
                    "graph_entities": [],
                    "retrieval_path": "[Fallback] retrieval_only (no entities)",
                }

            # Full LightRAG pipeline
            result = self.lightrag_retriever.retrieve(
                state["query"],
                doc_ids=doc_ids,
            )

            return {
                "documents": result["documents"],
                "graph_context": result["graph_context"],
                "graph_entities": result.get("entities_found", []),
                "retrieval_path": result.get("retrieval_path", "[LightRAG]"),
            }
        except Exception as e:
            logger = __import__("logging").getLogger(__name__)
            logger.warning(f"LightRAG agent failed, falling back: {e}")
            # Fallback to existing pipeline
            from src.agents.retrieval_agent import RetrievalAgent
            try:
                results = self.retrieval_agent.search(state["query"])
                return {
                    "documents": results,
                    "graph_context": "",
                    "graph_entities": [],
                    "retrieval_path": f"[Fallback after LightRAG error] retrieval_only",
                }
            except Exception:
                return {"error": f"LightRAG/Retrieval failed: {e}"}

    # [DISABLED] GraphRAG search node — unreachable via current routing
    def _node_graphrag_search(self, state: AgentState) -> dict:
        try:
            graphrag = self._get_graphrag()
            query_type = state.get("query_type", "holistic")

            if query_type == "holistic":
                result = graphrag.search_sync(state["query"], mode="global")
            else:
                result = graphrag.search_sync(state["query"], mode="drift")

            return {
                "graphrag_context": (
                    f"[Microsoft GraphRAG - {result['search_mode']} search]\n"
                    f"{result['answer']}\n"
                    f"(LLM calls: {result['llm_calls']}, "
                    f"tokens: {result['prompt_tokens'] + result['output_tokens']})"
                ),
            }
        except Exception as e:
            return {
                "graphrag_context": "",
                "error": f"GraphRAG search failed: {e}",
            }

    def _node_answer_generator(self, state: AgentState) -> dict:
        try:
            context = ""
            citations = []
            retrieval_path = state.get("retrieval_path", "")

            if state.get("graphrag_context"):
                context = state["graphrag_context"]

            if state.get("documents"):
                doc_context = self.retrieval_agent.extract_context(state["documents"])
                context = f"{context}\n\n[Retrieved Documents]\n{doc_context}" if context else doc_context
                citations = [
                    f"[{i + 1}] {d.get('doc_id', '?')}/{d.get('chunk_id', '?')}"
                    for i, d in enumerate(state["documents"][:10])
                ]

            if state.get("graph_context"):
                context = f"[Knowledge Graph Context]\n{state['graph_context']}\n\n{context}"

            if not context.strip():
                return {
                    "draft_answer": "I cannot find sufficient context to answer this question.",
                    "citations": [],
                }

            # Append retrieval path for observability (not visible to LLM but stored in state)
            if retrieval_path:
                context = f"[Retrieval: {retrieval_path}]\n\n{context}"

            llm = self._get_llm()
            # Truncate context at document boundary (on "\n\n---\n\n") to avoid
            # cutting in the middle of a chunk. Budget: 8000 chars.
            max_ctx = 8000
            if len(context) > max_ctx:
                cut = context.rfind("\n\n---\n\n", 0, max_ctx)
                context = context[:cut] if cut > 0 else context[:max_ctx]

            # 按 retrieval_path 分支选择 prompt：
            # - sql_nl2sql: SQL 执行结果，用表格化 prompt
            # - 其他: 文本 RAG 默认 prompt
            if retrieval_path == "sql_nl2sql":
                prompt = SQL_ANSWER_GENERATION_SYSTEM.format(
                    context=context, question=state["query"],
                    language=settings.query_rewrite_language,
                )
            else:
                prompt = ANSWER_GENERATION_SYSTEM.format(
                    context=context, question=state["query"],
                    language=settings.query_rewrite_language,
                )

            # Incorporate validation feedback on retry
            feedback = state.get("validation_feedback", "")
            if feedback:
                prompt += f"\n\n[Previous answer was rejected. Fix the following issues:]\n{feedback}"

            resp = llm.invoke(prompt)

            return {
                "draft_answer": resp.content,
                "citations": citations,
            }
        except Exception as e:
            return {"draft_answer": f"Answer generation failed: {e}", "error": str(e)}

    def _node_answer_validator(self, state: AgentState) -> dict:
        try:
            context = ""
            if state.get("documents"):
                # Use full text of top documents (up to 6000 chars) so the validator
                # sees the same evidence the answer generator used, preventing false
                # "unsupported_claim" verdicts from truncated context.
                context_parts = []
                char_budget = 6000
                for d in state["documents"][:8]:
                    text = d.get("text", "")
                    if len(context_parts) > 0:
                        char_budget -= 2  # for "\n"
                    if char_budget <= 0:
                        break
                    text = text[:char_budget]
                    char_budget -= len(text)
                    context_parts.append(text)
                context = "\n".join(context_parts)

            validation = self.answer_validator.validate(
                question=state["query"],
                answer=state.get("draft_answer", ""),
                context=context,
                citations=state.get("citations", []),
            )

            new_iteration = state.get("iteration", 0) + 1
            final_answer = validation.get("improved_answer") or state.get("draft_answer", "")

            # Build feedback string from failure reasons for retry
            failure_reasons = validation.get("failure_reasons", [])
            issues = validation.get("issues", [])
            feedback_parts = []
            reason_map = {
                "missing_citation": "Answer lacks source citations for factual claims. Cite every claim with [N], where N is the context chunk number (e.g. [1], [2]).",
                "unsupported_claim": "Answer contains claims not supported by context. Remove or limit to evidence in context only.",
                "context_insufficient": "Context lacks information to answer. State 'insufficient information' rather than guessing.",
                "conflict_detected": "Context has conflicting information. Acknowledge the conflict explicitly.",
            }
            for reason in failure_reasons:
                if reason in reason_map:
                    feedback_parts.append(reason_map[reason])
            feedback = "\n".join(feedback_parts) if feedback_parts else ""

            return {
                "validation": validation,
                "validation_feedback": feedback,
                "final_answer": final_answer,
                "iteration": new_iteration,
            }
        except Exception as e:
            return {
                "validation": {"is_valid": True},
                "validation_feedback": "",
                "final_answer": state.get("draft_answer", ""),
                "iteration": state.get("iteration", 0) + 1,
                "error": str(e),
            }


_workflow_instance = None


def get_workflow() -> AgenticRAGWorkflow:
    global _workflow_instance
    if _workflow_instance is None:
        _workflow_instance = AgenticRAGWorkflow()
    return _workflow_instance
