#!/usr/bin/env python3
"""Microsoft GraphRAG 索引构建脚本 - 从已解析文档构建 GraphRAG 索引"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.logging_config import setup_logging
setup_logging()

from src.knowledge_graph.graphrag_indexer import GraphRAGIndexer
from src.retrieval.bm25_retriever import BM25Retriever
from config.settings import settings


def build_graphrag_index():
    print("=== Microsoft GraphRAG Index Builder ===\n")

    indexer = GraphRAGIndexer()

    print("[1/4] Initializing GraphRAG workspace...")
    indexer.init()
    print(f"  -> Workspace: {indexer.root_dir}")

    print("[2/4] Loading chunks from BM25 index...")
    bm25 = BM25Retriever()
    bm25.load()
    chunks = bm25._chunks
    if not chunks:
        print("  ERROR: No chunks found. Run ingest_documents.py first.")
        return

    print(f"  -> Found {len(chunks)} chunks")

    print("[3/4] Writing documents to GraphRAG input directory...")
    doc_texts = {}
    for chunk in chunks:
        doc_id = chunk.get("doc_id", "unknown")
        if doc_id not in doc_texts:
            doc_texts[doc_id] = []
        doc_texts[doc_id].append(chunk["text"])

    for doc_id, texts in doc_texts.items():
        full_text = "\n\n".join(texts)
        indexer.add_document(full_text, f"{doc_id}.txt")
        print(f"  -> {doc_id}: {len(full_text)} chars")

    print(f"  -> {len(doc_texts)} documents written")

    print("[4/4] Running GraphRAG indexing pipeline...")
    print("  (This may take several minutes depending on dataset size)")
    result = indexer.index()

    if result["success"]:
        print("\n=== GraphRAG indexing complete! ===")
        print(f"  Output: {result['output_dir']}")
        files = indexer.get_parquet_files()
        print(f"  Parquet files: {len(files)}")
        for f in files:
            print(f"    - {Path(f).name}")
    else:
        print(f"\n=== GraphRAG indexing FAILED ===")
        print(f"  Error: {result['error']}")


if __name__ == "__main__":
    build_graphrag_index()
