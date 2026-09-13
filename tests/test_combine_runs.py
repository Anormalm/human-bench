import json

import pytest
from test_model_run import config, decision, inputs, stub_http

from shuorenhua_bench.benchmark_run import run_benchmark
from shuorenhua_bench.combine_runs import combine_runs, preference_sensitivity
from shuorenhua_bench.judge_audit import load_judge_run
from shuorenhua_bench.study import verify_study


def batches(tmp_path, monkeypatch, *, unstable_actions=False):
    def responder(payload, n):
        if payload['model'] == 'judge':
            prompt = json.loads(payload['messages'][1]['content'])
            a_first = prompt['candidate_A'] == 'Generated a'
            # Preference is invariant to display. In one mode, an action depends on display.
            return json.dumps(decision('A' if a_first else 'B',
                                       action_a='revise' if unstable_actions and a_first else 'send'))
        return 'Generated ' + payload['model']
    calls = stub_http(monkeypatch, responder)
    paths = []
    for i in range(2):
        scenario = inputs(1)[0][0].model_copy(update={
            'scenario_id': f'batch-{i}', 'context': f'Independent scenario {i}',
            'semantic_cluster_id': 'shared-family'})
        path = tmp_path / f'run-{i}'
        run_benchmark([scenario], config(), path, execute=True, max_requests=6,
                      seed=i + 1, bootstrap_samples=0)
        paths.append(path)
    return paths, calls


def test_pooling_is_offline_one_judge_and_clusters_across_batches(tmp_path, monkeypatch):
    paths, calls = batches(tmp_path, monkeypatch)
    before = len(calls)
    source_bytes = [(p / 'judge/observations.json').read_bytes() for p in paths]
    out = tmp_path / 'pooled'
    result = combine_runs(paths, out, bootstrap_samples=0, raters=3)
    assert len(calls) == before and result['n_scenarios'] == 2
    report = json.loads((out / 'report.json').read_text())
    assert report['sample']['n_model_judges'] == 1
    assert report['sample']['n_annotators'] == 0
    assert report['uncertainty']['n_independent_groups'] == 1
    assert report['systems']['a']['wins'] == 2
    assert report['systems']['b']['losses'] == 2
    audit = json.loads((out / 'judge-audit.json').read_text())
    assert len(audit['judges']) == 1 and audit['n_pairs'] == 2
    assert audit['judges']['judge-1']['human_comparison']['n_unresolved_reference_pairs'] == 2
    assert all(p['candidate_a']['system'] == 'a' for p in audit['pairs'])
    assert all(p['judges']['judge-1']['stable_preference'] == 'A' for p in audit['pairs'])
    assert source_bytes == [(p / 'judge/observations.json').read_bytes() for p in paths]
    assert verify_study(out / 'human-study')['judgments_per_pair'] == 3
    with pytest.raises(ValueError, match='new directory'):
        combine_runs(paths, out)


def test_stable_preference_diagnostic_does_not_relax_primary_or_invent_actions(tmp_path, monkeypatch):
    paths, _ = batches(tmp_path, monkeypatch, unstable_actions=True)
    result = preference_sensitivity([load_judge_run(p) for p in paths])
    assert result['primary_full_consistency']['n_pairs'] == 0
    assert result['primary_full_consistency']['status'] == 'withheld'
    assert result['diagnostic_stable_preference_only']['systems']['a']['wins'] == 2
    assert len(result['added_diagnostic_pairs']) == 2
    assert not result['primary_rule_changed'] and result['point_order_changed'] is None
    assert result['head_to_head_exclusion_bounds'][0]['a_score_range_over_all_planned'] == [0, 1]
    assert 'direct_use_rate' not in result['diagnostic_stable_preference_only']['systems']['a']
    out = tmp_path / 'pooled'
    combine_runs(paths, out, bootstrap_samples=0, raters=3)
    report = json.loads((out / 'report.json').read_text())
    assert report['ranking_status'] == 'withheld' and report['sample']['n_judgments'] == 0


def test_duplicate_or_overlapping_batches_rejected(tmp_path, monkeypatch):
    paths, _ = batches(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='distinct'):
        combine_runs([paths[0], paths[0]], tmp_path / 'invalid')
    import shutil
    duplicate = tmp_path / 'copied-run'
    shutil.copytree(paths[0], duplicate)
    with pytest.raises(ValueError, match='overlapping'):
        combine_runs([paths[0], duplicate], tmp_path / 'invalid')
    assert not (tmp_path / 'invalid').exists()


def test_changed_candidate_protocol_rejected(tmp_path, monkeypatch):
    paths, _ = batches(tmp_path, monkeypatch)
    file = paths[1] / 'run.json'
    data = json.loads(file.read_text())
    data['config']['system_prompt'] = 'A different prompt'
    file.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='configurations must be identical'):
        combine_runs(paths, tmp_path / 'invalid')


def test_candidate_fingerprint_checked_even_when_both_configs_match(tmp_path, monkeypatch):
    paths, _ = batches(tmp_path, monkeypatch)
    for path in paths:
        file = path / 'run.json'
        data = json.loads(file.read_text())
        data['config']['system_prompt'] = 'A different prompt'
        file.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='configuration or input changed'):
        combine_runs(paths, tmp_path / 'invalid')


def test_incomplete_batch_rejected(tmp_path, monkeypatch):
    paths, _ = batches(tmp_path, monkeypatch)
    file = paths[1] / 'judge/observations.json'
    data = json.loads(file.read_text())
    data['records'].pop(next(iter(data['records'])))
    file.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='complete both judge orders'):
        combine_runs(paths, tmp_path / 'invalid')
