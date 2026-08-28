from __future__ import annotations

import argparse
import hashlib
import itertools
from collections import defaultdict
from pathlib import Path

from .dataset import read_jsonl, write_jsonl
from .schemas import Pair, Response


def build_pairs(responses: list[Response], seed: int = 20260827) -> list[Pair]:
    """Create all cross-system pairs per scenario with deterministic A/B counterbalancing."""
    grouped: dict[str, list[Response]] = defaultdict(list)
    for response in responses:
        grouped[response.scenario_id].append(response)

    pairs: list[Pair] = []
    position_balance: dict[str, int] = defaultdict(int)
    for scenario_id in sorted(grouped):
        candidates = sorted(grouped[scenario_id], key=lambda item: item.response_id)
        block = 0
        for left, right in itertools.combinations(candidates, 2):
            if left.system_id == right.system_id:
                continue
            digest = hashlib.sha256(
                f"{scenario_id}\0{min(left.response_id, right.response_id)}\0"
                f"{max(left.response_id, right.response_id)}".encode()
            ).hexdigest()[:16]
            forward_cost = abs(position_balance[left.system_id] + 1) + abs(
                position_balance[right.system_id] - 1
            )
            reverse_cost = abs(position_balance[left.system_id] - 1) + abs(
                position_balance[right.system_id] + 1
            )
            if forward_cost == reverse_cost:
                forward = int(hashlib.sha256(f"{seed}:{digest}".encode()).hexdigest(), 16) % 2 == 0
            else:
                forward = forward_cost < reverse_cost
            a, b = (left, right) if forward else (right, left)
            position_balance[a.system_id] += 1
            position_balance[b.system_id] -= 1
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
