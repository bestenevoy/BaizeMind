#!/usr/bin/env python3
"""批量文档导入脚本 — evidence-driven flow"""
import argparse
import sys
from pathlib import Path
import hashlib

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.logging_config import setup_logging
setup_logging()

from src.document_parser.mineru_parser import MinerUParser
from src.chunker.hierarchical_chunker import HierarchicalChunker
from src.chunker.table_chunker import TableChunker
from src.document_parser.table_parser import TableParser
from src.embeddings.bge_m3 import BGEM3Embedding
from src.retrieval.vector_retriever import MilvusVectorRetriever
from src.retrieval.bm25_retriever import BM25Retriever
from src.knowledge_graph.entity_extractor import EntityExtractor
from src.knowledge_graph.chunk_manager import create_or_reuse_chunk, build_sync_tasks
from src.knowledge_graph.evidence_writer import write_evidence
from src.knowledge_graph.graph_sync_worker import process_pending_tasks
from src.storage import doc_store
from config.settings import settings
import numpy as np


def ingest(file_path: str, skip_evidence: bool = False):
    path = Path(file_path)
    doc_id = path.stem
    doc_version = 1
    skip_evidence = skip_evidence or settings.ingest_skip_evidence

    total_steps = 4 if skip_evidence else 6
    print(f"[Ingest] Processing: {path} (doc_id={doc_id})")

    # 1. Parse
    print(f"  [1/{total_steps}] Parsing with MinerU...")
    parser = MinerUParser()
    result = parser.parse(path, doc_id)
    markdown = result.get("markdown", "")
    print(f"  -> Parsed {len(markdown)} chars of markdown")

    # 2. Chunk
    print(f"  [2/{total_steps}] Chunking...")
    h_chunker = HierarchicalChunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    chunks = h_chunker.chunk(doc_id, markdown)

    tables = TableParser.extract_tables_from_markdown(markdown)
    table_chunks = TableChunker().chunk_tables(doc_id, tables)
    chunks.extend(table_chunks)

    chunks = [c for c in chunks if c["text"].strip()]
    print(f"  -> Created {len(chunks)} chunks ({len(table_chunks)} table chunks)")

    # 3. Chunk dedup & ref management
    print(f"  [3/{total_steps}] Chunk dedup & ref management...")
    new_chunks = []

    for i, chunk in enumerate(chunks):
        ch, is_new = create_or_reuse_chunk(chunk["text"])
        chunk["chunk_hash"] = ch
        doc_store.create_doc_chunk_ref(doc_id, doc_version, ch, i)
        doc_store.update_chunk_ref_count(ch)
        if is_new:
            new_chunks.append(chunk)

    print(f"  -> {len(new_chunks)} new chunks need embedding")

    # 4. Embed & Index in Milvus + BM25
    if new_chunks:
        print(f"  [4/{total_steps}] Embedding & indexing...")
        embedding = BGEM3Embedding()
        texts = [c["text"] for c in new_chunks]
        embeddings = embedding.encode_dense_all(texts, batch_size=settings.bge_m3_batch_size, concurrency=8)

        vector_retriever = MilvusVectorRetriever()
        vector_retriever.ensure_collection()
        vector_retriever.insert(new_chunks, embeddings)
        print(f"  -> Inserted {len(new_chunks)} vectors")

        conn = doc_store._get_conn()
        for nc in new_chunks:
            conn.execute(
                "UPDATE chunk_content SET milvus_id = ? WHERE chunk_hash = ?",
                (nc.get("chunk_id", ""), nc["chunk_hash"]),
            )
        conn.commit()
        conn.close()

        bm25 = BM25Retriever()
        bm25.load()
        bm25.merge_chunks(new_chunks)
        bm25.save()
        print("  -> BM25 index saved")
    else:
        print(f"  [4/{total_steps}] No new chunks — skipped embedding")

    if skip_evidence:
        print("  [SKIP] Evidence extraction + KG sync disabled (--skip-evidence)")
        print(f"[Done] Document {doc_id} ingested (chunk + index only)!")
        return

    # 5. Evidence Extraction
    print(f"  [5/{total_steps}] Extracting evidence...")
    extractor = EntityExtractor()
    all_affected_keys: dict[str, set[str]] = {}

    for chunk in new_chunks:
        ch = chunk["chunk_hash"]
        items = extractor.extract_evidence(chunk["text"], chunk_hash=ch)
        if items:
            result = write_evidence(ch, items)
            for t, keys in result.get("affected_keys", {}).items():
                if t not in all_affected_keys:
                    all_affected_keys[t] = set()
                all_affected_keys[t].update(keys)

    print(f"  -> Evidence written, affected keys: {sum(len(v) for v in all_affected_keys.values())}")

    # 6. Sync Neo4j
    print(f"  [6/{total_steps}] Syncing knowledge graph...")
    if all_affected_keys:
        tasks = build_sync_tasks(all_affected_keys, doc_id=doc_id, doc_version=doc_version)
        doc_store.create_sync_tasks_batch(tasks)
        result = process_pending_tasks()
        print(f"  -> Sync: {result['success']} success, {result['failed']} failed")
    else:
        print("  -> No changes to sync")

    print(f"[Done] Document {doc_id} ingested successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a document into the RAG system")
    parser.add_argument("file_path", help="Path to the document file")
    parser.add_argument("--skip-evidence", action="store_true",
                        help="Skip evidence extraction and knowledge graph sync (chunk + index only)")
    args = parser.parse_args()
    ingest(args.file_path, skip_evidence=args.skip_evidence)
