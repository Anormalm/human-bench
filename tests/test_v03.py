import json

import numpy as np
import pytest

from scripts.generate_responses import run
from shuorenhua_bench.annotation_bundle import build_annotation_bundle
from shuorenhua_bench.audit import audit_dataset, plan_sample_size
from shuorenhua_bench.dataset import write_jsonl
from shuorenhua_bench.leaderboard.aggregate import aggregate
from shuorenhua_bench.pairing import build_pairs
from shuorenhua_bench.schemas import PairwiseJudgment, Response, Scenario
from shuorenhua_bench.statistics.davidson_bt import fit_davidson, outcome_probabilities
from shuorenhua_bench.study import import_judgments, prepare_study, verify_study
from shuorenhua_bench.validation import validate_dataset


def scenario(i="s", **kwargs):
    return Scenario(scenario_id=i, language="zh-CN", genre="message", relationship="friend",
                    intent="respond", task_type="contextual_completion", channel="private",
                    context="Context " + i, instruction="Reply " + i, **kwargs)


def response(i, system, s="s", **kwargs):
    return Response(response_id=i, system_id=system, scenario_id=s, text="Text " + i,
                    provenance="raw_model", **kwargs)


def vote(a="a", b="b", annotator="r1", s="s", pair="p", preference="A", **kwargs):
    return PairwiseJudgment(pair_id=pair, scenario_id=s, annotator_id=annotator,
                            response_a=a, response_b=b, preference=preference,
                            action_a="send", action_b="revise", confidence=3, **kwargs)


@pytest.mark.parametrize("mutate,expected", [
    (lambda j: [j, j], "duplicate_judgment"),
    (lambda j: [j.model_copy(update={"scenario_id": "elsewhere"})], "cross_scenario_pair"),
    (lambda j: [j.model_copy(update={"response_b": "missing"})], "orphan_comparison_response"),
    (lambda j: [j.model_copy(update={"response_b": "a"})], "same_system_pair"),
    (lambda j: [j.model_copy(update={"annotator_id": ""})], "missing_annotator"),
])
def test_invalid_votes_rejected_before_fit(mutate, expected):
    with pytest.raises(ValueError, match=expected):
        aggregate(mutate(vote()), [response("a", "A"), response("b", "B")], bootstrap_samples=0)


def test_same_pair_cannot_change_responses():
    rows = [vote(), vote(b="c", annotator="r2")]
    with pytest.raises(ValueError, match="inconsistent_pair"):
        aggregate(rows, [response("a", "A"), response("b", "B"), response("c", "C")], bootstrap_samples=0)


def test_cannot_pool_tracks_or_rewrite_sources():
    responses = [response("source", "source"),
                 response("a", "A", track="humanization", source_response_id="source"),
                 response("b", "B", track="humanization", source_response_id="source"),
                 response("c", "C")]
    pairs = build_pairs(responses)
    assert any({p.response_a, p.response_b} == {"a", "b"} for p in pairs)
    assert not any(({p.response_a, p.response_b} & {"a", "b"}) and
                   ({p.response_a, p.response_b} & {"source", "c"}) for p in pairs)


def test_duplicate_response_ids_fail():
    with pytest.raises(ValueError, match="unique"):
        build_pairs([response("a", "A"), response("a", "B")])


def test_public_bundle_contains_no_model_identity():
    responses = [response("s:secret-model-a", "secret-model-a"),
                 response("s:secret-model-b", "secret-model-b")]
    mapping = {}
    bundle = build_annotation_bundle([scenario()], responses, build_pairs(responses), id_map=mapping)
    # Text may itself contain self-identification; identity fields must be opaque.
    for item in bundle["items"]:
        item.pop("response_a_text")
        item.pop("response_b_text")
    assert "secret-model" not in json.dumps(bundle)
    assert set(mapping.values()) == {r.response_id for r in responses}


def test_prepare_balances_distinct_raters_and_rejects_tampering(tmp_path):
    scenarios = [scenario(str(i)) for i in range(8)]
    responses = [response(f"{s.scenario_id}:{m}", m, s.scenario_id) for s in scenarios for m in ("A", "B", "C")]
    manifest = prepare_study(scenarios, responses, tmp_path, raters=6)
    assignments = {}
    for assignment, relative in manifest["assignments"].items():
        packet = json.loads((tmp_path / relative).read_text())
        for item in packet["items"]:
            assignments.setdefault(item["pair_id"], []).append((assignment, item["response_a"]))
    assert all(len({r for r, _ in rows}) == 3 for rows in assignments.values())
    assert all(len({a for _, a in rows}) == 2 for rows in assignments.values())
    assert max(manifest["assignment_loads"]) - min(manifest["assignment_loads"]) <= 2
    verify_study(tmp_path)
    with pytest.raises(ValueError, match="empty"):
        prepare_study(scenarios, responses, tmp_path)
    (tmp_path / "private/responses.jsonl").write_text("tampered")
    with pytest.raises(ValueError, match="integrity"):
        verify_study(tmp_path)


