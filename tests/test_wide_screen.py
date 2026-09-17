import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_v03 import scenario

from shuorenhua_bench.model_judge import atomic_json
from shuorenhua_bench.wide_screen import (
    BudgetClient,
    BudgetStop,
    analyze,
    cycle_schedule,
    make_plan,
    prepare_rejudge,
    reanalyze_screen,
    run_screen,
    select_models,
)


def catalog():
    return [{'id': name, 'name': name, 'canonical_slug': name, 'created': i,
             'architecture': {'input_modalities': ['text'], 'output_modalities': ['text']},
             'pricing': {'prompt': '.0000002', 'completion': '.000001'},
             'supported_parameters': ['max_tokens', 'structured_outputs']}
            for i, name in enumerate(['one/a', 'two/b', 'three/c', 'four/d', 'openai/gpt-5.6-luna'])]


def plan(budget=1):
    scenarios = [scenario('s1').model_copy(update={'genre': 'family'}),
                 scenario('s2').model_copy(update={'genre': 'work'})]
    return make_plan(catalog(), scenarios, 'test', count=4, scenario_count=2, budget_usd=budget)


def payload(p):
    return {'model': 'one/a', 'messages': [{'role': 'user', 'content': 'test'}],
            'max_tokens': 512, 'provider': p['provider']}


def response(text='ok', cost=.001, finish='stop'):
    result = {'choices': [{'message': {'content': text}, 'finish_reason': finish}], 'usage': {}}
    if cost is not None:
        result['usage']['cost'] = cost
    return result


def test_catalog_filters_and_canonical_deduplication():
    rows = catalog()
    duplicate = copy.deepcopy(rows[0]); duplicate['id'] = 'one/alias'; rows.append(duplicate)
    for name, price in [('one/pricey', '.01'), ('stealth/new', '.0000001'), ('one/a:free', '.0000001'),
                        ('one/safety-image', '.0000001')]:
        m = copy.deepcopy(rows[0]); m.update(id=name, canonical_slug=name); m['pricing']['prompt'] = price
        rows.append(m)
    selected = select_models(rows, 100)
    assert len(selected) == 4
    assert len({m['canonical_slug'] for m in selected}) == 4


def test_cycles_balance_degree_and_are_deterministic():
    names = [f'm{i}' for i in range(150)]
    rows = cycle_schedule(names, ['s1', 's2'], 123)
    assert rows == cycle_schedule(list(reversed(names)), ['s1', 's2'], 123)
    assert len(rows) == len({r['pair_id'] for r in rows}) == 300
    for s in ['s1', 's2']:
        assert all(sum(m in (r['model_a'], r['model_b']) for r in rows if r['scenario_id'] == s) == 2 for m in names)


def test_unknown_cost_retains_reservation_and_resume_never_repeats(tmp_path):
    p = plan()
    calls = []
    def send(body):
        calls.append(body); return response(cost=None, finish='length')
    client = BudgetClient(tmp_path, p, transport=send)
    first = client.request('task', payload(p))
    assert first['status'] == 'failed'
    assert client.totals()['charged_or_reserved_usd'] > 0
    reopened = BudgetClient(tmp_path, p, transport=send)
    assert reopened.request('task', payload(p)) == first
    assert len(calls) == 1
    assert reopened.totals()['unknown_cost_requests'] == 1


def test_parallel_reservations_prevent_oversubscription(tmp_path):
    p = plan(.035)
    client = BudgetClient(tmp_path, p, transport=lambda _: response(cost=None))
    def attempt(i):
        try:
            client.request(str(i), payload(p)); return True
        except BudgetStop:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        sent = list(pool.map(attempt, range(20)))
    assert 0 < sum(sent) < 20
    assert client.totals()['charged_or_reserved_usd'] <= p['budget_usd']


def test_crash_reservation_is_not_reissued(tmp_path):
    p = plan()
    client = BudgetClient(tmp_path, p, transport=lambda _: pytest.fail('must not send'))
    from shuorenhua_bench.model_judge import digest
    client.state['entries']['task'] = {'request_hash': digest(payload(p)), 'accounted_cost': .02,
                                       'reported_cost': None, 'status': 'reserved'}
    atomic_json(client.path, client.state)
    assert client.request('task', payload(p))['status'] == 'unknown_after_interruption'


