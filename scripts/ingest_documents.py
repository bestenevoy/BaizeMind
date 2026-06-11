#!/usr/bin/env python3
"""批量文档导入脚本"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.document_parser.mineru_parser import MinerUParser
from src.chunker.hierarchical_chunker import HierarchicalChunker
from src.chunker.table_chunker import TableChunker
from src.chunker.context_merger import ContextMerger
from src.document_parser.table_parser import TableParser
from src.embeddings.bge_m3 import BGEM3Embedding
from src.retrieval.vector_retriever import MilvusVectorRetriever
from src.retrieval.bm25_retriever import BM25Retriever
from src.knowledge_graph.entity_extractor import EntityExtractor
from src.knowledge_graph.neo4j_manager import Neo4jManager
from config.settings import settings
import numpy as np


def ingest(file_path: str):
    path = Path(file_path)
    doc_id = path.stem

    print(f"[Ingest] Processing: {path} (doc_id={doc_id})")

    # 1. Parse
    print("  [1/5] Parsing with MinerU...")
    parser = MinerUParser()
    result = parser.parse(path, doc_id)
    markdown = result.get("markdown", "")
    print(f"  -> Parsed {len(markdown)} chars of markdown")

    # 2. Chunk
    print("  [2/5] Chunking...")
    h_chunker = HierarchicalChunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    chunks = h_chunker.chunk(doc_id, markdown)

    tables = TableParser.extract_tables_from_markdown(markdown)
    table_chunks = TableChunker().chunk_tables(doc_id, tables)
    chunks.extend(table_chunks)

    merger = ContextMerger()
    chunks = merger.merge(chunks)
    chunks = merger.deduplicate(chunks)
    print(f"  -> Created {len(chunks)} chunks ({len(table_chunks)} table chunks)")

    # 3. Embed & Index in Milvus
    print("  [3/5] Embedding & indexing...")
    embedding = BGEM3Embedding()
    texts = [c["text"] for c in chunks]
    all_emb = []
    for i in range(0, len(texts), settings.bge_m3_batch_size):
        batch = texts[i: i + settings.bge_m3_batch_size]
        all_emb.append(embedding.encode_dense(batch))
    embeddings = np.concatenate(all_emb) if all_emb else np.array([])

    vector_retriever = MilvusVectorRetriever()
    vector_retriever.ensure_collection()
    vector_retriever.insert(chunks, embeddings)
    print(f"  -> Inserted {len(chunks)} vectors")

    # 4. BM25 Index
    print("  [4/5] Building BM25 index...")
    bm25 = BM25Retriever()
    bm25.load()
    bm25.merge_chunks(chunks)
    bm25.save()
    print("  -> BM25 index saved")

    # 5. Knowledge Graph
    print("  [5/5] Extracting entities & building graph...")
    extractor = EntityExtractor()
    extracted = extractor.extract_from_chunks(chunks)
    entities = [e for e in extracted if "type" in e and "name" in e]
    relations = [r for r in extracted if "predicate" in r]
    neo4j = Neo4jManager()
    neo4j.connect()
    neo4j.init_schema()
    neo4j.batch_import(entities, relations)
    print(f"  -> Imported {len(entities)} entities, {len(relations)} relations")

    print(f"[Done] Document {doc_id} ingested successfully!")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ingest_documents.py <file_path>")
        sys.exit(1)
    ingest(sys.argv[1])