def test_import_roundtrip_and_identical_export_deduplication(tmp_path):
    study = tmp_path / "study"
    prepare_study([scenario()], [response("a", "A"), response("b", "B")], study, raters=3)
    packet = json.loads((study / "public/rater-001.json").read_text())
    item = packet["items"][0]
    j = vote(item["response_a"], item["response_b"], "rater-001", pair=item["pair_id"],
             study_id=packet["study_id"], assignment_id="rater-001")
    export = tmp_path / "export.jsonl"
    write_jsonl(export, [j])
    rows, duplicates = import_judgments(study, [export, export])
    assert duplicates == 1 and {rows[0].response_a, rows[0].response_b} == {"a", "b"}
    write_jsonl(export, [j.model_copy(update={"study_id": "foreign"})])
    with pytest.raises(ValueError, match="different study"):
        import_judgments(study, [export])


def test_import_rejects_wrong_orientation_and_conflicting_votes(tmp_path):
    study = tmp_path / "study"
    prepare_study([scenario()], [response("a", "A"), response("b", "B")], study, raters=3)
    packet = json.loads((study / "public/rater-001.json").read_text())
    item = packet["items"][0]
    j = vote(item["response_a"], item["response_b"], "rater-001", pair=item["pair_id"],
             study_id=packet["study_id"], assignment_id="rater-001")
    export = tmp_path / "one.jsonl"
    write_jsonl(export, [j.model_copy(update={"response_a": j.response_b, "response_b": j.response_a})])
    with pytest.raises(ValueError, match="assigned display"):
        import_judgments(study, [export])
    write_jsonl(export, [j, j.model_copy(update={"preference": "B"})])
    with pytest.raises(ValueError, match="conflicting"):
        import_judgments(study, [export])


def test_agreement_normalizes_display_order():
    rows = [vote(), vote("b", "a", "r2", preference="B")]
    report = aggregate(rows, [response("a", "A"), response("b", "B")], bootstrap_samples=0)
    assert report["agreement"]["mean_pairwise_agreement"] == 1
    assert report["agreement"]["mean_pair_disagreement_entropy"] == 0
    assert report["systems"]["A"]["wins"] == 2


def test_repeated_response_actions_do_not_inflate_sample_size():
    rows = [vote(), vote(b="c", pair="p2")]
    report = aggregate(rows, [response("a", "A"), response("b", "B"), response("c", "C")], bootstrap_samples=0)
    assert report["systems"]["A"]["n_unique_response_rater_actions"] == 1
    assert report["systems"]["A"]["direct_use_rate"] == 1


def test_disconnected_graph_refuses_global_ranking():
    with pytest.raises(ValueError, match="disconnected"):
        fit_davidson([("A", "B", "A"), ("C", "D", "B")])


@pytest.mark.parametrize("outcome", ["A", "B", "tie"])
def test_extreme_data_remain_finite_and_converge(outcome):
    fit = fit_davidson([("A", "B", outcome)] * 100)
    assert fit.converged
    probabilities = outcome_probabilities(fit, "A", "B")
    assert sum(probabilities.values()) == pytest.approx(1)
    assert all(np.isfinite(v) for v in fit.abilities.values())


def test_position_adjustment_recovers_known_strength_and_bias():
    rng = np.random.default_rng(44)
    comparisons = []
    theta, beta, nu = .8, .6, .5
    for _ in range(8000):
        a, b = ("strong", "weak") if rng.random() < .5 else ("weak", "strong")
        strength_a = theta / 2 if a == "strong" else -theta / 2
        logits = np.array([strength_a + beta / 2, -strength_a - beta / 2, np.log(nu)])
        probs = np.exp(logits) / np.exp(logits).sum()
        comparisons.append((a, b, str(rng.choice(["A", "B", "tie"], p=probs))))
    result = fit_davidson(comparisons, fit_position=True)
    assert result.converged
    assert result.abilities["strong"] - result.abilities["weak"] == pytest.approx(theta, abs=.1)
    assert result.position_bias == pytest.approx(beta, abs=.1)
    assert result.tie_parameter == pytest.approx(nu, abs=.07)
    flipped = [(b, a, {"A": "B", "B": "A", "tie": "tie"}[y]) for a, b, y in comparisons]
    other = fit_davidson(flipped, fit_position=True)
    assert other.abilities == pytest.approx(result.abilities, abs=1e-5)
    assert other.position_bias == pytest.approx(-result.position_bias, abs=1e-5)


