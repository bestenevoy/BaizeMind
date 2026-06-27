import operator
import uuid
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import StateGraph, START, END

from src.agents.query_router import QueryRouter
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.graph_agent import GraphAgent
from src.logging_config import get_request_id, set_request_id, reset_request_id
from src.retrieval.lightrag_retriever import LightRAGRetriever
from src.llm.deepseek import get_chat_llm
from config.prompts import ANSWER_GENERATION_SYSTEM, CHITCHAT_SYSTEM, QUERY_REWRITE_SYSTEM, SQL_ANSWER_GENERATION_SYSTEM
from config.settings import settings

import logging

logger = logging.getLogger(__name__)


def _ensure_request_id() -> Optional[Any]:
    """workflow 入口兜底设置 request_id（脚本/测试调用无 HTTP middleware 场景）。

    返回 Token 用于还原；若已设置（HTTP middleware 路径）则返回 None 不动。
    """
    if get_request_id() != "-":
        return None
    return set_request_id(uuid.uuid4().hex[:8])



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
    # 重判防死循环：从 answer_generator → sql_agent 自动重判后置 True
    # 防止 sql_agent → answer_generator → sql_agent 循环
    # [UNIFIED] sql_agent 现在仅作为统一召回后的条件性 Tool Call 触发，
    # 不再有独立 sql_query 路由路径，也不再基于 force_sql 短路进入。
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
            display_name = c.get("display_name", "")
            column_name = c.get("column_name", "")
            ctype = c.get("data_type", "TEXT")
            schema_lines.append(f"- {column_name} ({ctype}): {display_name}")
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
        # chunk_id 加 __sql_result 后缀，避免与 sheet_summary doc 的 chunk_id（meta_id）冲突
        # _dedup_by_chunk_id 按 chunk_id 去重先到先得，若两者 chunk_id 相同，
        # sheet_summary 先注入会占位，SQL 结果 doc 被丢弃 → answer_generator 拿不到 SQL 语句和结果
        "chunk_id": f"{sheet_meta.get('meta_id', '')}__sql_result",
        "text": text,
        "score": score,
        "source_type": "sql",  # 标记来源类型，便于评估/前端区分
        "sheet_meta_id": sheet_meta.get("meta_id", ""),
        "sheet_name": sheet_meta.get("sheet_name", ""),
        "sql": sql,
        "sql_result_columns": result_cols,
        # 暴露前 5 行结果，便于前端 chunks 详情直接渲染数据表（避免 doc.text 截断后只显示表结构）
        "sql_result_rows": result_rows[:5] if result_rows else [],
        "sql_result_row_count": row_count,
    }


def _route_by_query_type(state: AgentState) -> str:
    query_type = state.get("query_type", "simple_fact")
    graph_eligible = state.get("graph_eligible", False)

    if query_type == "chitchat":
        return "chitchat"
    # [UNIFIED] sql_query 路由分支已移除：所有非 chitchat 查询统一走向量召回
    # (retrieval_agent / lightrag_agent)，SQL 作为召回后 answer_generator 的条件性
    # Tool Call 触发（见 _route_after_generation）。
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


def _is_data_table_document(d: dict) -> bool:
    """判断单个 document 是否属于"数据表类文件"。

    数据表类文件判断标准（统一以 source_type / metadata.source / chunk_id 前缀为准）：
    - Excel/CSV/数据库链接表等结构化数据文件的 sheet_summary chunk：
      metadata.source == "excel_sheet" 或 source_type == "excel_sheet" 或 chunk_id 以 "excel:" 开头
    - SQL 执行结果 doc：source_type == "sql" 或 chunk_id 含 "__sql_result" 后缀
      （sql_agent 生成的 document，本质也是数据表查询产物）

    扩展点：未来 CSV / DB link 表接入时，只需在此函数添加新的 source 标识即可。
    """
    if not isinstance(d, dict):
        return False
    meta = d.get("metadata", {}) or {}
    source_type = d.get("source_type", "") or ""
    cid = d.get("chunk_id", "") or ""

    # Excel sheet 摘要 chunk
    if meta.get("source") == "excel_sheet":
        return True
    if source_type == "excel_sheet":
        return True
    if cid.startswith("excel:"):
        return True
    # SQL 执行结果 doc（_format_sql_result_as_document 生成）
    if source_type == "sql":
        return True
    if "__sql_result" in cid:
        return True
    return False


