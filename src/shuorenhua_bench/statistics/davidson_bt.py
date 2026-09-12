from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp


@dataclass(frozen=True)
class DavidsonResult:
    abilities: dict[str, float]
    tie_parameter: float
    converged: bool
    iterations: int
    log_likelihood: float
    position_bias: float = 0.0
    regularization: float = 0.01
    gradient_norm: float = 0.0


def comparison_components(comparisons: list[tuple[str, str, str]]) -> list[list[str]]:
    neighbors: dict[str, set[str]] = {}
    for a, b, _ in comparisons:
        neighbors.setdefault(a, set()).add(b)
        neighbors.setdefault(b, set()).add(a)
    components = []
    remaining = set(neighbors)
    while remaining:
        pending = [min(remaining)]
        component = set()
        while pending:
            node = pending.pop()
            if node not in component:
                component.add(node)
                pending.extend(neighbors[node] - component)
        remaining -= component
        components.append(sorted(component))
    return components


def fit_davidson(
    comparisons: list[tuple[str, str, str]], *, max_iter: int = 500,
    learning_rate: float = 0.05, tolerance: float = 1e-8,
    regularization: float = 0.01, fit_position: bool = False,
) -> DavidsonResult:
    """Penalized Davidson likelihood; a positive position coefficient favors displayed A.

    The penalty is regularization/2 * ||parameters||^2 on the SUM likelihood.
    This is a fixed Gaussian regularizer, not a hierarchical population model.
    learning_rate is retained for compatibility with v0.2 and is unused by L-BFGS.
    """
    if not comparisons or max_iter < 1 or regularization <= 0:
        raise ValueError("nonempty comparisons, positive iterations and regularization required")
    if any(a == b or y not in {"A", "B", "tie"} for a, b, y in comparisons):
        raise ValueError("comparisons require distinct systems and A/B/tie outcomes")
    if len(comparison_components(comparisons)) != 1:
        raise ValueError("disconnected comparison graph: abilities are not globally identifiable")
    names = sorted({s for a, b, _ in comparisons for s in (a, b)})
    lookup = {s: i for i, s in enumerate(names)}
    ia = np.array([lookup[a] for a, _, _ in comparisons])
    ib = np.array([lookup[b] for _, b, _ in comparisons])
    targets = np.array([{"A": 0, "B": 1, "tie": 2}[y] for _, _, y in comparisons])
    n = len(names)
    observed = np.eye(3)[targets]

    def objective(x):
        a, b = x[ia], x[ib]
        position = x[n + 1] if fit_position else 0.0
        logits = np.column_stack((a + position / 2, b - position / 2,
                                  (a + b) / 2 + x[n]))
        logs = logits - logsumexp(logits, axis=1, keepdims=True)
        residual = np.exp(logs) - observed
        gradient = regularization * x
        np.add.at(gradient, ia, residual[:, 0] + residual[:, 2] / 2)
        np.add.at(gradient, ib, residual[:, 1] + residual[:, 2] / 2)
        gradient[n] += residual[:, 2].sum()
        if fit_position:
            gradient[n + 1] += ((residual[:, 0] - residual[:, 1]) / 2).sum()
        value = -logs[np.arange(len(targets)), targets].sum()
        return value + regularization / 2 * np.dot(x, x), gradient

    result = minimize(objective, np.zeros(n + 1 + int(fit_position)), jac=True,
                      method="L-BFGS-B", options={"maxiter": max_iter, "ftol": tolerance,
                                                 "gtol": tolerance})
    x = result.x
    abilities = x[:n] - x[:n].mean()
    return DavidsonResult(
        abilities=dict(zip(names, abilities.tolist())), tie_parameter=float(np.exp(x[n])),
        converged=bool(result.success), iterations=int(result.nit),
        log_likelihood=float(-result.fun + regularization / 2 * np.dot(x, x)),
        position_bias=float(x[n + 1]) if fit_position else 0.0,
        regularization=regularization, gradient_norm=float(np.max(np.abs(result.jac))),
    )


def outcome_probabilities(result: DavidsonResult, system_a: str, system_b: str,
                          *, include_position: bool = False) -> dict[str, float]:
    a, b = result.abilities[system_a], result.abilities[system_b]
    position = result.position_bias if include_position else 0.0
    logits = np.array([a + position / 2, b - position / 2,
                       (a + b) / 2 + np.log(result.tie_parameter)])
    p = np.exp(logits - logsumexp(logits))
    return dict(zip(("A", "B", "tie"), p.tolist()))
