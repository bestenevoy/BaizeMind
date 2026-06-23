"""Garbage collector — cleans up inactive ChunkContent and old GraphSyncTasks."""

from datetime import datetime, timedelta
import logging

from src.storage import doc_store
from config.settings import settings

logger = logging.getLogger(__name__)

TTL_DAYS = settings.chunk_gc_ttl_days


def gc_inactive_chunks() -> int:
    """Physically delete ChunkContent records that have been inactive for > TTL_DAYS.
    Also removes their Milvus vectors.
    Returns count of deleted chunks.
    """
    cutoff = (datetime.now() - timedelta(days=TTL_DAYS)).isoformat()
    conn = doc_store._get_conn()
    rows = conn.execute(
        "SELECT chunk_hash, milvus_id FROM chunk_content WHERE active = 0 AND created_at < ?",
        (cutoff,),
    ).fetchall()
    conn.close()

    if not rows:
        return 0

    from src.retrieval.vector_retriever import MilvusVectorRetriever
    vr = MilvusVectorRetriever()

    deleted = 0
    for r in rows:
        chunk_hash = r["chunk_hash"]
        milvus_id = r["milvus_id"]

        conn = doc_store._get_conn()
        conn.execute("DELETE FROM chunk_content WHERE chunk_hash = ?", (chunk_hash,))
        conn.execute("DELETE FROM evidence WHERE chunk_hash = ?", (chunk_hash,))
        conn.commit()
        conn.close()

        if milvus_id:
            try:
                vr._client.delete(
                    collection_name=settings.milvus_collection,
                    filter=f'chunk_id == "{milvus_id}"',
                )
            except Exception as e:
                logger.warning(f"Failed to delete Milvus vector for chunk {chunk_hash}: {e}")

        deleted += 1

    logger.info(f"GC: deleted {deleted} inactive chunks (older than {TTL_DAYS} days)")
    return deleted


def gc_old_sync_tasks(days: int = 7) -> None:
    """Remove GraphSyncTask entries older than N days."""
    doc_store.cleanup_old_sync_tasks(days)
    logger.info(f"GC: cleaned up sync tasks older than {days} days")
