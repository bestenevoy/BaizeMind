import json
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.settings import settings

DB_PATH = settings.data_dir / "documents.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            doc_id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            folder TEXT NOT NULL DEFAULT '/',
            tags TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending',
            processing_stage TEXT NOT NULL DEFAULT '',
            chunk_count INTEGER NOT NULL DEFAULT 0,
            processing_time_ms REAL NOT NULL DEFAULT 0,
            error TEXT,
            file_path TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_documents_folder ON documents(folder);
        CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
        CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at);
        CREATE TABLE IF NOT EXISTS folder_markers (
            path TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        );

        -- Evidence pipeline tables
        -- chunk_content: 每个文档独立持有 chunk，不再跨文档复用/dedup。
        -- doc_id 列用于按文档清理；ref_count/doc_chunk_ref 已废弃移除。
        -- 注意：CREATE TABLE IF NOT EXISTS 不会为已存在的表添加新列，
        -- 因此 doc_id 列通过下方的 ALTER TABLE 迁移补充，idx_cc_doc_id 也在迁移后创建。
        CREATE TABLE IF NOT EXISTS chunk_content (
            chunk_hash TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            doc_id TEXT NOT NULL DEFAULT '',
            milvus_id TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT PRIMARY KEY,
            chunk_hash TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            entity_key TEXT,
            entity_name TEXT,
            entity_type TEXT,
            subject_key TEXT,
            subject_name TEXT,
            subject_type TEXT,
            predicate TEXT,
            object_key TEXT,
            object_name TEXT,
            object_type TEXT,
            attr_owner_type TEXT,
            attr_key TEXT,
            attr_value TEXT,
            evidence_text TEXT DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0.5,
            extractor_version TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ev_chunk ON evidence(chunk_hash, active);
        CREATE INDEX IF NOT EXISTS idx_ev_type ON evidence(active, evidence_type);
        CREATE INDEX IF NOT EXISTS idx_ev_entity ON evidence(entity_key, active);
        CREATE INDEX IF NOT EXISTS idx_ev_fact ON evidence(subject_key, predicate, object_key, active);
        CREATE INDEX IF NOT EXISTS idx_ev_entity_attr ON evidence(entity_key, attr_key, attr_value, active);
        CREATE INDEX IF NOT EXISTS idx_ev_fact_attr ON evidence(subject_key, predicate, object_key, attr_key, attr_value, active);

        CREATE TABLE IF NOT EXISTS graph_sync_task (
            task_id TEXT PRIMARY KEY,
            doc_id TEXT,
            doc_version INTEGER,
            chunk_hash TEXT,
            affected_key TEXT NOT NULL,
            affected_type TEXT NOT NULL,
            operation TEXT NOT NULL DEFAULT 'UPSERT',
            status TEXT NOT NULL DEFAULT 'PENDING',
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_gst_status ON graph_sync_task(status);
    """)
    try:
        conn.execute("ALTER TABLE documents ADD COLUMN processing_stage TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE documents ADD COLUMN doc_version INTEGER NOT NULL DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE documents ADD COLUMN doc_hash TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    # Migration: add doc_id column to chunk_content (existing DBs only)
    try:
        conn.execute("ALTER TABLE chunk_content ADD COLUMN doc_id TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    # 创建 doc_id 索引（必须放在 ALTER 之后，确保列已存在）
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_doc_id ON chunk_content(doc_id)")
    # Normalize existing folders without leading slash
    conn.execute("UPDATE documents SET folder = '/' || folder WHERE folder != '/' AND folder NOT LIKE '/%'")
    conn.execute("UPDATE folder_markers SET path = '/' || path WHERE path != '/' AND path NOT LIKE '/%'")
    conn.close()


init_db()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d.get("tags", "[]"))
    return d


def create_document(doc_id: str, filename: str, folder: str = "/", file_path: str = "") -> dict:
    now = datetime.now().isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO documents (doc_id, filename, folder, tags, status, file_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (doc_id, filename, folder, "[]", "pending", file_path, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def update_document(doc_id: str, **kwargs) -> Optional[dict]:
    if not kwargs:
        return get_document(doc_id)
    if "tags" in kwargs and isinstance(kwargs["tags"], list):
        kwargs["tags"] = json.dumps(kwargs["tags"])
    kwargs["updated_at"] = datetime.now().isoformat()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [doc_id]
    conn = _get_conn()
    conn.execute(f"UPDATE documents SET {sets} WHERE doc_id = ?", vals)
    conn.commit()
    row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def get_document(doc_id: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def delete_document(doc_id: str) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def list_documents(
    folder: Optional[str] = None,
    tags: Optional[list[str]] = None,
    status: Optional[str] = None,
    file_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    conn = _get_conn()
    query = "SELECT * FROM documents WHERE 1=1"
    params: list = []

    if folder is not None:
        if folder == "/":
            query += " AND folder = ?"
            params.append("/")
        else:
            query += " AND (folder = ? OR folder LIKE ?)"
            params.extend([folder, f"{folder}/%"])

    if status:
        query += " AND status = ?"
        params.append(status)

    # 文件类型筛选：按扩展名匹配（file_type 形如 "xlsx"/"pdf"/"docx"）
    if file_type:
        ext = file_type.lstrip(".").lower()
        query += " AND LOWER(filename) LIKE ?"
        params.append(f"%.{ext}")

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()

    results = [_row_to_dict(r) for r in rows]

    if tags:
        tag_set = set(tags)
        results = [r for r in results if tag_set.intersection(set(r["tags"]))]

    return results


def list_folders() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT folder, COUNT(*) as doc_count FROM documents GROUP BY folder ORDER BY folder"
    ).fetchall()
    counts = {r["folder"]: r["doc_count"] for r in rows}

    # Add folder markers with 0 doc_count
    marker_rows = conn.execute(
        "SELECT path FROM folder_markers ORDER BY path"
    ).fetchall()
    conn.close()

    for r in marker_rows:
        p = r["path"]
        if p not in counts:
            counts[p] = 0

    return [{"folder": k, "doc_count": v} for k, v in sorted(counts.items())]


def list_all_tags() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT tags FROM documents").fetchall()
    conn.close()
    tag_counts: dict[str, int] = {}
    for row in rows:
        for tag in json.loads(row["tags"]):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(tag_counts.items(), key=lambda x: -x[1])]


def get_doc_ids_by_filter(
    folder: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> list[str]:
    docs = list_documents(folder=folder, tags=tags, limit=10000)
    return [d["doc_id"] for d in docs]


def move_document(doc_id: str, new_folder: str) -> Optional[dict]:
    new_folder = normalize_folder(new_folder)
    doc = get_document(doc_id)
    if not doc:
        return None
    # Move physical file
    old_path = doc.get("file_path", "")
    if old_path:
        old = Path(old_path)
        if old.exists():
            new_dir = Path(settings.raw_dir) / new_folder.lstrip("/")
            new_dir.mkdir(parents=True, exist_ok=True)
            new_path = new_dir / old.name
            shutil.move(str(old), str(new_path))
            return update_document(doc_id, folder=new_folder, file_path=str(new_path))
    return update_document(doc_id, folder=new_folder)


def add_tag(doc_id: str, tag: str) -> Optional[dict]:
    doc = get_document(doc_id)
    if not doc:
        return None
    tags = doc["tags"]
    if tag not in tags:
        tags.append(tag)
    return update_document(doc_id, tags=tags)


def remove_tag(doc_id: str, tag: str) -> Optional[dict]:
    doc = get_document(doc_id)
    if not doc:
        return None
    tags = [t for t in doc["tags"] if t != tag]
    return update_document(doc_id, tags=tags)


# ── Folder management ──

def normalize_folder(path: str) -> str:
    if not path or path == "/":
        return "/"
    return "/" + path.strip("/")


def create_folder(path: str) -> dict:
    path = normalize_folder(path)
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO folder_markers (path, created_at) VALUES (?, ?)",
        (path, now),
    )
    conn.commit()
    conn.close()
    return {"folder": path, "doc_count": 0}


def delete_folder(path: str) -> int:
    """Delete all documents in folder and subfolders. Returns count of deleted docs."""
    path = normalize_folder(path)
    conn = _get_conn()
    # Find all docs in this folder and subfolders
    rows = conn.execute(
        "SELECT doc_id FROM documents WHERE folder = ? OR folder LIKE ?",
        (path, f"{path}/%"),
    ).fetchall()
    doc_ids = [r["doc_id"] for r in rows]
    count = len(doc_ids)

    if count > 0:
        placeholders = ",".join("?" * len(doc_ids))
        conn.execute(f"DELETE FROM documents WHERE doc_id IN ({placeholders})", doc_ids)

    # Also delete any nested folder markers
    conn.execute(
        "DELETE FROM folder_markers WHERE path = ? OR path LIKE ?",
        (path, f"{path}/%"),
    )
    conn.commit()
    conn.close()
    return count


def move_folder(src: str, dst: str) -> int:
    """Move all documents from src folder (and subfolders) to dst folder. Returns count of moved docs."""
    src = normalize_folder(src)
    dst = normalize_folder(dst)

    conn = _get_conn()
    rows = conn.execute(
        "SELECT doc_id, folder, file_path FROM documents WHERE folder = ? OR folder LIKE ?",
        (src, f"{src}/%"),
    ).fetchall()

    count = 0
    for r in rows:
        old_folder = r["folder"]
        new_folder = dst + old_folder[len(src):] if old_folder.startswith(src) else dst
        conn.execute(
            "UPDATE documents SET folder = ?, updated_at = ? WHERE doc_id = ?",
            (new_folder, datetime.now().isoformat(), r["doc_id"]),
        )
        # Move physical file on disk
        old_path = r["file_path"]
        if old_path:
            old = Path(old_path)
            if old.exists():
                new_dir = Path(settings.raw_dir) / new_folder.lstrip("/")
                new_dir.mkdir(parents=True, exist_ok=True)
                new_path = new_dir / old.name
                shutil.move(str(old), str(new_path))
                conn.execute(
                    "UPDATE documents SET file_path = ? WHERE doc_id = ?",
                    (str(new_path), r["doc_id"]),
                )
        count += 1

    # Move folder markers
    mrows = conn.execute(
        "SELECT path FROM folder_markers WHERE path = ? OR path LIKE ?",
        (src, f"{src}/%"),
    ).fetchall()
    for mr in mrows:
        old_path = mr["path"]
        new_path = dst + old_path[len(src):] if old_path.startswith(src) else dst
        conn.execute(
            "UPDATE folder_markers SET path = ?, created_at = ? WHERE path = ?",
            (new_path, datetime.now().isoformat(), old_path),
        )

    conn.commit()
    conn.close()
    return count


def delete_folder_marker(path: str) -> bool:
    path = normalize_folder(path)
    conn = _get_conn()
    conn.execute("DELETE FROM folder_markers WHERE path = ?", (path,))
    conn.commit()
    conn.close()
    return True


def _folder_has_docs(path: str) -> bool:
    path = normalize_folder(path)
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM documents WHERE folder = ? OR folder LIKE ?",
        (path, f"{path}/%"),
    ).fetchone()
    conn.close()
    return row["cnt"] > 0 if row else False


# ═══════════════════════════════════════════════════════════════
# ChunkContent — per-document chunks (no dedup / ref_count)
# ═══════════════════════════════════════════════════════════════

def get_chunk_content(chunk_hash: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM chunk_content WHERE chunk_hash = ?", (chunk_hash,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_chunk_content(chunk_hash: str, text: str, doc_id: str = "", milvus_id: str = "") -> dict:
    """创建 ChunkContent（每次都写入，不再查重复用）。"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO chunk_content (chunk_hash, text, doc_id, milvus_id, active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
        (chunk_hash, text, doc_id, milvus_id, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM chunk_content WHERE chunk_hash = ?", (chunk_hash,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def get_chunk_hashes_by_doc(doc_id: str) -> list[str]:
    """返回某文档的所有 chunk_hash（用于删除/重索引）。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT chunk_hash FROM chunk_content WHERE doc_id = ?", (doc_id,)
    ).fetchall()
    conn.close()
    return [r["chunk_hash"] for r in rows]


def delete_chunk_content_by_doc(doc_id: str) -> int:
    """物理删除某文档的所有 ChunkContent 记录。返回删除条数。"""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM chunk_content WHERE doc_id = ?", (doc_id,))
    conn.commit()
    conn.close()
    return cur.rowcount


def update_chunk_milvus_id(chunk_hash: str, milvus_id: str):
    conn = _get_conn()
    conn.execute("UPDATE chunk_content SET milvus_id = ? WHERE chunk_hash = ?", (milvus_id, chunk_hash))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
# Evidence — Source of Truth
# ═══════════════════════════════════════════════════════════════

def insert_evidence_batch(items: list[dict]) -> int:
    """Insert evidence records. Each item is an evidence dict (from Evidence.to_dict())."""
    if not items:
        return 0
    conn = _get_conn()
    now = datetime.now().isoformat()
    for item in items:
        item.setdefault("evidence_text", "")
        item.setdefault("extractor_version", "")
        item.setdefault("confidence", 0.5)
        conn.execute(
            """INSERT OR REPLACE INTO evidence
               (evidence_id, chunk_hash, evidence_type, entity_key, entity_name, entity_type,
                subject_key, subject_name, subject_type, predicate, object_key, object_name, object_type,
                attr_owner_type, attr_key, attr_value,
                evidence_text, confidence, extractor_version, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                item["evidence_id"], item["chunk_hash"], item["evidence_type"],
                item.get("entity_key"), item.get("entity_name"), item.get("entity_type"),
                item.get("subject_key"), item.get("subject_name"), item.get("subject_type"),
                item.get("predicate"), item.get("object_key"), item.get("object_name"), item.get("object_type"),
                item.get("attr_owner_type"), item.get("attr_key"), item.get("attr_value"),
                item.get("evidence_text", ""), item.get("confidence", 0.5),
                item.get("extractor_version", ""), now, now,
            ),
        )
    conn.commit()
    conn.close()
    return len(items)


def deactivate_evidence_by_chunk(chunk_hash: str) -> list[dict]:
    """Deactivate all evidence for a chunk. Returns affected keys for Neo4j sync."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT evidence_type, entity_key, subject_key, predicate, object_key, attr_key, attr_value FROM evidence WHERE chunk_hash = ? AND active = 1",
        (chunk_hash,),
    ).fetchall()
    affected = []
    for r in rows:
        t = r["evidence_type"]
        if t == "ENTITY":
            affected.append({"affected_type": t, "affected_key": r["entity_key"]})
        elif t == "ENTITY_ATTRIBUTE":
            key = f"{r['entity_key']}|{r['attr_key']}|{r['attr_value']}"
            affected.append({"affected_type": t, "affected_key": key})
        elif t == "FACT":
            key = f"{r['subject_key']}|{r['predicate']}|{r['object_key']}"
            affected.append({"affected_type": t, "affected_key": key})
        elif t == "FACT_ATTRIBUTE":
            fact_key = f"{r['subject_key']}|{r['predicate']}|{r['object_key']}"
            key = f"{fact_key}|{r['attr_key']}|{r['attr_value']}"
            affected.append({"affected_type": t, "affected_key": key})
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE evidence SET active = 0, updated_at = ? WHERE chunk_hash = ? AND active = 1",
        (now, chunk_hash),
    )
    conn.commit()
    conn.close()
    return affected


def count_active_evidence(
    affected_type: str,
    entity_key: Optional[str] = None,
    subject_key: Optional[str] = None,
    predicate: Optional[str] = None,
    object_key: Optional[str] = None,
    attr_key: Optional[str] = None,
    attr_value: Optional[str] = None,
) -> int:
    """Recalculate support_count from active evidence."""
    conn = _get_conn()
    if affected_type == "ENTITY":
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM evidence WHERE active = 1 AND evidence_type = 'ENTITY' AND entity_key = ?",
            (entity_key,),
        ).fetchone()
    elif affected_type == "FACT":
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM evidence WHERE active = 1 AND evidence_type = 'FACT' AND subject_key = ? AND predicate = ? AND object_key = ?",
            (subject_key, predicate, object_key),
        ).fetchone()
    elif affected_type == "ENTITY_ATTRIBUTE":
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM evidence WHERE active = 1 AND evidence_type = 'ENTITY_ATTRIBUTE' AND entity_key = ? AND attr_key = ? AND attr_value = ?",
            (entity_key, attr_key, attr_value),
        ).fetchone()
    elif affected_type == "FACT_ATTRIBUTE":
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM evidence WHERE active = 1 AND evidence_type = 'FACT_ATTRIBUTE' AND subject_key = ? AND predicate = ? AND object_key = ? AND attr_key = ? AND attr_value = ?",
            (subject_key, predicate, object_key, attr_key, attr_value),
        ).fetchone()
    else:
        row = None
    conn.close()
    return row["cnt"] if row else 0


# ═══════════════════════════════════════════════════════════════
# GraphSyncTask — Neo4j eventual consistency queue
# ═══════════════════════════════════════════════════════════════

def create_sync_tasks_batch(tasks: list[dict]) -> int:
    """Batch insert sync tasks. Each task: {doc_id, doc_version, chunk_hash, affected_key, affected_type, operation}."""
    if not tasks:
        return 0
    conn = _get_conn()
    now = datetime.now().isoformat()
    for t in tasks:
        task_id = f"sync_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """INSERT OR REPLACE INTO graph_sync_task
               (task_id, doc_id, doc_version, chunk_hash, affected_key, affected_type, operation, status, retry_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?)""",
            (
                task_id, t.get("doc_id"), t.get("doc_version"), t.get("chunk_hash"),
                t["affected_key"], t["affected_type"], t.get("operation", "UPSERT"),
                now, now,
            ),
        )
    conn.commit()
    conn.close()
    return len(tasks)


def get_pending_sync_tasks(limit: int = 100) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM graph_sync_task WHERE status = 'PENDING' ORDER BY created_at LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_sync_task_status(task_id: str, status: str):
    conn = _get_conn()
    conn.execute(
        "UPDATE graph_sync_task SET status = ?, updated_at = ? WHERE task_id = ?",
        (status, datetime.now().isoformat(), task_id),
    )
    conn.commit()
    conn.close()


def mark_sync_task_retry(task_id: str):
    conn = _get_conn()
    conn.execute(
        "UPDATE graph_sync_task SET retry_count = retry_count + 1, status = 'PENDING', updated_at = ? WHERE task_id = ?",
        (datetime.now().isoformat(), task_id),
    )
    conn.commit()
    conn.close()


def cleanup_old_sync_tasks(days: int = 7):
    conn = _get_conn()
    conn.execute(
        "DELETE FROM graph_sync_task WHERE status = 'SUCCESS' AND updated_at < datetime('now', ?)",
        (f'-{days} days',),
    )
    conn.commit()
    conn.close()
