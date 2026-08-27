from __future__ import annotations

from collections.abc import Callable

import numpy as np


def clustered_bootstrap(
    records: list[dict],
    statistic: Callable[[list[dict]], float],
    *,
    cluster_key: str = "scenario_id",
    samples: int = 1000,
    seed: int = 20260827,
    confidence: float = 0.95,
) -> tuple[float, float]:
    if not records:
        raise ValueError("records must not be empty")
    clusters: dict[str, list[dict]] = {}
    for record in records:
        clusters.setdefault(str(record[cluster_key]), []).append(record)
    keys = list(clusters)
    rng = np.random.default_rng(seed)
    estimates = []
    for _ in range(samples):
        sampled_keys = rng.choice(keys, size=len(keys), replace=True)
        sampled = [row for key in sampled_keys for row in clusters[key]]
        estimates.append(statistic(sampled))
    alpha = (1 - confidence) / 2
    return tuple(float(x) for x in np.quantile(estimates, [alpha, 1 - alpha]))

