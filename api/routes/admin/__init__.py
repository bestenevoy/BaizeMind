"""系统管理路由聚合子包。

按功能域拆分的 4 个管理类 router 模块：
- :mod:`api.routes.admin.system`        — 配置展示 / 连通性检测 / 统计 / 孤儿清理 / 运行时配置覆盖
- :mod:`api.routes.admin.graph_admin`   — 图谱查询 / 构建图谱 / 批量删除 / BM25 重建
- :mod:`api.routes.admin.search_debug`  — 检索调试 (/search)
- :mod:`api.routes.admin.cache_admin`   — 缓存管理 (list/clear/delete)

所有子 router 仍挂在 ``/api/v1/system`` 前缀下，前端 API 路径保持不变。
:mod:`api.main` 通过 ``app.include_router(admin.router)`` 一次性挂载全部子路由。
"""
from fastapi import APIRouter

from api.routes.admin import cache_admin, graph_admin, search_debug, system

router = APIRouter()
router.include_router(system.router)
router.include_router(graph_admin.router)
router.include_router(search_debug.router)
router.include_router(cache_admin.router)

__all__ = ["router"]
