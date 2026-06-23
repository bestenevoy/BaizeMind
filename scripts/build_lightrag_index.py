#!/usr/bin/env python3
"""Build LightRAG entity & relation vector indexes from the existing Neo4j knowledge graph.

This script:
1. Reads all entities from Neo4j, embeds them, and stores in Milvus (entity index)
2. Reads all relations from Neo4j, embeds them, and stores in Milvus (relation index)
3. After this, the workflow can use LightRAG (vector-based entity/relation retrieval)
   instead of LLM-based NER for query-time entity extraction.

Usage:
    uv run python scripts/build_lightrag_index.py              # Build both indexes
    uv run python scripts/build_lightrag_index.py --clear      # Clear and rebuild
    uv run python scripts/build_lightrag_index.py --entities-only
    uv run python scripts/build_lightrag_index.py --relations-only
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.retrieval.entity_index import EntityIndex
from src.retrieval.relation_index import RelationIndex


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build LightRAG vector indexes")
    parser.add_argument("--clear", action="store_true", help="Clear existing indexes before building")
    parser.add_argument("--entities-only", action="store_true", help="Build entity index only")
    parser.add_argument("--relations-only", action="store_true", help="Build relation index only")
    args = parser.parse_args()

    build_entities = not args.relations_only
    build_relations = not args.entities_only

    if build_entities:
        print("=" * 60)
        print("Building LightRAG Entity Index...")
        print("=" * 60)
        ei = EntityIndex()
        if args.clear:
            ei.clear()
        count = ei.build_from_neo4j()
        print(f"Entity index: {count} entities indexed in '{ei.collection_name}'")

    if build_relations:
        print("\n" + "=" * 60)
        print("Building LightRAG Relation Index...")
        print("=" * 60)
        ri = RelationIndex()
        if args.clear:
            ri.clear()
        count = ri.build_from_neo4j()
        print(f"Relation index: {count} relations indexed in '{ri.collection_name}'")

    print("\nLightRAG indexes built successfully.")
    print("The workflow will now use vector-based entity/relation retrieval for:")
    print("  - multi_hop queries")
    print("  - comparison queries")
    print("  - simple_fact queries with multiple entities")


if __name__ == "__main__":
    main()
