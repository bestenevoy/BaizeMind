"""Chunk Manager — chunk creation and evidence sync task building.

复用/dedup/ref_count 逻辑已移除：每个文档拥有独立的 chunk，删除文档时直接清理，
不再跨文档共享 ChunkContent，也不再做 mark-and-sweep 引用计数。
chunk_hash 由 (text, doc_id) 共同决定，保证文档间不冲突。
"""

import hashlib

from src.storage import doc_store


def compute_chunk_hash(text: str, doc_id: str = "") -> str:
    """计算 chunk_hash。包含 doc_id 以保证文档间唯一（不再跨文档复用）。

    旧数据（doc_id 为空）的 hash 与历史一致；新数据强制传入 doc_id。
    """
    payload = f"{doc_id}\x1f{text}" if doc_id else text
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def create_chunk(text: str, doc_id: str, milvus_id: str = "") -> str:
    """创建一个新的 ChunkContent（不再查重复用）。

    返回 chunk_hash。每次调用都 INSERT OR REPLACE。
    """
    chunk_hash = compute_chunk_hash(text, doc_id)
    doc_store.create_chunk_content(chunk_hash, text, doc_id=doc_id, milvus_id=milvus_id)
    return chunk_hash


def delete_document_chunks(doc_id: str) -> dict:
    """删除文档的所有 chunk 及其关联 evidence，返回受影响的 evidence keys 供 Neo4j 同步。

    流程：
      1. 查出该文档所有 chunk_hash
      2. 逐个 deactivate 关联 evidence（收集 affected_keys）
      3. 物理删除 chunk_content 记录
    """
    chunk_hashes = doc_store.get_chunk_hashes_by_doc(doc_id)
    all_affected: dict[str, set[str]] = {}

    for ch in chunk_hashes:
        affected = doc_store.deactivate_evidence_by_chunk(ch)
        for item in affected:
            t = item["affected_type"]
            k = item["affected_key"]
            if t not in all_affected:
                all_affected[t] = set()
            all_affected[t].add(k)

    doc_store.delete_chunk_content_by_doc(doc_id)
    return {"deleted_count": len(chunk_hashes), "affected_keys": all_affected}


def build_sync_tasks(
    affected_keys: dict[str, set[str]],
    doc_id: str = "",
    doc_version: int = 1,
    chunk_hash: str = "",
) -> list[dict]:
    """Convert affected_key groups into GraphSyncTask entries."""
    tasks = []
    for affected_type, keys in affected_keys.items():
        for key in keys:
            tasks.append({
                "doc_id": doc_id,
                "doc_version": doc_version,
                "chunk_hash": chunk_hash,
                "affected_key": key,
                "affected_type": affected_type,
                "operation": "UPSERT",
            })
    return tasks
