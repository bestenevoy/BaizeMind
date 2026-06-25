"""缓存后端工厂 + 注册表。

新增后端的步骤：
1. 实现 ``src/cache/base.py`` 中的 :class:`CacheBackend`。
2. 在 ``_BACKEND_BUILDERS`` 注册一个构造函数。
3. 在 ``config/settings.py`` 的 ``cache_backend`` 注释里加上新选项。

通过 :func:`get_cache` 拿到的实例单例化（按 backend 名缓存），避免反复建连接。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Callable

from config.settings import settings
from src.cache.base import CacheBackend
from src.cache.memory import MemoryCache
from src.cache.sqlite_backend import SQLiteCache


# backend name -> 构造函数(default_ttl) -> CacheBackend
_BACKEND_BUILDERS: dict[str, Callable[[int | None], CacheBackend]] = {
    "memory": lambda ttl: MemoryCache(default_ttl=ttl),
    "sqlite": lambda ttl: SQLiteCache(
        db_path=settings.cache_db_path, default_ttl=ttl
    ),
}


@lru_cache(maxsize=None)
def get_cache(backend: str | None = None) -> CacheBackend:
    """返回指定后端的单例。

    ``backend`` 为 None 时使用 ``settings.cache_backend``。
    未知后端会回退到 memory 并记录 warning（避免线上配置笔误直接崩溃）。
    """
    import logging

    name = backend or settings.cache_backend
    builder = _BACKEND_BUILDERS.get(name)
    if builder is None:
        logging.getLogger(__name__).warning(
            "Unknown cache backend %r, falling back to 'memory'", name
        )
        builder = _BACKEND_BUILDERS["memory"]
    return builder(settings.cache_ttl_seconds)


def register_backend(name: str, builder: Callable[[int | None], CacheBackend]) -> None:
    """运行时注册新后端（用于插件式扩展，例如 Redis）。"""
    _BACKEND_BUILDERS[name] = builder
    get_cache.cache_clear()  # 让下次 get_cache 重新构造
