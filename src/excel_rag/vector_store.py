"""Excel Sheet 摘要向量检索（Milvus 独立集合）。

集合结构：
- id (VARCHAR, PK): 与 meta_id 相同
- meta_id (VARCHAR): 关联 excel_sheets 元数据
- doc_id (VARCHAR)
- text (VARCHAR): 摘要文本
- dense_vector (FLOAT_VECTOR, 1024): BGE-M3 向量
- metadata (JSON)
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
from pymilvus import MilvusClient, DataType

from config.settings import settings


class ExcelVectorStore:
    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        self.host = host or settings.milvus_host
        self.port = port or settings.milvus_port
        self.collection_name = settings.excel_milvus_collection
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
            schema.add_field("meta_id", DataType.VARCHAR, max_length=256)
            schema.add_field("doc_id", DataType.VARCHAR, max_length=256)
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

    def insert(self, sheets: list[dict[str, Any]], embeddings: np.ndarray):
        self.ensure_collection()
        data = []
        for i, sheet in enumerate(sheets):
            meta_id = sheet["meta_id"]
            data.append({
                "id": meta_id,
                "meta_id": meta_id,
                "doc_id": sheet["doc_id"],
                "text": sheet["summary"],
                "dense_vector": embeddings[i].tolist(),
                "metadata": {
                    "sheet_name": sheet.get("sheet_name", ""),
                    "doc_id": sheet["doc_id"],
                },
            })
        self._client.insert(collection_name=self.collection_name, data=data)

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 3,
        doc_ids: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """语义检索 Sheet 摘要，返回 Top-K。

        - doc_ids 非空时按 doc_id 过滤（folder/tag 隔离）
        """
        self.ensure_collection()
        expr = None
        if doc_ids is not None:
            if not doc_ids:
                return []
            ids_str = ", ".join(f'"{d}"' for d in doc_ids)
            expr = f"doc_id in [{ids_str}]"

        search_params = {"metric_type": "COSINE", "params": {"nprobe": 16}}
        results = self._client.search(
            collection_name=self.collection_name,
            data=[query_embedding.tolist()],
            anns_field="dense_vector",
            search_params=search_params,
            limit=top_k,
            filter=expr,
            output_fields=["id", "meta_id", "doc_id", "text", "metadata"],
        )

        return [
            {
                "meta_id": hit["entity"].get("meta_id", ""),
                "doc_id": hit["entity"].get("doc_id", ""),
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
        res = self._client.query(
            collection_name=self.collection_name,
            filter="id != ''",
            output_fields=["count(*)"],
        )
        return res[0]["count(*)"] if res else 0
