import json

from api.index import app
from shuorenhua_bench.annotation_bundle import build_annotation_bundle
from shuorenhua_bench.leaderboard.aggregate import aggregate
from shuorenhua_bench.pairing import build_pairs
from shuorenhua_bench.schemas import PairwiseJudgment, Provenance, Response, Scenario
from shuorenhua_bench.splitting import grouped_split


def _scenario(identifier: str, cluster: str, genre: str = "workplace_message") -> Scenario:
    return Scenario(
        scenario_id=identifier,
        language="zh-CN",
        genre=genre,
        relationship="colleague",
        intent="respond",
        task_type="contextual_completion",
        channel="wechat_private",
        context="context",
        instruction="instruction",
        semantic_cluster_id=cluster,
    )


def _response(identifier: str, scenario: str, system: str) -> Response:
    return Response(
        response_id=identifier,
        scenario_id=scenario,
        system_id=system,
        text=identifier,
        provenance=Provenance.RAW_MODEL,
    )


def test_annotation_bundle_is_blind_and_joined():
    scenario = _scenario("s1", "c1")
    responses = [_response("a", "s1", "model-a"), _response("b", "s1", "model-b")]
    pair = build_pairs(responses)[0]
    bundle = build_annotation_bundle([scenario], responses, [pair])
    assert bundle["n_pairs"] == 1
    assert "system_id" not in bundle["items"][0]
    assert {bundle["items"][0]["response_a_text"], bundle["items"][0]["response_b_text"]} == {"a", "b"}


def test_grouped_split_prevents_cluster_leakage():
    scenarios = [
        _scenario("s1", "shared"),
        _scenario("s2", "shared"),
        _scenario("s3", "other"),
        _scenario("s4", "third"),
        _scenario("s5", "fourth"),
    ]
    splits = grouped_split(scenarios)
    containing = [name for name, values in splits.items() if "s1" in values or "s2" in values]
    assert len(containing) == 1
    assert {"s1", "s2"}.issubset(splits[containing[0]])


def test_aggregate_reports_uncertainty_and_disagreement():
    responses = [_response("a", "s1", "model-a"), _response("b", "s1", "model-b")]
    judgments = [
        PairwiseJudgment(
            pair_id="p1", scenario_id="s1", annotator_id=f"r{i}",
            response_a="a", response_b="b", preference=preference,
            action_a="send", action_b="revise", confidence=3,
        )
        for i, preference in enumerate(["A", "B", "tie"])
    ]
    report = aggregate(judgments, responses, bootstrap_samples=0)
    assert report["sample"]["n_annotators"] == 3
    assert report["agreement"]["mean_pair_disagreement_entropy"] > 0.99
    assert report["systems"]["model-a"]["direct_use_rate"] == 1.0


def test_wsgi_root_and_bundle():
    def request(path: str):
        result = {}
        body = b"".join(app({"PATH_INFO": path}, lambda status, headers: result.update(status=status, headers=headers)))
        return result["status"], body

    root_status, root = request("/")
    bundle_status, bundle = request("/api/bundle")
    assert root_status == "200 OK"
    assert "说人话 Bench" in root.decode("utf-8")
    assert bundle_status == "200 OK"
    assert json.loads(bundle)["n_pairs"] >= 1

