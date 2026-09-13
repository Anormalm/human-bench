import json
from copy import deepcopy

import pytest
from test_model_run import config, decision, inputs, stub_http

from shuorenhua_bench.benchmark_run import run_benchmark
from shuorenhua_bench.dataset import read_jsonl, write_jsonl
from shuorenhua_bench.judge_audit import compare_judges, load_judge_run, reanalyze_run
from shuorenhua_bench.model_judge import JudgeDecision, compare_orders, digest
from shuorenhua_bench.schemas import PairwiseJudgment, Response


def make_runs(tmp_path, monkeypatch, count=3, changed_context=False):
    def responder(payload, n):
        if payload["model"].startswith("judge"):
            prompt = json.loads(payload["messages"][1]["content"])
            choice = ("A" if prompt["candidate_A"].endswith(" a") else "B") if payload["model"] == "judge-1" else "tie"
            return json.dumps(decision(choice))
        return "Generated response " + payload["model"]
    calls = stub_http(monkeypatch, responder)
    scenarios = inputs(count)[0]
    first_config = config()
    first_config["judge"]["model"] = "judge-1"
    first = tmp_path / "first"
    run_benchmark(scenarios, first_config, first, execute=True, max_requests=count * 8,
                  bootstrap_samples=0)
    second_config = deepcopy(first_config)
    second_config["judge"]["model"] = "judge-2"
    second = tmp_path / "second"
    if changed_context:
        scenarios = [scenarios[0].model_copy(update={"context": "A different situation"}), *scenarios[1:]]
    run_benchmark(scenarios, second_config, second, execute=True, max_requests=count * 4,
                  bootstrap_samples=0, existing_responses=read_jsonl(first / "responses.jsonl", Response))
    return first, second, calls


def human_exports(study, output, choices):
    mapping = json.loads((study / "private/response_map.json").read_text(encoding="utf-8"))
    files = []
    for i, chosen in enumerate(choices, 1):
        packet = json.loads((study / f"public/rater-{i:03}.json").read_text(encoding="utf-8"))
        rows = []
        for item in packet["items"]:
            if chosen == "tie":
                preference = "tie"
            else:
                preference = "A" if mapping[item["response_a"]].endswith(":" + chosen) else "B"
            rows.append(PairwiseJudgment(
                pair_id=item["pair_id"], scenario_id=item["scenario_id"],
                response_a=item["response_a"], response_b=item["response_b"],
                annotator_id=packet["assignment_id"], assignment_id=packet["assignment_id"],
                study_id=packet["study_id"], preference=preference,
                action_a="send", action_b="send", confidence=3, evidence_kind="human"))
        file = output / f"human-{i}.jsonl"
        write_jsonl(file, rows)
        files.append(file)
    return files


@pytest.mark.parametrize("a,b,status,pref_consistent,actions_consistent", [
    (decision("A"), decision("B", action_a="revise"), "actions_changed", True, False),
    (decision("A"), decision("A"), "preference_changed", False, True),
    (decision("A"), decision("A", action_a="revise"), "preference_and_actions_changed", False, False),
    (decision("tie"), decision("tie"), "accepted", True, True),
    (decision("abstain"), decision("abstain"), "abstained", None, None),
])
def test_preference_and_actions_are_independent_diagnostics(a, b, status, pref_consistent, actions_consistent):
    result = compare_orders(JudgeDecision(**a), JudgeDecision(**b))
    assert result["status"] == status
    assert result["preference_agrees"] is pref_consistent
    assert result["actions_agree"] is actions_consistent
    assert result["accepted"] == (status == "accepted")


def test_same_inputs_audit_is_offline_and_does_not_count_orders_as_raters(tmp_path, monkeypatch):
    first, second, calls = make_runs(tmp_path, monkeypatch)
    n_before = len(calls)
    report = compare_judges([first, second], bootstrap_samples=20)
    assert len(calls) == n_before
    assert report["evidence_status"] == "awaiting_human_judgments"
    assert report["n_human_judgments"] == 0
    comparison = report["cross_judge"][0]
    assert comparison["n_comparable_pairs"] == 3 and comparison["agreement"] == 0
    assert comparison["agreement_95ci_cluster_bootstrap"] is None
    for judge in report["judges"].values():
        assert judge["order_diagnostics"]["n_preference_consistent"] == 3
        assert judge["human_comparison"]["agreement"] is None
    original = json.loads((first / "report.json").read_text(encoding="utf-8"))
    offline = reanalyze_run(first, bootstrap_samples=0)
    assert len(calls) == n_before
    assert original["systems"] == offline["systems"]
    assert all(p["judges"]["judge-1"]["stable_preference"] == "A" for p in report["pairs"])


