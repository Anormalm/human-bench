from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict

import numpy as np

from ..schemas import PairwiseJudgment, Response, Scenario
from ..statistics.davidson_bt import comparison_components, fit_davidson, outcome_probabilities
from ..validation import require_valid


def _normalized_entropy(counts):
    total = sum(counts.values())
    return -sum((v / total) * math.log(v / total) for v in counts.values() if v) / math.log(3)


def _clusters(scenarios, judgments):
    # Transitive closure over BOTH identifiers; a template and a semantic cluster can bridge.
    ids = sorted({j.scenario_id for j in judgments})
    parent = {s.scenario_id: s.scenario_id for s in scenarios or []}
    parent.update({s: parent.get(s, s) for s in ids})

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owners = {}
    for s in sorted(scenarios or [], key=lambda s: s.scenario_id):
        for field in ("semantic_cluster_id", "source_template_id"):
            value = getattr(s, field)
            if value:
                key = (field, value)
                if key in owners:
                    parent[find(s.scenario_id)] = find(owners[key])
                owners[key] = s.scenario_id
    return {s: find(s) for s in ids}


def _ci(values, alpha=0.05):
    if len(values) < 2:
        return None
    lower, upper = (float(x) for x in np.quantile(values, [alpha / 2, 1 - alpha / 2]))
    # A collapsed empirical bootstrap is not evidence of zero population uncertainty.
    return None if math.isclose(lower, upper, rel_tol=1e-9, abs_tol=1e-10) else [lower, upper]


def _position_identifiable(comparisons, names):
    design = np.zeros((len(comparisons), len(names)))
    indices = {s: i for i, s in enumerate(names)}
    for i, (a, b, _) in enumerate(comparisons):
        if indices[a] < len(names) - 1:
            design[i, indices[a]] += 1
        if indices[b] < len(names) - 1:
            design[i, indices[b]] -= 1
        design[i, -1] = 1
    return bool(np.linalg.matrix_rank(design) == len(names))


def _actions(judgments, systems):
    # One action per annotator/response. Multiple comparisons must not inflate n.
    observations = defaultdict(list)
    for j in judgments:
        observations[(j.scenario_id, j.annotator_id, j.response_a)].append(j.action_a)
        observations[(j.scenario_id, j.annotator_id, j.response_b)].append(j.action_b)
    by_system = defaultdict(list)
    conflicts = 0
    for (_, _, response), labels in observations.items():
        conflicts += int(len(set(labels)) > 1)
        by_system[systems[response]].append(
            {label: labels.count(label) / len(labels) for label in ("send", "revise", "reject")}
        )
    return {
        system: {label: float(np.mean([row[label] for row in rows]))
                 for label in ("send", "revise", "reject")}
        for system, rows in by_system.items()
    }, {s: len(rows) for s, rows in by_system.items()}, conflicts


