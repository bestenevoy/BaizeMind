"""Sheet 摘要 + 字段映射生成器。

一次 LLM 调用同时产出：
1. 自然语言摘要（作为唯一向量 Chunk）
2. 中文→英文列名映射 + SQLite 类型

LLM 调用失败时回退到本地启发式：摘要用表头+统计拼接，列名用 parser 的占位名。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from config.prompts import EXCEL_SUMMARY_SYSTEM
from config.settings import settings
from src.excel_rag.parser import SheetInfo
from src.llm.deepseek import get_chat_llm

logger = logging.getLogger(__name__)


def _build_llm_input(sheet: SheetInfo) -> str:
    """构造喂给 LLM 的输入：表头、推断类型、统计、样本行。"""
    lines = [f"Sheet 名称: {sheet.sheet_name}", f"总记录数: {sheet.row_count}", "表头与类型:"]
    for col in sheet.columns:
        sample = ", ".join(str(v) for v in col.sample_values[:3])
        lines.append(f"- {col.cn} ({col.type}) 样本: {sample}")
    lines.append("统计信息:")
    for k, v in sheet.stats.items():
        if k == "row_count":
            continue
        lines.append(f"- {k}: {v}")
    lines.append("前 5 行数据:")
    for row in sheet.sample_rows:
        lines.append("  | ".join(str(v) for v in row))
    return "\n".join(lines)


def _sanitize_en_name(name: str, fallback: str) -> str:
    """确保英文列名为合法 SQLite 标识符。"""
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(name).strip())
    s = re.sub(r"_+", "_", s).strip("_").lower()
    if not s or s[0].isdigit():
        s = fallback
    return s


def _fallback_summary(sheet: SheetInfo) -> tuple[str, list[dict[str, str]]]:
    """LLM 不可用时的本地回退。"""
    parts = [f"{sheet.sheet_name} 数据表。", f"共 {sheet.row_count} 条记录。", "包含字段:"]
    cols_desc = []
    columns_out = []
    for col in sheet.columns:
        cols_desc.append(f"- {col.cn}（{col.type}）")
        columns_out.append({"cn": col.cn, "en": col.en, "type": col.type})
    parts.extend(cols_desc)
    for k, v in sheet.stats.items():
        if k == "row_count":
            continue
        parts.append(f"{k}: {v}")
    return "\n".join(parts), columns_out


def generate_summary(sheet: SheetInfo) -> tuple[str, list[dict[str, str]]]:
    """为单个 Sheet 生成摘要 + 列映射。

    返回 (summary_text, columns)。
    columns 元素: {"cn": str, "en": str, "type": str}
    """
    # 原始占位列名作为回退
    fallback_cols = [{"cn": c.cn, "en": c.en, "type": c.type} for c in sheet.columns]

    try:
        llm = get_chat_llm(temperature=0.0)
        system = EXCEL_SUMMARY_SYSTEM.format(language=settings.response_language)
        user_msg = _build_llm_input(sheet)
        resp = llm.invoke([("system", system), ("human", user_msg)])
        text = resp.content.strip()
        # 去除可能的 markdown fence
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(text)

        summary = str(data.get("summary", "")).strip()
        if not summary:
            summary, cols = _fallback_summary(sheet)
            return summary, cols

        # 校验并补齐列映射
        llm_cols = data.get("columns", [])
        if not isinstance(llm_cols, list) or len(llm_cols) != len(sheet.columns):
            logger.warning(
                f"Sheet '{sheet.sheet_name}': LLM returned {len(llm_cols) if isinstance(llm_cols, list) else 0} "
                f"columns, expected {len(sheet.columns)}; falling back to local mapping"
            )
            return summary, fallback_cols

        columns_out = []
        for i, raw in enumerate(llm_cols):
            cn = str(raw.get("cn", sheet.columns[i].cn))
            en = _sanitize_en_name(str(raw.get("en", "")), sheet.columns[i].en)
            col_type = str(raw.get("type", sheet.columns[i].type)).upper()
            if col_type not in ("INTEGER", "REAL", "TEXT"):
                col_type = sheet.columns[i].type
            columns_out.append({"cn": cn, "en": en, "type": col_type})

        return summary, columns_out
    except Exception as e:
        logger.warning(f"Sheet '{sheet.sheet_name}' summary generation failed ({e}); using fallback")
        return _fallback_summary(sheet)
