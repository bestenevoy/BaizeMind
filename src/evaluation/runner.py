import json
import time
from pathlib import Path
from typing import Any, Optional

from src.evaluation.dataset import EvalDataset
from src.evaluation.metrics import EvalMetrics, compute_ragas_metrics
from src.agents.workflow import get_workflow
from config.settings import settings


class EvalRunner:
    def __init__(self, output_dir: Optional[str] = None):
        self.dataset = EvalDataset()
        self.metrics = EvalMetrics()
        self.output_dir = Path(output_dir or settings.evaluation_dir / "results")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        max_samples: Optional[int] = None,
        scope: str = "all",
    ) -> dict[str, Any]:
        """运行评测。

        Args:
            max_samples: 最多评测的样本数（截断）
            scope: "all"(默认, 合并文档+SQL 评测集) / "doc"(仅文档) / "sql"(仅 SQL/Excel)
        """
        if scope == "doc":
            samples = self.dataset.load()
        elif scope == "sql":
            samples = self.dataset.load_excel()
        else:
            samples = self.dataset.load_all()
        if max_samples:
            samples = samples[:max_samples]

        results = []
        start = time.time()

        print(f"Running evaluation on {len(samples)} samples...")

        for i, sample in enumerate(samples):
            print(f"  [{i+1}/{len(samples)}] {sample['query'][:60]}...")
            t0 = time.time()
            try:
                # 按 query_type 分流：sql_query 走独立检索评测（隔离生成质量）
                if sample.get("query_type") == "sql_query":
                    result = self._run_sql_sample(sample)
                else:
                    result = self._run_doc_sample(sample)
                elapsed_ms = (time.time() - t0) * 1000
                result["processing_time_ms"] = elapsed_ms
                result["is_negative_sample"] = sample.get("is_negative", False)
                results.append(result)
            except Exception as e:
                results.append({
                    "sample_id": sample.get("id", str(i)),
                    "query": sample["query"],
                    "query_type": sample.get("query_type", ""),
                    "predicted_answer": f"ERROR: {e}",
                    "cited_sources": [],
                    "retrieved_ids": [],
                    "retrieved_texts": [],
                    "is_negative_sample": sample.get("is_negative", False),
                    "error": str(e),
                })

        elapsed = time.time() - start

        # 文本 RAG 样本指标（IR, hallucination, timing）—— 仅对非 sql_query 样本计算
        doc_samples = [s for s in samples if s.get("query_type") != "sql_query"]
        doc_results = [r for r in results if r.get("query_type") != "sql_query"]
        custom_metrics = self.metrics.compute_metrics(doc_samples, doc_results)

        # SQL 检索指标（仅对 sql_query 样本）
        sql_metrics = self.metrics.compute_sql_metrics(samples, results)

        # Ragas QA-quality metrics (仅对非 sql_query 样本，因为 sql 样本不走 answer_generator)
        ragas_metrics = compute_ragas_metrics(doc_samples, doc_results)

        # Merge: 文档指标 + SQL 指标 + ragas 指标
        metrics = {**custom_metrics, **ragas_metrics, **sql_metrics}

        report = {
            "summary": metrics,
            "total_time_seconds": elapsed,
            "avg_time_per_sample": elapsed / len(samples) if samples else 0,
            "results": results,
        }

        output_path = self.output_dir / f"eval_{int(time.time())}.json"
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

        print(f"\nEvaluation complete. Results saved to {output_path}")
        self._print_summary(metrics)

        return report

    def _run_doc_sample(self, sample: dict) -> dict:
        """文本 RAG 样本：走完整 workflow（检索 + 生成 + 校验）。"""
        workflow = get_workflow()
        result = workflow.invoke(sample["query"])
        return {
            "sample_id": sample.get("id", ""),
            "query": sample["query"],
            "query_type": result.get("query_type", sample.get("query_type", "")),
            "predicted_answer": result.get("final_answer", ""),
            "cited_sources": result.get("citations", []),
            "retrieved_ids": [
                d.get("chunk_id", "") for d in result.get("documents", [])
            ],
            "retrieved_texts": [
                d.get("text", "") for d in result.get("documents", [])
            ],
        }

    def _run_sql_sample(self, sample: dict) -> dict:
        """SQL 样本：直接调 retrieve() 评估检索阶段（召回/选择/NL2SQL/执行），
        不走 answer_generator，以隔离生成质量，专注检索指标。"""
        from src.excel_rag.qa import ExcelQA
        qa = ExcelQA()
        r = qa.retrieve(sample["query"])

        recalled = r.get("recalled_sheets", []) or []
        recalled_ids = [
            (s.get("sheet_meta", s) if isinstance(s, dict) else s).get("meta_id", "")
            for s in recalled
        ]
        selected = r.get("selected_sheet") or {}
        selected_id = (selected.get("sheet_meta", {}) if selected else {}).get("meta_id")
        sql_result = r.get("sql_result") or {}

        # documents 字段填充为格式化文本，便于复用 hallucination 等指标
        docs = []
        if selected and r.get("sql"):
            from src.agents.workflow import _format_sql_result_as_document
            doc = _format_sql_result_as_document(
                sheet_meta=selected.get("sheet_meta", {}),
                sql=r.get("sql", ""),
                sql_result=sql_result,
                err=r.get("error", ""),
                score=selected.get("score", 0.0),
            )
            docs.append(doc)

        return {
            "sample_id": sample.get("id", ""),
            "query": sample["query"],
            "query_type": "sql_query",
            "predicted_answer": "",  # SQL 样本不评估生成，留空跳过 ragas
            "cited_sources": [],
            "retrieved_ids": [d.get("chunk_id", "") for d in docs],
            "retrieved_texts": [d.get("text", "") for d in docs],
            # SQL 专用字段（供 compute_sql_metrics 使用）
            "recalled_sheet_ids": recalled_ids,
            "selected_sheet_id": selected_id,
            "predicted_sql": r.get("sql", ""),
            "predicted_result": sql_result,
            "sql_error": r.get("error", ""),
        }

    def _print_summary(self, metrics: dict):
        print("\n" + "=" * 50)
        print("Evaluation Summary")
        print("=" * 50)
        print("  --- QA Quality (ragas) ---")
        for k in ["faithfulness", "answer_relevancy", "context_precision", "context_recall", "answer_correctness"]:
            if k in metrics:
                print(f"  {k}: {metrics[k]:.4f}")
        print("  --- Retrieval ---")
        for k in ["recall_at_5", "recall_at_10", "precision_at_5", "ndcg_at_5", "mrr"]:
            if k in metrics:
                print(f"  {k}: {metrics[k]:.4f}")
        print("  --- Hallucination ---")
        for k in ["intrinsic_hallucination_rate", "extrinsic_hallucination_rate"]:
            if k in metrics:
                print(f"  {k}: {metrics[k]:.4f}")
        print("  --- Other ---")
        for k in ["citation_accuracy", "context_redundancy", "delta_ndcg"]:
            if k in metrics:
                print(f"  {k}: {metrics[k]:.4f}")
        if any(k.startswith("sql_") or k in (
            "sheet_recall_at_1", "sheet_recall_at_3", "sheet_recall_at_5",
            "table_selection_accuracy", "sql_correctness", "execution_accuracy",
        ) for k in metrics):
            print("  --- SQL Retrieval (NL2SQL) ---")
            for k in [
                "sql_num_samples", "sql_error_count",
                "sheet_recall_at_1", "sheet_recall_at_3", "sheet_recall_at_5",
                "table_selection_accuracy", "sql_correctness", "execution_accuracy",
                "sql_timing_mean_ms",
            ]:
                if k in metrics and metrics[k] is not None:
                    v = metrics[k]
                    if isinstance(v, float):
                        print(f"  {k}: {v:.4f}")
                    else:
                        print(f"  {k}: {v}")
        print("=" * 50)


def main():
    runner = EvalRunner()
    runner.run()


if __name__ == "__main__":
    main()
