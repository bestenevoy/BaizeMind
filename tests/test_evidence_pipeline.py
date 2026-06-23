"""Integration tests for chunk manager and evidence pipeline — uses SQLite, no external services."""

import pytest
from datetime import datetime

from src.knowledge_graph.chunk_manager import (
    compute_chunk_hash, create_or_reuse_chunk, update_document_refs,
    build_sync_tasks, process_chunk_ref_one_to_zero, process_chunk_ref_zero_to_one,
)
from src.knowledge_graph.evidence import (
    EntityEvidence, FactEvidence, EntityAttributeEvidence,
)
from src.knowledge_graph.evidence_writer import (
    write_evidence, deactivate_chunk_evidence, get_support_count,
)
from src.storage import doc_store


@pytest.fixture(autouse=True)
def clean_evidence_tables():
    conn = doc_store._get_conn()
    conn.execute("DELETE FROM evidence")
    conn.execute("DELETE FROM doc_chunk_ref")
    conn.execute("DELETE FROM chunk_content")
    conn.execute("DELETE FROM graph_sync_task")
    conn.commit()
    conn.close()
    yield


class TestChunkContentDedup:
    def test_create_new_chunk(self):
        text = "马云于1999年在杭州创立阿里巴巴。"
        chunk_hash, is_new = create_or_reuse_chunk(text)
        assert is_new is True
        content = doc_store.get_chunk_content(chunk_hash)
        assert content is not None
        assert content["text"] == text
        assert content["active"] == 1

    def test_reuse_existing_chunk(self):
        text = "阿里巴巴是中国最大的电商平台。"
        h1, is_new1 = create_or_reuse_chunk(text)
        h2, is_new2 = create_or_reuse_chunk(text)
        assert is_new1 is True
        assert is_new2 is False
        assert h1 == h2

    def test_different_text_different_hash(self):
        h1, _ = create_or_reuse_chunk("hello world")
        h2, _ = create_or_reuse_chunk("hello world!")
        assert h1 != h2


class TestDocChunkRefManagement:
    def test_mark_and_sweep_new_doc(self):
        doc_id = "test_doc_001"
        chunks = [
            {"text": "Chunk A: 杭州是浙江省省会。", "chunk_index": 0},
            {"text": "Chunk B: 阿里巴巴总部位于杭州。", "chunk_index": 1},
        ]
        # Don't pre-create — let update_document_refs handle ChunkContent creation
        result = update_document_refs(doc_id, 1, chunks)
        assert len(result["new_chunk_hashes"]) == 2
        assert result["stale_chunk_hashes"] == []
        assert result["zero_ref_hashes"] == []

        refs = doc_store.get_doc_chunk_refs(doc_id)
        assert len(refs) == 2

    def test_mark_and_sweep_update(self):
        doc_id = "test_doc_002"
        version1_chunks = [
            {"text": "Chunk A: original content v1", "chunk_index": 0},
            {"text": "Chunk B: also original v1", "chunk_index": 1},
        ]
        result1 = update_document_refs(doc_id, 1, version1_chunks)
        assert len(doc_store.get_doc_chunk_refs(doc_id)) == 2

        version2_chunks = [
            {"text": "Chunk A: original content v1", "chunk_index": 0},
            {"text": "Chunk C: new updated content v2", "chunk_index": 1},
        ]
        result2 = update_document_refs(doc_id, 2, version2_chunks)

        assert len(result2["new_chunk_hashes"]) == 1
        assert len(result2["stale_chunk_hashes"]) == 2  # both v1 refs deactivated

        refs = doc_store.get_doc_chunk_refs(doc_id, 2)
        assert len(refs) == 2


