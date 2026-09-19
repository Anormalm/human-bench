"""Budgeted, sparse OpenRouter screening. Separate from confirmatory human studies."""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .benchmark_run import run_lock
from .leaderboard.aggregate import _clusters
from .model_judge import (
    RUBRIC,
    RUBRIC_VERSION,
    JudgeDecision,
    atomic_json,
    compare_orders,
    digest,
    response_format,
)
from .response_runner import render_prompt
from .schemas import Scenario
from .statistics.davidson_bt import comparison_components, fit_davidson

API = 'https://openrouter.ai/api/v1/chat/completions'
SPECIALIST = re.compile(r'(^inference-net/|^relace/|^morph/|^perplexity/|safeguard|llama-guard|'
                        r'content-safety|ui-tars|hy-mt2|perceptron|image|audio|voxtral)', re.IGNORECASE)


def billing_totals(state):
    entries = list(state['entries'].values())
    imported = [state['entries'][k] for k in state.get('imported_tasks', [])]
    return {'reported_usd': sum(e.get('reported_cost') or 0 for e in entries),
            'reused_requests': len(imported),
            'reused_generation_requests': sum(k.startswith('g:') for k in state.get('imported_tasks', [])),
            'reused_judge_requests': sum(k.startswith('j:') for k in state.get('imported_tasks', [])),
            'reused_reported_usd': sum(e.get('reported_cost') or 0 for e in imported),
            'charged_or_reserved_usd': sum(e['accounted_cost'] for e in entries),
            'unknown_cost_requests': sum(e.get('reported_cost') is None for e in entries),
            'attempts': len(entries), 'budget_usd': state['budget_usd']}


def campaign_totals(root, plan, state):
    """Include earlier provider passes once, deduplicating exactly reused ledger entries."""
    entries = {digest(e): e for e in state['entries'].values()}
    seen, studies = {digest(plan)}, 1
    while plan.get('generation_source'):
        source = plan['generation_source']
        root = (Path(root) / source['path']).resolve()
        parent = json.loads((root / 'plan.json').read_text(encoding='utf-8'))
        ledger = json.loads((root / 'requests.json').read_text(encoding='utf-8'))
        if (digest(parent) != source['plan_hash'] or digest(ledger) != source['ledger_hash']
                or digest(parent) in seen):
            raise ValueError('generation source provenance changed or contains a cycle')
        for task_id in state.get('imported_tasks', []):
            if state['entries'][task_id] != ledger['entries'].get(task_id):
                raise ValueError('reused request differs from its source ledger')
        entries.update({digest(e): e for e in ledger['entries'].values()})
        plan, state = parent, ledger
        seen.add(digest(plan)); studies += 1
    total = billing_totals({'entries': entries, 'budget_usd': None})
    total.pop('budget_usd')
    total['n_studies'] = studies
    return total


def result_fields(body):
    usage = body.get('usage') if isinstance(body.get('usage'), dict) else {}
    cost = usage.get('cost')
    if not isinstance(cost, (float, int)) or isinstance(cost, bool) or not np.isfinite(cost) or cost < 0:
        cost = None
    choices = body.get('choices')
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get('message') if isinstance(choice.get('message'), dict) else {}
    text = message.get('content')
    success = isinstance(text, str) and bool(text.strip()) and choice.get('finish_reason') == 'stop'
    return ('success' if success else 'failed', text.strip() if success else None, cost)


def failure_reason(record):
    if record.get('status') == 'success':
        return None
    if record.get('status') != 'failed':
        return record.get('status', 'not_sent')
    body = record.get('body', {})
    error = body.get('error')
    if isinstance(error, dict):
        # Public reports expose error categories, not provider messages or account identifiers.
        code = error.get('http_status', error.get('code'))
        return f'http_{code}' if isinstance(code, int) else 'provider_or_network_error'
    choices = body.get('choices')
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    return 'output_token_limit' if choice.get('finish_reason') == 'length' else 'no_usable_response'


def select_models(catalog, count=150, judge='openai/gpt-5.6-luna'):
    families, seen = defaultdict(list), set()
    for model in sorted(catalog, key=lambda m: (-m.get('created', 0), m['id'])):
        name, arch, prices = model['id'], model.get('architecture', {}), model['pricing']
        canonical = model.get('canonical_slug', name)
        if (name == judge or '/' not in name or name.startswith(('~', 'openrouter/', 'stealth/'))
                or ':' in name or SPECIALIST.search(name) or canonical in seen
                or arch.get('output_modalities') != ['text'] or 'text' not in arch.get('input_modalities', [])
                or 'max_tokens' not in model.get('supported_parameters', [])
                or not 0 < float(prices.get('prompt', 0)) * 1e6 <= 1
                or not 0 < float(prices.get('completion', 0)) * 1e6 <= 3
                or float(prices.get('request', 0)) != 0):
            continue
        seen.add(canonical)
        families[name.split('/')[0]].append(model)
    selected = []
    while len(selected) < count and any(families.values()):
        for family in sorted(families):
            if families[family] and len(selected) < count:
                selected.append(families[family].pop(0))
    return selected


def select_scenarios(scenarios, count, seed):
    groups = _clusters(scenarios, scenarios)
    rng = random.Random(seed)
    genres = sorted({s.genre for s in scenarios}); rng.shuffle(genres)
    chosen, used = [], set()
    for genre in genres:
        options = sorted((s for s in scenarios if s.genre == genre), key=lambda s: s.scenario_id)
        rng.shuffle(options)
        for s in options:
            if groups[s.scenario_id] not in used:
                chosen.append(s); used.add(groups[s.scenario_id]); break
        if len(chosen) == count:
            return chosen
    raise ValueError('not enough distinct genres and scenario families for this screen')


