"""SQLite 持久化缓存后端。

跨进程共享、重启不丢失。复用项目既有的 SQLite 风格（直接 sqlite3 模块，无 ORM）。
WAL 模式提升并发读写。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from src.cache.base import CacheBackend, now_ts


class SQLiteCache(CacheBackend):
    def __init__(self, db_path: str | Path, default_ttl: Optional[int] = None):
        self._db_path = str(db_path)
        self._default_ttl = default_ttl
        self._lock = threading.Lock()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        # check_same_thread=False + 外层锁保证跨线程安全
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache_entries (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        expires_at REAL,
                        created_at REAL NOT NULL
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cache_expires "
                    "ON cache_entries(expires_at) WHERE expires_at IS NOT NULL"
                )
                conn.commit()
            finally:
                conn.close()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT value, expires_at FROM cache_entries WHERE key = ?",
                    (key,),
                ).fetchone()
                if row is None:
                    return None
                value, expires_at = row
                if expires_at is not None and expires_at <= now_ts():
                    conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                    conn.commit()
                    return None
                return value
            finally:
                conn.close()

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        if ttl == 0:
            return
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = (now_ts() + effective_ttl) if effective_ttl else None
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO cache_entries(key, value, expires_at, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (key, value, expires_at, now_ts()),
                )
                conn.commit()
            finally:
                conn.close()

    def delete(self, key: str) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                conn.commit()
            finally:
                conn.close()

    def clear(self) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("DELETE FROM cache_entries")
                conn.commit()
            finally:
                conn.close()

    def cleanup_expired(self) -> int:
        """删除所有已过期条目，返回删除行数。"""
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    "DELETE FROM cache_entries WHERE expires_at IS NOT NULL AND expires_at <= ?",
                    (now_ts(),),
                )
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()
