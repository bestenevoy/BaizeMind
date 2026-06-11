"""检索模块测试"""


def test_hybrid_retriever_init():
    from src.retrieval.hybrid_retriever import HybridRetriever
    retriever = HybridRetriever()
    assert retriever is not None


def test_bm25_retriever():
    from src.retrieval.bm25_retriever import BM25Retriever, tokenize
    chunks = [
        {"doc_id": "d1", "chunk_id": "c1", "text": "Python is a programming language", "metadata": {}},
        {"doc_id": "d1", "chunk_id": "c2", "text": "Java is also a programming language", "metadata": {}},
        {"doc_id": "d2", "chunk_id": "c3", "text": "Machine learning with Python", "metadata": {}},
    ]
    bm25 = BM25Retriever()
    bm25.build_index(chunks)
    results = bm25.search("Python programming")
    assert len(results) > 0
    assert "Python" in results[0]["text"]


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
        top_k=3,
    )
    assert len(result) <= 3


def test_reranker_score():
    from src.retrieval.reranker import Reranker
    results = [
        {"text": "The capital of France is Paris"},
        {"text": "Python was created by Guido van Rossum"},
        {"text": "Machine learning is a subset of AI"},
    ]
    reranker = Reranker()
    reranked = reranker._score_rerank("What is the capital of France?", results, top_k=1)
    assert len(reranked) == 1
    assert "Paris" in reranked[0]["text"]
