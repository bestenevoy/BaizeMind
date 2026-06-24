from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-v4-flash"
    deepseek_reasoner_model: str = "deepseek-v4-pro"

    # BGE-M3 Embedding
    bge_m3_use_local: bool = False
    bge_m3_model_path: str = "BAAI/bge-m3"
    bge_m3_device: str = "cuda:0"
    bge_m3_batch_size: int = 32
    bge_m3_max_length: int = 8192

    # SiliconFlow Embedding API
    siliconflow_api_key: str = ""
    siliconflow_embedding_url: str = "https://api.siliconflow.cn/v1/embeddings"
    siliconflow_embedding_model: str = "BAAI/bge-m3"
    siliconflow_rerank_url: str = "https://api.siliconflow.cn/v1/rerank"
    siliconflow_rerank_model: str = "BAAI/bge-reranker-v2-m3"

    # Milvus
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    milvus_collection: str = "agentic_rag"

    # LightRAG — Entity & Relation vector indexes
    lightrag_entity_collection: str = "lightrag_entities"
    lightrag_relation_collection: str = "lightrag_relations"
    lightrag_entity_top_k: int = 10
    lightrag_relation_top_k: int = 10
    lightrag_graph_hops: int = 2
    lightrag_retrieval_mode: str = "hybrid"  # "local" | "global" | "hybrid"

    # Neo4j
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # PaddleOCR-VL
    paddleocr_vl_model_dir: str = "./PaddleOCR-VL-1.5/PaddlePaddle/PaddleOCR-VL-1.5"
    layout_detection_model_dir: str = "./PP-DocLayoutV3/PaddlePaddle/PP-DocLayoutV3"
    cuda_visible_devices: str = "0"

    # Knowledge Graph
    graph_sync_max_retries: int = 3
    graph_sync_batch_size: int = 50
    chunk_gc_ttl_days: int = 30  # days before inactive chunks are physically deleted

    # Microsoft GraphRAG
    graphrag_root_dir: str = "./data/graphrag"
    graphrag_community_level: int = 2

    # MinerU
    mineru_model_source: str = "modelscope"
    mineru_output_dir: str = "./data/processed"

    # Chunking
    chunk_size: int = 512
    chunk_overlap: int = 64

    # Retrieval
    hybrid_top_k: int = 20
    hybrid_dense_weight: float = 0.6
    hybrid_sparse_weight: float = 0.3
    hybrid_bm25_weight: float = 0.4
    hybrid_rrf_k: int = 60
    retrieval_similarity_threshold: float = 0.6
    dense_vector_threshold: float = 0.6
    reranker_score_threshold: float = 0.3
    reranker_method: str = "embedding"  # "embedding" | "llm" | "hybrid"

    # Graph relation type filtering: high-relevance types for multi-hop/entity enrichment
    # Only paths involving these relation types are forwarded to the LLM entity filter
    graph_relation_whitelist: list[str] = [
        "ACQUIRED", "RELATED_TO_TECH", "USED_IN", "AFFECTS",
        "PART_OF", "DEPENDS_ON", "DEVELOPS", "PROVIDES_TECHNOLOGY_FOR",
        "COMPETES_WITH", "INTEGRATED_INTO", "POWERS", "SUPPORTS",
    ]
    # Low-relevance types (skipped unless no whitelist matches exist):
    # LOCATED_IN, FOUNDED_BY, CEO, HEADQUARTERED_IN, WORKS_FOR, MENTIONS, RELATES_TO

    # Agent
    agent_max_iterations: int = 5
    agent_temperature: float = 0.1

    # Ingest control
    ingest_skip_evidence: bool = False  # Skip evidence extraction + KG sync for fast chunk/index testing

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    server_workers: int = 4

    # Paths
    project_root: Path = Path(__file__).parent.parent
    data_dir: Path = project_root / "data"
    raw_dir: Path = data_dir / "raw"
    processed_dir: Path = data_dir / "processed"
    evaluation_dir: Path = data_dir / "evaluation"
    log_dir: Path = data_dir / "logs"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
