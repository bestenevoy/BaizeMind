import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from api.schemas import (
    DocumentUploadResponse,
    DocumentStatusResponse,
    DocumentContentResponse,
    DocumentChunksResponse,
    ChunkInfo,
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
    skip_evidence: bool = Form(False),
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

    background_tasks.add_task(_process_document, doc_id, str(save_path), folder, skip_evidence)

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

    await _delete_document_evidence(doc_id, doc)
    return {"status": "deleted", "doc_id": doc_id}


async def _delete_document_evidence(doc_id: str, doc: dict):
    from src.knowledge_graph.chunk_manager import (
        build_sync_tasks, process_chunk_ref_one_to_zero,
    )
    from src.knowledge_graph.graph_sync_worker import process_pending_tasks

    all_affected: dict[str, set[str]] = {}

    doc_store.mark_doc_chunk_refs_stale(doc_id)
    stale_hashes = doc_store.deactivate_stale_doc_chunk_refs(doc_id)

    for sh in stale_hashes:
        affected = process_chunk_ref_one_to_zero(sh)
        for item in affected:
            t = item["affected_type"]
            k = item["affected_key"]
            if t not in all_affected:
                all_affected[t] = set()
            all_affected[t].add(k)

    if all_affected:
        tasks = build_sync_tasks(all_affected, doc_id=doc_id)
        doc_store.create_sync_tasks_batch(tasks)
        from src.knowledge_graph.graph_sync_worker import process_pending_tasks
        for _ in range(20):
            r = process_pending_tasks()
            if r["success"] + r["failed"] == 0:
                break

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

    doc_store.delete_document(doc_id)


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
    # 优先 mineru_output_dir，若不存在则尝试 paddleocr_output_dir
    processed_dir = Path(settings.mineru_output_dir) / doc_id
    if not processed_dir.exists():
        processed_dir = Path(settings.paddleocr_output_dir) / doc_id
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


@router.get("/{doc_id}/chunks", response_model=DocumentChunksResponse)
async def get_document_chunks(doc_id: str):
    doc = doc_store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found")

    from src.retrieval.vector_retriever import MilvusVectorRetriever
    vr = MilvusVectorRetriever()
    chunks = vr.get_chunks_by_doc(doc_id)
    return DocumentChunksResponse(
        doc_id=doc_id,
        chunks=[ChunkInfo(
            chunk_id=c.get("chunk_id", ""),
            text=c.get("text", ""),
            heading=c.get("metadata", {}).get("heading", "") if isinstance(c.get("metadata"), dict) else "",
            metadata=c.get("metadata", {}) if isinstance(c.get("metadata"), dict) else {},
        ) for c in chunks],
        total=len(chunks),
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
    return FileResponse(fp, media_type=media_type, filename=doc.get("filename", fp.name), content_disposition_type="inline")


@router.post("/{doc_id}/retry", response_model=DocumentUploadResponse)
async def retry_document(
    doc_id: str,
    background_tasks: BackgroundTasks,
    skip_evidence: bool = Form(False),
):
    doc = doc_store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found")
    if doc["status"] not in ("failed", "completed"):
        raise HTTPException(400, f"Document {doc_id} status '{doc['status']}' cannot be retried")

    file_path = doc.get("file_path", "")
    folder = doc.get("folder", "/")
    if not file_path or not Path(file_path).exists():
        raise HTTPException(400, f"Original file for {doc_id} no longer exists")

    doc_store.update_document(doc_id, status="pending", error=None)
    background_tasks.add_task(_process_document, doc_id, file_path, folder, skip_evidence)

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


def _process_document(doc_id: str, file_path: str, folder: str, skip_evidence: bool = False):
    _process_document_evidence(doc_id, file_path, folder, skip_evidence)


def _process_document_evidence(doc_id: str, file_path: str, folder: str, skip_evidence: bool = False):
    import time
    import hashlib
    start = time.time()

    skip_evidence = skip_evidence or settings.ingest_skip_evidence

    try:
        doc_store.update_document(doc_id, processing_stage="解析文档")
        from src.document_parser import parse_document
        result = parse_document(file_path, doc_id)
        markdown = result.get("markdown", "")

        doc_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()[:32]
        doc_version = doc_store.get_document(doc_id).get("doc_version", 1)
        doc_store.update_document(doc_id, doc_hash=doc_hash)

        doc_store.update_document(doc_id, processing_stage="切分文本块")
        from src.chunker.hierarchical_chunker import HierarchicalChunker
        from src.chunker.table_chunker import TableChunker
        from src.document_parser.table_parser import TableParser

        h_chunker = HierarchicalChunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
        chunks = h_chunker.chunk(doc_id, markdown)

        tables = TableParser.extract_tables_from_markdown(markdown)
        table_chunks = TableChunker().chunk_tables(doc_id, tables)
        chunks.extend(table_chunks)

        chunks = [c for c in chunks if c["text"].strip()]

        from src.storage.text_cleaner import clean_chunks
        clean_chunks(chunks)

        for chunk in chunks:
            chunk["folder"] = folder

        doc_store.update_document(doc_id, processing_stage="Chunk去重与引用管理")
        from src.knowledge_graph.chunk_manager import (
            compute_chunk_hash, update_document_refs, build_sync_tasks,
            process_chunk_ref_zero_to_one, process_chunk_ref_one_to_zero,
        )
        from src.retrieval.vector_retriever import MilvusVectorRetriever

        vr = MilvusVectorRetriever()
        force_reembed = not vr.doc_has_vectors(doc_id)

        if not force_reembed:
            vr.delete_by_doc(doc_id)
            force_reembed = True

        chunk_hashes = []
        new_chunk_texts = []
        all_affected_keys: dict[str, set[str]] = {}

        for i, chunk in enumerate(chunks):
            ch = compute_chunk_hash(chunk["text"])
            chunk_hashes.append(ch)
            chunk["chunk_hash"] = ch
            chunk["chunk_id"] = f"{doc_id}_{i:04d}_{ch[:8]}"

            existing = doc_store.get_chunk_content(ch)
            if not existing:
                doc_store.create_chunk_content(ch, chunk["text"], milvus_id="")
                new_chunk_texts.append(chunk)
            elif not existing.get("milvus_id") or force_reembed:
                new_chunk_texts.append(chunk)

        ref_result = update_document_refs(doc_id, doc_version, [
            {"text": c["text"], "chunk_index": i} for i, c in enumerate(chunks)
        ])

        for ch in ref_result["restored_hashes"]:
            affected = process_chunk_ref_zero_to_one(ch)
            merge_affected_keys(all_affected_keys, affected)

        for ch in ref_result["zero_ref_hashes"]:
            affected = process_chunk_ref_one_to_zero(ch)
            merge_affected_keys(all_affected_keys, affected)

        doc_store.update_document(doc_id, processing_stage="向量嵌入")
        from src.embeddings.bge_m3 import BGEM3Embedding

        if new_chunk_texts:
            embedding = BGEM3Embedding()
            texts = [c["text"] for c in new_chunk_texts]
            embeddings = embedding.encode_dense_all(texts, batch_size=settings.bge_m3_batch_size, concurrency=8)

            doc_store.update_document(doc_id, processing_stage="写入向量库")
            vector_retriever = MilvusVectorRetriever()
            vector_retriever.ensure_collection()
            vector_retriever.insert(new_chunk_texts, embeddings)

            conn = doc_store._get_conn()
            for nc in new_chunk_texts:
                conn.execute(
                    "UPDATE chunk_content SET milvus_id = ? WHERE chunk_hash = ?",
                    (nc.get("chunk_id", ""), nc["chunk_hash"]),
                )
            conn.commit()
            conn.close()

        doc_store.update_document(doc_id, processing_stage="构建BM25索引")
        from src.retrieval.bm25_retriever import BM25Retriever
        bm25 = BM25Retriever()
        bm25.load()
        bm25.remove_by_doc_id(doc_id)
        if new_chunk_texts:
            bm25.merge_chunks(new_chunk_texts)
            bm25.save()

        if not skip_evidence:
            doc_store.update_document(doc_id, processing_stage="Evidence抽取")
            from src.knowledge_graph.entity_extractor import EntityExtractor
            from src.knowledge_graph.evidence_writer import write_evidence

            extractor = EntityExtractor()

            total_evidence = len(chunks)

            for i, chunk in enumerate(chunks):
                ch = chunk["chunk_hash"]
                doc_store.update_document(doc_id, processing_stage=f"Evidence抽取 {i + 1}/{total_evidence}")

                try:
                    evidence_items = extractor.extract_evidence(chunk["text"], chunk_hash=ch)
                    if evidence_items:
                        result = write_evidence(ch, evidence_items)
                        merge_affected_keys(all_affected_keys, result["affected_keys"])
                except Exception as chunk_err:
                    import traceback as _tb
                    tb_str = _tb.format_exc()
                    chunk_text_preview = chunk["text"][:500]
                    raise RuntimeError(
                        f"Evidence extraction failed for chunk_hash={ch[:16]}...: {chunk_err}\n"
                        f"Chunk text preview: {chunk_text_preview}\n"
                        f"Full traceback:\n{tb_str}"
                    ) from chunk_err

            doc_store.update_document(doc_id, processing_stage="同步知识图谱")
            if all_affected_keys:
                tasks = build_sync_tasks(all_affected_keys, doc_id=doc_id, doc_version=doc_version)
                doc_store.create_sync_tasks_batch(tasks)

                from src.knowledge_graph.graph_sync_worker import process_pending_tasks
                for _ in range(20):
                    r = process_pending_tasks()
                    if r["success"] + r["failed"] == 0:
                        break

        else:
            logger = __import__("logging").getLogger(__name__)
            logger.info(f"Skip evidence: skipping evidence extraction + KG sync for {doc_id}")

        doc_store.update_document(doc_id, processing_stage="自动标签")
        from src.storage.auto_tagger import generate_tags
        tags = generate_tags(markdown)
        if tags:
            doc_store.update_document(doc_id, tags=tags)

        elapsed = (time.time() - start) * 1000
        doc_store.update_document(doc_id, status="completed", processing_stage="完成",
                                  chunk_count=len(chunks), processing_time_ms=elapsed,
                                  doc_version=doc_version + 1)

    except Exception as e:
        import traceback as _tb
        elapsed = (time.time() - start) * 1000
        full_error = f"{e}\n\nFull traceback:\n{_tb.format_exc()}"
        doc_store.update_document(doc_id, status="failed", processing_time_ms=elapsed, error=full_error[:2000])


def merge_affected_keys(target: dict[str, set[str]], source: list[dict] | dict[str, set[str]]):
    if isinstance(source, dict):
        for t, keys in source.items():
            if t not in target:
                target[t] = set()
            target[t].update(keys)
    else:
        for item in source:
            t = item["affected_type"]
            k = item["affected_key"]
            if t not in target:
                target[t] = set()
            target[t].add(k)


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

    # Clean up Milvus, BM25 for deleted docs
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

    return {"deleted": True, "folder": path, "doc_count": count, "cleaned_vectors": True}


@router.put("/folders/move")
async def move_folder_endpoint(req: FolderMoveRequest):
    count = doc_store.move_folder(req.src, req.dst)
    return {"moved": True, "src": req.src, "dst": req.dst, "doc_count": count}
