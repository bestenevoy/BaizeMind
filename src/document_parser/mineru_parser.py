import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional
from config.settings import settings


class MinerUParser:
    def __init__(self, model_source: str = "modelscope"):
        self.model_source = model_source
        self.output_base = Path(settings.mineru_output_dir)

    def _get_mineru_cmd(self) -> list[str]:
        venv_bin = Path(sys.executable).parent
        mineru_path = venv_bin / "mineru"
        if mineru_path.exists():
            return [str(mineru_path)]
        return [sys.executable, "-m", "mineru.cli.client"]

    def parse(self, file_path: str | Path, doc_id: Optional[str] = None) -> dict:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        doc_id = doc_id or file_path.stem
        output_dir = self.output_base / doc_id
        output_dir.mkdir(parents=True, exist_ok=True)

        if file_path.suffix.lower() in (".txt", ".md"):
            return self._parse_plaintext(file_path, output_dir, doc_id)

        env = os.environ.copy()
        env["MINERU_MODEL_SOURCE"] = self.model_source
        
        cmd = self._get_mineru_cmd() + ["-p", str(file_path.absolute()), "-o", str(output_dir.absolute())]

        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"MinerU parsing failed:\n{result.stderr}")

        return self._collect_output(output_dir, doc_id)

    def _parse_plaintext(self, file_path: Path, output_dir: Path, doc_id: str) -> dict:
        content = file_path.read_text(encoding="utf-8")
        md_path = output_dir / f"{doc_id}.md"
        md_path.write_text(content, encoding="utf-8")
        return {
            "doc_id": doc_id,
            "markdown": content,
            "content_list": [],
            "output_dir": str(output_dir),
        }

    def _collect_output(self, output_dir: Path, doc_id: str) -> dict:
        md_content = ""
        content_list = []

        for item in output_dir.rglob("*"):
            if item.suffix == ".md":
                md_content = item.read_text(encoding="utf-8")
            elif item.name == "content_list.json":
                content_list = json.loads(item.read_text(encoding="utf-8"))

        return {
            "doc_id": doc_id,
            "markdown": md_content,
            "content_list": content_list,
            "output_dir": str(output_dir),
        }
