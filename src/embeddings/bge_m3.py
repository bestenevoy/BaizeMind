import numpy as np
from config.settings import settings


class BGEM3Embedding:
    def __init__(self, use_local: bool | None = None):
        self.use_local = use_local if use_local is not None else settings.bge_m3_use_local
        self._model = None
        self._dim = 1024
        if self.use_local:
            self._init_local()

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
        resp.raise_for_status()
        data = resp.json()["data"]
        return np.array([d["embedding"] for d in data], dtype=np.float32)

    def encode_dense(self, texts: list[str]) -> np.ndarray:
        if self.use_local and self._model is not None:
            return np.array(self._model.encode(texts)["dense_vecs"], dtype=np.float32)
        return self._get_api_embeddings(texts)

    def encode_sparse(self, texts: list[str]) -> list[dict[int, float]]:
        if self.use_local and self._model is not None:
            return self._model.encode(texts)["lexical_weights"]
        return []

    def encode_query_dense(self, text: str) -> np.ndarray:
        return self.encode_dense([text])[0]

    @property
    def dim(self) -> int:
        return self._dim
