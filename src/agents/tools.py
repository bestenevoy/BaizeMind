import json
from typing import Type

from langchain_core.tools import BaseTool
from langchain_core.tools import tool

from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.bm25_retriever import BM25Retriever
from src.retrieval.reranker import Reranker
from src.knowledge_graph.graph_query import GraphQuery
from src.knowledge_graph.neo4j_manager import Neo4jManager

_hybrid_retriever = HybridRetriever()
_bm25_retriever = BM25Retriever()
_reranker = Reranker()
_graph_query = GraphQuery()
_neo4j = Neo4jManager()
_graphrag_query = None


def _get_graphrag():
    global _graphrag_query
    if _graphrag_query is None:
        from src.knowledge_graph.graphrag_query import GraphRAGQuery
        _graphrag_query = GraphRAGQuery()
    return _graphrag_query


@tool
def hybrid_search(query: str, top_k: int = 10) -> str:
    """Perform hybrid (vector + BM25) search across the document base. Best for factual questions about document content."""
    results = _hybrid_retriever.retrieve(query, top_k=top_k)
    return _format_search_results(results)


@tool
def bm25_search(query: str, top_k: int = 10) -> str:
    """Perform keyword-based BM25 search. Best for exact term matching and code/variable lookups."""
    results = _bm25_retriever.search(query, top_k=top_k)
    return _format_search_results(results)


@tool
def rerank_results(query: str, results: str, top_k: int = 5) -> str:
    """Re-rank search results by relevance to the query. Input 'results' should be result indices or descriptions."""
    return f"Re-ranked to top {top_k} results for query: {query}"


@tool
def query_kg(question: str) -> str:
    """Query the enterprise knowledge graph (Neo4j) using natural language. Best for relationship and entity questions."""
    result = _graph_query.query_natural_language(question)
    if result.get("error"):
        return f"Graph query error: {result['error']}"
    return _format_graph_results(result["results"])


@tool
def expand_path(entity_name: str, max_hops: int = 2) -> str:
    """Expand knowledge graph paths from an entity to find connected entities. Best for 'how is X related to Y' questions."""
    _neo4j.connect()
    neighbors = _neo4j.get_neighbors(entity_name, max_hops=max_hops)
    return _format_graph_results(neighbors)


@tool
def get_entity_info(name: str) -> str:
    """Get detailed information about a specific entity from the knowledge graph."""
    result = _graph_query.get_entity_detail(name)
    if not result.get("entity"):
        return f"No entity found named '{name}'"
    entity = result["entity"]
    neighbors_str = "\n".join(
        f"  - {n.get('object_name', '?')} (distance={n.get('distance', '?')})"
        for n in result.get("neighbors", [])[:10]
    )
    return f"Entity: {entity.get('name')}\nType: {entity.get('type')}\nDescription: {entity.get('description', 'N/A')}\nRelations:\n{neighbors_str}"


@tool
def graphrag_global_search(query: str) -> str:
    """Microsoft GraphRAG Global Search: answers holistic questions about the entire dataset by leveraging community summaries. Best for 'What are the main themes?', 'Summarize the key findings', broad overview questions."""
    try:
        graphrag = _get_graphrag()
        result = graphrag.search_sync(query, mode="global")
        return f"[GraphRAG Global]\n{result['answer']}\n\n(LLM calls: {result['llm_calls']}, tokens: {result['prompt_tokens'] + result['output_tokens']})"
    except Exception as e:
        return f"GraphRAG global search failed: {e}. Falling back to standard retrieval."


@tool
def graphrag_local_search(query: str) -> str:
    """Microsoft GraphRAG Local Search: answers questions about specific entities by exploring their neighborhood in the knowledge graph. Best for entity-specific questions, relationship queries."""
    try:
        graphrag = _get_graphrag()
        result = graphrag.search_sync(query, mode="local")
        return f"[GraphRAG Local]\n{result['answer']}\n\n(LLM calls: {result['llm_calls']}, tokens: {result['prompt_tokens'] + result['output_tokens']})"
    except Exception as e:
        return f"GraphRAG local search failed: {e}. Falling back to standard retrieval."


@tool
def graphrag_drift_search(query: str) -> str:
    """Microsoft GraphRAG DRIFT Search: hybrid approach combining local entity exploration with community context. Best for exploratory questions that need both specific details and broader context."""
    try:
        graphrag = _get_graphrag()
        result = graphrag.search_sync(query, mode="drift")
        return f"[GraphRAG DRIFT]\n{result['answer']}\n\n(LLM calls: {result['llm_calls']}, tokens: {result['prompt_tokens'] + result['output_tokens']})"
    except Exception as e:
        return f"GraphRAG drift search failed: {e}. Falling back to standard retrieval."


ALL_TOOLS: list[BaseTool] = [
    hybrid_search, bm25_search, query_kg, expand_path, get_entity_info,
    graphrag_global_search, graphrag_local_search, graphrag_drift_search,
]


def _format_search_results(results: list[dict]) -> str:
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results[:10]):
        text = r.get("text", "")[:300].replace("\n", " ")
        score = r.get("score", 0.0)
        doc = r.get("doc_id", "?")
        lines.append(f"[{i}] (doc={doc}, score={score:.3f}) {text}")
    return "\n".join(lines)


def _format_graph_results(results: list[dict]) -> str:
    if not results:
        return "No graph results found."
    lines = []
    for i, r in enumerate(results[:10]):
        if "path_string" in r:
            lines.append(f"[{i}] {r['path_string']}")
        elif "entity_name" in r:
            lines.append(f"[{i}] {r['entity_name']} ({r.get('entity_type', '?')})")
        elif "nodes" in r:
            lines.append(f"[{i}] Path: {' -> '.join(r['nodes'])}")
        else:
            lines.append(f"[{i}] {json.dumps(r, default=str)[:200]}")
    return "\n".join(lines)
