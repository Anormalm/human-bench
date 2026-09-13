from __future__ import annotations

import itertools
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .dataset import read_jsonl
from .generation import stable_hash
from .leaderboard.aggregate import _ci, _clusters
from .model_judge import (
    automatic_report,
    compare_orders,
    decode_decision,
    digest,
    judge_config,
    summarize_order_checks,
)
from .pairing import build_pairs
from .response_runner import render_prompt
from .schemas import Pair, PairwiseJudgment, Response, Scenario
from .study import import_judgments, sha256_file, verify_study
from .validation import require_valid


def _dataset_signature(scenarios, responses, pairs):
    return digest({
        "scenarios": sorted((s.model_dump(mode="json") for s in scenarios), key=lambda s: s["scenario_id"]),
        "responses": sorted((r.model_dump(mode="json") for r in responses), key=lambda r: r["response_id"]),
        "pairs": sorted((p.pair_id, p.scenario_id, *sorted((p.response_a, p.response_b))) for p in pairs),
    })


def _label(preference, displayed_a, canonical_a):
    return {"A": "B", "B": "A"}.get(preference, preference) if displayed_a != canonical_a else preference


def load_judge_run(path):
    """Reconstruct checks from hashed raw observations, never trusting a report's derived votes."""
    path = Path(path)
    frozen = json.loads((path / "run.json").read_text(encoding="utf-8"))
    scenarios = read_jsonl(path / "scenarios.jsonl", Scenario)
    responses = read_jsonl(path / "responses.jsonl", Response)
    pairs = read_jsonl(path / "pairs.jsonl", Pair)
    require_valid(scenarios, responses, pairs)
    if frozen["scenarios"] != [s.model_dump(mode="json") for s in scenarios]:
        raise ValueError("run scenarios differ from the frozen selection")
    if frozen.get("imported_responses") is not None and frozen["imported_responses"] != [
            r.model_dump(mode="json") for r in responses]:
        raise ValueError("imported run responses differ from the frozen inputs")
    if pairs != build_pairs(responses, seed=frozen["seed"]):
        raise ValueError("run comparison registry differs from the frozen design")
    cache = json.loads((path / "judge/observations.json").read_text(encoding="utf-8"))
    protocol = cache["protocol"]
    if cache["fingerprint"] != digest(protocol):
        raise ValueError("judge protocol hash mismatch")
    expected_inputs = digest([x.model_dump(mode="json") for x in [*scenarios, *responses, *pairs]])
    if protocol["inputs_hash"] != expected_inputs:
        raise ValueError("judge cache does not match these response texts and scenarios")
    provider, _ = judge_config(frozen["config"]["judge"])
    if protocol["provider"] != asdict(provider):
        raise ValueError("judge configuration differs from the frozen run")
    records = cache["records"]
    expected_keys = {f"{p.pair_id}:{order}" for p in pairs for order in ("forward", "reverse")}
    if set(records) - expected_keys:
        raise ValueError("unexpected observation in judge cache")
    for key, record in records.items():
        if record.get("sha256") != digest({k: v for k, v in record.items() if k != "sha256"}):
            raise ValueError("judge observation hash mismatch")
        if key != f"{record['pair_id']}:{record['order']}":
            raise ValueError("judge observation identity mismatch")
    smap, rmap = {s.scenario_id: s for s in scenarios}, {r.response_id: r for r in responses}
    rows, judgments = [], []
    for pair in pairs:
        canonical_a = min(pair.response_a, pair.response_b)
        observed, displayed = [], []
        for order in ("forward", "reverse"):
            record = records.get(f"{pair.pair_id}:{order}")
            a, b = ((pair.response_a, pair.response_b) if order == "forward"
                    else (pair.response_b, pair.response_a))
            if record is not None:
                prompt = json.dumps({"scenario": json.loads(render_prompt(smap[pair.scenario_id])),
                                     "candidate_A": rmap[a].text, "candidate_B": rmap[b].text},
                                    ensure_ascii=False)
                if (record["response_a"], record["response_b"], record["input_hash"]) != (
                        a, b, stable_hash(protocol["rubric"] + "\0" + prompt)):
                    raise ValueError("judge observation display or prompt mismatch")
            decision = decode_decision(record)
            observed.append(decision)
            displayed.append({
                "order": order, "displayed_first": "A" if a == canonical_a else "B",
                "preference": _label(decision.preference, a, canonical_a) if decision else None,
                "action_a": (decision.action_a if a == canonical_a else decision.action_b) if decision else None,
                "action_b": (decision.action_b if a == canonical_a else decision.action_a) if decision else None,
                "confidence": decision.confidence if decision else None,
                "rationale": decision.rationale if decision else None,
                "raw_output": record["raw_output"] if record is not None and decision is None else None,
                "status": "missing" if record is None else "valid" if decision else "invalid",
            })
        check = compare_orders(*observed)
        if any(d["status"] == "missing" for d in displayed):
            check["status"] = "incomplete"
        if check["stable_preference"]:
            check["stable_preference"] = _label(check["stable_preference"], pair.response_a, canonical_a)
        if pair.response_a != canonical_a:
            check["action_a_agrees"], check["action_b_agrees"] = check["action_b_agrees"], check["action_a_agrees"]
        rows.append(dict(check, pair_id=pair.pair_id, scenario_id=pair.scenario_id, observations=displayed))
        if check["accepted"]:
            d = observed[0]
            judgments.append(PairwiseJudgment(
                pair_id=pair.pair_id, scenario_id=pair.scenario_id,
                annotator_id="model-judge:" + cache["fingerprint"][:16],
                response_a=pair.response_a, response_b=pair.response_b, preference=d.preference,
                action_a=d.action_a, action_b=d.action_b, confidence=check["confidence"],
                evidence_kind="model"))
    summary = {
        "rubric_version": protocol["rubric_version"], "protocol_hash": cache["fingerprint"],
        "rubric_hash": stable_hash(protocol["rubric"]), "observations_hash": digest(cache),
        "requested_model": provider.model, "provider": provider.base_url,
        "decoding": {"temperature": provider.temperature, "top_p": provider.top_p,
                     "reasoning_effort": provider.reasoning_effort, "max_tokens": provider.max_tokens,
                     "token_parameter": provider.token_parameter},
        "resolved_models": sorted({str(r["metadata"].get("resolved_model")) for r in records.values()}),
        "n_pairs": len(pairs), "n_scenarios_planned": len({p.scenario_id for p in pairs}),
        "n_scenarios_judged": len({p.scenario_id for p in pairs if any(
            f"{p.pair_id}:{order}" in records for order in ("forward", "reverse"))}),
        "n_accepted_pairs": len(judgments), "n_excluded_pairs": len(pairs) - len(judgments),
        "accepted_fraction": len(judgments) / len(pairs) if pairs else None,
        "n_observations": len(records), "n_missing_observations": len(expected_keys - set(records)),
        "order_diagnostics": summarize_order_checks(rows),
        "excluded_pairs": [{"pair_id": r["pair_id"], "reason": r["status"]} for r in rows if not r["accepted"]],
        "acceptance_rule": "Both display orders must agree on preference and both actions.",
    }
    return {"path": path, "scenarios": scenarios, "responses": responses, "pairs": pairs,
            "summary": summary, "rows": rows, "judgments": judgments,
            "signature": _dataset_signature(scenarios, responses, pairs)}


