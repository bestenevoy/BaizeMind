#!/usr/bin/env python3
"""评测执行脚本"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.evaluation.runner import EvalRunner


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run evaluation on the QA dataset")
    parser.add_argument("--max-samples", type=int, default=None, help="Maximum number of samples to evaluate")
    parser.add_argument("--dataset", type=str, default=None, help="Path to custom dataset JSON")
    args = parser.parse_args()

    runner = EvalRunner()
    if args.dataset:
        runner.dataset.dataset_path = Path(args.dataset)

    runner.run(max_samples=args.max_samples)


if __name__ == "__main__":
    main()
