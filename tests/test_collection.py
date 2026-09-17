import json
import sys

import pytest
from test_v03 import response, scenario

from shuorenhua_bench.cli import main
from shuorenhua_bench.collection import collection_snapshot
from shuorenhua_bench.dataset import write_jsonl
from shuorenhua_bench.schemas import PairwiseJudgment
from shuorenhua_bench.study import prepare_study, sha256_file


def make_study(tmp_path, *, demo=False, disconnected=False):
    scenarios = [scenario('s1', semantic_cluster_id='shared'),
                 scenario('s2', semantic_cluster_id='shared'), scenario('s3')]
    responses = [response(f'{s.scenario_id}:{model}', model, s.scenario_id)
                 for s in scenarios for model in ('A', 'B', 'C')]
    if disconnected:
        scenarios = scenarios[:2]
        responses = [response(f'{s.scenario_id}:{model}', model, s.scenario_id)
                     for s, models in zip(scenarios, [('A', 'B'), ('C', 'D')]) for model in models]
    study = tmp_path / 'study'
    prepare_study(scenarios, responses, study, raters=3, demo=demo)
    return study


def export_rows(study, assignment='rater-001', *, demo=False):
    packet = json.loads((study / f'public/{assignment}.json').read_text(encoding='utf-8'))
    return [PairwiseJudgment(
        pair_id=p['pair_id'], scenario_id=p['scenario_id'], response_a=p['response_a'],
        response_b=p['response_b'], annotator_id=assignment, assignment_id=assignment,
        study_id=packet['study_id'], preference='A', action_a='send', action_b='revise',
        confidence=3, evidence_kind='synthetic' if demo else 'human') for p in packet['items']]


def test_empty_snapshot_retains_full_plan_and_unobserved_systems(tmp_path):
    report = collection_snapshot(make_study(tmp_path))
    assert report['status'] == 'awaiting_returns'
    assert report['sample']['n_planned_judgments'] == 27
    assert report['sample']['n_received_judgments'] == report['sample']['n_human_judgments'] == 0
    assert report['sample']['n_groups_planned'] == 2
    assert report['readiness']['returned_components'] == [['A'], ['B'], ['C']]
    assert all(len(p['missing_assignments']) == 3 for p in report['pairs'])
    assert all(a['status'] == 'not_returned' for a in report['assignments'])
    assert 'ability' not in json.dumps(report)


def test_cumulative_exports_deduplicate_without_inflating_rater_coverage(tmp_path):
    study = make_study(tmp_path)
    rows = export_rows(study)
    first, second = tmp_path / 'partial.jsonl', tmp_path / 'complete.jsonl'
    write_jsonl(first, rows[:2]); write_jsonl(second, rows)
    report = collection_snapshot(study, [first, second])
    assert report['imports']['identical_duplicate_rows_ignored'] == 2
    assert report['sample']['n_received_judgments'] == 9
    assert report['sample']['n_assignments_complete'] == 1
    assert report['sample']['n_complete_pairs'] == 0
    assert report['readiness']['can_fit_global_ranking_on_returned_comparisons']
    assert not report['readiness']['ready_for_planned_analysis']
    assert report['readiness']['fully_rated_components'] == [['A'], ['B'], ['C']]
    assert report['assignments'][0]['file_ids'] == [1, 2]
    assert sum(g['n_received_judgments'] for g in report['genres']) == 9
    partial = collection_snapshot(study, [first])
    assert partial['sample']['n_assignments_partial'] == 1
    assert partial['assignments'][0]['n_remaining'] == 7


def test_conflicting_cumulative_returns_are_rejected(tmp_path):
    study = make_study(tmp_path)
    row = export_rows(study)[0]
    first, changed = tmp_path / 'first.jsonl', tmp_path / 'changed.jsonl'
    write_jsonl(first, [row]); write_jsonl(changed, [row.model_copy(update={'preference': 'B'})])
    with pytest.raises(ValueError, match='conflicting duplicate'):
        collection_snapshot(study, [first, changed])


def test_fully_rated_subset_does_not_hide_an_unobserved_model(tmp_path):
    study = make_study(tmp_path)
    mapping = json.loads((study / 'private/response_map.json').read_text())
    files = []
    for i in range(1, 4):
        rows = export_rows(study, f'rater-{i:03}')
        rows = [r for r in rows if {mapping[r.response_a][-1], mapping[r.response_b][-1]} == {'A', 'B'}]
        file = tmp_path / f'export-{i}.jsonl'; write_jsonl(file, rows); files.append(file)
    report = collection_snapshot(study, files)
    assert report['sample']['n_complete_pairs'] == 3
    assert report['readiness']['fully_rated_components'] == [['A', 'B'], ['C']]
    assert not report['readiness']['can_fit_global_ranking_on_returned_comparisons']


