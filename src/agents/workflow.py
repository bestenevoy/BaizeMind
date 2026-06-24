import operator
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import StateGraph, START, END

from src.agents.query_router import QueryRouter
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.graph_agent import GraphAgent
from src.agents.answer_validator import AnswerValidator
from src.retrieval.lightrag_retriever import LightRAGRetriever
from src.llm.deepseek import get_chat_llm
from config.prompts import ANSWER_GENERATION_SYSTEM, QUERY_REWRITE_SYSTEM
from config.settings import settings


def _serialize_debug(debug: dict, dense_query: str) -> dict:
    """Strip large text fields from debug info to keep state lightweight."""
    result = {
        "dense_count": len(debug.get("dense_results", [])),
        "bm25_count": len(debug.get("bm25_results", [])),
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
        "reranked_count": len(debug.get("reranked_filtered", [])),
        "rerank_top3_scores": [
            {
                "chunk_id": r.get("chunk_id", ""),
                "rerank_score": round(r.get("rerank_score", r.get("score", 0)), 4),
                "text_preview": r.get("text", "")[:100],
            }
            for r in debug.get("reranked_filtered", [])[:3]
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


# [DISABLED] GraphRAG pipeline: holistic queries now route to retrieval_agent.
# Original routing: "holistic" → "graphrag_search"
# The graphrag_search node and _route_after_graphrag edge remain in the graph
# for compilation integrity but are unreachable.
def _route_by_query_type(state: AgentState) -> str:
    query_type = state.get("query_type", "simple_fact")
    graph_eligible = state.get("graph_eligible", False)

    if query_type == "chitchat":
        return "chitchat"
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


def _route_after_validation(state: AgentState) -> str:
    validation = state.get("validation", {})
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", settings.agent_max_iterations)

    if not validation.get("is_valid", True) and iteration < max_iter:
        failure_reasons = validation.get("failure_reasons", [])
        if "context_insufficient" in failure_reasons:
            return "retrieval_agent"
        return "answer_generator"
    return END


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

    def _rewrite_query(self, query: str) -> tuple[str, str]:
        """Use LLM to rewrite query for dense (semantic) and BM25 (keyword) search."""
        import json
        try:
            prompt = QUERY_REWRITE_SYSTEM.format(language=settings.query_rewrite_language)
            prompt += f"\n\nUser question: {query}"
            resp = self._get_llm().invoke(prompt)
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("\n```", 1)[0]
            result = json.loads(text)
            dense = result.get("dense_query", query)
            bm25 = result.get("bm25_query", query)
            return dense, bm25
        except Exception:
            return query, query

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
        builder.add_conditional_edges("graph_agent", _route_for_multi_hop)
        # [DISABLED] GraphRAG edge — retained for graph compilation
        builder.add_conditional_edges("graphrag_search", _route_after_graphrag)
        builder.add_edge("retrieval_agent", "answer_generator")
        builder.add_edge("lightrag_agent", "answer_generator")
        builder.add_edge("answer_generator", "answer_validator")
        builder.add_conditional_edges("answer_validator", _route_after_validation)

        return builder.compile()

    def invoke(self, query: str, folder: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
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
        }
        return self._graph.invoke(state)

    async def astream(self, query: str, folder: str | None = None, tags: list[str] | None = None):
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
        }
        async for event in self._graph.astream(state):
            yield event

    def _node_chitchat(self, state: AgentState) -> dict:
        try:
            llm = self._get_llm()
            resp = llm.invoke(state["query"])
            return {"final_answer": resp.content, "draft_answer": resp.content}
        except Exception as e:
            return {"final_answer": f"Chat failed: {e}", "error": str(e)}

    def _node_query_router(self, state: AgentState) -> dict:
        result = self.query_router.classify(state["query"])
        return {
            "query_type": result["query_type"],
            "confidence": result["confidence"],
            "graph_eligible": result.get("graph_eligible", False),
        }

    def _node_retrieval_agent(self, state: AgentState) -> dict:
        try:
            folder = state.get("folder", "") or None
            tags = state.get("tags", []) or None
            doc_ids = None
            if folder or tags:
                from src.storage.doc_store import get_doc_ids_by_filter
                doc_ids = get_doc_ids_by_filter(folder=folder, tags=tags)
                if not doc_ids:
                    return {"documents": [], "error": "No documents match the filter"}

            original_query = state["query"]
            graph_entities = state.get("graph_entities", [])
            sub_queries = state.get("sub_queries", [])

            # Multi-query retrieval: search with each sub-question, merge results
            if sub_queries:
                seen_ids = set()
                all_results = []
                for sq in sub_queries[:3]:
                    dense_q = sq
                    bm25_q = sq
                    if settings.query_rewrite_enabled:
                        dense_q, bm25_q = self._rewrite_query(sq)
                    if graph_entities:
                        bm25_q = f"{bm25_q} {' '.join(graph_entities[:10])}"
                    results = self.retrieval_agent.search(
                        sq, doc_ids=doc_ids,
                        dense_query=dense_q, bm25_query=bm25_q,
                    )
                    for r in results:
                        cid = r.get("chunk_id", "")
                        if cid and cid not in seen_ids:
                            seen_ids.add(cid)
                            all_results.append(r)
                return {"documents": all_results[:20], "retrieval_path": f"[Multi-query] {len(sub_queries)} sub-queries → {len(all_results)} chunks"}

            # Single query: rewrite for dense (semantic) and BM25 (keyword)
            original_query = state["query"]
            dense_query = original_query
            bm25_query = original_query
            if settings.query_rewrite_enabled:
                dense_query, bm25_query = self._rewrite_query(original_query)
            if graph_entities:
                bm25_query = f"{bm25_query} {' '.join(graph_entities[:10])}"

            results, debug = self.retrieval_agent._retriever.retrieve(
                original_query,
                top_k=20, doc_ids=doc_ids,
                dense_query=dense_query, bm25_query=bm25_query,
            )
            results = self.retrieval_agent._dedup_by_chunk_id(results)
            return {
                "documents": results,
                "retrieval_path": "[Retrieval] hybrid (dense + BM25)",
                "retrieval_debug": _serialize_debug(debug, dense_query),
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
            retrieval_path = state.get("retrieval_path", "")
            if retrieval_path:
                context = f"[Retrieval: {retrieval_path}]\n\n{context}"

            llm = self._get_llm()
            # Truncate context at document boundary (on "\n\n---\n\n") to avoid
            # cutting in the middle of a chunk. Budget: 8000 chars.
            max_ctx = 8000
            if len(context) > max_ctx:
                cut = context.rfind("\n\n---\n\n", 0, max_ctx)
                context = context[:cut] if cut > 0 else context[:max_ctx]
            prompt = ANSWER_GENERATION_SYSTEM.format(
                context=context, question=state["query"]
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
