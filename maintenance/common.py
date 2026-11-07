import hashlib
import json
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.trail-state'


def load_env():
    path = ROOT / '.env.local'
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.strip().partition('=')
            if sep and key in {'MAPBOX_ACCESS_TOKEN', 'OPENAI_API_KEY', 'OPENAI_MODEL'}:
                os.environ.setdefault(key, value.strip().strip('\"\''))


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(value).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    temp.replace(path)


class RequestError(RuntimeError):
    """Sanitized remote failure with enough metadata for read-only retry policy."""
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status
        self.retryable = status is None or status in {408, 429, 500, 502, 503, 504}


def request(url, method='GET', body=None, headers=None, limit=20_000_000, timeout=45):
    headers = {'User-Agent': 'CvilleTrails/1.0 (+https://cvilletrails.com)', **(headers or {})}
    if body is not None:
        body = json.dumps(body, allow_nan=False).encode()
        headers['Content-Type'] = 'application/json'
    try:
        with urlopen(Request(url, data=body, headers=headers, method=method), timeout=timeout) as response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError('Response exceeds configured size limit')
            return data, dict(response.headers), response.status
    except HTTPError as error:
        if error.code == 304:
            return b'', dict(error.headers), 304
        # Only expose a machine-readable error code, never URLs, headers, or bodies.
        detail = ''
        try:
            code = json.loads(error.read(4096)).get('error', {}).get('code')
            if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,80}', code): detail = f' ({code})'
        except (ValueError, AttributeError): pass
        raise RequestError(f'HTTP {error.code} from remote service{detail}', error.code) from None
    except (URLError, TimeoutError):
        raise RequestError('Network request failed or timed out') from None


def configs(pipeline=None):
    found = []
    for path in sorted((ROOT / 'pipelines').glob('*/pipeline.json')):
        config = read_json(path)
        if pipeline is None or config['id'] == pipeline:
            if config['id'] != path.parent.name or not re.fullmatch(r'[a-z0-9-]+', config['id']):
                raise ValueError('Pipeline ID must match its directory')
            ids = set()
            for source in config['sources']:
                if not re.fullmatch(r'[a-z0-9-]+', source['id']) or source['id'] in ids:
                    raise ValueError('Source IDs must be unique simple identifiers')
                ids.add(source['id'])
                if 'system_ids' in source and (not source['system_ids'] or not set(source['system_ids']).issubset(config['system_ids'])):
                    raise ValueError('Source systems must be a nonempty subset of pipeline systems')
                if not source['url'].startswith('https://') or source['kind'] not in {'html', 'pdf', 'geojson', 'arcgis', 'text'}:
                    raise ValueError('Sources require HTTPS and a supported format')
                manual = source.get('manual_review_on_403')
                if manual is not None:
                    if not isinstance(manual, dict) or any(not isinstance(manual.get(k), str) or not manual[k].strip()
                            for k in ('reason', 'since', 'evidence')):
                        raise ValueError('Manual-review exception needs a reason, since date and evidence')
                    datetime.strptime(manual['since'], '%Y-%m-%d')
            for filename in ('ingest.py', 'overrides.json', 'review.txt'):
                if not (path.parent / filename).is_file(): raise ValueError(f'Pipeline missing {filename}')
            config['_directory'] = path.parent
            found.append(config)
    if not found:
        raise ValueError('No matching pipeline')
    return found