def _all_documents_are_data_tables(documents: list[dict]) -> bool:
    """检测召回的 documents 是否全部为数据表类文件。

    用于 retrieval_agent / lightrag_agent 之后路由决策：
    - 全部为数据表类 → 跳过 answer_generator 的 LLM 判断，直接进 sql_agent
    - 空召回 / 混合类型 → 保持原流程（answer_generator 判断是否需要 SQL）
    """
    if not documents:
        return False
    return all(_is_data_table_document(d) for d in documents if isinstance(d, dict))


def _route_after_retrieval(state: AgentState) -> str:
    """retrieval_agent / lightrag_agent 之后路由：数据表类文档短路到 sql_agent。

    [SHORT-CIRCUIT] 当召回的 documents 全部为数据表类文件（Excel/CSV/DB link 等）时，
    跳过 answer_generator 的 LLM 判断，直接进入 sql_agent 执行 NL2SQL。
    这避免了"先让 LLM 看摘要 → 判断信息不足 → 再触发 SQL"的额外 LLM 往返，
    在用户已通过 folder/tags/doc_ids 限定到纯数据表文件场景下显著提升响应效率。

    决策规则：
    1. 召回非空 + 全部为数据表类 → sql_agent（短路）
    2. 空召回 / 含非数据表文档 → answer_generator（保持原流程，由 LLM 判断）
       - 混合类型场景：LLM 先尝试用召回上下文回答；不足时 _route_after_generation
         仍会触发 sql_agent（数据表 chunk 已在召回中）

    防死循环：此函数仅在 retrieval_agent / lightrag_agent 之后调用一次，
    不会在 sql_agent → answer_generator 之后再次进入（该路径走 _route_after_generation）。
    """
    docs = state.get("documents", [])
    if _all_documents_are_data_tables(docs) and _has_excel_sheet_chunk(docs):
        logger.info(
            "Short-circuit to sql_agent: all %d recalled docs are data-table types",
            len(docs),
        )
        return "sql_agent"
    return "answer_generator"


def _route_after_generation(state: AgentState) -> str:
    """answer_generator 之后路由：统一召回 → LLM 决策 → 条件触发 SQL Tool Call。

    [UNIFIED] 这是新统一流程的核心决策点。answer_generator 基于统一召回的上下文
    （文档块 + 表结构 + 表摘要都在同一向量库）生成回答，其输出本身就是 LLM 对
    "召回是否充分"的决策：
    - 回答正常 → 召回充分，直接 END
    - 回答含"信息不足"短语 → 召回不充分，进入下面的条件性 SQL 触发判定

    条件触发 SQL Tool Call 的规则（对应设计文档三点决策）：
    1. rerouted_to_sql=True → 直接 END
       （sql_agent 已作为 Tool Call 执行过，answer_generator 已基于 SQL 结果生成
       最终答案，不再做任何路由决策。无论 answer 是否信息不足，流程结束。）
    2. 未重判 + 召回含 excel_sheet chunk + answer 信息不足 + iteration < max_iter
       → sql_agent（条件性 Tool Call：召回中含相关数据表，LLM 判断 SQL 可能获得答案）
    3. 其他 → END
       （召回不充分但无数据表可尝试 SQL → 返回"无法回答"，对应设计文档第 3 点）

    判定信号（不依赖额外 LLM 调用，复用 answer_generator 输出）：
    - _answer_indicates_insufficient(answer)：正则匹配回答文本中的"信息不足"短语
    - _has_excel_sheet_chunk(documents)：检测统一召回是否含 excel_sheet chunk
    """
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", settings.agent_max_iterations)
    docs = state.get("documents", [])
    has_excel_chunk = _has_excel_sheet_chunk(docs)
    answer = state.get("final_answer") or state.get("draft_answer") or ""
    answer_insufficient = _answer_indicates_insufficient(answer)

    # [SHORT-CIRCUIT] rerouted_to_sql=True → sql_agent 已执行过，直接 END。
    # 新统一流程下，sql_agent 是条件性 Tool Call（非独立路由），执行后 answer_generator
    # 已基于 SQL 结果生成最终答案。无论 answer 是否信息不足，都不再路由——
    # - answer 正常 → 最终答案，END
    # - answer 仍信息不足 → 已穷尽统一召回 + NL2SQL 两条路径，END 避免死循环
    if state.get("rerouted_to_sql", False):
        logger.info(
            "rerouted_to_sql=True → END (sql_agent already executed, iteration=%d/%d, insufficient=%s)",
            iteration, max_iter, answer_insufficient,
        )
        return END

    # 自动重判触发条件：
    # 1. 尚未重判过（防死循环，由上面的 short-circuit 保证）
    # 2. 检索到了 excel_sheet 类型的 chunk（统一召回检到了 sheet 摘要）
    # 3. answer 文本含"信息不足"短语（正则匹配，非 LLM 判定）
    # 4. iteration < max_iter（answer_generator 已 +1，这里用 +1 后的值判断）
    if (
        has_excel_chunk
        and answer_insufficient
        and iteration < max_iter
    ):
        logger.info(
            "Rerouting to sql_agent: excel_sheet chunk + answer indicates insufficiency"
        )
        return "sql_agent"

    return END


