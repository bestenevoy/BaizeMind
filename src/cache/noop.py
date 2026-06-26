"""空操作缓存后端（总是 miss，用于禁用缓存的场景）。

当 settings.cache_enabled=False 时由工厂返回，保证所有调用点无需判空。
"""
from __future__ import annotations

from typing import Optional

from src.cache.base import CacheBackend, CacheEntry


class NoopCache(CacheBackend):
    """空实现：get 总返回 None，set/delete/clear 为 no-op。"""

    def get(self, key: str) -> Optional[str]:
        return None

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        pass

    def delete(self, key: str) -> None:
        pass

    def clear(self) -> None:
        pass

    def entries(self, prefix: Optional[str] = None) -> list[CacheEntry]:
        return []
