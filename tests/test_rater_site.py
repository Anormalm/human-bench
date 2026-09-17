import json

import pytest
from test_v03 import response, scenario

from api.rater import create_rater_app
from shuorenhua_bench.dataset import write_jsonl
from shuorenhua_bench.rater_site import prepare_rater_site
from shuorenhua_bench.schemas import PairwiseJudgment
from shuorenhua_bench.study import import_judgments, prepare_study, sha256_file


def site(tmp_path, *, demo=False):
    study = tmp_path / 'study'
    prepare_study([scenario()], [response('a', 'SECRET-MODEL-A'), response('b', 'SECRET-MODEL-B')],
                  study, raters=3, study_name='PRIVATE MODEL TITLE', demo=demo)
    output = tmp_path / 'rater-site'
    prepare_rater_site(study, output)
    coordinator = json.loads((output / 'coordinator.json').read_text(encoding='utf-8'))
    return study, output, coordinator['assignments']['rater-001']['path']


def request(app, path, method='GET'):
    result = {}
    def start(status, headers):
        result.update(status=status, headers=dict(headers))
    result['body'] = b''.join(app({'PATH_INFO': path, 'REQUEST_METHOD': method}, start))
    return result


def test_rater_app_exposes_only_assigned_content(tmp_path, monkeypatch):
    study, output, url = site(tmp_path)
    secret = tmp_path / 'secret.json'
    secret.write_text('{"model":"DO-NOT-SERVE"}')
    monkeypatch.setenv('SHUORENHUA_REPORT', str(secret))
    monkeypatch.setenv('SHUORENHUA_JUDGE_AUDIT', str(secret))
    app = create_rater_app(output)
    for path in ['/api/report', '/api/judge-audit', '/api/collection', '/api/wide-report', '/wide', '/wide.js',
                 '/api/bundle', '/app.js', '/index.html',
                 '/coordinator.json', '/site-manifest.json', '/private/response_map.json',
                 '/studies/secret.json', '/r/rater-001/bundle.json', url + '../../coordinator.json']:
        assert request(app, path)['status'] == '404 Not Found'
    packet = request(app, url + 'bundle.json')
    assert packet['status'] == '200 OK'
    text = packet['body'].decode()
    assert 'SECRET-MODEL' not in text and 'PRIVATE MODEL TITLE' not in text
    data = json.loads(text)
    assert data['assignment_id'] == 'rater-001' and not data['demo']
    html = request(app, url)['body'].decode()
    assert 'reportFile' not in html and 'judgeAudit' not in html and 'Load packet' not in html
    assert 'annotation.js' in html and 'app.js' not in html
    assert b'@import' not in request(app, '/assets/styles.css')['body']
    assert request(app, url)['headers']['Referrer-Policy'] == 'no-referrer'
    assert 'fonts.googleapis' not in request(app, url)['headers']['Content-Security-Policy']
    original = json.loads((study / 'public/rater-001.json').read_text(encoding='utf-8'))
    assert data['items'] == original['items']
    assert data['bundle_id'] == original['bundle_id']


def test_site_is_frozen_and_requests_never_serve_new_files(tmp_path):
    _, output, url = site(tmp_path)
    app = create_rater_app(output)
    before = request(app, url + 'bundle.json')['body']
    (output / 'site/secret.json').write_text('not public')
    assert request(app, '/secret.json')['status'] == '404 Not Found'
    target = output / 'site' / url.strip('/') / 'bundle.json'
    target.write_text('{}')
    assert request(app, url + 'bundle.json')['body'] == before
    with pytest.raises(ValueError, match='hash or path mismatch'):
        create_rater_app(output)


def test_head_has_no_body_and_post_never_accepts_annotations(tmp_path):
    _, output, url = site(tmp_path)
    app = create_rater_app(output)
    head = request(app, url, 'HEAD')
    assert head['status'] == '200 OK' and head['body'] == b''
    assert int(head['headers']['Content-Length']) > 0
    assert request(app, url, 'POST')['status'] == '405 Method Not Allowed'


@pytest.mark.parametrize('path', ['../coordinator.json', 'assets/app.js', '/private/response_map.json'])
def test_manifest_cannot_expand_public_route_allowlist(tmp_path, path):
    _, output, _ = site(tmp_path)
    file = output / 'site-manifest.json'
    manifest = json.loads(file.read_text())
    manifest['sha256'][path] = 'x'
    file.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='unrecognized public rater path'):
        create_rater_app(output)


@pytest.mark.parametrize('demo', [False, True])
def test_rater_exports_keep_frozen_identity_orientation_and_evidence(tmp_path, demo):
    study, output, url = site(tmp_path, demo=demo)
    packet = json.loads(request(create_rater_app(output), url + 'bundle.json')['body'])
    rows = [PairwiseJudgment(
        pair_id=item['pair_id'], scenario_id=item['scenario_id'],
        response_a=item['response_a'], response_b=item['response_b'],
        annotator_id=packet['assignment_id'], assignment_id=packet['assignment_id'],
        study_id=packet['study_id'], preference='B', action_a='revise', action_b='send',
        confidence=4, evidence_kind='synthetic' if packet['demo'] else 'human')
        for item in packet['items']]
    export = tmp_path / 'export.jsonl'
    write_jsonl(export, rows)
    imported, duplicates = import_judgments(study, [export, export])
    assert len(imported) == duplicates == 1 and imported[0].preference == 'B'
    mapping = json.loads((study / 'private/response_map.json').read_text())
    assert imported[0].response_b == mapping[rows[0].response_b]
    assert imported[0].evidence_kind == ('synthetic' if demo else 'human')


def test_rater_site_refuses_changed_source_and_overwriting(tmp_path):
    study, output, _ = site(tmp_path)
    with pytest.raises(ValueError, match='new directory'):
        prepare_rater_site(study, output)
    (study / 'public/rater-001.json').write_text('{}')
    with pytest.raises(ValueError, match='study integrity failure'):
        prepare_rater_site(study, tmp_path / 'new-site')


def test_public_projection_drops_extra_metadata(tmp_path):
    study, _, _ = site(tmp_path)
    packet_file = study / 'public/rater-001.json'
    packet = json.loads(packet_file.read_text(encoding='utf-8'))
    packet['internal_model_scores'] = 'PRIVATE'
    packet['items'][0]['system_id'] = 'PRIVATE'
    packet_file.write_text(json.dumps(packet), encoding='utf-8')
    file = study / 'manifest.json'
    manifest = json.loads(file.read_text(encoding='utf-8'))
    manifest['sha256']['public/rater-001.json'] = sha256_file(packet_file)
    file.write_text(json.dumps(manifest), encoding='utf-8')
    output = tmp_path / 'projected'
    prepare_rater_site(study, output)
    coordinator = json.loads((output / 'coordinator.json').read_text())
    url = coordinator['assignments']['rater-001']['path']
    assert b'PRIVATE' not in request(create_rater_app(output), url + 'bundle.json')['body']
