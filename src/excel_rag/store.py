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

    columns: [{"cn": str, "en": str, "type": str}, ...]
    返回创建的元数据 dict。
    """
    meta_id = f"excel_{uuid.uuid4().hex[:16]}"
    table_name = _make_table_name(doc_id, sheet_index)
    now = datetime.now().isoformat()

    # 构造 CREATE TABLE（列名已校验为安全标识符）
    col_defs = ['"id" INTEGER PRIMARY KEY AUTOINCREMENT']
    en_names: list[str] = []
    for col in columns:
        en = _validate_identifier(col["en"])
        col_type = col["type"] if col["type"] in ("INTEGER", "REAL", "TEXT") else "TEXT"
        col_defs.append(f'"{en}" {col_type}')
        en_names.append(en)
    create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(col_defs)})'

    conn = _get_conn()
    try:
        conn.execute(create_sql)
        # 批量导入数据（按英文列名对应）
        if not df.empty and en_names:
            # df 列名是中文表头，按 columns 顺序映射到英文列名
            cn_to_en = {c["cn"]: c["en"] for c in columns}
            ordered_cn = [c["cn"] for c in columns]
            # 只保留存在的列
            existing_cn = [c for c in ordered_cn if c in df.columns]
            if existing_cn:
                sub_df = df[existing_cn].copy()
                sub_df.columns = [cn_to_en[c] for c in existing_cn]
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


def get_sheet(meta_id: str) -> Optional[dict[str, Any]]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM excel_sheets WHERE meta_id = ?", (meta_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["columns"] = json.loads(d["columns_json"])
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
        d["columns"] = json.loads(d["columns_json"])
        out.append(d)
    return out


def list_all_sheets() -> list[dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM excel_sheets ORDER BY created_at DESC").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["columns"] = json.loads(d["columns_json"])
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
