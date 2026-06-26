import json
import logging

import numpy as np

from config.settings import settings

logger = logging.getLogger(__name__)


class BGEM3Embedding:
    def __init__(self, use_local: bool | None = None):
        self.use_local = use_local if use_local is not None else settings.bge_m3_use_local
        self._model = None
        self._dim = 1024
        # Embedding 缓存（按 text 缓存向量，避免调试时重复请求 API）
        # 与 LLM 共用同一缓存实例，仅 make_key 前缀不同（"emb"）
        self._cache = None
        if self.use_local:
            self._init_local()

    def _get_cache(self):
        """延迟初始化 embedding 缓存（避免 import 时连接 Garnet）。"""
        if self._cache is None:
            from src.cache import get_embedding_cache
            self._cache = get_embedding_cache()
        return self._cache

    def _cache_key(self, text: str) -> str:
        """构造缓存 key：使用 make_key 生成 "emb:hash" 形式。

        包含 model 标识 + max_length + text，不同 model/截断长度会产生不同向量，需区分。
        """
        from src.cache import make_key
        model_tag = settings.siliconflow_embedding_model if not self.use_local else "local-bge-m3"
        return make_key("emb", model_tag, str(settings.bge_m3_max_length), text)

    def _init_local(self):
        try:
            from FlagEmbedding import BGEM3FlagModel
            self._model = BGEM3FlagModel(
                settings.bge_m3_model_path,
                devices=settings.bge_m3_device,
                normalize_embeddings=True,
                use_fp16=True,
            )
        except Exception as e:
            print(f"Failed to load local BGE-M3: {e}. Falling back to SiliconFlow API.")
            self.use_local = False

    def _get_api_embeddings(self, texts: list[str]) -> np.ndarray:
        import httpx
        payload = {
            "model": settings.siliconflow_embedding_model,
            "input": texts,
            "encoding_format": "float",
        }
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                settings.siliconflow_embedding_url,
                json=payload,
                headers={"Authorization": f"Bearer {settings.siliconflow_api_key}"},
            )
        if resp.is_error:
            raise RuntimeError(
                f"SiliconFlow API error (HTTP {resp.status_code}): {resp.text}"
            )
        data = resp.json()["data"]
        return np.array([d["embedding"] for d in data], dtype=np.float32)

    def encode_dense(self, texts: list[str]) -> np.ndarray:
        """编码文本为稠密向量（带缓存）。

        缓存策略：按 text 查缓存，命中直接反序列化为向量；
        未命中的 text 才走真实 embedding（API 或本地模型），结果写入缓存。
        """
        from src.cache import NoopCache

        max_chars = settings.bge_m3_max_length
        truncated = [t[:max_chars] if len(t) > max_chars else t for t in texts]

        cache = self._get_cache()
        if isinstance(cache, NoopCache):
            # 缓存禁用，直接走原逻辑
            if self.use_local and self._model is not None:
                return np.array(self._model.encode(truncated)["dense_vecs"], dtype=np.float32)
            return self._get_api_embeddings(truncated)

        # 逐个查缓存，分离 hit / miss
        results: list[np.ndarray | None] = [None] * len(truncated)
        miss_indices: list[int] = []
        miss_texts: list[str] = []
        for i, t in enumerate(truncated):
            key = self._cache_key(t)
            cached = cache.get(key)
            if cached is not None:
                try:
                    results[i] = np.array(json.loads(cached), dtype=np.float32)
                except json.JSONDecodeError:
                    miss_indices.append(i)
                    miss_texts.append(t)
            else:
                miss_indices.append(i)
                miss_texts.append(t)

        # 对未命中的 text 批量生成向量
        if miss_texts:
            if self.use_local and self._model is not None:
                miss_vecs = np.array(self._model.encode(miss_texts)["dense_vecs"], dtype=np.float32)
            else:
                miss_vecs = self._get_api_embeddings(miss_texts)

            # 写入缓存 + 填回 results
            for j, idx in enumerate(miss_indices):
                vec = miss_vecs[j]
                results[idx] = vec
                t = miss_texts[j]
                key = self._cache_key(t)
                cache.set(key, json.dumps(vec.tolist()), ttl=settings.cache_ttl_seconds)
            logger.debug(
                "Embedding cache: %d hit, %d miss (model=%s)",
                len(truncated) - len(miss_texts),
                len(miss_texts),
                "local" if self.use_local else "api",
            )

        return np.array(results, dtype=np.float32)

    def encode_dense_all(self, texts: list[str], batch_size: int = 32, concurrency: int = 8) -> np.ndarray:
        """批量编码（带缓存，复用 encode_dense 的缓存逻辑）。

        缓存命中时不调用 API；未命中的 text 按批次并发请求。
        """
        if not texts:
            return np.array([], dtype=np.float32)
        # 复用 encode_dense 的逐文本缓存逻辑（已内置批量未命中处理）
        # 注意：encode_dense 内部已按 miss_texts 调用 _get_api_embeddings 一次性批量请求，
        # 无需在此再分批。保留 batch_size 参数仅为 API 层兼容。
        return self.encode_dense(texts)

    def encode_sparse(self, texts: list[str]) -> list[dict[int, float]]:
        if self.use_local and self._model is not None:
            return self._model.encode(texts)["lexical_weights"]
        return []

    def encode_query_dense(self, text: str) -> np.ndarray:
        return self.encode_dense([text])[0]

    @property
    def dim(self) -> int:
        return self._dim
