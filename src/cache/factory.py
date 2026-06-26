"""缓存后端工厂 + 注册表。

新增后端的步骤：
1. 实现 ``src/cache/base.py`` 中的 :class:`CacheBackend`。
2. 在 ``_BACKEND_BUILDERS`` 注册一个构造函数。
3. 在 ``config/settings.py`` 的 ``cache_backend`` 注释里加上新选项。

通过 :func:`get_cache` 拿到的实例单例化（按 backend 名缓存），避免反复建连接。
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Callable

from config.settings import settings
from src.cache.base import CacheBackend
from src.cache.garnet import GarnetCache
from src.cache.memory import MemoryCache
from src.cache.noop import NoopCache
from src.cache.sqlite_backend import SQLiteCache

logger = logging.getLogger(__name__)


# backend name -> 构造函数(default_ttl) -> CacheBackend
_BACKEND_BUILDERS: dict[str, Callable[[int | None], CacheBackend]] = {
    "memory": lambda ttl: MemoryCache(default_ttl=ttl),
    "sqlite": lambda ttl: SQLiteCache(
        db_path=settings.cache_db_path, default_ttl=ttl
    ),
    # garnet / redis 协议相同，等价使用
    "garnet": lambda ttl: GarnetCache(url=settings.garnet_url, default_ttl=ttl),
    "redis": lambda ttl: GarnetCache(url=settings.garnet_url, default_ttl=ttl),
    "none": lambda ttl: NoopCache(),
    "noop": lambda ttl: NoopCache(),
}


@lru_cache(maxsize=None)
def get_cache(backend: str | None = None) -> CacheBackend:
    """返回指定后端的单例。

    ``backend`` 为 None 时使用 ``settings.cache_backend``。
    未知后端会回退到 memory 并记录 warning（避免线上配置笔误直接崩溃）。
    """
    name = backend or settings.cache_backend
    builder = _BACKEND_BUILDERS.get(name)
    if builder is None:
        logger.warning("Unknown cache backend %r, falling back to 'memory'", name)
        builder = _BACKEND_BUILDERS["memory"]
    return builder(settings.cache_ttl_seconds)


def get_llm_cache() -> CacheBackend:
    """获取 LLM 响应缓存（与通用缓存共用同一实例，仅 make_key 前缀不同）。

    如果 settings.cache_enabled=False，返回 NoopCache。
    """
    if not settings.cache_enabled:
        return NoopCache()
    return get_cache()


def get_embedding_cache() -> CacheBackend:
    """获取 embedding 缓存（与 LLM 共用底层实例，仅 make_key 前缀不同）。

    用于 bge_m3.py 缓存文本→向量映射，避免调试时重复请求 SiliconFlow API。
    """
    if not settings.cache_enabled:
        return NoopCache()
    return get_cache()


def register_backend(name: str, builder: Callable[[int | None], CacheBackend]) -> None:
    """运行时注册新后端（用于插件式扩展）。"""
    _BACKEND_BUILDERS[name] = builder
    get_cache.cache_clear()  # 让下次 get_cache 重新构造