def reasoning_options(model, *, judge=False):
    if 'reasoning' not in model.get('supported_parameters', []):
        return {}
    reasoning = model.get('reasoning', {})
    if not judge and not reasoning.get('mandatory', False):
        return {'reasoning': {'enabled': False, 'exclude': True}}
    efforts = reasoning.get('supported_efforts')
    for effort in ['low', 'minimal', 'medium', 'high', 'xhigh', 'max']:
        if efforts is None or effort in efforts:
            return {'reasoning': {'effort': effort, 'exclude': True}}
    return {'reasoning': {'exclude': True}}


def make_plan(catalog, scenarios, system_prompt, *, count=150, scenario_count=6,
              judge='openai/gpt-5.6-luna', seed=20260917, budget_usd=12):
    if count < 3 or scenario_count < 2 or not 0 < budget_usd <= 20:
        raise ValueError('invalid screen size or budget')
    models = select_models(catalog, count, judge)
    if len(models) < count:
        raise ValueError(f'only {len(models)} eligible low-cost model IDs; requested {count}')
    judge_model = next(m for m in catalog if m['id'] == judge)
    if ('structured_outputs' not in judge_model['supported_parameters']
            or float(judge_model['pricing']['prompt']) * 1e6 > 1
            or float(judge_model['pricing']['completion']) * 1e6 > 3):
        raise ValueError('judge must support structured outputs and fit the price ceilings')
    selected = select_scenarios(scenarios, scenario_count, seed)
    specs = [{'model': m['id'], 'name': m['name'], 'canonical_slug': m.get('canonical_slug'),
              'catalog_pricing': m['pricing'], 'options': reasoning_options(m)} for m in models]
    return {'schema_version': '0.1', 'kind': 'wide_model_screen', 'seed': seed,
            'budget_usd': budget_usd, 'max_requests': count * scenario_count * 5,
            'models': specs, 'scenarios': [s.model_dump(mode='json') for s in selected],
            'system_prompt': system_prompt, 'candidate_max_tokens': 2048, 'judge_max_tokens': 1024,
            'judge': {'model': judge, 'options': reasoning_options(judge_model, judge=True)},
            'rubric': RUBRIC, 'rubric_version': RUBRIC_VERSION,
            'provider': {'sort': 'price', 'allow_fallbacks': False, 'require_parameters': True,
                         'max_price': {'prompt': 1, 'completion': 3, 'request': 0}},
            'schedule': 'One seeded cycle per scenario over models with all generations; no outcome-based selection.',
            'selection': 'Paid text model IDs, specialist exclusions, canonical deduplication, family round-robin newest first.',
            'decoding': 'Reasoning disabled where optional, lowest economical advertised effort where mandatory; equal visible token caps, not equal compute.',
            'created_at': datetime.now(timezone.utc).isoformat()}


def cycle_schedule(models, scenarios, seed):
    """Each model has two opponents per scenario; different seeded cycles share all nodes."""
    if len(models) < 3 or len(set(models)) != len(models):
        raise ValueError('at least three unique models required')
    rows = []
    for scenario in scenarios:
        order = sorted(models)
        random.Random(f'{seed}:{scenario}').shuffle(order)
        for i, left in enumerate(order):
            right = order[(i + 1) % len(order)]
            a, b = sorted((left, right))
            rows.append({'pair_id': digest([scenario, a, b])[:20], 'scenario_id': scenario,
                         'model_a': a, 'model_b': b})
    return rows


def scheduled_cohort(plan, responses):
    names = [m['model'] for m in plan['models']]
    if plan.get('cohort_policy') in {'fixed_prior_complete', 'fixed_model_expansion'}:
        return names
    return [m for m in names if all(responses.get((s['scenario_id'], m), {}).get('status') == 'success'
                                   for s in plan['scenarios'])]


def screen_schedule(plan, responses):
    expansion = plan.get('model_expansion')
    if expansion:
        rows = deepcopy(expansion['inherited_schedule'])
        for scenario in plan['scenarios']:
            sid = scenario['scenario_id']
            anchors = sorted(expansion['anchor_models'])
            random.Random(f'{plan["seed"]}:enroll:{sid}').shuffle(anchors)
            for i, model in enumerate(sorted(expansion['added_models'])):
                for offset in (0, 1):
                    a, b = sorted((model, anchors[(2 * i + offset) % len(anchors)]))
                    rows.append({'pair_id': digest([sid, a, b])[:20], 'scenario_id': sid,
                                 'model_a': a, 'model_b': b})
        return rows
    cohort = scheduled_cohort(plan, responses)
    return cycle_schedule(cohort, [s['scenario_id'] for s in plan['scenarios']], plan['seed']) if len(cohort) >= 3 else []


def request_provider(plan, model):
    if model == plan['judge']['model']:
        return plan['judge'].get('provider', plan['provider'])
    spec = next((m for m in plan['models'] if m['model'] == model), {})
    return spec.get('provider', plan['provider'])


def pair_available(pair, responses):
    return all(responses.get((pair['scenario_id'], pair[k]), {}).get('status') == 'success'
               for k in ('model_a', 'model_b'))


class BudgetStop(RuntimeError):
    pass


