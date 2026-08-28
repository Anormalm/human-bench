from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np

from ..schemas import PairwiseJudgment, Response
from ..statistics.davidson_bt import fit_davidson


def _wilson(successes: int, total: int, z: float = 1.96) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def _normalized_entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total <= 1:
        return 0.0
    probabilities = [counts[label] / total for label in ("A", "B", "tie") if counts[label]]
    return -sum(p * math.log(p) for p in probabilities) / math.log(3)


def _bootstrap_abilities(
    judgments: list[PairwiseJudgment],
    systems: dict[str, str],
    *,
    samples: int,
    seed: int,
) -> dict[str, list[float]]:
    if samples <= 0:
        return {}
    by_scenario: dict[str, list[PairwiseJudgment]] = defaultdict(list)
    for judgment in judgments:
        by_scenario[judgment.scenario_id].append(judgment)
    keys = sorted(by_scenario)
    rng = np.random.default_rng(seed)
    estimates: dict[str, list[float]] = defaultdict(list)
    for _ in range(samples):
        sample_keys = rng.choice(keys, size=len(keys), replace=True)
        sampled = [item for key in sample_keys for item in by_scenario[str(key)]]
        comparisons = [
            (systems[item.response_a], systems[item.response_b], item.preference)
            for item in sampled
        ]
        result = fit_davidson(comparisons, max_iter=250)
        for system, ability in result.abilities.items():
            estimates[system].append(ability)
    return {
        system: [float(x) for x in np.quantile(values, [0.025, 0.975])]
        for system, values in estimates.items()
    }


def aggregate(
    judgments: list[PairwiseJudgment],
    responses: list[Response],
    *,
    bootstrap_samples: int = 200,
    seed: int = 20260827,
) -> dict:
    if not judgments:
        raise ValueError("at least one human judgment is required")
    systems = {response.response_id: response.system_id for response in responses}
    missing = {
        response_id
        for item in judgments
        for response_id in (item.response_a, item.response_b)
        if response_id not in systems
    }
    if missing:
        raise ValueError(f"judgments reference missing responses: {sorted(missing)}")

    comparisons = [
        (systems[item.response_a], systems[item.response_b], item.preference) for item in judgments
    ]
    result = fit_davidson(comparisons)
    ability_intervals = _bootstrap_abilities(judgments, systems, samples=bootstrap_samples, seed=seed)
    actions: dict[str, Counter] = defaultdict(Counter)
    outcomes: dict[str, Counter] = defaultdict(Counter)
    pair_votes: dict[str, Counter] = defaultdict(Counter)
    for item in judgments:
        system_a, system_b = systems[item.response_a], systems[item.response_b]
        actions[system_a][item.action_a] += 1
        actions[system_b][item.action_b] += 1
        pair_votes[item.pair_id][item.preference] += 1
        if item.preference == "A":
            outcomes[system_a]["win"] += 1
            outcomes[system_b]["loss"] += 1
        elif item.preference == "B":
            outcomes[system_b]["win"] += 1
            outcomes[system_a]["loss"] += 1
        else:
            outcomes[system_a]["tie"] += 1
            outcomes[system_b]["tie"] += 1

    system_summary = {}
    for system in sorted(set(systems.values())):
        action_counts = actions[system]
        outcome_counts = outcomes[system]
        action_total = sum(action_counts.values())
        comparison_total = sum(outcome_counts.values())
        send_count = action_counts["send"]
        system_summary[system] = {
            "ability": result.abilities.get(system),
            "ability_95ci_prompt_bootstrap": ability_intervals.get(system),
            "empirical_preference_rate": (
                (outcome_counts["win"] + 0.5 * outcome_counts["tie"]) / comparison_total
                if comparison_total
                else None
            ),
            "wins": outcome_counts["win"],
            "ties": outcome_counts["tie"],
            "losses": outcome_counts["loss"],
            "direct_use_rate": send_count / action_total if action_total else None,
            "direct_use_95ci_wilson": _wilson(send_count, action_total),
            "action_distribution": {
                label: action_counts[label] / action_total if action_total else 0.0
                for label in ("send", "revise", "reject")
            },
        }

    disagreement = [_normalized_entropy(votes) for votes in pair_votes.values()]
    return {
        "schema_version": "0.2",
        "pairwise_model": {
            "name": "Davidson-Bradley-Terry",
            "tie_parameter": result.tie_parameter,
            "converged": result.converged,
            "iterations": result.iterations,
        },
        "systems": system_summary,
        "agreement": {
            "mean_pair_disagreement_entropy": float(np.mean(disagreement)),
            "high_disagreement_pair_fraction": float(np.mean(np.array(disagreement) >= 0.75)),
        },
        "sample": {
            "n_judgments": len(judgments),
            "n_pairs": len(pair_votes),
            "n_scenarios": len({item.scenario_id for item in judgments}),
            "n_annotators": len({item.annotator_id for item in judgments}),
        },
        "disclaimer": (
            "These are context-conditioned human preference estimates, not a universal "
            "human-likeness score. Source detectability is a separate construct."
        ),
    }
