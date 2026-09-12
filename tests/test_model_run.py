import json
import urllib.error

import pytest

from shuorenhua_bench.benchmark_run import RequestLedger, run_benchmark, run_lock
from shuorenhua_bench.dataset import read_jsonl
from shuorenhua_bench.leaderboard.aggregate import aggregate
from shuorenhua_bench.model_judge import JudgeDecision, automatic_report, judge_pairs
from shuorenhua_bench.pairing import build_pairs
from shuorenhua_bench.providers import OpenAICompatibleProvider, ProviderConfig, openai_compatible
from shuorenhua_bench.schemas import PairwiseJudgment, Response, Scenario

KEY = "BENCH_TEST_KEY"


def inputs(count=2):
    scenarios = [Scenario(scenario_id=f"s{i}", language="zh-CN", genre="message", relationship="friend",
                          intent="update", task_type="contextual_completion", channel="private",
                          context=f"Work scheduled for Friday {i}", instruction="Reply faithfully",
                          metadata={"authoring_system": "SHOULD_NOT_REACH_JUDGE"}) for i in range(count)]
    responses = [Response(response_id=f"{s.scenario_id}:{system}", scenario_id=s.scenario_id,
                          system_id=system, text=f"PRIVATE TEXT {system}", provenance="raw_model")
                 for s in scenarios for system in ("a", "b")]
    return scenarios, responses, build_pairs(responses)


def config():
    return {"system_prompt": "Write only the message.", "systems": [
        {"system_id": s, "model": s, "base_url": "https://example.test/v1",
         "api_key_env": KEY, "retries": 2, "max_tokens": 128} for s in ("a", "b")],
        "judge": {"model": "judge", "base_url": "https://example.test/v1",
                  "api_key_env": KEY, "retries": 2, "max_tokens": 256}}


def decision(preference="A", **kwargs):
    return {"preference": preference, "action_a": "send", "action_b": "send", "confidence": 3,
            "rationale": "Concrete test evidence.", **kwargs}


def stub_http(monkeypatch, responder):
    calls = []
    monkeypatch.setenv(KEY, "test-value-not-a-real-key")
    monkeypatch.setattr(openai_compatible.time, "sleep", lambda _: None)

    def urlopen(request, **kwargs):
        payload = json.loads(request.data)
        calls.append(payload)
        result = responder(payload, len(calls))
        if isinstance(result, Exception):
            raise result

        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return json.dumps({"model": payload["model"] + "-resolved", "id": str(len(calls)),
                                   "choices": [{"message": {"content": result}, "finish_reason": "stop"}],
                                   "usage": {"prompt_tokens": 10, "completion_tokens": 20}}).encode()
        return Reply()
    monkeypatch.setattr(openai_compatible.urllib.request, "urlopen", urlopen)
    return calls


@pytest.mark.parametrize("forward,reverse,accepted,reason", [
    (decision("A"), decision("B"), 1, None),
    (decision("tie"), decision("tie"), 1, None),
    (decision("A"), decision("A"), 0, "order_sensitive_decision"),
    (decision("A"), decision("B", action_a="reject"), 0, "order_sensitive_decision"),
    (decision("abstain"), decision("B"), 0, "judge_abstained"),
    ({"not": "a decision"}, decision("B"), 0, "invalid_judge_output"),
])
def test_order_checks_are_one_vote_or_abstention(tmp_path, monkeypatch, forward, reverse, accepted, reason):
    scenarios, responses, pairs = inputs(1)
    calls = stub_http(monkeypatch, lambda p, n: json.dumps(forward if n == 1 else reverse))
    judgments, summary = judge_pairs(scenarios, responses, pairs, config()["judge"], tmp_path)
    assert len(judgments) == accepted
    assert summary["n_observations"] == 2
    assert summary["exclusions_by_reason"] == ({reason: 1} if reason else {})
    assert "SHOULD_NOT_REACH_JUDGE" not in json.dumps(calls)
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert set(payload) == {"scenario", "candidate_A", "candidate_B"}
    assert all(j.evidence_kind == "model" for j in judgments)
    # Invalid responses and abstentions also checkpoint; no repeated calls on resume.
    judge_pairs(scenarios, responses, pairs, config()["judge"], tmp_path, resume=True)
    assert len(calls) == 2


