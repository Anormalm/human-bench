from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import Field

from .benchmark_run import RequestLedger, run_lock
from .dataset import write_jsonl
from .model_judge import (
    atomic_json,
    compare_orders,
    decode_decision,
    digest,
    judge_config,
    judge_pairs,
)
from .pairing import build_pairs
from .schemas import Response, Scenario, StrictModel


class JudgeControl(StrictModel):
    control_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    scenario: Scenario
    response_a: str = Field(min_length=1)
    response_b: str = Field(min_length=1)
    expected_preference: Literal["A", "B", "tie"]
    expected_actions_a: list[Literal["send", "revise", "reject"]] = Field(min_length=1)
    expected_actions_b: list[Literal["send", "revise", "reject"]] = Field(min_length=1)
    reason: str = Field(min_length=1)


def control_inputs(controls, seed):
    if not controls or len({c.control_id for c in controls}) != len(controls):
        raise ValueError("controls must be nonempty and have unique IDs")
    if len({c.scenario.scenario_id for c in controls}) != len(controls):
        raise ValueError("each control needs its own scenario ID")
    scenarios = [c.scenario for c in controls]
    responses = [
        Response(response_id=f"{c.control_id}:{side}", scenario_id=c.scenario.scenario_id,
                 system_id=f"control-{side.lower()}", text=getattr(c, f"response_{side.lower()}"),
                 provenance="controlled_perturbation",
                 metadata={"evidence_status": "constructed_judge_control", "control_id": c.control_id})
        for c in controls for side in ("A", "B")
    ]
    return scenarios, responses, build_pairs(responses, seed=seed)


def analyze_controls(controls, pairs, cache):
    controls_by_scenario = {c.scenario.scenario_id: c for c in controls}
    rows = []
    for pair in pairs:
        control = controls_by_scenario[pair.scenario_id]
        first_is_a = pair.response_a == f"{control.control_id}:A"
        expected = control.expected_preference
        checks = []
        observations = []
        for order in ("forward", "reverse"):
            record = cache["records"].get(f"{pair.pair_id}:{order}")
            d = decode_decision(record)
            checks.append(d)
            display_a_is_a = first_is_a if order == "forward" else not first_is_a
            pref = d.preference if d else None
            if not display_a_is_a:
                pref = {"A": "B", "B": "A"}.get(pref, pref)
            action_a = (d.action_a if display_a_is_a else d.action_b) if d else None
            action_b = (d.action_b if display_a_is_a else d.action_a) if d else None
            observations.append({
                "order": order, "displayed_first": "A" if display_a_is_a else "B",
                "preference": pref, "action_a": action_a, "action_b": action_b,
                "matches_expected_preference": pref == expected,
                "matches_expected_actions": action_a in control.expected_actions_a
                and action_b in control.expected_actions_b,
                "rationale": d.rationale if d else None,
            })
        consistency = compare_orders(*checks)
        pref_matches = all(o["matches_expected_preference"] for o in observations)
        actions_match = all(o["matches_expected_actions"] for o in observations)
        rows.append({
            "control_id": control.control_id, "category": control.category, "pair_id": pair.pair_id,
            "expected_preference": expected, "expected_actions_a": control.expected_actions_a,
            "expected_actions_b": control.expected_actions_b, "reason": control.reason,
            "scenario": control.scenario.model_dump(mode="json"),
            "response_a": control.response_a, "response_b": control.response_b,
            "preference_matches_both_orders": pref_matches, "actions_match_both_orders": actions_match,
            "accepted_under_full_rule": consistency["accepted"],
            "passed": bool(pref_matches and actions_match and consistency["accepted"]),
            "observations": observations,
        })
    return {
        "schema_version": "0.5", "report_kind": "judge_controls",
        "evidence_kind": "model_judged_constructed_controls", "n_human_judgments": 0,
        "n_controls": len(rows), "n_passed": sum(r["passed"] for r in rows),
        "n_preference_matches_both_orders": sum(r["preference_matches_both_orders"] for r in rows),
        "n_actions_match_both_orders": sum(r["actions_match_both_orders"] for r in rows),
        "controls": rows,
        "interpretation": "Fixed constructed checks of obvious violations and equivalent texts. "
                          "Expectations are author-declared, not human annotations. Two orders are dependent. "
                          "This is neither a model leaderboard nor an estimate of general judge accuracy.",
    }


def run_controls(controls, config, output, *, execute=False, max_requests=None, resume=False, seed=20260913):
    output = Path(output)
    provider, _ = judge_config(config)
    scenarios, responses, pairs = control_inputs(controls, seed)
    protocol = {"version": "0.5", "controls": [c.model_dump(mode="json") for c in controls],
                "config": config, "seed": seed}
    manifest = output / "control-run.json"
    if output.exists() and any(output.iterdir()):
        if not resume or not manifest.exists():
            raise ValueError("choose a new control output directory or use --resume")
        if json.loads(manifest.read_text(encoding="utf-8")) != protocol:
            raise ValueError("control inputs or judge configuration changed")
        if not (output / "requests.json").exists():
            raise ValueError("control request ledger is missing")
    plan = {"status": "preview", "n_controls": len(controls), "judge": provider.model,
            "judge_completions_before_resume": 2 * len(pairs), "max_requests": max_requests,
            "output": str(output), "evidence_kind": "model_judged_constructed_controls"}
    if not execute:
        return plan
    if not isinstance(max_requests, int) or isinstance(max_requests, bool) or max_requests < 1:
        raise ValueError("execute requires a positive --max-requests")
    if not resume and max_requests < 2 * len(pairs):
        raise ValueError("request cap is below the minimum control run size")
    if not os.environ.get(provider.api_key_env):
        raise ValueError("missing API key environment variable: " + provider.api_key_env)
    output.mkdir(parents=True, exist_ok=True)
    with run_lock(output):
        ledger = RequestLedger(output / "requests.json", max_requests)
        atomic_json(manifest, protocol)
        write_jsonl(output / "scenarios.jsonl", scenarios)
        write_jsonl(output / "responses.jsonl", responses)
        write_jsonl(output / "pairs.jsonl", pairs)
        _, summary = judge_pairs(scenarios, responses, pairs, config, output / "judge",
                                  resume=resume, before_request=ledger.reserve)
        cache = json.loads((output / "judge/observations.json").read_text(encoding="utf-8"))
        result = analyze_controls(controls, pairs, cache)
        result["automatic_judge"] = summary
        result["run"] = {"protocol_hash": digest(protocol), "raw_observations_hash": digest(cache),
                         "http_attempts_reserved": len(ledger.data["attempts"]), "max_requests": max_requests}
        atomic_json(output / "control-results.json", result)
    return {"status": "complete", "n_controls": len(controls), "n_passed": result["n_passed"],
            "report": str(output / "control-results.json"),
            "http_attempts_reserved": len(ledger.data["attempts"]), "max_requests": max_requests}
