import json
from pathlib import Path

import pytest
from test_model_run import config, decision, stub_http

from shuorenhua_bench.judge_controls import JudgeControl, run_controls

CONTROLS = Path(__file__).resolve().parents[1] / "data/controls/judge_sensitivity_v05.json"


def fixtures():
    return [JudgeControl.model_validate(c) for c in json.loads(CONTROLS.read_text(encoding="utf-8-sig"))]


def test_control_preview_is_offline_and_does_not_create_directory(tmp_path, monkeypatch):
    calls = stub_http(monkeypatch, lambda *_: pytest.fail("unexpected API call"))
    result = run_controls(fixtures(), config()["judge"], tmp_path / "controls")
    assert result["n_controls"] == 6 and result["judge_completions_before_resume"] == 12
    assert not calls and not (tmp_path / "controls").exists()


def test_always_tie_judge_fails_violation_controls(tmp_path, monkeypatch):
    stub_http(monkeypatch, lambda *_: json.dumps(decision("tie")))
    result = run_controls(fixtures(), config()["judge"], tmp_path, execute=True, max_requests=12)
    report = json.loads((tmp_path / "control-results.json").read_text(encoding="utf-8"))
    assert result["n_passed"] == 2
    assert report["n_human_judgments"] == 0
    assert report["evidence_kind"] == "model_judged_constructed_controls"
    assert not (tmp_path / "report.json").exists()
    assert not (tmp_path / "model-judgments.jsonl").exists()


def test_controls_resolve_display_order_and_preserve_resume(tmp_path, monkeypatch):
    cases = fixtures()
    lookup = {c.scenario.context: c for c in cases[:4]}
    # The last two checks use the same scenario as wrong-time, so inspect both texts.
    def responder(payload, _):
        user = json.loads(payload["messages"][1]["content"])
        a, b = user["candidate_A"], user["candidate_B"]
        if a == b or all("现在十点二十" in text for text in (a, b)):
            return json.dumps(decision("tie"))
        c = lookup[user["scenario"]["context"]]
        valid_first = a == c.response_a
        return json.dumps(decision("A" if valid_first else "B",
                                   action_a="send" if valid_first else "revise",
                                   action_b="revise" if valid_first else "send"))
    calls = stub_http(monkeypatch, responder)
    result = run_controls(cases, config()["judge"], tmp_path, execute=True, max_requests=12)
    assert result["n_passed"] == 6 and len(calls) == 12
    for payload in calls:
        data = json.loads(payload["messages"][1]["content"])
        assert set(data) == {"scenario", "candidate_A", "candidate_B"}
        assert "expected_preference" not in payload["messages"][1]["content"]
    run_controls(cases, config()["judge"], tmp_path, execute=True, max_requests=12, resume=True)
    assert len(calls) == 12
    changed = [cases[0].model_copy(update={"expected_preference": "B"}), *cases[1:]]
    with pytest.raises(ValueError, match="inputs or judge configuration changed"):
        run_controls(changed, config()["judge"], tmp_path, resume=True)
    with pytest.raises(ValueError, match="original"):
        run_controls(cases, config()["judge"], tmp_path, execute=True, max_requests=13, resume=True)


def test_matching_preference_with_unstable_actions_does_not_pass(tmp_path, monkeypatch):
    c = fixtures()[0]
    count = 0
    def responder(payload, _):
        nonlocal count
        count += 1
        text = json.loads(payload["messages"][1]["content"])["candidate_A"]
        valid_first = text == c.response_a
        flawed_action = "revise" if count == 1 else "reject"
        return json.dumps(decision("A" if valid_first else "B",
                                   action_a="send" if valid_first else flawed_action,
                                   action_b=flawed_action if valid_first else "send"))
    stub_http(monkeypatch, responder)
    result = run_controls([c], config()["judge"], tmp_path, execute=True, max_requests=2)
    report = json.loads((tmp_path / "control-results.json").read_text(encoding="utf-8"))
    assert result["n_passed"] == 0
    assert report["n_preference_matches_both_orders"] == 1
    assert report["n_actions_match_both_orders"] == 1
