"""LLM 调用 token 统计路由。

提供 ``/api/v1/system/llm-stats`` 查看进程内累计的 LLM 调用统计，
按调用方模块分组，便于定位哪一块耗费 token 最多。

数据仅存内存，重启即清空；可调用 ``/llm-stats/reset`` 手动清零（重新开始统计）。
"""
from fastapi import APIRouter, Depends

from src.auth import User, require_admin, require_login
from src.llm.token_stats import get_token_stats

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/llm-stats")
async def llm_stats(_: User = Depends(require_login)):
    """查看 LLM 调用 token 统计（按调用方模块分组，按总 token 降序）。

    统计维度（每个调用方模块独立累计）：
    - call_count: 总调用次数（含缓存命中）
    - llm_calls: 实际发起 LLM API 调用次数（不含缓存命中）
    - cache_hits: 缓存命中次数
    - input_chars / output_chars: 字符数（始终可用）
    - input_tokens / output_tokens: token 数（响应 usage 可用时；流式调用拿不到，记 0）
    """
    snapshot = get_token_stats().snapshot()

    # 按 input_tokens + output_tokens 降序排（拿不到 token 时用字符数排序）
    def total_cost(v: dict) -> int:
        return v.get("input_tokens", 0) + v.get("output_tokens", 0) \
            or v.get("input_chars", 0) + v.get("output_chars", 0)

    sorted_items = sorted(snapshot.items(), key=lambda x: total_cost(x[1]), reverse=True)

    totals = {
        "call_count": sum(s["call_count"] for s in snapshot.values()),
        "llm_calls": sum(s["llm_calls"] for s in snapshot.values()),
        "cache_hits": sum(s["cache_hits"] for s in snapshot.values()),
        "input_chars": sum(s["input_chars"] for s in snapshot.values()),
        "output_chars": sum(s["output_chars"] for s in snapshot.values()),
        "input_tokens": sum(s["input_tokens"] for s in snapshot.values()),
        "output_tokens": sum(s["output_tokens"] for s in snapshot.values()),
    }
    cache_hit_rate = (
        round(totals["cache_hits"] / totals["call_count"] * 100, 2)
        if totals["call_count"] else 0.0
    )

    return {
        "callers": [
            {"caller": caller, **data} for caller, data in sorted_items
        ],
        "totals": totals,
        "cache_hit_rate": cache_hit_rate,
    }


@router.post("/llm-stats/reset")
async def reset_llm_stats(_: User = Depends(require_admin)):
    """清零统计计数器（保留缓存，仅重置统计）。"""
    get_token_stats().reset()
    return {"success": True}
