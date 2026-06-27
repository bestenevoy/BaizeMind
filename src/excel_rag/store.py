"""Excel RAG 存储：元数据表 + 动态数据表（复用现有 SQLite documents.db）。

- excel_sheets: 每个 Sheet 一行元数据（meta_id, doc_id, table_name, columns_json, ...）
- excel_data_<doc_id>_<sheet_idx>: 动态创建的明细数据表
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from config.settings import settings

# 复用 doc_store 的同一个 SQLite 数据库，避免多库管理
DB_PATH = settings.data_dir / "documents.db"

# 合法标识符：仅允许字母数字下划线（防 SQL 注入，表名/列名拼接时安全）
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_excel_tables():
    """初始化 excel_sheets 元数据表（幂等）。"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS excel_sheets (
            meta_id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            sheet_index INTEGER NOT NULL,
            sheet_name TEXT NOT NULL,
            table_name TEXT NOT NULL,
            columns_json TEXT NOT NULL,
            summary TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_excel_sheets_doc ON excel_sheets(doc_id);
    """)
    conn.close()


# 模块导入时自动初始化
init_excel_tables()


def _make_table_name(doc_id: str, sheet_index: int) -> str:
    """生成安全的动态表名: excel_data_<doc_id>_<sheet_idx>"""
    safe_doc = re.sub(r"[^A-Za-z0-9_]", "_", doc_id)
    return f"excel_data_{safe_doc}_{sheet_index}"


def _validate_identifier(name: str) -> str:
    """校验列名/表名为合法 SQLite 标识符，返回清洗后的值。"""
    if not name or not _IDENT_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


def create_sheet(
    doc_id: str,
    sheet_index: int,
    sheet_name: str,
    columns: list[dict[str, str]],
    summary: str,
    df: pd.DataFrame,
) -> dict[str, Any]:
    """创建元数据记录 + 动态数据表并导入明细数据。

    columns: [{"display_name": str, "column_name": str, "data_type": str}, ...]
      - display_name: 实际显示字段（原始表头，支持中英文，不参与 SQL 生成）
      - column_name: 数据库表字段名（snake_case 英文标识符，用于建表 + SQL 生成）
      - data_type: 字段数据类型（INTEGER / REAL / TEXT）
    返回创建的元数据 dict。
    """
    meta_id = f"excel_{uuid.uuid4().hex[:16]}"
    table_name = _make_table_name(doc_id, sheet_index)
    now = datetime.now().isoformat()

    # 构造 CREATE TABLE（列名已校验为安全标识符）
    col_defs = ['"id" INTEGER PRIMARY KEY AUTOINCREMENT']
    en_names: list[str] = []
    for col in columns:
        en = _validate_identifier(col["column_name"])
        col_type = col["data_type"] if col["data_type"] in ("INTEGER", "REAL", "TEXT") else "TEXT"
        col_defs.append(f'"{en}" {col_type}')
        en_names.append(en)
    create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(col_defs)})'

    conn = _get_conn()
    try:
        conn.execute(create_sql)
        # 批量导入数据（按 column_name 对应；df 列名为 display_name，需先映射）
        if not df.empty and en_names:
            # df 列名是原始表头，按 columns 顺序映射到 column_name
            display_to_column = {c["display_name"]: c["column_name"] for c in columns}
            ordered_display = [c["display_name"] for c in columns]
            # 只保留存在的列
            existing_display = [c for c in ordered_display if c in df.columns]
            if existing_display:
                sub_df = df[existing_display].copy()
                sub_df.columns = [display_to_column[c] for c in existing_display]
                # NaN → None（SQLite NULL）
                sub_df = sub_df.where(pd.notna(sub_df), None)
                placeholders = ", ".join("?" * len(sub_df.columns))
                col_list = ", ".join(f'"{_validate_identifier(c)}"' for c in sub_df.columns)
                insert_sql = f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})'
                conn.executemany(insert_sql, sub_df.values.tolist())
        row_count = df.shape[0]
        conn.execute(
            """INSERT INTO excel_sheets (meta_id, doc_id, sheet_index, sheet_name, table_name,
               columns_json, summary, row_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (meta_id, doc_id, sheet_index, sheet_name, table_name,
             json.dumps(columns, ensure_ascii=False), summary, row_count, now),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "meta_id": meta_id,
        "doc_id": doc_id,
        "sheet_index": sheet_index,
        "sheet_name": sheet_name,
        "table_name": table_name,
        "columns": columns,
        "summary": summary,
        "row_count": row_count,
    }


