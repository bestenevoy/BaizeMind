import json
import sqlite3
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
    """)
    try:
        conn.execute("ALTER TABLE documents ADD COLUMN processing_stage TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
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
        "SELECT doc_id, folder FROM documents WHERE folder = ? OR folder LIKE ?",
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
