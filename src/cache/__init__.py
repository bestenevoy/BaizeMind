"""LLM 响应缓存抽象层。

支持三种后端：
- file: 文件持久化（默认，按 hash 分片，无外部依赖）
- garnet: Redis 协议（Garnet 服务器，跨进程共享，带 TTL）
- memory: 进程内 LRU（单进程开发用，重启丢失）

设计要点：
- 通用 KV 接口：get(namespace, key) / put(namespace, key, value, ttl) / clear(namespace)
- namespace 用于隔离不同用途（llm / query_rewrite / nl2sql）
- 序列化统一用 JSON（LLM 响应是字符串，无复杂对象）
- 所有后端实现 get 返回 None 表示 miss（不抛异常，缓存失败不影响主流程）
"""
from __future__ import annotations

import abc
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CacheBackend(abc.ABC):
    """缓存后端抽象基类。"""

    @abc.abstractmethod
    def get(self, namespace: str, key: str) -> str | None:
        """读取缓存。返回 None 表示 miss。"""

    @abc.abstractmethod
    def put(self, namespace: str, key: str, value: str, ttl: int = 0) -> None:
        """写入缓存。ttl=0 表示永不过期（或后端默认 TTL）。"""

    @abc.abstractmethod
    def clear(self, namespace: str | None = None) -> int:
        """清空缓存。namespace=None 清空所有。返回删除条数。"""


class MemoryCache(CacheBackend):
    """进程内 LRU 缓存（单进程，重启丢失）。

    适用场景：开发调试、单进程部署。
    线程安全：用 threading.Lock 保护 OrderedDict。
    """

    def __init__(self, max_items: int = 1024):
        self._max = max_items
        self._data: OrderedDict[str, tuple[str, float]] = OrderedDict()  # full_key -> (value, expire_ts)
        self._lock = threading.Lock()

    def _full_key(self, namespace: str, key: str) -> str:
        return f"{namespace}:{key}"

    def get(self, namespace: str, key: str) -> str | None:
        fk = self._full_key(namespace, key)
        with self._lock:
            entry = self._data.get(fk)
            if entry is None:
                return None
            value, expire_ts = entry
            if expire_ts > 0 and time.time() > expire_ts:
                # 过期，惰性删除
                del self._data[fk]
                return None
            self._data.move_to_end(fk)
            return value

    def put(self, namespace: str, key: str, value: str, ttl: int = 0) -> None:
        fk = self._full_key(namespace, key)
        expire_ts = (time.time() + ttl) if ttl > 0 else 0
        with self._lock:
            if fk in self._data:
                self._data.move_to_end(fk)
            self._data[fk] = (value, expire_ts)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self, namespace: str | None = None) -> int:
        with self._lock:
            if namespace is None:
                n = len(self._data)
                self._data.clear()
                return n
            prefix = f"{namespace}:"
            keys = [k for k in self._data if k.startswith(prefix)]
            for k in keys:
                del self._data[k]
            return len(keys)


