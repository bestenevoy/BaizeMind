"""LLM 调用 token 统计（进程内单例，按调用方模块分组）。

统计维度（每个调用方模块独立累计）：
- call_count: 总调用次数（含缓存命中）
- llm_calls: 实际发起 LLM API 调用次数（不含缓存命中）
- cache_hits: 缓存命中次数
- input_chars / output_chars: 字符数（始终可用，作为 token 的 fallback）
- input_tokens / output_tokens: token 数（响应 usage 可用时）

调用方模块通过 ``inspect.stack`` 自动识别，无需调用方显式传 namespace。
按模块名（如 ``src.agents.workflow`` / ``src.knowledge_graph.entity_extractor``）分组，
便于定位哪一块耗费 token 最多。

数据仅存内存，进程重启即清空；适合短期观测，不做持久化。
"""
from __future__ import annotations

import inspect
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass


@dataclass
class CallerStats:
    call_count: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    input_chars: int = 0
    output_chars: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class TokenStats:
    """线程安全的 LLM 调用统计（按 caller 模块分组）。"""

    def __init__(self) -> None:
        self._stats: dict[str, CallerStats] = defaultdict(CallerStats)
        self._lock = threading.Lock()

    def record(
        self,
        caller: str,
        input_chars: int,
        output_chars: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_hit: bool = False,
    ) -> None:
        with self._lock:
            s = self._stats[caller]
            s.call_count += 1
            if cache_hit:
                s.cache_hits += 1
            else:
                s.llm_calls += 1
            s.input_chars += input_chars
            s.output_chars += output_chars
            s.input_tokens += input_tokens
            s.output_tokens += output_tokens

    def snapshot(self) -> dict[str, dict]:
        """返回当前统计的深拷贝（线程安全）。"""
        with self._lock:
            return {caller: asdict(s) for caller, s in self._stats.items()}

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()


_stats = TokenStats()


def get_token_stats() -> TokenStats:
    return _stats


def extract_caller(skip_frames: int = 2) -> str:
    """从调用栈提取调用方模块名。

    Args:
        skip_frames: 跳过的栈帧数。
            - CachedLLM.invoke 调用本函数时传 skip_frames=2
              （跳过 extract_caller 本身 + invoke 帧，到达真正调用 .invoke 的代码）
    """
    try:
        frame = inspect.stack()[skip_frames]
        mod = inspect.getmodule(frame.frame)
        if mod and mod.__name__:
            return mod.__name__
        # fallback：用文件名
        return frame.filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    except Exception:
        return "unknown"


def extract_token_usage(result: object) -> tuple[int, int]:
    """从 LangChain AIMessage 响应中提取 token 使用量。

    优先尝试 OpenAI 标准字段：
    - response_metadata.token_usage.prompt_tokens / completion_tokens
    - response_metadata.token_usage.input_tokens / output_tokens（部分 provider）

    Returns:
        (input_tokens, output_tokens)；拿不到时返回 (0, 0)，调用方应 fallback 到字符数。
    """
    try:
        meta = getattr(result, "response_metadata", None) or {}
        usage = meta.get("token_usage") or meta.get("usage") or {}
        if not usage:
            # 部分 langchain 版本把 usage 放在 usage_metadata
            usage = getattr(result, "usage_metadata", None) or {}
        in_tok = int(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or 0
        )
        out_tok = int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or 0
        )
        return in_tok, out_tok
    except (AttributeError, TypeError, ValueError):
        return 0, 0
