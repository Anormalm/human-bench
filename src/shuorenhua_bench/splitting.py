from __future__ import annotations

import random
from collections import Counter, defaultdict

from .schemas import Scenario


class _UnionFind:
    def __init__(self, values: list[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def grouped_split(
    scenarios: list[Scenario],
    *,
    ratios: dict[str, float] | None = None,
    seed: int = 20260827,
) -> dict[str, list[str]]:
    """Leakage-resistant split by connected semantic/template groups.

    Scenarios sharing either semantic_cluster_id or source_template_id remain in
    one split. A seeded greedy objective balances split sizes and genres.
    """
    if not scenarios:
        raise ValueError("scenarios must not be empty")
    ratios = ratios or {"train": 0.6, "dev": 0.2, "test": 0.2}
    if any(value <= 0 for value in ratios.values()) or abs(sum(ratios.values()) - 1) > 1e-9:
        raise ValueError("split ratios must be positive and sum to one")
    ids = [item.scenario_id for item in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("scenario IDs must be unique")

    union_find = _UnionFind(ids)
    by_cluster: dict[str, list[str]] = defaultdict(list)
    by_template: dict[str, list[str]] = defaultdict(list)
    for item in scenarios:
        if item.semantic_cluster_id:
            by_cluster[item.semantic_cluster_id].append(item.scenario_id)
        if item.source_template_id:
            by_template[item.source_template_id].append(item.scenario_id)
    for values in [*by_cluster.values(), *by_template.values()]:
        for other in values[1:]:
            union_find.union(values[0], other)

    scenario_by_id = {item.scenario_id: item for item in scenarios}
    groups: dict[str, list[str]] = defaultdict(list)
    for identifier in ids:
        groups[union_find.find(identifier)].append(identifier)
    rng = random.Random(seed)
    ordered = list(groups.values())
    rng.shuffle(ordered)
    ordered.sort(key=len, reverse=True)

    targets = {name: ratio * len(scenarios) for name, ratio in ratios.items()}
    assignments: dict[str, list[str]] = {name: [] for name in ratios}
    genre_counts: dict[str, Counter] = {name: Counter() for name in ratios}
    total_genres = Counter(item.genre for item in scenarios)
    for group in ordered:
        group_genres = Counter(scenario_by_id[item].genre for item in group)

        def cost(split: str, group=group, group_genres=group_genres) -> float:
            size_after = len(assignments[split]) + len(group)
            size_cost = size_after / max(targets[split], 1)
            genre_cost = 0.0
            for genre, total in total_genres.items():
                desired = ratios[split] * total
                actual = genre_counts[split][genre] + group_genres[genre]
                genre_cost += abs(actual - desired) / max(desired, 1)
            return size_cost + 0.05 * genre_cost

        selected = min(ratios, key=lambda name: (cost(name), len(assignments[name]), name))
        assignments[selected].extend(group)
        genre_counts[selected].update(group_genres)
    return {name: sorted(values) for name, values in assignments.items()}
