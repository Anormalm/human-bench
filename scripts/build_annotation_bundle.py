from __future__ import annotations

import argparse
import json
from pathlib import Path

from shuorenhua_bench.annotation_bundle import build_annotation_bundle
from shuorenhua_bench.dataset import read_jsonl
from shuorenhua_bench.schemas import Pair, Response, Scenario


def main() -> None:
    parser = argparse.ArgumentParser(description="Join scenarios, responses, and pairs for annotation")
    parser.add_argument("--scenarios", required=True, type=Path)
    parser.add_argument("--responses", required=True, type=Path)
    parser.add_argument("--pairs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    bundle = build_annotation_bundle(
        read_jsonl(args.scenarios, Scenario),
        read_jsonl(args.responses, Response),
        read_jsonl(args.pairs, Pair),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()

