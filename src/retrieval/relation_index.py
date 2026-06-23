"""LightRAG Relation Vector Index — stores relation embeddings in Milvus."""
import logging
from typing import Any, Optional

import numpy as np
from pymilvus import MilvusClient, DataType

from src.embeddings.bge_m3 import BGEM3Embedding
from config.settings import settings

logger = logging.getLogger(__name__)


class RelationIndex:
    """Vector index for knowledge graph relations.

    Each relation (subject + predicate + object) is embedded as a sentence and
    searchable. This enables Global Retrieval in LightRAG: finding thematic
    relation patterns across the entire knowledge graph.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        embedding: Optional[BGEM3Embedding] = None,
    ):
        self.host = host or settings.milvus_host
        self.port = port or settings.milvus_port
        self.collection_name = settings.lightrag_relation_collection
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
            schema.add_field("subject", DataType.VARCHAR, max_length=256)
            schema.add_field("predicate", DataType.VARCHAR, max_length=64)
            schema.add_field("object", DataType.VARCHAR, max_length=256)
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
            logger.info(f"Created relation index collection: {self.collection_name}")

    def build_from_neo4j(self) -> int:
        """Extract all relations from Neo4j, embed them, and insert into Milvus.
        Supports both legacy (:RELATES_TO) and new (:Fact) models."""
        from src.knowledge_graph.neo4j_manager import Neo4jManager

        self.ensure_collection()
        neo4j = Neo4jManager()
        neo4j.connect()

        relations = []
        seen = set()

        with neo4j._driver.session() as session:
            # Try new Fact model first
            try:
                result = session.run(
                    """
                    MATCH (f:Fact) WHERE f.active = true
                    OPTIONAL MATCH (s:Entity {entity_key: f.subject_key})
                    OPTIONAL MATCH (o:Entity {entity_key: f.object_key})
                    RETURN coalesce(s.name, f.subject_key) AS subject,
                           f.predicate AS predicate,
                           coalesce(o.name, f.object_key) AS object
                    """
                )
                for rec in result:
                    key = (rec["subject"], rec["predicate"], rec["object"])
                    if key not in seen:
                        seen.add(key)
                        relations.append(dict(rec))
            except Exception:
                pass

            # Fallback: legacy RELATES_TO model
            if not relations:
                result = session.run(
                    """
                    MATCH (s:Entity)-[r:RELATES_TO]->(o:Entity)
                    RETURN s.name AS subject, r.type AS predicate, o.name AS object
                    """
                )
                for rec in result:
                    key = (rec["subject"], rec["predicate"], rec["object"])
                    if key not in seen:
                        seen.add(key)
                        relations.append(dict(rec))

        if not relations:
            logger.info("No relations found in Neo4j. Build the knowledge graph first.")
            return 0

        texts = []
        records = []
        for rel in relations:
            subj = rel["subject"]
            pred = rel["predicate"]
            objj = rel["object"]
            text = f"{subj} {pred} {objj}"
            texts.append(text)
            records.append({
                "id": f"rel:{subj}|{pred}|{objj}",
                "subject": subj,
                "predicate": pred,
                "object": objj,
                "text": text,
                "metadata": {},
            })

        embeddings = self._embed(records, texts)
        self._insert(records, embeddings)
        logger.info(f"Relation index built: {len(records)} relations")
        return len(records)

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """Retrieve relations by semantic similarity to the query."""
        self.ensure_collection()
        query_vec = self._embedding.encode_query_dense(query)

        search_params = {"metric_type": "COSINE", "params": {"nprobe": 16}}
        results = self._client.search(
            collection_name=self.collection_name,
            data=[query_vec.tolist()],
            anns_field="dense_vector",
            search_params=search_params,
            limit=top_k,
            output_fields=["id", "subject", "predicate", "object", "metadata"],
        )

        return [
            {
                "subject": hit["entity"].get("subject", ""),
                "predicate": hit["entity"].get("predicate", ""),
                "object": hit["entity"].get("object", ""),
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
                "subject": rec["subject"],
                "predicate": rec["predicate"],
                "object": rec["object"],
                "text": rec["text"],
                "dense_vector": embeddings[i].tolist(),
                "metadata": rec["metadata"],
            })
        self._client.insert(collection_name=self.collection_name, data=data)
        self._client.flush(self.collection_name)

    def upsert_relation(self, subject: str, predicate: str, object_: str):
        """Single relation upsert into Milvus (for incremental updates)."""
        self.ensure_collection()
        text = f"{subject} {predicate} {object_}"
        record = {
            "id": f"rel:{subject}|{predicate}|{object_}",
            "subject": subject,
            "predicate": predicate,
            "object": object_,
            "text": text,
            "metadata": {},
        }
        embedding = self._embedding.encode_dense([text])
        self._insert([record], embedding)

    def delete_relation(self, fact_key: str):
        """Delete a single relation from Milvus."""
        self.ensure_collection()
        if not self._client.has_collection(self.collection_name):
            return
        self._client.delete(
            collection_name=self.collection_name,
            filter=f'id == "rel:{fact_key}"',
        )

    def build_from_evidence(self) -> int:
        """Build relation index from SQLite Evidence (instead of Neo4j)."""
        from src.storage import doc_store

        self.ensure_collection()
        conn = doc_store._get_conn()
        rows = conn.execute(
            """SELECT DISTINCT subject_key, predicate, object_key,
                      subject_name, object_name
               FROM evidence WHERE active = 1 AND evidence_type = 'FACT'"""
        ).fetchall()
        conn.close()

        relations = []
        seen = set()
        for r in rows:
            d = dict(r)
            key = (d["subject_name"], d["predicate"], d["object_name"])
            if key not in seen:
                seen.add(key)
                relations.append(d)

        if not relations:
            logger.info("No active FACT evidence found.")
            return 0

        texts = []
        records = []
        for rel in relations:
            subj = rel.get("subject_name", rel["subject_key"])
            pred = rel["predicate"]
            objj = rel.get("object_name", rel["object_key"])
            text = f"{subj} {pred} {objj}"
            texts.append(text)
            records.append({
                "id": f"rel:{subj}|{pred}|{objj}",
                "subject": subj,
                "predicate": pred,
                "object": objj,
                "text": text,
                "metadata": {},
            })

        embeddings = self._embed(records, texts)
        self._insert(records, embeddings)
        logger.info(f"Relation index built from evidence: {len(records)} relations")
        return len(records)

    def clear(self):
        self.ensure_collection()
        if self._client.has_collection(self.collection_name):
            self._client.drop_collection(self.collection_name)
            logger.info(f"Dropped relation index collection: {self.collection_name}")

    def count(self) -> int:
        self.ensure_collection()
        if not self._client.has_collection(self.collection_name):
            return 0
        return self._client.get_collection_stats(self.collection_name).get("row_count", 0)
