"""Excel RAG 问答路由。

- POST /api/v1/excel/ask: 针对已入库 Excel 的自然语言问答（NL2SQL）
- GET  /api/v1/excel/sheets: 列出所有已入库 Sheet
- GET  /api/v1/excel/sheets/{doc_id}: 列出指定文档的 Sheet
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.auth import User, enforce_guest_query_limit, get_current_user_optional
from src.excel_rag import store as excel_store
from src.excel_rag.qa import ExcelQA

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/excel", tags=["excel"])


class ExcelAskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096, description="自然语言问题")
    folder: Optional[str] = Field(None, description="按文件夹过滤 Excel")
    tags: Optional[list[str]] = Field(None, description="按标签过滤 Excel")


class RecalledSheet(BaseModel):
    meta_id: str
    doc_id: str = ""
    sheet_name: str = ""
    summary: str = ""
    score: float = 0.0


class ExcelAskResponse(BaseModel):
    query: str
    answer: str
    sql: str = ""
    sheet_meta_id: str = ""
    sheet_name: str = ""
    recalled_sheets: list[RecalledSheet] = []
    attempts: list[dict[str, Any]] = []
    error: str = ""
    processing_time_ms: float = 0.0


class SheetInfoResponse(BaseModel):
    meta_id: str
    doc_id: str
    sheet_index: int
    sheet_name: str
    table_name: str
    row_count: int
    summary: str
    columns: list[dict[str, str]] = []
    created_at: str = ""


@router.post("/ask", response_model=ExcelAskResponse)
async def ask_excel(req: ExcelAskRequest, current: User = Depends(get_current_user_optional)):
    """对已入库的 Excel 报表进行自然语言问答（RAG + NL2SQL）。"""
    enforce_guest_query_limit(req.query, current)
    start = time.time()
    try:
        qa = ExcelQA()
        result = qa.ask(req.query, folder=req.folder, tags=req.tags)
        elapsed = (time.time() - start) * 1000
        recalled = [
            RecalledSheet(
                meta_id=r.get("meta_id", ""),
                doc_id=r.get("doc_id", ""),
                sheet_name=r.get("sheet_name", ""),
                summary=r.get("summary", "")[:500],
                score=r.get("score", 0.0),
            )
            for r in result.get("recalled_sheets", [])
        ]
        return ExcelAskResponse(
            query=req.query,
            answer=result.get("answer", ""),
            sql=result.get("sql", ""),
            sheet_meta_id=result.get("sheet_meta_id", ""),
            sheet_name=result.get("sheet_name", ""),
            recalled_sheets=recalled,
            attempts=result.get("attempts", []),
            error=result.get("error", ""),
            processing_time_ms=elapsed,
        )
    except Exception as e:
        logger.error(f"Excel QA failed: {e}", exc_info=True)
        raise HTTPException(500, f"Excel QA processing failed: {e}")


@router.get("/sheets", response_model=list[SheetInfoResponse])
async def list_all_sheets():
    """列出所有已入库的 Excel Sheet。"""
    sheets = excel_store.list_all_sheets()
    return [
        SheetInfoResponse(
            meta_id=s["meta_id"],
            doc_id=s["doc_id"],
            sheet_index=s["sheet_index"],
            sheet_name=s["sheet_name"],
            table_name=s["table_name"],
            row_count=s["row_count"],
            summary=s["summary"][:500],
            columns=s["columns"],
            created_at=s.get("created_at", ""),
        )
        for s in sheets
    ]


@router.get("/sheets/{doc_id}", response_model=list[SheetInfoResponse])
async def list_sheets_by_doc(doc_id: str):
    """列出指定文档的 Sheet。"""
    sheets = excel_store.list_sheets_by_doc(doc_id)
    if not sheets:
        raise HTTPException(404, f"No Excel sheets found for document {doc_id}")
    return [
        SheetInfoResponse(
            meta_id=s["meta_id"],
            doc_id=s["doc_id"],
            sheet_index=s["sheet_index"],
            sheet_name=s["sheet_name"],
            table_name=s["table_name"],
            row_count=s["row_count"],
            summary=s["summary"][:500],
            columns=s["columns"],
            created_at=s.get("created_at", ""),
        )
        for s in sheets
    ]
