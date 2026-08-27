from shuorenhua_bench.diagnostics.semantic_preservation import check_preservation
from shuorenhua_bench.pairing import build_pairs
from shuorenhua_bench.schemas import Provenance, Response
from shuorenhua_bench.statistics.davidson_bt import fit_davidson, outcome_probabilities


def response(identifier: str, system: str) -> Response:
    return Response(
        response_id=identifier,
        scenario_id="s1",
        system_id=system,
        text=f"text {identifier}",
        provenance=Provenance.RAW_MODEL,
    )


def test_pair_builder_is_complete_and_deterministic():
    responses = [response("r1", "a"), response("r2", "b"), response("r3", "c")]
    first = build_pairs(responses, seed=7)
    second = build_pairs(responses, seed=7)
    assert first == second
    assert len(first) == 3
    assert len({item.pair_id for item in first}) == 3


def test_davidson_ranks_repeated_winner():
    result = fit_davidson([("good", "bad", "A")] * 8 + [("good", "bad", "tie")])
    probabilities = outcome_probabilities(result, "good", "bad")
    assert result.abilities["good"] > result.abilities["bad"]
    assert probabilities["A"] > probabilities["B"]


def test_semantic_preservation_flags_numbers():
    result = check_preservation("周五交付 20 个", "周五交付 30 个", ["周五"])
    assert result.required_fact_recall == 1.0
    assert result.number_consistency == 0.0
    assert result.introduced_numbers == ("30",)

