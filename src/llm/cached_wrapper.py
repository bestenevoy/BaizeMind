"""LLM 响应缓存包装器。

包装 LangChain 的 ChatOpenAI，在 invoke / stream 之前先查缓存：
- 命中：直接构造 AIMessage 返回（stream 时生成单块流），跳过 LLM 调用
- 未命中：调用真实 LLM，缓存响应 content，返回

缓存 key 设计（使用 src.cache.make_key）：
- 输入规范化：把 string / list[tuple] / list[BaseMessage] 统一转为可哈希的字符串
- key = make_key("llm", model_name, temperature, input_serialized, model_kwargs_json)
  生成形如 ``"llm:a1b2c3..."`` 的稳定 key，namespace 作为前缀
- value：LLM 响应的 content 字符串（AIMessage.content）

注意：
- 仅缓存 content（文本），不缓存 token 使用量、finish_reason 等元数据
- stream 命中缓存时返回单块 AIMessageChunk 流（一次性 yield 完整 content）
- stream 未命中时透传真实流，并在流结束后缓存拼接的完整 content
"""
from __future__ import annotations

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
                role = item.type
                content = item.content
                if isinstance(content, str):
                    parts.append(f"{role}:{content}")
                else:
                    # content 可能是 list（多模态），序列化为 JSON
                    parts.append(f"{role}:{json.dumps(content, ensure_ascii=False, sort_keys=True)}")
            else:
                parts.append(str(item))
        return "\x1e".join(parts)

    return str(input)


# LLM 缓存 value 中的 input_preview 截断长度（够看出是哪个 query，又不至于占空间）
_INPUT_PREVIEW_LEN = 400


def _encode_llm_cache_value(content: str, input_serialized: str, caller: str) -> str:
    """把 LLM 响应 + 触发它的 input 预览 + 调用方打包成 JSON 字符串。

    用于缓存 value，便于在 cache_admin 列表里看出"这条缓存是哪个 query 触发的"。

    向后兼容：旧缓存 value 是纯 content 字符串（不是 JSON），由 _decode 处理。
    """
    preview = input_serialized[:_INPUT_PREVIEW_LEN]
    return json.dumps(
        {
            "content": content,
            "input_preview": preview,
            "caller": caller,
        },
        ensure_ascii=False,
    )


def _decode_llm_cache_value(raw: str) -> str:
    """从缓存 value 中提取 content 字符串。

    兼容两种格式：
    - 新格式：JSON ``{"content": ..., "input_preview": ..., "caller": ...}``
    - 旧格式：纯 content 字符串（直接返回）
    """
    if not raw:
        return raw
    # JSON 一定以 '{' 开头；纯 content 可能也以 '{' 开头但极少
    # 保险起见尝试 parse，失败则当作旧格式
    if raw.lstrip().startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "content" in data:
                return data["content"]
        except (json.JSONDecodeError, ValueError):
            pass
    return raw


def _extract_llm_cache_meta(raw: str) -> dict:
    """从缓存 value 中提取 meta（input_preview / caller），无法解析时返回空。"""
    if not raw or not raw.lstrip().startswith("{"):
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "content" in data:
            return {
                "input_preview": data.get("input_preview", ""),
                "caller": data.get("caller", ""),
            }
    except (json.JSONDecodeError, ValueError):
        pass
    return {}


