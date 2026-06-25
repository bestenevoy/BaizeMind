"""进程内内存缓存后端。

适合单进程部署或对持久化无要求的场景。重启后失效。
线程安全。
"""
from __future__ import annotations

import threading
from typing import Optional

from src.cache.base import CacheBackend, CacheEntry, now_ts


class _Entry:
    __slots__ = ("value", "expires_at", "created_at")

    def __init__(self, value: str, expires_at: Optional[float], created_at: float):
        self.value = value
        self.expires_at = expires_at
        self.created_at = created_at


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
            self._store[key] = _Entry(value, expires_at, now_ts())

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

    def entries(self, prefix: Optional[str] = None) -> list[CacheEntry]:
        """列举条目，主动剔除已过期项。"""
        now = now_ts()
        result: list[CacheEntry] = []
        # 复制引用，避免遍历时持锁太久；删除操作再单独加锁
        with self._lock:
            snapshot = list(self._store.items())
        for k, e in snapshot:
            if prefix is not None and not k.startswith(prefix):
                continue
            if e.expires_at is not None and e.expires_at <= now:
                # 惰性清除
                with self._lock:
                    cur = self._store.get(k)
                    if cur is not None and cur.expires_at is not None and cur.expires_at <= now:
                        self._store.pop(k, None)
                continue
            ttl_remaining = (e.expires_at - now) if e.expires_at is not None else None
            result.append(CacheEntry(
                key=k,
                value=e.value,
                created_at=e.created_at,
                expires_at=e.expires_at,
                ttl_remaining=ttl_remaining,
            ))
        return result
