"""Graph Sync Worker — consumes GraphSyncTask queue and syncs Neo4j."""

import logging
from typing import Optional

from src.storage import doc_store
from src.knowledge_graph.evidence_writer import get_support_count
from config.settings import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = settings.graph_sync_max_retries


def _parse_affected_key(task: dict) -> dict:
    """Parse affected_key string into structured fields for get_support_count.

    Returns dict with optional: entity_key, subject_key, predicate, object_key, attr_key, attr_value.
    """
    t = task["affected_type"]
    key = task["affected_key"]
    result = {}

    if t == "ENTITY":
        result["entity_key"] = key
    elif t == "FACT":
        parts = key.split("|")
        if len(parts) >= 3:
            result["subject_key"] = parts[0]
            result["predicate"] = parts[1]
            result["object_key"] = parts[2]
    elif t == "ENTITY_ATTRIBUTE":
        parts = key.split("|")
        if len(parts) >= 3:
            result["entity_key"] = parts[0]
            result["attr_key"] = parts[1]
            result["attr_value"] = parts[2]
    elif t == "FACT_ATTRIBUTE":
        parts = key.split("|")
        if len(parts) >= 5:
            result["subject_key"] = parts[0]
            result["predicate"] = parts[1]
            result["object_key"] = parts[2]
            result["attr_key"] = parts[3]
            result["attr_value"] = parts[4]

    return result


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
            parsed = _parse_affected_key(task)
            count = get_support_count(
                affected_type=task["affected_type"],
                entity_key=parsed.get("entity_key"),
                subject_key=parsed.get("subject_key"),
                predicate=parsed.get("predicate"),
                object_key=parsed.get("object_key"),
                attr_key=parsed.get("attr_key"),
                attr_value=parsed.get("attr_value"),
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
