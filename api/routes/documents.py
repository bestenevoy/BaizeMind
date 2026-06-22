import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from api.schemas import (
    DocumentUploadResponse,
    DocumentStatusResponse,
    DocumentContentResponse,
    DocumentInfo,
    FolderInfo,
    TagInfo,
    MoveRequest,
    TagRequest,
)
from src.storage import doc_store
from config.settings import settings

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    folder: str = Form("/"),
):
    folder = ("/" + folder.strip("/")) if folder != "/" else "/"

    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = {"pdf", "docx", "pptx", "xlsx", "png", "jpg", "jpeg", "txt", "md"}

    if ext not in allowed:
        raise HTTPException(400, f"Unsupported file type: .{ext}")

    doc_id = str(uuid.uuid4())[:12]
    save_dir = Path(settings.raw_dir) / folder.lstrip("/")
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"{doc_id}.{ext}"

    content = await file.read()
    save_path.write_bytes(content)

    doc_store.create_document(doc_id, filename, folder, str(save_path))

    background_tasks.add_task(_process_document, doc_id, str(save_path), folder)

    return DocumentUploadResponse(
        doc_id=doc_id,
        filename=filename,
        folder=folder,
        status="pending",
        message="Document uploaded. Processing started.",
    )


@router.get("/list", response_model=list[DocumentInfo])
async def list_documents(
    folder: Optional[str] = None,
    tags: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    docs = doc_store.list_documents(folder=folder, tags=tag_list, status=status, limit=limit, offset=offset)
    return [DocumentInfo(**d) for d in docs]


@router.get("/folders", response_model=list[FolderInfo])
async def list_folders():
    return [FolderInfo(**f) for f in doc_store.list_folders()]


@router.get("/tags", response_model=list[TagInfo])
async def list_tags():
    return [TagInfo(**t) for t in doc_store.list_all_tags()]


@router.get("/status/{doc_id}", response_model=DocumentStatusResponse)
async def get_document_status(doc_id: str):
    doc = doc_store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found")
    return DocumentStatusResponse(
        doc_id=doc_id,
        status=doc["status"],
        processing_stage=doc.get("processing_stage", ""),
        chunk_count=doc["chunk_count"],
        processing_time_ms=doc["processing_time_ms"],
        error=doc.get("error"),
    )


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    doc = doc_store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found")

    try:
        from src.retrieval.vector_retriever import MilvusVectorRetriever
        vr = MilvusVectorRetriever()
        vr.delete_by_doc(doc_id)
    except Exception:
        pass

    try:
        from src.retrieval.bm25_retriever import BM25Retriever
        bm25 = BM25Retriever()
        bm25.load()
        bm25.remove_by_doc_id(doc_id)
    except Exception:
        pass

    try:
        from src.knowledge_graph.neo4j_manager import Neo4jManager
        neo4j = Neo4jManager()
        neo4j.delete_entities_by_doc(doc_id)
    except Exception:
        pass

    doc_store.delete_document(doc_id)
    return {"status": "deleted", "doc_id": doc_id}


@router.put("/{doc_id}/move", response_model=DocumentInfo)
async def move_document(doc_id: str, req: MoveRequest):
    folder = req.folder
    if folder and folder != "/":
        folder = "/" + folder.strip("/")
    doc = doc_store.move_document(doc_id, folder)
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found")
    return DocumentInfo(**doc)


@router.post("/{doc_id}/tags", response_model=DocumentInfo)
async def add_tag(doc_id: str, req: TagRequest):
    doc = doc_store.add_tag(doc_id, req.tag)
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found")
    return DocumentInfo(**doc)


@router.get("/{doc_id}/content", response_model=DocumentContentResponse)
async def get_document_content(doc_id: str):
    doc = doc_store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found")

    file_path = doc.get("file_path", "")
    original = ""
    is_binary = False
    file_ext = ""
    file_size_kb = 0.0

    if file_path:
        fp = Path(file_path)
        if not fp.exists():
            original = "(文件已被删除)"
        else:
            file_ext = fp.suffix.lower()
            try:
                original = fp.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                is_binary = True
                file_size_kb = fp.stat().st_size / 1024
                if file_ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"):
                    original = "图片文件，请在下方链接查看"
                else:
                    original = f"二进制文件 ({file_ext})"

    parsed = ""
    processed_dir = Path(settings.mineru_output_dir) / doc_id
    if processed_dir.exists():
        for f in processed_dir.rglob("*.md"):
            try:
                parsed = f.read_text(encoding="utf-8")
            except Exception:
                pass
            break

    raw_url = f"/api/v1/documents/{doc_id}/raw" if is_binary else ""

    return DocumentContentResponse(
        doc_id=doc_id,
        filename=doc.get("filename", ""),
        original_content=original,
        parsed_markdown=parsed,
        raw_url=raw_url,
        is_binary=is_binary,
        file_ext=file_ext,
        file_size_kb=file_size_kb,
        status=doc.get("status", ""),
    )


@router.get("/{doc_id}/raw")
async def get_document_raw(doc_id: str):
    from fastapi.responses import FileResponse
    doc = doc_store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found")

    file_path = doc.get("file_path", "")
    fp = Path(file_path)
    if not fp.exists():
        raise HTTPException(404, "Original file not found on disk")

    import mimetypes
    media_type = mimetypes.guess_type(fp.name)[0] or "application/octet-stream"
    return FileResponse(fp, media_type=media_type, filename=doc.get("filename", fp.name))


@router.post("/{doc_id}/retry", response_model=DocumentUploadResponse)
async def retry_document(doc_id: str, background_tasks: BackgroundTasks):
    doc = doc_store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found")
    if doc["status"] != "failed":
        raise HTTPException(400, f"Document {doc_id} is not in failed status (current: {doc['status']})")

    file_path = doc.get("file_path", "")
    folder = doc.get("folder", "/")
    if not file_path or not Path(file_path).exists():
        raise HTTPException(400, f"Original file for {doc_id} no longer exists")

    doc_store.update_document(doc_id, status="pending", error=None)
    background_tasks.add_task(_process_document, doc_id, file_path, folder)

    return DocumentUploadResponse(
        doc_id=doc_id,
        filename=doc.get("filename", ""),
        folder=folder,
        status="pending",
        message="Reprocessing started.",
    )


@router.delete("/{doc_id}/tags/{tag}", response_model=DocumentInfo)
async def remove_tag(doc_id: str, tag: str):
    doc = doc_store.remove_tag(doc_id, tag)
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found")
    return DocumentInfo(**doc)


def _process_document(doc_id: str, file_path: str, folder: str):
    import time
    start = time.time()

    try:
        doc_store.update_document(doc_id, processing_stage="解析文档")
        from src.document_parser.mineru_parser import MinerUParser
        parser = MinerUParser()
        result = parser.parse(file_path, doc_id)
        markdown = result.get("markdown", "")

        doc_store.update_document(doc_id, processing_stage="切分文本块")
        from src.chunker.hierarchical_chunker import HierarchicalChunker
        from src.chunker.table_chunker import TableChunker
        from src.chunker.context_merger import ContextMerger
        from src.document_parser.table_parser import TableParser

        h_chunker = HierarchicalChunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
        chunks = h_chunker.chunk(doc_id, markdown)

        tables = TableParser.extract_tables_from_markdown(markdown)
        table_chunks = TableChunker().chunk_tables(doc_id, tables)
        chunks.extend(table_chunks)

        merger = ContextMerger()
        chunks = merger.merge(chunks)
        chunks = merger.deduplicate(chunks)
        chunks = [c for c in chunks if c["text"].strip()]

        for chunk in chunks:
            chunk["folder"] = folder

        doc_store.update_document(doc_id, processing_stage="向量嵌入")
        from src.embeddings.bge_m3 import BGEM3Embedding
        from src.retrieval.vector_retriever import MilvusVectorRetriever

        embedding = BGEM3Embedding()
        texts = [c["text"] for c in chunks]
        embeddings = embedding.encode_dense_all(texts, batch_size=settings.bge_m3_batch_size, concurrency=8)

        doc_store.update_document(doc_id, processing_stage="写入向量库")
        vector_retriever = MilvusVectorRetriever()
        vector_retriever.ensure_collection()
        vector_retriever.insert(chunks, embeddings)

        doc_store.update_document(doc_id, processing_stage="构建BM25索引")
        from src.retrieval.bm25_retriever import BM25Retriever
        bm25 = BM25Retriever()
        bm25.load()
        bm25.merge_chunks(chunks)
        bm25.save()

        doc_store.update_document(doc_id, processing_stage="构建知识图谱")
        from src.knowledge_graph.entity_extractor import EntityExtractor
        from src.knowledge_graph.neo4j_manager import Neo4jManager

        extractor = EntityExtractor()
        extracted = extractor.extract_from_chunks(chunks)
        entities = [e for e in extracted if "type" in e and "name" in e]
        relations = [r for r in extracted if "predicate" in r]

        neo4j = Neo4jManager()
        neo4j.connect()
        neo4j.init_schema()
        neo4j.batch_import(entities, relations, doc_id=doc_id)

        doc_store.update_document(doc_id, processing_stage="自动标签")
        from src.storage.auto_tagger import generate_tags
        tags = generate_tags(markdown)
        if tags:
            doc_store.update_document(doc_id, tags=tags)

        elapsed = (time.time() - start) * 1000
        doc_store.update_document(doc_id, status="completed", processing_stage="完成", chunk_count=len(chunks), processing_time_ms=elapsed)

    except Exception as e:
        elapsed = (time.time() - start) * 1000
        doc_store.update_document(doc_id, status="failed", processing_time_ms=elapsed, error=str(e))


# ── Folder Management ──

class FolderCreateRequest(BaseModel):
    path: str = Field(..., description="Folder path e.g. /myfolder")


class FolderMoveRequest(BaseModel):
    src: str = Field(..., description="Source folder path")
    dst: str = Field(..., description="Destination folder path")


@router.post("/folders")
async def create_folder(req: FolderCreateRequest):
    return doc_store.create_folder(req.path)


@router.delete("/folders/{folder_path:path}")
async def delete_folder(folder_path: str):
    path = "/" + folder_path.lstrip("/")
    has_docs = doc_store._folder_has_docs(path)

    # Collect doc_ids before deletion
    docs = doc_store.list_documents(folder=path, limit=10000)

    count = doc_store.delete_folder(path)
    if not has_docs and count == 0:
        doc_store.delete_folder_marker(path)

    # Clean up Milvus, BM25, Neo4j for deleted docs
    for d in docs:
        did = d["doc_id"]
        try:
            from src.retrieval.vector_retriever import MilvusVectorRetriever
            vr = MilvusVectorRetriever()
            vr.delete_by_doc(did)
        except Exception:
            pass
        try:
            from src.retrieval.bm25_retriever import BM25Retriever
            bm25 = BM25Retriever()
            bm25.load()
            bm25.remove_by_doc_id(did)
        except Exception:
            pass
        try:
            from src.knowledge_graph.neo4j_manager import Neo4jManager
            neo4j = Neo4jManager()
            neo4j.delete_entities_by_doc(did)
        except Exception:
            pass

    return {"deleted": True, "folder": path, "doc_count": count, "cleaned_vectors": True}


@router.put("/folders/move")
async def move_folder_endpoint(req: FolderMoveRequest):
    count = doc_store.move_folder(req.src, req.dst)
    return {"moved": True, "src": req.src, "dst": req.dst, "doc_count": count}