def test_judge_refuses_cache_edits_and_config_drift(tmp_path, monkeypatch):
    scenarios, responses, pairs = inputs(1)
    stub_http(monkeypatch, lambda p, n: json.dumps(decision("tie")))
    judge_pairs(scenarios, responses, pairs, config()["judge"], tmp_path)
    changed = dict(config()["judge"], model="other-model")
    with pytest.raises(ValueError, match="configuration changed"):
        judge_pairs(scenarios, responses, pairs, changed, tmp_path, resume=True)
    cache_path = tmp_path / "observations.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    next(iter(cache["records"].values()))["raw_output"] = "tampered"
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        judge_pairs(scenarios, responses, pairs, config()["judge"], tmp_path, resume=True)


def test_judge_requires_strict_types():
    with pytest.raises(ValueError):
        JudgeDecision.model_validate_json(json.dumps(decision(confidence="3")), strict=True)


def test_attempt_cap_includes_retries_and_survives_restart(tmp_path, monkeypatch):
    calls = stub_http(monkeypatch, lambda p, n: urllib.error.HTTPError(
        "https://example.test", 429, "retry", {}, None))
    ledger = RequestLedger(tmp_path / "requests.json", 2)
    provider = OpenAICompatibleProvider(ProviderConfig(
        system_id="judge", model="test", base_url="https://example.test", api_key_env=KEY, retries=3),
        ledger.reserve)
    with pytest.raises(RuntimeError, match="cap reached"):
        provider.generate(system_prompt="test", user_prompt="test")
    assert len(calls) == 2
    restarted = RequestLedger(tmp_path / "requests.json", 2)
    with pytest.raises(RuntimeError, match="cap reached"):
        restarted.reserve(provider.config, {})
    with pytest.raises(ValueError, match="original"):
        RequestLedger(tmp_path / "requests.json", 3)


def test_preview_is_offline_and_does_not_create_files(tmp_path, monkeypatch):
    monkeypatch.delenv(KEY, raising=False)
    plan = run_benchmark(inputs(3)[0], config(), tmp_path / "run")
    assert plan["new_generation_completions"] == 6
    assert plan["judge_completions_before_resume"] == 6
    assert plan["maximum_http_attempts_before_judge_resume"] == 24
    assert not (tmp_path / "run").exists()
    with pytest.raises(ValueError, match="missing API key"):
        run_benchmark(inputs(3)[0], config(), tmp_path / "run", execute=True, max_requests=24)
    assert not (tmp_path / "run").exists()


def test_full_pipeline_and_resume_without_duplicate_calls(tmp_path, monkeypatch):
    def responder(payload, n):
        if payload["model"] == "judge":
            prompt = json.loads(payload["messages"][1]["content"])
            preference = "A" if prompt["candidate_A"].endswith(" a") else "B"
            return json.dumps(decision(preference))
        return "Generated response " + payload["model"]
    calls = stub_http(monkeypatch, responder)
    scenarios = inputs(2)[0]
    result = run_benchmark(scenarios, config(), tmp_path / "run", execute=True, max_requests=16,
                           bootstrap_samples=5)
    assert result["status"] == "complete" and result["accepted_pairs"] == 2
    assert result["http_attempts_reserved"] == 8 and len(calls) == 8
    report = json.loads((tmp_path / "run/report.json").read_text(encoding="utf-8"))
    assert report["evidence_kind"] == "model_judged"
    assert report["sample"]["n_annotators"] == 0 and report["sample"]["n_model_judges"] == 1
    assert report["systems"]["a"]["ability"] > report["systems"]["b"]["ability"]
    judgments = read_jsonl(tmp_path / "run/model-judgments.jsonl", PairwiseJudgment)
    assert len(judgments) == 2
    assert (tmp_path / "run/human-study/public/rater-001.json").exists()
    run_benchmark(scenarios, config(), tmp_path / "run", execute=True, max_requests=16,
                  resume=True, bootstrap_samples=0)
    assert len(calls) == 8


