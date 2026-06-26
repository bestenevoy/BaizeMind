import os
import json
import shutil
import tempfile
import logging
from pathlib import Path
from typing import Optional

import src.document_parser.langchain_compat  # noqa: F401

from config.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PaddleX 缓存目录 & 模型路径解析
# ---------------------------------------------------------------------------
# 必须在 import paddleocr 之前设置 PADDLE_PDX_CACHE_HOME，
# PaddleX 在模块加载时读取此环境变量来确定官方模型缓存路径。
_paddle_cache = Path(settings.paddle_cache_dir)
if not _paddle_cache.is_absolute():
    _paddle_cache = settings.project_root / _paddle_cache
_paddle_cache.mkdir(parents=True, exist_ok=True)
# 使用直接赋值而非 setdefault，确保即使环境变量已被设为错误值也能覆盖
os.environ["PADDLE_PDX_CACHE_HOME"] = str(_paddle_cache.resolve())

# 官方模型存放在 <paddle_cache>/official_models/ 下
_official_models_dir = _paddle_cache / "official_models"


def _resolve_local_model_dir(setting_val: str, default_subdir: str) -> Optional[str]:
    """解析模型目录路径。

    优先级：
    1. settings 中显式指定的路径（如果存在）
    2. <paddle_cache>/official_models/<default_subdir>（如果存在）
    3. None（交给 PaddleOCR 自动下载）
    """
    # 1. 显式指定的路径
    if setting_val:
        p = Path(setting_val)
        if not p.is_absolute():
            p = settings.project_root / p
        if p.exists() and (p / "inference.yml").exists():
            return str(p.resolve())
        logger.warning(
            "PaddleOCR model dir '%s' does not contain inference.yml, "
            "falling back to auto-resolve",
            setting_val,
        )

    # 2. 从 paddle_cache_dir 自动解析
    candidate = _official_models_dir / default_subdir
    if candidate.exists() and (candidate / "inference.yml").exists():
        return str(candidate.resolve())

    # 3. 返回 None，让 PaddleOCR 自动下载
    return None


# 根据 pipeline_version 确定模型子目录名
_VERSION_MODEL_MAP = {
    "v1": {
        "vl_rec": "PaddleOCR-VL",
        "layout_det": "PP-DocLayoutV3",
    },
    "v1.5": {
        "vl_rec": "PaddleOCR-VL-1.5",
        "layout_det": "PP-DocLayoutV3",
    },
    "v1.6": {
        "vl_rec": "PaddleOCR-VL-1.6",
        "layout_det": "PP-DocLayoutV3",
    },
}


def _detect_device() -> str:
    """自动检测可用的推理设备。

    如果 settings.paddleocr_device 不是 "auto"，直接使用该值。
    否则尝试检测 GPU 是否可用。
    """
    configured = settings.paddleocr_device
    if configured and configured != "auto":
        return configured

    # 自动检测 GPU
    try:
        import paddle
        if paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            return "gpu:0"
    except Exception:
        pass

    logger.info("GPU not available, falling back to CPU for PaddleOCR-VL")
    return "cpu"


from paddleocr import PaddleOCRVL


class PaddleOCRParser:
    def __init__(
        self,
        vl_rec_model_dir: Optional[str] = None,
        layout_detection_model_dir: Optional[str] = None,
        device: Optional[str] = None,
    ):
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", settings.cuda_visible_devices)

        # 解析模型目录：优先使用参数 > settings > 自动从 paddle_cache_dir 解析 > None(自动下载)
        model_map = _VERSION_MODEL_MAP.get(
            settings.paddleocr_pipeline_version, _VERSION_MODEL_MAP["v1.6"]
        )

        vl_rec_dir = vl_rec_model_dir or _resolve_local_model_dir(
            settings.paddleocr_vl_model_dir, model_map["vl_rec"]
        )
        layout_det_dir = layout_detection_model_dir or _resolve_local_model_dir(
            settings.layout_detection_model_dir, model_map["layout_det"]
        )

        if vl_rec_dir:
            logger.info("PaddleOCR-VL rec model dir: %s", vl_rec_dir)
        else:
            logger.info("PaddleOCR-VL rec model: auto-download")

        if layout_det_dir:
            logger.info("Layout detection model dir: %s", layout_det_dir)
        else:
            logger.info("Layout detection model: auto-download")

        device = device or _detect_device()
        logger.info("PaddleOCR-VL device: %s", device)

        vllm_url = os.getenv("VLLM_SERVER_URL", "http://127.0.0.1:9123/v1")
        use_vllm = self._check_vllm(vllm_url)

        common_kwargs = dict(
            pipeline_version=settings.paddleocr_pipeline_version,
            vl_rec_model_dir=vl_rec_dir,
            layout_detection_model_dir=layout_det_dir,
            device=device,
            precision="fp32",
        )

        if use_vllm:
            self._pipeline = PaddleOCRVL(
                **common_kwargs,
                vl_rec_backend="vllm-server",
                vl_rec_server_url=vllm_url,
            )
        else:
            self._pipeline = PaddleOCRVL(
                **common_kwargs,
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

    def parse(self, file_path: str | Path, doc_id: Optional[str] = None) -> dict:
        """统一接口：返回 {doc_id, markdown, content_list, output_dir}。

        与 MinerUParser 保持相同契约，便于上游在两个 backend 间切换。
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        doc_id = doc_id or file_path.stem
        output_dir = Path(settings.paddleocr_output_dir) / doc_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # PaddleOCR 的 predict() 内部已经会写文件，但它的 save_path 是固定的，
        # 用一个临时目录接住结果再拷贝到 paddleocr_output_dir，避免路径污染。
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output = self._pipeline.predict(
                input=str(file_path),
                save_path=str(tmp_path),
            )
            self._save_results(output, tmp_path)
            markdown = self.load_markdown(tmp_path)
            content_list_json = self.load_json(tmp_path)

            # 复制到最终输出目录（保留可查看的中间产物）
            if tmp_path.exists():
                for item in tmp_path.iterdir():
                    target = output_dir / item.name
                    if item.is_dir():
                        shutil.copytree(item, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, target)

        return {
            "doc_id": doc_id,
            "markdown": markdown,
            "content_list": content_list_json.get("content_list", []) if content_list_json else [],
            "output_dir": str(output_dir),
        }

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
            try:
                return json.loads(json_files[0].read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}
