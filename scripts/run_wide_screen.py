"""Prepare or run a reproducible low-cost OpenRouter model screen."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))

from shuorenhua_bench.dataset import read_jsonl
from shuorenhua_bench.model_judge import atomic_json
from shuorenhua_bench.schemas import Scenario
from shuorenhua_bench.wide_screen import (
    make_plan,
    prepare_expansion,
    prepare_rejudge,
    reanalyze_screen,
    run_screen,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, help='Saved OpenRouter /models JSON, required for new plans')
    parser.add_argument('--reuse-generations', type=Path, help='Start a separate judging study using verified saved candidate responses')
    parser.add_argument('--extend', type=Path, help='Extend a verified study with more scenario families and reuse compatible checks')
    parser.add_argument('--additional-scenarios', type=int, default=12)
    parser.add_argument('--judge-provider', help='Provider slug for the new judging pass; requires --reuse-generations')
    parser.add_argument('--scenarios', type=Path, default=ROOT / 'data/prompts/suite_zh_v0.3.jsonl')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--models', type=int, default=150)
    parser.add_argument('--scenario-count', type=int, default=6)
    parser.add_argument('--budget-usd', type=float, default=12)
    parser.add_argument('--seed', type=int, default=20260917)
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--request-interval', type=float, default=1,
                        help='Minimum seconds between new requests; 429 responses also trigger a 30-second cooldown')
    parser.add_argument('--bootstrap-samples', type=int, default=100)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--analyze-only', action='store_true', help='Verify and rebuild saved results without API calls')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.bootstrap_samples < 0:
        parser.error('bootstrap samples must be nonnegative')
    if args.analyze_only:
        report = reanalyze_screen(args.output, bootstrap=args.bootstrap_samples)
        print(json.dumps({k: report[k] for k in ['n_models_ranked', 'n_accepted_pairs', 'cost', 'integrity']}, indent=2))
        return
    path = args.output / 'plan.json'
    if args.extend:
        if args.resume or args.reuse_generations or args.judge_provider:
            parser.error('--extend needs a new output and preserves the original judge and provider')
        plan = prepare_expansion(args.extend, args.output, read_jsonl(args.scenarios, Scenario),
                                 additional_scenarios=args.additional_scenarios, budget_usd=args.budget_usd)
    elif args.reuse_generations:
        if args.resume or not args.judge_provider:
            parser.error('--reuse-generations requires a new study and --judge-provider')
        plan = prepare_rejudge(args.reuse_generations, args.output, budget_usd=args.budget_usd,
                               judge_provider=args.judge_provider)
    elif args.judge_provider:
        parser.error('--judge-provider requires --reuse-generations; saved plans cannot change')
    elif args.resume:
        if not path.exists():
            parser.error('resume requires an existing frozen plan')
        plan = json.loads(path.read_text(encoding='utf-8'))
    else:
        if args.output.exists():
            parser.error('output exists; use --resume to retain the frozen plan')
        if not args.catalog:
            parser.error('a saved public model catalog is required')
        catalog = json.loads(args.catalog.read_text(encoding='utf-8'))['data']
        system_prompt = ('你正在替用户撰写一条真实沟通消息。严格依据给定场景、关系、渠道和事实作答；'
                         '不新增事实、承诺或情绪，不解释写作过程，只输出可以直接发送的正文。')
        plan = make_plan(catalog, read_jsonl(args.scenarios, Scenario), system_prompt,
                         count=args.models, scenario_count=args.scenario_count,
                         budget_usd=args.budget_usd, seed=args.seed)
        args.output.mkdir(parents=True)
        atomic_json(path, plan)
        wanted = {m['model'] for m in plan['models']} | {plan['judge']['model']}
        atomic_json(args.output / 'catalog-selected.json', [m for m in catalog if m['id'] in wanted])
    n, s = len(plan['models']), len(plan['scenarios'])
    print(json.dumps({'models': n, 'scenarios': s, 'planned_generations': n * s,
                      'maximum_cycle_pairs': n * s, 'maximum_judge_checks': n * s * 2,
                      'budget_usd': plan['budget_usd'], 'execute': args.execute,
                      'judge': plan['judge']['model'], 'output': str(args.output)}, indent=2), flush=True)
    if args.execute:
        run_screen(args.output, plan, workers=args.workers, bootstrap=args.bootstrap_samples,
                   request_interval=args.request_interval)


if __name__ == '__main__':
    main()