def test_interrupted_generation_resumes_remaining_calls(tmp_path, monkeypatch):
    def responder(payload, n):
        if n == 2:
            return urllib.error.HTTPError("https://example.test", 401, "auth", {}, None)
        return json.dumps(decision("tie")) if payload["model"] == "judge" else "Generated"
    calls = stub_http(monkeypatch, responder)
    scenarios = inputs(1)[0]
    with pytest.raises(RuntimeError, match="HTTP 401"):
        run_benchmark(scenarios, config(), tmp_path / "run", execute=True, max_requests=8)
    assert len(read_jsonl(tmp_path / "run/responses.jsonl", Response)) == 1
    result = run_benchmark(scenarios, config(), tmp_path / "run", execute=True, max_requests=8,
                           resume=True, bootstrap_samples=0)
    assert len(calls) == result["http_attempts_reserved"] == 5
    assert result["accepted_pairs"] == 1


def test_resume_refuses_missing_attempt_ledger(tmp_path, monkeypatch):
    stub_http(monkeypatch, lambda p, n: json.dumps(decision("tie")) if p["model"] == "judge" else "text")
    scenarios = inputs(1)[0]
    run_benchmark(scenarios, config(), tmp_path / "run", execute=True, max_requests=8, bootstrap_samples=0)
    (tmp_path / "run/requests.json").unlink()
    with pytest.raises(ValueError, match="ledger is missing"):
        run_benchmark(scenarios, config(), tmp_path / "run", execute=True, max_requests=8, resume=True)


def test_withhold_empty_or_disconnected_rankings():
    scenarios, responses, pairs = inputs(1)
    report = automatic_report(scenarios, responses, pairs, [], {"requested_model": "judge"})
    assert report["ranking_status"] == "withheld"
    assert all(s["ability"] is None for s in report["systems"].values())
    responses += [Response(response_id="s0:c", scenario_id="s0", system_id="c",
                           text="third", provenance="raw_model")]
    pairs = build_pairs(responses)
    pair = next(p for p in pairs if "s0:c" not in (p.response_a, p.response_b))
    vote = PairwiseJudgment(**{k: getattr(pair, k) for k in (
        "pair_id", "scenario_id", "response_a", "response_b")},
        annotator_id="judge", preference="tie", action_a="send", action_b="send",
        confidence=3, evidence_kind="model")
    report = automatic_report(scenarios, responses, pairs, [vote], {"requested_model": "judge"})
    assert report["ranking_status"] == "withheld"
    assert report["systems"]["a"]["ties"] == 1
    with pytest.raises(ValueError, match="separately"):
        aggregate([vote, vote.model_copy(update={"annotator_id": "person", "evidence_kind": "human"})],
                  responses, bootstrap_samples=0)


def test_reasoning_payload_can_omit_sampling_parameters(monkeypatch):
    calls = stub_http(monkeypatch, lambda p, n: "complete")
    provider = OpenAICompatibleProvider(ProviderConfig(
        system_id="a", model="reasoner", base_url="https://example.test", api_key_env=KEY,
        temperature=None, top_p=None, token_parameter="max_completion_tokens", reasoning_effort="low"))
    provider.generate(system_prompt="test", user_prompt="test")
    assert "temperature" not in calls[0] and "top_p" not in calls[0] and "max_tokens" not in calls[0]
    assert calls[0]["max_completion_tokens"] == 512 and calls[0]["reasoning_effort"] == "low"


def test_run_lock_rejects_concurrent_writer(tmp_path):
    with run_lock(tmp_path), pytest.raises(ValueError, match="locked"), run_lock(tmp_path):
        pass
    assert not (tmp_path / ".run.lock").exists()