def test_cached_payload_and_raw_tampering_rejected(tmp_path):
    p = plan(); client = BudgetClient(tmp_path, p, transport=lambda _: response())
    client.request('task', payload(p))
    changed = payload(p); changed['messages'][0]['content'] = 'changed'
    with pytest.raises(ValueError, match='input changed'):
        client.request('task', changed)
    raw = next((tmp_path/'raw').glob('*.json'))
    data = json.loads(raw.read_text()); data['text'] = 'tampered'; atomic_json(raw, data)
    with pytest.raises(ValueError, match='raw record changed'):
        client.request('task', payload(p))


def test_price_policy_cannot_be_removed(tmp_path):
    p = plan(); client = BudgetClient(tmp_path, p, transport=lambda _: pytest.fail('must not send'))
    body = payload(p); body.pop('provider')
    with pytest.raises(ValueError, match='price ceilings'):
        client.request('task', body)


def test_missing_ledger_cannot_reset_spending_history(tmp_path):
    p = plan(); client = BudgetClient(tmp_path, p, transport=lambda _: response())
    client.request('task', payload(p)); client.path.unlink()
    with pytest.raises(ValueError, match='ledger missing'):
        BudgetClient(tmp_path, p, transport=lambda _: pytest.fail('must not send'))


def test_rate_limit_cools_down_new_requests_without_retry(tmp_path, monkeypatch):
    from shuorenhua_bench import wide_screen
    ticks = [0.0]; sent = []
    monkeypatch.setattr(wide_screen.time, 'monotonic', lambda: ticks[0])
    monkeypatch.setattr(wide_screen.time, 'sleep', lambda delay: ticks.__setitem__(0, ticks[0] + delay))
    def send(body):
        sent.append(ticks[0])
        return {'error': {'http_status': 429}} if len(sent) == 1 else response()
    p = plan(); client = BudgetClient(tmp_path, p, transport=send, request_interval=1)
    client.request('first', payload(p)); client.request('first', payload(p))
    client.request('second', payload(p)); client.request('third', payload(p))
    assert sent == [0, 30, 31]
    assert client.totals()['unknown_cost_requests'] == 1


def test_workbench_serves_only_configured_wide_report(tmp_path, monkeypatch):
    from test_rater_site import request

    from api.index import app
    monkeypatch.delenv('SHUORENHUA_WIDE_REPORT', raising=False)
    assert request(app, '/api/wide-report')['status'] == '503 Service Unavailable'
    report = tmp_path / 'wide.json'; atomic_json(report, {'report_kind': 'wide_screen'})
    monkeypatch.setenv('SHUORENHUA_WIDE_REPORT', str(report))
    result = request(app, '/api/wide-report')
    assert result['status'] == '200 OK' and json.loads(result['body'])['report_kind'] == 'wide_screen'
    assert b'wide.js' in request(app, '/wide')['body']
    assert request(app, '/api/wide-report', 'POST')['status'] == '405 Method Not Allowed'


def test_synthetic_transport_complete_screen_and_zero_call_resume(tmp_path):
    p = plan()
    calls = []
    def send(body):
        calls.append(body)
        if 'response_format' in body:
            return response(json.dumps({'preference': 'tie', 'action_a': 'send', 'action_b': 'send',
                                         'confidence': 3, 'rationale': 'synthetic fixture'}))
        return response('synthetic candidate')
    report = run_screen(tmp_path, p, workers=4, bootstrap=0, transport=send)
    assert len(calls) == 24 and report['n_models_ranked'] == 4
    assert report['n_accepted_pairs'] == 8
    assert all(r['ties'] == 4 and r['wins'] == r['losses'] == 0 for r in report['rows'])
    run_screen(tmp_path, p, workers=4, bootstrap=0, transport=send)
    assert len(calls) == 24
    rebuilt = reanalyze_screen(tmp_path, bootstrap=0)
    assert rebuilt['rows'] == report['rows']
    assert rebuilt['cost'] == report['cost']
    assert rebuilt['integrity']['verified_raw_records'] == 24
    assert rebuilt['integrity']['not_sent_judge_checks'] == 0
    assert len(calls) == 24

    # Recomputing an altered raw file's own checksum must not bypass the ledger.
    from shuorenhua_bench.model_judge import digest
    path = next((tmp_path / 'raw').glob('*.json'))
    raw = json.loads(path.read_text()); raw['body']['usage']['cost'] = .9
    raw['sha256'] = digest({k: v for k, v in raw.items() if k != 'sha256'})
    atomic_json(path, raw)
    with pytest.raises(ValueError, match='raw evidence changed'):
        reanalyze_screen(tmp_path, bootstrap=0)


