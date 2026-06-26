"""Garbage collector — cleans up old GraphSyncTasks.

ChunkContent 的物理删除已改为文档删除时直接清理（见 chunk_manager.delete_document_chunks），
不再需要基于 ref_count/TTL 的延迟 GC，gc_inactive_chunks 已移除。
"""

import logging

from src.storage import doc_store

logger = logging.getLogger(__name__)


def gc_old_sync_tasks(days: int = 7) -> None:
    """Remove GraphSyncTask entries older than N days."""
    doc_store.cleanup_old_sync_tasks(days)
    logger.info(f"GC: cleaned up sync tasks older than {days} days")
