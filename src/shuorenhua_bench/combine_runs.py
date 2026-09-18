from __future__ import annotations

import itertools
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

from .dataset import write_jsonl
from .judge_audit import _dataset_signature, compare_judges, load_judge_run
from .leaderboard.aggregate import _clusters
from .model_judge import automatic_report, digest, summarize_order_checks
from .response_runner import run as verify_generation
from .statistics.davidson_bt import comparison_components, fit_davidson
from .study import prepare_study, sha256_file, write_json
from .validation import require_valid


def _fit_preferences(rows, systems):
    comparisons = [(r['system_a'], r['system_b'], r['preference']) for r in rows]
    observed = {s for a, b, _ in comparisons for s in (a, b)}
    connected = observed == set(systems) and len(comparison_components(comparisons)) == 1
    fit = fit_davidson(comparisons, fit_position=False) if connected else None
    all_ties = bool(comparisons) and all(p == 'tie' for _, _, p in comparisons)
    usable = fit is not None and fit.converged
    return {
        'n_pairs': len(rows),
        'status': 'withheld' if not usable else 'no_separation' if all_ties else 'available',
        'point_order': sorted(systems, key=lambda s: (-fit.abilities[s], s))
                       if usable and not all_ties else None,
        'systems': {s: {
            'ability': fit.abilities[s] if usable else None,
            'wins': sum((a == s and p == 'A') or (b == s and p == 'B') for a, b, p in comparisons),
            'ties': sum(s in (a, b) and p == 'tie' for a, b, p in comparisons),
            'losses': sum((a == s and p == 'B') or (b == s and p == 'A') for a, b, p in comparisons),
        } for s in systems},
        'converged': bool(usable),
    }


def preference_sensitivity(runs):
    """Preferences only: never fabricate send/revise labels for rejected comparisons."""
    responses = {r.response_id: r for run in runs for r in run['responses']}
    systems = sorted({r.system_id for r in responses.values()})
    primary, stable, all_pairs = [], [], []
    for run in runs:
        pairs = {p.pair_id: p for p in run['pairs']}
        for check in run['rows']:
            pair = pairs[check['pair_id']]
            a, b = sorted((pair.response_a, pair.response_b))
            row = {'pair_id': pair.pair_id, 'scenario_id': pair.scenario_id,
                   'system_a': responses[a].system_id, 'system_b': responses[b].system_id,
                   'preference': check['stable_preference'], 'status': check['status']}
            all_pairs.append(row)
            if check['stable_preference'] is not None:
                stable.append(row)
            if check['accepted']:
                primary.append(row)
    primary_ids = {r['pair_id'] for r in primary}
    head_to_head = []
    for a, b in itertools.combinations(systems, 2):
        expected = [r for r in all_pairs if {r['system_a'], r['system_b']} == {a, b}]
        accepted = [r for r in expected if r['pair_id'] in primary_ids]
        wins = sum(r['preference'] == ('A' if r['system_a'] == a else 'B') for r in accepted)
        ties = sum(r['preference'] == 'tie' for r in accepted)
        missing = len(expected) - len(accepted)
        head_to_head.append({
            'system_a': a, 'system_b': b, 'n_planned': len(expected),
            'a_wins': wins, 'ties': ties, 'b_wins': len(accepted) - wins - ties,
            'n_excluded': missing,
            'a_score_range_over_all_planned': [(wins + ties / 2) / len(expected),
                                              (wins + ties / 2 + missing) / len(expected)]
                                             if expected else None,
        })
    first, second = _fit_preferences(primary, systems), _fit_preferences(stable, systems)
    return {
        'report_kind': 'preference_sensitivity', 'evidence_kind': 'model_judged',
        'primary_rule_changed': False, 'primary_full_consistency': first,
        'diagnostic_stable_preference_only': second,
        'point_order_changed': first['point_order'] != second['point_order']
                               if first['point_order'] and second['point_order'] else None,
        'added_diagnostic_pairs': [r for r in stable if r['pair_id'] not in primary_ids],
        'head_to_head_exclusion_bounds': head_to_head,
        'scope': 'Post hoc diagnostic of the same fixed judge. Point estimates are not significance '
                 'or human-validation claims. The diagnostic counts one stable preference per pair '
                 'even when actions disagree; it does not estimate action rates. Exclusion bounds '
                 'assign every excluded outcome to either side, keeping observed ties at half a point; '
                 'these are deterministic bounds, not confidence intervals or imputed judgments.',
    }


