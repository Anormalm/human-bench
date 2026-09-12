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
    parser.add_argument("--private-map", required=True, type=Path,
                        help="Private identity map; never serve this file to annotators")
    args = parser.parse_args()
    if args.private_map.resolve().is_relative_to(args.output.parent.resolve()):
        parser.error("--private-map must be outside the public bundle directory")
    identities = {}
    bundle = build_annotation_bundle(
        read_jsonl(args.scenarios, Scenario),
        read_jsonl(args.responses, Response),
        read_jsonl(args.pairs, Pair),
        id_map=identities,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.private_map.parent.mkdir(parents=True, exist_ok=True)
    args.private_map.write_text(json.dumps(identities, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
