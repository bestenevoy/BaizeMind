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

    # Milvus
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    milvus_collection: str = "agentic_rag"

    # Neo4j
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # PaddleOCR-VL
    paddleocr_vl_model_dir: str = "./PaddleOCR-VL-1.5/PaddlePaddle/PaddleOCR-VL-1.5"
    layout_detection_model_dir: str = "./PP-DocLayoutV3/PaddlePaddle/PP-DocLayoutV3"
    cuda_visible_devices: str = "0"

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
    hybrid_dense_weight: float = 0.5
    hybrid_sparse_weight: float = 0.3
    hybrid_bm25_weight: float = 0.2
    hybrid_rrf_k: int = 60

    # Agent
    agent_max_iterations: int = 5
    agent_temperature: float = 0.1

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
