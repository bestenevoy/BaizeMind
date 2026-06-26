"""认证与用户管理路由。

接口概览：
- ``POST /api/v1/auth/login``   登录（admin / user），返回 token
- ``POST /api/v1/auth/logout``  注销当前会话
- ``GET  /api/v1/auth/me``      获取当前用户信息（未登录返回 guest）
- ``POST /api/v1/auth/register`` 自助注册（受 ``auth_allow_register`` 开关控制）
- ``GET  /api/v1/auth/users``   列出全部用户（仅 admin）
- ``POST /api/v1/auth/users``   创建用户（仅 admin）
- ``PUT  /api/v1/auth/users/{id}/role``   修改用户角色（仅 admin）
- ``PUT  /api/v1/auth/users/{id}/password`` 重置用户密码（仅 admin）
- ``DELETE /api/v1/auth/users/{id}``       删除用户（仅 admin）
- ``PUT  /api/v1/auth/password`` 修改自己的密码（登录用户）
- ``GET  /api/v1/auth/upload-quota`` 查询当前用户今日上传配额（user / admin）
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from config.settings import settings
from src.auth import (
    ROLE_ADMIN,
    ROLE_GUEST,
    ROLE_USER,
    User,
    authenticate,
    create_session,
    create_user,
    delete_user,
    get_upload_count_today,
    get_user,
    get_user_by_username,
    list_users,
    revoke_session,
    revoke_all_user_sessions,
    update_user_password,
    update_user_role,
    require_admin,
    require_login,
    get_current_user_optional,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class LoginResponse(BaseModel):
    token: str
    username: str
    role: str
    expires_at: str


class UserInfoResponse(BaseModel):
    user_id: str = ""
    username: str
    role: str
    is_guest: bool
    # 普通用户配额信息
    upload_used_today: int = 0
    upload_limit: int = 0
    # 访客聊天输入长度上限
    guest_chat_max_length: int = 0


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=256)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=256)


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=256)
    role: str = Field(ROLE_USER, description="admin | user")


class UpdateRoleRequest(BaseModel):
    role: str = Field(..., description="admin | user | guest")


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=256)


class UploadQuotaResponse(BaseModel):
    used: int
    limit: int
    remaining: int


def _build_user_info(user: User) -> UserInfoResponse:
    is_guest = user.role == ROLE_GUEST
    upload_used = 0
    upload_limit = 0
    guest_chat_max = 0
    if is_guest:
        guest_chat_max = settings.auth_guest_chat_max_length
    elif user.role == ROLE_USER:
        upload_used = get_upload_count_today(user.user_id)
        upload_limit = settings.auth_user_upload_daily_limit
    elif user.role == ROLE_ADMIN:
        upload_limit = -1  # 无限制
    return UserInfoResponse(
        user_id=user.user_id,
        username=user.username,
        role=user.role,
        is_guest=is_guest,
        upload_used_today=upload_used,
        upload_limit=upload_limit,
        guest_chat_max_length=guest_chat_max,
    )


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, response: Response):
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    token = create_session(user)
    # 同时写入 cookie，方便 SSR / 静态页
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.auth_session_expire_hours * 3600,
        path="/",
    )
    expires_at = (datetime.now() + timedelta(hours=settings.auth_session_expire_hours)).isoformat()
    return LoginResponse(token=token, username=user.username, role=user.role, expires_at=expires_at)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
):
    """注销当前会话：从 Authorization header 或 cookie 提取 token 并销毁。"""
    auth = request.headers.get("authorization", "") or request.headers.get("Authorization", "")
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = request.cookies.get("auth_token", "")
    if token:
        revoke_session(token)
    response.delete_cookie("auth_token", path="/")
    return {"success": True}


@router.get("/me", response_model=UserInfoResponse)
async def me(current: User = Depends(get_current_user_optional)):
    return _build_user_info(current)


@router.post("/register", response_model=UserInfoResponse)
async def register(req: RegisterRequest):
    if not settings.auth_allow_register:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理员未开放自助注册，请联系管理员创建账号",
        )
    user = create_user(req.username, req.password, ROLE_USER)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )
    return _build_user_info(user)


@router.put("/password")
async def change_my_password(
    req: ChangePasswordRequest,
    current: User = Depends(require_login),
):
    if current.role == ROLE_GUEST:
        raise HTTPException(403, "访客无法修改密码")
    # 重新校验旧密码
    real = authenticate(current.username, req.old_password)
    if not real or real.user_id != current.user_id:
        raise HTTPException(400, "原密码错误")
    update_user_password(current.user_id, req.new_password)
    revoke_all_user_sessions(current.user_id)
    return {"success": True}


@router.get("/upload-quota", response_model=UploadQuotaResponse)
async def my_upload_quota(current: User = Depends(require_login)):
    if current.role == ROLE_ADMIN:
        return UploadQuotaResponse(used=0, limit=-1, remaining=-1)
    used = get_upload_count_today(current.user_id)
    limit = settings.auth_user_upload_daily_limit
    return UploadQuotaResponse(used=used, limit=limit, remaining=max(0, limit - used))


# ── 管理员接口 ──

@router.get("/users", response_model=list[dict])
async def admin_list_users(_: User = Depends(require_admin)):
    return list_users()


@router.post("/users", response_model=UserInfoResponse)
async def admin_create_user(req: CreateUserRequest, _: User = Depends(require_admin)):
    role = req.role if req.role in (ROLE_ADMIN, ROLE_USER) else ROLE_USER
    user = create_user(req.username, req.password, role)
    if not user:
        raise HTTPException(409, "用户名已存在")
    return _build_user_info(user)


@router.put("/users/{user_id}/role")
async def admin_update_role(user_id: str, req: UpdateRoleRequest, _: User = Depends(require_admin)):
    if req.role not in (ROLE_ADMIN, ROLE_USER, ROLE_GUEST):
        raise HTTPException(400, "非法角色")
    target = get_user(user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    if target.username == settings.auth_admin_username and req.role != ROLE_ADMIN:
        raise HTTPException(400, "不能降低默认管理员角色")
    if not update_user_role(user_id, req.role):
        raise HTTPException(404, "用户不存在")
    revoke_all_user_sessions(user_id)
    return {"success": True}


@router.put("/users/{user_id}/password")
async def admin_reset_password(user_id: str, req: AdminResetPasswordRequest, _: User = Depends(require_admin)):
    target = get_user(user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    update_user_password(user_id, req.new_password)
    revoke_all_user_sessions(user_id)
    return {"success": True}


@router.delete("/users/{user_id}")
async def admin_delete_user(user_id: str, current: User = Depends(require_admin)):
    target = get_user(user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    if target.username == settings.auth_admin_username:
        raise HTTPException(400, "不能删除默认管理员账号")
    if target.user_id == current.user_id:
        raise HTTPException(400, "不能删除当前登录账号")
    delete_user(user_id)
    return {"success": True}