def _normalize_columns(columns: list[dict[str, Any]]) -> list[dict[str, str]]:
    """统一列结构字段名，兼容旧数据（cn/en/type → display_name/column_name/data_type）。

    旧版 schema: {"cn": str, "en": str, "type": str}
    新版 schema: {"display_name": str, "column_name": str, "data_type": str}
    """
    out = []
    for c in columns:
        if not isinstance(c, dict):
            continue
        # 优先用新字段，缺失时回退到旧字段名
        display_name = c.get("display_name") or c.get("cn") or ""
        column_name = c.get("column_name") or c.get("en") or ""
        data_type = c.get("data_type") or c.get("type") or "TEXT"
        out.append({
            "display_name": str(display_name),
            "column_name": str(column_name),
            "data_type": str(data_type),
        })
    return out


def format_columns_for_llm(columns: list[dict[str, str]]) -> str:
    """把列结构格式化为 LLM 可读的 markdown 表格（全系统唯一规范格式）。

    输出格式（表头即字段标签，自文档化，无需在 prompt 中解释字段位置）：

        | column_name | data_type | display_name |
        |-------------|-----------|--------------|
        | segment     | TEXT      | Segment      |
        | sales_amount| REAL      | 销售额        |

    设计原则：
    - column_name 放第一列：SQL 生成的核心标识符，LLM 直接看首列即可
    - data_type 放第二列：类型判断紧随其后
    - display_name 放第三列：人类可读名，仅用于理解用户问题指向的字段
    - 表头与 EXCEL_SUMMARY_SYSTEM 输出的 JSON 字段名一致，生成与消费同源

    所有 LLM-facing 的列结构拼接（NL2SQL / answer 生成 / 检索上下文 / chunk text）
    必须调用此函数，禁止各处自行拼格式。
    """
    if not columns:
        return "(no columns)"
    lines = ["| column_name | data_type | display_name |", "|-------------|-----------|--------------|"]
    for c in columns:
        cn = str(c.get("column_name", "")).replace("|", "\\|")
        dt = str(c.get("data_type", "TEXT")).replace("|", "\\|")
        dn = str(c.get("display_name", "")).replace("|", "\\|")
        lines.append(f"| {cn} | {dt} | {dn} |")
    return "\n".join(lines)


def get_sheet(meta_id: str) -> Optional[dict[str, Any]]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM excel_sheets WHERE meta_id = ?", (meta_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["columns"] = _normalize_columns(json.loads(d["columns_json"]))
    return d


def list_sheets_by_doc(doc_id: str) -> list[dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM excel_sheets WHERE doc_id = ? ORDER BY sheet_index",
        (doc_id,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["columns"] = _normalize_columns(json.loads(d["columns_json"]))
        out.append(d)
    return out


def list_all_sheets() -> list[dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM excel_sheets ORDER BY created_at DESC").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["columns"] = _normalize_columns(json.loads(d["columns_json"]))
        out.append(d)
    return out


def delete_sheets_by_doc(doc_id: str) -> int:
    """删除文档关联的所有 Sheet 元数据 + 动态数据表。返回删除的表数。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT meta_id, table_name FROM excel_sheets WHERE doc_id = ?",
        (doc_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return 0

    conn = _get_conn()
    try:
        for r in rows:
            table_name = r["table_name"]
            if _IDENT_RE.match(table_name):
                conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        conn.execute("DELETE FROM excel_sheets WHERE doc_id = ?", (doc_id,))
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def execute_sql(table_name: str, sql: str, timeout_ms: int | None = None) -> dict[str, Any]:
    """在 SQLite 上执行只读 SELECT，返回 {columns, rows, row_count}。

    - 使用独立只读连接，避免影响主库
    - 设置执行超时
    """
    timeout_ms = timeout_ms or settings.excel_sql_timeout_ms
    # row_factory 不用 Row，直接返回 tuple 保持顺序
    conn = sqlite3.connect(str(DB_PATH), timeout=timeout_ms / 1000)
    try:
        conn.execute(f"PRAGMA query_only = 1")  # 只读模式，禁止任何写操作
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return {"columns": columns, "rows": rows, "row_count": len(rows)}
    finally:
        conn.close()
