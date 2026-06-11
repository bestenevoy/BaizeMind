import json
from typing import Any, Optional

import numpy as np
from pymilvus import MilvusClient, DataType
from config.settings import settings


class MilvusVectorRetriever:
    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        self.host = host or settings.milvus_host
        self.port = port or settings.milvus_port
        self.collection_name = settings.milvus_collection
        self._client: Optional[MilvusClient] = None

    def connect(self):
        if self._client is None:
            uri = f"http://{self.host}:{self.port}"
            self._client = MilvusClient(uri=uri)

    def ensure_collection(self):
        self.connect()
        if not self._client.has_collection(self.collection_name):
            schema = self._client.create_schema(auto_id=False, enable_dynamic_field=True)
            schema.add_field("id", DataType.VARCHAR, max_length=256, is_primary=True)
            schema.add_field("doc_id", DataType.VARCHAR, max_length=256)
            schema.add_field("chunk_id", DataType.VARCHAR, max_length=256)
            schema.add_field("text", DataType.VARCHAR, max_length=65535)
            schema.add_field("dense_vector", DataType.FLOAT_VECTOR, dim=1024)
            schema.add_field("metadata", DataType.JSON)

            index_params = self._client.prepare_index_params()
            index_params.add_index(
                field_name="dense_vector",
                index_type="IVF_FLAT",
                metric_type="COSINE",
                params={"nlist": 128},
            )

            self._client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=index_params,
            )

    def insert(self, chunks: list[dict[str, Any]], embeddings: np.ndarray):
        self.ensure_collection()
        data = []
        for i, chunk in enumerate(chunks):
            data.append({
                "id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "chunk_id": chunk["chunk_id"],
                "text": chunk["text"],
                "dense_vector": embeddings[i].tolist(),
                "metadata": chunk.get("metadata", {}),
            })
        self._client.insert(collection_name=self.collection_name, data=data)

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 20,
        expr: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        self.ensure_collection()

        search_params = {"metric_type": "COSINE", "params": {"nprobe": 16}}
        results = self._client.search(
            collection_name=self.collection_name,
            data=[query_embedding.tolist()],
            anns_field="dense_vector",
            search_params=search_params,
            limit=top_k,
            filter=expr,
            output_fields=["id", "doc_id", "chunk_id", "text", "metadata"],
        )

        return [
            {
                "id": hit["id"],
                "doc_id": hit["entity"].get("doc_id", ""),
                "chunk_id": hit["entity"].get("chunk_id", ""),
                "text": hit["entity"].get("text", ""),
                "score": float(hit["distance"]),
                "metadata": hit["entity"].get("metadata", {}),
            }
            for hits in results
            for hit in hits
        ]

    def delete_by_doc(self, doc_id: str):
        self.ensure_collection()
        self._client.delete(
            collection_name=self.collection_name,
            filter=f'doc_id == "{doc_id}"',
        )

    def count(self) -> int:
        self.ensure_collection()
        stats = self._client.get_collection_stats(self.collection_name)
        return int(stats.get("row_count", 0))

    def fetch_all_chunks(self) -> list[dict[str, Any]]:
        self.ensure_collection()
        total = self.count()
        if total == 0:
            return []
        all_results = []
        limit = 1000
        for offset in range(0, total, limit):
            batch = self._client.query(
                collection_name=self.collection_name,
                filter="id != ''",
                output_fields=["id", "doc_id", "chunk_id", "text", "metadata"],
                limit=limit,
                offset=offset,
            )
            all_results.extend(batch)
        return all_results
