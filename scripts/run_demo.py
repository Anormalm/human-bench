"""Exercise every study stage with declared synthetic evidence. No model API calls."""
import argparse
import json
import random
from pathlib import Path

from shuorenhua_bench.dataset import read_jsonl, write_jsonl
from shuorenhua_bench.leaderboard.aggregate import aggregate
from shuorenhua_bench.schemas import Pair, PairwiseJudgment, Response, Scenario
from shuorenhua_bench.study import import_judgments, prepare_study, write_json

ROOT = Path(__file__).resolve().parents[1]


def build_demo(output, samples=200):
    scenarios = read_jsonl(ROOT / "data/prompts/challenge_zh_v0.3.jsonl", Scenario)
    responses = read_jsonl(ROOT / "data/responses/challenge_fixtures.jsonl", Response)
    manifest = prepare_study(scenarios, responses, output, raters=12, judgments_per_pair=3,
                             study_name="Controlled software demonstration", demo=True)
    mapping = json.loads((output / "private/response_map.json").read_text(encoding="utf-8"))
    lookup = {r.response_id: r for r in responses}
    strength = {"fixture-concise": 1.0, "fixture-padded": 0.0, "fixture-overpromise": -0.7}
    rng = random.Random(20260913)
    exports = []
    for assignment, relative in manifest["assignments"].items():
        packet = json.loads((output / relative).read_text(encoding="utf-8"))
        rows = []
        for item in packet["items"]:
            a, b = lookup[mapping[item["response_a"]]], lookup[mapping[item["response_b"]]]
            if rng.random() < .18:
                preference = "tie"
            else:
                p = 1 / (1 + __import__("math").exp(-(strength[a.system_id] - strength[b.system_id])))
                preference = "A" if rng.random() < p else "B"
            def action(response):
                send = {"fixture-concise": .82, "fixture-padded": .3, "fixture-overpromise": .12}[response.system_id]
                return "send" if rng.random() < send else rng.choice(["revise", "reject"])
            rows.append(PairwiseJudgment(
                pair_id=item["pair_id"], scenario_id=item["scenario_id"], annotator_id=assignment,
                response_a=item["response_a"], response_b=item["response_b"], preference=preference,
                action_a=action(a), action_b=action(b), confidence=3, duration_seconds=30,
                study_id=manifest["study_id"], assignment_id=assignment, evidence_kind="synthetic"))
        path = output / "exports" / f"{assignment}.jsonl"
        write_jsonl(path, rows)
        exports.append(path)
    judgments, _ = import_judgments(output, exports)
    report = aggregate(judgments, responses, scenarios=scenarios,
                       pairs=read_jsonl(output / "private/pairs.jsonl", Pair),
                       bootstrap_samples=samples, seed=20260913)
    report["study_id"] = manifest["study_id"]
    report["demo_data_generation"] = "Simulated labels from declared fixture strengths; no human raters."
    write_json(output / "report.json", report)
    write_jsonl(output / "judgments.jsonl", judgments)
    return manifest, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "studies/software-demo")
    parser.add_argument("--bootstrap-samples", type=int, default=200)
    parser.add_argument("--update-web-demo", action="store_true")
    args = parser.parse_args()
    manifest, report = build_demo(args.output, args.bootstrap_samples)
    if args.update_web_demo:
        packet = json.loads((args.output / manifest["assignments"]["rater-001"]).read_text(encoding="utf-8"))
        write_json(ROOT / "data/web/demo_bundle.json", packet)
        write_json(ROOT / "data/web/demo_report.json", report)
    print(json.dumps({"study": str(args.output), "pairs": manifest["n_pairs"],
                      "judgments": report["sample"]["n_judgments"],
                      "successful_bootstrap_fits": report["uncertainty"]["successful_model_samples"],
                      "evidence": report["evidence_kind"]}))


if __name__ == "__main__":
    main()
