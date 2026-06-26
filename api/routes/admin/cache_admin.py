"""缓存管理路由：列出 / 清空 / 删除单条缓存。

从 management.py 拆分而来，统一挂在 /api/v1/system 前缀下。
用于配置页"缓存"tab，以及方便运维验证 cache 是否生效。
"""
from fastapi import APIRouter, Depends

from config.settings import settings
from src.auth import User, require_admin, require_login
from src.llm.cached_wrapper import _decode_llm_cache_value, _extract_llm_cache_meta

router = APIRouter(prefix="/api/v1/system", tags=["system"])


def _truncate(s: str, n: int = 200) -> str:
    return s if len(s) <= n else s[:n] + "..."


def _format_entry(e) -> dict:
    """构造 cache 条目返回结构。

    LLM namespace（``llm:*``）的 value 是 JSON ``{content, input_preview, caller}``，
    这里把它解包：value_preview 显示真实 content（响应），并额外提供 input_preview
    和 caller 字段方便定位"是哪个 query 触发的"。
    """
    namespace = e.key.split(":", 1)[0] if ":" in e.key else ""
    raw = e.value

    if namespace == "llm":
        meta = _extract_llm_cache_meta(raw)
        content = _decode_llm_cache_value(raw)
        return {
            "key": e.key,
            "namespace": namespace,
            "value_preview": _truncate(content),
            "value_length": len(content),
            "input_preview": _truncate(meta.get("input_preview", ""), 400),
            "caller": meta.get("caller", ""),
            "created_at": e.created_at,
            "expires_at": e.expires_at,
            "ttl_remaining": e.ttl_remaining,
        }

    # 其他 namespace（emb / rerank）：value 直接是字符串
    return {
        "key": e.key,
        "namespace": namespace,
        "value_preview": _truncate(raw),
        "value_length": len(raw),
        "input_preview": "",
        "caller": "",
        "created_at": e.created_at,
        "expires_at": e.expires_at,
        "ttl_remaining": e.ttl_remaining,
    }


@router.get("/cache")
async def list_cache(prefix: str | None = None, _: User = Depends(require_login)):
    """列出缓存条目。

    Query 参数：
        prefix: 按 key 前缀过滤（如 ``query_rewrite``）；默认返回全部

    返回值包含后端信息、配置、条目列表（值截断预览 + TTL 剩余）。
    """
    if not settings.cache_enabled:
        return {
            "enabled": False,
            "backend": settings.cache_backend,
            "ttl_seconds": settings.cache_ttl_seconds,
            "total": 0,
            "filtered_total": 0,
            "filtered_prefix": prefix,
            "namespaces": {},
            "entries": [],
            "message": "cache_enabled=False, 缓存已全局禁用",
        }

    from src.cache import get_cache
    cache = get_cache()
    entries = cache.entries(prefix=prefix)

    # namespaces 与 total 总是按全量计算（不受 prefix 影响），
    # 这样前端切换筛选时 namespace 按钮列表和"总条目"数字保持稳定。
    # filtered_total 才反映当前 prefix 过滤后的条目数。
    all_entries = cache.entries() if prefix is not None else entries
    namespace_counts: dict[str, int] = {}
    for e in all_entries:
        ns = e.key.split(":", 1)[0] if ":" in e.key else "(no-ns)"
        namespace_counts[ns] = namespace_counts.get(ns, 0) + 1

    return {
        "enabled": True,
        "backend": settings.cache_backend,
        "ttl_seconds": settings.cache_ttl_seconds,
        "total": len(all_entries),
        "filtered_total": len(entries),
        "filtered_prefix": prefix,
        "namespaces": namespace_counts,
        "entries": [_format_entry(e) for e in entries],
    }


@router.post("/cache/clear")
async def clear_cache(prefix: str | None = None, _: User = Depends(require_admin)):
    """清空缓存。

    Query 参数：
        prefix: 仅清除该 namespace 前缀的条目；默认清空全部
    """
    if not settings.cache_enabled:
        return {"success": False, "message": "缓存已全局禁用，无需清空"}

    from src.cache import get_cache
    cache = get_cache()

    if prefix is not None:
        # 按前缀删除：枚举后逐条 delete（后端未提供批量 prefix-delete 接口）
        entries = cache.entries(prefix=prefix)
        for e in entries:
            cache.delete(e.key)
        return {"success": True, "cleared": len(entries), "prefix": prefix}
    else:
        before = len(cache.entries())
        cache.clear()
        return {"success": True, "cleared": before, "prefix": None}


@router.delete("/cache/{key}")
async def delete_cache_entry(key: str, _: User = Depends(require_admin)):
    """删除单个缓存条目。

    ``key`` 是 :func:`make_key` 生成的完整 key（形如 ``namespace:hash``）。
    路径参数会自动 URL 解码；前端调用时需 ``encodeURIComponent``。
    """
    if not settings.cache_enabled:
        return {"success": False, "message": "缓存已全局禁用"}

    from src.cache import get_cache
    cache = get_cache()
    existed = cache.get(key) is not None
    cache.delete(key)
    return {"success": True, "existed": existed, "key": key}