def aggregate(judgments: list[PairwiseJudgment], responses: list[Response], *,
              bootstrap_samples: int = 200, seed: int = 20260827,
              scenarios: list[Scenario] | None = None, pairs=None,
              min_raters: int = 3, fit_position: bool = True) -> dict:
    if not judgments:
        raise ValueError("at least one judgment is required")
    if bootstrap_samples < 0 or min_raters < 1:
        raise ValueError("invalid bootstrap sample count or minimum raters")
    evidence = {j.evidence_kind for j in judgments}
    if len(evidence) != 1:
        raise ValueError("evaluate human, model and synthetic evidence separately")
    model_judged = evidence == {"model"}
    require_valid(scenarios, responses, pairs, judgments)
    systems = {r.response_id: r.system_id for r in responses}
    response_lookup = {r.response_id: r for r in responses}
    used_responses = {r for j in judgments for r in (j.response_a, j.response_b)}
    tracks = {response_lookup[r].track for r in used_responses}
    if len(tracks) != 1:
        raise ValueError("evaluate native_generation and humanization tracks separately")
    track_systems = {r.system_id for r in responses if r.track in tracks}
    comparisons = [(systems[j.response_a], systems[j.response_b], j.preference) for j in judgments]
    components = comparison_components(comparisons)
    if len(components) > 1:
        raise ValueError(f"disconnected comparison graph: {components}; collect bridge comparisons")
    names = sorted({s for a, b, _ in comparisons for s in (a, b)})
    # Check identifiability of system effects AND position before adjusting.
    position_identifiable = _position_identifiable(comparisons, names)
    adjust_position = fit_position and position_identifiable
    result = fit_davidson(comparisons, fit_position=adjust_position)
    action_rates, action_ns, action_conflicts = _actions(judgments, systems)
    cluster_map = _clusters(scenarios, judgments)
    clustered = defaultdict(list)
    for j in judgments:
        clustered[cluster_map[j.scenario_id]].append(j)
    keys = sorted(clustered)
    rng = np.random.default_rng(seed)
    ability_samples, direct_samples, rank_samples = defaultdict(list), defaultdict(list), defaultdict(list)
    contrast_samples = defaultdict(list)
    skipped = 0
    effective_samples = bootstrap_samples if len(keys) >= 2 else 0
    for _ in range(effective_samples):
        sampled = []
        # Unique occurrence IDs keep duplicated clusters as duplicated observations.
        for occurrence, key in enumerate(rng.choice(keys, len(keys), replace=True)):
            sampled.extend(j.model_copy(update={"scenario_id": f"{occurrence}:{j.scenario_id}"})
                           for j in clustered[str(key)])
        rates, _, _ = _actions(sampled, systems)
        for s, rates_s in rates.items():
            direct_samples[s].append(rates_s["send"])
        comps = [(systems[j.response_a], systems[j.response_b], j.preference) for j in sampled]
        if ({s for a, b, _ in comps for s in (a, b)} != set(names)
                or len(comparison_components(comps)) != 1
                or (adjust_position and not _position_identifiable(comps, names))):
            skipped += 1
            continue
        fitted = fit_davidson(comps, fit_position=adjust_position)
        if not fitted.converged:
            skipped += 1
            continue
        for s in names:
            ability_samples[s].append(fitted.abilities[s])
            rank_samples[s].append(1 + sum(fitted.abilities[t] > fitted.abilities[s] + 1e-8
                                          for t in names))
        for a, b in itertools.combinations(names, 2):
            contrast_samples[(a, b)].append(fitted.abilities[a] - fitted.abilities[b])
    outcomes, pair_votes, raters = defaultdict(Counter), defaultdict(Counter), defaultdict(set)
    position = defaultdict(Counter)
    head_to_head = defaultdict(Counter)
    for j in judgments:
        a, b = systems[j.response_a], systems[j.response_b]
        position[a]["A"] += 1
        position[b]["B"] += 1
        winner = a if j.preference == "A" else b if j.preference == "B" else "tie"
        outcomes[a]["tie" if winner == "tie" else "win" if winner == a else "loss"] += 1
        outcomes[b]["tie" if winner == "tie" else "win" if winner == b else "loss"] += 1
        canonical = tuple(sorted((a, b)))
        label = "tie" if winner == "tie" else "A" if winner == canonical[0] else "B"
        head_to_head[canonical][label] += 1
        # Normalize reversed displays before computing agreement.
        canonical_responses = sorted((j.response_a, j.response_b))
        vote = "tie" if j.preference == "tie" else (
            "A" if (j.response_a if j.preference == "A" else j.response_b) == canonical_responses[0] else "B"
        )
        pair_votes[j.pair_id][vote] += 1
        raters[j.pair_id].add(j.annotator_id)
    system_summary = {}
    reliable_bootstrap = (effective_samples >= 100 and skipped / effective_samples <= 0.1
                          and result.converged and len(keys) >= 30)
    for s in sorted(track_systems):
        n = sum(outcomes[s].values())
        system_summary[s] = {
            "ability": result.abilities.get(s),
            "ability_95ci_cluster_bootstrap": _ci(ability_samples[s]),
            "rank_95ci_cluster_bootstrap": _ci(rank_samples[s]),
            "empirical_preference_rate": (outcomes[s]["win"] + 0.5 * outcomes[s]["tie"]) / n if n else None,
            "wins": outcomes[s]["win"], "ties": outcomes[s]["tie"], "losses": outcomes[s]["loss"],
            "direct_use_rate": action_rates.get(s, {}).get("send"),
            "direct_use_95ci_cluster_bootstrap": _ci(direct_samples[s]),
            "n_direct_use_bootstrap_samples": len(direct_samples[s]),
            "n_unique_response_rater_actions": action_ns.get(s, 0),
            "action_distribution": action_rates.get(s, {}),
            "display_position_counts": dict(position[s]),
        }
    contrasts = []
    # Bonferroni simultaneous percentile intervals across declared system contrasts.
    # Descriptive ordinary intervals remain visible, never a claim of an exact familywise guarantee.
    alpha = 0.05 / max(1, len(contrast_samples))
    for a, b in itertools.combinations(names, 2):
        values = contrast_samples[(a, b)]
        ci = _ci(values)
        simultaneous = _ci(values, alpha=alpha)
        probs = outcome_probabilities(result, a, b)
        contrasts.append({
            "system_a": a, "system_b": b, "counts": dict(head_to_head[(a, b)]),
            "neutral_position_probabilities": probs,
            "tie_adjusted_preference_probability_a": probs["A"] + 0.5 * probs["tie"],
            "ability_difference": result.abilities[a] - result.abilities[b],
            "difference_95ci": ci, "difference_familywise_95ci_bonferroni_percentile": simultaneous,
            "separated_exploratory": bool(reliable_bootstrap and simultaneous
                                          and (simultaneous[0] > 0 or simultaneous[1] < 0)),
        })
    eligible_votes = [v for v in pair_votes.values() if sum(v.values()) >= 2]
    entropy = [_normalized_entropy(v) for v in eligible_votes]
    agreements = [sum(c * (c - 1) for c in v.values()) / (sum(v.values()) * (sum(v.values()) - 1))
                  for v in eligible_votes]
    expected_pair_ids = {p.pair_id for p in pairs} if pairs is not None else set(pair_votes)
    short = sorted(p for p in expected_pair_ids if len(raters[p]) < min_raters)
    warnings = []
    degenerate = [f"{metric}:{name}" for metric, series in (
        ("ability", ability_samples), ("direct_use", direct_samples), ("rank", rank_samples))
        for name, values in series.items() if len(values) >= 2 and _ci(values) is None]
    if degenerate:
        warnings.append("Zero-width bootstrap intervals are withheld; repeated identical outcomes "
                        "do not establish zero uncertainty.")
    all_ties = all(j.preference == "tie" for j in judgments)
    if all_ties:
        warnings.append("Every observed preference is a tie; no winner or equivalence claim is supported.")
    if len(keys) < 30:
        warnings.append("Fewer than 30 independent scenario groups; uncertainty is exploratory.")
    if fit_position and not position_identifiable:
        warnings.append("Display position is confounded with systems; position adjustment disabled.")
    if not reliable_bootstrap:
        warnings.append("Separation requires 30 independent groups, 100 bootstrap attempts, "
                        "no more than 10% lost fits and primary convergence; these conditions are not all met.")
    if short:
        warnings.append(f"{len(short)} pairs have fewer than {min_raters} distinct annotators.")
    if not result.converged:
        warnings.append("Primary optimizer did not converge; do not interpret abilities.")
    if scenarios is None:
        warnings.append("No scenario metadata: bootstrap groups are prompts, not semantic/template families.")
    if action_conflicts:
        warnings.append(f"{action_conflicts} response/rater actions disagree across comparisons; averaged.")
    unobserved = sorted(track_systems - set(names))
    if unobserved:
        warnings.append(f"No judgments for systems: {unobserved}; their estimates are unavailable.")
    if model_judged:
        warnings.append("MODEL-JUDGED screening: these predictions are not human preferences. "
                        "Judge bias and errors are not captured by the bootstrap intervals.")
    elif evidence != {"human"}:
        warnings.append("SYNTHETIC evidence is present: this report is a software demonstration.")
    slices = {}
    if scenarios is not None:
        scenario_lookup = {s.scenario_id: s for s in scenarios}
        for field in ("language", "genre", "relationship", "intent"):
            groups = defaultdict(list)
            for j in judgments:
                groups[getattr(scenario_lookup[j.scenario_id], field)].append(j)
            slices[field] = {
                key: {"n_judgments": len(rows), "n_scenarios": len({j.scenario_id for j in rows}),
                      "direct_use": _actions(rows, systems)[0]}
                for key, rows in sorted(groups.items())
            }
    rater_groups = defaultdict(list)
    span_counts = defaultdict(Counter)
    unique_span_observations = set()
    for j in judgments:
        rater_groups[j.annotator_id].append(j)
        for span in j.spans:
            key = (j.annotator_id, span.response_id, span.type, span.start, span.end)
            if key not in unique_span_observations:
                span_counts[systems[span.response_id]][span.type] += 1
                unique_span_observations.add(key)
    rater_diagnostics = {}
    for rater, rows in sorted(rater_groups.items()):
        durations = [j.duration_seconds for j in rows if j.duration_seconds is not None]
        rater_diagnostics[rater] = {
            "n_judgments": len(rows), "display_preference_counts": dict(Counter(j.preference for j in rows)),
            "median_duration_seconds": float(np.median(durations)) if durations else None,
            "n_timed_judgments": len(durations), "automatic_exclusion": False,
        }
    return {
        "schema_version": "0.3", "analysis_version": "0.5.0", "evidence_kind": "model_judged" if model_judged else (
            "human" if evidence == {"human"} else "synthetic_or_mixed"),
        "ranking_status": "no_separation" if all_ties else "available",
        "track": next(iter(tracks)), "systems": system_summary, "contrasts": contrasts,
        "pairwise_model": {
            "name": "regularized Davidson-Bradley-Terry", "tie_parameter": result.tie_parameter,
            "converged": result.converged, "iterations": result.iterations,
            "gradient_norm": result.gradient_norm, "regularization": result.regularization,
            "position_adjusted": adjust_position, "position_bias_log_odds": result.position_bias,
            "comparison_components": components,
        },
        "uncertainty": {
            "method": "connected semantic/template cluster percentile bootstrap",
            "requested_samples": bootstrap_samples, "attempted_samples": effective_samples,
            "successful_model_samples": effective_samples - skipped, "skipped_model_samples": skipped,
            "n_independent_groups": len(keys), "seed": seed,
            "withheld_degenerate_intervals": degenerate,
            "scope": "scenario sampling, conditional on a fixed model judge and accepted comparisons; "
                     "not human preference or judge uncertainty" if model_judged else
                     "scenario sampling, conditional on recruited annotators; not population uncertainty",
        },
        "agreement": {
            "mean_pair_disagreement_entropy": float(np.mean(entropy)) if entropy else None,
            "mean_pairwise_agreement": float(np.mean(agreements)) if agreements else None,
            "n_pairs_with_multiple_raters": len(eligible_votes),
            "conflicting_repeated_actions": action_conflicts,
        },
        "coverage": {"minimum_raters_per_pair": min_raters, "under_annotated_pairs": short,
                     "n_expected_pairs": len(expected_pair_ids)},
        "sample": {"n_judgments": len(judgments), "n_pairs": len(pair_votes),
                   "n_scenarios": len({j.scenario_id for j in judgments}),
                   "n_annotators": 0 if model_judged else len({j.annotator_id for j in judgments}),
                   "n_model_judges": len({j.annotator_id for j in judgments}) if model_judged else 0},
        "slices": slices, "warnings": warnings, "rater_diagnostics": rater_diagnostics,
        "problem_spans": {"counts_by_system_and_type": {s: dict(c) for s, c in span_counts.items()},
                          "interpretation": "Optional flags: counts only, not error prevalence or quality scores."},
        "disclaimer": "Context-conditioned preference estimates. No universal human-likeness score. "
                      "Source detection and diagnostic proxies are separate from preference.",
    }
