from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    doc_id: str
    filename: str
    folder: str = "/"
    status: str
    message: str


class DocumentInfo(BaseModel):
    doc_id: str
    filename: str
    folder: str = "/"
    tags: list[str] = []
    status: str
    processing_stage: str = ""
    chunk_count: int = 0
    processing_time_ms: float = 0.0
    error: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


class DocumentStatusResponse(BaseModel):
    doc_id: str
    status: str
    processing_stage: str = ""
    chunk_count: int = 0
    processing_time_ms: float = 0.0
    error: Optional[str] = None


class FolderInfo(BaseModel):
    folder: str
    doc_count: int


class TagInfo(BaseModel):
    tag: str
    count: int


class MoveRequest(BaseModel):
    folder: str = Field(..., description="Target folder path")


class TagRequest(BaseModel):
    tag: str = Field(..., min_length=1, max_length=50)


class QARequest(BaseModel):
    query: str = Field(..., description="User's question", min_length=1, max_length=4096)
    stream: bool = Field(False, description="Whether to stream the response")
    top_k: int = Field(20, ge=1, le=100, description="Number of documents to retrieve")
    doc_filter: Optional[str] = Field(None, description="Optional document ID filter")
    folder: Optional[str] = Field(None, description="Filter by folder path")
    tags: Optional[list[str]] = Field(None, description="Filter by tags")


class QAResponse(BaseModel):
    query: str
    answer: str
    query_type: str
    confidence: float
    citations: list[str] = []
    graph_context: str = ""
    retrieved_docs: list[dict[str, Any]] = []
    validation: dict[str, Any] = {}
    processing_time_ms: float = 0.0


class SystemStatsResponse(BaseModel):
    document_count: int
    chunk_count: int
    milvus_vector_count: int
    neo4j_entity_count: int
    neo4j_relation_count: int


class DocumentContentResponse(BaseModel):
    doc_id: str
    filename: str
    original_content: str = ""
    parsed_markdown: str = ""
    raw_url: str = ""
    is_binary: bool = False
    file_ext: str = ""
    file_size_kb: float = 0.0
    status: str


class ConnectivityResult(BaseModel):
    service: str
    status: str  # ok / warning / error
    detail: str = ""
    latency_ms: float = 0.0


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
