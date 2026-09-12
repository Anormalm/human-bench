from __future__ import annotations

import argparse
import json
from pathlib import Path

from shuorenhua_bench.dataset import read_jsonl
from shuorenhua_bench.leaderboard.aggregate import aggregate
from shuorenhua_bench.leaderboard.report import write_report
from shuorenhua_bench.schemas import PairwiseJudgment, Response, Scenario


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate human observations")
    parser.add_argument("--responses", required=True, type=Path)
    parser.add_argument("--judgments", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument("--scenarios", type=Path)
    parser.add_argument("--response-map", type=Path)
    args = parser.parse_args()
    judgments = read_jsonl(args.judgments, PairwiseJudgment)
    if args.response_map:
        mapping = json.loads(args.response_map.read_text(encoding="utf-8"))
        judgments = [j.model_copy(update={
            "response_a": mapping[j.response_a], "response_b": mapping[j.response_b],
            "spans": [s.model_copy(update={"response_id": mapping[s.response_id]}) for s in j.spans],
        }) for j in judgments]
    report = aggregate(
        judgments,
        read_jsonl(args.responses, Response),
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
        scenarios=read_jsonl(args.scenarios, Scenario) if args.scenarios else None,
    )
    write_report(report, args.output)


if __name__ == "__main__":
    main()