def reanalyze_run(path, *, bootstrap_samples=1000, seed=20260913):
    if bootstrap_samples < 0:
        raise ValueError("bootstrap sample count must be nonnegative")
    run = load_judge_run(path)
    result = automatic_report(run["scenarios"], run["responses"], run["pairs"], run["judgments"],
                              run["summary"], bootstrap_samples=bootstrap_samples, seed=seed)
    result["analysis"] = {"version": "0.5.0", "source_protocol_hash": run["summary"]["protocol_hash"],
                          "offline": True, "acceptance_rule_changed": False}
    return result


def _agreement(rows, clusters, *, bootstrap_samples, seed):
    labels = ("A", "B", "tie")
    matrix = {a: {b: 0 for b in labels} for a in labels}
    for row in rows:
        matrix[row["left"]][row["right"]] += 1
    n = len(rows)
    matching = sum(r["left"] == r["right"] for r in rows)
    observed = matching / n if n else None
    left_counts, right_counts = Counter(r["left"] for r in rows), Counter(r["right"] for r in rows)
    expected = sum(left_counts[l] * right_counts[l] for l in labels) / n**2 if n else None
    grouped = defaultdict(list)
    for row in rows:
        grouped[clusters[row["scenario_id"]]].append(int(row["left"] == row["right"]))
    keys = sorted(grouped)
    samples = []
    if len(keys) >= 2:
        rng = np.random.default_rng(seed)
        for _ in range(bootstrap_samples):
            sampled = [value for key in rng.choice(keys, len(keys), replace=True) for value in grouped[key]]
            samples.append(float(np.mean(sampled)))
    return {"n_comparable_pairs": n, "n_matching_pairs": matching, "agreement": observed,
            "cohen_kappa": (observed - expected) / (1 - expected) if expected is not None and expected < 1 else None,
            "confusion_matrix": matrix, "agreement_95ci_cluster_bootstrap": _ci(samples),
            "n_independent_groups": len(keys), "bootstrap_samples": len(samples),
            "scope": "Conditional on pairs with stable judge preference and an available reference. "
                     "Each pair contributes once; this is agreement, not ground-truth accuracy."}


