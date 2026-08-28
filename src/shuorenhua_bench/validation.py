from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .schemas import Pair, PairwiseJudgment, Response, Scenario


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


def validate_dataset(
    scenarios: list[Scenario],
    responses: list[Response],
    pairs: list[Pair] | None = None,
    judgments: list[PairwiseJudgment] | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    scenario_ids = {item.scenario_id for item in scenarios}
    response_ids = {item.response_id for item in responses}
    response_by_id = {item.response_id: item for item in responses}
    if len(scenario_ids) != len(scenarios):
        issues.append(ValidationIssue("duplicate_scenario_id", "Scenario IDs must be unique"))
    if len(response_ids) != len(responses):
        issues.append(ValidationIssue("duplicate_response_id", "Response IDs must be unique"))
    for response in responses:
        if response.scenario_id not in scenario_ids:
            issues.append(ValidationIssue("orphan_response", response.response_id))
        if response.source_response_id and response.source_response_id not in response_ids:
            issues.append(ValidationIssue("missing_source_response", response.response_id))
    pair_ids = set()
    for pair in pairs or []:
        pair_ids.add(pair.pair_id)
        if pair.response_a not in response_ids or pair.response_b not in response_ids:
            issues.append(ValidationIssue("orphan_pair", pair.pair_id))
            continue
        if (
            response_by_id[pair.response_a].scenario_id != pair.scenario_id
            or response_by_id[pair.response_b].scenario_id != pair.scenario_id
        ):
            issues.append(ValidationIssue("cross_scenario_pair", pair.pair_id))
    for judgment in judgments or []:
        if pair_ids and judgment.pair_id not in pair_ids:
            issues.append(ValidationIssue("orphan_judgment", judgment.pair_id))
        if judgment.response_a not in response_ids or judgment.response_b not in response_ids:
            issues.append(ValidationIssue("orphan_judgment_response", judgment.pair_id))
    exposure = Counter(
        response_id for pair in pairs or [] for response_id in (pair.response_a, pair.response_b)
    )
    if exposure and max(exposure.values()) - min(exposure.values()) > 1:
        issues.append(ValidationIssue("unbalanced_exposure", dict(exposure).__repr__()))
    return issues
