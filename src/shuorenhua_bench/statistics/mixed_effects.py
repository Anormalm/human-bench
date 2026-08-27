from __future__ import annotations

from typing import Any


def fit_direct_use_mixed_model(rows: list[dict[str, Any]]) -> Any:
    """Fit a binomial mixed model for direct use via the optional statsmodels backend.

    Rows require ``send`` (0/1), ``system_id``, ``scenario_id``, and ``annotator_id``.
    The three-class ordinal model is deferred until pilot data can justify proportional odds.
    """
    try:
        import pandas as pd
        from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM
    except ImportError as exc:
        raise RuntimeError("install shuorenhua-bench[stats] for mixed-effects models") from exc
    frame = pd.DataFrame(rows)
    required = {"send", "system_id", "scenario_id", "annotator_id"}
    if missing := required - set(frame.columns):
        raise ValueError(f"missing columns: {sorted(missing)}")
    return BinomialBayesMixedGLM.from_formula(
        "send ~ C(system_id)",
        {"scenario": "0 + C(scenario_id)", "annotator": "0 + C(annotator_id)"},
        frame,
    ).fit_vb()

