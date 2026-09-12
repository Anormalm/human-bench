from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import yaml

from .audit import audit_dataset, plan_sample_size
from .benchmark_run import run_benchmark
from .dataset import read_jsonl, write_jsonl
from .leaderboard.aggregate import aggregate
from .schemas import Pair, Response, Scenario
from .study import import_judgments, prepare_study, verify_study, write_json


def main():
    parser = argparse.ArgumentParser(prog="shuorenhua", description="Human-grounded communication benchmark")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Generate, judge both orders, rank, and prepare human validation")
    run.add_argument("--scenarios", type=Path, required=True)
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--responses", type=Path, help="Use existing complete native-generation outputs")
    run.add_argument("--limit", type=int, help="Select a reproducible random scenario subset")
    run.add_argument("--seed", type=int, default=20260913)
    run.add_argument("--bootstrap-samples", type=int, default=1000)
    run.add_argument("--execute", action="store_true", help="Make paid API calls; default is preview")
    run.add_argument("--max-requests", type=int, help="Persistent HTTP attempt cap, including retries")
    run.add_argument("--resume", action="store_true")
    prepare = sub.add_parser("prepare", help="Freeze a study and create blinded rater packets")
    prepare.add_argument("--scenarios", type=Path, required=True)
    prepare.add_argument("--responses", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--raters", type=int, default=9)
    prepare.add_argument("--judgments-per-pair", type=int, default=3)
    prepare.add_argument("--seed", type=int, default=20260913)
    prepare.add_argument("--name", default="Chinese communication study")
    evaluate = sub.add_parser("evaluate", help="Verify study, resolve blind exports and report")
    evaluate.add_argument("--study", type=Path, required=True)
    evaluate.add_argument("--exports", type=Path, nargs="+", required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--bootstrap-samples", type=int, default=1000)
    evaluate.add_argument("--seed", type=int, default=20260913)
    audit = sub.add_parser("audit", help="Check dataset integrity, coverage and split leakage")
    audit.add_argument("--scenarios", type=Path, required=True)
    audit.add_argument("--responses", type=Path)
    audit.add_argument("--splits", type=Path)
    audit.add_argument("--output", type=Path, required=True)
    plan = sub.add_parser("plan", help="Conservative approximate annotation size planning")
    plan.add_argument("--systems", type=int, default=4)
    plan.add_argument("--scenarios", type=int, default=200)
    plan.add_argument("--raters-per-pair", type=int, default=3)
    plan.add_argument("--effect", type=float, default=0.1)
    plan.add_argument("--icc", type=float, default=0.25)
    plan.add_argument("--output", type=Path)
    verify = sub.add_parser("verify", help="Verify all frozen study files")
    verify.add_argument("--study", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        scenarios = read_jsonl(args.scenarios, Scenario)
        if args.limit is not None:
            if args.limit < 1 or args.limit > len(scenarios):
                parser.error("--limit must be between 1 and the scenario count")
            indices = sorted(random.Random(args.seed).sample(range(len(scenarios)), args.limit))
            scenarios = [scenarios[i] for i in indices]
        responses = read_jsonl(args.responses, Response) if args.responses else None
        if responses is not None and args.limit is not None:
            selected = {s.scenario_id for s in scenarios}
            responses = [r for r in responses if r.scenario_id in selected]
        result = run_benchmark(
            scenarios, yaml.safe_load(args.config.read_text(encoding="utf-8-sig")), args.output,
            execute=args.execute, max_requests=args.max_requests, resume=args.resume,
            bootstrap_samples=args.bootstrap_samples, seed=args.seed, existing_responses=responses)
    elif args.command == "prepare":
        result = prepare_study(read_jsonl(args.scenarios, Scenario), read_jsonl(args.responses, Response),
                               args.output, raters=args.raters, judgments_per_pair=args.judgments_per_pair,
                               seed=args.seed, study_name=args.name)
    elif args.command == "evaluate":
        manifest = verify_study(args.study)
        judgments, duplicates = import_judgments(args.study, args.exports)
        result = aggregate(
            judgments, read_jsonl(args.study / "private/responses.jsonl", Response),
            scenarios=read_jsonl(args.study / "private/scenarios.jsonl", Scenario),
            pairs=read_jsonl(args.study / "private/pairs.jsonl", Pair),
            min_raters=manifest["judgments_per_pair"], bootstrap_samples=args.bootstrap_samples,
            seed=args.seed)
        result["study_id"] = manifest["study_id"]
        result["input_coverage"] = manifest.get("input_coverage", {})
        missing = result["input_coverage"].get("missing_system_scenario_cells", [])
        if missing:
            result["warnings"].append(f"{len(missing)} declared system/scenario cells have no response.")
        result["import"] = {"identical_duplicate_exports_ignored": duplicates,
                            "input_files": [p.name for p in args.exports]}
        result["provenance"] = {"study_hashes": manifest["sha256"],
                                "analysis_version": "0.3.0"}
        write_json(args.output, result)
        write_jsonl(args.output.with_suffix(".judgments.jsonl"), judgments)
    elif args.command == "audit":
        result = audit_dataset(
            read_jsonl(args.scenarios, Scenario),
            read_jsonl(args.responses, Response) if args.responses else [],
            splits=json.loads(args.splits.read_text(encoding="utf-8")) if args.splits else None)
        write_json(args.output, result)
    elif args.command == "verify":
        result = verify_study(args.study)
    else:
        result = plan_sample_size(systems=args.systems, scenarios=args.scenarios,
                                  raters_per_pair=args.raters_per_pair, effect=args.effect, icc=args.icc)
        if args.output:
            write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if args.command == "audit" and not result["valid"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
