"""Pipeline-owned adapters with shared completeness checks for ArcGIS."""
import importlib.util
import json
from urllib.parse import urlencode
from .common import request
from .geo import canonical


def run_adapter(collection, config, source_id):
    path = config['_directory'] / 'ingest.py'
    spec = importlib.util.spec_from_file_location(f"pipeline_{config['id']}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.transform(collection, config, source_id)
    normalized = canonical(result)
    if result.get('ingest_report'): normalized['ingest_report'] = result['ingest_report']
    return normalized


def fetch_arcgis(url, request_fn=None):
    request_fn = request_fn or request
    def query(params):
        data, _, _ = request_fn(url.rstrip('/') + '/query?' + urlencode(params))
        value = json.loads(data)
        if 'error' in value: raise ValueError('ArcGIS returned an error')
        return value
    ids = query({'where': '1=1', 'returnIdsOnly': 'true', 'f': 'json'}).get('objectIds')
    if not isinstance(ids, list) or not ids: raise ValueError('ArcGIS returned no feature IDs')
    if len(ids) != len(set(ids)): raise ValueError('ArcGIS returned duplicate feature IDs')
    features = []
    # Request explicit IDs in bounded batches so record limits cannot silently truncate.
    for start in range(0, len(ids), 200):
        batch = ids[start:start + 200]
        page = query({'objectIds': ','.join(map(str, batch)), 'outFields': '*', 'returnGeometry': 'true', 'outSR': '4326', 'f': 'geojson'})
        if page.get('exceededTransferLimit') or len(page.get('features', [])) != len(batch):
            raise ValueError('ArcGIS response was incomplete; refusing partial trail data')
        features.extend(page['features'])
    # Check for edits to membership during pagination.
    final_ids = query({'where': '1=1', 'returnIdsOnly': 'true', 'f': 'json'}).get('objectIds')
    if set(final_ids or []) != set(ids): raise ValueError('ArcGIS changed during import; retry for a consistent snapshot')
    return json.dumps({'type': 'FeatureCollection', 'features': sorted(features, key=lambda f: str(f.get('id', '')))}, sort_keys=True).encode()
