"""进程内内存缓存后端。

适合单进程部署或对持久化无要求的场景。重启后失效。
线程安全。
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from src.cache.base import CacheBackend, now_ts


class _Entry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: str, expires_at: Optional[float]):
        self.value = value
        self.expires_at = expires_at


class MemoryCache(CacheBackend):
    def __init__(self, default_ttl: Optional[int] = None):
        self._store: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl  # None = 永不过期

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at is not None and entry.expires_at <= now_ts():
                # 惰性过期清除
                self._store.pop(key, None)
                return None
            return entry.value

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        if ttl == 0:
            return  # 显式不缓存
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = (now_ts() + effective_ttl) if effective_ttl else None
        with self._lock:
            self._store[key] = _Entry(value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def cleanup_expired(self) -> int:
        """主动扫描并清除已过期条目，返回清除数量。"""
        now = now_ts()
        with self._lock:
            expired = [k for k, e in self._store.items()
                       if e.expires_at is not None and e.expires_at <= now]
            for k in expired:
                self._store.pop(k, None)
            return len(expired)
