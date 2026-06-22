import operator
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import StateGraph, START, END

from src.agents.query_router import QueryRouter
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.graph_agent import GraphAgent
from src.agents.answer_validator import AnswerValidator
from src.llm.deepseek import get_chat_llm
from config.prompts import ANSWER_GENERATION_SYSTEM
from config.settings import settings


class AgentState(TypedDict):
    query: str
    query_type: str
    confidence: float
    documents: Annotated[list[dict], operator.add]
    graph_context: str
    graph_entities: list[str]
    graphrag_context: str
    draft_answer: str
    final_answer: str
    citations: list[str]
    validation: dict
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
    if query_type == "chitchat":
        return "chitchat"
    if query_type == "holistic":
        return "retrieval_agent"  # DISABLED: was "graphrag_search"
    if query_type in ("multi_hop", "comparison"):
        return "graph_agent"
    return "retrieval_agent"


def _route_for_multi_hop(state: AgentState) -> str:
    query_type = state.get("query_type", "simple_fact")
    if query_type == "multi_hop":
        return "retrieval_agent"
    elif query_type == "comparison":
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
        return "retrieval_agent"
    return END


class AgenticRAGWorkflow:
    def __init__(self):
        self.query_router = QueryRouter()
        self.retrieval_agent = RetrievalAgent()
        self.graph_agent = GraphAgent()
        self.answer_validator = AnswerValidator()
        self._llm = None
        self._graphrag_query = None
        self._graph = self._build_graph()

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm()
        return self._llm

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
        builder.add_edge("answer_generator", "answer_validator")
        builder.add_conditional_edges("answer_validator", _route_after_validation)

        return builder.compile()

    def invoke(self, query: str, folder: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        state: AgentState = {
            "query": query,
            "query_type": "simple_fact",
            "confidence": 0.0,
            "documents": [],
            "graph_context": "",
            "graphrag_context": "",
            "draft_answer": "",
            "final_answer": "",
            "citations": [],
            "validation": {},
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
            "documents": [],
            "graph_context": "",
            "graphrag_context": "",
            "draft_answer": "",
            "final_answer": "",
            "citations": [],
            "validation": {},
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
        }

    def _node_retrieval_agent(self, state: AgentState) -> dict:
        try:
            folder = state.get("folder", "") or None
            tags = state.get("tags", []) or None
            doc_filter = None
            if folder or tags:
                from src.storage.doc_store import get_doc_ids_by_filter
                ids = get_doc_ids_by_filter(folder=folder, tags=tags)
                if not ids:
                    return {"documents": [], "error": "No documents match the filter"}
                doc_filter = ids

            query = state["query"]
            graph_entities = state.get("graph_entities", [])
            if graph_entities:
                entity_suffix = " ".join(graph_entities[:10])
                query = f"{query} {entity_suffix}"

            results = self.retrieval_agent.search(query, doc_ids=doc_filter)
            return {"documents": results}
        except Exception as e:
            return {"error": f"Retrieval failed: {e}"}

    def _node_graph_agent(self, state: AgentState) -> dict:
        try:
            entities = self.graph_agent.extract_entities_from_query(state["query"])
            if entities:
                paths = self.graph_agent.expand(entities)
                graph_context = self.graph_agent.format_context(paths)

                graph_entities = list(entities)
                for p in paths:
                    for key in ("subject_name", "object_name"):
                        name = p.get(key, "")
                        if name and name not in graph_entities:
                            graph_entities.append(name)
            else:
                graph_context = "No entities found for graph expansion."
                graph_entities = []
            return {"graph_context": graph_context, "graph_entities": graph_entities}
        except Exception as e:
            return {"graph_context": f"Graph query failed: {e}", "graph_entities": [], "error": str(e)}

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
                    f"{d.get('doc_id', '?')}_{d.get('chunk_id', '?')}"
                    for d in state["documents"][:10]
                ]

            if state.get("graph_context"):
                context = f"[Knowledge Graph Context]\n{state['graph_context']}\n\n{context}"

            if not context.strip():
                return {
                    "draft_answer": "I cannot find sufficient context to answer this question.",
                    "citations": [],
                }

            llm = self._get_llm()
            prompt = ANSWER_GENERATION_SYSTEM.format(
                context=context[:8000], question=state["query"]
            )
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
                context = "\n".join(d.get("text", "")[:500] for d in state["documents"][:5])

            validation = self.answer_validator.validate(
                question=state["query"],
                answer=state.get("draft_answer", ""),
                context=context,
                citations=state.get("citations", []),
            )

            new_iteration = state.get("iteration", 0) + 1
            final_answer = validation.get("improved_answer") or state.get("draft_answer", "")

            return {
                "validation": validation,
                "final_answer": final_answer,
                "iteration": new_iteration,
            }
        except Exception as e:
            return {
                "validation": {"is_valid": True},
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
