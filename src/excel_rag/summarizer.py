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
        lines.append(f"- {col.display_name} ({col.data_type}) 样本: {sample}")
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
        cols_desc.append(f"- {col.display_name}（{col.data_type}）")
        columns_out.append({"display_name": col.display_name, "column_name": col.column_name, "data_type": col.data_type})
    parts.extend(cols_desc)
    for k, v in sheet.stats.items():
        if k == "row_count":
            continue
        parts.append(f"{k}: {v}")
    return "\n".join(parts), columns_out


def generate_summary(sheet: SheetInfo) -> tuple[str, list[dict[str, str]]]:
    """为单个 Sheet 生成摘要 + 列映射。

    返回 (summary_text, columns)。
    columns 元素: {"display_name": str, "column_name": str, "data_type": str}
      - display_name: 实际显示字段（原始表头，支持中英文，不参与 SQL 生成）
      - column_name: 数据库表字段名（snake_case 英文标识符，用于 SQL 生成）
      - data_type: 字段数据类型（INTEGER / REAL / TEXT）
    """
    # 原始占位列名作为回退
    fallback_cols = [
        {"display_name": c.display_name, "column_name": c.column_name, "data_type": c.data_type}
        for c in sheet.columns
    ]

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
            display_name = str(raw.get("display_name", sheet.columns[i].display_name))
            column_name = _sanitize_en_name(str(raw.get("column_name", "")), sheet.columns[i].column_name)
            col_type = str(raw.get("data_type", sheet.columns[i].data_type)).upper()
            if col_type not in ("INTEGER", "REAL", "TEXT"):
                col_type = sheet.columns[i].data_type
            columns_out.append({
                "display_name": display_name,
                "column_name": column_name,
                "data_type": col_type,
            })

        return summary, columns_out
    except Exception as e:
        logger.warning(f"Sheet '{sheet.sheet_name}' summary generation failed ({e}); using fallback")
        return _fallback_summary(sheet)
