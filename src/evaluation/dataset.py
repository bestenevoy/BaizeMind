import json
from pathlib import Path
from typing import Any, Optional

from config.settings import settings


class EvalDataset:
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = Path(dataset_path or settings.evaluation_dir / "dataset.json")
        # SQL/Excel 评测集合：独立文件，仅含 query_type == "sql_query" 的样本
        self.excel_dataset_path = settings.evaluation_dir / "excel_dataset.json"
        self._samples: list[dict] = []

    def load(self) -> list[dict[str, Any]]:
        if self.dataset_path.exists():
            self._samples = json.loads(self.dataset_path.read_text(encoding="utf-8"))
        return self._samples

    def load_excel(self) -> list[dict[str, Any]]:
        """加载 SQL/Excel 独立评测集合。"""
        if self.excel_dataset_path.exists():
            return json.loads(self.excel_dataset_path.read_text(encoding="utf-8"))
        return []

    def load_all(self) -> list[dict[str, Any]]:
        """合并加载文档评测集 + SQL/Excel 评测集。"""
        doc_samples = self.load()
        sql_samples = self.load_excel()
        self._samples = doc_samples + sql_samples
        return self._samples

    def save(self):
        self.dataset_path.parent.mkdir(parents=True, exist_ok=True)
        self.dataset_path.write_text(
            json.dumps(self._samples, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def save_excel(self, samples: list[dict]):
        self.excel_dataset_path.parent.mkdir(parents=True, exist_ok=True)
        self.excel_dataset_path.write_text(
            json.dumps(samples, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_sample(self, sample: dict):
        self._samples.append(sample)

    def add_samples(self, samples: list[dict]):
        self._samples.extend(samples)

    @property
    def samples(self) -> list[dict]:
        return self._samples

    def __len__(self) -> int:
        return len(self._samples)

    def by_type(self, query_type: str) -> list[dict]:
        return [s for s in self._samples if s.get("query_type") == query_type]
