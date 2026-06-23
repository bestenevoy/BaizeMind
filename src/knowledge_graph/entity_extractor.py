import json
import re

from src.llm.deepseek import get_chat_llm
from config.prompts import EVIDENCE_EXTRACTION_SYSTEM, EVIDENCE_EXTRACTION_EXAMPLE


class EntityExtractor:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm(temperature=0.1)
        return self._llm

    def extract_evidence(self, text: str, chunk_hash: str = "") -> list:
        from src.knowledge_graph.evidence import (
            EntityEvidence, EntityAttributeEvidence, FactEvidence, FactAttributeEvidence,
        )

        llm = self._get_llm()
        prompt = f"{EVIDENCE_EXTRACTION_SYSTEM}\n\nExample:\n{EVIDENCE_EXTRACTION_EXAMPLE}\n\nText: {text[:4000]}\n\nResponse:"
        resp = llm.invoke(prompt)
        data = self._parse_response(resp.content)

        items = []
        for item in data.get("evidence_items", []):
            etype = item.get("type", "").upper()
            conf = float(item.get("confidence", 0.5))
            ev_text = text[:200]

            if etype == "ENTITY":
                items.append(EntityEvidence(
                    chunk_hash=chunk_hash,
                    entity_name=item.get("entity_name", ""),
                    entity_type=item.get("entity_type", "Unknown"),
                    confidence=conf,
                    evidence_text=ev_text,
                ))
            elif etype == "ENTITY_ATTRIBUTE":
                items.append(EntityAttributeEvidence(
                    chunk_hash=chunk_hash,
                    entity_key=item.get("entity_key", ""),
                    attr_key=item.get("attr_key", ""),
                    attr_value=item.get("attr_value", ""),
                    confidence=conf,
                    evidence_text=ev_text,
                ))
            elif etype == "FACT":
                items.append(FactEvidence(
                    chunk_hash=chunk_hash,
                    subject_name=item.get("subject_name", ""),
                    subject_type=item.get("subject_type", "Unknown"),
                    predicate=item.get("predicate", ""),
                    object_name=item.get("object_name", ""),
                    object_type=item.get("object_type", "Unknown"),
                    confidence=conf,
                    evidence_text=ev_text,
                ))
            elif etype == "FACT_ATTRIBUTE":
                items.append(FactAttributeEvidence(
                    chunk_hash=chunk_hash,
                    subject_key=item.get("subject_key", ""),
                    predicate=item.get("predicate", ""),
                    object_key=item.get("object_key", ""),
                    attr_key=item.get("attr_key", ""),
                    attr_value=item.get("attr_value", ""),
                    confidence=conf,
                    evidence_text=ev_text,
                ))

        return items

    @staticmethod
    def _parse_response(content: str) -> dict:
        try:
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass
        return {"evidence_items": []}
