#!/usr/bin/env python3
"""知识图谱构建脚本 - 对已索引文档的Chunk进行实体关系抽取并导入Neo4j"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.retrieval.bm25_retriever import BM25Retriever
from src.knowledge_graph.entity_extractor import EntityExtractor
from src.knowledge_graph.neo4j_manager import Neo4jManager


def build_graph():
    print("Building knowledge graph...")

    bm25 = BM25Retriever()
    bm25.load()
    chunks = bm25._chunks
    if not chunks:
        print("No chunks found. Please ingest documents first.")
        return

    print(f"Processing {len(chunks)} chunks...")

    extractor = EntityExtractor()
    neo4j = Neo4jManager()
    neo4j.connect()
    neo4j.init_schema()

    batch_size = 10
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i: i + batch_size]
        extracted = extractor.extract_from_chunks(batch)
        entities = [e for e in extracted if "type" in e and "name" in e]
        relations = [r for r in extracted if "predicate" in r]
        neo4j.batch_import(entities, relations)
        print(f"  Batch {i // batch_size + 1}/{len(chunks) // batch_size + 1}: "
              f"{len(entities)} entities, {len(relations)} relations")

    stats = neo4j.get_stats()
    print(f"\nGraph built successfully!")
    print(f"  Entities: {stats['entity_count']}")
    print(f"  Relations: {stats['relation_count']}")


if __name__ == "__main__":
    build_graph()