class BudgetClient:
    """Persist reservations before requests; keep uncertain charges reserved across resume."""
    def __init__(self, root, plan, *, transport=None, request_interval=0):
        self.root, self.plan = Path(root), plan
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'raw').mkdir(exist_ok=True)
        self.path = self.root / 'requests.json'
        if not self.path.exists() and any((self.root / 'raw').glob('*.json')):
            raise ValueError('request ledger missing; refusing to repeat saved requests')
        self.lock = threading.Lock()
        self.pacing_lock = threading.Lock()
        self.request_interval = request_interval
        self.not_before = 0.0
        self.transport = transport or self._send
        self.state = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {
            'plan_hash': digest(plan), 'budget_usd': plan['budget_usd'], 'entries': {}}
        if self.state['plan_hash'] != digest(plan):
            raise ValueError('screen protocol changed; use a new directory')
        atomic_json(self.path, self.state)

    def totals(self):
        return billing_totals(self.state)

    def _pace(self):
        if self.request_interval <= 0:
            return
        while True:
            with self.pacing_lock:
                now = time.monotonic()
                delay = self.not_before - now
                if delay <= 0:
                    self.not_before = now + self.request_interval
                    return
            time.sleep(min(delay, 1))

    def _send(self, payload):
        key = os.environ.get('OPENROUTER_API_KEY')
        if not key:
            raise ValueError('OPENROUTER_API_KEY is not configured')
        request = urllib.request.Request(API, data=json.dumps(payload, ensure_ascii=False).encode(),
                                         headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # Preserve provider errors without request headers or credentials.
            return {'error': {'http_status': exc.code,
                              'message': exc.read(3000).decode('utf-8', errors='replace')}}

    def request(self, task_id, payload):
        provider = request_provider(self.plan, payload.get('model'))
        if payload.get('provider') != provider:
            raise ValueError('request must retain the frozen provider price ceilings')
        limit = payload.get('max_tokens')
        if not isinstance(limit, int) or not 0 < limit <= self.plan['candidate_max_tokens']:
            raise ValueError('invalid request token budget')
        fingerprint = digest(payload)
        raw_path = self.root / 'raw' / (digest(task_id) + '.json')
        with self.lock:
            prior = self.state['entries'].get(task_id)
            if prior:
                if prior['request_hash'] != fingerprint:
                    raise ValueError('cached task input changed')
                if raw_path.exists():
                    record = json.loads(raw_path.read_text(encoding='utf-8'))
                    if (record['request_hash'] != fingerprint or record['task_id'] != task_id
                            or (prior.get('raw_sha256') and prior['raw_sha256'] != record['sha256'])
                            or record['sha256'] != digest({k: v for k, v in record.items() if k != 'sha256'})):
                        raise ValueError('cached raw record changed')
                    return record
                return {'status': 'unknown_after_interruption', 'task_id': task_id}
            # Conservative reservation: UTF-8 payload bytes plus overhead, at least 8192
            # input tokens; twice the requested output allowance. Provider pricing is capped.
            rates = provider['max_price']
            input_allowance = max(8192, len(json.dumps(payload, ensure_ascii=False).encode()) + 1024)
            reservation = (input_allowance * rates['prompt'] + 2 * limit * rates['completion']) / 1e6
            totals = self.totals()
            if (totals['attempts'] >= self.plan['max_requests']
                    or totals['charged_or_reserved_usd'] + reservation > self.plan['budget_usd']):
                raise BudgetStop('request or cost reservation limit reached')
            self.state['entries'][task_id] = {'request_hash': fingerprint, 'model': payload['model'],
                                              'accounted_cost': reservation, 'reported_cost': None,
                                              'status': 'reserved', 'started_at': datetime.now(timezone.utc).isoformat()}
            atomic_json(self.path, self.state)
        try:
            self._pace()
            body = self.transport(payload)
        except (OSError, ValueError) as exc:
            body = {'error': {'type': type(exc).__name__, 'message': 'Request failed; billing outcome unknown.'}}
        if not isinstance(body, dict):
            body = {'error': {'message': 'Response was not a JSON object.'}, 'raw_response': body}
        error = body.get('error')
        if (self.request_interval > 0 and isinstance(error, dict)
                and (error.get('http_status') == 429 or error.get('code') == 429)):
            with self.pacing_lock:
                self.not_before = max(self.not_before, time.monotonic() + 30)
        status, text, cost = result_fields(body)
        record = {'task_id': task_id, 'request_hash': fingerprint, 'payload': payload, 'body': body,
                  'status': status, 'text': text}
        record['sha256'] = digest(record)
        with self.lock:
            atomic_json(raw_path, record)
            entry = self.state['entries'][task_id]
            entry.update(status=record['status'], reported_cost=cost,
                         accounted_cost=float(cost) if cost is not None else reservation,
                         raw_sha256=record['sha256'])
            atomic_json(self.path, self.state)
        return record


def generation_payload(plan, spec, scenario):
    return {'model': spec['model'], 'messages': [{'role': 'system', 'content': plan['system_prompt']},
            {'role': 'user', 'content': render_prompt(scenario)}], 'max_tokens': plan['candidate_max_tokens'],
            'provider': request_provider(plan, spec['model']), **spec['options']}


def judge_payload(plan, pair, scenario, responses, reverse=False):
    a, b = pair['model_a'], pair['model_b']
    if reverse:
        a, b = b, a
    prompt = {'scenario': json.loads(render_prompt(scenario)),
              'candidate_A': responses[(scenario.scenario_id, a)]['text'],
              'candidate_B': responses[(scenario.scenario_id, b)]['text']}
    return {'model': plan['judge']['model'], 'messages': [{'role': 'system', 'content': plan['rubric']},
            {'role': 'user', 'content': json.dumps(prompt, ensure_ascii=False)}],
            'max_tokens': plan['judge_max_tokens'], 'provider': plan['judge'].get('provider', plan['provider']),
            'response_format': response_format('json_schema'), **plan['judge']['options']}


def _decision(record):
    if record and record.get('status') == 'success':
        try:
            return JudgeDecision.model_validate_json(record['text'], strict=True)
        except ValueError:
            pass
    return None


def analyze(plan, responses, schedule, checks, costs, *, phase, bootstrap=0):
    names = [m['model'] for m in plan['models']]
    scenario_ids = [s['scenario_id'] for s in plan['scenarios']]
    complete = [m for m in names if all(responses.get((s, m), {}).get('status') == 'success' for s in scenario_ids)]
    accepted, diagnostics = [], []
    for pair in schedule:
        f, r = (checks.get((pair['pair_id'], order)) for order in (False, True))
        result = compare_orders(_decision(f), _decision(r))
        if not pair_available(pair, responses):
            result.update(accepted=False, status='missing_candidate', exclusion_reason='missing_candidate_response')
        diagnostics.append({**pair, **result})
        if result['accepted']:
            accepted.append((pair['model_a'], pair['model_b'], result['stable_preference'], pair['scenario_id']))
    components = comparison_components([(a, b, y) for a, b, y, _ in accepted])
    observed = {m for c in components for m in c}
    components += [[m] for m in scheduled_cohort(plan, responses) if m not in observed]
    components.sort(key=lambda c: (-len(c), c))
    ranked = components[0] if components and len(components[0]) >= 3 else []
    comparisons = [(a, b, y) for a, b, y, _ in accepted if a in ranked and b in ranked]
    fit = fit_davidson(comparisons) if phase == 'complete' and comparisons else None
    if fit is not None and not fit.converged:
        fit = None
    rank_samples, ability_samples = defaultdict(list), defaultdict(list)
    lost = 0
    if fit is not None and bootstrap:
        rng = random.Random(plan['seed'])
        for _ in range(bootstrap):
            sampled = rng.choices(scenario_ids, k=len(scenario_ids))
            draws = [(a, b, y) for s in sampled for a, b, y, sid in accepted
                     if sid == s and a in ranked and b in ranked]
            if ({m for a, b, _ in draws for m in (a, b)} != set(ranked)
                    or len(comparison_components(draws)) != 1):
                lost += 1; continue
            sample_fit = fit_davidson(draws)
            if not sample_fit.converged:
                lost += 1; continue
            values = sample_fit.abilities
            for m in ranked:
                rank_samples[m].append(1 + sum(v > values[m] + 1e-10 for v in values.values()))
                ability_samples[m].append(values[m])
    rows = []
    for model in plan['models']:
        m = model['model']
        n_success = sum(responses.get((s, m), {}).get('status') == 'success' for s in scenario_ids)
        votes = [y if a == m else {'A': 'B', 'B': 'A', 'tie': 'tie'}[y]
                 for a, b, y, _ in accepted if m in (a, b)]
        ability = fit.abilities.get(m) if fit else None
        rank = 1 + sum(v > ability + 1e-10 for v in fit.abilities.values()) if ability is not None else None
        previous_rank = plan.get('baseline', {}).get('ranks', {}).get(m)
        def interval(values):
            if len(values) < 20 or lost > bootstrap * .1:
                return None
            bounds = [float(x) for x in np.quantile(values, [.025, .975])]
            return None if abs(bounds[1] - bounds[0]) < 1e-10 else bounds
        rows.append({'model': m, 'name': model['name'], 'n_generated': n_success,
                     'is_new_model': m in plan.get('model_expansion', {}).get('added_models', []),
                     'n_scenarios': len(scenario_ids), 'n_accepted': len(votes),
                     'n_planned_comparisons': sum(m in (p['model_a'], p['model_b']) for p in schedule),
                     'wins': votes.count('A'), 'ties': votes.count('tie'), 'losses': votes.count('B'),
                     'ability': ability,
                     'rank': rank, 'previous_rank': previous_rank,
                     'rank_change': previous_rank - rank if rank is not None and previous_rank is not None else None,
                     'rank_interval': interval(rank_samples[m]), 'ability_interval': interval(ability_samples[m]),
                     'generation_failures': dict(Counter(failure_reason(responses[(s, m)]) for s in scenario_ids
                                                         if (s, m) in responses and responses[(s, m)].get('status') != 'success')),
                     'generation_reported_usd': sum(result_fields(responses[(s, m)]['body'])[2] or 0
                                                    for s in scenario_ids if 'body' in responses.get((s, m), {})),
                     'status': ('ranked' if n_success == len(scenario_ids) else 'ranked_partial_generation') if ability is not None
                               else 'incomplete_generation' if n_success < len(scenario_ids)
                               else 'ranking_pending' if phase != 'complete' else 'disconnected_or_fit_unavailable'})
    rows.sort(key=lambda r: (r['rank'] is None, r['rank'] or 0, r['model']))
    return {'schema_version': '0.1', 'report_kind': 'wide_screen', 'phase': phase,
            'updated_at': datetime.now(timezone.utc).isoformat(), 'plan_hash': digest(plan),
            'n_models_planned': len(names), 'n_models_complete': len(complete),
            'n_models_ranked': sum(r['rank'] is not None for r in rows), 'n_scenarios': len(scenario_ids),
            'n_generation_successes': sum(r['n_generated'] for r in rows),
            'n_pairs_planned': len(schedule), 'n_accepted_pairs': len(accepted),
            'n_judge_checks_saved': sum('body' in c for c in checks.values()),
            'n_judge_checks_valid': sum(_decision(c) is not None for c in checks.values()),
            'judge': plan['judge']['model'], 'cost': costs,
            'judge_provider_policy': plan['judge'].get('provider', plan['provider']),
            'cohort_policy': plan.get('cohort_policy', 'complete_generations'),
            'baseline_n_scenarios': plan.get('baseline', {}).get('n_scenarios'),
            'baseline_n_models': plan.get('baseline', {}).get('n_models'),
            'n_models_added': len(plan.get('model_expansion', {}).get('added_models', [])),
            'schedule_description': plan['schedule'],
            'n_judge_checks_skipped': sum(c.get('status') == 'missing_candidate' for c in checks.values()),
            'rows': rows, 'order_status_counts': dict(Counter(d['status'] for d in diagnostics)),
            'components': components, 'bootstrap': {'attempts': bootstrap if fit is not None else 0, 'lost_fits': lost,
                                                   'intervals_withheld': lost > bootstrap * .1,
                                                   'n_scenario_groups': len(scenario_ids)},
            'fit': {'converged': fit.converged, 'regularization': fit.regularization,
                    'iterations': fit.iterations, 'gradient_norm': fit.gradient_norm} if fit else None,
            'warnings': [f'Exploratory screening on {len(scenario_ids)} public AI-authored Chinese scenarios; no supported overall winner.',
                         'Rank intervals resample whole scenario families. Intervals are withheld if over 10% of fits fail, fewer than 20 survive, or the interval collapses.',
                         ('The cohort and pairings are frozen before new responses. Missing responses skip affected pairs, not whole models; inspect unequal coverage.'
                          if plan.get('cohort_policy') in {'fixed_prior_complete', 'fixed_model_expansion'} else
                          'Only complete-generation models enter the sparse schedule. Failure is not a preference loss.'),
                         'Rank covers the largest connected accepted-comparison component; disconnected models are not ordered against it.',
                         'Model judge predictions are not human preference evidence. Price and token limits restrict the population of models.',
                         'One fixed judge may favor related models or styles. Candidate identities are hidden, but judge error and family bias are not measured here.',
                         'Some IDs are revisions or variants within one family, not independent model families.',
                         'Cost reservations bound local scheduling using token allowances. Provider price ceilings are enforced in requests; final billing may differ.'],
            'diagnostics': diagnostics}


def reanalyze_screen(root, *, bootstrap=100, write_report=True):
    """Validate frozen inputs and saved HTTP evidence; never instantiate a network client."""
    root = Path(root)
    with run_lock(root):
        plan = json.loads((root / 'plan.json').read_text(encoding='utf-8'))
        state = json.loads((root / 'requests.json').read_text(encoding='utf-8'))
        if state['plan_hash'] != digest(plan) or state['budget_usd'] != plan['budget_usd']:
            raise ValueError('frozen plan or billing ledger changed')
        seen, raw_files = set(), set()
        def read(task_id, payload):
            entry = state['entries'].get(task_id)
            if entry is None:
                return {'status': 'not_sent', 'task_id': task_id}
            seen.add(task_id)
            if entry['request_hash'] != digest(payload):
                raise ValueError('saved request differs from the frozen plan')
            path = root / 'raw' / (digest(task_id) + '.json')
            if not path.exists():
                if entry['status'] != 'reserved':
                    raise ValueError('completed request has no raw evidence')
                return {'status': 'unknown_after_interruption', 'task_id': task_id}
            raw_files.add(path.name)
            record = json.loads(path.read_text(encoding='utf-8'))
            if (record['task_id'] != task_id or record['payload'] != payload
                    or record['request_hash'] != entry['request_hash']
                    or record['sha256'] != digest({k: v for k, v in record.items() if k != 'sha256'})
                    or (entry.get('raw_sha256') and entry['raw_sha256'] != record['sha256'])):
                raise ValueError('saved raw evidence changed')
            status, text, cost = result_fields(record['body'])
            if (record['status'] != status or record['text'] != text
                    or (entry['status'] != 'reserved' and (entry['status'] != status or entry['reported_cost'] != cost))
                    or (entry.get('reported_cost') is not None and entry['accounted_cost'] != cost)):
                raise ValueError('derived result or billing differs from raw evidence')
            return record
        scenarios = [Scenario.model_validate(s) for s in plan['scenarios']]
        responses = {(s.scenario_id, m['model']): read(f'g:{s.scenario_id}:{m["model"]}', generation_payload(plan, m, s))
                     for s in scenarios for m in plan['models']}
        expected = screen_schedule(plan, responses)
        schedule_path = root / 'schedule.json'
        schedule = json.loads(schedule_path.read_text(encoding='utf-8')) if schedule_path.exists() else []
        if schedule and schedule != expected:
            raise ValueError('saved comparison schedule changed')
        by_id = {s.scenario_id: s for s in scenarios}
        checks = {(p['pair_id'], rev): (read(f'j:{p["pair_id"]}:{int(rev)}',
                                           judge_payload(plan, p, by_id[p['scenario_id']], responses, rev))
                                       if pair_available(p, responses) else {'status': 'missing_candidate'})
                  for p in schedule for rev in (False, True)}
        if seen != set(state['entries']) or raw_files != {p.name for p in (root / 'raw').glob('*.json')}:
            raise ValueError('unrecognized request or raw evidence outside the frozen schedule')
        report = analyze(plan, responses, schedule, checks, billing_totals(state), phase='complete', bootstrap=bootstrap)
        report['campaign_cost'] = campaign_totals(root, plan, state)
        report['integrity'] = {'verified_raw_records': len(raw_files), 'ledger_hash': digest(state),
                               'not_sent_generations': sum(r['status'] == 'not_sent' for r in responses.values()),
                               'not_sent_judge_checks': sum(r['status'] == 'not_sent' for r in checks.values()),
                               'note': 'Hashes detect changes relative to the saved ledger; they are not independent signatures.'}
        if write_report:
            atomic_json(root / 'wide-report.json', report)
        return report


def prepare_rejudge(source, output, *, budget_usd, judge_provider):
    """Start a separate judging study from verified generations, preserving their charges."""
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or not 0 < budget_usd <= 20 or not judge_provider:
        raise ValueError('rejudge needs a new directory, provider and positive budget at most $20')
    verified = reanalyze_screen(source, bootstrap=0, write_report=False)
    with run_lock(source):
        original = json.loads((source / 'plan.json').read_text(encoding='utf-8'))
        ledger = json.loads((source / 'requests.json').read_text(encoding='utf-8'))
        if digest(ledger) != verified['integrity']['ledger_hash']:
            raise ValueError('source ledger changed after verification')
        plan = deepcopy(original)
        plan.update(budget_usd=budget_usd, created_at=datetime.now(timezone.utc).isoformat(),
                    generation_source={'path': os.path.relpath(source, output),
                                       'plan_hash': digest(original), 'ledger_hash': digest(ledger)})
        plan['judge']['provider'] = {**plan['provider'], 'only': [judge_provider]}
        entries = {k: deepcopy(e) for k, e in ledger['entries'].items() if k.startswith('g:')}
        if sum(e['accounted_cost'] for e in entries.values()) >= budget_usd:
            raise ValueError('reused generation charges and reservations exhaust the new allowance')
        state = {'plan_hash': digest(plan), 'budget_usd': budget_usd, 'entries': entries,
                 'imported_tasks': sorted(entries)}
        output.mkdir(parents=True)
        (output / 'raw').mkdir()
        atomic_json(output / 'plan.json', plan)
        atomic_json(output / 'requests.json', state)
        if plan.get('cohort_policy') in {'fixed_prior_complete', 'fixed_model_expansion'}:
            atomic_json(output / 'schedule.json', screen_schedule(plan, {}))
        for task_id in entries:
            path = source / 'raw' / (digest(task_id) + '.json')
            if path.exists():
                shutil.copyfile(path, output / 'raw' / path.name)
        catalog = source / 'catalog-selected.json'
        if catalog.exists():
            shutil.copyfile(catalog, output / catalog.name)
        return plan


def prepare_expansion(source, output, scenarios, *, additional_scenarios=12, budget_usd=6):
    """Freeze more distinct scenario families for every previously complete model."""
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or not 0 < budget_usd <= 20 or additional_scenarios < 1:
        raise ValueError('expansion needs a new directory, positive scenario count and budget at most $20')
    verified = reanalyze_screen(source, bootstrap=0, write_report=False)
    with run_lock(source):
        original = json.loads((source / 'plan.json').read_text(encoding='utf-8'))
        if original.get('model_expansion'):
            raise ValueError('scenario expansion after model enrollment needs a new protocol; keep the enrolled study frozen')
        ledger = json.loads((source / 'requests.json').read_text(encoding='utf-8'))
        if digest(ledger) != verified['integrity']['ledger_hash']:
            raise ValueError('source ledger changed after verification')
        full = {s.scenario_id: s for s in scenarios}
        if len(full) != len(scenarios) or any(
                s['scenario_id'] not in full or full[s['scenario_id']].model_dump(mode='json') != s
                for s in original['scenarios']):
            raise ValueError('scenario suite has duplicate IDs or changed source scenarios')
        groups = _clusters(scenarios, scenarios)
        selected = [full[s['scenario_id']] for s in original['scenarios']]
        used = {groups[s.scenario_id] for s in selected}
        if len(used) != len(selected):
            raise ValueError('source scenarios are not independent families in the full suite')
        counts = Counter(s.genre for s in selected)
        rng = random.Random(original['seed'])
        for _ in range(additional_scenarios):
            available = sorted((s for s in scenarios if groups[s.scenario_id] not in used), key=lambda s: s.scenario_id)
            rng.shuffle(available)
            if not available:
                raise ValueError('not enough unused scenario families')
            choice = min(available, key=lambda s: counts[s.genre])
            selected.append(choice); used.add(groups[choice.scenario_id]); counts[choice.genre] += 1
        cohort = ({m['model'] for m in original['models']} if original.get('cohort_policy') == 'fixed_prior_complete'
                  else {r['model'] for r in verified['rows'] if r['n_generated'] == r['n_scenarios']})
        if len(cohort) < 3:
            raise ValueError('expansion requires at least three previously complete models')
        plan = deepcopy(original)
        plan.update(models=[m for m in original['models'] if m['model'] in cohort],
                    scenarios=[s.model_dump(mode='json') for s in selected],
                    budget_usd=budget_usd, max_requests=len(cohort) * len(selected) * 5,
                    created_at=datetime.now(timezone.utc).isoformat(), cohort_policy='fixed_prior_complete',
                    scenario_groups={s.scenario_id: groups[s.scenario_id] for s in selected},
                    suite_hash=digest([s.model_dump(mode='json') for s in scenarios]),
                    generation_source={'path': os.path.relpath(source, output),
                                       'plan_hash': digest(original), 'ledger_hash': digest(ledger),
                                       'reuse_mode': 'generations_and_judge_checks'},
                    baseline={'n_scenarios': len(original['scenarios']),
                              'ranks': {r['model']: r['rank'] for r in verified['rows'] if r['model'] in cohort}},
                    schedule='Frozen seeded cycle per scenario over the prior complete cohort. Missing responses skip only affected pairs.',
                    scenario_selection='Retain prior scenarios; seeded genre balancing over unused full-suite semantic/template families.')
        schedule = cycle_schedule(sorted(cohort), [s.scenario_id for s in selected], plan['seed'])
        old_ids = {s['scenario_id'] for s in original['scenarios']}
        allowed = {f'g:{s}:{m}' for s in old_ids for m in cohort}
        allowed |= {f'j:{p["pair_id"]}:{order}' for p in schedule if p['scenario_id'] in old_ids for order in (0, 1)}
        entries = {k: deepcopy(v) for k, v in ledger['entries'].items() if k in allowed}
        if sum(e['accounted_cost'] for e in entries.values()) >= budget_usd:
            raise ValueError('reused charges and reservations exhaust the new allowance')
        output.mkdir(parents=True); (output / 'raw').mkdir()
        atomic_json(output / 'plan.json', plan)
        atomic_json(output / 'schedule.json', schedule)
        atomic_json(output / 'requests.json', {'plan_hash': digest(plan), 'budget_usd': budget_usd,
                                              'entries': entries, 'imported_tasks': sorted(entries)})
        for task_id in entries:
            path = source / 'raw' / (digest(task_id) + '.json')
            if path.exists():
                shutil.copyfile(path, output / 'raw' / path.name)
        return plan


def prepare_model_expansion(source, output, catalog, model_ids, *, additional_budget_usd=2,
                            max_input_price=3, max_output_price=15):
    """Preserve prior evidence and freeze two old-model opponents for each new model/case."""
    source, output = Path(source).resolve(), Path(output).resolve()
    if (output.exists() or not np.isfinite(additional_budget_usd) or not 0 < additional_budget_usd <= 20
            or not 0 < max_input_price <= 3 or not 0 < max_output_price <= 15
            or not model_ids or len(set(model_ids)) != len(model_ids)):
        raise ValueError('model expansion needs a new output, unique IDs, and bounded positive prices and budget')
    verified = reanalyze_screen(source, bootstrap=0, write_report=False)
    if verified['integrity']['not_sent_generations'] or verified['integrity']['not_sent_judge_checks']:
        raise ValueError('finish the source schedule before enrolling models')
    with run_lock(source):
        original = json.loads((source / 'plan.json').read_text(encoding='utf-8'))
        ledger = json.loads((source / 'requests.json').read_text(encoding='utf-8'))
        if digest(ledger) != verified['integrity']['ledger_hash']:
            raise ValueError('source ledger changed after verification')
        anchors = sorted(r['model'] for r in verified['rows'] if r['n_generated'] == r['n_scenarios'])
        if len(anchors) < 3:
            raise ValueError('model expansion requires three complete anchor models')
        by_id = {m['id']: m for m in catalog}
        seen = {m.get('canonical_slug') or m['model'] for m in original['models']}
        seen.add(by_id.get(original['judge']['model'], {}).get('canonical_slug') or original['judge']['model'])
        old_ids = {m['model'] for m in original['models']} | {original['judge']['model']}
        added = []
        for name in model_ids:
            model = by_id.get(name)
            if not model:
                raise ValueError(f'model absent from catalog: {name}')
            arch, prices = model.get('architecture', {}), model['pricing']
            ip, op = float(prices.get('prompt', 0)) * 1e6, float(prices.get('completion', 0)) * 1e6
            canonical = model.get('canonical_slug') or name
            if (name in old_ids or canonical in seen or '/' not in name or ':' in name
                    or name.endswith('-latest') or name.startswith(('~', 'openrouter/', 'stealth/'))
                    or SPECIALIST.search(name) or arch.get('output_modalities') != ['text']
                    or 'text' not in arch.get('input_modalities', [])
                    or 'max_tokens' not in model.get('supported_parameters', [])
                    or not 0 < ip <= max_input_price or not 0 < op <= max_output_price
                    or float(prices.get('request', 0)) != 0):
                raise ValueError(f'model is duplicate, judge, unsuitable, or exceeds price ceiling: {name}')
            seen.add(canonical)
            provider = deepcopy(original['provider'])
            provider['max_price'] = {'prompt': min(max_input_price, ip * 1.1),
                                     'completion': min(max_output_price, op * 1.1), 'request': 0}
            added.append({'model': name, 'name': model['name'], 'canonical_slug': canonical,
                          'catalog_pricing': prices, 'options': reasoning_options(model), 'provider': provider})
        inherited = json.loads((source / 'schedule.json').read_text(encoding='utf-8'))
        entries = deepcopy(ledger['entries'])
        budget = sum(e['accounted_cost'] for e in entries.values()) + additional_budget_usd
        if budget > 20:
            raise ValueError('imported reservations plus additional budget must not exceed $20')
        plan = deepcopy(original)
        plan.update(models=deepcopy(original['models']) + added, budget_usd=budget,
                    max_requests=len(entries) + len(added) * len(original['scenarios']) * 5,
                    created_at=datetime.now(timezone.utc).isoformat(), cohort_policy='fixed_model_expansion',
                    generation_source={'path': os.path.relpath(source, output), 'plan_hash': digest(original),
                                       'ledger_hash': digest(ledger), 'reuse_mode': 'generations_and_judge_checks'},
                    baseline={'n_scenarios': len(original['scenarios']), 'n_models': len(original['models']),
                              'ranks': {r['model']: r['rank'] for r in verified['rows']}},
                    model_expansion={'added_models': model_ids, 'anchor_models': anchors,
                                     'inherited_schedule': inherited, 'additional_budget_usd': additional_budget_usd,
                                     'catalog_hash': digest(catalog)},
                    schedule='Retain all prior pairs; each new model gets two seeded complete prior-model opponents per scenario. No outcome-based opponent selection.',
                    selection='Explicit catalog-validated model enrollment, exact canonical deduplication; same frozen scenarios, prompts, token limits and judge.')
        output.mkdir(parents=True); (output / 'raw').mkdir()
        atomic_json(output / 'plan.json', plan)
        atomic_json(output / 'schedule.json', screen_schedule(plan, {}))
        atomic_json(output / 'requests.json', {'plan_hash': digest(plan), 'budget_usd': budget,
                                              'entries': entries, 'imported_tasks': sorted(entries)})
        atomic_json(output / 'catalog-added.json', [by_id[name] for name in model_ids])
        for task_id in entries:
            path = source / 'raw' / (digest(task_id) + '.json')
            if path.exists():
                shutil.copyfile(path, output / 'raw' / path.name)
        return plan


def run_screen(root, plan, *, workers=12, bootstrap=100, transport=None, request_interval=1):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    plan_path = root / 'plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text(encoding='utf-8')) != plan:
        raise ValueError('frozen screen plan changed')
    if not 1 <= workers <= 16:
        raise ValueError('workers must be between 1 and 16')
    if not np.isfinite(request_interval) or not 0 <= request_interval <= 60:
        raise ValueError('request interval must be between 0 and 60 seconds')
    if transport is None and not os.environ.get('OPENROUTER_API_KEY'):
        raise ValueError('OPENROUTER_API_KEY is not configured')
    atomic_json(plan_path, plan)
    scenarios = [Scenario.model_validate(s) for s in plan['scenarios']]
    responses, checks, schedule = {}, {}, []
    with run_lock(root):
        if plan.get('cohort_policy') in {'fixed_prior_complete', 'fixed_model_expansion'}:
            schedule = screen_schedule(plan, {})
            saved_schedule = root / 'schedule.json'
            if not saved_schedule.exists() or json.loads(saved_schedule.read_text(encoding='utf-8')) != schedule:
                raise ValueError('frozen comparison schedule changed or is missing')
        client = BudgetClient(root, plan, transport=transport,
                              request_interval=request_interval if transport is None else 0)
        def publish(phase, samples=0):
            report = analyze(plan, responses, schedule, checks, client.totals(), phase=phase, bootstrap=samples)
            report['campaign_cost'] = campaign_totals(root, plan, client.state)
            atomic_json(root / 'wide-report.json', report)
            print(json.dumps({k: report[k] for k in ['phase', 'n_generation_successes', 'n_models_complete',
                                                    'n_judge_checks_saved', 'n_accepted_pairs', 'cost']}), flush=True)
            return report
        def call(task):
            try:
                return client.request(*task)
            except BudgetStop:
                return {'status': 'budget_not_sent', 'task_id': task[0]}
        publish('generating')
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for scenario in scenarios:
                specs = plan['models']
                tasks = [(f'g:{scenario.scenario_id}:{m["model"]}', generation_payload(plan, m, scenario)) for m in specs]
                for model, record in zip(specs, pool.map(call, tasks)):
                    responses[(scenario.scenario_id, model['model'])] = record
                publish('generating')
            complete = scheduled_cohort(plan, responses)
            if len(complete) >= 3:
                schedule = screen_schedule(plan, responses)
                if (root / 'schedule.json').exists() and json.loads((root / 'schedule.json').read_text(encoding='utf-8')) != schedule:
                    raise ValueError('saved comparison schedule changed')
                atomic_json(root / 'schedule.json', schedule)
                for scenario in scenarios:
                    pairs = [p for p in schedule if p['scenario_id'] == scenario.scenario_id and pair_available(p, responses)]
                    for p in schedule:
                        if p['scenario_id'] == scenario.scenario_id and not pair_available(p, responses):
                            for reverse in (False, True):
                                checks[(p['pair_id'], reverse)] = {'status': 'missing_candidate'}
                    tasks = [(f'j:{p["pair_id"]}:{int(reverse)}', judge_payload(plan, p, scenario, responses, reverse))
                             for p in pairs for reverse in (False, True)]
                    keys = [(p['pair_id'], reverse) for p in pairs for reverse in (False, True)]
                    for key, record in zip(keys, pool.map(call, tasks)):
                        checks[key] = record
                    publish('judging')
        return publish('complete', bootstrap)
