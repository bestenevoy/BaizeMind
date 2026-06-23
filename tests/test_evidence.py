"""Unit tests for the evidence pipeline — safe offline, no external services."""

import pytest

from src.knowledge_graph.evidence import (
    EntityEvidence, EntityAttributeEvidence, FactEvidence, FactAttributeEvidence,
    make_entity_key, make_fact_key, make_entity_attr_key, make_fact_attr_key,
    collect_affected_keys,
)
from src.knowledge_graph.chunk_manager import (
    compute_chunk_hash, create_or_reuse_chunk, build_sync_tasks,
)


class TestEvidenceKeys:
    def test_entity_key(self):
        assert make_entity_key("Person", "马云") == "person:马云"
        assert make_entity_key("  Organization  ", " 阿里巴巴 ") == "organization:阿里巴巴"
        assert make_entity_key("Location", "杭州") == "location:杭州"

    def test_fact_key(self):
        key = make_fact_key("person:马云", "FOUNDED", "company:阿里巴巴")
        assert key == "person:马云|FOUNDED|company:阿里巴巴"
        key2 = make_fact_key("person:马云", " founded ", "company:阿里巴巴")
        assert key2 == "person:马云|FOUNDED|company:阿里巴巴"

    def test_entity_attr_key(self):
        key = make_entity_attr_key("company:阿里巴巴", "HeadQuarter", "杭州")
        assert key == "company:阿里巴巴|headquarter|杭州"

    def test_fact_attr_key(self):
        key = make_fact_attr_key("person:马云|FOUNDED|company:阿里巴巴", "Year", "1999")
        assert key == "person:马云|FOUNDED|company:阿里巴巴|year|1999"


class TestEntityEvidence:
    def test_create(self):
        ev = EntityEvidence("chunk_001", "马云", "Person", confidence=0.98)
        assert ev.evidence_type == "ENTITY"
        assert ev.entity_key == "person:马云"
        assert ev.entity_name == "马云"
        assert ev.entity_type == "Person"
        assert ev.confidence == 0.98
        assert ev.affected_key == "person:马云"
        assert ev.affected_type == "ENTITY"

    def test_to_dict(self):
        ev = EntityEvidence("chunk_001", "阿里巴巴", "Organization", confidence=0.95)
        d = ev.to_dict()
        assert d["evidence_type"] == "ENTITY"
        assert d["entity_key"] == "organization:阿里巴巴"
        assert d["entity_name"] == "阿里巴巴"
        assert d["confidence"] == 0.95
        assert d["active"] is True


class TestEntityAttributeEvidence:
    def test_create(self):
        ev = EntityAttributeEvidence("chunk_001", "company:阿里巴巴", "headquarter", "杭州", confidence=0.95)
        assert ev.evidence_type == "ENTITY_ATTRIBUTE"
        assert ev.entity_key == "company:阿里巴巴"
        assert ev.attr_key == "headquarter"
        assert ev.attr_value == "杭州"
        assert ev.affected_key == "company:阿里巴巴|headquarter|杭州"
        assert ev.affected_type == "ENTITY_ATTRIBUTE"


class TestFactEvidence:
    def test_create(self):
        ev = FactEvidence("chunk_001", "马云", "Person", "FOUNDED", "阿里巴巴", "Organization", confidence=0.96)
        assert ev.evidence_type == "FACT"
        assert ev.subject_key == "person:马云"
        assert ev.predicate == "FOUNDED"
        assert ev.object_key == "organization:阿里巴巴"
        assert ev.fact_key == "person:马云|FOUNDED|organization:阿里巴巴"
        assert ev.affected_key == "person:马云|FOUNDED|organization:阿里巴巴"
        assert ev.affected_type == "FACT"

    def test_predicate_normalization(self):
        ev = FactEvidence("chunk_002", "Alice", "Person", "works for", "OpenAI", "Organization")
        assert ev.predicate == "WORKS_FOR"

    def test_to_dict(self):
        ev = FactEvidence("chunk_001", "马云", "Person", "FOUNDED", "阿里巴巴", "Organization", confidence=0.96)
        d = ev.to_dict()
        assert d["subject_key"] == "person:马云"
        assert d["predicate"] == "FOUNDED"
        assert d["object_key"] == "organization:阿里巴巴"


class TestFactAttributeEvidence:
    def test_create(self):
        ev = FactAttributeEvidence(
            "chunk_001",
            subject_key="person:马云",
            predicate="FOUNDED",
            object_key="company:阿里巴巴",
            attr_key="year",
            attr_value="1999",
            confidence=0.94,
        )
        assert ev.evidence_type == "FACT_ATTRIBUTE"
        assert ev.fact_key == "person:马云|FOUNDED|company:阿里巴巴"
        assert ev.affected_key == "person:马云|FOUNDED|company:阿里巴巴|year|1999"
        assert ev.affected_type == "FACT_ATTRIBUTE"


class TestCollectAffectedKeys:
    def test_mixed_evidence(self):
        items = [
            EntityEvidence("c1", "马云", "Person"),
            EntityEvidence("c1", "阿里巴巴", "Organization"),
            FactEvidence("c1", "马云", "Person", "FOUNDED", "阿里巴巴", "Organization"),
            EntityAttributeEvidence("c1", "company:阿里巴巴", "headquarter", "杭州"),
        ]
        result = collect_affected_keys(items)
        assert "ENTITY" in result
        assert result["ENTITY"] == {"person:马云", "organization:阿里巴巴"}
        assert "FACT" in result
        assert result["FACT"] == {"person:马云|FOUNDED|organization:阿里巴巴"}
        assert "ENTITY_ATTRIBUTE" in result
        assert result["ENTITY_ATTRIBUTE"] == {"company:阿里巴巴|headquarter|杭州"}

    def test_empty(self):
        assert collect_affected_keys([]) == {}


class TestChunkHash:
    def test_deterministic(self):
        h1 = compute_chunk_hash("hello world")
        h2 = compute_chunk_hash("hello world")
        assert h1 == h2
        assert len(h1) == 32

    def test_different_content(self):
        h1 = compute_chunk_hash("hello world")
        h2 = compute_chunk_hash("hello world!")
        assert h1 != h2


class TestBuildSyncTasks:
    def test_basic(self):
        affected = {
            "ENTITY": {"person:马云", "company:阿里巴巴"},
            "FACT": {"person:马云|FOUNDED|company:阿里巴巴"},
        }
        tasks = build_sync_tasks(affected, doc_id="doc123", doc_version=2)
        assert len(tasks) == 3
        entity_tasks = [t for t in tasks if t["affected_type"] == "ENTITY"]
        fact_tasks = [t for t in tasks if t["affected_type"] == "FACT"]
        assert len(entity_tasks) == 2
        assert len(fact_tasks) == 1
        assert all(t["doc_id"] == "doc123" for t in tasks)
        assert all(t["doc_version"] == 2 for t in tasks)
        assert all(t["operation"] == "UPSERT" for t in tasks)

    def test_empty(self):
        tasks = build_sync_tasks({})
        assert tasks == []
