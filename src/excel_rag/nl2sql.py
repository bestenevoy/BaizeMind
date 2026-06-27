"""NL2SQL: 生成 → 安全校验 → 执行 → 自动修正。

安全机制（对应 EXCEL_RAG.md 第七节异常处理）：
- SQL 校验：仅允许 SELECT，禁止 DELETE/UPDATE/DROP/INSERT/ALTER/CREATE/ATTACH/PRAGMA 等
- LIMIT 注入：缺失时自动追加，限制结果集大小
- 执行隔离：独立连接 + PRAGMA query_only（双保险，即便校验漏过也无法写入）
- 超时控制：SQLite busy timeout
- 自动修正：执行失败时把错误信息回喂 LLM，最多 N 轮

缓存策略：
- LLM 调用统一由 src/llm/cached_wrapper.py 的 CachedLLM 包装缓存
  （相同 model + temperature + messages 直接返回，无需本模块单独管理）
- SQL 校验/执行/重试都不缓存，每次都重走真实流程，保证数据最新
"""
from __future__ import annotations

import logging
import re
from typing import Any

from config.prompts import (
    EXCEL_ANSWER_SYSTEM,
    EXCEL_NL2SQL_CORRECTION_SYSTEM,
    EXCEL_NL2SQL_SYSTEM,
)
from config.settings import settings
from src.excel_rag import store as excel_store
from src.llm.deepseek import get_chat_llm

logger = logging.getLogger(__name__)


# 禁止的 SQL 关键字（不区分大小写）
_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|REPLACE|MERGE|TRUNCATE|VACUUM|REINDEX)\b",
    re.IGNORECASE,
)


class SQLSafetyError(Exception):
    """SQL 未通过安全校验。"""


def _strip_sql(text: str) -> str:
    """清洗 LLM 输出：去除 markdown fence、前后空白、结尾分号。"""
    s = text.strip()
    if s.startswith("```"):
        # 去除首行 ```sql / ```
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
    s = s.strip()
    # 去除结尾分号（执行时不必要）
    s = s.rstrip(";").strip()
    return s


def validate_sql(sql: str) -> str:
    """安全校验：返回清洗后的 SQL，或在非法时抛出 SQLSafetyError。"""
    sql = _strip_sql(sql)
    if not sql:
        raise SQLSafetyError("Empty SQL")
    # 必须以 SELECT 开头（允许前导空白/WITH）
    first = sql.lstrip().split(None, 1)[0].upper() if sql.lstrip() else ""
    if first not in ("SELECT", "WITH"):
        raise SQLSafetyError(f"Only SELECT/WITH allowed, got: {first}")
    # 禁止危险关键字
    m = _FORBIDDEN_RE.search(sql)
    if m:
        raise SQLSafetyError(f"Forbidden keyword: {m.group()}")
    return sql


def inject_limit(sql: str, max_rows: int) -> str:
    """若 SQL 缺少 LIMIT，追加一个。已有 LIMIT 则不重复添加。"""
    if re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        return sql
    return f"{sql.rstrip(';')} LIMIT {max_rows}"


def _format_columns_for_prompt(columns: list[dict[str, str]]) -> str:
    return "\n".join(f"- {c['cn']} → {c['en']} : {c['type']}" for c in columns)


def _format_sample_rows(columns: list[dict[str, str]], table_name: str) -> str:
    """从实际表取前 5 行作为 prompt 上下文。"""
    try:
        result = excel_store.execute_sql(table_name, f'SELECT * FROM "{table_name}" LIMIT 5')
        en_to_cn = {c["en"]: c["cn"] for c in columns}
        lines = []
        for row in result["rows"]:
            # row[0] 是 id 自增列，跳过
            vals = row[1:]
            pairs = [f"{en_to_cn.get(col, col)}={v}" for col, v in zip(result["columns"][1:], vals)]
            lines.append("  " + ", ".join(str(p) for p in pairs))
        return "\n".join(lines) if lines else "  (no rows)"
    except Exception as e:
        return f"  (sample fetch failed: {e})"


