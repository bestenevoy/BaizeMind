from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import auth, documents, evaluation, management, qa
from config.settings import settings
from src.logging_config import setup_logging
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

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(qa.router)
app.include_router(management.router)
app.include_router(evaluation.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "Agentic-GraphRAG"}
