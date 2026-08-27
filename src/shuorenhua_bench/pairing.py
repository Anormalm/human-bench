from __future__ import annotations

import argparse
import hashlib
import itertools
import random
from collections import defaultdict
from pathlib import Path

from .dataset import read_jsonl, write_jsonl
from .schemas import Pair, Response


def build_pairs(responses: list[Response], seed: int = 20260827) -> list[Pair]:
    """Create all cross-system pairs per scenario with deterministic A/B counterbalancing."""
    grouped: dict[str, list[Response]] = defaultdict(list)
    for response in responses:
        grouped[response.scenario_id].append(response)

    rng = random.Random(seed)
    pairs: list[Pair] = []
    for scenario_id in sorted(grouped):
        candidates = sorted(grouped[scenario_id], key=lambda item: item.response_id)
        block = 0
        for left, right in itertools.combinations(candidates, 2):
            if left.system_id == right.system_id:
                continue
            a, b = (left, right) if rng.random() < 0.5 else (right, left)
            digest = hashlib.sha256(
                f"{scenario_id}\0{min(left.response_id, right.response_id)}\0"
                f"{max(left.response_id, right.response_id)}".encode()
            ).hexdigest()[:16]
            pairs.append(
                Pair(
                    pair_id=f"pair-{digest}",
                    scenario_id=scenario_id,
                    response_a=a.response_id,
                    response_b=b.response_id,
                    assignment_block=block,
                )
            )
            block += 1
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build blinded comparison pairs")
    parser.add_argument("--responses", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=20260827)
    args = parser.parse_args()
    write_jsonl(args.output, build_pairs(read_jsonl(args.responses, Response), args.seed))


if __name__ == "__main__":
    main()

