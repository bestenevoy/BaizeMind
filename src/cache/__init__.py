"""通用缓存模块。

对外暴露：
- :class:`CacheBackend`  — 后端抽象接口
- :func:`get_cache`      — 按 settings.cache_backend 拿单例
- :func:`make_key`       — 生成稳定 key
- :func:`cached`         — 装饰器，给纯函数加缓存
"""
from __future__ import annotations

import functools
import json
from typing import Any, Callable

from config.settings import settings
from src.cache.base import CacheBackend, make_key
from src.cache.factory import get_cache, register_backend
from src.cache.memory import MemoryCache
from src.cache.sqlite_backend import SQLiteCache

__all__ = [
    "CacheBackend",
    "get_cache",
    "register_backend",
    "make_key",
    "MemoryCache",
    "SQLiteCache",
    "cached",
]


def cached(
    namespace: str,
    key_fn: Callable[[tuple, dict], tuple[str, ...]] | None = None,
    ttl: int | None = None,
    backend: str | None = None,
    enabled_flag: Callable[[], bool] | None = None,
):
    """装饰器：给函数返回值加缓存。

    参数：
        namespace:    key 前缀，区分不同用途（如 "rewrite"）
        key_fn:       自定义 key 生成函数 ``(args, kwargs) -> tuple[str, ...]``；
                      默认用所有位置+关键字参数 str 化
        ttl:          单次覆盖 TTL；None 用后端默认
        backend:      指定后端名；None 用 settings.cache_backend
        enabled_flag: 额外开关回调，返回 False 时跳过缓存
                      （如 ``lambda: settings.cache_query_rewrite_enabled``）

    被装饰函数的返回值必须可 JSON 序列化。
    """
    def decorator(func: Callable[..., Any]):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not settings.cache_enabled:
                return func(*args, **kwargs)
            if enabled_flag is not None and not enabled_flag():
                return func(*args, **kwargs)

            cache = get_cache(backend)
            if key_fn is not None:
                parts = key_fn(args, kwargs)
            else:
                parts = (
                    tuple(str(a) for a in args)
                    + tuple(f"{k}={v}" for k, v in sorted(kwargs.items()))
                )
            key = make_key(namespace, *parts)

            hit = cache.get(key)
            if hit is not None:
                try:
                    return json.loads(hit)
                except (json.JSONDecodeError, ValueError):
                    pass  # 损坏的条目，按 miss 处理

            value = func(*args, **kwargs)
            try:
                cache.set(key, json.dumps(value, ensure_ascii=False), ttl=ttl)
            except (TypeError, ValueError):
                pass  # 不可序列化的值不缓存，但不影响函数正常返回
            return value

        wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
        return wrapper

    def cache_clear():
        get_cache(backend).clear()

    return decorator