def compare_judges(paths, *, study=None, exports=None, min_human_raters=3,
                   bootstrap_samples=1000, seed=20260913):
    if not paths or len({Path(p).resolve() for p in paths}) != len(paths):
        raise ValueError("provide distinct run directories")
    if bootstrap_samples < 0 or min_human_raters < 1:
        raise ValueError("invalid bootstrap sample count or human-rater minimum")
    if bool(study) != bool(exports):
        raise ValueError("human reference requires both --study and --exports")
    runs = [load_judge_run(p) for p in paths]
    if len({r["signature"] for r in runs}) != 1:
        raise ValueError("judge runs must use the same frozen scenario texts, responses and pair set")
    base = runs[0]
    clusters = _clusters(base["scenarios"], base["pairs"])
    rmap = {r.response_id: r for r in base["responses"]}
    smap = {s.scenario_id: s for s in base["scenarios"]}
    pair_map = {p.pair_id: p for p in base["pairs"]}
    references, reference_status, n_human_judgments = {}, "awaiting_human_judgments", 0
    human_provenance = None
    if study:
        manifest = verify_study(study)
        if manifest["evidence_status"] == "synthetic_demo":
            raise ValueError("human calibration cannot use a synthetic study")
        study = Path(study)
        signature = _dataset_signature(read_jsonl(study / "private/scenarios.jsonl", Scenario),
                                       read_jsonl(study / "private/responses.jsonl", Response),
                                       read_jsonl(study / "private/pairs.jsonl", Pair))
        if signature != base["signature"]:
            raise ValueError("human study must use the same frozen comparison inputs")
        votes, duplicates = import_judgments(study, exports)
        human_provenance = {"study_id": manifest["study_id"],
                            "study_manifest_sha256": sha256_file(study / "manifest.json"),
                            "exports": [{"name": Path(p).name, "sha256": sha256_file(p)} for p in exports],
                            "identical_duplicate_exports_ignored": duplicates}
        if any(j.evidence_kind != "human" for j in votes):
            raise ValueError("human reference accepts human evidence only")
        grouped = defaultdict(list)
        for j in votes:
            canonical_a = min(j.response_a, j.response_b)
            grouped[j.pair_id].append(_label(j.preference, j.response_a, canonical_a))
        for pair_id, choices in grouped.items():
            counts = Counter(choices)
            choice, count = counts.most_common(1)[0]
            sufficient = len(choices) >= min_human_raters
            majority = choice if sufficient and count > len(choices) / 2 else None
            references[pair_id] = {"n_raters": len(choices), "votes": dict(counts), "majority": majority,
                                   "status": "majority" if majority else "no_majority" if sufficient else "under_annotated"}
        n_human_judgments = len(votes)
        reference_status = "human_reference_available" if any(r["majority"] for r in references.values()) else "human_reference_incomplete"
    judges, pair_rows = {}, {}
    for pair in base["pairs"]:
        a, b = sorted((pair.response_a, pair.response_b))
        scenario = smap[pair.scenario_id]
        pair_rows[pair.pair_id] = {
            "pair_id": pair.pair_id, "scenario_id": pair.scenario_id,
            "context": scenario.context, "instruction": scenario.instruction,
            "required_facts": scenario.required_facts, "prohibited_changes": scenario.prohibited_changes,
            "candidate_a": {"system": rmap[a].system_id, "text": rmap[a].text},
            "candidate_b": {"system": rmap[b].system_id, "text": rmap[b].text},
            "judges": {}, "human_reference": references.get(pair.pair_id),
        }
    for i, run in enumerate(runs, 1):
        key = f"judge-{i}"
        comparable = []
        for row in run["rows"]:
            pair_rows[row["pair_id"]]["judges"][key] = row
            ref = references.get(row["pair_id"])
            if ref and ref["majority"] and row["stable_preference"]:
                comparable.append({"left": row["stable_preference"], "right": ref["majority"],
                                   "scenario_id": row["scenario_id"], "confidence": row["confidence"]})
        calibration = _agreement(comparable, clusters, bootstrap_samples=bootstrap_samples, seed=seed)
        calibration["n_reference_pairs"] = sum(r["majority"] is not None for r in references.values())
        calibration["n_unresolved_reference_pairs"] = len(base["pairs"]) - calibration["n_reference_pairs"]
        calibration["ordinal_confidence_groups"] = {
            str(confidence): {"n_pairs": len(rows), "agreement": sum(r["left"] == r["right"] for r in rows) / len(rows)}
            for confidence in range(1, 6) if (rows := [r for r in comparable if r["confidence"] == confidence])}
        judges[key] = dict(run["summary"], run_label=run["path"].name, human_comparison=calibration)
    cross_judge = []
    for left, right in itertools.combinations(judges, 2):
        compared = []
        for pair_id, row in pair_rows.items():
            a, b = row["judges"][left]["stable_preference"], row["judges"][right]["stable_preference"]
            if a and b:
                compared.append({"left": a, "right": b, "scenario_id": pair_map[pair_id].scenario_id})
        cross_judge.append(dict(_agreement(compared, clusters, bootstrap_samples=bootstrap_samples, seed=seed),
                                judge_a=left, judge_b=right, n_expected_pairs=len(base["pairs"])))
    warnings = [
        "Order consistency measures repeatability, not correctness.",
        "Agreement rates condition on comparable pairs; inspect missing, abstained and inconsistent cases.",
        "Human majority is a study-dependent reference; disagreement is not converted into a tie.",
        "Judge confidence is ordinal, not a calibrated probability.",
    ]
    if reference_status != "human_reference_available":
        warnings.append("Human calibration is pending; no human-alignment claim can be made.")
    if len(set(clusters.values())) < 30:
        warnings.append("Fewer than 30 independent scenario groups; results and intervals are exploratory.")
    if len({r["summary"]["rubric_hash"] for r in runs}) > 1:
        warnings.append("Rubrics differ across runs; differences cannot be attributed to judge models alone.")
    return {"schema_version": "0.5", "report_kind": "judge_audit", "evidence_status": reference_status,
            "dataset_hash": base["signature"], "n_pairs": len(base["pairs"]),
            "n_scenarios": len(base["scenarios"]), "n_independent_groups": len(set(clusters.values())),
            "n_human_judgments": n_human_judgments, "minimum_human_raters": min_human_raters,
            "human_provenance": human_provenance,
            "judges": judges, "cross_judge": cross_judge, "pairs": list(pair_rows.values()),
            "warnings": warnings, "analysis": {"version": "0.5.0", "seed": seed,
                                               "bootstrap_samples": bootstrap_samples, "offline": True}}
