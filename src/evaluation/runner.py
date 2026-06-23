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

    def run(self, max_samples: Optional[int] = None) -> dict[str, Any]:
        samples = self.dataset.load()
        if max_samples:
            samples = samples[:max_samples]

        results = []
        start = time.time()

        print(f"Running evaluation on {len(samples)} samples...")

        for i, sample in enumerate(samples):
            print(f"  [{i+1}/{len(samples)}] {sample['query'][:60]}...")
            t0 = time.time()
            try:
                workflow = get_workflow()
                result = workflow.invoke(sample["query"])
                elapsed_ms = (time.time() - t0) * 1000

                results.append({
                    "sample_id": sample.get("id", str(i)),
                    "query": sample["query"],
                    "query_type": result.get("query_type", ""),
                    "predicted_answer": result.get("final_answer", ""),
                    "cited_sources": result.get("citations", []),
                    "retrieved_ids": [
                        d.get("chunk_id", "") for d in result.get("documents", [])
                    ],
                    "retrieved_texts": [
                        d.get("text", "") for d in result.get("documents", [])
                    ],
                    "is_negative_sample": sample.get("is_negative", False),
                    "processing_time_ms": elapsed_ms,
                })
            except Exception as e:
                results.append({
                    "sample_id": sample.get("id", str(i)),
                    "query": sample["query"],
                    "predicted_answer": f"ERROR: {e}",
                    "cited_sources": [],
                    "retrieved_ids": [],
                    "retrieved_texts": [],
                    "is_negative_sample": sample.get("is_negative", False),
                    "error": str(e),
                })

        elapsed = time.time() - start

        # Custom metrics (IR, hallucination, timing)
        custom_metrics = self.metrics.compute_metrics(samples, results)

        # Ragas QA-quality metrics (faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness)
        ragas_metrics = compute_ragas_metrics(samples, results)

        # Merge: ragas metrics override/replace legacy equivalents
        metrics = {**custom_metrics, **ragas_metrics}

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
        print("=" * 50)


def main():
    runner = EvalRunner()
    runner.run()


if __name__ == "__main__":
    main()
