"""Excel RAG 查询编排：向量召回 → 多表选择 → NL2SQL → 执行 → 回答。

对应 EXCEL_RAG.md 第六节查询流程：
1. Query Embedding
2. Qdrant(→Milvus) TopK 检索返回 meta_id
3. 查询 Metadata 获取 Schema
4. Prompt Builder 构造 NL2SQL Prompt
5. LLM 生成 SQL
6. SQLite 执行 SQL
7. LLM 整理生成最终回答
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from config.prompts import EXCEL_TABLE_SELECTOR_SYSTEM
from config.settings import settings
from src.embeddings.bge_m3 import BGEM3Embedding
from src.excel_rag import store as excel_store
from src.excel_rag.nl2sql import execute_with_retry, format_answer
from src.excel_rag.vector_store import ExcelVectorStore
from src.llm.deepseek import get_chat_llm

logger = logging.getLogger(__name__)


class ExcelQA:
    def __init__(self):
        self._embedding = None
        self._vector_store = None
        self._llm = None

    def _get_embedding(self) -> BGEM3Embedding:
        if self._embedding is None:
            self._embedding = BGEM3Embedding()
        return self._embedding

    def _get_vector_store(self) -> ExcelVectorStore:
        if self._vector_store is None:
            self._vector_store = ExcelVectorStore()
        return self._vector_store

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm(temperature=0.0)
        return self._llm

    def retrieve(
        self,
        query: str,
        folder: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """纯检索阶段：向量召回 → 多表选择 → NL2SQL → 执行（含重试）。

        不调用 LLM 生成回答。返回中间产物，供统一生成链路（answer_generator）使用。
        返回:
            {recalled_sheets, selected_sheet, sql, sql_result, attempts, error}
        其中 selected_sheet / sql / sql_result 在失败场景下可能为空。
        """
        # ── 1. 向量召回 TopK Sheet ──
        recalled = self._recall_sheets(query, folder=folder, tags=tags)
        if not recalled:
            return {
                "recalled_sheets": [], "selected_sheet": None,
                "sql": "", "sql_result": None, "attempts": [],
                "error": "no_sheets",
            }

        # ── 2. 多表选择 ──
        selected = self._select_table(query, recalled)
        if not selected:
            return {
                "recalled_sheets": recalled, "selected_sheet": None,
                "sql": "", "sql_result": None, "attempts": [],
                "error": "no_relevant_sheet",
            }

        sheet_meta = selected["sheet_meta"]

        # ── 3 & 4 & 5 & 6. NL2SQL → 校验 → 执行（含自动修正重试）──
        exec_result = execute_with_retry(sheet_meta, query)

        return {
            "recalled_sheets": recalled,
            "selected_sheet": selected,
            "sql": exec_result.get("sql", ""),
            "sql_result": exec_result.get("result"),
            "attempts": exec_result.get("attempts", []),
            "error": exec_result.get("error", ""),
        }

    def ask(
        self,
        query: str,
        folder: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """完整查询流程（检索 + 生成）。给独立 /api/v1/excel/ask 端点用。

        返回: {answer, sql, sheet_meta_id, sheet_name, recalled_sheets, attempts, error}
        """
        r = self.retrieve(query, folder=folder, tags=tags)

        if r["error"] in ("no_sheets", "no_relevant_sheet"):
            return {
                "answer": "未找到匹配的 Excel 报表。请先上传 .xlsx 文件或换一种问法。",
                "sql": "", "sheet_meta_id": "", "sheet_name": "",
                "recalled_sheets": r["recalled_sheets"], "attempts": [], "error": r["error"],
            }

        selected = r["selected_sheet"]
        sheet_meta = selected["sheet_meta"]

        if r["error"] and not r["sql_result"]:
            return {
                "answer": f"无法生成有效查询：{r['error']}",
                "sql": r["sql"],
                "sheet_meta_id": selected["meta_id"],
                "sheet_name": sheet_meta["sheet_name"],
                "recalled_sheets": r["recalled_sheets"],
                "attempts": r["attempts"],
                "error": r["error"],
            }

        # LLM 整理最终回答
        answer = format_answer(query, r["sql"], r["sql_result"])

        return {
            "answer": answer,
            "sql": r["sql"],
            "sheet_meta_id": selected["meta_id"],
            "sheet_name": sheet_meta["sheet_name"],
            "recalled_sheets": r["recalled_sheets"],
            "attempts": r["attempts"],
            "error": "",
        }

    def _recall_sheets(
        self,
        query: str,
        folder: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """向量召回 TopK Sheet，返回带 meta_id 的候选列表。"""
        try:
            embedding = self._get_embedding()
            query_vec = embedding.encode_query_dense(query)
        except Exception as e:
            logger.error(f"Excel query embedding failed: {e}")
            return []

        # folder/tag 过滤 → doc_id 列表
        doc_ids = None
        if folder or tags:
            from src.storage.doc_store import get_doc_ids_by_filter
            doc_ids = get_doc_ids_by_filter(folder=folder, tags=tags)
            if not doc_ids:
                return []

        try:
            vs = self._get_vector_store()
            hits = vs.search(query_vec, top_k=settings.excel_recall_top_k, doc_ids=doc_ids)
        except Exception as e:
            logger.error(f"Excel vector search failed: {e}")
            return []

        # 拉取完整元数据
        recalled: list[dict[str, Any]] = []
        for hit in hits:
            sheet_meta = excel_store.get_sheet(hit["meta_id"])
            if sheet_meta:
                recalled.append({
                    "meta_id": hit["meta_id"],
                    "doc_id": hit["doc_id"],
                    "sheet_name": sheet_meta["sheet_name"],
                    "summary": sheet_meta["summary"],
                    "score": hit["score"],
                    "sheet_meta": sheet_meta,
                })
        return recalled

    def _select_table(
        self,
        query: str,
        recalled: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """TopK > 1 时让 LLM 选择最相关表；否则直接取 Top1。"""
        if len(recalled) == 1:
            return recalled[0]

        # 构造候选列表
        candidates = "\n".join(
            f'- meta_id: {r["meta_id"]}, sheet: "{r["sheet_name"]}", summary: {r["summary"][:200]}'
            for r in recalled
        )
        try:
            llm = self._get_llm()
            prompt = EXCEL_TABLE_SELECTOR_SYSTEM.format(
                candidates=candidates,
                question=query,
            )
            resp = llm.invoke(prompt)
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(text)
            selected_id = data.get("selected_meta_id")
            if not selected_id:
                return None
            for r in recalled:
                if r["meta_id"] == selected_id:
                    return r
            # LLM 选了一个不在列表里的 id，回退 Top1
            logger.warning(f"LLM selected unknown meta_id {selected_id}; falling back to Top1")
            return recalled[0]
        except Exception as e:
            logger.warning(f"Table selection failed ({e}); falling back to Top1")
            return recalled[0]
