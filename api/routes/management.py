import time
import os

from fastapi import APIRouter

from api.schemas import SystemStatsResponse, ConnectivityResult
from config.settings import settings
from src.retrieval.vector_retriever import MilvusVectorRetriever
from src.knowledge_graph.neo4j_manager import Neo4jManager
from src.storage import doc_store

router = APIRouter(prefix="/api/v1/system", tags=["system"])

SETTING_CATEGORIES = [
    ("DeepSeek", [
        ("deepseek_chat_model", "Chat 模型"),
        ("deepseek_reasoner_model", "推理模型"),
        ("deepseek_base_url", "API 地址"),
    ]),
    ("BGE-M3 向量化", [
        ("bge_m3_use_local", "使用本地模型"),
        ("bge_m3_model_path", "模型路径"),
        ("bge_m3_device", "运行设备"),
        ("bge_m3_batch_size", "批次大小"),
        ("bge_m3_max_length", "最大长度"),
    ]),
    ("SiliconFlow 云端向量化", [
        ("siliconflow_embedding_url", "API 地址"),
        ("siliconflow_embedding_model", "模型名称"),
    ]),
    ("Milvus 向量数据库", [
        ("milvus_host", "主机地址"),
        ("milvus_port", "端口"),
        ("milvus_collection", "集合名称"),
    ]),
    ("Neo4j 图数据库", [
        ("neo4j_uri", "连接地址"),
        ("neo4j_user", "用户名"),
    ]),
    ("GraphRAG", [
        ("graphrag_root_dir", "数据目录"),
        ("graphrag_community_level", "社区层级"),
    ]),
    ("MinerU 文档解析", [
        ("mineru_model_source", "模型来源"),
        ("mineru_output_dir", "输出目录"),
    ]),
    ("PaddleOCR-VL", [
        ("paddleocr_vl_model_dir", "模型目录"),
        ("layout_detection_model_dir", "版面检测模型"),
        ("cuda_visible_devices", "CUDA 设备"),
    ]),
    ("分块参数", [
        ("chunk_size", "块大小"),
        ("chunk_overlap", "重叠大小"),
    ]),
    ("检索参数", [
        ("hybrid_top_k", "检索数量"),
        ("hybrid_dense_weight", "稠密向量权重"),
        ("hybrid_sparse_weight", "稀疏向量权重"),
        ("hybrid_bm25_weight", "BM25 权重"),
        ("hybrid_rrf_k", "RRF 参数 k"),
    ]),
    ("Agent 智能体", [
        ("agent_max_iterations", "最大迭代次数"),
        ("agent_temperature", "温度"),
    ]),
    ("服务器", [
        ("server_host", "绑定地址"),
        ("server_port", "端口"),
        ("server_workers", "工作进程数"),
    ]),
]


def _mask_secret(value: str) -> str:
    """Mask API key showing only first 3 and last 4 chars."""
    if not value:
        return ""
    if len(value) <= 10:
        return "***"
    return value[:3] + "****" + value[-4:]


@router.get("/config")
async def get_config():
    categories = []
    for cat_name, fields in SETTING_CATEGORIES:
        items = []
        for key, label in fields:
            val = getattr(settings, key, "")
            if key in ("neo4j_password",):
                continue  # never send passwords
            if "key" in key and val:
                val = _mask_secret(str(val))
            items.append({"key": key, "label": label, "value": str(val)})
        categories.append({"category": cat_name, "items": items})

    deepseek_key = _mask_secret(settings.deepseek_api_key) if settings.deepseek_api_key else ""
    silicon_key = _mask_secret(settings.siliconflow_api_key) if settings.siliconflow_api_key else ""

    return {
        "categories": categories,
        "secrets": {
            "deepseek_api_key": deepseek_key,
            "siliconflow_api_key": silicon_key,
        },
    }


