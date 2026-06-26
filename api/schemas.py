from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, computed_field


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

    @computed_field  # type: ignore[misc]
    @property
    def file_type(self) -> str:
        """从 filename 推导文件类型（扩展名小写，无点）。如 xlsx/pdf/docx/md。"""
        fn = self.filename or ""
        if "." not in fn:
            return ""
        return fn.rsplit(".", 1)[-1].lower()


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


class ChunkInfo(BaseModel):
    chunk_id: str
    text: str
    heading: str = ""
    metadata: dict[str, Any] = {}


class DocumentChunksResponse(BaseModel):
    doc_id: str
    chunks: list[ChunkInfo]
    total: int


class GraphNode(BaseModel):
    id: str
    label: str
    type: str = ""
    doc_id: str = ""
    description: str = ""


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str


class GraphOverviewResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_nodes: int
    total_edges: int


class EntityDetailResponse(BaseModel):
    name: str
    type: str = ""
    description: str = ""
    doc_id: str = ""
    documents: list[dict[str, Any]] = []
    related_chunks: list[ChunkInfo] = []


class ConnectivityResult(BaseModel):
    service: str
    status: str  # ok / warning / error
    detail: str = ""
    latency_ms: float = 0.0


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ── Evaluation ──

class EvalSampleCreate(BaseModel):
    id: str
    query: str
    query_type: str = "simple_fact"
    ground_truth_answer: str = ""
    ground_truth_sources: list[str] = []
    ground_truth_ids: list[str] = []


class EvalSampleUpdate(BaseModel):
    query: Optional[str] = None
    query_type: Optional[str] = None
    ground_truth_answer: Optional[str] = None
    ground_truth_sources: Optional[list[str]] = None
    ground_truth_ids: Optional[list[str]] = None


class EvalSampleResponse(BaseModel):
    id: str
    query: str
    query_type: str = "simple_fact"
    ground_truth_answer: str = ""
    ground_truth_sources: list[str] = []
    ground_truth_ids: list[str] = []


class EvalDatasetImport(BaseModel):
    samples: list[dict[str, Any]]
    mode: str = "replace"  # "replace" | "merge"


class EvalRunRequest(BaseModel):
    max_samples: Optional[int] = Field(None, ge=1, description="Limit number of samples to evaluate")
    folder: Optional[str] = Field(None, description="Limit retrieval scope to this folder")


class EvalDatasetGenerate(BaseModel):
    folder: Optional[str] = Field(None, description="Knowledge base folder to generate dataset from, e.g. /eval")
    max_docs: Optional[int] = Field(10, ge=1, le=50, description="Max number of docs to generate from")
    samples_per_doc: Optional[int] = Field(3, ge=1, le=10, description="Samples per document")
    mode: str = Field("replace", description="replace | merge")


class EvalResultSummary(BaseModel):
    filename: str
    timestamp: float = 0
    num_samples: int = 0
    # P1: Core
    context_relevancy: float = 0
    context_recall: float = 0
    answer_relevancy: float = 0
    faithfulness: float = 0
    # P1: Precision & NDCG
    precision_at_5: Optional[float] = None
    precision_at_10: Optional[float] = None
    ndcg_at_5: Optional[float] = None
    # P1: Hallucination
    intrinsic_hallucination_rate: float = 0
    extrinsic_hallucination_rate: float = 0
    # P1: Completeness
    answer_completeness: float = 0
    # P2
    mrr: Optional[float] = None
    context_redundancy: float = 0
    delta_ndcg: Optional[float] = None
    filter_drop_rate: float = 0
    # P3
    timing_mean_ms: float = 0
    timing_p95_ms: float = 0
    # legacy
    recall_at_5: float = 0
    recall_at_10: float = 0
    semantic_similarity: float = 0
    judge_accuracy: float = 0
    citation_accuracy: float = 0


class EvalSampleResult(BaseModel):
    sample_id: str
    query: str
    query_type: str = ""
    predicted_answer: str = ""
    cited_sources: list[str] = []
    retrieved_ids: list[str] = []
    retrieved_texts: list[str] = []
    error: Optional[str] = None
    processing_time_ms: float = 0


class EvalResultDetail(BaseModel):
    summary: dict[str, Any] = {}
    total_time_seconds: float = 0
    avg_time_per_sample: float = 0
    results: list[dict[str, Any]] = []