def generate_sql(
    sheet_meta: dict[str, Any],
    question: str,
    correction: dict[str, str] | None = None,
) -> str:
    """调用 LLM 生成 SQL。correction 非空时走修正 prompt。

    LLM 调用由 CachedLLM 统一缓存（相同 model + temperature + messages 命中即返回），
    本函数无需单独管理缓存。correction 路径的 messages 包含错误信息，自然不会命中首次生成的缓存。
    """
    llm = get_chat_llm(temperature=0.0)
    columns = sheet_meta["columns"]
    cols_text = _format_columns_for_prompt(columns)

    if correction:
        prompt = EXCEL_NL2SQL_CORRECTION_SYSTEM.format(
            error=correction["error"],
            previous_sql=correction["previous_sql"],
            table_name=sheet_meta["table_name"],
            columns=cols_text,
        )
        resp = llm.invoke(prompt)
    else:
        sample_text = _format_sample_rows(columns, sheet_meta["table_name"])
        system = EXCEL_NL2SQL_SYSTEM.format(
            table_name=sheet_meta["table_name"],
            columns=cols_text,
            sample_rows=sample_text,
            max_rows=settings.excel_sql_max_rows,
            question=question,
        )
        resp = llm.invoke([("system", system), ("human", question)])

    return _strip_sql(resp.content)


def execute_with_retry(
    sheet_meta: dict[str, Any],
    question: str,
) -> dict[str, Any]:
    """生成 → 校验 → 执行 → 失败自动修正。

    返回:
        {sql, result, attempts, error}
        - result 非空表示成功
        - error 非空表示最终失败
    """
    table_name = sheet_meta["table_name"]
    max_rows = settings.excel_sql_max_rows
    max_retries = settings.excel_sql_max_retries

    previous_sql = ""
    error = ""
    attempts: list[dict[str, str]] = []

    for attempt in range(1, max_retries + 2):  # 首次 + max_retries 次修正
        try:
            correction = {"error": error, "previous_sql": previous_sql} if previous_sql else None
            raw_sql = generate_sql(sheet_meta, question, correction=correction)
        except Exception as e:
            logger.error(f"NL2SQL generation failed (attempt {attempt}): {e}")
            return {"sql": "", "result": None, "attempts": attempts, "error": f"SQL generation failed: {e}"}

        try:
            sql = validate_sql(raw_sql)
            sql = inject_limit(sql, max_rows)
        except SQLSafetyError as e:
            attempts.append({"sql": raw_sql, "error": f"safety: {e}"})
            previous_sql = raw_sql
            error = str(e)
            if attempt > max_retries:
                return {"sql": raw_sql, "result": None, "attempts": attempts, "error": f"SQL safety check failed: {e}"}
            continue

        try:
            result = excel_store.execute_sql(table_name, sql)
            return {"sql": sql, "result": result, "attempts": attempts, "error": ""}
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}"
            attempts.append({"sql": sql, "error": err_msg})
            logger.warning(f"SQL execution failed (attempt {attempt}): {err_msg}")
            previous_sql = sql
            error = err_msg
            if attempt > max_retries:
                return {"sql": sql, "result": None, "attempts": attempts, "error": err_msg}

    return {"sql": "", "result": None, "attempts": attempts, "error": error or "unknown"}


def format_answer(
    question: str,
    sql: str,
    result: dict[str, Any],
) -> str:
    """调用 LLM 把 SQL 结果整理为自然语言回答。"""
    llm = get_chat_llm()
    # 结果序列化（限制行数避免超长）
    rows = result.get("rows", [])
    columns = result.get("columns", [])
    if rows:
        # 转为 list of dict 便于 LLM 理解
        preview = [dict(zip(columns, r)) for r in rows[:50]]
        result_text = _format_result_for_llm(preview)
        if len(rows) > 50:
            result_text += f"\n... ({len(rows)} rows total, showing first 50)"
    else:
        result_text = "(empty result)"

    prompt = EXCEL_ANSWER_SYSTEM.format(
        language=settings.response_language,
        question=question,
        sql=sql,
        result=result_text,
    )
    resp = llm.invoke(prompt)
    return resp.content.strip()


def _format_result_for_llm(rows: list[dict]) -> str:
    """把结果行格式化为 LLM 友好的文本。"""
    if not rows:
        return "(empty)"
    lines = []
    for i, row in enumerate(rows, 1):
        parts = [f"{k}={v}" for k, v in row.items()]
        lines.append(f"  {i}. {', '.join(parts)}")
    return "\n".join(lines)
