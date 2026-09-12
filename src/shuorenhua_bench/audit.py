from __future__ import annotations

import itertools
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict
from difflib import SequenceMatcher

from scipy.stats import norm

from .validation import validate_dataset


def audit_dataset(scenarios, responses, *, pairs=None, judgments=None, splits=None):
    issues = [asdict(i) for i in validate_dataset(scenarios, responses, pairs, judgments)]
    coverage = {field: dict(Counter(getattr(s, field) for s in scenarios))
                for field in ("language", "genre", "relationship", "intent", "task_type")}
    texts = {}
    exact_duplicates = []
    for s in scenarios:
        text = unicodedata.normalize("NFKC", s.context + s.instruction)
        text = re.sub(r"\s+", "", text).casefold()
        if text in texts:
            exact_duplicates.append([texts[text], s.scenario_id])
        texts[text] = s.scenario_id
    near_duplicates = []
    # Candidate generation over shared character trigrams avoids an unrestricted O(N^2) scan.
    index = defaultdict(set)
    normalized = list(texts)
    for i, text in enumerate(normalized):
        candidates = Counter()
        grams = {text[k:k + 3] for k in range(max(0, len(text) - 2))}
        for gram in grams:
            candidates.update(index[gram])
        for j, overlap in candidates.items():
            other = normalized[j]
            if overlap / max(1, len(grams)) >= 0.5:
                score = SequenceMatcher(None, text, other, autojunk=False).ratio()
                if score >= 0.85:
                    near_duplicates.append({"a": texts[text], "b": texts[other], "similarity": score})
        for gram in grams:
            index[gram].add(i)
    missing_cells = []
    names = sorted({r.system_id for r in responses})
    cells = Counter((r.scenario_id, r.system_id) for r in responses)
    for s, name in itertools.product(scenarios, names):
        if not cells[(s.scenario_id, name)]:
            missing_cells.append({"scenario_id": s.scenario_id, "system_id": name})
    split_issues = []
    if splits is not None:
        splits = splits.get("splits", splits)
        if not isinstance(splits, dict) or any(not isinstance(ids, list) for ids in splits.values()):
            raise ValueError("splits must map split names to scenario ID lists")
        known = {s.scenario_id for s in scenarios}
        seen = {}
        for split, ids in splits.items():
            for identifier in ids:
                if identifier in seen:
                    split_issues.append(f"{identifier} appears more than once")
                if identifier not in known:
                    split_issues.append(f"unknown scenario {identifier}")
                seen[identifier] = split
        if set(seen) != known:
            split_issues.append("split assignment does not cover exactly all scenarios")
        for field in ("semantic_cluster_id", "source_template_id"):
            owners = defaultdict(set)
            for s in scenarios:
                if getattr(s, field) and s.scenario_id in seen:
                    owners[getattr(s, field)].add(seen[s.scenario_id])
            for group, memberships in owners.items():
                if len(memberships) > 1:
                    split_issues.append(f"{field} {group} crosses splits")
        for a, b in exact_duplicates:
            if seen.get(a) != seen.get(b):
                split_issues.append(f"identical scenario text crosses splits: {a}, {b}")
    human = [r for r in responses if r.provenance.value == "human"]
    eligible_human = [r for r in human if r.author_id and r.metadata.get("consent")
                      and r.metadata.get("source") and r.metadata.get("license")]
    return {
        "schema_version": "0.3", "valid": not issues and not split_issues and not exact_duplicates,
        "n_scenarios": len(scenarios), "n_responses": len(responses), "systems": names,
        "coverage": coverage, "issues": issues, "split_issues": split_issues,
        "exact_duplicate_scenarios": exact_duplicates,
        "near_duplicate_review_candidates": near_duplicates,
        "missing_system_scenario_cells": missing_cells,
        "scenario_sources": dict(Counter(s.metadata.get("scenario_source", "undocumented") for s in scenarios)),
        "human_reference_count": len(human),
        "human_references_with_documented_consent_source_license": len(eligible_human),
        "model_responses_missing_manifest": [r.response_id for r in responses
                                             if r.provenance.value in {"raw_model", "humanizer"} and not r.manifest],
        "interpretation": "An integrity/coverage audit is not construct validation or evidence of SOTA.",
    }


def plan_sample_size(effect=0.1, power=0.8, alpha=0.05, raters_per_pair=3, icc=0.25,
                     systems=4, scenarios=200):
    if not 0 < effect < 0.5 or not 0 < power < 1 or not 0 < alpha < 1:
        raise ValueError("effect must be in (0,.5), power and alpha in (0,1)")
    if not 0 <= icc <= 1 or raters_per_pair < 1 or systems < 2 or scenarios < 1:
        raise ValueError("invalid study sizes or ICC")
    comparisons = systems * (systems - 1) // 2
    corrected_alpha = alpha / comparisons
    p = 0.5 + effect
    z_alpha, z_power = norm.ppf(1 - corrected_alpha / 2), norm.ppf(power)
    independent = math.ceil(((z_alpha * 0.5 + z_power * math.sqrt(p * (1 - p))) / effect) ** 2)
    design_effect = 1 + (raters_per_pair - 1) * icc
    clusters = math.ceil(independent * design_effect / raters_per_pair)
    return {
        "assumptions": "Two-sided normal approximation to binary preference vs .5; "
                       "equal independent scenario groups, common within-group ICC; no ties. "
                       "Planning sensitivity only, not power for the Davidson model.",
        "effect_above_chance": effect, "power": power, "familywise_alpha": alpha,
        "n_system_contrasts": comparisons, "assumed_icc": icc,
        "independent_votes_per_contrast_approx": independent,
        "scenario_groups_per_contrast_approx": clusters,
        "requested_scenarios": scenarios,
        "planned_pairs": scenarios * comparisons,
        "planned_judgments": scenarios * comparisons * raters_per_pair,
        "requested_design_meets_approximation": scenarios >= clusters,
    }
