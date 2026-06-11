import os
import subprocess
from pathlib import Path
from typing import Optional

from config.settings import settings


class GraphRAGIndexer:
    def __init__(self, root_dir: Optional[str] = None):
        self.root_dir = Path(root_dir or settings.graphrag_root_dir)
        self.input_dir = self.root_dir / "input"
        self.output_dir = self.root_dir / "output"

    def init(self):
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.input_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["GRAPHRAG_API_KEY"] = settings.deepseek_api_key

        result = subprocess.run(
            ["graphrag", "init", "--root", str(self.root_dir)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"GraphRAG init failed:\n{result.stderr}")

        self._write_settings()

    def _write_settings(self):
        import yaml

        config = {
            "models": {
                "default_chat_model": {
                    "type": "chat",
                    "api_key": settings.deepseek_api_key,
                    "api_base": settings.deepseek_base_url,
                    "model": settings.deepseek_chat_model,
                    "max_retries": 5,
                },
                "default_embedding_model": {
                    "type": "embedding",
                    "api_key": settings.siliconflow_api_key,
                    "api_base": settings.siliconflow_embedding_url.rsplit("/", 1)[0],
                    "model": settings.siliconflow_embedding_model,
                    "max_retries": 5,
                },
            },
            "chunks": {
                "size": settings.chunk_size,
                "overlap": settings.chunk_overlap,
            },
            "input": {
                "type": "file_or_folder",
                "file_type": "text",
                "base_dir": str(self.input_dir),
            },
            "storage": {
                "type": "file",
                "base_dir": str(self.output_dir),
            },
            "community_reports": {
                "max_length": 2000,
                "max_input_length": 8000,
            },
            "cluster_graph": {
                "max_cluster_size": 10,
            },
            "embed_graph": {
                "enabled": True,
            },
            "umap": {
                "enabled": False,
            },
        }

        settings_path = self.root_dir / "settings.yaml"
        with open(settings_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    def add_document(self, text: str, filename: str):
        self.input_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.input_dir / filename
        file_path.write_text(text, encoding="utf-8")

    def index(self) -> dict:
        env = os.environ.copy()
        env["GRAPHRAG_API_KEY"] = settings.deepseek_api_key

        result = subprocess.run(
            ["graphrag", "index", "--root", str(self.root_dir)],
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,
        )

        if result.returncode != 0:
            return {"success": False, "error": result.stderr}

        return {
            "success": True,
            "output_dir": str(self.output_dir),
            "stdout": result.stdout[-2000:],
        }

    def get_parquet_files(self) -> list[str]:
        if not self.output_dir.exists():
            return []
        return [str(f) for f in self.output_dir.rglob("*.parquet")]

    def is_indexed(self) -> bool:
        return len(self.get_parquet_files()) > 0
