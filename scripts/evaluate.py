from __future__ import annotations

import argparse
from pathlib import Path

from shuorenhua_bench.dataset import read_jsonl
from shuorenhua_bench.leaderboard.aggregate import aggregate
from shuorenhua_bench.leaderboard.report import write_report
from shuorenhua_bench.schemas import PairwiseJudgment, Response


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate human observations")
    parser.add_argument("--responses", required=True, type=Path)
    parser.add_argument("--judgments", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260827)
    args = parser.parse_args()
    report = aggregate(
        read_jsonl(args.judgments, PairwiseJudgment),
        read_jsonl(args.responses, Response),
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
    )
    write_report(report, args.output)


if __name__ == "__main__":
    main()
