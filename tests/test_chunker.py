"""Chunk切分模块测试"""


def test_hierarchical_chunker_basic():
    from src.chunker.hierarchical_chunker import HierarchicalChunker
    md = "# Title\nContent here.\n\n## Section 1\nMore content.\n\n### Detail\nDeep content here."
    chunker = HierarchicalChunker(chunk_size=512, chunk_overlap=64)
    chunks = chunker.chunk("test_doc", md)
    assert len(chunks) > 0
    for c in chunks:
        assert "text" in c
        assert "doc_id" in c
        assert c["doc_id"] == "test_doc"


def test_table_chunker():
    from src.chunker.table_chunker import TableChunker
    table = {
        "type": "table",
        "caption": "Test Table",
        "headers": ["A", "B"],
        "rows": [["x", "y"] for _ in range(5)],
        "num_rows": 5,
        "num_cols": 2,
    }
    chunker = TableChunker(max_table_rows=3)
    chunks = chunker.chunk_tables("doc1", [table])
    assert len(chunks) == 2
    assert chunks[0]["metadata"]["type"] == "table"


def test_context_merger():
    from src.chunker.context_merger import ContextMerger
    chunks = [
        {"doc_id": "d1", "chunk_id": "c1", "heading": "H1", "text": "text1", "metadata": {"type": "text"}},
        {"doc_id": "d1", "chunk_id": "c2", "heading": "H1", "text": "text2", "metadata": {"type": "text"}},
    ]
    merger = ContextMerger(max_merge_chars=5000)
    merged = merger.merge(chunks)
    assert len(merged) == 1
    assert "text1" in merged[0]["text"]
    assert "text2" in merged[0]["text"]
