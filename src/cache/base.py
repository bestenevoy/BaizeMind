"""Cache backend abstraction.

通用的缓存接口，所有后端（memory / sqlite / redis ...）实现同一契约。
新增后端时只需继承 :class:`CacheBackend` 并在 ``factory.py`` 注册。
"""
from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from typing import Any, Optional


class CacheBackend(ABC):
    """所有缓存后端的统一接口。

    值通过 :func:`_serialize` / :func:`_deserialize` 在调用方完成 JSON 序列化，
    后端只负责存储字符串。这样不同后端行为一致，且不依赖 pickle（安全 + 跨语言）。
    """

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """返回 key 对应的原始字符串值，未命中或已过期返回 None。"""
        raise NotImplementedError

    @abstractmethod
    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        """写入键值。``ttl`` 为 None 表示沿用后端默认 TTL；为 0 表示不缓存。"""
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        """清空当前 namespace 下的所有缓存条目。"""
        raise NotImplementedError


def make_key(*parts: str) -> str:
    """根据若干可序列化部件生成稳定的短 key。

    用 SHA-256 摘要避免长 query / 含特殊字符的字符串污染后端存储。
    保留人类可读前缀方便调试。

    >>> make_key("rewrite", "zh", "什么是 RAG?")
    'rewrite:a1b2c3...'
    """
    raw = "\u241f".join(parts)  # 用 unit separator 拼接，避免部件内含分隔符造成碰撞
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    prefix = parts[0] if parts else "cache"
    return f"{prefix}:{digest}"


def now_ts() -> float:
    return time.time()
