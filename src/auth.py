"""用户系统：角色、会话、密码哈希、FastAPI 依赖。

角色：
- ``admin``  管理员：全部权限
- ``user``   普通用户：可上传（受每日配额限制）、查询、检索测试
- ``guest``  访客：只能查询与检索测试，不能上传/修改/删除；聊天输入长度受限

未登录用户视为 ``guest``，仅可访问对外展示接口。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.settings import settings

# ── 角色常量 ──
ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_GUEST = "guest"

# 角色权限等级（数值越大权限越高）
_ROLE_LEVEL = {ROLE_GUEST: 0, ROLE_USER: 1, ROLE_ADMIN: 2}

DB_PATH = settings.data_dir / "users.db"

_bearer_scheme = HTTPBearer(auto_error=False)


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            username TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE TABLE IF NOT EXISTS upload_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            filename TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_upload_log_user_date ON upload_log(user_id, created_at);
    """)
    conn.close()
    _ensure_default_admin()


# ── 密码哈希 ──

def _hash_password(password: str, salt: str) -> str:
    """PBKDF2-HMAC-SHA256, 200k iterations."""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000
    ).hex()


def _make_password_hash(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    return _hash_password(password, salt), salt


def _verify_password(password: str, salt: str, expected_hash: str) -> bool:
    actual = _hash_password(password, salt)
    return hmac.compare_digest(actual, expected_hash)


# ── 用户/会话 CRUD ──

@dataclass
class User:
    user_id: str
    username: str
    role: str
    active: bool


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        user_id=row["user_id"],
        username=row["username"],
        role=row["role"],
        active=bool(row["active"]),
    )


def _ensure_default_admin() -> None:
    """首次启动时自动创建默认管理员账号。"""
    if not settings.auth_admin_username:
        return
    conn = _get_conn()
    row = conn.execute(
        "SELECT user_id FROM users WHERE username = ?", (settings.auth_admin_username,)
    ).fetchone()
    if row is None:
        now = datetime.now().isoformat()
        pw_hash, salt = _make_password_hash(settings.auth_admin_password)
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, password_salt, role, active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (secrets.token_hex(8), settings.auth_admin_username, pw_hash, salt, ROLE_ADMIN, now, now),
        )
        conn.commit()
    conn.close()


def get_user_by_username(username: str) -> Optional[User]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return _row_to_user(row) if row else None


def get_user(user_id: str) -> Optional[User]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return _row_to_user(row) if row else None


