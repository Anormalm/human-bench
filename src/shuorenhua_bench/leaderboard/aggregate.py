from __future__ import annotations

from collections import Counter, defaultdict

from ..schemas import PairwiseJudgment, Response
from ..statistics.davidson_bt import fit_davidson


def aggregate(judgments: list[PairwiseJudgment], responses: list[Response]) -> dict:
    systems = {response.response_id: response.system_id for response in responses}
    comparisons = [
        (systems[item.response_a], systems[item.response_b], item.preference) for item in judgments
    ]
    result = fit_davidson(comparisons)
    actions: dict[str, Counter] = defaultdict(Counter)
    for item in judgments:
        actions[systems[item.response_a]][item.action_a] += 1
        actions[systems[item.response_b]][item.action_b] += 1
    action_rates = {}
    for system, counts in actions.items():
        total = sum(counts.values())
        action_rates[system] = {label: counts[label] / total for label in ("send", "revise", "reject")}
    return {
        "pairwise": {
            "abilities": result.abilities,
            "tie_parameter": result.tie_parameter,
            "converged": result.converged,
            "iterations": result.iterations,
        },
        "direct_use": action_rates,
        "n_judgments": len(judgments),
        "disclaimer": "Diagnostics and abilities are multidimensional evidence, not a universal human-likeness score.",
    }

