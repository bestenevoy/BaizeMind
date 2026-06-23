"""Chunk Manager — ChunkContent deduplication, DocChunkRef management, Mark-And-Sweep updates."""

import hashlib
from typing import Optional

from src.storage import doc_store


def compute_chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def create_or_reuse_chunk(text: str, milvus_id: str = "") -> tuple[str, bool]:
    """Get or create a ChunkContent entry.

    Returns: (chunk_hash, is_new)
    """
    chunk_hash = compute_chunk_hash(text)
    existing = doc_store.get_chunk_content(chunk_hash)

    if existing:
        return chunk_hash, False

    doc_store.create_chunk_content(chunk_hash, text, milvus_id)
    return chunk_hash, True


def update_document_refs(
    doc_id: str,
    doc_version: int,
    chunks: list[dict],
) -> dict:
    """Update DocChunkRef entries for a document using Mark-And-Sweep.

    Each chunk dict must have: text, chunk_index.
    Returns: {new_chunk_hashes, stale_chunk_hashes, zero_ref_hashes, restored_hashes}
    """
    # Step 1: Mark all current refs as stale
    doc_store.mark_doc_chunk_refs_stale(doc_id)

    new_chunk_hashes = []
    restored_hashes = []

    # Step 2: Process each chunk
    for chunk in chunks:
        text = chunk["text"]
        chunk_hash = compute_chunk_hash(text)
        chunk_index = chunk.get("chunk_index", chunk.get("index", 0))

        # Check if already referenced by this doc (Case 1)
        existing_refs = doc_store.get_doc_chunk_refs(doc_id, doc_version)
        already_refd = any(r["chunk_hash"] == chunk_hash for r in existing_refs)

        if already_refd:
            doc_store.unmark_doc_chunk_ref(doc_id, chunk_hash, chunk_index)
        else:
            # Check if ChunkContent exists (Case 2: reuse)
            content = doc_store.get_chunk_content(chunk_hash)
            if content:
                ref_info = doc_store.update_chunk_ref_count(chunk_hash)
                if ref_info.get("was_zero"):
                    restored_hashes.append(chunk_hash)
                doc_store.create_doc_chunk_ref(doc_id, doc_version, chunk_hash, chunk_index)
            else:
                # Case 3: entirely new chunk — caller creates ChunkContent with milvus_id
                doc_store.create_doc_chunk_ref(doc_id, doc_version, chunk_hash, chunk_index)
                new_chunk_hashes.append(chunk_hash)

            doc_store.update_chunk_ref_count(chunk_hash)

    # Step 3: Deactivate stale refs
    stale_hashes = doc_store.deactivate_stale_doc_chunk_refs(doc_id)

    # Step 4: Process ref_count changes for stale chunks
    zero_ref_hashes = []
    for sh in stale_hashes:
        ref_info = doc_store.update_chunk_ref_count(sh)
        if ref_info.get("became_zero"):
            zero_ref_hashes.append(sh)

    return {
        "new_chunk_hashes": new_chunk_hashes,
        "stale_chunk_hashes": stale_hashes,
        "zero_ref_hashes": zero_ref_hashes,
        "restored_hashes": restored_hashes,
    }


def process_chunk_ref_zero_to_one(chunk_hash: str) -> list[dict]:
    """Handle a chunk whose ref_count went from 0 to 1.
    Reactivates evidence and returns affected keys.
    """
    doc_store.update_chunk_ref_count(chunk_hash)
    return doc_store.reactivate_evidence_by_chunk(chunk_hash)


def process_chunk_ref_one_to_zero(chunk_hash: str) -> list[dict]:
    """Handle a chunk whose ref_count went from 1 to 0.
    Only deactivates evidence and ChunkContent if ref_count actually reached 0.
    Returns affected keys for Neo4j sync.
    """
    ref_info = doc_store.update_chunk_ref_count(chunk_hash)
    if not ref_info.get("became_zero"):
        return []
    affected = doc_store.deactivate_evidence_by_chunk(chunk_hash)
    doc_store.deactivate_chunk_content(chunk_hash)
    return affected


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
