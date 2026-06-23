import time
import os
import logging

from fastapi import APIRouter

from api.schemas import SystemStatsResponse, ConnectivityResult, GraphOverviewResponse, GraphNode, GraphEdge, EntityDetailResponse, ChunkInfo
from config.settings import settings
from src.retrieval.vector_retriever import MilvusVectorRetriever
from src.retrieval.bm25_retriever import BM25Retriever
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.reranker import Reranker
from src.embeddings.bge_m3 import BGEM3Embedding
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
            MATCH (s:Entity)-[:SUBJECT_OF]->(f:Fact)-[:OBJECT_OF]->(o:Entity)
            WHERE (s)-[:SUBJECT_OF]->(f) AND (f)-[:OBJECT_OF]->(o)
            RETURN s, f, o
            LIMIT 500
            """,
        )
    else:
        result = neo4j.query(
            """
            MATCH (s:Entity)-[:SUBJECT_OF]->(f:Fact)-[:OBJECT_OF]->(o:Entity)
            WHERE s.active = true AND f.active = true AND o.active = true
            RETURN s, f, o
            LIMIT 500
            """
        )

    nodes_map: dict[str, GraphNode] = {}
    edges_seen: set[str] = set()
    edges: list[GraphEdge] = []

    for row in result:
        s = row["s"]
        o = row["o"]
        f = row["f"]

        for entity in (s, o):
            node_id = entity.get("name", "") or entity.get("entity_key", "")
            if node_id and node_id not in nodes_map:
                nodes_map[node_id] = GraphNode(
                    id=node_id,
                    label=entity.get("name", node_id),
                    type=entity.get("type", ""),
                    doc_id=entity.get("doc_id", ""),
                    description=entity.get("description", ""),
                )

        predicate = f.get("predicate", "")
        source = s.get("name", "") or s.get("entity_key", "")
        target = o.get("name", "") or o.get("entity_key", "")
        edge_key = f"{source}|{predicate}|{target}"
        if source and target and predicate and edge_key not in edges_seen:
            edges_seen.add(edge_key)
            edges.append(GraphEdge(source=source, target=target, type=predicate))

    return GraphOverviewResponse(
        nodes=list(nodes_map.values()),
        edges=edges,
        total_nodes=len(nodes_map),
        total_edges=len(edges),
    )


@router.get("/graph/entity/{entity_name:path}", response_model=EntityDetailResponse)
async def get_graph_entity_detail(entity_name: str):
    neo4j = Neo4jManager()
    neo4j.connect()

    entity_row = neo4j.query(
        "MATCH (n:Entity {name: $name}) RETURN n LIMIT 1",
        {"name": entity_name},
    )
    if not entity_row:
        return EntityDetailResponse(name=entity_name, type="", description="", doc_id="")

    entity = entity_row[0]["n"]
    doc_id = entity.get("doc_id", "")

    documents = []
    related_doc_ids: set[str] = set()
    chunks: list[ChunkInfo] = []

    # Get doc info from SQLite
    if doc_id:
        doc = doc_store.get_document(doc_id)
        if doc:
            documents.append(dict(doc))
            related_doc_ids.add(doc_id)

    # Get chunks from Milvus containing the entity name
    try:
        vr = MilvusVectorRetriever()
        vr.ensure_collection()
        all_related = vr._client.query(
            collection_name=vr.collection_name,
            filter=f'text like "%{entity_name}%"',
            output_fields=["id", "doc_id", "chunk_id", "text", "metadata"],
            limit=10,
        )
        for c in all_related:
            c_doc_id = c.get("doc_id", "")
            if c_doc_id and c_doc_id not in related_doc_ids:
                related_doc_ids.add(c_doc_id)
                d = doc_store.get_document(c_doc_id)
                if d:
                    documents.append(dict(d))
            meta = c.get("metadata", {})
            chunks.append(ChunkInfo(
                chunk_id=c.get("chunk_id", ""),
                text=c.get("text", ""),
                heading=meta.get("heading", "") if isinstance(meta, dict) else "",
                metadata=meta if isinstance(meta, dict) else {},
            ))
    except Exception:
        pass

    return EntityDetailResponse(
        name=entity_name,
        type=entity.get("type", ""),
        description=entity.get("description", ""),
        doc_id=doc_id,
        documents=documents,
        related_chunks=chunks,
    )


# ── Search Debug ──

logger = logging.getLogger(__name__)


class SearchDebugRequest(BaseModel):
    query: str
    folder: str | None = None
    tags: list[str] | None = None
    top_k: int = 20


@router.post("/search")
async def search_debug(body: SearchDebugRequest):
    query = body.query
    current_threshold = settings.retrieval_similarity_threshold

    doc_filter = None
    if body.folder or body.tags:
        ids = doc_store.get_doc_ids_by_filter(folder=body.folder or None, tags=body.tags or None)
        if not ids:
            return {"query": query, "threshold": current_threshold, "stages": {}, "filtered_count": 0, "message": "No documents match the folder/tag filter"}
        id_list = " ".join(f'"{d}"' for d in ids)
        doc_filter = f"doc_id in [{id_list}]"

    embedding = BGEM3Embedding()
    vector_retriever = MilvusVectorRetriever()
    bm25_retriever = BM25Retriever()
    bm25_retriever.load()
    if bm25_retriever._model is None:
        bm25_retriever.rebuild_from_milvus()
    reranker = Reranker()

    k = settings.hybrid_rrf_k
    dense_weight = settings.hybrid_dense_weight
    bm25_weight = settings.hybrid_bm25_weight

    # Stage 1: Dense search
    query_vec = embedding.encode_query_dense(query)
    expr = f'doc_id == "{doc_filter}"' if doc_filter else None
    dense_results = vector_retriever.search(query_vec, top_k=body.top_k, expr=expr)

    # Stage 2: BM25 search
    bm25_results = bm25_retriever.search(query, top_k=body.top_k)

    # Stage 3: RRF fusion (before threshold)
    scores_raw: dict[str, tuple[dict, float]] = {}
    scores_dense: dict[str, float] = {}
    scores_bm25: dict[str, float] = {}
    for rank, doc in enumerate(dense_results):
        cid = doc.get("chunk_id", "")
        scores_raw[cid] = (doc, scores_raw.get(cid, (doc, 0.0))[1] + dense_weight / (k + rank + 1))
        scores_dense[cid] = doc.get("score", 0)
    for rank, doc in enumerate(bm25_results):
        cid = doc.get("chunk_id", "")
        scores_raw[cid] = (doc, scores_raw.get(cid, (doc, 0.0))[1] + bm25_weight / (k + rank + 1))
        scores_bm25[cid] = doc.get("score", 0)

    ranked_rrf = sorted(scores_raw.items(), key=lambda x: x[1][1], reverse=True)
    max_rrf = ranked_rrf[0][1][1] if ranked_rrf else 1.0

    # RRF results with pass/fail for threshold
    rrf_debug = []
    for cid, (doc, raw_score) in ranked_rrf:
        normalized = raw_score / max_rrf if max_rrf > 0 else 0
        rrf_debug.append({
            "chunk_id": cid,
            "doc_id": doc.get("doc_id", ""),
            "text_preview": doc.get("text", "")[:200],
            "rrf_raw": round(raw_score, 8),
            "rrf_normalized": round(normalized, 4),
            "rrf_pass_threshold": current_threshold == 0 or normalized >= current_threshold,
            "dense_score": round(scores_dense.get(cid, 0), 6),
            "bm25_score": round(scores_bm25.get(cid, 0), 6),
        })

    # Stage 4: Reranker
    rrf_passed = [doc for cid, (doc, _) in ranked_rrf
                  if current_threshold == 0 or (max_rrf > 0 and (_ / max_rrf) >= current_threshold)]
    all_for_rerank = rrf_passed[:body.top_k] if rrf_passed else [doc for _, (doc, _) in ranked_rrf[:body.top_k]]
    reranked = reranker.rerank(query, all_for_rerank, top_k=min(10, len(all_for_rerank)))

    rerank_debug = []
    for r in reranked:
        rs = r.get("rerank_score", r.get("score", 0))
        rerank_debug.append({
            "chunk_id": r.get("chunk_id", ""),
            "doc_id": r.get("doc_id", ""),
            "text_preview": r.get("text", "")[:200],
            "rerank_score": round(rs, 4) if isinstance(rs, (int, float)) else 0,
            "rerank_pass_threshold": current_threshold == 0 or (isinstance(rs, (int, float)) and rs >= current_threshold),
        })

    # Build filename cache
    doc_name_cache: dict[str, str] = {}
    for item in rrf_debug + rerank_debug:
        did = item.get("doc_id", "")
        if did and did not in doc_name_cache:
            d = doc_store.get_document(did)
            doc_name_cache[did] = d["filename"] if d else did

    for item in rrf_debug + rerank_debug:
        item["filename"] = doc_name_cache.get(item.get("doc_id", ""), "")

    # Final filtered view
    final = [r for r in rerank_debug if r["rerank_pass_threshold"]]
    filter_drop = len(rerank_debug) - len(final)

    return {
        "query": query,
        "threshold": current_threshold,
        "stages": {
            "dense_top5": [{
                "chunk_id": d.get("chunk_id", ""),
                "doc_id": d.get("doc_id", ""),
                "filename": doc_name_cache.get(d.get("doc_id", ""), ""),
                "text_preview": d.get("text", "")[:150],
                "score": round(d.get("score", 0), 4),
            } for d in dense_results[:5]],
            "bm25_top5": [{
                "chunk_id": d.get("chunk_id", ""),
                "doc_id": d.get("doc_id", ""),
                "filename": doc_name_cache.get(d.get("doc_id", ""), ""),
                "text_preview": d.get("text", "")[:150],
                "score": round(d.get("score", 0), 4),
            } for d in bm25_results[:5]],
            "rrf": rrf_debug[:20],
            "rerank": rerank_debug,
        },
        "final_count": len(final),
        "filtered_out_by_rerank_threshold": filter_drop,
    }


# ── Build Graph ──


@router.post("/build-graph")
async def build_graph():
    try:
        from src.retrieval.bm25_retriever import BM25Retriever
        from src.knowledge_graph.entity_extractor import EntityExtractor
        from src.knowledge_graph.chunk_manager import compute_chunk_hash, create_or_reuse_chunk, build_sync_tasks
        from src.knowledge_graph.evidence_writer import write_evidence
        from src.knowledge_graph.graph_sync_worker import process_pending_tasks
        from config.settings import settings
        from src.storage import doc_store

        bm25 = BM25Retriever()
        bm25.load()
        if bm25._model is None:
            bm25.rebuild_from_milvus()
        chunks = bm25._chunks
        if not chunks:
            return {"success": False, "message": "No chunks found. Please ingest documents first."}

        logger.info(f"Building knowledge graph for {len(chunks)} chunks...")

        extractor = EntityExtractor()
        all_affected_keys: dict[str, set[str]] = {}
        evidence_count = 0
        errors = 0

        for i, chunk in enumerate(chunks):
            try:
                ch = compute_chunk_hash(chunk["text"])
                create_or_reuse_chunk(chunk["text"])
                items = extractor.extract_evidence(chunk["text"], chunk_hash=ch)
                if items:
                    result = write_evidence(ch, items)
                    evidence_count += result["count"]
                    for t, keys in result.get("affected_keys", {}).items():
                        if t not in all_affected_keys:
                            all_affected_keys[t] = set()
                        all_affected_keys[t].update(keys)
            except Exception as e:
                errors += 1
                logger.warning(f"Evidence extraction failed for chunk {i}: {e}")

        sync_success = 0
        sync_failed = 0
        if all_affected_keys:
            tasks = build_sync_tasks(all_affected_keys)
            doc_store.create_sync_tasks_batch(tasks)
            for _ in range(50):
                r = process_pending_tasks()
                sync_success += r["success"]
                sync_failed += r["failed"]
                if r["success"] + r["failed"] == 0:
                    break

        return {
            "success": True,
            "chunks_processed": len(chunks),
            "evidence_count": evidence_count,
            "affected_keys": sum(len(v) for v in all_affected_keys.values()),
            "sync_success": sync_success,
            "sync_failed": sync_failed,
            "errors": errors,
        }
    except Exception as e:
        logger.error(f"Build graph failed: {e}", exc_info=True)
        return {"success": False, "message": str(e)}


# ── Delete All ──


@router.post("/delete-all-vectors")
async def delete_all_vectors():
    try:
        from src.retrieval.vector_retriever import MilvusVectorRetriever
        vr = MilvusVectorRetriever()
        vr.connect()
        vr._client.drop_collection(vr.collection_name)
        return {"success": True, "message": "All vectors deleted"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/delete-all-graph")
async def delete_all_graph():
    try:
        from src.knowledge_graph.neo4j_manager import Neo4jManager
        nm = Neo4jManager()
        nm.connect()
        with nm._driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        return {"success": True, "message": "All Neo4j nodes and relations deleted"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/delete-inactive-graph")
async def delete_inactive_graph():
    try:
        from src.knowledge_graph.neo4j_manager import Neo4jManager
        nm = Neo4jManager()
        nm.connect()
        with nm._driver.session() as session:
            entities = session.run("MATCH (e:Entity) WHERE e.active = false DETACH DELETE e").consume()
            facts = session.run("MATCH (f:Fact) WHERE f.active = false DETACH DELETE f").consume()
            attrs = session.run("MATCH (a:Attribute) WHERE a.active = false DETACH DELETE a").consume()
        return {
            "success": True,
            "entities_deleted": entities.counters.nodes_deleted,
            "facts_deleted": facts.counters.nodes_deleted,
            "attrs_deleted": attrs.counters.nodes_deleted,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


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
