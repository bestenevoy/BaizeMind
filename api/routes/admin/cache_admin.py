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
    """构造 cache 条目返回结构（列表用，截断预览）。

    LLM namespace（``llm:*``）的 value 是 JSON ``{content, input, input_preview, caller}``，
    列表里展示截断预览（200 字符），完整内容用详情接口 ``GET /cache/{key}`` 查看。
    """
    namespace = e.key.split(":", 1)[0] if ":" in e.key else ""
    raw = e.value

    if namespace == "llm":
        meta = _extract_llm_cache_meta(raw)
        content = _decode_llm_cache_value(raw)
        # 列表短预览：input_preview 取前 200 字符（meta 里已经是 400 字符，再截一次）
        # 详情接口返回完整 input
        return {
            "key": e.key,
            "namespace": namespace,
            "value_preview": _truncate(content),
            "value_length": len(content),
            "input_preview": _truncate(meta.get("input_preview", ""), 200),
            "input_length": meta.get("input_length", 0),
            "has_full_input": bool(meta.get("input")),  # 新格式有完整 input；旧格式为 False
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
        "input_length": 0,
        "has_full_input": False,
        "caller": "",
        "created_at": e.created_at,
        "expires_at": e.expires_at,
        "ttl_remaining": e.ttl_remaining,
    }


def _format_entry_detail(e) -> dict:
    """构造 cache 条目详情（完整内容，用于详情接口）。

    LLM namespace 返回完整 input 和 content，便于 debug 分析"给到 LLM 的实际上下文"。
    其他 namespace 与列表相同（无完整 input 概念）。
    """
    namespace = e.key.split(":", 1)[0] if ":" in e.key else ""
    raw = e.value

    if namespace == "llm":
        meta = _extract_llm_cache_meta(raw)
        content = _decode_llm_cache_value(raw)
        # 详情接口：优先返回完整 input；旧格式缓存没有 input 字段时回退到 input_preview
        full_input = meta.get("input", "") or meta.get("input_preview", "")
        return {
            "key": e.key,
            "namespace": namespace,
            "content": content,
            "content_length": len(content),
            "input": full_input,
            "input_length": meta.get("input_length", len(full_input)),
            "caller": meta.get("caller", ""),
            "created_at": e.created_at,
            "expires_at": e.expires_at,
            "ttl_remaining": e.ttl_remaining,
        }

    return {
        "key": e.key,
        "namespace": namespace,
        "content": raw,
        "content_length": len(raw),
        "input": "",
        "input_length": 0,
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


@router.get("/cache/{key}")
async def get_cache_entry(key: str, _: User = Depends(require_login)):
    """获取单个缓存条目详情（完整 input + content）。

    用于 cache panel 点击查看"给到 LLM 的实际上下文"，便于 debug 分析。
    LLM namespace 返回完整 input（含 system prompt + context + question）；
    其他 namespace 返回完整 value 字符串。

    ``key`` 是 :func:`make_key` 生成的完整 key（形如 ``namespace:hash``）。
    路径参数会自动 URL 解码；前端调用时需 ``encodeURIComponent``。
    """
    if not settings.cache_enabled:
        return {"enabled": False, "message": "缓存已全局禁用"}

    from src.cache import get_cache
    cache = get_cache()
    # 缓存后端没提供 get_entry 接口，用 entries() 过滤一次
    # （单条查询性能可接受，cache panel 是低频管理操作）
    for e in cache.entries():
        if e.key == key:
            return {"enabled": True, **_format_entry_detail(e)}
    return {"enabled": True, "message": "缓存条目不存在或已过期", "key": key}


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
