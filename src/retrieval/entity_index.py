"""LightRAG Entity Vector Index — stores entity embeddings in Milvus."""
import logging
from typing import Any, Optional

import numpy as np
from pymilvus import MilvusClient, DataType

from src.embeddings.bge_m3 import BGEM3Embedding
from config.settings import settings

logger = logging.getLogger(__name__)


class EntityIndex:
    """Vector index for knowledge graph entities.

    Each entity (name + type + description) is embedded and searchable.
    Query-time entity retrieval uses this index instead of LLM-based NER,
    enabling Retrieval-Driven Retrieval (LightRAG pattern).
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        embedding: Optional[BGEM3Embedding] = None,
    ):
        self.host = host or settings.milvus_host
        self.port = port or settings.milvus_port
        self.collection_name = settings.lightrag_entity_collection
        self._client: Optional[MilvusClient] = None
        self._embedding = embedding or BGEM3Embedding()

    def connect(self):
        if self._client is None:
            self._client = MilvusClient(uri=f"http://{self.host}:{self.port}")

    def ensure_collection(self):
        self.connect()
        if not self._client.has_collection(self.collection_name):
            schema = self._client.create_schema(
                auto_id=False, enable_dynamic_field=True
            )
            schema.add_field("id", DataType.VARCHAR, max_length=512, is_primary=True)
            schema.add_field("entity_name", DataType.VARCHAR, max_length=256)
            schema.add_field("entity_type", DataType.VARCHAR, max_length=64)
            schema.add_field("description", DataType.VARCHAR, max_length=65535)
            schema.add_field("text", DataType.VARCHAR, max_length=65535)
            schema.add_field("dense_vector", DataType.FLOAT_VECTOR, dim=self._embedding.dim)
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
            logger.info(f"Created entity index collection: {self.collection_name}")

    def build_from_neo4j(self) -> int:
        """Extract all entities from Neo4j, embed them, and insert into Milvus."""
        from src.knowledge_graph.neo4j_manager import Neo4jManager

        self.ensure_collection()
        neo4j = Neo4jManager()
        neo4j.connect()

        with neo4j._driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity)
                RETURN e.name AS name, e.type AS type, e.description AS description,
                       e.doc_id AS doc_id, e.chunk_id AS chunk_id
                """
            )
            entities = [dict(r) for r in result]

        if not entities:
            logger.info("No entities found in Neo4j. Build the knowledge graph first.")
            return 0

        texts = []
        records = []
        for e in entities:
            desc = e.get("description", "") or ""
            text = f"{e['name']}: {desc}" if desc else e["name"]
            texts.append(text)
            records.append({
                "id": f"entity:{e['name']}",
                "entity_name": e["name"],
                "entity_type": e.get("type", "Unknown"),
                "description": desc,
                "text": text,
                "metadata": {
                    "doc_id": e.get("doc_id", ""),
                    "chunk_id": e.get("chunk_id", ""),
                },
            })

        embeddings = self._embed(records, texts)
        self._insert(records, embeddings)
        logger.info(f"Entity index built: {len(records)} entities")
        return len(records)

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """Retrieve entities by semantic similarity to the query."""
        self.ensure_collection()
        query_vec = self._embedding.encode_query_dense(query)

        search_params = {"metric_type": "COSINE", "params": {"nprobe": 16}}
        results = self._client.search(
            collection_name=self.collection_name,
            data=[query_vec.tolist()],
            anns_field="dense_vector",
            search_params=search_params,
            limit=top_k,
            output_fields=["id", "entity_name", "entity_type", "description", "metadata"],
        )

        return [
            {
                "entity_name": hit["entity"].get("entity_name", ""),
                "entity_type": hit["entity"].get("entity_type", ""),
                "description": hit["entity"].get("description", ""),
                "score": float(hit["distance"]),
                "metadata": hit["entity"].get("metadata", {}),
            }
            for hits in results
            for hit in hits
        ]

    def _embed(self, records: list[dict], texts: list[str]) -> np.ndarray:
        batch_size = settings.bge_m3_batch_size
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            all_embeddings.append(self._embedding.encode_dense(batch))
        return np.concatenate(all_embeddings, axis=0) if all_embeddings else np.array([], dtype=np.float32)

    def _insert(self, records: list[dict], embeddings: np.ndarray):
        data = []
        for i, rec in enumerate(records):
            data.append({
                "id": rec["id"],
                "entity_name": rec["entity_name"],
                "entity_type": rec["entity_type"],
                "description": rec["description"],
                "text": rec["text"],
                "dense_vector": embeddings[i].tolist(),
                "metadata": rec["metadata"],
            })
        self._client.insert(collection_name=self.collection_name, data=data)
        self._client.flush(self.collection_name)

    def upsert_entity(self, entity_key: str, name: str, entity_type: str, description: str = ""):
        """Single entity upsert into Milvus (for incremental updates)."""
        self.ensure_collection()
        text = f"{name}: {description}" if description else name
        record = {
            "id": f"entity:{name}",
            "entity_name": name,
            "entity_type": entity_type,
            "description": description,
            "text": text,
            "metadata": {"entity_key": entity_key},
        }
        embedding = self._embedding.encode_dense([text])
        self._insert([record], embedding)

    def delete_entity(self, entity_key_or_name: str):
        """Delete a single entity from Milvus."""
        self.ensure_collection()
        if not self._client.has_collection(self.collection_name):
            return
        self._client.delete(
            collection_name=self.collection_name,
            filter=f'id == "entity:{entity_key_or_name}" or entity_name == "{entity_key_or_name}"',
        )

    def build_from_evidence(self) -> int:
        """Build entity index from SQLite Evidence (instead of Neo4j)."""
        from src.storage import doc_store

        self.ensure_collection()
        conn = doc_store._get_conn()
        rows = conn.execute(
            """SELECT DISTINCT entity_key, entity_name, entity_type
               FROM evidence WHERE active = 1 AND evidence_type = 'ENTITY'"""
        ).fetchall()
        conn.close()

        entities = [dict(r) for r in rows]
        if not entities:
            logger.info("No active ENTITY evidence found.")
            return 0

        texts = []
        records = []
        for e in entities:
            text = f"{e['entity_name']}: {e['entity_type']}"
            texts.append(text)
            records.append({
                "id": f"entity:{e['entity_name']}",
                "entity_name": e["entity_name"],
                "entity_type": e.get("entity_type", "Unknown"),
                "description": "",
                "text": text,
                "metadata": {"entity_key": e["entity_key"]},
            })

        embeddings = self._embed(records, texts)
        self._insert(records, embeddings)
        logger.info(f"Entity index built from evidence: {len(records)} entities")
        return len(records)

    def clear(self):
        self.ensure_collection()
        if self._client.has_collection(self.collection_name):
            self._client.drop_collection(self.collection_name)
            logger.info(f"Dropped entity index collection: {self.collection_name}")

    def count(self) -> int:
        self.ensure_collection()
        if not self._client.has_collection(self.collection_name):
            return 0
        return self._client.get_collection_stats(self.collection_name).get("row_count", 0)
