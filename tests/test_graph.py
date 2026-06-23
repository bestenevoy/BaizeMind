"""知识图谱模块测试"""


def test_entity_extractor_parse():
    from src.knowledge_graph.entity_extractor import EntityExtractor
    extractor = EntityExtractor()
    result = extractor._parse_response('{"evidence_items": [{"type": "ENTITY", "entity_name": "Test", "entity_type": "Org"}]}')
    assert len(result["evidence_items"]) == 1
    assert result["evidence_items"][0]["entity_name"] == "Test"


def test_neo4j_manager_init():
    from src.knowledge_graph.neo4j_manager import Neo4jManager
    manager = Neo4jManager()
    assert manager is not None
