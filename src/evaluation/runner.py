import json
import time
from pathlib import Path
from typing import Any, Optional

from src.evaluation.dataset import EvalDataset
from src.evaluation.metrics import EvalMetrics
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
        metrics = self.metrics.compute_metrics(samples, results)

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
        for k, v in metrics.items():
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
