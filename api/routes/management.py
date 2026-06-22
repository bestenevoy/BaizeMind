import time
import os

from fastapi import APIRouter

from api.schemas import SystemStatsResponse, ConnectivityResult, GraphOverviewResponse, GraphNode, GraphEdge
from config.settings import settings
from src.retrieval.vector_retriever import MilvusVectorRetriever
from src.knowledge_graph.neo4j_manager import Neo4jManager
from src.storage import doc_store, config_overrides
from pydantic import BaseModel

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
        ("retrieval_similarity_threshold", "相似度阈值"),
        ("reranker_method", "重排序方式"),
    ]),
    ("重排序模型", [
        ("siliconflow_rerank_model", "重排模型"),
        ("siliconflow_rerank_url", "重排 API"),
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
            if key == "reranker_method":
                val = {"embedding": "硅基流动 Cross-Encoder", "llm": "LLM 排序", "hybrid": "混合 (Cross-Encoder + LLM)"}.get(str(val), str(val))
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


@router.post("/cleanup-orphans")
async def cleanup_orphans():
    """Remove vectors and entities that have no corresponding document in doc_store."""
    result = {"milvus_deleted": 0, "neo4j_deleted_entities": 0}
    try:
        doc_ids = set(d["doc_id"] for d in doc_store.list_documents(limit=10000))
    except Exception as e:
        return {"error": f"Failed to list documents: {e}", "milvus_deleted": 0, "neo4j_deleted_entities": 0}

    # Clean orphan Milvus vectors
    try:
        from src.retrieval.vector_retriever import MilvusVectorRetriever
        vr = MilvusVectorRetriever()
        vr.ensure_collection()
        all_chunks = vr.fetch_all_chunks()
        orphans = [c for c in all_chunks if c.get("doc_id", "") not in doc_ids]
        for c in orphans:
            try:
                vr._client.delete(vr.collection_name, f'id == "{c["id"]}"')
                result["milvus_deleted"] += 1
            except Exception:
                pass
    except Exception as e:
        result["milvus_error"] = str(e)

    # Clean orphan Neo4j entities
    try:
        from src.knowledge_graph.neo4j_manager import Neo4jManager
        neo4j = Neo4jManager()
        neo4j.connect()
        id_list = list(doc_ids) if doc_ids else [""]
        with neo4j._driver.session() as session:
            res = session.run(
                """
                MATCH (n:Entity)
                WHERE n.doc_id IS NULL OR NOT n.doc_id IN $doc_ids
                DETACH DELETE n
                RETURN count(n) as cnt
                """,
                doc_ids=id_list,
            ).single()
            result["neo4j_deleted_entities"] = res["cnt"] if res else 0
    except Exception as e:
        result["neo4j_error"] = str(e)

    return result


@router.get("/graph/overview", response_model=GraphOverviewResponse)
async def get_graph_overview(doc_id: str = ""):
    neo4j = Neo4jManager()
    neo4j.connect()

    if doc_id:
        result = neo4j.query(
            """
            MATCH (n:Entity {doc_id: $doc_id})-[r:RELATES_TO]-(m:Entity {doc_id: $doc_id})
            RETURN n, r, m
            """,
            {"doc_id": doc_id},
        )
    else:
        result = neo4j.query(
            "MATCH (n:Entity)-[r:RELATES_TO]->(m:Entity) RETURN n, r, m LIMIT 500"
        )

    nodes_map: dict[str, GraphNode] = {}
    edges_seen: set[str] = set()
    edges: list[GraphEdge] = []

    for row in result:
        n = row["n"]
        m = row["m"]
        r = row["r"]

        for entity in (n, m):
            node_id = entity.get("name", "")
            if node_id and node_id not in nodes_map:
                nodes_map[node_id] = GraphNode(
                    id=node_id,
                    label=node_id,
                    type=entity.get("type", ""),
                    doc_id=entity.get("doc_id", ""),
                    description=entity.get("description", ""),
                )

        rel_type = r.get("type", "")
        source = n.get("name", "")
        target = m.get("name", "")
        edge_key = f"{source}|{rel_type}|{target}"
        if source and target and edge_key not in edges_seen:
            edges_seen.add(edge_key)
            edges.append(GraphEdge(source=source, target=target, type=rel_type))

    return GraphOverviewResponse(
        nodes=list(nodes_map.values()),
        edges=edges,
        total_nodes=len(nodes_map),
        total_edges=len(edges),
    )


# ── Runtime Config Overrides ──

class ConfigOverrideBody(BaseModel):
    key: str
    value: str


@router.get("/config/editable")
async def list_editable_config():
    return config_overrides.list_editable_config()


@router.put("/config/editable")
async def update_config_override(body: ConfigOverrideBody):
    try:
        # Coerce value type based on key
        current = getattr(settings, body.key, "")
        if isinstance(current, bool):
            val = body.value.lower() in ("true", "1", "yes", "是")
        elif isinstance(current, float):
            val = float(body.value)
        elif isinstance(current, int):
            val = int(body.value)
        else:
            val = body.value

        ok = config_overrides.set_override(body.key, val)
        if not ok:
            return {"error": f"Key '{body.key}' is not editable"}
        return {"key": body.key, "value": val, "saved": True}
    except (ValueError, TypeError) as e:
        return {"error": f"Invalid value for '{body.key}': {e}"}


@router.delete("/config/editable/{key}")
async def reset_config_override(key: str):
    overrides = config_overrides.load_overrides()
    if key in overrides:
        del overrides[key]
        config_overrides.save_overrides(overrides)
        # Restore original value from settings/env
        setattr(settings, key, getattr(type(settings)(), key, ""))
        return {"key": key, "reset": True}
    return {"key": key, "reset": False, "message": "No override found"}
