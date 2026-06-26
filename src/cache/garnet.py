"""Redis/Garnet 后端（跨进程共享，原生 TTL 支持）。

Garnet 与 Redis 协议兼容，本实现两者等价使用。
适用场景：生产环境多进程部署，需要跨进程共享缓存。
连接：garnet_url = "redis://127.0.0.1:16389/0"
"""
from __future__ import annotations

import logging
from typing import Optional

from src.cache.base import CacheBackend, CacheEntry, now_ts

logger = logging.getLogger(__name__)


class GarnetCache(CacheBackend):
    """Redis/Garnet 后端。

    key 直接使用调用方传入的字符串（通常由 :func:`make_key` 生成，
    形如 ``"llm:abc123..."``）。namespace 已作为前缀编入 key，无需再拼接。
    """

    def __init__(self, url: str, default_ttl: Optional[int] = None):
        import redis
        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._url = url
        self._default_ttl = default_ttl
        try:
            self._client.ping()
            logger.info("GarnetCache connected: %s", url)
        except Exception as e:
            logger.error("GarnetCache connection failed: %s", e)
            raise

    def get(self, key: str) -> Optional[str]:
        try:
            return self._client.get(key)
        except Exception as e:
            logger.warning("GarnetCache get failed: %s", e)
            return None

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        if ttl == 0:
            return
        effective_ttl = ttl if ttl is not None else self._default_ttl
        try:
            if effective_ttl:
                self._client.setex(key, effective_ttl, value)
            else:
                self._client.set(key, value)
        except Exception as e:
            logger.warning("GarnetCache set failed: %s", e)

    def delete(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception as e:
            logger.warning("GarnetCache delete failed: %s", e)

    def clear(self) -> None:
        """清空当前 db 的所有 key。

        注意：Redis/Garnet 的 FLUSHDB 会清除整个 db，不区分 namespace。
        如需按 namespace 清除，请用 :meth:`entries` + :meth:`delete` 逐条删除。
        """
        try:
            self._client.flushdb()
        except Exception as e:
            logger.warning("GarnetCache clear failed: %s", e)

    def entries(self, prefix: Optional[str] = None) -> list[CacheEntry]:
        """列举条目（用 SCAN 匹配 prefix）。

        Garnet/Redis 不存储 created_at，此处用当前时间近似；
        TTL 剩余通过 PTTL 查询（-1 表示永不过期，-2 表示不存在）。
        """
        now = now_ts()
        result: list[CacheEntry] = []
        try:
            pattern = f"{prefix}*" if prefix is not None else "*"
            keys = list(self._client.scan_iter(match=pattern, count=100))
            if not keys:
                return result
            # 批量查 TTL
            pipe = self._client.pipeline()
            for k in keys:
                pipe.pttl(k)
            ttls = pipe.execute()
            for k, ttl_ms in zip(keys, ttls):
                # ttl_ms: -2=key 不存在, -1=永不过期, >0=剩余毫秒
                if ttl_ms == -2:
                    continue
                value = self._client.get(k)
                if value is None:
                    continue
                if ttl_ms == -1:
                    expires_at = None
                    ttl_remaining = None
                else:
                    ttl_remaining = ttl_ms / 1000.0
                    expires_at = now + ttl_remaining
                result.append(CacheEntry(
                    key=k,
                    value=value,
                    created_at=now,  # Redis 不存 created_at，用当前时间近似
                    expires_at=expires_at,
                    ttl_remaining=ttl_remaining,
                ))
        except Exception as e:
            logger.warning("GarnetCache entries failed: %s", e)
        return result
