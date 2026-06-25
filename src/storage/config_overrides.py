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


def apply_overrides_to_settings() -> int:
    """启动时把持久化的 override 同步到 settings 对象。

    若不调用，settings 仍是 .env / 代码默认值，而 list_editable_config() 读
    override 文件 —— 两边不一致：检索流程用 settings（默认值），配置页显示
    override 文件值。本函数在模块导入时自动执行一次，确保所有入口
    （uvicorn / scripts）都把 override 应用到运行中的 settings。
    返回已应用的条目数。
    """
    overrides = load_overrides()
    applied = 0
    for key, value in overrides.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
            applied += 1
    return applied


# 模块导入时自动应用，确保服务启动后 settings 与 override 文件一致
apply_overrides_to_settings()
