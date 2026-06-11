"""Agent模块测试"""


def test_query_router_classify():
    from src.agents.query_router import QueryRouter
    router = QueryRouter()
    result = router._parse('{"query_type": "simple_fact", "confidence": 0.9}')
    assert result["query_type"] == "simple_fact"
    assert result["confidence"] == 0.9


def test_answer_validator_parse():
    from src.agents.answer_validator import AnswerValidator
    validator = AnswerValidator()
    result = validator._parse('{"is_valid": true, "hallucination_score": 0.1, "citation_accuracy": 0.9}')
    assert result["is_valid"] is True
    assert result["hallucination_score"] == 0.1


def test_workflow_init():
    from src.agents.workflow import AgenticRAGWorkflow
    workflow = AgenticRAGWorkflow()
    assert workflow is not None
    assert workflow._graph is not None
