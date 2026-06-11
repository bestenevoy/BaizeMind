from fastapi import APIRouter

from api.schemas import SystemStatsResponse
from src.retrieval.vector_retriever import MilvusVectorRetriever
from src.knowledge_graph.neo4j_manager import Neo4jManager
from src.storage import doc_store

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/stats", response_model=SystemStatsResponse)
async def get_stats():
    try:
        vector_retriever = MilvusVectorRetriever()
        vector_count = vector_retriever.count()
    except Exception:
        vector_count = 0

    try:
        neo4j = Neo4jManager()
        neo4j.connect()
        graph_stats = neo4j.get_stats()
    except Exception:
        graph_stats = {"entity_count": 0, "relation_count": 0}

    docs = doc_store.list_documents(limit=10000)
    chunk_count = sum(d.get("chunk_count", 0) for d in docs)

    return SystemStatsResponse(
        document_count=len(docs),
        chunk_count=chunk_count,
        milvus_vector_count=vector_count,
        neo4j_entity_count=graph_stats.get("entity_count", 0),
        neo4j_relation_count=graph_stats.get("relation_count", 0),
    )


@router.post("/rebuild-indices")
async def rebuild_indices():
    return {"status": "rebuild initiated", "message": "Index rebuild not fully implemented"}
