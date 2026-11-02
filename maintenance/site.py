import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from .common import ROOT, digest, now, read_json, write_json


def timestamp(value):
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None: raise ValueError('Dates must include a timezone')
    return date


def validate_updates(feed, systems):
    valid_systems = {system['id'] for system in systems}
    seen = set()
    for notice in feed['updates']:
        for key in ('id', 'title', 'body', 'source_url', 'source_label', 'reviewer', 'evidence'):
            if not isinstance(notice.get(key), str) or not notice[key].strip(): raise ValueError(f'Notice needs {key}')
        if notice['id'] in seen: raise ValueError('Duplicate notice ID')
        seen.add(notice['id'])
        if notice['status'] != 'approved': raise ValueError('Only reviewed notices belong in the public feed')
        if notice['kind'] not in {'closure', 'access', 'maintenance', 'event', 'information'}: raise ValueError('Invalid notice kind')
        if not notice['system_ids'] or not set(notice['system_ids']).issubset(valid_systems): raise ValueError('Unknown trail system')
        if urlparse(notice['source_url']).scheme != 'https' or not urlparse(notice['source_url']).netloc: raise ValueError('Source URL must be HTTPS')
        if timestamp(notice['expires_at']) <= timestamp(notice['starts_at']): raise ValueError('Notice expires before it starts')
        timestamp(notice['reviewed_at'])


def approve_notice(review_path, index, reviewer, starts, expires, output=ROOT / 'data/updates.json'):
    review = read_json(review_path)
    draft = review['assessment']['result']['notices'][index]
    notice = {
        'id': digest({'source': review['source']['id'], 'snapshot': review['after']['sha256'], 'index': index})[:24],
        'title': draft['title'], 'body': draft['body'], 'kind': draft['kind'],
        'evidence': draft['evidence'], 'system_ids': review['system_ids'],
        'source_url': review['source']['url'], 'source_label': review['source']['label'],
        'status': 'approved', 'reviewer': reviewer, 'reviewed_at': now(),
        'starts_at': starts or draft['starts_at'], 'expires_at': expires or draft['expires_at'],
        'snapshot_sha256': review['after']['sha256'],
    }
    if not notice['starts_at'] or not notice['expires_at']:
        raise ValueError('Explicit start and expiry dates are required; use --starts and --expires')
    feed = read_json(output)
    feed['updates'] = [item for item in feed['updates'] if item['id'] != notice['id']] + [notice]
    validate_updates(feed, read_json(ROOT / 'data/systems.json'))
    write_json(output, feed)
    return notice


def build_site(output=ROOT / 'dist'):
    # Build from an allowlist: never serve the repo root or copy .env/state/backups.
    output = Path(output)
    if output.resolve() != (ROOT / 'dist').resolve(): raise ValueError('Build output must be the project dist directory')
    validate_updates(read_json(ROOT / 'data/updates.json'), read_json(ROOT / 'data/systems.json'))
    if output.exists(): shutil.rmtree(output)
    output.mkdir()
    for filename in ('index.html', 'CNAME'):
        shutil.copy2(ROOT / filename, output / filename)
    shutil.copytree(ROOT / 'assets', output / 'assets')
    (output / 'data').mkdir()
    for filename in ('systems.json', 'updates.json'):
        shutil.copy2(ROOT / 'data' / filename, output / 'data' / filename)
    (output / '.nojekyll').touch()
