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
from src.retrieval.vector_retriever import MilvusVectorRetriever

logger = logging.getLogger(__name__)


def _build_sheet_summary_chunk(record: dict[str, Any]) -> dict[str, Any]:
    """把一个 Sheet 摘要构造成主 collection 的 chunk 结构。

    chunk_id 用 ``excel:{meta_id}`` 前缀形式，与普通文档 chunk 区分；
    metadata 标 source=excel_sheet 便于追溯/过滤，并保留 meta_id/sheet_name
    方便后续按需触发 NL2SQL 流程。

    chunk text 内嵌 [列结构] 字段映射（en→cn），让向量检索能按字段名命中，
    同时 LLM 在 answer_generator/sql_agent 阶段直接看到数据库字段名与业务名称的对应关系，
    避免 NL2SQL 生成大写列名（SQLite 虽大小写不敏感，但小写 en 与建表语句一致更稳妥）。
    """
    meta_id = record["meta_id"]
    sheet_name = record.get("sheet_name", "")
    summary = record.get("summary", "")
    doc_id = record["doc_id"]
    columns = record.get("columns", []) or []

    # 字段映射：column_name (data_type) → display_name，与 retrieval_agent.extract_context 拼接格式一致，
    # extract_context 检测到 [列结构] 已存在便不会重复拼接。
    col_lines = "\n".join(
        f"  - {c.get('column_name', '')} ({c.get('data_type', '')}) → {c.get('display_name', '')}"
        for c in columns if isinstance(c, dict) and c.get("column_name")
    )
    schema_block = f"\n[列结构]\n{col_lines}" if col_lines else ""

    text = (
        f"[数据源: Excel Sheet \"{sheet_name}\"]\n"
        f"{summary}{schema_block}"
    )

    return {
        "doc_id": doc_id,
        # 主 collection 的 PK 长度限制 256，"excel:" + meta_id 足够
        "chunk_id": f"excel:{meta_id}",
        "text": text,
        "metadata": {
            "source": "excel_sheet",
            "meta_id": meta_id,
            "sheet_name": sheet_name,
            "doc_id": doc_id,
        },
    }


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

    # 向量索引：一次性嵌入所有 Sheet 摘要，复用 embeddings 写两个 collection
    try:
        embedding = BGEM3Embedding()
        texts = [s["summary"] for s in sheet_records]
        embeddings = embedding.encode_dense_all(texts, batch_size=settings.bge_m3_batch_size, concurrency=4)

        # 1) Excel 专用 collection（给 sql_agent 走 NL2SQL 用）
        vs = ExcelVectorStore()
        vs.ensure_collection()
        vs.insert(sheet_records, embeddings)

        # 2) 主 collection（让文本检索也能搜到 sheet 摘要，避免 sql_agent fallback 时
        #    retrieval_agent 啥也搜不到；复用已嵌入的 embeddings，零额外嵌入成本）
        main_chunks = [_build_sheet_summary_chunk(r) for r in sheet_records]
        main_retriever = MilvusVectorRetriever()
        main_retriever.ensure_collection()
        main_retriever.insert(main_chunks, embeddings)
    except Exception as e:
        logger.error(f"Excel vector indexing failed for doc {doc_id}: {e}")
        # 向量失败不回滚已入库的元数据/明细数据（查询时仍可降级为全表扫描）
        raise

    return {"sheets": sheet_records, "sheet_count": len(sheet_records)}


def delete_excel(doc_id: str) -> int:
    """删除文档关联的所有 Sheet 元数据 + 动态数据表 + 向量。返回删除表数。"""
    # 向量：Excel 专用 collection
    try:
        vs = ExcelVectorStore()
        vs.ensure_collection()
        vs.delete_by_doc(doc_id)
    except Exception as e:
        logger.warning(f"Excel vector delete failed for doc {doc_id}: {e}")
    # 向量：主 collection 里的 sheet 摘要 chunk（按 doc_id 删，与普通文档同路径）
    try:
        main_retriever = MilvusVectorRetriever()
        main_retriever.ensure_collection()
        main_retriever.delete_by_doc(doc_id)
    except Exception as e:
        logger.warning(f"Main collection vector delete failed for doc {doc_id}: {e}")
    # 元数据 + 数据表
    return excel_store.delete_sheets_by_doc(doc_id)