@router.get("/connectivity-check", response_model=list[ConnectivityResult])
async def connectivity_check():
    results = []

    # Milvus
    t0 = time.time()
    try:
        v = MilvusVectorRetriever()
        cnt = v.count()
        results.append(ConnectivityResult(
            service="Milvus", status="ok",
            detail=f"连接正常，向量数: {cnt}", latency_ms=round((time.time() - t0) * 1000),
        ).model_dump())
    except Exception as e:
        results.append(ConnectivityResult(
            service="Milvus", status="error",
            detail=str(e), latency_ms=round((time.time() - t0) * 1000),
        ).model_dump())

    # Neo4j
    t0 = time.time()
    try:
        neo = Neo4jManager()
        neo.connect()
        stats = neo.get_stats()
        results.append(ConnectivityResult(
            service="Neo4j", status="ok",
            detail=f"连接正常，实体: {stats.get('entity_count', 0)}，关系: {stats.get('relation_count', 0)}",
            latency_ms=round((time.time() - t0) * 1000),
        ).model_dump())
    except Exception as e:
        results.append(ConnectivityResult(
            service="Neo4j", status="error",
            detail=str(e), latency_ms=round((time.time() - t0) * 1000),
        ).model_dump())

    # DeepSeek API
    t0 = time.time()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.deepseek_base_url}/v1/models",
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            )
            if resp.status_code == 200:
                results.append(ConnectivityResult(
                    service="DeepSeek API", status="ok",
                    detail="API 连通正常", latency_ms=round((time.time() - t0) * 1000),
                ).model_dump())
            else:
                results.append(ConnectivityResult(
                    service="DeepSeek API", status="error",
                    detail=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    latency_ms=round((time.time() - t0) * 1000),
                ).model_dump())
    except Exception as e:
        results.append(ConnectivityResult(
            service="DeepSeek API", status="error",
            detail=str(e), latency_ms=round((time.time() - t0) * 1000),
        ).model_dump())

    # SiliconFlow API
    t0 = time.time()
    if settings.siliconflow_api_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    settings.siliconflow_embedding_url,
                    headers={"Authorization": f"Bearer {settings.siliconflow_api_key}"},
                    json={"model": settings.siliconflow_embedding_model, "input": "test"},
                )
                if resp.status_code == 200:
                    results.append(ConnectivityResult(
                        service="SiliconFlow API", status="ok",
                        detail="API 连通正常", latency_ms=round((time.time() - t0) * 1000),
                    ).model_dump())
                else:
                    results.append(ConnectivityResult(
                        service="SiliconFlow API", status="error",
                        detail=f"HTTP {resp.status_code}: {resp.text[:200]}",
                        latency_ms=round((time.time() - t0) * 1000),
                    ).model_dump())
        except Exception as e:
            results.append(ConnectivityResult(
                service="SiliconFlow API", status="error",
                detail=str(e), latency_ms=round((time.time() - t0) * 1000),
            ).model_dump())
    else:
        results.append(ConnectivityResult(
            service="SiliconFlow API", status="warning",
            detail="未配置 API Key", latency_ms=0,
        ).model_dump())

    # MinerU CLI
    t0 = time.time()
    try:
        venv_bin = os.path.dirname(os.path.abspath(os.sys.executable))
        mineru_path = os.path.join(venv_bin, "mineru")
        if not os.path.exists(mineru_path):
            # try system PATH
            import shutil
            mineru_path = shutil.which("mineru") or mineru_path
        if os.path.exists(mineru_path):
            results.append(ConnectivityResult(
                service="MinerU CLI", status="ok",
                detail=f"找到: {mineru_path}", latency_ms=round((time.time() - t0) * 1000),
            ).model_dump())
        else:
            results.append(ConnectivityResult(
                service="MinerU CLI", status="warning",
                detail=f"未找到 mineru 命令", latency_ms=round((time.time() - t0) * 1000),
            ).model_dump())
    except Exception as e:
        results.append(ConnectivityResult(
            service="MinerU CLI", status="error",
            detail=str(e), latency_ms=round((time.time() - t0) * 1000),
        ).model_dump())

    return results


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
    from src.retrieval.bm25_retriever import BM25Retriever
    bm25 = BM25Retriever()
    success = bm25.rebuild_from_milvus()
    if success:
        return {"status": "completed", "message": "BM25 index rebuilt from Milvus", "chunks_indexed": len(bm25._chunks)}
    return {"status": "skipped", "message": "No chunks found in Milvus to rebuild"}