def test_cluster_bootstrap_preserves_transitive_template_families():
    scenarios = [scenario("s1", semantic_cluster_id="g"),
                 scenario("s2", semantic_cluster_id="g", source_template_id="t"),
                 scenario("s3", source_template_id="t")]
    responses = [response(s.scenario_id + m, m, s.scenario_id) for s in scenarios for m in ("A", "B")]
    rows = [vote(s.scenario_id + "A", s.scenario_id + "B", s=s.scenario_id, pair=s.scenario_id)
            for s in scenarios]
    report = aggregate(rows, responses, scenarios=scenarios, bootstrap_samples=100)
    assert report["uncertainty"]["n_independent_groups"] == 1
    assert report["systems"]["A"]["ability_95ci_cluster_bootstrap"] is None


def test_bootstrap_accounts_for_disconnected_resamples():
    responses = [response("a1", "A", "s1"), response("b1", "B", "s1"),
                 response("b2", "B", "s2"), response("c2", "C", "s2")]
    rows = [vote("a1", "b1", s="s1", pair="p1"), vote("b2", "c2", s="s2", pair="p2")]
    result = aggregate(rows, responses, bootstrap_samples=40)
    assert result["uncertainty"]["skipped_model_samples"] > 0
    assert not any(c["separated_exploratory"] for c in result["contrasts"])
    json.dumps(result, allow_nan=False)


def test_audit_detects_template_leakage_and_missing_outputs():
    scenarios = [scenario("s1", source_template_id="t"), scenario("s2", source_template_id="t")]
    result = audit_dataset(scenarios, [response("a", "A", "s1")],
                           splits={"train": ["s1"], "test": ["s2"]})
    assert not result["valid"]
    assert result["missing_system_scenario_cells"] == [{"scenario_id": "s2", "system_id": "A"}]


def test_power_plan_scales_with_effect_and_correlation():
    base = plan_sample_size(effect=.1, icc=0)
    narrow = plan_sample_size(effect=.05, icc=0)
    correlated = plan_sample_size(effect=.1, icc=.5)
    assert narrow["scenario_groups_per_contrast_approx"] > base["scenario_groups_per_contrast_approx"] * 3
    assert correlated["scenario_groups_per_contrast_approx"] > base["scenario_groups_per_contrast_approx"]
    assert base["planned_judgments"] == 3600


def config():
    return {"system_prompt": "Reply only", "systems": [
        {"system_id": "A", "model": "test-model", "base_url": "https://example.com/v1",
         "api_key_env": "TEST_BENCH_API_KEY"}]}


