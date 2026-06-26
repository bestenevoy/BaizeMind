"""Document parser factory.

根据 ``settings.parser_backend`` 选择实际解析器（MinerU 或 PaddleOCR-VL），
返回统一格式的解析结果::

    {
        "doc_id": str,
        "markdown": str,
        "content_list": list,
        "output_dir": str,
    }
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config.settings import settings


def get_parser(backend: str | None = None):
    """根据 backend 名称返回 parser 实例。

    参数：
        backend: ``"mineru"`` 或 ``"paddleocr_vl"``；为 None 时使用
                 ``settings.parser_backend``。

    返回值拥有 ``parse(file_path, doc_id)`` 方法，调用后返回统一 dict。
    """
    backend = (backend or settings.parser_backend or "mineru").lower()
    if backend == "mineru":
        from src.document_parser.mineru_parser import MinerUParser
        return MinerUParser()
    if backend in ("paddleocr_vl", "paddleocr", "paddleocr-vl"):
        from src.document_parser.ocr_parser import PaddleOCRParser
        return PaddleOCRParser()
    raise ValueError(
        f"Unknown parser backend: {backend!r}. Expected 'mineru' or 'paddleocr_vl'."
    )


def parse_document(file_path: str | Path, doc_id: str, backend: str | None = None) -> dict[str, Any]:
    """统一入口：解析文档并返回 {doc_id, markdown, content_list, output_dir}。"""
    parser = get_parser(backend)
    result = parser.parse(file_path, doc_id)
    # PaddleOCR 解析器不返回 content_list 字段；补一个空列表以便下游统一处理
    if "content_list" not in result:
        result["content_list"] = []
    return result


def output_dir_for(backend: str | None = None, doc_id: str = "") -> Path:
    """根据 backend 返回对应的输出目录。"""
    backend = (backend or settings.parser_backend or "mineru").lower()
    if backend in ("paddleocr_vl", "paddleocr", "paddleocr-vl"):
        return Path(settings.paddleocr_output_dir) / doc_id
    return Path(settings.mineru_output_dir) / doc_id
