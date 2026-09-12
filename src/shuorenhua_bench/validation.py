from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .schemas import Pair, PairwiseJudgment, Response, Scenario


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


def validate_dataset(scenarios: list[Scenario] | None, responses: list[Response],
                     pairs: list[Pair] | None = None,
                     judgments: list[PairwiseJudgment] | None = None) -> list[ValidationIssue]:
    issues = []

    def issue(code, message):
        issues.append(ValidationIssue(code, str(message)))

    def unique(rows, key):
        values = [getattr(row, key) for row in rows]
        if len(values) != len(set(values)):
            issue("duplicate_" + key, f"{key} must be unique")

    unique(scenarios or [], "scenario_id")
    unique(responses, "response_id")
    unique(pairs or [], "pair_id")
    scenario_ids = {s.scenario_id for s in scenarios or []}
    response_by_id = {r.response_id: r for r in responses}
    pair_by_id = {p.pair_id: p for p in pairs or []}
    for r in responses:
        if scenarios is not None and r.scenario_id not in scenario_ids:
            issue("orphan_response", r.response_id)
        if r.source_response_id:
            source = response_by_id.get(r.source_response_id)
            if source is None:
                issue("missing_source_response", r.response_id)
            elif source.scenario_id != r.scenario_id or source.response_id == r.response_id:
                issue("invalid_source_response", r.response_id)
        if (r.manifest and r.manifest.output_hash
                and hashlib.sha256(r.text.encode()).hexdigest() != r.manifest.output_hash):
            issue("output_hash_mismatch", r.response_id)

    def check_comparison(p):
        a, b = response_by_id.get(p.response_a), response_by_id.get(p.response_b)
        if a is None or b is None:
            issue("orphan_comparison_response", p.pair_id)
            return
        if a.scenario_id != p.scenario_id or b.scenario_id != p.scenario_id:
            issue("cross_scenario_pair", p.pair_id)
        if a.system_id == b.system_id:
            issue("same_system_pair", p.pair_id)
        if a.track != b.track or a.source_response_id != b.source_response_id:
            issue("incompatible_track_or_source", p.pair_id)

    for p in pairs or []:
        check_comparison(p)
    seen = set()
    definitions = {}
    for j in judgments or []:
        check_comparison(j)
        if not j.annotator_id.strip():
            issue("missing_annotator", j.pair_id)
        key = (j.pair_id, j.annotator_id)
        if key in seen:
            issue("duplicate_judgment", key)
        seen.add(key)
        definition = (j.scenario_id, frozenset((j.response_a, j.response_b)))
        if j.pair_id in definitions and definitions[j.pair_id] != definition:
            issue("inconsistent_pair_definition", j.pair_id)
        definitions[j.pair_id] = definition
        if pairs is not None:
            pair = pair_by_id.get(j.pair_id)
            if pair is None:
                issue("orphan_judgment", j.pair_id)
            elif definition != (pair.scenario_id, frozenset((pair.response_a, pair.response_b))):
                issue("judgment_pair_mismatch", j.pair_id)
        for span in j.spans:
            response = response_by_id.get(span.response_id)
            if span.response_id not in (j.response_a, j.response_b):
                issue("span_response_mismatch", j.pair_id)
            elif response is not None and span.end > len(response.text):
                issue("span_out_of_bounds", j.pair_id)
    return issues


def require_valid(scenarios, responses, pairs=None, judgments=None):
    issues = validate_dataset(scenarios, responses, pairs, judgments)
    if issues:
        raise ValueError("; ".join(f"{i.code}: {i.message}" for i in issues[:20]))
