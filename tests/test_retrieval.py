"""检索模块测试"""
from src.retrieval.bm25_retriever import BM25Retriever, tokenize


def _build_test_bm25():
    """Build a BM25 index large enough to avoid negative-IDF zero-score issues."""
    chunks = [
        {"doc_id": "d1", "chunk_id": "c1", "text": "Python是一种流行的编程语言，语法简洁易读", "metadata": {}},
        {"doc_id": "d1", "chunk_id": "c2", "text": "Java也是一种广泛使用的编程语言，面向对象特性强", "metadata": {}},
        {"doc_id": "d2", "chunk_id": "c3", "text": "机器学习是人工智能的重要分支，Python是首选语言", "metadata": {}},
        {"doc_id": "d3", "chunk_id": "c4", "text": "深度学习使用神经网络进行特征提取和模式识别", "metadata": {}},
        {"doc_id": "d3", "chunk_id": "c5", "text": "自然语言处理研究计算机与人类语言的交互", "metadata": {}},
        {"doc_id": "d4", "chunk_id": "c6", "text": "数据库管理系统负责数据的存储检索和管理", "metadata": {}},
        {"doc_id": "d4", "chunk_id": "c7", "text": "分布式系统通过多台计算机协同工作提高可靠性", "metadata": {}},
        {"doc_id": "d5", "chunk_id": "c8", "text": "云计算提供弹性可扩展的计算资源服务", "metadata": {}},
    ]
    bm25 = BM25Retriever()
    bm25.build_index(chunks)
    return bm25, chunks


def test_hybrid_retriever_init():
    from src.retrieval.hybrid_retriever import HybridRetriever
    retriever = HybridRetriever()
    assert retriever is not None


def test_bm25_retriever():
    bm25, _ = _build_test_bm25()
    results = bm25.search("Python编程语言")
    assert len(results) > 0
    assert "Python" in results[0]["text"]


def test_bm25_retriever_doc_filter():
    """BM25 should filter results by doc_ids."""
    bm25, _ = _build_test_bm25()
    results = bm25.search("Python", doc_ids=["d1"])
    assert len(results) > 0
    assert all(r["doc_id"] == "d1" for r in results)


def test_bm25_zero_score_filter():
    """BM25 should not return zero-score results for non-matching queries."""
    bm25, _ = _build_test_bm25()
    results = bm25.search("量子纠缠物理实验")
    assert len(results) == 0


def test_rrf_fusion():
    from src.retrieval.hybrid_retriever import HybridRetriever
    retriever = HybridRetriever()
    r1 = [
        {"chunk_id": "a", "text": "doc a", "score": 0.9},
        {"chunk_id": "b", "text": "doc b", "score": 0.7},
    ]
    r2 = [
        {"chunk_id": "b", "text": "doc b", "score": 0.8},
        {"chunk_id": "c", "text": "doc c", "score": 0.5},
    ]
    result = retriever._rrf_fusion(
        {"dense": r1, "bm25": r2},
        {"dense": 0.5, "bm25": 0.5},
    )
    assert "ranked" in result
    assert len(result["ranked"]) <= 3
    # chunk "b" appears in both sources, should rank first
    assert result["ranked"][0][0] == "b"


def test_reranker_cross_encoder():
    """Test reranker with cross-encoder (embedding method)."""
    from src.retrieval.reranker import Reranker
    results = [
        {"text": "The capital of France is Paris"},
        {"text": "Python was created by Guido van Rossum"},
        {"text": "Machine learning is a subset of AI"},
    ]
    reranker = Reranker()
    reranked = reranker._cross_encoder_rerank("What is the capital of France?", results, top_k=1)
    assert len(reranked) == 1
    assert "Paris" in reranked[0]["text"]


def test_build_milvus_doc_filter():
    """Test the Milvus doc filter expression builder."""
    from src.retrieval.hybrid_retriever import _build_milvus_doc_filter

    # None / empty → None
    assert _build_milvus_doc_filter(None) is None
    assert _build_milvus_doc_filter([]) is None

    # Normal case → proper expression with commas
    expr = _build_milvus_doc_filter(["doc1", "doc2", "doc3"])
    assert expr == 'doc_id in ["doc1", "doc2", "doc3"]'

    # Single doc
    expr = _build_milvus_doc_filter(["only_doc"])
    assert expr == 'doc_id in ["only_doc"]'

    # Too many docs → None (skip filter)
    expr = _build_milvus_doc_filter([f"doc_{i}" for i in range(600)])
    assert expr is None