class FileCache(CacheBackend):
    """文件持久化缓存（按 hash 分片存储）。

    适用场景：无外部依赖的持久化缓存，跨进程共享（同机）。
    存储结构：{cache_dir}/{namespace}/{key_hash[:2]}/{key_hash}.json
    每个条目一个 JSON 文件，包含 value 和 expire_ts。
    """

    def __init__(self, cache_dir: str):
        self._base = Path(cache_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path_for(self, namespace: str, key: str) -> Path:
        import hashlib
        h = hashlib.sha256(f"{namespace}\x1f{key}".encode("utf-8")).hexdigest()
        shard = self._base / namespace / h[:2]
        shard.mkdir(parents=True, exist_ok=True)
        return shard / f"{h}.json"

    def get(self, namespace: str, key: str) -> str | None:
        path = self._path_for(namespace, key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            expire_ts = data.get("expire_ts", 0)
            if expire_ts > 0 and time.time() > expire_ts:
                # 过期，删除文件
                try:
                    path.unlink()
                except OSError:
                    pass
                return None
            return data.get("value")
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("FileCache read failed for %s: %s", path, e)
            return None

    def put(self, namespace: str, key: str, value: str, ttl: int = 0) -> None:
        path = self._path_for(namespace, key)
        expire_ts = (time.time() + ttl) if ttl > 0 else 0
        data = {"value": value, "expire_ts": expire_ts, "ts": time.time()}
        try:
            with self._lock:
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            logger.warning("FileCache write failed for %s: %s", path, e)

    def clear(self, namespace: str | None = None) -> int:
        import shutil
        count = 0
        if namespace is None:
            # 清空所有 namespace
            if self._base.exists():
                for ns_dir in self._base.iterdir():
                    if ns_dir.is_dir():
                        count += sum(1 for _ in ns_dir.rglob("*.json"))
                        shutil.rmtree(ns_dir, ignore_errors=True)
            return count
        ns_dir = self._base / namespace
        if ns_dir.exists():
            count = sum(1 for _ in ns_dir.rglob("*.json"))
            shutil.rmtree(ns_dir, ignore_errors=True)
        return count


class GarnetCache(CacheBackend):
    """Redis/Garnet 后端（跨进程共享，原生 TTL 支持）。

    适用场景：生产环境多进程部署，需要跨进程共享缓存。
    连接：garnet_url = "redis://127.0.0.1:16389/0"
    """

    def __init__(self, url: str):
        import redis
        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._url = url
        try:
            self._client.ping()
            logger.info("GarnetCache connected: %s", url)
        except Exception as e:
            logger.error("GarnetCache connection failed: %s", e)
            raise

    def _full_key(self, namespace: str, key: str) -> str:
        return f"{namespace}:{key}"

    def get(self, namespace: str, key: str) -> str | None:
        try:
            return self._client.get(self._full_key(namespace, key))
        except Exception as e:
            logger.warning("GarnetCache get failed: %s", e)
            return None

    def put(self, namespace: str, key: str, value: str, ttl: int = 0) -> None:
        try:
            fk = self._full_key(namespace, key)
            if ttl > 0:
                self._client.setex(fk, ttl, value)
            else:
                self._client.set(fk, value)
        except Exception as e:
            logger.warning("GarnetCache put failed: %s", e)

    def clear(self, namespace: str | None = None) -> int:
        try:
            if namespace is None:
                return self._client.flushdb()
            # 扫描删除指定 namespace 的 key
            pattern = f"{namespace}:*"
            keys = list(self._client.scan_iter(match=pattern, count=100))
            if keys:
                return self._client.delete(*keys)
            return 0
        except Exception as e:
            logger.warning("GarnetCache clear failed: %s", e)
            return 0


class NoopCache(CacheBackend):
    """空操作缓存（总是 miss，用于禁用缓存的场景）。"""

    def get(self, namespace: str, key: str) -> str | None:
        return None

    def put(self, namespace: str, key: str, value: str, ttl: int = 0) -> None:
        pass

    def clear(self, namespace: str | None = None) -> int:
        return 0


# 单例缓存（按 backend 类型 + 配置缓存实例，避免重复创建连接）
_instances: dict[str, CacheBackend] = {}
_instances_lock = threading.Lock()


def get_cache_backend(backend: str, **kwargs: Any) -> CacheBackend:
    """工厂函数：根据 backend 名称创建/复用缓存实例。

    Args:
        backend: "memory" | "file" | "garnet" | "none"
        **kwargs: 后端特定参数（file: cache_dir; garnet: url）

    Returns:
        CacheBackend 实例（单例）
    """
    cache_key = f"{backend}:{kwargs.get('cache_dir', '')}:{kwargs.get('url', '')}"
    with _instances_lock:
        if cache_key in _instances:
            return _instances[cache_key]

        if backend == "memory":
            inst: CacheBackend = MemoryCache(max_items=kwargs.get("max_items", 1024))
        elif backend == "file":
            inst = FileCache(cache_dir=kwargs.get("cache_dir", "data/cache"))
        elif backend in ("garnet", "redis"):
            inst = GarnetCache(url=kwargs.get("url", "redis://127.0.0.1:16389/0"))
        elif backend in ("none", "noop"):
            inst = NoopCache()
        else:
            raise ValueError(f"Unknown cache backend: {backend}")

        _instances[cache_key] = inst
        return inst


def get_llm_cache() -> CacheBackend:
    """获取 LLM 响应缓存后端（根据 settings.llm_cache_* 配置）。

    如果 settings.llm_cache_enabled=False，返回 NoopCache。
    """
    from config.settings import settings
    if not settings.llm_cache_enabled:
        return NoopCache()
    return get_cache_backend(
        settings.llm_cache_backend,
        cache_dir=str(settings.project_root / settings.cache_file_dir),
        url=settings.garnet_url,
    )