@pytest.mark.parametrize('demo', [False, True])
def test_complete_collection_retains_evidence_kind_and_does_not_declare_winner(tmp_path, demo):
    study = make_study(tmp_path, demo=demo)
    files = []
    for i in range(1, 4):
        file = tmp_path / f'export-{i}.jsonl'
        write_jsonl(file, export_rows(study, f'rater-{i:03}', demo=demo)); files.append(file)
    report = collection_snapshot(study, files)
    assert report['status'] == 'ready_for_analysis'
    assert report['sample']['n_complete_pairs'] == 9
    assert report['sample']['n_remaining_judgments'] == 0
    assert report['sample']['n_human_judgments'] == (0 if demo else 27)
    assert report['readiness']['ready_for_planned_analysis']
    assert 'ranking' not in report and any('not statistical separation' in w for w in report['warnings'])


def test_completed_disconnected_design_is_not_ready(tmp_path):
    study = make_study(tmp_path, disconnected=True)
    files = []
    for i in range(1, 4):
        file = tmp_path / f'export-{i}.jsonl'
        write_jsonl(file, export_rows(study, f'rater-{i:03}')); files.append(file)
    report = collection_snapshot(study, files)
    assert report['readiness']['all_assigned_judgments_returned']
    assert report['status'] == 'collection_complete_design_incomplete'
    assert not report['readiness']['ready_for_planned_analysis']
    assert report['readiness']['missing_system_scenario_cells']


def test_model_votes_cannot_enter_human_collection(tmp_path):
    study = make_study(tmp_path)
    file = tmp_path / 'model.jsonl'
    write_jsonl(file, [export_rows(study)[0].model_copy(update={'evidence_kind': 'model'})])
    with pytest.raises(ValueError, match='must be labeled human'):
        collection_snapshot(study, [file])


def test_cli_directory_snapshot_preserves_previous_snapshot(tmp_path, monkeypatch):
    study = make_study(tmp_path)
    returns = tmp_path / 'returns'; returns.mkdir()
    write_jsonl(returns / 'partial.jsonl', export_rows(study)[:1])
    (returns / 'empty.jsonl').write_text('')
    output = tmp_path / 'collection.json'
    monkeypatch.setattr(sys, 'argv', ['shuorenhua', 'collection', '--study', str(study),
                                    '--exports-dir', str(returns), '--output', str(output)])
    main(); before = output.read_bytes()
    report = json.loads(before)
    assert report['sample']['n_received_judgments'] == 1
    assert len(report['imports']['empty_files']) == 1
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2 and output.read_bytes() == before


def test_changed_input_during_validation_is_rejected(tmp_path, monkeypatch):
    from shuorenhua_bench import collection
    study = make_study(tmp_path)
    file = tmp_path / 'partial.jsonl'; write_jsonl(file, export_rows(study)[:1])
    original = collection.import_judgments
    def changing(study, files):
        result = original(study, files)
        file.write_bytes(file.read_bytes() + b'\n')
        return result
    monkeypatch.setattr(collection, 'import_judgments', changing)
    with pytest.raises(ValueError, match='export changed during validation'):
        collection.collection_snapshot(study, [file])


def test_duplicate_frozen_assignment_items_are_rejected(tmp_path):
    study = make_study(tmp_path)
    file = study / 'public/rater-001.json'
    packet = json.loads(file.read_text(encoding='utf-8')); packet['items'].append(packet['items'][0])
    file.write_text(json.dumps(packet), encoding='utf-8')
    path = study / 'manifest.json'; manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['sha256']['public/rater-001.json'] = sha256_file(file)
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='comparison differs from frozen registry'):
        collection_snapshot(study)


def test_collection_endpoint_remains_researcher_only(tmp_path, monkeypatch):
    from test_rater_site import request

    from api.index import app
    from api.rater import create_rater_app
    from shuorenhua_bench.rater_site import prepare_rater_site
    from shuorenhua_bench.study import write_json

    study = make_study(tmp_path)
    report = tmp_path / 'collection.json'
    write_json(report, collection_snapshot(study))
    monkeypatch.setenv('SHUORENHUA_COLLECTION', str(report))
    result = request(app, '/api/collection')
    assert result['status'] == '200 OK'
    assert json.loads(result['body'])['report_kind'] == 'collection_status'
    rater = tmp_path / 'rater-site'
    prepare_rater_site(study, rater)
    assert request(create_rater_app(rater), '/api/collection')['status'] == '404 Not Found'
