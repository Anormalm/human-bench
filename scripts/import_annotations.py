from __future__ import annotations

import argparse
import json
from pathlib import Path

from shuorenhua_bench.dataset import write_jsonl
from shuorenhua_bench.schemas import PairwiseJudgment


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize a Label Studio JSON export")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    tasks = json.loads(args.input.read_text(encoding="utf-8"))
    records = []
    for task in tasks:
        data = task["data"]
        for annotation in task.get("annotations", []):
            values = {
                item["from_name"]: item["value"].get("choices", [item["value"].get("rating")])[0]
                for item in annotation.get("result", [])
            }
            records.append(
                PairwiseJudgment(
                    pair_id=data["pair_id"], scenario_id=data["scenario_id"],
                    annotator_id=str(annotation.get("completed_by", "unknown")),
                    response_a=data["response_a"], response_b=data["response_b"],
                    preference=values["preference"], action_a=values["action_a"],
                    action_b=values["action_b"], confidence=int(values["confidence"]),
                    duration_seconds=annotation.get("lead_time"),
                )
            )
    write_jsonl(args.output, records)


if __name__ == "__main__":
    main()

