"""Integration tests for chunk manager and evidence pipeline — uses SQLite, no external services."""

import pytest
from datetime import datetime

from src.knowledge_graph.chunk_manager import (
    compute_chunk_hash, create_chunk, delete_document_chunks,
    build_sync_tasks,
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
    conn.execute("DELETE FROM chunk_content")
    conn.execute("DELETE FROM graph_sync_task")
    conn.commit()
    conn.close()
    yield


class TestChunkContentPerDoc:
    """每个文档独立拥有 chunk，不再跨文档 dedup。"""

    def test_create_new_chunk(self):
        text = "马云于1999年在杭州创立阿里巴巴。"
        doc_id = "doc_001"
        chunk_hash = create_chunk(text, doc_id=doc_id)
        content = doc_store.get_chunk_content(chunk_hash)
        assert content is not None
        assert content["text"] == text
        assert content["active"] == 1
        assert content["doc_id"] == doc_id

    def test_same_text_different_doc(self):
        """相同文本在不同文档中各自创建独立的 chunk。"""
        text = "阿里巴巴是中国最大的电商平台。"
        h1 = create_chunk(text, doc_id="doc_a")
        h2 = create_chunk(text, doc_id="doc_b")
        assert h1 != h2  # doc_id 参与 hash，文档间不冲突

    def test_same_doc_recreate_replaces(self):
        """同一文档同一文本重复 create —— INSERT OR REPLACE 覆盖。"""
        text = "阿里巴巴是中国最大的电商平台。"
        h1 = create_chunk(text, doc_id="doc_a")
        h2 = create_chunk(text, doc_id="doc_a")
        assert h1 == h2  # 同 doc + 同 text → 同 hash，覆盖

    def test_different_text_different_hash(self):
        h1 = create_chunk("hello world", doc_id="doc_x")
        h2 = create_chunk("hello world!", doc_id="doc_x")
        assert h1 != h2

    def test_delete_document_chunks(self):
        """删除文档时清理所有 chunk + 关联 evidence。"""
        doc_id = "doc_del"
        ch1 = create_chunk("Chunk A", doc_id=doc_id)
        ch2 = create_chunk("Chunk B", doc_id=doc_id)

        items = [EntityEvidence(ch1, "阿里巴巴", "Organization", 0.99)]
        write_evidence(ch1, items)

        assert get_support_count("ENTITY", entity_key="organization:阿里巴巴") == 1

        result = delete_document_chunks(doc_id)
        assert result["deleted_count"] == 2
        assert doc_store.get_chunk_content(ch1) is None
        assert doc_store.get_chunk_content(ch2) is None
        # evidence 被 deactivate
        assert get_support_count("ENTITY", entity_key="organization:阿里巴巴") == 0

    def test_delete_does_not_affect_other_docs(self):
        """删除文档不影响其他文档的 chunk。"""
        doc1, doc2 = "doc_keep", "doc_del"
        ch_keep = create_chunk("保留的chunk", doc_id=doc1)
        ch_del = create_chunk("待删除的chunk", doc_id=doc2)

        delete_document_chunks(doc2)
        assert doc_store.get_chunk_content(ch_keep) is not None
        assert doc_store.get_chunk_content(ch_del) is None


class TestEvidenceWrite:
    def test_write_entity_evidence(self):
        chunk_hash = create_chunk("马云是阿里巴巴的创始人。", doc_id="doc_e1")
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
        chunk_hash = create_chunk("马云创立了阿里巴巴。", doc_id="doc_e2")
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
        chunk_hash = create_chunk("阿里巴巴总部位于杭州。", doc_id="doc_e3")
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
        """不同文档的多个 chunk 各自贡献 evidence，support_count 累加。"""
        for i, text in enumerate([
            "阿里巴巴总部在杭州。",
            "阿里巴巴总部设在杭州。",
            "阿里巴巴总部位于杭州。",
        ]):
            ch = create_chunk(text, doc_id=f"doc_multi_{i}")
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
        chunk_hash = create_chunk("阿里巴巴总部位于杭州。", doc_id="doc_d1")
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
