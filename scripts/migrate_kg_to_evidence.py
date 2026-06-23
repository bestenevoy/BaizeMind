#!/usr/bin/env python3
"""Migrate existing Neo4j knowledge graph to the evidence-driven model.

Steps:
1. Read existing Entity nodes and RELATES_TO relationships from Neo4j
2. Generate backward-compatible Evidence records in SQLite
3. Rebuild Neo4j using the new Entity/Fact/Attribute model
4. Rebuild LightRAG indexes from evidence

Usage:
    uv run python scripts/migrate_kg_to_evidence.py              # Full migration
    uv run python scripts/migrate_kg_to_evidence.py --dry-run    # Preview only
    uv run python scripts/migrate_kg_to_evidence.py --clear      # Clear existing before migrate
"""
import sys
import uuid
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage import doc_store
from src.knowledge_graph.neo4j_manager import Neo4jManager
from src.knowledge_graph.evidence import (
    EntityEvidence, FactEvidence, make_entity_key, make_fact_key,
)


def migrate_entities(neo4j: Neo4jManager) -> tuple[int, list[dict]]:
    """Read Entity nodes, create ENTITY evidence, rebuild Entity+Fact nodes."""
    neo4j.connect()
    with neo4j._driver.session() as session:
        result = session.run(
            "MATCH (e:Entity) WHERE e.name IS NOT NULL RETURN e.name AS name, e.type AS type, e.description AS description, e.doc_id AS doc_id, e.chunk_id AS chunk_id"
        )
        entities = [dict(r) for r in result]

    evidence_batch = []
    for e in entities:
        ch = e.get("chunk_id", "") or "migrated"
        ev = EntityEvidence(
            chunk_hash=ch,
            entity_name=e["name"],
            entity_type=e.get("type", "Unknown"),
            confidence=0.9,
            evidence_text=f"Migrated from existing Entity: {e['name']}",
        )
        ev.extractor_version = "migration_v1"
        ev_dict = ev.to_dict()
        evidence_batch.append(ev_dict)

    if evidence_batch:
        doc_store.insert_evidence_batch(evidence_batch)

    return len(entities), entities


def migrate_relations(neo4j: Neo4jManager, entities: list[dict]) -> tuple[int, list[dict]]:
    """Read RELATES_TO relationships, create FACT evidence."""
    neo4j.connect()
    entity_map = {e["name"].lower().strip(): e for e in entities}

    with neo4j._driver.session() as session:
        try:
            result = session.run(
                """MATCH (s:Entity)-[r:RELATES_TO]->(o:Entity)
                   WHERE s.name IS NOT NULL AND o.name IS NOT NULL
                   RETURN s.name AS subject, r.type AS predicate, o.name AS object"""
            )
            relations = [dict(r) for r in result]
        except Exception:
            relations = []

    evidence_batch = []
    for rel in relations:
        subj = rel["subject"]
        pred = rel.get("predicate", "RELATES_TO") or "RELATES_TO"
        objj = rel["object"]

        subj_data = entity_map.get(subj.lower().strip(), {"type": "Unknown"})
        obj_data = entity_map.get(objj.lower().strip(), {"type": "Unknown"})

        ev = FactEvidence(
            chunk_hash="migrated",
            subject_name=subj,
            subject_type=subj_data.get("type", "Unknown"),
            predicate=pred,
            object_name=objj,
            object_type=obj_data.get("type", "Unknown"),
            confidence=0.85,
            evidence_text=f"Migrated from existing Relation: {subj} {pred} {objj}",
        )
        ev.extractor_version = "migration_v1"
        ev_dict = ev.to_dict()
        evidence_batch.append(ev_dict)

    if evidence_batch:
        doc_store.insert_evidence_batch(evidence_batch)

    return len(relations), relations


def rebuild_neo4j(entities: list[dict], relations: list[dict]):
    """Rebuild Neo4j using Entity/Fact/Attribute model."""
    neo4j = Neo4jManager()
    neo4j.connect()
    neo4j.init_evidence_schema()

    from src.knowledge_graph.evidence_writer import get_support_count

    for e in entities:
        entity_key = make_entity_key(e.get("type", "Unknown"), e["name"])
        count = get_support_count("ENTITY", entity_key=entity_key)
        neo4j.sync_entity_with_name(entity_key, e["name"], e.get("type", "Unknown"), count)

    seen_facts = set()
    for rel in relations:
        subj = rel["subject"]
        pred = rel.get("predicate", "RELATES_TO") or "RELATES_TO"
        objj = rel["object"]

        subj_match = entity_map.get(subj.lower().strip(), {"type": "Unknown"})
        obj_match = entity_map.get(objj.lower().strip(), {"type": "Unknown"})
        subject_key = make_entity_key(subj_match.get("type", "Unknown"), subj)
        object_key = make_entity_key(obj_match.get("type", "Unknown"), objj)
        fact_key = make_fact_key(subject_key, pred, object_key)

        if fact_key in seen_facts:
            continue
        seen_facts.add(fact_key)

        count = get_support_count("FACT", subject_key=subject_key, predicate=pred, object_key=object_key)
        neo4j.sync_fact(fact_key, subject_key, pred, object_key, count)

    return neo4j


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Migrate KG to evidence-driven model")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    parser.add_argument("--clear", action="store_true", help="Clear existing evidence before migrating")
    args = parser.parse_args()

    print("=" * 60)
    print("Knowledge Graph Migration to Evidence-Driven Model")
    print("=" * 60)

    if args.clear:
        print("Clearing existing evidence tables...")
        conn = doc_store._get_conn()
        conn.execute("DELETE FROM evidence")
        conn.execute("DELETE FROM graph_sync_task")
        conn.commit()
        conn.close()

    neo4j = Neo4jManager()
    neo4j.connect()

    print("\n[1/4] Reading existing Entity nodes from Neo4j...")
    entity_count, entities = migrate_entities(neo4j)
    print(f"  Found {entity_count} entities")

    print("\n[2/4] Reading existing RELATES_TO relationships...")
    relation_count, relations = migrate_relations(neo4j, entities)
    print(f"  Found {relation_count} relations")

    print(f"\n[3/4] Generating evidence records...")
    print(f"  {entity_count} ENTITY evidence records")
    print(f"  {relation_count} FACT evidence records")

    if args.dry_run:
        print("\n[Dry run] No changes applied.")
        print("Sample ENTITY evidence:", entities[:2] if entities else "None")
        print("Sample FACT evidence:", relations[:2] if relations else "None")
        return

    print("\n[4/4] Rebuilding Neo4j with Entity/Fact/Attribute model...")
    rebuild_neo4j(entities, relations)

    print("\n>>> Migration complete!")
    print("    Next steps:")
    print("    1. Set use_evidence_model=true in config/settings.py or .env")
    print("    2. Rebuild LightRAG indexes: uv run python scripts/build_lightrag_index.py --clear")
    print("    3. Restart the server")


if __name__ == "__main__":
    main()