# [REMOVED] _should_force_sql: 旧版基于 folder/tags/doc_ids 全为 Excel 文件时
# 强制走 sql_query 路由的短路逻辑。新统一流程下，所有 query 都先走统一向量召回
# （Excel sheet 摘要已作为 chunk 存入主向量库，metadata.source="excel_sheet"），
# SQL 仅在 answer_generator 判定信息不足 + 召回含 excel_sheet chunk 时作为
# 条件性 Tool Call 触发。用户选 Excel 文件不再特殊路由，而是自然进入统一召回。


class AgenticRAGWorkflow:
    def __init__(self):
        self.query_router = QueryRouter()
        self.retrieval_agent = RetrievalAgent()
        self.graph_agent = GraphAgent()
        # [MERGED] answer_validator 节点已合并到 answer_generator：单次 LLM 调用
        # 同时生成 + 自检（详见 _node_answer_generator）。AnswerValidator 类仍保留供
        # 独立评测/脚本调用（src/agents/answer_validator.py），但不再实例化到 workflow。
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
        prompt 包含 ``response_language`` 和 ``query_rewrite_count``，
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
                language=settings.response_language,
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
        # [MERGED] answer_validator 已合并到 answer_generator：单次 LLM 调用同时生成 + 自检，
        # 重判信号改用正则匹配 _answer_indicates_insufficient + _has_excel_sheet_chunk，
        # 不再依赖独立的 validator LLM 调用。

        builder.add_edge(START, "query_router")
        builder.add_conditional_edges("query_router", _route_by_query_type)
        builder.add_edge("chitchat", END)
        # [UNIFIED] sql_agent 现在是条件触发的 SQL Tool Call 节点（不再有独立 sql_query 路由入口）：
        # 触发路径有二：
        # 1. retrieval_agent / lightrag_agent 之后召回全部为数据表类 → _route_after_retrieval 短路
        # 2. answer_generator 判定信息不足 + 召回含 excel_sheet chunk → _route_after_generation
        # NL2SQL+执行结果转 documents 后回到 answer_generator 生成最终答案（统一生成链路）。
        builder.add_edge("sql_agent", "answer_generator")
        builder.add_conditional_edges("graph_agent", _route_for_multi_hop)
        # [DISABLED] GraphRAG edge — retained for graph compilation
        builder.add_conditional_edges("graphrag_search", _route_after_graphrag)
        # [SHORT-CIRCUIT] 召回后立即判断：若全部为数据表类文件 → 直接 sql_agent
        # 跳过 answer_generator 的 LLM 判断，省一次 LLM 往返，提升纯数据表场景响应效率
        builder.add_conditional_edges("retrieval_agent", _route_after_retrieval)
        builder.add_conditional_edges("lightrag_agent", _route_after_retrieval)
        # answer_generator 单次 LLM 生成 + 自检后路由（合并了原 answer_validator 的职责）
        builder.add_conditional_edges("answer_generator", _route_after_generation)

        return builder.compile()

    def invoke(
        self,
        query: str,
        folder: str | None = None,
        tags: list[str] | None = None,
        doc_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        # [UNIFIED] 不再计算 force_sql：所有 query 统一走向量召回，SQL 作为
        # answer_generator 之后的条件性 Tool Call 触发（见 _route_after_generation）。
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
            "rerouted_to_sql": False,
        }
        token = _ensure_request_id()
        logger.info("workflow.invoke start: query=%r folder=%r tags=%r doc_ids=%r",
                    query, folder, tags, doc_ids)
        try:
            return self._graph.invoke(state)
        finally:
            if token is not None:
                reset_request_id(token)

    async def astream(
        self,
        query: str,
        folder: str | None = None,
        tags: list[str] | None = None,
        doc_ids: list[str] | None = None,
    ):
        # [UNIFIED] 不再计算 force_sql：所有 query 统一走向量召回，SQL 作为
        # answer_generator 之后的条件性 Tool Call 触发（见 _route_after_generation）。
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
            "rerouted_to_sql": False,
        }
        token = _ensure_request_id()
        logger.info("workflow.astream start: query=%r folder=%r tags=%r doc_ids=%r",
                    query, folder, tags, doc_ids)
        try:
            async for event in self._graph.astream(state):
                yield event
        finally:
            if token is not None:
                reset_request_id(token)

    def _node_chitchat(self, state: AgentState) -> dict:
        try:
            llm = self._get_llm()
            system = CHITCHAT_SYSTEM.format(language=settings.response_language)
            resp = llm.invoke([("system", system), ("human", state["query"])])
            return {"final_answer": resp.content, "draft_answer": resp.content}
        except Exception as e:
            return {"final_answer": f"Chat failed: {e}", "error": str(e)}

    def _node_sql_agent(self, state: AgentState) -> dict:
        """SQL Tool Call 节点（条件触发）：向量召回 Sheet → 多表选择 → NL2SQL → 执行（含重试）。

        [UNIFIED] 此节点现在 ONLY 作为统一召回 + answer_generator 之后的条件性 Tool Call
        被触发（见 _route_after_generation），不再有独立的 sql_query 路由入口，也不再基于
        force_sql 短路进入。统一召回（retrieval_agent / lightrag_agent）已经把文档块 +
        表结构 + 表摘要从同一向量库召回，answer_generator 基于召回内容生成回答；当回答
        表示"信息不足"且召回中含 excel_sheet chunk 时，本节点作为 Tool Call 被触发，执行
        NL2SQL 拿真实数据，把 SQL 结果 documents 追加到 state（operator.add），交给
        answer_generator 生成最终答案。

        失败处理（统一不再 fallback 到 retrieval_agent — 召回已在前序步骤完成）：
        - 无 sheet 召回 / NL2SQL 失败 / 任何异常 → 返回空 documents
          answer_generator 基于"无 SQL 结果"信号生成"无法回答"（对应设计文档第 3 点）

        防死循环：本节点被调用即意味着 rerouted_to_sql=False（_route_after_generation 仅在
        rerouted_to_sql=False 时才会路由到此）。本节点返回时统一设置 rerouted_to_sql=True，
        下一轮 answer_generator → _route_after_generation 检测到 rerouted_to_sql=True
        → 直接 END（不再做任何路由决策，无论 answer 是否信息不足）。
        之前 retrieval_agent 检索到的 sheet 摘要 chunk 仍在 documents 中，sql_agent 返回
        的 SQL 结果会追加进去（operator.add），让 answer_generator 看到
        "sheet 摘要 + 真实 SQL 结果" 双重信息生成更好的回答。
        """
        try:
            from src.excel_rag.qa import ExcelQA
            qa = ExcelQA()
            r = qa.retrieve(
                state["query"],
                folder=state.get("folder") or None,
                tags=state.get("tags") or None,
                doc_ids=state.get("doc_ids") or None,
            )

            # 没有任何结构化数据或召回失败 → 返回空 documents，不再 fallback 到 retrieval
            # （统一召回已在前序步骤完成，这里 fallback 没有意义，反而可能造成死循环）
            if r.get("error") in ("no_sheets", "no_relevant_sheet"):
                logger.info("sql_agent no sheet recalled, returning empty: %s", r["error"])
                return {
                    "documents": [],
                    "retrieval_path": "sql_no_sheet",
                    "error": r["error"],
                    "rerouted_to_sql": True,
                    "retrieval_debug": {
                        "sql_fallback_reason": r["error"],
                        "sql_recalled_sheets": r.get("recalled_sheets", []),
                    },
                }

            selected = r["selected_sheet"]
            sheet_meta = selected["sheet_meta"]
            sql = r["sql"]
            sql_result = r["sql_result"] or {}
            recalled = r["recalled_sheets"]
            attempts = r["attempts"]
            err = r["error"]

            # 先注入召回的 sheet 摘要，再注入 SQL 结果 doc
            # 顺序很重要：前端 effectiveDocs 按 chunk_id 去重时先到先得，
            # selected sheet 的 summary（chunk_id=meta_id）先入，
            # SQL 结果 doc（chunk_id=meta_id）后入被去重丢弃，
            # 这样"检索上下文"只显示 sheet 摘要，不显示 SQL 结果提示。
            # 但 sql_agent step 的 chunks 详情用原始 result.documents，仍能渲染 SQL 表格。
            # answer_generator 从 state["documents"]（不去重）仍能看到 SQL 结果 doc。
            existing_meta_ids = {
                d.get("sheet_meta_id") or d.get("chunk_id")
                for d in state.get("documents", [])
                if isinstance(d, dict)
            }
            documents = []
            for sh in recalled:
                meta_id = sh.get("meta_id", "")
                if not meta_id or meta_id in existing_meta_ids:
                    continue
                sm = sh.get("sheet_meta", {}) or {}
                # columns 结构: [{display_name, column_name, data_type}, ...]
                sheet_columns = sm.get("columns", []) or []
                documents.append({
                    "doc_id": sh.get("doc_id", ""),
                    "chunk_id": meta_id,
                    "text": sh.get("summary", ""),
                    "score": sh.get("score", 0.0),
                    "source_type": "sheet_summary",
                    "sheet_meta_id": meta_id,
                    "sheet_name": sh.get("sheet_name", ""),
                    # 结构化字段供前端渲染 Sheet 卡片（行数/列结构）
                    "sheet_row_count": sm.get("row_count", 0),
                    "sheet_columns": sheet_columns,
                    "sql": "",
                    "sql_result_columns": [],
                    "sql_result_rows": [],
                    "sql_result_row_count": 0,
                })

            # 把 SQL 执行结果格式化为一个 document，追加到 documents 末尾
            # chunk_id 与 selected sheet 的 summary 相同（meta_id），前端去重时被丢弃
            # 但 answer_generator 仍能从 state["documents"] 看到 SQL 结果
            documents.append(_format_sql_result_as_document(
                sheet_meta=sheet_meta,
                sql=sql,
                sql_result=sql_result,
                err=err,
                score=selected.get("score", 0.0),
            ))

            return {
                "documents": documents,
                "retrieval_path": "sql_nl2sql",
                "rerouted_to_sql": True,
                "retrieval_debug": {
                    "sql_query": sql,
                    "sql_sheet_meta_id": selected["meta_id"],
                    "sql_sheet_name": sheet_meta["sheet_name"],
                    "sql_recalled_sheets": recalled,
                    "sql_attempts": attempts,
                    "sql_error": err,
                    "sql_result_columns": sql_result.get("columns", []) if isinstance(sql_result, dict) else [],
                    "sql_result_row_count": sql_result.get("row_count", 0) if isinstance(sql_result, dict) else 0,
                    # 暴露前 5 行结果，便于前端 sql_agent step 详情直接渲染数据表
                    "sql_result_rows": (sql_result.get("rows", []) if isinstance(sql_result, dict) else [])[:5],
                },
            }
        except Exception as e:
            logger.error("sql_agent failed: %s", e, exc_info=True)
            # 统一不再 fallback 到 retrieval_agent：召回已在前序步骤完成，
            # 这里返回空 documents 让 answer_generator 生成"无法回答"。
            return {
                "documents": [],
                "retrieval_path": "sql_error",
                "error": str(e),
                "rerouted_to_sql": True,
            }

    def _node_query_router(self, state: AgentState) -> dict:
        result = self.query_router.classify(state["query"])
        # [UNIFIED] 不再基于 force_sql 覆盖 query_type 为 sql_query。
        # query_router 只做语义意图分类（chitchat / simple_fact / multi_hop /
        # comparison / definition），所有非 chitchat 查询统一走向量召回，
        # SQL 由 _route_after_generation 作为条件性 Tool Call 触发。
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
                # documents 用 operator.add 追加（retrieval_agent + sql_agent fallback 都会写入），
                # 同一 chunk_id 可能出现多次。extract_context 内部已去重传给 LLM，
                # citations 必须用同一份去重后的列表，否则 LLM 输出的 [1][2] 引用会指向同一条 chunk，
                # 与 effectiveDocs 长度不匹配，导致前端点击 [2] 时拿不到 doc。
                raw_docs = state["documents"]
                deduped_docs = self.retrieval_agent._dedup_by_chunk_id(raw_docs)
                doc_context = self.retrieval_agent.extract_context(raw_docs)
                context = f"{context}\n\n[Retrieved Documents]\n{doc_context}" if context else doc_context
                citations = [
                    f"[{i + 1}] {d.get('doc_id', '?')}/{d.get('chunk_id', '?')}"
                    for i, d in enumerate(deduped_docs[:10])
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
                    language=settings.response_language,
                )
            else:
                prompt = ANSWER_GENERATION_SYSTEM.format(
                    context=context, question=state["query"],
                    language=settings.response_language,
                )

            # [MERGED] 原 validation_feedback 路径已废弃（validator 节点已合并），
            # 重判场景下 answer_generator 会基于 sql_agent 的 documents 重新生成。
            feedback = state.get("validation_feedback", "")
            if feedback:
                prompt += f"\n\n[Previous answer was rejected. Fix the following issues:]\n{feedback}"

            resp = llm.invoke(prompt)
            answer = resp.content

            # [延迟显示] 检测是否会触发重判到 sql_agent：
            # 条件与 _route_after_generation 完全一致（含 iteration 边界）。
            # 如果会重判，标记 intermediate=True 让前端不渲染这个中间答案，
            # 等待 sql_agent 跑完后下一轮 answer_generator 的最终答案。
            #
            # [BUGFIX] iteration 边界对齐：answer_generator 输入 iteration=N，输出 N+1。
            # _route_after_generation 读取 N+1，检查 N+1 < max_iter。
            # 这里必须用 (N+1) < max_iter 才能与之对齐，否则当 N=max_iter-1 时
            # will_reroute=True（intermediate=True，前端不渲染）但 _route_after_generation
            # 判 END → 前端卡死等待永远不来的最终答案。
            docs = state.get("documents", [])
            next_iteration = state.get("iteration", 0) + 1
            will_reroute = (
                not state.get("rerouted_to_sql", False)
                and _has_excel_sheet_chunk(docs)
                and _answer_indicates_insufficient(answer)
                and next_iteration < state.get("max_iterations", settings.agent_max_iterations)
            )

            # [MERGED] 原 answer_validator 节点的职责合并到此处：
            # - 直接输出 final_answer（不再有 draft_answer → validator 改善 → final_answer 两步）
            # - iteration 递增（兼容死循环防护的路由检查）
            return {
                "draft_answer": answer,
                "final_answer": answer,
                "citations": citations,
                "iteration": state.get("iteration", 0) + 1,
                "intermediate": will_reroute,
            }
        except Exception as e:
            return {
                "draft_answer": f"Answer generation failed: {e}",
                "final_answer": f"Answer generation failed: {e}",
                "error": str(e),
                "iteration": state.get("iteration", 0) + 1,
                "intermediate": False,
            }


_workflow_instance = None


def get_workflow() -> AgenticRAGWorkflow:
    global _workflow_instance
    if _workflow_instance is None:
        _workflow_instance = AgenticRAGWorkflow()
    return _workflow_instance
