#!/usr/bin/env python3
"""评测执行脚本"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.logging_config import setup_logging
setup_logging()

from src.evaluation.runner import EvalRunner


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run evaluation on the QA dataset")
    parser.add_argument("--max-samples", type=int, default=None, help="Maximum number of samples to evaluate")
    parser.add_argument("--dataset", type=str, default=None, help="Path to custom doc dataset JSON (overrides default dataset.json)")
    parser.add_argument(
        "--scope", choices=["all", "doc", "sql"], default="all",
        help="评测范围: all=合并文档+SQL评测集; doc=仅文档RAG; sql=仅SQL/Excel",
    )
    args = parser.parse_args()

    runner = EvalRunner()
    if args.dataset:
        runner.dataset.dataset_path = Path(args.dataset)

    runner.run(max_samples=args.max_samples, scope=args.scope)


if __name__ == "__main__":
    main()