class CachedLLM:
    """LLM 缓存包装器（组合模式，不继承 ChatOpenAI）。

    用 __getattr__ 代理所有未显式实现的属性到 base_llm，
    调用方代码无需修改（llm.invoke(...) / llm.model_name 等照常工作）。

    缓存 key 通过 src.cache.make_key("llm", ...) 生成，namespace "llm" 作为前缀，
    与 embedding（"emb"）/ query rewrite（"query_rewrite"）等隔离。
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
        model_kwargs = getattr(base, "model_kwargs", {}) or {}
        return model_name, float(temperature), model_kwargs

    def _make_key(self, input_serialized: str) -> str:
        """构造缓存 key（含 namespace 前缀，由 make_key 保证稳定 + 短哈希）。"""
        from src.cache import make_key
        model_name, temperature, model_kwargs = self._get_model_info()
        kwargs_json = json.dumps(model_kwargs, ensure_ascii=False, sort_keys=True)
        # make_key 返回 "namespace:hash"，namespace 即 "llm" 前缀
        return make_key(
            self._namespace,
            model_name,
            f"{temperature:.6f}",
            input_serialized,
            kwargs_json,
        )

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> BaseMessage:
        """带缓存的 invoke。

        缓存命中时构造 AIMessage(content=cached) 返回。
        config 和 **kwargs 不参与缓存 key（一般是无状态配置）。
        """
        from src.llm.token_stats import get_token_stats, extract_caller, extract_token_usage
        stats = get_token_stats()
        caller = extract_caller(skip_frames=2)
        input_serialized = _serialize_messages(input)
        input_chars = len(input_serialized)

        cache = self._get_cache()
        # NoopCache 直接跳过
        from src.cache import NoopCache
        if isinstance(cache, NoopCache):
            result = self._base.invoke(input, config=config, **kwargs)
            content = result.content if isinstance(result.content, str) else json.dumps(result.content, ensure_ascii=False)
            in_tok, out_tok = extract_token_usage(result)
            stats.record(caller, input_chars, len(content), in_tok, out_tok, cache_hit=False)
            return result

        key = self._make_key(input_serialized)

        cached = cache.get(key)
        if cached is not None:
            logger.debug("LLM cache hit: key=%s...", key[:24])
            cached_content = _decode_llm_cache_value(cached)
            # 缓存命中：不计 token（未发起 API 调用），只记字符数
            stats.record(caller, input_chars, len(cached_content), cache_hit=True)
            return AIMessage(content=cached_content)

        logger.debug("LLM cache miss: key=%s...", key[:24])
        result = self._base.invoke(input, config=config, **kwargs)
        content = result.content if isinstance(result.content, str) else json.dumps(result.content, ensure_ascii=False)
        if content:
            cache.set(key, _encode_llm_cache_value(content, input_serialized, caller), ttl=self._ttl)
        in_tok, out_tok = extract_token_usage(result)
        stats.record(caller, input_chars, len(content), in_tok, out_tok, cache_hit=False)
        return result

    def stream(self, input: Any, config: Any = None, **kwargs: Any):
        """带缓存的流式调用。

        缓存命中：生成单块 AIMessageChunk 流（一次性 yield 完整 content）。
        缓存未命中：透传真实流，同时在流结束后缓存拼接的 content。
        """
        from src.cache import NoopCache
        from src.llm.token_stats import get_token_stats, extract_caller
        stats = get_token_stats()
        caller = extract_caller(skip_frames=2)
        input_serialized = _serialize_messages(input)
        input_chars = len(input_serialized)

        cache = self._get_cache()
        if isinstance(cache, NoopCache):
            # NoopCache 模式：透传真实流，包一层 _StreamCollector 仅用于统计字符数
            real_stream = self._base.stream(input, config=config, **kwargs)
            return _StreamCollector(real_stream, cache=None, key=None, ttl=0,
                                    stats=stats, caller=caller, input_chars=input_chars,
                                    input_serialized=input_serialized)

        key = self._make_key(input_serialized)

        cached = cache.get(key)
        if cached is not None:
            logger.debug("LLM stream cache hit: key=%s...", key[:24])
            cached_content = _decode_llm_cache_value(cached)
            stats.record(caller, input_chars, len(cached_content), cache_hit=True)
            from langchain_core.messages import AIMessageChunk
            return iter([AIMessageChunk(content=cached_content)])

        logger.debug("LLM stream cache miss: key=%s...", key[:24])
        real_stream = self._base.stream(input, config=config, **kwargs)
        return _StreamCollector(real_stream, cache, key, self._ttl,
                                stats=stats, caller=caller, input_chars=input_chars,
                                input_serialized=input_serialized)

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


class _StreamCollector:
    """包装流式迭代器，在迭代结束时缓存拼接的 content。

    用法：直接迭代该对象，每次 yield 一个 chunk（与原 stream 行为一致）。
    迭代结束后自动把拼接的 content 写入缓存，并记录 token/字符数统计。

    stats / caller / input_chars 可选：传入时会在流结束后记录一次统计。
    流式响应通常不带 token_usage（SSE 协议不包含），所以只记字符数。
    """

    def __init__(self, base_stream, cache, key: str | None, ttl: int,
                 stats=None, caller: str = "", input_chars: int = 0,
                 input_serialized: str = ""):
        self._base = base_stream
        self._cache = cache
        self._key = key
        self._ttl = ttl
        self._parts: list[str] = []
        self._stats = stats
        self._caller = caller
        self._input_chars = input_chars
        self._input_serialized = input_serialized
        self._recorded = False  # 防止 __next__/__anext__ 都结束时重复记录

    def _write_cache(self, full_content: str) -> None:
        """写入缓存（带 input_preview + caller 元数据）。"""
        if full_content and self._cache is not None and self._key is not None:
            self._cache.set(
                self._key,
                _encode_llm_cache_value(full_content, self._input_serialized, self._caller),
                ttl=self._ttl,
            )

    def _record_stats(self) -> None:
        if self._recorded or self._stats is None:
            return
        self._recorded = True
        full = "".join(self._parts)
        # 流式响应拿不到 token_usage，只记字符数（cache_hit=False，因为是真实 LLM 调用）
        self._stats.record(self._caller, self._input_chars, len(full), cache_hit=False)

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = next(self._base)
            content = chunk.content
            if isinstance(content, str):
                self._parts.append(content)
            elif content:
                self._parts.append(json.dumps(content, ensure_ascii=False))
            return chunk
        except StopIteration:
            self._write_cache("".join(self._parts))
            self._record_stats()
            raise

    # 支持 async for（LangChain 的 astream 可能需要）
    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            chunk = await self._base.__anext__()
            content = chunk.content
            if isinstance(content, str):
                self._parts.append(content)
            elif content:
                self._parts.append(json.dumps(content, ensure_ascii=False))
            return chunk
        except StopAsyncIteration:
            self._write_cache("".join(self._parts))
            self._record_stats()
            raise


def wrap_with_cache(base_llm: Any, namespace: str | None = None, ttl: int | None = None) -> Any:
    """包装 LLM 实例为 CachedLLM。

    Args:
        base_llm: 原始 LLM 实例（如 ChatOpenAI）
        namespace: 缓存 key 前缀，None 则用 settings.cache_llm_namespace
        ttl: 缓存 TTL 秒，None 则用 settings.cache_ttl_seconds

    Returns:
        CachedLLM 实例（如果缓存禁用则返回原始 LLM）
    """
    from config.settings import settings
    if not settings.cache_enabled:
        return base_llm
    ns = namespace if namespace is not None else settings.cache_llm_namespace
    t = ttl if ttl is not None else settings.cache_ttl_seconds
    return CachedLLM(base_llm, namespace=ns, ttl=t)
