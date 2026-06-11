import os
import json
from pathlib import Path
from typing import Optional

import src.document_parser.langchain_compat  # noqa: F401

from paddleocr import PaddleOCRVL
from config.settings import settings


class PaddleOCRParser:
    def __init__(
        self,
        vl_rec_model_dir: Optional[str] = None,
        layout_detection_model_dir: Optional[str] = None,
        device: str = "gpu:0",
    ):
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", settings.cuda_visible_devices)
        vl_rec_model_dir = vl_rec_model_dir or settings.paddleocr_vl_model_dir
        layout_detection_model_dir = layout_detection_model_dir or settings.layout_detection_model_dir

        vllm_url = os.getenv("VLLM_SERVER_URL", "http://127.0.0.1:9123/v1")
        use_vllm = self._check_vllm(vllm_url)

        if use_vllm:
            self._pipeline = PaddleOCRVL(
                vl_rec_model_dir=vl_rec_model_dir,
                layout_detection_model_dir=layout_detection_model_dir,
                device=device,
                precision="fp32",
                vl_rec_backend="vllm-server",
                vl_rec_server_url=vllm_url,
            )
        else:
            self._pipeline = PaddleOCRVL(
                vl_rec_model_dir=vl_rec_model_dir,
                layout_detection_model_dir=layout_detection_model_dir,
                device=device,
                precision="fp32",
                vl_rec_backend="native",
            )

    @staticmethod
    def _check_vllm(vllm_url: str) -> bool:
        try:
            import requests
            resp = requests.get(
                vllm_url.replace("/v1", "/health"), timeout=2
            )
            return resp.status_code == 200
        except Exception:
            return False

    def parse(self, file_path: str | Path, output_dir: str) -> list:
        file_path = Path(file_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        output = self._pipeline.predict(
            input=str(file_path),
            save_path=str(output_dir),
        )
        self._save_results(output, output_dir)
        return output

    def _save_results(self, output: list, output_dir: Path):
        for res in output:
            try:
                res.save_to_json(save_path=str(output_dir))
            except Exception:
                pass
            try:
                res.save_to_markdown(save_path=str(output_dir))
            except Exception:
                pass
            try:
                res.save_to_img(save_path=str(output_dir))
            except Exception:
                pass

    def load_markdown(self, output_dir: Path) -> str:
        md_files = sorted(output_dir.glob("*.md"))
        if md_files:
            return md_files[0].read_text(encoding="utf-8")
        return ""

    def load_json(self, output_dir: Path) -> dict:
        json_files = sorted(output_dir.glob("*.json"))
        if json_files:
            return json.loads(json_files[0].read_text(encoding="utf-8"))
        return {}
