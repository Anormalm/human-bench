from __future__ import annotations

import argparse
import json
from pathlib import Path

from shuorenhua_bench.dataset import read_jsonl
from shuorenhua_bench.schemas import Scenario
from shuorenhua_bench.splitting import grouped_split


def main() -> None:
    parser = argparse.ArgumentParser(description="Build leakage-resistant grouped splits")
    parser.add_argument("--scenarios", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=20260827)
    args = parser.parse_args()
    splits = grouped_split(read_jsonl(args.scenarios, Scenario), seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"seed": args.seed, "splits": splits}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

