import json
import pickle
import logging
from pathlib import Path
from typing import Any, Optional

from rank_bm25 import BM25Okapi

from config.settings import settings

logger = logging.getLogger(__name__)


def tokenize(text: str) -> list[str]:
    try:
        import jieba
        return list(jieba.cut(text))
    except ImportError:
        return text.lower().split()


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
            with open(model_file, "rb") as f:
                self._model = pickle.load(f)
            with open(data_file) as f:
                data = json.load(f)
            self._chunks = data["chunks"]
            self._corpus = data["corpus"]
            self._chunk_ids = set(data.get("chunk_ids", []) or [])

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
