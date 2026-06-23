"""Graph Sync Worker — consumes GraphSyncTask queue and syncs Neo4j."""

import logging
from typing import Optional

from src.storage import doc_store
from src.knowledge_graph.evidence_writer import get_support_count
from config.settings import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = settings.graph_sync_max_retries


def process_pending_tasks(neo4j_manager=None) -> dict:
    """Process pending GraphSyncTask entries. Returns {success, failed, skipped}."""
    if neo4j_manager is None:
        from src.knowledge_graph.neo4j_manager import Neo4jManager
        neo4j_manager = Neo4jManager()

    tasks = doc_store.get_pending_sync_tasks(limit=settings.graph_sync_batch_size)
    if not tasks:
        return {"success": 0, "failed": 0, "skipped": 0}

    neo4j_manager.connect()
    success = 0
    failed = 0

    for task in tasks:
        try:
            count = get_support_count(
                affected_type=task["affected_type"],
                entity_key=_parse_entity_key(task),
                subject_key=_parse_subject_key(task),
                predicate=task.get("predicate"),
                object_key=_parse_object_key(task),
                attr_key=task.get("attr_key"),
                attr_value=task.get("attr_value"),
            )
            neo4j_manager.sync_from_affected(
                affected_key=task["affected_key"],
                affected_type=task["affected_type"],
                support_count=count,
            )
            doc_store.mark_sync_task_status(task["task_id"], "SUCCESS")
            success += 1
        except Exception as e:
            logger.warning(f"Sync task {task['task_id']} failed: {e}")
            if task["retry_count"] < MAX_RETRIES:
                doc_store.mark_sync_task_retry(task["task_id"])
            else:
                doc_store.mark_sync_task_status(task["task_id"], "FAILED")
            failed += 1

    return {"success": success, "failed": failed, "skipped": 0}


def _parse_entity_key(task: dict) -> Optional[str]:
    t = task["affected_type"]
    key = task["affected_key"]
    if t == "ENTITY":
        return key
    if t == "ENTITY_ATTRIBUTE":
        return key.split("|")[0] if "|" in key else key
    return None


def _parse_subject_key(task: dict) -> Optional[str]:
    t = task["affected_type"]
    key = task["affected_key"]
    if t in ("FACT", "FACT_ATTRIBUTE"):
        return key.split("|")[0] if "|" in key else None
    return None


def _parse_object_key(task: dict) -> Optional[str]:
    t = task["affected_type"]
    key = task["affected_key"]
    if t in ("FACT", "FACT_ATTRIBUTE"):
        parts = key.split("|")
        return parts[2] if len(parts) >= 3 else None
    return None
