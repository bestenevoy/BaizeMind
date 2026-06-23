#!/usr/bin/env python3
"""Debug script: test evidence extraction on a specific file step by step.
Usage: uv run python scripts/debug_evidence.py [file_path]
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage import doc_store
from config.settings import settings


def debug_file(file_path: str):
    doc_id = Path(file_path).stem
    print(f"=== Debug evidence extraction for: {file_path} ===")

    # Step 1: Parse
    print("\n[1] Parsing with MinerU...")
    from src.document_parser.mineru_parser import MinerUParser
    parser = MinerUParser()
    result = parser.parse(file_path, doc_id)
    markdown = result.get("markdown", "")
    print(f"    Markdown: {len(markdown)} chars")

    # Step 2: Chunk
    print("\n[2] Chunking...")
    from src.chunker.hierarchical_chunker import HierarchicalChunker
    from src.chunker.table_chunker import TableChunker
    from src.chunker.context_merger import ContextMerger
    from src.document_parser.table_parser import TableParser

    h_chunker = HierarchicalChunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    chunks = h_chunker.chunk(doc_id, markdown)
    tables = TableParser.extract_tables_from_markdown(markdown)
    table_chunks = TableChunker().chunk_tables(doc_id, tables)
    chunks.extend(table_chunks)
    merger = ContextMerger()
    chunks = merger.merge(chunks)
    chunks = merger.deduplicate(chunks)
    chunks = [c for c in chunks if c["text"].strip()]
    print(f"    {len(chunks)} chunks")

    # Step 3: Evidence extraction
    print("\n[3] Extracting evidence...")
    from src.knowledge_graph.entity_extractor import EntityExtractor, _parse_evidence_items
    from src.knowledge_graph.evidence_writer import write_evidence
    from src.knowledge_graph.chunk_manager import compute_chunk_hash

    extractor = EntityExtractor()
    total = 0
    errors = 0

    for i, chunk in enumerate(chunks):
        ch = compute_chunk_hash(chunk["text"])
        text = chunk["text"][:4000]
        print(f"\n  Chunk [{i}] ({len(text)} chars) hash={ch[:12]}...")
        print(f"    Text preview: {text[:150]}...")

        try:
            items = extractor.extract_evidence(text, chunk_hash=ch)
            print(f"    → {len(items)} evidence items")
            for it in items[:3]:
                print(f"      type={it.evidence_type}, key={it.affected_key}")
            if len(items) > 3:
                print(f"      ... and {len(items) - 3} more")

            if items:
                result = write_evidence(ch, items)
                print(f"    → Wrote {result['count']} to SQLite")
            total += len(items)
        except Exception as e:
            print(f"    → ERROR: {e}")
            traceback.print_exc()
            errors += 1

    print(f"\n=== Summary: {total} evidence items, {errors} errors ===")

    # Step 4: Check DB
    print("\n[4] Checking SQLite evidence counts...")
    conn = doc_store._get_conn()
    by_type = conn.execute(
        "SELECT evidence_type, COUNT(*) as cnt FROM evidence WHERE active=1 GROUP BY evidence_type"
    ).fetchall()
    for r in by_type:
        print(f"    {r['evidence_type']}: {r['cnt']}")
    conn.close()


if __name__ == "__main__":
    file_path = sys.argv[1] if len(sys.argv) > 1 else "/home/wrz/code/agentic-rag/data/raw/中华人民共和国劳动法_20181229.docx"
    debug_file(file_path)