def test_human_alignment_resolves_blind_orientation_and_distinct_raters(tmp_path, monkeypatch):
    first, second, _ = make_runs(tmp_path, monkeypatch)
    study = first / "human-study"
    exports = human_exports(study, tmp_path, ["a", "a", "b"])
    report = compare_judges([first, second], study=study, exports=[*exports, exports[0]],
                            bootstrap_samples=10)
    assert report["n_human_judgments"] == 9
    assert report["evidence_status"] == "human_reference_available"
    a, b = (report["judges"][j]["human_comparison"] for j in ("judge-1", "judge-2"))
    assert a["n_reference_pairs"] == a["n_comparable_pairs"] == 3
    assert a["agreement"] == 1 and b["agreement"] == 0
    assert a["agreement_95ci_cluster_bootstrap"] is None
    assert all(p["human_reference"]["majority"] == "A" for p in report["pairs"])


@pytest.mark.parametrize("votes,status", [
    (["a", "b", "tie"], "no_majority"), (["a", "a"], "under_annotated"),
])
def test_human_disagreement_is_not_a_tie_or_majority(tmp_path, monkeypatch, votes, status):
    first, second, _ = make_runs(tmp_path, monkeypatch, count=1)
    study = first / "human-study"
    exports = human_exports(study, tmp_path, votes)
    report = compare_judges([first, second], study=study, exports=exports, bootstrap_samples=0)
    assert report["evidence_status"] == "human_reference_incomplete"
    assert report["pairs"][0]["human_reference"]["status"] == status
    assert report["pairs"][0]["human_reference"]["majority"] is None
    assert report["judges"]["judge-1"]["human_comparison"]["n_comparable_pairs"] == 0


def test_audit_rejects_cross_dataset_and_duplicate_runs(tmp_path, monkeypatch):
    first, second, _ = make_runs(tmp_path, monkeypatch, count=1, changed_context=True)
    with pytest.raises(ValueError, match="same frozen"):
        compare_judges([first, second])
    with pytest.raises(ValueError, match="distinct"):
        compare_judges([first, first])


def test_audit_verifies_text_hashes_and_display_not_only_summary(tmp_path, monkeypatch):
    first, _, _ = make_runs(tmp_path, monkeypatch, count=1)
    path = first / "judge/observations.json"
    cache = json.loads(path.read_text(encoding="utf-8"))
    record = next(iter(cache["records"].values()))
    record["response_a"], record["response_b"] = record["response_b"], record["response_a"]
    record["sha256"] = digest({k: v for k, v in record.items() if k != "sha256"})
    path.write_text(json.dumps(cache), encoding="utf-8")
    with pytest.raises(ValueError, match="display or prompt"):
        load_judge_run(first)


def test_incomplete_observation_is_reported_as_missing(tmp_path, monkeypatch):
    first, _, _ = make_runs(tmp_path, monkeypatch, count=1)
    path = first / "judge/observations.json"
    cache = json.loads(path.read_text(encoding="utf-8"))
    cache["records"].pop(next(iter(cache["records"])))
    path.write_text(json.dumps(cache), encoding="utf-8")
    run = load_judge_run(first)
    assert run["summary"]["n_missing_observations"] == 1
    assert run["rows"][0]["status"] == "incomplete" and not run["judgments"]
    assert run["summary"]["n_scenarios_judged"] == 1
    cache["records"].clear()
    path.write_text(json.dumps(cache), encoding="utf-8")
    summary = load_judge_run(first)["summary"]
    assert summary["n_scenarios_judged"] == 0 and summary["n_scenarios_planned"] == 1


def test_all_ties_do_not_produce_false_precision_or_a_winner(tmp_path, monkeypatch):
    _, second, _ = make_runs(tmp_path, monkeypatch)
    report = reanalyze_run(second, bootstrap_samples=20)
    assert report["ranking_status"] == "no_separation"
    assert report["uncertainty"]["withheld_degenerate_intervals"]
    for system in report["systems"].values():
        assert system["ties"] == 3
        assert system["ability_95ci_cluster_bootstrap"] is None
        assert system["rank_95ci_cluster_bootstrap"] is None
        assert system["direct_use_95ci_cluster_bootstrap"] is None
    assert report["contrasts"][0]["difference_familywise_95ci_bonferroni_percentile"] is None
