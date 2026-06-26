"""图谱管理路由：图谱总览/实体详情 + 构建图谱 + 批量删除 + BM25 重建。

从 management.py 拆分而来，统一挂在 /api/v1/system 前缀下。
"""
import logging
import threading

from fastapi import APIRouter, Depends

from api.schemas import GraphOverviewResponse, GraphNode, GraphEdge, EntityDetailResponse, ChunkInfo
from src.auth import User, require_admin
from src.knowledge_graph.neo4j_manager import Neo4jManager
from src.retrieval.vector_retriever import MilvusVectorRetriever
from src.storage import doc_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/system", tags=["system"])

# ── Graph Query ──


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


# ── Build Graph ──

_build_status: dict = {"running": False, "progress": 0, "total": 0, "done": False, "phase": "", "result": None}


@router.get("/build-graph/status")
async def build_graph_status():
    return _build_status


def _finish_build(result: dict):
    global _build_status
    _build_status = {"running": False, "progress": _build_status.get("total", 0), "total": _build_status.get("total", 0), "done": True, "phase": "完成" if result.get("success") else "失败", "result": result}


def _set_phase(phase: str):
    global _build_status
    _build_status["phase"] = phase


def _run_build_graph():
    global _build_status
    try:
        from src.retrieval.bm25_retriever import BM25Retriever
        from src.knowledge_graph.entity_extractor import EntityExtractor
        from src.knowledge_graph.chunk_manager import compute_chunk_hash, create_or_reuse_chunk, build_sync_tasks
        from src.knowledge_graph.evidence_writer import write_evidence
        from src.knowledge_graph.graph_sync_worker import process_pending_tasks
        from src.storage import doc_store

        _build_status = {"running": True, "progress": 0, "total": 0, "done": False, "phase": "加载BM25索引", "result": None}

        bm25 = BM25Retriever()
        bm25.load()
        if bm25._model is None:
            _finish_build({"success": False, "message": "BM25 index not found. Re-upload documents first (BM25 is populated during ingestion)."})
            return

        chunks = bm25._chunks
        if not chunks:
            _finish_build({"success": False, "message": "No chunks found. Re-upload documents first."})
            return
            return

        logger.info(f"Building knowledge graph for {len(chunks)} chunks...")
        _build_status = {"running": True, "progress": 0, "total": len(chunks), "done": False, "phase": f"证据抽取 0/{len(chunks)}", "result": None}

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
            _build_status["progress"] = i + 1
            _build_status["phase"] = f"证据抽取 {i + 1}/{len(chunks)}"

        sync_success = 0
        sync_failed = 0
        if all_affected_keys:
            _build_status["phase"] = "同步到Neo4j"
            tasks = build_sync_tasks(all_affected_keys)
            doc_store.create_sync_tasks_batch(tasks)
            for _ in range(50):
                r = process_pending_tasks()
                sync_success += r["success"]
                sync_failed += r["failed"]
                if r["success"] + r["failed"] == 0:
                    break

        _build_status = {"running": False, "done": True, "progress": len(chunks), "total": len(chunks),
            "result": {
                "success": True,
                "chunks_processed": len(chunks),
                "evidence_count": evidence_count,
                "affected_keys": sum(len(v) for v in all_affected_keys.values()),
                "sync_success": sync_success,
                "sync_failed": sync_failed,
                "errors": errors,
            },
        }
    except Exception as e:
        logger.error(f"Build graph failed: {e}", exc_info=True)
        _finish_build({"success": False, "message": str(e)})


@router.post("/build-graph")
async def build_graph(_: User = Depends(require_admin)):
    if _build_status.get("running"):
        return {"success": False, "message": "Build already in progress", "status": _build_status}
    threading.Thread(target=_run_build_graph, daemon=True).start()
    return {"success": True, "message": "Build started", "status": _build_status}


# ── Bulk Delete / Rebuild ──


@router.post("/rebuild-bm25")
async def rebuild_bm25(_: User = Depends(require_admin)):
    try:
        from src.retrieval.bm25_retriever import BM25Retriever
        bm25 = BM25Retriever()
        ok = bm25.rebuild_from_milvus()
        if ok:
            return {"success": True, "message": f"BM25 rebuilt: {len(bm25._chunks)} chunks"}
        else:
            # Milvus is empty — delete stale index files
            model_file = bm25.index_path / "bm25_model.pkl"
            data_file = bm25.index_path / "bm25_data.json"
            if model_file.exists():
                model_file.unlink()
            if data_file.exists():
                data_file.unlink()
            bm25._model = None
            bm25._chunks = []
            bm25._corpus = []
            bm25._chunk_ids = set()
            return {"success": True, "message": "BM25 cleared: 0 chunks (old index files deleted)"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/delete-all-vectors")
async def delete_all_vectors(_: User = Depends(require_admin)):
    try:
        from src.retrieval.vector_retriever import MilvusVectorRetriever
        vr = MilvusVectorRetriever()
        vr.connect()
        vr._client.drop_collection(vr.collection_name)
        return {"success": True, "message": "All vectors deleted"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/delete-all-graph")
async def delete_all_graph(_: User = Depends(require_admin)):
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
async def delete_inactive_graph(_: User = Depends(require_admin)):
    try:
        from src.knowledge_graph.neo4j_manager import Neo4jManager
        nm = Neo4jManager()
        nm.connect()
        with nm._driver.session() as session:
            # 包括 active=false 以及没有 active 属性的旧节点
            entities = session.run(
                "MATCH (e:Entity) WHERE e.active = false OR e.active IS NULL DETACH DELETE e"
            ).consume()
            facts = session.run(
                "MATCH (f:Fact) WHERE f.active = false OR f.active IS NULL DETACH DELETE f"
            ).consume()
            attrs = session.run(
                "MATCH (a:Attribute) WHERE a.active = false OR a.active IS NULL DETACH DELETE a"
            ).consume()
            # 也清理没有 support_count 或 support_count=0 的旧节点
            entities2 = session.run(
                "MATCH (e:Entity) WHERE e.support_count = 0 OR e.support_count IS NULL DETACH DELETE e"
            ).consume()
            facts2 = session.run(
                "MATCH (f:Fact) WHERE f.support_count = 0 OR f.support_count IS NULL DETACH DELETE f"
            ).consume()
            attrs2 = session.run(
                "MATCH (a:Attribute) WHERE a.support_count = 0 OR a.support_count IS NULL DETACH DELETE a"
            ).consume()
        return {
            "success": True,
            "entities_deleted": entities.counters.nodes_deleted + entities2.counters.nodes_deleted,
            "facts_deleted": facts.counters.nodes_deleted + facts2.counters.nodes_deleted,
            "attrs_deleted": attrs.counters.nodes_deleted + attrs2.counters.nodes_deleted,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}
