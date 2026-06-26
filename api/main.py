import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from api.routes import admin, auth, documents, evaluation, excel, qa
from config.settings import settings
from src.logging_config import reset_request_id, set_request_id, setup_logging
from src.retrieval.bm25_retriever import BM25Retriever

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        bm25 = BM25Retriever()
        bm25.load()
        if bm25._model is None:
            bm25.rebuild_from_milvus()
    except Exception:
        pass
    yield


app = FastAPI(
    title="Agentic-GraphRAG",
    description="多模态文档解析 + 知识图谱 + Hybrid RAG + Agent 推理的企业知识问答系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """给每个 HTTP 请求注入 request_id（8 位短 uuid）用于日志链路追踪。

    优先使用前端透传的 X-Request-ID header；否则生成新的。
    设置后所有同上下文的日志都会带 [req_id=xxx] 前缀，方便 grep 一条请求的全部日志。
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8]
        token = set_request_id(request_id)
        try:
            response = await call_next(request)
            # 把 request_id 回写到响应头，前端/客户端可记录用于排查
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            reset_request_id(token)


app.add_middleware(RequestIdMiddleware)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(qa.router)
app.include_router(excel.router)
app.include_router(admin.router)
app.include_router(evaluation.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "Agentic-GraphRAG"}
