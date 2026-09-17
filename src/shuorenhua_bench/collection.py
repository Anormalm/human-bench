from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .dataset import read_jsonl
from .leaderboard.aggregate import _clusters
from .schemas import Pair, PairwiseJudgment, Response, Scenario
from .statistics.davidson_bt import comparison_components
from .study import import_judgments, sha256_file, verify_study


def _components(pairs, response_systems, systems):
    # Only graph structure is used here; no outcome is created or fitted.
    edges = [(response_systems[p.response_a], response_systems[p.response_b], None) for p in pairs]
    found = {s for a, b, _ in edges for s in (a, b)}
    return comparison_components(edges) + [[s] for s in sorted(systems - found)]


def collection_snapshot(study, files=()):
    """Validate returned exports and describe coverage, without selecting or fitting votes."""
    study = Path(study).resolve()
    files = [Path(p).resolve() for p in files]
    manifest = verify_study(study)
    manifest_hash = sha256_file(study / 'manifest.json')
    hashes = {str(p): sha256_file(p) for p in files}
    judgments, duplicates = import_judgments(study, files)
    scenarios = read_jsonl(study / 'private/scenarios.jsonl', Scenario)
    responses = read_jsonl(study / 'private/responses.jsonl', Response)
    pairs = read_jsonl(study / 'private/pairs.jsonl', Pair)
    mapping = json.loads((study / 'private/response_map.json').read_text(encoding='utf-8'))
    pair_map = {p.pair_id: p for p in pairs}
    target = manifest['judgments_per_pair']
    if target < 2 or not pairs or len(pair_map) != manifest['n_pairs']:
        raise ValueError('invalid frozen comparison coverage')
    planned, expected = {}, defaultdict(set)
    for assignment, relative in manifest['assignments'].items():
        packet = json.loads((study / relative).read_text(encoding='utf-8'))
        if packet['assignment_id'] != assignment or packet['study_id'] != manifest['study_id']:
            raise ValueError('assignment identity differs from frozen study')
        planned[assignment] = set()
        for item in packet['items']:
            pair = pair_map.get(item['pair_id'])
            shown = {mapping.get(item['response_a']), mapping.get(item['response_b'])}
            if (pair is None or shown != {pair.response_a, pair.response_b} or
                    item['scenario_id'] != pair.scenario_id or item['pair_id'] in planned[assignment]):
                raise ValueError('assignment comparison differs from frozen registry')
            planned[assignment].add(item['pair_id'])
            expected[item['pair_id']].add(assignment)
    total = sum(len(ids) for ids in planned.values())
    if (any(len(expected[p.pair_id]) != target for p in pairs) or
            total != manifest['n_planned_judgments'] or len(planned) != manifest['n_assignments']):
        raise ValueError('frozen assignment coverage does not match the study plan')
    received, votes = defaultdict(set), defaultdict(set)
    for j in judgments:
        received[j.assignment_id].add(j.pair_id)
        votes[j.pair_id].add(j.assignment_id)
    file_rows = []
    assignment_files = defaultdict(list)
    for i, file in enumerate(files, 1):
        rows = read_jsonl(file, PairwiseJudgment)
        assignments = sorted({j.assignment_id for j in rows})
        file_rows.append({'file_id': i, 'name': file.name, 'sha256': hashes[str(file)],
                          'n_records': len(rows), 'assignments': assignments})
        for assignment in assignments:
            assignment_files[assignment].append(i)
    assignments = []
    for name, ids in sorted(planned.items()):
        missing = sorted(ids - received[name])
        assignments.append({
            'assignment_id': name, 'n_planned': len(ids), 'n_received': len(received[name]),
            'n_remaining': len(missing), 'missing_pair_ids': missing, 'file_ids': assignment_files[name],
            'status': 'not_required' if not ids else 'complete' if not missing else
                      'partial' if received[name] else 'not_returned',
        })
    response_systems = {r.response_id: r.system_id for r in responses}
    systems = {r.system_id for r in responses if r.track == manifest['track']}
    planned_graph = _components(pairs, response_systems, systems)
    received_graph = _components(judgments, response_systems, systems)
    pair_rows, complete_pairs = [], []
    smap = {s.scenario_id: s for s in scenarios}
    for p in pairs:
        enough = len(votes[p.pair_id]) >= target
        if enough:
            complete_pairs.append(p)
        pair_rows.append({
            'pair_id': p.pair_id, 'scenario_id': p.scenario_id, 'genre': smap[p.scenario_id].genre,
            'systems': sorted((response_systems[p.response_a], response_systems[p.response_b])),
            'n_required': target, 'n_received': len(votes[p.pair_id]),
            'missing_assignments': sorted(expected[p.pair_id] - votes[p.pair_id]),
            'status': 'complete' if enough else 'partial' if votes[p.pair_id] else 'not_started',
        })
    fully_rated_graph = _components(complete_pairs, response_systems, systems)
    clusters = _clusters(scenarios, pairs)
    groups_with_returns = {clusters[j.scenario_id] for j in judgments}
    missing_cells = manifest.get('input_coverage', {}).get('missing_system_scenario_cells', [])
    all_collected = len(judgments) == total
    can_fit = len(systems) >= 2 and len(received_graph) == 1
    ready = all_collected and can_fit and not missing_cells
    blockers = []
    if not all_collected:
        blockers.append(f'{total - len(judgments)} assigned judgments are still missing.')
    if not can_fit:
        blockers.append('Returned comparisons do not connect every system; a global ranking is unavailable.')
    if missing_cells:
        blockers.append(f'{len(missing_cells)} system/scenario cells have no generated response.')
    warnings = [
        'Completion describes returned assignments, not statistical separation, rater eligibility or human validity.',
        'Assigned pseudonyms count as distinct rater IDs; actual participant independence requires recruitment records.',
        'This snapshot does not fit or rank models and does not filter votes by speed, confidence or agreement.',
        'Unreturned work is not an abstention or tie. Conflicting exports must be resolved before producing a snapshot.',
    ]
    if len(groups_with_returns) < 30:
        warnings.append('Fewer than 30 scenario-family groups have returned judgments; uncertainty remains exploratory.')
    demo = manifest['evidence_status'] == 'synthetic_demo'
    if demo:
        warnings.append('Synthetic practice study: these counts are not human evidence.')
    genre_rows = []
    for genre in sorted({s.genre for s in scenarios}):
        relevant = [p for p in pair_rows if p['genre'] == genre]
        genre_rows.append({'genre': genre, 'n_pairs': len(relevant),
                           'n_complete_pairs': sum(p['status'] == 'complete' for p in relevant),
                           'n_planned_judgments': sum(p['n_required'] for p in relevant),
                           'n_received_judgments': sum(p['n_received'] for p in relevant)})
    # Bind the snapshot to the exact inputs that were checked, including cumulative exports.
    if any(sha256_file(Path(p)) != h for p, h in hashes.items()):
        raise ValueError('an export changed during validation; try again with stable files')
    if sha256_file(study / 'manifest.json') != manifest_hash or verify_study(study) != manifest:
        raise ValueError('the frozen study changed during validation')
    return {
        'schema_version': '0.5', 'report_kind': 'collection_status',
        'created_at': datetime.now(timezone.utc).isoformat(), 'study_id': manifest['study_id'],
        'evidence_kind': 'synthetic' if demo else 'human',
        'status': 'ready_for_analysis' if ready else 'collection_complete_design_incomplete'
                  if all_collected else 'awaiting_returns' if not judgments else 'collection_in_progress',
        'sample': {'n_assignments': len(assignments),
                   'n_assignments_complete': sum(a['status'] == 'complete' for a in assignments),
                   'n_assignments_partial': sum(a['status'] == 'partial' for a in assignments),
                   'n_assignments_not_returned': sum(a['status'] == 'not_returned' for a in assignments),
                   'n_planned_judgments': total, 'n_received_judgments': len(judgments),
                   'n_human_judgments': 0 if demo else len(judgments),
                   'n_remaining_judgments': total - len(judgments),
                   'n_pairs': len(pairs), 'n_complete_pairs': len(complete_pairs),
                   'n_scenarios_planned': len(scenarios),
                   'n_scenarios_with_returns': len({j.scenario_id for j in judgments}),
                   'n_groups_planned': len(set(clusters.values())),
                   'n_groups_with_returns': len(groups_with_returns)},
        'readiness': {'all_assigned_judgments_returned': all_collected,
                      'can_fit_global_ranking_on_returned_comparisons': can_fit,
                      'ready_for_planned_analysis': ready, 'blockers': blockers,
                      'missing_system_scenario_cells': missing_cells,
                      'planned_components': planned_graph, 'returned_components': received_graph,
                      'fully_rated_components': fully_rated_graph},
        'assignments': assignments, 'pairs': pair_rows, 'genres': genre_rows,
        'imports': {'files': file_rows, 'identical_duplicate_rows_ignored': duplicates,
                    'empty_files': [f['file_id'] for f in file_rows if not f['n_records']]},
        'provenance': {'study_manifest_sha256': manifest_hash, 'study_hashes': manifest['sha256'],
                       'analysis_version': '0.5.0', 'offline': True},
        'warnings': warnings,
    }
