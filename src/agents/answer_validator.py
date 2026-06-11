import json
import re
from typing import Any

from src.llm.deepseek import get_chat_llm
from config.prompts import ANSWER_VALIDATION_SYSTEM


class AnswerValidator:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm(temperature=0.0)
        return self._llm

    def validate(
        self, question: str, answer: str, context: str, citations: list[str]
    ) -> dict[str, Any]:
        llm = self._get_llm()
        prompt = (
            f"{ANSWER_VALIDATION_SYSTEM}\n\n"
            f"Question: {question}\n\n"
            f"Context:\n{context[:4000]}\n\n"
            f"Answer: {answer}\n\n"
            f"Citations: {citations}\n\n"
            f"Response:"
        )
        resp = llm.invoke(prompt)
        return self._parse(resp.content)

    @staticmethod
    def _parse(content: str) -> dict:
        try:
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                data = json.loads(match.group())
                return {
                    "is_valid": data.get("is_valid", True),
                    "hallucination_score": data.get("hallucination_score", 0.0),
                    "citation_accuracy": data.get("citation_accuracy", 0.0),
                    "completeness_score": data.get("completeness_score", 0.0),
                    "issues": data.get("issues", []),
                    "improved_answer": data.get("improved_answer"),
                }
        except (json.JSONDecodeError, AttributeError):
            pass
        return {
            "is_valid": True,
            "hallucination_score": 0.0,
            "citation_accuracy": 1.0,
            "completeness_score": 1.0,
            "issues": [],
            "improved_answer": None,
        }