def test_failures_are_unranked_not_losses():
    p = plan()
    report = analyze(p, {}, [], {}, {}, phase='complete')
    assert report['n_models_ranked'] == report['n_models_complete'] == 0
    assert all(r['losses'] == 0 and r['rank'] is None for r in report['rows'])


def test_offline_reanalysis_refuses_missing_completed_evidence(tmp_path):
    p = plan()
    run_screen(tmp_path, p, workers=2, bootstrap=0, transport=lambda _: response())
    next((tmp_path / 'raw').glob('*.json')).unlink()
    with pytest.raises(ValueError, match='no raw evidence'):
        reanalyze_screen(tmp_path, bootstrap=0)


def test_offline_reanalysis_cannot_overlap_a_live_run(tmp_path):
    from shuorenhua_bench.benchmark_run import run_lock
    with run_lock(tmp_path), pytest.raises(ValueError, match='run is locked'):
        reanalyze_screen(tmp_path, bootstrap=0)


def test_disconnected_model_has_no_cross_component_rank():
    p = plan()
    names = [m['model'] for m in p['models']]
    responses = {(s['scenario_id'], m): {'status': 'success'} for s in p['scenarios'] for m in names}
    schedule = cycle_schedule(names[:3], ['s1', 's2'], p['seed'])
    checks = {(r['pair_id'], reverse): {'status': 'success', 'text': json.dumps({
        'preference': 'tie', 'action_a': 'send', 'action_b': 'send', 'confidence': 3, 'rationale': 'fixture'})}
        for r in schedule for reverse in (False, True)}
    report = analyze(p, responses, schedule, checks, {}, phase='complete', bootstrap=20)
    assert report['n_models_ranked'] == 3
    isolated = next(r for r in report['rows'] if r['model'] == names[3])
    assert isolated['rank'] is None and isolated['losses'] == 0
    assert all(r['rank_interval'] is None for r in report['rows'])  # All-tie fits collapse.


def test_separate_provider_pass_reuses_generations_but_no_judge_votes(tmp_path):
    source, destination = tmp_path / 'source', tmp_path / 'rerouted'
    p = plan()
    def send(body):
        return response(json.dumps({'preference': 'tie', 'action_a': 'send', 'action_b': 'send',
                                    'confidence': 3, 'rationale': 'fixture'})) if 'response_format' in body else response()
    run_screen(source, p, transport=send, bootstrap=0)
    before = (source / 'plan.json').read_bytes()
    rerouted = prepare_rejudge(source, destination, budget_usd=1, judge_provider='openai')
    assert (source / 'plan.json').read_bytes() == before
    calls = []
    def reroute(body):
        calls.append(body)
        assert body['model'] == p['judge']['model'] and body['provider']['only'] == ['openai']
        return send(body)
    report = run_screen(destination, rerouted, transport=reroute, bootstrap=0)
    assert len(calls) == 16 and report['n_models_ranked'] == 4
    assert report['cost']['reused_requests'] == 8
    assert report['cost']['reused_reported_usd'] == pytest.approx(.008)
    rebuilt = reanalyze_screen(destination, bootstrap=0)
    assert rebuilt['rows'] == report['rows'] and rebuilt['cost'] == report['cost']
    assert rebuilt['campaign_cost']['attempts'] == 40
    assert rebuilt['campaign_cost']['reported_usd'] == pytest.approx(.04)
    assert rebuilt['campaign_cost']['n_studies'] == 2
    source_ledger = source / 'requests.json'
    changed = json.loads(source_ledger.read_text()); changed['entries'].clear()
    atomic_json(source_ledger, changed)
    with pytest.raises(ValueError, match='provenance changed'):
        reanalyze_screen(destination, bootstrap=0)
