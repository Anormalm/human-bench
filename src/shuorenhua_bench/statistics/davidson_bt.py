from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DavidsonResult:
    abilities: dict[str, float]
    tie_parameter: float
    converged: bool
    iterations: int
    log_likelihood: float


def fit_davidson(
    comparisons: list[tuple[str, str, str]],
    *,
    max_iter: int = 500,
    learning_rate: float = 0.05,
    tolerance: float = 1e-8,
) -> DavidsonResult:
    """Fit Davidson's tie-aware Bradley–Terry model with Adam gradient ascent.

    Each comparison is ``(system_a, system_b, outcome)`` where outcome is A, B, or tie.
    Abilities are centered to zero for identifiability.
    """
    if not comparisons:
        raise ValueError("at least one comparison is required")
    names = sorted({name for a, b, _ in comparisons for name in (a, b)})
    index = {name: i for i, name in enumerate(names)}
    theta = np.zeros(len(names), dtype=float)
    log_nu = 0.0
    m = np.zeros(len(names) + 1)
    v = np.zeros(len(names) + 1)
    previous = -np.inf

    def objective_and_gradient() -> tuple[float, np.ndarray]:
        gradient = np.zeros(len(names) + 1)
        objective = 0.0
        nu = np.exp(log_nu)
        for a, b, outcome in comparisons:
            ia, ib = index[a], index[b]
            wa, wb = np.exp(theta[ia]), np.exp(theta[ib])
            tie_weight = nu * np.sqrt(wa * wb)
            denominator = wa + wb + tie_weight
            probs = np.array([wa, wb, tie_weight]) / denominator
            target = {"A": 0, "B": 1, "tie": 2}.get(outcome)
            if target is None:
                raise ValueError(f"invalid outcome: {outcome}")
            objective += np.log(max(probs[target], 1e-300))
            expected_a = probs[0] + 0.5 * probs[2]
            expected_b = probs[1] + 0.5 * probs[2]
            observed_a = 1.0 if target == 0 else 0.5 if target == 2 else 0.0
            observed_b = 1.0 if target == 1 else 0.5 if target == 2 else 0.0
            gradient[ia] += observed_a - expected_a
            gradient[ib] += observed_b - expected_b
            gradient[-1] += (1.0 if target == 2 else 0.0) - probs[2]
        return objective, gradient

    converged = False
    for iteration in range(1, max_iter + 1):
        objective, gradient = objective_and_gradient()
        gradient /= len(comparisons)
        m = 0.9 * m + 0.1 * gradient
        v = 0.999 * v + 0.001 * gradient * gradient
        m_hat = m / (1 - 0.9**iteration)
        v_hat = v / (1 - 0.999**iteration)
        update = learning_rate * m_hat / (np.sqrt(v_hat) + 1e-8)
        theta += update[:-1]
        theta -= theta.mean()
        log_nu += update[-1]
        if abs(objective - previous) < tolerance:
            converged = True
            break
        previous = objective
    final_objective, _ = objective_and_gradient()
    return DavidsonResult(
        abilities=dict(zip(names, theta.tolist())),
        tie_parameter=float(np.exp(log_nu)),
        converged=converged,
        iterations=iteration,
        log_likelihood=float(final_objective),
    )


def outcome_probabilities(result: DavidsonResult, system_a: str, system_b: str) -> dict[str, float]:
    wa = np.exp(result.abilities[system_a])
    wb = np.exp(result.abilities[system_b])
    tie = result.tie_parameter * np.sqrt(wa * wb)
    denominator = wa + wb + tie
    return {"A": float(wa / denominator), "B": float(wb / denominator), "tie": float(tie / denominator)}

