import json
import pickle
import logging
import re
from pathlib import Path
from typing import Any, Optional

from rank_bm25 import BM25Okapi

from config.settings import settings

logger = logging.getLogger(__name__)


_JIEBA_LOADED = False


def _load_jieba():
    global _JIEBA_LOADED
    if _JIEBA_LOADED:
        return
    try:
        import os
        import tempfile

        cache_dir = settings.data_dir / "jieba_cache"
        os.makedirs(cache_dir, exist_ok=True)

        _orig = tempfile.tempdir
        tempfile.tempdir = str(cache_dir)
        try:
            import jieba
            jieba.setLogLevel(20)
        finally:
            tempfile.tempdir = _orig

        _JIEBA_LOADED = True
    except ImportError:
        pass


def tokenize(text: str) -> list[str]:
    try:
        import jieba
        _load_jieba()
        return [t for t in jieba.cut(text) if t.strip()]
    except ImportError:
        return _char_bigram_fallback(text)


def _char_bigram_fallback(text: str) -> list[str]:
    """Character bigram fallback for Chinese text when jieba is unavailable."""
    result = []
    for i in range(len(text)):
        if i + 1 < len(text):
            result.append(text[i:i + 2])
    return result if result else [text.lower()]


class BM25Retriever:
    def __init__(self, index_path: Optional[str] = None):
        self.index_path = Path(index_path or settings.data_dir / "bm25_index")
        self._model: Optional[BM25Okapi] = None
        self._chunks: list[dict] = []
        self._corpus: list[list[str]] = []
        self._chunk_ids: set[str] = set()

    def build_index(self, chunks: list[dict[str, Any]]):
        self._chunks = chunks
        self._chunk_ids = {c.get("chunk_id", "") for c in chunks}
        self._corpus = [tokenize(c["text"]) for c in chunks]
        self._model = BM25Okapi(self._corpus)

    def merge_chunks(self, new_chunks: list[dict[str, Any]]):
        fresh = [c for c in new_chunks if c.get("chunk_id", "") not in self._chunk_ids]
        if not fresh:
            return
        for c in fresh:
            self._chunks.append(c)
            self._chunk_ids.add(c.get("chunk_id", ""))
            self._corpus.append(tokenize(c["text"]))
        self._model = BM25Okapi(self._corpus)

    def rebuild_from_milvus(self) -> bool:
        try:
            from src.retrieval.vector_retriever import MilvusVectorRetriever
            vr = MilvusVectorRetriever()
            all_chunks = vr.fetch_all_chunks()
            if not all_chunks:
                logger.info("BM25 rebuild skipped: no chunks in Milvus")
                return False
            chunk_dicts = [
                {
                    "doc_id": c.get("doc_id", ""),
                    "chunk_id": c.get("chunk_id", ""),
                    "text": c.get("text", ""),
                    "metadata": c.get("metadata", {}),
                }
                for c in all_chunks
            ]
            self.build_index(chunk_dicts)
            self.save()
            logger.info(f"BM25 index rebuilt from Milvus: {len(chunk_dicts)} chunks")
            return True
        except Exception as e:
            logger.warning(f"BM25 rebuild from Milvus failed: {e}")
            return False

    def save(self):
        if self._model is None:
            return
        self.index_path.mkdir(parents=True, exist_ok=True)
        data = {"chunks": self._chunks, "corpus": self._corpus, "chunk_ids": list(self._chunk_ids)}
        with open(self.index_path / "bm25_model.pkl", "wb") as f:
            pickle.dump(self._model, f)
        with open(self.index_path / "bm25_data.json", "w") as f:
            json.dump(data, f, ensure_ascii=False)

    def load(self):
        model_file = self.index_path / "bm25_model.pkl"
        data_file = self.index_path / "bm25_data.json"
        if model_file.exists() and data_file.exists():
            try:
                with open(model_file, "rb") as f:
                    self._model = pickle.load(f)
                with open(data_file) as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._chunks = data.get("chunks", [])
                    self._corpus = data.get("corpus", [])
                    self._chunk_ids = set(data.get("chunk_ids", []) or [])
                else:
                    logger.warning("BM25 data file has unexpected format, treating as empty")
                    self._model = None
                    self._chunks = []
                    self._corpus = []
                    self._chunk_ids = set()
                    return
                if not self._validate():
                    logger.warning("BM25 index validation failed, deleting stale files and will rebuild")
                    self._model = None
                    self._chunks = []
                    self._corpus = []
                    self._chunk_ids = set()
                    try:
                        model_file.unlink(missing_ok=True)
                        data_file.unlink(missing_ok=True)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Failed to load BM25 index: {e}, treating as empty")
                self._model = None
                self._chunks = []
                self._corpus = []
                self._chunk_ids = set()

    def _validate(self) -> bool:
        if not self._model or not self._chunks or not self._corpus:
            return False
        if len(self._chunks) != len(self._corpus):
            return False
        sample_size = min(5, len(self._corpus))
        for i in range(sample_size):
            clen = len(self._corpus[i])
            if clen == 0:
                return False
            if clen == 1 and len(self._corpus[i][0]) > 200:
                return False
        return True

    def remove_by_doc_id(self, doc_id: str):
        if not self._model:
            return
        keep = [c for c in self._chunks if c.get("doc_id") != doc_id]
        removed = len(self._chunks) - len(keep)
        if removed == 0:
            return
        self._chunks = keep
        self._chunk_ids = {c.get("chunk_id", "") for c in keep}
        if self._chunks:
            self._corpus = [tokenize(c["text"]) for c in self._chunks]
            self._model = BM25Okapi(self._corpus)
        else:
            self._model = None
            self._corpus = []
        self.save()

    def search(self, query: str, top_k: int = 20) -> list[dict[str, Any]]:
        if self._model is None:
            self.load()
        if self._model is None:
            self.rebuild_from_milvus()
        if self._model is None:
            return []
        tokenized = tokenize(query)
        scores = self._model.get_scores(tokenized)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        max_score = max(scores) if len(scores) > 0 and max(scores) > 0 else 1.0
        return [
            {
                "id": self._chunks[idx].get("chunk_id", ""),
                "doc_id": self._chunks[idx].get("doc_id", ""),
                "chunk_id": self._chunks[idx].get("chunk_id", ""),
                "text": self._chunks[idx].get("text", ""),
                "score": float(score / max_score),
                "metadata": self._chunks[idx].get("metadata", {}),
            }
            for idx, score in ranked
        ]