def test_generation_preflight_makes_no_api_calls(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_BENCH_API_KEY", raising=False)
    result = run([scenario()], config(), tmp_path / "responses.jsonl", dry_run=True)
    assert result["planned_completions"] == 1
    assert not (tmp_path / "responses.jsonl").exists()
    with pytest.raises(ValueError, match="exceeds"):
        run([scenario()], config(), tmp_path / "responses.jsonl", max_calls=0)


def test_resume_rejects_input_or_model_changes(tmp_path, monkeypatch):
    from shuorenhua_bench.providers import OpenAICompatibleProvider
    monkeypatch.setenv("TEST_BENCH_API_KEY", "test-only")
    monkeypatch.setattr(OpenAICompatibleProvider, "generate", lambda *a, **k: ("test response", {"resolved_model": "snapshot"}))
    output = tmp_path / "responses.jsonl"
    run([scenario()], config(), output)
    result = run([scenario()], config(), output, resume=True)
    assert result["planned_completions"] == 0
    changed = config()
    changed["systems"][0]["model"] = "different-model"
    with pytest.raises(ValueError, match="resume configuration"):
        run([scenario()], changed, output, resume=True)


def test_spans_checked_in_unicode_codepoints():
    from shuorenhua_bench.schemas import ProblemSpan
    responses = [response("a", "A").model_copy(update={"text": "好🙂啊"}), response("b", "B")]
    j = vote(spans=[ProblemSpan(response_id="a", start=1, end=4, type="factual_change", severity=2)])
    assert any(i.code == "span_out_of_bounds" for i in validate_dataset([scenario()], responses, judgments=[j]))


def test_private_files_never_served():
    from api.index import app
    for path in ["/private/response_map.json", "/../pyproject.toml", "/studies/demo-v03/manifest.json"]:
        status = []
        b"".join(app({"PATH_INFO": path}, lambda s, h, status=status: status.append(s)))
        assert status == ["404 Not Found"]


def test_synthetic_votes_stay_labeled():
    report = aggregate([vote(evidence_kind="synthetic")],
                       [response("a", "A"), response("b", "B")], bootstrap_samples=0)
    assert report["evidence_kind"] == "synthetic_or_mixed"
    assert any("SYNTHETIC" in warning for warning in report["warnings"])


def test_audit_accepts_split_builder_format():
    result = audit_dataset([scenario()], [], splits={"seed": 7, "splits": {"test": ["s"]}})
    assert result["valid"]


def test_rewrite_generation_can_prepare_and_evaluate_own_track(tmp_path, monkeypatch):
    from shuorenhua_bench.providers import OpenAICompatibleProvider
    monkeypatch.setenv("TEST_BENCH_API_KEY", "test-only")
    monkeypatch.setattr(OpenAICompatibleProvider, "generate", lambda *a, **k: ("rewritten", {}))
    cfg = config()
    cfg["systems"].append({**cfg["systems"][0], "system_id": "B"})
    source = response("source", "source-system")
    output = tmp_path / "responses.jsonl"
    run([scenario()], cfg, output, sources=[source])
    from shuorenhua_bench.dataset import read_jsonl
    responses = read_jsonl(output, Response)
    study = tmp_path / "study"
    manifest = prepare_study([scenario()], responses, study, raters=3)
    assert manifest["track"] == "humanization" and manifest["n_pairs"] == 1
    report = aggregate([vote("s:A", "s:B")], responses, bootstrap_samples=0)
    assert report["track"] == "humanization"
    assert "source-system" not in report["systems"]


@pytest.mark.parametrize("status,retry_count", [(401, 1), (429, 3), (500, 3)])
def test_provider_only_retries_retryable_http_errors(monkeypatch, status, retry_count):
    import urllib.error

    from shuorenhua_bench.providers import (
        OpenAICompatibleProvider,
        ProviderConfig,
        openai_compatible,
    )
    calls = []
    def fake_urlopen(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError("https://example.com", status, "test", {}, None)
    monkeypatch.setenv("TEST_BENCH_API_KEY", "test-only")
    monkeypatch.setattr(openai_compatible.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(openai_compatible.time, "sleep", lambda _: None)
    provider = OpenAICompatibleProvider(ProviderConfig(
        system_id="A", model="model", base_url="https://example.com", api_key_env="TEST_BENCH_API_KEY"))
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        provider.generate(system_prompt="s", user_prompt="u")
    assert len(calls) == retry_count


def test_provider_rejects_truncated_completion(monkeypatch):
    from shuorenhua_bench.providers import (
        OpenAICompatibleProvider,
        ProviderConfig,
        openai_compatible,
    )
    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "incomplete"}, "finish_reason": "length"}]}).encode()
    monkeypatch.setenv("TEST_BENCH_API_KEY", "test-only")
    monkeypatch.setattr(openai_compatible.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    provider = OpenAICompatibleProvider(ProviderConfig(
        system_id="A", model="model", base_url="https://example.com", api_key_env="TEST_BENCH_API_KEY"))
    with pytest.raises(RuntimeError, match="did not finish"):
        provider.generate(system_prompt="s", user_prompt="u")

def test_study_preserves_missing_generation_coverage(tmp_path):
    manifest = prepare_study([scenario("s"), scenario("missing")],
                             [response("a", "A"), response("b", "B")], tmp_path, raters=3)
    missing = manifest["input_coverage"]["missing_system_scenario_cells"]
    assert len(missing) == 2 and all(x["scenario_id"] == "missing" for x in missing)


@pytest.mark.parametrize("url", ["http://localhost.evil.example/v1", "http://127.0.0.1.evil.example/v1"])
def test_provider_does_not_treat_hostname_prefix_as_local(url):
    from shuorenhua_bench.providers import ProviderConfig
    with pytest.raises(ValueError, match="HTTPS"):
        ProviderConfig(system_id="A", model="m", base_url=url, api_key_env="key")
