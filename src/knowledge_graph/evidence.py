"""Evidence data model — atomic knowledge facts extracted from Chunks."""

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Optional


def make_entity_key(entity_type: str, name: str) -> str:
    return f"{entity_type.lower().strip()}:{name.strip()}"


def make_fact_key(subject_key: str, predicate: str, object_key: str) -> str:
    return f"{subject_key}|{predicate.upper().strip()}|{object_key}"


def make_entity_attr_key(entity_key: str, attr_key: str, attr_value: str) -> str:
    return f"{entity_key}|{attr_key.strip().lower()}|{attr_value.strip()}"


def make_fact_attr_key(fact_key: str, attr_key: str, attr_value: str) -> str:
    return f"{fact_key}|{attr_key.strip().lower()}|{attr_value.strip()}"


@dataclass
class Evidence:
    evidence_id: str
    chunk_hash: str
    evidence_type: str  # ENTITY | ENTITY_ATTRIBUTE | FACT | FACT_ATTRIBUTE
    confidence: float = 0.5
    evidence_text: str = ""
    extractor_version: str = ""
    active: bool = True

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "chunk_hash": self.chunk_hash,
            "evidence_type": self.evidence_type,
            "confidence": self.confidence,
            "evidence_text": self.evidence_text,
            "extractor_version": self.extractor_version,
            "active": self.active,
        }


@dataclass
class EntityEvidence(Evidence):
    entity_key: str = ""
    entity_name: str = ""
    entity_type: str = ""

    def __init__(
        self,
        chunk_hash: str,
        entity_name: str,
        entity_type: str = "Unknown",
        confidence: float = 0.5,
        evidence_text: str = "",
    ):
        entity_key = make_entity_key(entity_type, entity_name)
        super().__init__(
            evidence_id=f"ev_entity_{uuid.uuid4().hex[:12]}",
            chunk_hash=chunk_hash,
            evidence_type="ENTITY",
            confidence=confidence,
            evidence_text=evidence_text,
        )
        self.entity_key = entity_key
        self.entity_name = entity_name.strip()
        self.entity_type = entity_type.strip()

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "entity_key": self.entity_key,
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
        })
        return d

    @property
    def affected_key(self) -> str:
        return self.entity_key

    @property
    def affected_type(self) -> str:
        return "ENTITY"


@dataclass
class EntityAttributeEvidence(Evidence):
    entity_key: str = ""
    attr_key: str = ""
    attr_value: str = ""

    def __init__(
        self,
        chunk_hash: str,
        entity_key: str,
        attr_key: str,
        attr_value: str,
        confidence: float = 0.5,
        evidence_text: str = "",
    ):
        super().__init__(
            evidence_id=f"ev_entattr_{uuid.uuid4().hex[:12]}",
            chunk_hash=chunk_hash,
            evidence_type="ENTITY_ATTRIBUTE",
            confidence=confidence,
            evidence_text=evidence_text,
        )
        self.entity_key = entity_key
        self.attr_key = attr_key.strip().lower()
        self.attr_value = attr_value.strip()

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "entity_key": self.entity_key,
            "attr_key": self.attr_key,
            "attr_value": self.attr_value,
        })
        return d

    @property
    def affected_key(self) -> str:
        return make_entity_attr_key(self.entity_key, self.attr_key, self.attr_value)

    @property
    def affected_type(self) -> str:
        return "ENTITY_ATTRIBUTE"


@dataclass
class FactEvidence(Evidence):
    subject_key: str = ""
    subject_name: str = ""
    subject_type: str = ""
    predicate: str = ""
    object_key: str = ""
    object_name: str = ""
    object_type: str = ""

    def __init__(
        self,
        chunk_hash: str,
        subject_name: str,
        subject_type: str,
        predicate: str,
        object_name: str,
        object_type: str,
        confidence: float = 0.5,
        evidence_text: str = "",
    ):
        subject_key = make_entity_key(subject_type, subject_name)
        object_key = make_entity_key(object_type, object_name)
        super().__init__(
            evidence_id=f"ev_fact_{uuid.uuid4().hex[:12]}",
            chunk_hash=chunk_hash,
            evidence_type="FACT",
            confidence=confidence,
            evidence_text=evidence_text,
        )
        self.subject_key = subject_key
        self.subject_name = subject_name.strip()
        self.subject_type = subject_type.strip()
        self.predicate = predicate.upper().strip().replace(" ", "_")
        self.object_key = object_key
        self.object_name = object_name.strip()
        self.object_type = object_type.strip()

    @property
    def fact_key(self) -> str:
        return make_fact_key(self.subject_key, self.predicate, self.object_key)

    @property
    def affected_key(self) -> str:
        return self.fact_key

    @property
    def affected_type(self) -> str:
        return "FACT"

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "subject_key": self.subject_key,
            "subject_name": self.subject_name,
            "subject_type": self.subject_type,
            "predicate": self.predicate,
            "object_key": self.object_key,
            "object_name": self.object_name,
            "object_type": self.object_type,
        })
        return d


@dataclass
class FactAttributeEvidence(Evidence):
    subject_key: str = ""
    predicate: str = ""
    object_key: str = ""
    attr_key: str = ""
    attr_value: str = ""

    def __init__(
        self,
        chunk_hash: str,
        subject_key: str,
        predicate: str,
        object_key: str,
        attr_key: str,
        attr_value: str,
        confidence: float = 0.5,
        evidence_text: str = "",
    ):
        super().__init__(
            evidence_id=f"ev_factattr_{uuid.uuid4().hex[:12]}",
            chunk_hash=chunk_hash,
            evidence_type="FACT_ATTRIBUTE",
            confidence=confidence,
            evidence_text=evidence_text,
        )
        self.subject_key = subject_key
        self.predicate = predicate.upper().strip().replace(" ", "_")
        self.object_key = object_key
        self.attr_key = attr_key.strip().lower()
        self.attr_value = attr_value.strip()

    @property
    def fact_key(self) -> str:
        return make_fact_key(self.subject_key, self.predicate, self.object_key)

    @property
    def affected_key(self) -> str:
        return make_fact_attr_key(
            self.fact_key, self.attr_key, self.attr_value
        )

    @property
    def affected_type(self) -> str:
        return "FACT_ATTRIBUTE"

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "subject_key": self.subject_key,
            "predicate": self.predicate,
            "object_key": self.object_key,
            "attr_key": self.attr_key,
            "attr_value": self.attr_value,
        })
        return d


EVIDENCE_TYPES = ("ENTITY", "ENTITY_ATTRIBUTE", "FACT", "FACT_ATTRIBUTE")


def collect_affected_keys(evidence_items: list[Evidence]) -> dict[str, set[str]]:
    """Group affected keys by type for bulk GraphSyncTask generation."""
    result: dict[str, set[str]] = {}
    for ev in evidence_items:
        t = ev.affected_type
        k = ev.affected_key
        if t not in result:
            result[t] = set()
        result[t].add(k)
    return result
