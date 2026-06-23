"""Evidence writer — bridge between extraction and SQLite evidence store."""

from typing import Optional

from src.knowledge_graph.evidence import (
    Evidence,
    EntityEvidence,
    EntityAttributeEvidence,
    FactEvidence,
    FactAttributeEvidence,
    collect_affected_keys,
)
from src.storage import doc_store


def write_evidence(
    chunk_hash: str,
    evidence_items: list[Evidence],
) -> dict:
    """Write extracted evidence to SQLite and return affected keys for Neo4j sync.

    Returns: {"count": int, "affected_keys": dict[str, set[str]]}
    """
    if not evidence_items:
        return {"count": 0, "affected_keys": {}}

    records = [ev.to_dict() for ev in evidence_items]
    count = doc_store.insert_evidence_batch(records)
    affected = collect_affected_keys(evidence_items)
    return {"count": count, "affected_keys": affected}


def deactivate_chunk_evidence(chunk_hash: str) -> list[dict]:
    """Deactivate all evidence for a chunk. Returns affected keys for GraphSyncTask."""
    return doc_store.deactivate_evidence_by_chunk(chunk_hash)


def reactivate_chunk_evidence(chunk_hash: str) -> list[dict]:
    """Reactivate evidence when chunk ref_count goes 0→1."""
    return doc_store.reactivate_evidence_by_chunk(chunk_hash)


def get_support_count(
    affected_type: str,
    entity_key: Optional[str] = None,
    subject_key: Optional[str] = None,
    predicate: Optional[str] = None,
    object_key: Optional[str] = None,
    attr_key: Optional[str] = None,
    attr_value: Optional[str] = None,
) -> int:
    return doc_store.count_active_evidence(
        affected_type=affected_type,
        entity_key=entity_key,
        subject_key=subject_key,
        predicate=predicate,
        object_key=object_key,
        attr_key=attr_key,
        attr_value=attr_value,
    )
