from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audit import audit_dataset, plan_sample_size
from .dataset import read_jsonl, write_jsonl
from .leaderboard.aggregate import aggregate
from .schemas import Pair, Response, Scenario
from .study import import_judgments, prepare_study, verify_study, write_json


def main():
    parser = argparse.ArgumentParser(prog="shuorenhua", description="Human-grounded communication benchmark")
    sub = parser.add_subparsers(dest="command", required=True)
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
    if args.command == "prepare":
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
