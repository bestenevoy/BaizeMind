"""Attribute conflict resolver — picks primary value from multiple candidates."""

from typing import Optional

from src.storage import doc_store


def resolve_primary(entity_key: str, attr_key: str) -> Optional[dict]:
    """Pick the primary attribute value based on support_count and confidence.

    Returns: {"attr_value": ..., "support_count": ..., "confidence_avg": ...} or None
    """
    conn = doc_store._get_conn()
    rows = conn.execute(
        """SELECT attr_value, COUNT(*) as support_count, AVG(confidence) as confidence_avg
           FROM evidence
           WHERE active = 1 AND evidence_type = 'ENTITY_ATTRIBUTE'
             AND entity_key = ? AND attr_key = ?
           GROUP BY attr_value
           ORDER BY support_count DESC, confidence_avg DESC
           LIMIT 1""",
        (entity_key, attr_key),
    ).fetchall()
    conn.close()

    if not rows:
        return None

    r = rows[0]
    return {
        "attr_value": r["attr_value"],
        "support_count": r["support_count"],
        "confidence_avg": round(r["confidence_avg"], 4),
    }


def resolve_fact_primary(fact_key: str, attr_key: str) -> Optional[dict]:
    """Pick the primary fact attribute value."""
    parts = fact_key.split("|")
    if len(parts) < 3:
        return None

    conn = doc_store._get_conn()
    rows = conn.execute(
        """SELECT attr_value, COUNT(*) as support_count, AVG(confidence) as confidence_avg
           FROM evidence
           WHERE active = 1 AND evidence_type = 'FACT_ATTRIBUTE'
             AND subject_key = ? AND predicate = ? AND object_key = ?
             AND attr_key = ?
           GROUP BY attr_value
           ORDER BY support_count DESC, confidence_avg DESC
           LIMIT 1""",
        (parts[0], parts[1], parts[2], attr_key),
    ).fetchall()
    conn.close()

    if not rows:
        return None

    r = rows[0]
    return {
        "attr_value": r["attr_value"],
        "support_count": r["support_count"],
        "confidence_avg": round(r["confidence_avg"], 4),
    }


def list_entity_attr_candidates(entity_key: str, attr_key: str) -> list[dict]:
    """List all candidate values for a given entity attribute, sorted by support_count."""
    conn = doc_store._get_conn()
    rows = conn.execute(
        """SELECT attr_value, COUNT(*) as support_count, AVG(confidence) as confidence_avg
           FROM evidence
           WHERE active = 1 AND evidence_type = 'ENTITY_ATTRIBUTE'
             AND entity_key = ? AND attr_key = ?
           GROUP BY attr_value
           ORDER BY support_count DESC, confidence_avg DESC""",
        (entity_key, attr_key),
    ).fetchall()
    conn.close()
    return [
        {"attr_value": r["attr_value"], "support_count": r["support_count"], "confidence_avg": round(r["confidence_avg"], 4)}
        for r in rows
    ]


def update_primary_in_neo4j(entity_key: str, attr_key: str, neo4j_manager=None) -> bool:
    """After primary value change, update Neo4j Attribute.is_primary flags."""
    if neo4j_manager is None:
        from src.knowledge_graph.neo4j_manager import Neo4jManager
        neo4j_manager = Neo4jManager()

    neo4j_manager.connect()
    candidates = list_entity_attr_candidates(entity_key, attr_key)
    if not candidates:
        return False

    primary_value = candidates[0]["attr_value"]

    with neo4j_manager._driver.session() as session:
        session.run(
            """MATCH (a:Attribute {owner_key: $owner_key, key: $attr_key})
               SET a.is_primary = false""",
            owner_key=entity_key, attr_key=attr_key,
        )
        session.run(
            """MATCH (a:Attribute {owner_key: $owner_key, key: $attr_key, value: $value})
               SET a.is_primary = true""",
            owner_key=entity_key, attr_key=attr_key, value=primary_value,
        )
    return True
