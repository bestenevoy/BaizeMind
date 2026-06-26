"""Excel 解析：读取每个 Sheet，提取表头、统计信息，并推断列类型。

一张 Sheet 仅生成一个摘要 Chunk（符合 EXCEL_RAG.md 设计）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import settings


@dataclass
class ColumnInfo:
    cn: str  # 原始中文表头
    en: str = ""  # 英文列名（由 summarizer 填充）
    type: str = "TEXT"  # SQLite 类型: INTEGER / REAL / TEXT
    sample_values: list[Any] = field(default_factory=list)


@dataclass
class SheetInfo:
    sheet_index: int
    sheet_name: str
    headers: list[str]
    columns: list[ColumnInfo]
    df: pd.DataFrame
    row_count: int
    stats: dict[str, Any]
    sample_rows: list[list[Any]]  # 前 5 行用于 NL2SQL prompt


def _infer_sqlite_type(series: pd.Series) -> str:
    """根据列内容推断 SQLite 类型。空列默认 TEXT。"""
    non_null = series.dropna()
    if non_null.empty:
        return "TEXT"
    # 整数检测：pandas integer dtype 或全部可转为 int
    if pd.api.types.is_integer_dtype(non_null):
        return "INTEGER"
    # 浮点
    if pd.api.types.is_float_dtype(non_null):
        return "REAL"
    # 尝试将字符串列解析为数值
    if pd.api.types.is_object_dtype(non_null):
        converted = pd.to_numeric(non_null, errors="coerce")
        if converted.notna().all():
            # 全部能转数值：判断是否整数
            if (converted % 1 == 0).all():
                return "INTEGER"
            return "REAL"
    return "TEXT"


def _sanitize_header(name: str, idx: int) -> str:
    """清洗表头为合法的占位英文名（summarizer 会覆盖为更好的名字）。

    用于在 LLM 生成映射前的临时存储。
    """
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(name).strip())
    s = re.sub(r"_+", "_", s).strip("_").lower()
    if not s or s[0].isdigit():
        s = f"col_{idx}"
    return s


def _compute_stats(df: pd.DataFrame, columns: list[ColumnInfo]) -> dict[str, Any]:
    """统计整体信息：总记录数、数值列 min/max/mean、分类列枚举值。"""
    stats: dict[str, Any] = {
        "row_count": len(df),
    }
    # 数值列
    for col in columns:
        en = col.en or col.cn
        if col.type in ("INTEGER", "REAL"):
            series = pd.to_numeric(df[col.cn], errors="coerce").dropna()
            if not series.empty:
                stats[col.cn] = {
                    "min": float(series.min()),
                    "max": float(series.max()),
                    "mean": float(series.mean()),
                }
        elif col.type == "TEXT":
            # 枚举值（去重，最多 20 个）
            uniq = df[col.cn].dropna().astype(str).unique().tolist()
            if len(uniq) <= 20:
                stats[col.cn] = {"enum": uniq}
            else:
                stats[col.cn] = {"enum_count": len(uniq)}
    return stats


def parse_excel(file_path: str | Path) -> list[SheetInfo]:
    """解析 Excel 文件，返回每个 Sheet 的结构化信息。

    - 跳过完全为空的 Sheet
    - 首行视为表头
    - 推断列类型、采样统计
    """
    file_path = Path(file_path)
    # dtype=str 保留原始文本，避免日期被自动转换；后续再按需转型
    xlsx = pd.read_excel(file_path, sheet_name=None, dtype=str, engine="openpyxl")

    sheets: list[SheetInfo] = []
    for idx, (sheet_name, df) in enumerate(xlsx.items()):
        # 跳过空 Sheet
        if df.empty or len(df.columns) == 0:
            continue
        # 清理列名：去除前后空白，空列名补占位
        headers: list[str] = []
        for i, c in enumerate(df.columns):
            name = str(c).strip() if c is not None else ""
            if not name or name == "nan":
                name = f"列{i + 1}"
            headers.append(name)
        df.columns = headers

        # 跳过无数据行
        df = df.dropna(how="all").reset_index(drop=True)
        if df.empty:
            continue

        # 类型推断：采样前 N 行
        sample_n = min(settings.excel_sample_rows_for_inference, len(df))
        sample_df = df.head(sample_n)

        columns: list[ColumnInfo] = []
        for i, header in enumerate(headers):
            series = sample_df[header]
            col_type = _infer_sqlite_type(series)
            sample_values = series.dropna().head(5).tolist()
            columns.append(ColumnInfo(
                cn=header,
                en=_sanitize_header(header, i),
                type=col_type,
                sample_values=sample_values,
            ))

        stats = _compute_stats(sample_df, columns)

        # 前 5 行样本（用于 NL2SQL prompt）
        sample_rows = df.head(5).values.tolist()

        sheets.append(SheetInfo(
            sheet_index=idx,
            sheet_name=str(sheet_name),
            headers=headers,
            columns=columns,
            df=df,
            row_count=len(df),
            stats=stats,
            sample_rows=sample_rows,
        ))
    return sheets
