import json
from pathlib import Path
from typing import Any, Optional

from config.settings import settings

OVERRIDES_PATH = Path(settings.data_dir) / "config_overrides.json"

_EDITABLE_KEYS = {
    "retrieval_similarity_threshold",
    "dense_vector_threshold",
    "reranker_score_threshold",
    "reranker_method",
    "chunk_size",
    "chunk_overlap",
    "hybrid_top_k",
    "hybrid_dense_weight",
    "hybrid_bm25_weight",
    "agent_max_iterations",
    "agent_temperature",
}


def load_overrides() -> dict[str, Any]:
    if OVERRIDES_PATH.exists():
        try:
            return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_overrides(overrides: dict[str, Any]) -> None:
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")


def get_override(key: str) -> Optional[Any]:
    overrides = load_overrides()
    return overrides.get(key)


def set_override(key: str, value: Any) -> bool:
    if key not in _EDITABLE_KEYS:
        return False
    overrides = load_overrides()
    overrides[key] = value
    save_overrides(overrides)
    # Patch the live settings object
    setattr(settings, key, value)
    return True


def list_editable_config() -> list[dict]:
    overrides = load_overrides()
    items = []
    for key in sorted(_EDITABLE_KEYS):
        current = overrides.get(key, getattr(settings, key, ""))
        items.append({"key": key, "value": str(current), "overridden": key in overrides})
    return items
