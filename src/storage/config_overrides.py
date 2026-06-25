import json
from pathlib import Path
from typing import Any, Optional

from config.settings import settings

OVERRIDES_PATH = Path(settings.data_dir) / "config_overrides.json"

_EDITABLE_KEYS = {
    "dense_vector_threshold",
    "reranker_score_threshold",
    "reranker_method",
    "chunk_size",
    "chunk_overlap",
    "hybrid_top_k",
    "hybrid_dense_weight",
    "hybrid_bm25_weight",
    "hybrid_rrf_k",
    "rrf_score_threshold",
    "retrieval_over_fetch_multiplier",
    "agent_max_iterations",
    "agent_temperature",
    "query_rewrite_enabled",
    "query_rewrite_language",
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
    # Coerce value to match the type of the default setting
    default = getattr(settings, key, None)
    if default is not None and not isinstance(value, type(default)):
        try:
            if isinstance(default, bool) and isinstance(value, str):
                value = value.lower() in ("true", "1", "yes")
            elif isinstance(default, int):
                value = int(float(value))
            elif isinstance(default, float):
                value = float(value)
        except (ValueError, TypeError):
            pass
    overrides = load_overrides()
    overrides[key] = value
    save_overrides(overrides)
    setattr(settings, key, value)
    return True


def list_editable_config() -> list[dict]:
    overrides = load_overrides()
    items = []
    for key in sorted(_EDITABLE_KEYS):
        current = overrides.get(key, getattr(settings, key, ""))
        items.append({"key": key, "value": str(current), "overridden": key in overrides})
    return items
