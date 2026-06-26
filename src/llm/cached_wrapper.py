"""LLM 响应缓存包装器。

包装 LangChain 的 ChatOpenAI，在 invoke 之前先查缓存：
- 命中：直接构造 AIMessage 返回，跳过 LLM 调用
- 未命中：调用真实 LLM，缓存响应 content，返回

缓存 key 设计：
- 输入规范化：把 string / list[tuple] / list[BaseMessage] 统一转为可哈希的字符串
- key 包含：model_name + temperature + 规范化后的输入 + model_kwargs
- value：LLM 响应的 content 字符串（AIMessage.content）

注意：
- 仅缓存 content（文本），不缓存 token 使用量、finish_reason 等元数据
- temperature > 0 时仍可缓存（默认开启），如需禁用可在调用时 use_cache=False
- 流式调用（stream）不走缓存，直接透传到 base_llm
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

logger = logging.getLogger(__name__)


def _serialize_messages(input: Any) -> str:
    """把 LangChain invoke 的输入规范化为稳定字符串，用于缓存 key。

    支持的输入格式：
    - str: 直接返回
    - list[tuple[str, str]]: [("system", "..."), ("human", "...")]
    - list[BaseMessage]: [SystemMessage(...), HumanMessage(...)]
    """
    if isinstance(input, str):
        return input

    if isinstance(input, list):
        parts: list[str] = []
        for item in input:
            if isinstance(item, tuple) and len(item) == 2:
                role, content = item
                parts.append(f"{role}:{content}")
            elif isinstance(item, BaseMessage):
                # type: role (system/human/ai), content 是字符串或 list
                role = item.type
                content = item.content
                if isinstance(content, str):
                    parts.append(f"{role}:{content}")
                else:
                    # content 可能是 list（多模态），序列化为 JSON
                    parts.append(f"{role}:{json.dumps(content, ensure_ascii=False, sort_keys=True)}")
            else:
                # 未知类型，退化处理
                parts.append(str(item))
        return "\x1e".join(parts)

    return str(input)


def _make_cache_key(
    model_name: str,
    temperature: float,
    input_serialized: str,
    model_kwargs: dict[str, Any] | None,
) -> str:
    """构造缓存 key（哈希后返回）。

    包含：model_name + temperature + 输入 + model_kwargs
    """
    payload = {
        "model": model_name,
        "temperature": float(temperature),
        "input": input_serialized,
        "kwargs": model_kwargs or {},
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CachedLLM:
    """LLM 缓存包装器（组合模式，不继承 ChatOpenAI）。

    用 __getattr__ 代理所有未显式实现的属性到 base_llm，
    调用方代码无需修改（llm.invoke(...) / llm.model_name 等照常工作）。

    显式覆盖的方法：
    - invoke: 先查缓存，命中则构造 AIMessage 返回
    - stream: 不走缓存，直接透传
    """

    def __init__(self, base_llm: Any, namespace: str = "llm", ttl: int = 0):
        object.__setattr__(self, "_base", base_llm)
        object.__setattr__(self, "_namespace", namespace)
        object.__setattr__(self, "_ttl", ttl)
        object.__setattr__(self, "_cache", None)  # 延迟初始化，避免 import 时报错

    def _get_cache(self):
        """延迟获取缓存后端实例（首次调用时初始化）。"""
        if self._cache is None:
            from src.cache import get_llm_cache
            object.__setattr__(self, "_cache", get_llm_cache())
        return self._cache

    def _get_model_info(self) -> tuple[str, float, dict]:
        """从 base_llm 提取 model_name, temperature, model_kwargs。"""
        base = self._base
        model_name = getattr(base, "model_name", "") or getattr(base, "model", "")
        temperature = getattr(base, "temperature", 0.0) or 0.0
        # 捕获影响输出的关键 kwargs
        model_kwargs = getattr(base, "model_kwargs", {}) or {}
        return model_name, float(temperature), model_kwargs

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> BaseMessage:
        """带缓存的 invoke。

        缓存命中时构造 AIMessage(content=cached) 返回。
        config 和 **kwargs 不参与缓存 key（一般是无状态配置）。
        """
        cache = self._get_cache()
        # NoopCache 直接跳过
        from src.cache import NoopCache
        if isinstance(cache, NoopCache):
            return self._base.invoke(input, config=config, **kwargs)

        model_name, temperature, model_kwargs = self._get_model_info()
        input_serialized = _serialize_messages(input)
        key = _make_cache_key(model_name, temperature, input_serialized, model_kwargs)

        cached = cache.get(self._namespace, key)
        if cached is not None:
            logger.debug("LLM cache hit: model=%s, key=%s...", model_name, key[:8])
            return AIMessage(content=cached)

        logger.debug("LLM cache miss: model=%s, key=%s...", model_name, key[:8])
        result = self._base.invoke(input, config=config, **kwargs)
        content = result.content if isinstance(result.content, str) else json.dumps(result.content, ensure_ascii=False)
        if content:
            cache.put(self._namespace, key, content, ttl=self._ttl)
        return result

    def stream(self, input: Any, config: Any = None, **kwargs: Any):
        """流式调用不走缓存，直接透传。"""
        return self._base.stream(input, config=config, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """代理所有未显式实现的属性到 base_llm。"""
        return getattr(self._base, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """允许设置自身属性，其他代理到 base_llm。"""
        if name in ("_base", "_namespace", "_ttl", "_cache"):
            object.__setattr__(self, name, value)
        elif hasattr(self._base, name):
            setattr(self._base, name, value)
        else:
            object.__setattr__(self, name, value)


def wrap_with_cache(base_llm: Any, namespace: str | None = None, ttl: int | None = None) -> Any:
    """包装 LLM 实例为 CachedLLM。

    Args:
        base_llm: 原始 LLM 实例（如 ChatOpenAI）
        namespace: 缓存 namespace，None 则用 settings.llm_cache_namespace
        ttl: 缓存 TTL 秒，None 则用 settings.llm_cache_ttl_seconds

    Returns:
        CachedLLM 实例（如果缓存禁用则返回原始 LLM）
    """
    from config.settings import settings
    if not settings.llm_cache_enabled:
        return base_llm
    ns = namespace if namespace is not None else settings.llm_cache_namespace
    t = ttl if ttl is not None else settings.llm_cache_ttl_seconds
    return CachedLLM(base_llm, namespace=ns, ttl=t)
