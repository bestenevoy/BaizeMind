"""Excel RAG 入库编排：解析 → 摘要+映射 → 元数据+数据入库 → 向量索引。

对外暴露:
- ingest_excel(doc_id, file_path): 完整入库流程
- delete_excel(doc_id): 删除该文档的所有 Sheet + 向量
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config.settings import settings
from src.embeddings.bge_m3 import BGEM3Embedding
from src.excel_rag import store as excel_store
from src.excel_rag.parser import parse_excel
from src.excel_rag.summarizer import generate_summary
from src.excel_rag.vector_store import ExcelVectorStore

logger = logging.getLogger(__name__)


def ingest_excel(doc_id: str, file_path: str | Path) -> dict[str, Any]:
    """完整 Excel 入库流程。返回 {sheets, sheet_count}。"""
    file_path = Path(file_path)

    # 先清理可能存在的旧数据（重试场景）
    delete_excel(doc_id)

    sheets = parse_excel(file_path)
    if not sheets:
        return {"sheets": [], "sheet_count": 0}

    # 逐 Sheet：摘要 → 元数据/数据入库
    sheet_records: list[dict[str, Any]] = []
    for sheet in sheets:
        summary, columns = generate_summary(sheet)
        record = excel_store.create_sheet(
            doc_id=doc_id,
            sheet_index=sheet.sheet_index,
            sheet_name=sheet.sheet_name,
            columns=columns,
            summary=summary,
            df=sheet.df,
        )
        record["summary"] = summary
        sheet_records.append(record)

    # 向量索引：一次性嵌入所有 Sheet 摘要
    try:
        embedding = BGEM3Embedding()
        texts = [s["summary"] for s in sheet_records]
        embeddings = embedding.encode_dense_all(texts, batch_size=settings.bge_m3_batch_size, concurrency=4)
        vs = ExcelVectorStore()
        vs.ensure_collection()
        vs.insert(sheet_records, embeddings)
    except Exception as e:
        logger.error(f"Excel vector indexing failed for doc {doc_id}: {e}")
        # 向量失败不回滚已入库的元数据/明细数据（查询时仍可降级为全表扫描）
        raise

    return {"sheets": sheet_records, "sheet_count": len(sheet_records)}


def delete_excel(doc_id: str) -> int:
    """删除文档关联的所有 Sheet 元数据 + 动态数据表 + 向量。返回删除表数。"""
    # 向量
    try:
        vs = ExcelVectorStore()
        vs.ensure_collection()
        vs.delete_by_doc(doc_id)
    except Exception as e:
        logger.warning(f"Excel vector delete failed for doc {doc_id}: {e}")
    # 元数据 + 数据表
    return excel_store.delete_sheets_by_doc(doc_id)