def list_users() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT user_id, username, role, active, created_at, updated_at FROM users ORDER BY role DESC, username"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_user(username: str, password: str, role: str = ROLE_USER) -> Optional[User]:
    if role not in (ROLE_ADMIN, ROLE_USER):
        role = ROLE_USER
    if get_user_by_username(username):
        return None
    now = datetime.now().isoformat()
    pw_hash, salt = _make_password_hash(password)
    user_id = secrets.token_hex(8)
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, password_salt, role, active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (user_id, username, pw_hash, salt, role, now, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return None
    conn.close()
    return get_user(user_id)


def update_user_password(user_id: str, new_password: str) -> bool:
    pw_hash, salt = _make_password_hash(new_password)
    now = datetime.now().isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE users SET password_hash = ?, password_salt = ?, updated_at = ? WHERE user_id = ?",
        (pw_hash, salt, now, user_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def update_user_role(user_id: str, role: str) -> bool:
    if role not in (ROLE_ADMIN, ROLE_USER, ROLE_GUEST):
        return False
    now = datetime.now().isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE users SET role = ?, updated_at = ? WHERE user_id = ?",
        (role, now, user_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def delete_user(user_id: str) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── 会话管理 ──

def create_session(user: User) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires_at = now + timedelta(hours=settings.auth_session_expire_hours)
    conn = _get_conn()
    conn.execute(
        "INSERT INTO sessions (token, user_id, role, username, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (token, user.user_id, user.role, user.username, expires_at.isoformat(), now.isoformat()),
    )
    conn.commit()
    conn.close()
    return token


def revoke_session(token: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def revoke_all_user_sessions(user_id: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_session(token: str) -> Optional[User]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT s.user_id, s.role, s.username, s.expires_at, u.active "
        "FROM sessions s JOIN users u ON u.user_id = s.user_id WHERE s.token = ?",
        (token,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    if not row["active"]:
        return None
    try:
        expires_at = datetime.fromisoformat(row["expires_at"])
    except Exception:
        return None
    if expires_at < datetime.now():
        revoke_session(token)
        return None
    return User(user_id=row["user_id"], username=row["username"], role=row["role"], active=True)


def authenticate(username: str, password: str) -> Optional[User]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? AND active = 1", (username,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    if not _verify_password(password, row["password_salt"], row["password_hash"]):
        return None
    return _row_to_user(row)


# ── 上传配额 ──

def get_upload_count_today(user_id: str) -> int:
    """返回该用户今日（自然日，本地时区）已上传文档数。"""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM upload_log WHERE user_id = ? AND substr(created_at, 1, 10) = ?",
        (user_id, today),
    ).fetchone()
    conn.close()
    return int(row["cnt"]) if row else 0


def record_upload(user_id: str, doc_id: str, filename: str = "") -> None:
    now = datetime.now().isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO upload_log (user_id, doc_id, filename, created_at) VALUES (?, ?, ?, ?)",
        (user_id, doc_id, filename, now),
    )
    conn.commit()
    conn.close()


# ── FastAPI 依赖 ──

def _extract_token(request: Request, credentials: Optional[HTTPAuthorizationCredentials]) -> Optional[str]:
    if credentials and credentials.credentials:
        return credentials.credentials
    # 兼容 cookie
    return request.cookies.get("auth_token")


def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> User:
    """获取当前用户。未登录返回 guest。

    注意：当 ``settings.auth_enabled`` 为 False 时，直接返回 admin。
    """
    if not settings.auth_enabled:
        return User(user_id="__system__", username="system", role=ROLE_ADMIN, active=True)

    token = _extract_token(request, credentials)
    if not token:
        return _guest_user()
    user = get_session(token)
    return user if user else _guest_user()


def _guest_user() -> User:
    return User(user_id="", username="guest", role=ROLE_GUEST, active=True)


def require_login(
    current: User = Depends(get_current_user_optional),
) -> User:
    """要求至少为已登录用户（admin/user），拒绝访客。"""
    if current.role == ROLE_GUEST:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要登录后才能访问",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current


def require_user(
    current: User = Depends(get_current_user_optional),
) -> User:
    """要求至少为普通用户（admin/user）。等价于 require_login。"""
    if _ROLE_LEVEL.get(current.role, 0) < _ROLE_LEVEL[ROLE_USER]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="权限不足，请使用普通用户或管理员账号登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current


def require_admin(
    current: User = Depends(get_current_user_optional),
) -> User:
    """要求管理员。"""
    if current.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current


def require_role(min_role: str):
    """返回一个依赖，要求至少为指定角色。"""
    min_level = _ROLE_LEVEL.get(min_role, 0)

    def _dep(current: User = Depends(get_current_user_optional)) -> User:
        if _ROLE_LEVEL.get(current.role, 0) < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要至少 {min_role} 权限",
            )
        return current

    return _dep


def enforce_guest_query_limit(query: str, user: "User") -> None:
    """访客查询长度限制（聊天 / 检索测试通用）。

    当 ``auth_guest_chat_max_length > 0`` 且用户为访客时，校验 query 长度。
    超限抛出 400，提示用户登录后继续使用。
    """
    if (
        user.role == ROLE_GUEST
        and settings.auth_enabled
        and settings.auth_guest_chat_max_length > 0
        and len(query) > settings.auth_guest_chat_max_length
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"访客模式下单次查询不能超过 {settings.auth_guest_chat_max_length} 字符，"
                f"当前 {len(query)} 字符。请登录后继续使用。"
            ),
        )


# 启动时初始化
init_db()