class TestEvidenceWrite:
    def test_write_entity_evidence(self):
        chunk_hash, _ = create_or_reuse_chunk("马云是阿里巴巴的创始人。")
        items = [
            EntityEvidence(chunk_hash, "马云", "Person", 0.99),
            EntityEvidence(chunk_hash, "阿里巴巴", "Organization", 0.99),
        ]
        result = write_evidence(chunk_hash, items)
        assert result["count"] == 2
        assert "ENTITY" in result["affected_keys"]

        count = get_support_count("ENTITY", entity_key="person:马云")
        assert count == 1

    def test_write_fact_evidence(self):
        chunk_hash, _ = create_or_reuse_chunk("马云创立了阿里巴巴。")
        items = [
            EntityEvidence(chunk_hash, "马云", "Person", 0.99),
            EntityEvidence(chunk_hash, "阿里巴巴", "Organization", 0.99),
            FactEvidence(chunk_hash, "马云", "Person", "FOUNDED", "阿里巴巴", "Organization", 0.98),
        ]
        result = write_evidence(chunk_hash, items)
        assert result["count"] == 3

        count = get_support_count("FACT", subject_key="person:马云", predicate="FOUNDED", object_key="organization:阿里巴巴")
        assert count == 1

    def test_entity_attribute_evidence(self):
        chunk_hash, _ = create_or_reuse_chunk("阿里巴巴总部位于杭州。")
        items = [
            EntityEvidence(chunk_hash, "阿里巴巴", "Organization", 0.99),
            EntityAttributeEvidence(chunk_hash, "organization:阿里巴巴", "headquarter", "杭州", 0.95),
        ]
        result = write_evidence(chunk_hash, items)
        assert result["count"] == 2

        count = get_support_count(
            "ENTITY_ATTRIBUTE", entity_key="organization:阿里巴巴", attr_key="headquarter", attr_value="杭州"
        )
        assert count == 1

    def test_support_count_multiple_evidence(self):
        for i, text in enumerate([
            "阿里巴巴总部在杭州。",
            "阿里巴巴总部设在杭州。",
            "阿里巴巴总部位于杭州。",
        ]):
            ch, _ = create_or_reuse_chunk(text)
            items = [
                EntityAttributeEvidence(ch, "organization:阿里巴巴", "headquarter", "杭州", 0.9),
            ]
            write_evidence(ch, items)

        count = get_support_count(
            "ENTITY_ATTRIBUTE", entity_key="organization:阿里巴巴", attr_key="headquarter", attr_value="杭州"
        )
        assert count == 3


class TestEvidenceDeactivate:
    def test_deactivate_and_recount(self):
        chunk_hash, _ = create_or_reuse_chunk("阿里巴巴总部位于杭州。")
        items = [
            EntityEvidence(chunk_hash, "阿里巴巴", "Organization", 0.99),
            EntityAttributeEvidence(chunk_hash, "organization:阿里巴巴", "headquarter", "杭州", 0.95),
        ]
        write_evidence(chunk_hash, items)

        assert get_support_count("ENTITY", entity_key="organization:阿里巴巴") == 1
        assert get_support_count("ENTITY_ATTRIBUTE", entity_key="organization:阿里巴巴", attr_key="headquarter", attr_value="杭州") == 1

        affected = deactivate_chunk_evidence(chunk_hash)
        assert len(affected) == 2

        assert get_support_count("ENTITY", entity_key="organization:阿里巴巴") == 0
        assert get_support_count("ENTITY_ATTRIBUTE", entity_key="organization:阿里巴巴", attr_key="headquarter", attr_value="杭州") == 0


class TestProcessRefCountChanges:
    def test_one_to_zero_deactivates_evidence(self):
        chunk_hash, _ = create_or_reuse_chunk("阿里巴巴总部位于杭州。")
        items = [EntityEvidence(chunk_hash, "阿里巴巴", "Organization", 0.99)]
        write_evidence(chunk_hash, items)

        assert get_support_count("ENTITY", entity_key="organization:阿里巴巴") == 1

        affected = process_chunk_ref_one_to_zero(chunk_hash)
        assert len(affected) >= 1
        assert get_support_count("ENTITY", entity_key="organization:阿里巴巴") == 0

    def test_zero_to_one_reactivates_evidence(self):
        chunk_hash, _ = create_or_reuse_chunk("阿里巴巴总部位于杭州。")
        items = [EntityEvidence(chunk_hash, "阿里巴巴", "Organization", 0.99)]
        write_evidence(chunk_hash, items)
        deactivate_chunk_evidence(chunk_hash)
        assert get_support_count("ENTITY", entity_key="organization:阿里巴巴") == 0

        affected = process_chunk_ref_zero_to_one(chunk_hash)
        assert len(affected) >= 1
        assert get_support_count("ENTITY", entity_key="organization:阿里巴巴") == 1


class TestSyncTasks:
    def test_build_and_store_sync_tasks(self):
        affected = {
            "ENTITY": {"person:马云", "company:阿里巴巴"},
            "FACT": {"person:马云|FOUNDED|company:阿里巴巴"},
        }
        tasks = build_sync_tasks(affected, doc_id="doc_test", doc_version=1)
        count = doc_store.create_sync_tasks_batch(tasks)
        assert count == 3

        pending = doc_store.get_pending_sync_tasks(limit=10)
        assert len(pending) == 3
        assert all(t["status"] == "PENDING" for t in pending)

        doc_store.mark_sync_task_status(pending[0]["task_id"], "SUCCESS")
        pending2 = doc_store.get_pending_sync_tasks(limit=10)
        assert len(pending2) == 2
