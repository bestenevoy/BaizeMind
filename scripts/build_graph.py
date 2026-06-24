#!/usr/bin/env python3
"""知识图谱构建脚本 — 对已索引文档的Chunk进行实体关系抽取并以Evidence驱动的模式导入Neo4j"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.logging_config import setup_logging
setup_logging()

from src.retrieval.bm25_retriever import BM25Retriever
from src.knowledge_graph.entity_extractor import EntityExtractor
from src.knowledge_graph.chunk_manager import compute_chunk_hash, create_or_reuse_chunk, build_sync_tasks
from src.knowledge_graph.evidence_writer import write_evidence
from src.knowledge_graph.graph_sync_worker import process_pending_tasks
from src.storage import doc_store


def build_graph():
    print("Building knowledge graph (evidence-driven)...")

    bm25 = BM25Retriever()
    bm25.load()
    chunks = bm25._chunks
    if not chunks:
        print("No chunks found. Please ingest documents first.")
        return

    print(f"Processing {len(chunks)} chunks...")

    extractor = EntityExtractor()
    all_affected_keys: dict[str, set[str]] = {}
    evidence_count = 0

    for i, chunk in enumerate(chunks):
        ch = compute_chunk_hash(chunk["text"])
        create_or_reuse_chunk(chunk["text"])
        items = extractor.extract_evidence(chunk["text"], chunk_hash=ch)
        if items:
            result = write_evidence(ch, items)
            evidence_count += result["count"]
            for t, keys in result.get("affected_keys", {}).items():
                if t not in all_affected_keys:
                    all_affected_keys[t] = set()
                all_affected_keys[t].update(keys)

        if (i + 1) % 10 == 0:
            print(f"  Progress: {i + 1}/{len(chunks)} chunks, {evidence_count} evidence records")

    print(f"\n  Total evidence: {evidence_count} records")
    print(f"  Affected keys: {sum(len(v) for v in all_affected_keys.values())}")

    if all_affected_keys:
        tasks = build_sync_tasks(all_affected_keys)
        doc_store.create_sync_tasks_batch(tasks)
        result = process_pending_tasks()
        print(f"  Sync: {result['success']} success, {result['failed']} failed")

    print(f"\nGraph built successfully!")


if __name__ == "__main__":
    build_graph()
