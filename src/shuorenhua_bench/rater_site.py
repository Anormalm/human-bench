from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from .study import sha256_file, verify_study, write_json

WEB = Path(__file__).resolve().parents[2] / 'web'
ASSETS = {'annotation.js': 'text/javascript', 'rater.js': 'text/javascript', 'styles.css': 'text/css'}
ITEM_FIELDS = ('pair_id', 'scenario_id', 'language', 'genre', 'relationship', 'intent', 'channel',
               'context', 'instruction', 'required_facts', 'prohibited_changes',
               'response_a', 'response_b', 'response_a_text', 'response_b_text')
PUBLIC_PATH = re.compile(r'(assets/(annotation\.js|rater\.js|styles\.css)|'
                         r'r/[A-Za-z0-9_-]{32}/(index\.html|bundle\.json))')


def _public_packet(packet, assignment_id, study_id):
    if packet['assignment_id'] != assignment_id or packet['study_id'] != study_id:
        raise ValueError('packet identity differs from the frozen assignment')
    items = []
    for item in packet['items']:
        if any(not re.fullmatch(r'r-[0-9a-f]{24}', item[key]) for key in ('response_a', 'response_b')):
            raise ValueError('rater packets require opaque response aliases')
        items.append({key: item[key] for key in ITEM_FIELDS})
    # Keep the original packet identity for progress/import joins, but omit titles and metadata.
    return {'schema_version': '0.3', 'study_id': study_id, 'bundle_id': packet['bundle_id'],
            'assignment_id': assignment_id, 'n_pairs': len(items),
            'demo': bool(packet.get('demo', False)), 'items': items}


def prepare_rater_site(study, output, *, base_url='http://127.0.0.1:8044'):
    study, output = Path(study).resolve(), Path(output).resolve()
    manifest = verify_study(study)
    if output.exists():
        raise ValueError('rater site output must be a new directory')
    base_url = base_url.rstrip('/')
    url = urlsplit(base_url)
    if (url.scheme not in {'http', 'https'} or not url.netloc or url.username or url.password or
            url.query or url.fragment or url.path):
        raise ValueError('base URL must be an HTTP(S) origin without credentials, path, query or fragment')
    packets = {}
    for assignment, relative in manifest['assignments'].items():
        path = (study / relative).resolve()
        if not path.is_relative_to(study / 'public'):
            raise ValueError('assignment file must be inside the study public directory')
        packet = _public_packet(json.loads(path.read_text(encoding='utf-8')),
                                assignment, manifest['study_id'])
        expected_demo = manifest['evidence_status'] == 'synthetic_demo'
        if packet['demo'] != expected_demo:
            raise ValueError('packet evidence label differs from the frozen study')
        packets[assignment] = packet
    output.mkdir(parents=True)
    site = output / 'site'
    assets = site / 'assets'
    assets.mkdir(parents=True)
    for name in ASSETS:
        content = (WEB / name).read_text(encoding='utf-8-sig')
        if name == 'styles.css':
            # Rater pages work without third-party requests, including external font requests.
            content = '\n'.join(line for line in content.splitlines() if not line.startswith('@import '))
        (assets / name).write_text(content, encoding='utf-8')
    html = (WEB / 'rater.html').read_text(encoding='utf-8')
    assignments, tokens = {}, set()
    for assignment, packet in packets.items():
        token = secrets.token_urlsafe(24)
        while token in tokens:
            token = secrets.token_urlsafe(24)
        tokens.add(token)
        target = site / 'r' / token
        target.mkdir(parents=True)
        (target / 'index.html').write_text(html, encoding='utf-8')
        write_json(target / 'bundle.json', packet)
        assignments[assignment] = {'path': f'/r/{token}/', 'url': f'{base_url}/r/{token}/',
                                   'n_pairs': len(packet['items']), 'bundle_id': packet['bundle_id']}
    files = {str(p.relative_to(site)).replace('\\', '/'): sha256_file(p)
             for p in sorted(site.rglob('*')) if p.is_file()}
    frozen = {
        'schema_version': '0.5', 'artifact_kind': 'rater_site', 'study_id': manifest['study_id'],
        'source_study': str(study), 'source_manifest_sha256': sha256_file(study / 'manifest.json'),
        'evidence_status': manifest['evidence_status'], 'n_assignments': len(assignments),
        'n_planned_judgments': sum(a['n_pairs'] for a in assignments.values()), 'sha256': files,
    }
    write_json(output / 'site-manifest.json', frozen)
    write_json(output / 'coordinator.json', {'study_id': manifest['study_id'], 'assignments': assignments})
    links = '\n'.join(f"| {name} | {item['n_pairs']} | [Open assigned packet]({item['url']}) |"
                      for name, item in assignments.items())
    instructions = f'''# Rater-only annotation links

This is the coordinator's copy. Send each recruited rater only their own assigned URL.

| Assignment | Comparisons | Link |
| --- | ---: | --- |
{links}

The site serves blinded packets and annotation assets only. Rankings, raw generation files,
judge rationales, coordinator files and private response mappings are outside its route allowlist.
Raters' answers stay in their browser until they export JSONL and return the file to you.
No judgments are automatically uploaded. Resume in the same browser and origin.

Run from the repository root:

```powershell
.\\.venv\\Scripts\\python.exe scripts/serve_web.py --port {url.port or (443 if url.scheme == 'https' else 80)} --rater-site "{output}"
```

The default server binds to this computer only. A localhost URL is not accessible on another
person's computer. Remote recruitment requires an appropriately hosted site; none is published
by this command. The random assignment links limit accidental discovery, but do not authenticate
who responds. Do not use the workbench origin for recruited raters or share their links publicly.
The response text itself is preserved, including any identity clues it might contain.

Keep this directory and coordinator.json private. If publishing static files later, publish only
site/ through an explicitly configured host, with directory listings disabled. Serving a copied
site with serve_web verifies all declared files before launch and serves the frozen bytes.

Use the existing evaluate command with the original study and exported JSONL files. The importer
checks assignment, display orientation, evidence kind and duplicates. Review source scenarios with
native speakers and recruit independent raters before making human-preference claims.
'''
    (output / 'README.md').write_text(instructions, encoding='utf-8')
    return {'output': str(output), 'study_id': manifest['study_id'],
            'n_assignments': len(assignments), 'n_planned_judgments': frozen['n_planned_judgments'],
            'coordinator_links': str(output / 'README.md'), 'evidence_status': manifest['evidence_status']}