def combine_runs(paths, output, *, bootstrap_samples=1000, seed=20260913, raters=12):
    """Pool disjoint completed batches with an identical declared generation/judge protocol."""
    paths, output = [Path(p).resolve() for p in paths], Path(output)
    if len(paths) < 2 or len(set(paths)) != len(paths):
        raise ValueError('provide at least two distinct run directories')
    if bootstrap_samples < 0 or raters < 3:
        raise ValueError('nonnegative bootstrap samples and at least three raters required')
    if output.exists():
        raise ValueError('output must be a new directory; preserve previous analyses')
    runs = [load_judge_run(p) for p in paths]
    configs = [json.loads((p / 'run.json').read_text(encoding='utf-8'))['config'] for p in paths]
    if any(c != configs[0] for c in configs[1:]):
        raise ValueError('candidate and judge configurations must be identical across batches')
    protocols = [json.loads((p / 'judge/observations.json').read_text(encoding='utf-8'))['protocol']
                 for p in paths]
    # Dataset hashes vary by batch; every other judge-protocol field must match.
    common = [{k: v for k, v in p.items() if k != 'inputs_hash'} for p in protocols]
    if any(p != common[0] for p in common[1:]):
        raise ValueError('judge protocols must be identical except for dataset inputs')
    declared = {s['system_id'] for s in configs[0]['systems']}
    scenarios, responses, pairs, judgments, rows, sources = [], [], [], [], [], []
    seen = set()
    judge_id = 'model-judge:' + digest(common[0])[:16]
    for path, run, config in zip(paths, runs, configs):
        ids = {s.scenario_id for s in run['scenarios']}
        if seen & ids:
            raise ValueError('overlapping scenario IDs across batches; pooling would double count')
        seen.update(ids)
        cells = [(r.scenario_id, r.system_id) for r in run['responses']]
        if (len(cells) != len(set(cells)) or
                set(cells) != {(s, model) for s in ids for model in declared}):
            raise ValueError('each batch must contain exactly one response per declared system/scenario cell')
        if any(r.provenance.value != 'raw_model' or r.track != 'native_generation'
               for r in run['responses']):
            raise ValueError('pooling requires native model generations; controls and synthetic evidence are excluded')
        if run['summary']['n_missing_observations']:
            raise ValueError('complete both judge orders for every pair before pooling')
        plan = verify_generation(run['scenarios'], config, path / 'responses.jsonl',
                                 resume=True, dry_run=True)
        if plan['planned_completions']:
            raise ValueError('candidate generation is incomplete')
        scenarios.extend(run['scenarios'])
        responses.extend(run['responses'])
        pairs.extend(run['pairs'])
        rows.extend(run['rows'])
        judgments.extend(j.model_copy(update={'annotator_id': judge_id}) for j in run['judgments'])
        source_files = ['run.json', 'scenarios.jsonl', 'responses.jsonl', 'pairs.jsonl',
                        'judge/observations.json']
        if (path / 'requests.json').is_file():
            source_files.append('requests.json')
        sources.append({'path': str(path), 'dataset_hash': run['signature'],
                        'sha256': {f: sha256_file(path / f) for f in source_files},
                        'summary': run['summary']})
    require_valid(scenarios, responses, pairs, judgments)
    clusters = _clusters(scenarios, pairs)
    summary = deepcopy(runs[0]['summary'])
    summary.update({
        'protocol_hash': digest(common[0]), 'observations_hash': digest(sources),
        'n_pairs': len(pairs), 'n_scenarios_planned': len(scenarios),
        'n_scenarios_judged': len(scenarios), 'n_accepted_pairs': len(judgments),
        'n_excluded_pairs': len(pairs) - len(judgments),
        'accepted_fraction': len(judgments) / len(pairs),
        'n_observations': sum(r['summary']['n_observations'] for r in runs),
        'n_missing_observations': 0, 'order_diagnostics': summarize_order_checks(rows),
        'resolved_models': sorted({m for r in runs for m in r['summary']['resolved_models']}),
        'excluded_pairs': [p for r in runs for p in r['summary']['excluded_pairs']],
        'interpretation': 'One fixed judge configuration across disjoint batches; at most one vote per pair.',
        'source_runs': sources,
    })
    report = automatic_report(scenarios, responses, pairs, judgments, summary,
                              bootstrap_samples=bootstrap_samples, seed=seed)
    cautions = [
        'Exploratory pooled convenience sample across batches; this is not held-out performance or a population estimate.',
        'Matching requested models and decoding do not guarantee immutable backend snapshots. Inspect resolved model provenance.',
        'One fixed model judge is used across batches; no human judgments or independent judge replication are added by pooling.',
    ]
    report['warnings'].extend(cautions)
    report['analysis'] = {'kind': 'pooled_screening', 'offline': True,
                          'acceptance_rule_changed': False, 'n_batches': len(runs),
                          'source_runs': sources}
    sensitivity = preference_sensitivity(runs)
    report['sensitivity'] = sensitivity
    # Reuse the audit's canonical display normalization, retaining original batch labels.
    audit = compare_judges([paths[0]], bootstrap_samples=0, seed=seed)
    audit_pairs = []
    for path in paths:
        for pair in compare_judges([path], bootstrap_samples=0, seed=seed)['pairs']:
            pair['source_run'] = path.name
            audit_pairs.append(pair)
    calibration = audit['judges']['judge-1']['human_comparison']
    calibration['n_unresolved_reference_pairs'] = len(pairs)
    audit.update({
        'dataset_hash': _dataset_signature(scenarios, responses, pairs), 'n_pairs': len(pairs),
        'n_scenarios': len(scenarios), 'n_independent_groups': len(set(clusters.values())),
        'judges': {'judge-1': dict(summary, run_label='Combined batches', human_comparison=calibration)},
        'pairs': audit_pairs, 'warnings': cautions + ['Human calibration is pending.',
            'Order consistency measures repeatability, not correctness.'],
        'analysis': report['analysis'],
    })
    output.mkdir(parents=True)
    write_jsonl(output / 'scenarios.jsonl', scenarios)
    write_jsonl(output / 'responses.jsonl', responses)
    write_jsonl(output / 'pairs.jsonl', pairs)
    write_jsonl(output / 'model-judgments.jsonl', judgments)
    write_json(output / 'report.json', report)
    write_json(output / 'judge-audit.json', audit)
    write_json(output / 'sensitivity.json', sensitivity)
    study = prepare_study(scenarios, responses, output / 'human-study', raters=raters,
                          judgments_per_pair=3, seed=seed, study_name='Combined model screening validation')
    files = ['scenarios.jsonl', 'responses.jsonl', 'pairs.jsonl', 'model-judgments.jsonl',
             'report.json', 'judge-audit.json', 'sensitivity.json', 'human-study/manifest.json']
    manifest = {
        'schema_version': '0.5', 'artifact_kind': 'pooled_screening', 'offline': True,
        'sources': sources, 'seed': seed, 'bootstrap_samples': bootstrap_samples,
        'candidate_config_hash': digest(configs[0]), 'judge_id': judge_id,
        'n_scenarios': len(scenarios), 'n_independent_groups': len(set(clusters.values())),
        'n_pairs': len(pairs), 'n_human_judgments': 0, 'genres': dict(Counter(s.genre for s in scenarios)),
        'human_study_id': study['study_id'], 'warnings': cautions,
        'sha256': {f: sha256_file(output / f) for f in files},
    }
    write_json(output / 'combined-manifest.json', manifest)
    return {'output': str(output), 'n_batches': len(runs), 'n_scenarios': len(scenarios),
            'n_accepted_pairs': len(judgments), 'n_pairs': len(pairs),
            'n_model_judges': 1, 'n_human_judgments': 0,
            'sensitivity_point_order_changed': sensitivity['point_order_changed']}
