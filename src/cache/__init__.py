"""统一缓存层（单一 API，多后端）。

所有调用方使用同一套 API：
- ``get(key)`` / ``set(key, value, ttl)`` / ``delete(key)`` / ``clear()`` / ``entries(prefix)``
- ``make_key(*parts)`` 生成稳定的 ``"prefix:hash"`` 形式 key（namespace 作为前缀）
- ``get_cache(backend=None)`` 工厂返回单例

后端：
- ``memory`` - 进程内 LRU（开发默认）
- ``sqlite`` - SQLite 持久化（多 worker 共享）
- ``garnet`` / ``redis`` - Garnet/Redis 服务器（生产，跨进程共享，原生 TTL）
- ``none`` - NoopCache（禁用缓存）

LLM 与 embedding 缓存共用同一缓存实例，仅通过 make_key 的 prefix（namespace）区分：
- LLM 响应：``make_key("llm", model, temp, input, kwargs)``
- Embedding：``make_key("emb", model_tag, max_length, text)``
- Query rewrite：``make_key("query_rewrite", ...)``
"""
from src.cache.base import CacheBackend, CacheEntry, make_key, now_ts
from src.cache.factory import (
    get_cache,
    get_embedding_cache,
    get_llm_cache,
    register_backend,
)
from src.cache.garnet import GarnetCache
from src.cache.memory import MemoryCache
from src.cache.noop import NoopCache
from src.cache.sqlite_backend import SQLiteCache

__all__ = [
    "CacheBackend",
    "CacheEntry",
    "make_key",
    "now_ts",
    "get_cache",
    "get_llm_cache",
    "get_embedding_cache",
    "register_backend",
    "MemoryCache",
    "SQLiteCache",
    "GarnetCache",
    "NoopCache",
]
