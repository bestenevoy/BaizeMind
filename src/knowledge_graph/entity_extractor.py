import json
import re
from typing import Any

from src.llm.deepseek import get_chat_llm
from config.prompts import ENTITY_RELATION_SYSTEM, ENTITY_RELATION_EXAMPLE


class EntityExtractor:
    def __init__(self, use_langextract: bool = False):
        self.use_langextract = use_langextract
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm(temperature=0.1)
        return self._llm

    def extract(self, text: str) -> dict[str, Any]:
        if self.use_langextract:
            return self._extract_with_langextract(text)
        return self._extract_with_llm(text)

    def _extract_with_llm(self, text: str) -> dict:
        llm = self._get_llm()
        prompt = f"{ENTITY_RELATION_SYSTEM}\n\nExample:\n{ENTITY_RELATION_EXAMPLE}\n\nText: {text[:4000]}\n\nResponse:"
        resp = llm.invoke(prompt)
        return self._parse_response(resp.content)

    def _extract_with_langextract(self, text: str) -> dict:
        import langextract as lx
        from langextract.factory import ModelConfig

        examples = [
            lx.data.ExampleData(
                text=ENTITY_RELATION_EXAMPLE.split('Text: "')[1].split('"')[0],
                extractions=[
                    lx.data.Extraction(extraction_class="entity", extraction_text="Apple Inc.",
                                       attributes={"type": "Organization", "description": "Technology company"}),
                    lx.data.Extraction(extraction_class="entity", extraction_text="Xnor.ai",
                                       attributes={"type": "Organization", "description": "AI startup"}),
                    lx.data.Extraction(extraction_class="entity", extraction_text="iOS",
                                       attributes={"type": "Product", "description": "Mobile operating system"}),
                    lx.data.Extraction(extraction_class="relation",
                                       extraction_text="Apple Inc. acquired Xnor.ai",
                                       attributes={"predicate": "acquired"}),
                    lx.data.Extraction(extraction_class="relation",
                                       extraction_text="Xnor.ai integrated into iOS",
                                       attributes={"predicate": "provides_technology_for"}),
                ],
            )
        ]

        from config.settings import settings
        result = lx.extract(
            text_or_documents=text,
            prompt_description="Extract entities (Person, Organization, Product, Technology, Document, Event, Concept, Location) and relations from enterprise documents.",
            examples=examples,
            config=ModelConfig(
                model_id=settings.deepseek_chat_model,
                provider="openai",
                provider_kwargs={"api_key": settings.deepseek_api_key, "base_url": settings.deepseek_base_url},
            ),
        )
        entities = []
        relations = []
        for ext in result.extractions:
            if ext.extraction_class == "entity":
                entities.append({"name": ext.extraction_text, **ext.attributes})
            elif ext.extraction_class == "relation":
                parts = ext.extraction_text.split(" - ", 1) if " - " in ext.extraction_text else [ext.extraction_text, ""]
                subject_obj = parts[0]
                relations.append({**ext.attributes, "text": ext.extraction_text, "subject_obj": subject_obj})
        return {"entities": entities, "relations": relations}

    @staticmethod
    def _parse_response(content: str) -> dict:
        try:
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass
        return {"entities": [], "relations": []}

    def extract_from_chunks(self, chunks: list[dict]) -> list[dict]:
        all_results = []
        seen_entities = set()

        for chunk in chunks:
            result = self.extract(chunk["text"][:4000])
            for entity in result.get("entities", []):
                if entity["name"] not in seen_entities:
                    seen_entities.add(entity["name"])
                    entity["chunk_id"] = chunk.get("chunk_id", "")
                    all_results.append(entity)
            for relation in result.get("relations", []):
                relation["chunk_id"] = chunk.get("chunk_id", "")
                all_results.append(relation)

        return all_results
