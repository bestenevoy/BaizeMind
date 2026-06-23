"""知识图谱模块测试"""

import pytest
from src.knowledge_graph.entity_extractor import EntityExtractor, _parse_evidence_items


def test_entity_extractor_parse():
    extractor = EntityExtractor()
    result = extractor._parse_response('{"evidence_items": [{"type": "ENTITY", "entity_name": "Test", "entity_type": "Org"}]}')
    assert len(result["evidence_items"]) == 1
    assert result["evidence_items"][0]["entity_name"] == "Test"


def test_neo4j_manager_init():
    from src.knowledge_graph.neo4j_manager import Neo4jManager
    manager = Neo4jManager()
    assert manager is not None


class TestEvidenceParseItems:
    def test_normal_list(self):
        data = {"evidence_items": [{"type": "ENTITY", "entity_name": "Test"}]}
        items = _parse_evidence_items(data)
        assert len(items) == 1
        assert items[0]["entity_name"] == "Test"

    def test_empty(self):
        data = {}
        items = _parse_evidence_items(data)
        assert items == []

    def test_empty_list(self):
        data = {"evidence_items": []}
        items = _parse_evidence_items(data)
        assert items == []

    def test_single_dict(self):
        data = {"evidence_items": {"type": "ENTITY", "entity_name": "Single"}}
        items = _parse_evidence_items(data)
        assert len(items) == 1
        assert items[0]["entity_name"] == "Single"

    def test_items_is_string(self):
        data = {"evidence_items": '[{"type": "ENTITY", "entity_name": "Str"}]'}
        items = _parse_evidence_items(data)
        assert len(items) == 1
        assert items[0]["entity_name"] == "Str"

    def test_items_contain_string_items(self):
        data = {"evidence_items": [
            {"type": "ENTITY", "entity_name": "Normal"},
            '{"type": "FACT", "predicate": "FOUNDED"}',
        ]}
        items = _parse_evidence_items(data)
        assert len(items) == 2

    def test_items_not_list(self):
        assert _parse_evidence_items({"evidence_items": 123}) == []
        assert _parse_evidence_items({"evidence_items": None}) == []

    def test_broken_json_string(self):
        data = {"evidence_items": 'not valid json'}
        items = _parse_evidence_items(data)
        assert items == []

    def test_mixed_case_types(self):
        data = {"evidence_items": [
            {"type": "entity", "entity_name": "Lower"},
            {"type": "ENTITY", "entity_name": "Upper"},
            {"type": "fact", "predicate": "FOUNDED"},
        ]}
        items = _parse_evidence_items(data)
        assert len(items) == 3
        assert all(isinstance(it, dict) for it in items)