def load_rater_routes(directory):
    """Verify and snapshot only known public file kinds; never serve coordinator/private files."""
    directory = Path(directory).resolve()
    frozen = json.loads((directory / 'site-manifest.json').read_text(encoding='utf-8'))
    if frozen.get('artifact_kind') != 'rater_site' or frozen.get('schema_version') != '0.5':
        raise ValueError('unsupported rater site manifest')
    site, routes = (directory / 'site').resolve(), {}
    expected_assets = {f'assets/{name}' for name in ASSETS}
    if not expected_assets.issubset(frozen['sha256']):
        raise ValueError('rater site assets are missing')
    for relative, expected in frozen['sha256'].items():
        if not PUBLIC_PATH.fullmatch(relative):
            raise ValueError('unrecognized public rater path')
        path = (site / relative).resolve()
        if not path.is_relative_to(site):
            raise ValueError('rater site file hash or path mismatch')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != expected:
            raise ValueError('rater site file hash or path mismatch')
        mime = ASSETS[path.name] if relative.startswith('assets/') else (
            'text/html' if path.suffix == '.html' else 'application/json')
        routes['/' + relative] = (mime, body)
        if path.name == 'index.html':
            routes['/' + relative.removesuffix('index.html')] = (mime, body)
    packet_dirs = {p.rsplit('/', 1)[0] for p in frozen['sha256'] if p.endswith('/bundle.json')}
    html_dirs = {p.rsplit('/', 1)[0] for p in frozen['sha256'] if p.endswith('/index.html')}
    if packet_dirs != html_dirs or len(packet_dirs) != frozen['n_assignments']:
        raise ValueError('rater site assignment coverage mismatch')
    return routes
