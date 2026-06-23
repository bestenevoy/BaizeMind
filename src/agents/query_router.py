import json
import re
from typing import Any

from src.llm.deepseek import get_chat_llm
from config.prompts import QUERY_ROUTER_SYSTEM


class QueryRouter:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm(temperature=0.0)
        return self._llm

    def classify(self, query: str) -> dict[str, Any]:
        llm = self._get_llm()
        prompt = f"{QUERY_ROUTER_SYSTEM}\n\nUser Question: {query}\n\nResponse:"
        resp = llm.invoke(prompt)
        return self._parse(resp.content)

    @staticmethod
    def _parse(content: str) -> dict:
        try:
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                data = json.loads(match.group())
                query_type = data.get("query_type", "simple_fact")
                # [DISABLED] GraphRAG: holistic queries now fallback to retrieval path
                if query_type not in ("chitchat", "simple_fact", "multi_hop", "comparison", "definition"):
                    query_type = "simple_fact"
                return {
                    "query_type": query_type,
                    "confidence": data.get("confidence", 0.5),
                    "reasoning": data.get("reasoning", ""),
                    "graph_eligible": data.get("graph_eligible", False),
                }
        except (json.JSONDecodeError, AttributeError):
            pass
        return {"query_type": "simple_fact", "confidence": 0.3, "reasoning": "fallback classification", "graph_eligible": False}
