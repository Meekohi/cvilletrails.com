import json
import os
import time
from urllib.parse import quote, urlencode
from .common import ROOT, STATE, digest, now, read_json, request, write_json
from .geo import canonical, changes, fingerprint


class Mapbox:
    def __init__(self, username=None):
        settings = read_json(ROOT / 'config/mapbox.json')
        self.username = username or settings['username']
        self.style_id = settings['style_id']
        self.token = os.environ.get('MAPBOX_ACCESS_TOKEN')
        if not self.token: raise ValueError('MAPBOX_ACCESS_TOKEN is not configured')

    def call(self, path, method='GET', body=None, params=None):
        query = urlencode({**(params or {}), 'access_token': self.token})
        data, headers, _ = request(f'https://api.mapbox.com/{path}?{query}', method, body, {'Cache-Control': 'no-cache'})
        return (json.loads(data) if data else None), headers

    def datasets(self):
        result, start = [], None
        while True:
            params = {'limit': 100, 'sortby': 'created'}
            if start: params['start'] = start
            page, headers = self.call(f'datasets/v1/{self.username}', params=params)
            result.extend(page)
            if not any('rel="next"' in v for k, v in headers.items() if k.lower() == 'link'): break
            if not page or page[-1]['id'] == start: raise ValueError('Dataset pagination did not advance')
            start = page[-1]['id']
        return result

    def features(self, dataset):
        features, start = [], None
        while True:
            params = {'limit': 1000}
            if start: params['start'] = start
            page, headers = self.call(f'datasets/v1/{self.username}/{quote(dataset, safe="")}/features', params=params)
            features.extend(page['features'])
            if not any('rel="next"' in v for k, v in headers.items() if k.lower() == 'link'): break
            if not page['features'] or str(page['features'][-1]['id']) == start: raise ValueError('Feature pagination did not advance')
            start = str(page['features'][-1]['id'])
        return canonical({'type': 'FeatureCollection', 'features': features})

    def metadata(self, dataset):
        return self.call(f'datasets/v1/{self.username}/{quote(dataset, safe="")}')[0]

    def style(self):
        return self.call(f'styles/v1/{self.username}/{quote(self.style_id, safe="")}')[0]

    def tileset(self, tileset):
        return self.call(f'v4/{quote(tileset, safe=".")}.json', params={'secure': 'true'})[0]

    def write_feature(self, dataset, feature):
        self.call(f'datasets/v1/{self.username}/{quote(dataset, safe="")}/features/{quote(str(feature["id"]), safe="")}', 'PUT', feature)

    def delete_feature(self, dataset, fid):
        self.call(f'datasets/v1/{self.username}/{quote(dataset, safe="")}/features/{quote(fid, safe="")}', 'DELETE')

    def upload(self, dataset, tileset):
        return self.call(f'uploads/v1/{self.username}', 'POST', {'tileset': tileset, 'url': f'mapbox://datasets/{self.username}/{dataset}'})[0]

    def upload_status(self, upload_id):
        return self.call(f'uploads/v1/{self.username}/{quote(upload_id, safe="")}')[0]


def inventory(client, output=STATE / 'mapbox'):
    datasets = client.datasets()
    style = client.style()
    write_json(output / 'style.json', style)
    write_json(output / 'datasets.json', datasets)
    summary = []
    for dataset in datasets:
        features = client.features(dataset['id'])
        write_json(output / 'datasets' / f"{dataset['id']}.geojson", features)
        summary.append({'id': dataset['id'], 'name': dataset.get('name'), 'features': len(features['features'])})
    write_json(output / 'inventory.json', {'captured_at': now(), 'datasets': summary})
    return summary


def target_by_id(target_id):
    settings = read_json(ROOT / 'config/mapbox.json')
    target = next((t for t in settings['targets'] if t['id'] == target_id), None)
    if not target: raise ValueError('Unknown publishing target; configure config/mapbox.json first')
    return target


def verify_target(client, target):
    # A target must refer to an existing tileset/layer, never create a new source by accident.
    tilejson = client.tileset(target['tileset'])
    if target['source_layer'] not in [l['id'] for l in tilejson.get('vector_layers', [])]:
        raise ValueError('Configured source layer is absent from the target tileset')
    style = client.style()
    tilesets = {tile for source in style['sources'].values() for tile in source.get('url', '').removeprefix('mapbox://').split(',')}
    if target['tileset'] not in tilesets or target['source_layer'] not in {layer.get('source-layer') for layer in style['layers']}:
        raise ValueError('The current style no longer uses this publishing target; review the target mapping')


def make_plan(client, target, candidate, evidence):
    if not evidence.strip(): raise ValueError('An evidence reference is required')
    verify_target(client, target)
    metadata = client.metadata(target['dataset'])
    before = client.features(target['dataset'])
    review = candidate.get('ingest_report', {})
    if review.get('reviewed_before_hash') and (review['reviewed_before_hash'] != fingerprint(before) or review.get('reviewed_target') != target):
        raise ValueError('The dataset or target changed during visual review. Reconcile with the current Studio data before creating a new plan.')
    after = canonical(candidate)
    if not after['features']: raise ValueError('Refusing an empty replacement dataset')
    plan = {
        'schema_version': 1, 'created_at': now(), 'target': target,
        'evidence': evidence, 'dataset_modified': metadata['modified'],
        'ingest_report': candidate.get('ingest_report', {}),
        'before_hash': fingerprint(before), 'after_hash': fingerprint(after),
        'changes': changes(before, after), 'before': before, 'after': after,
    }
    plan['approval_hash'] = digest(plan)
    return plan


def apply_plan(client, plan, approval, publish=False, state_dir=STATE):
    unsigned = {k: v for k, v in plan.items() if k != 'approval_hash'}
    if approval != plan['approval_hash'] or digest(unsigned) != approval:
        raise ValueError('Approval hash does not match the exact reviewed plan')
    target = plan['target']
    if target != target_by_id(target['id']): raise ValueError('Publishing target changed since review')
    if fingerprint(plan['before']) != plan['before_hash'] or fingerprint(plan['after']) != plan['after_hash']:
        raise ValueError('Plan data hashes do not match')
    verify_target(client, target)
    live = client.features(target['dataset'])
    if fingerprint(live) != plan['before_hash'] or client.metadata(target['dataset'])['modified'] != plan['dataset_modified']:
        raise ValueError('Dataset changed since review. Generate a new plan to preserve Studio edits.')
    # Durable backup and journal are written before the first mutation.
    journal_path = state_dir / 'publishes' / f'{approval}.json'
    if journal_path.exists(): raise ValueError('This plan has already been attempted; inspect its journal before retrying')
    write_json(state_dir / 'backups' / f'{approval}.geojson', live)
    journal = {'approval_hash': approval, 'started_at': now(), 'target': target, 'state': 'writing', 'completed': []}
    write_json(journal_path, journal)
    change = changes(live, plan['after'])
    after = {f['id']: f for f in plan['after']['features']}
    try:
        for fid in change['added'] + change['changed']:
            client.write_feature(target['dataset'], after[fid])
            journal['completed'].append({'put': fid}); write_json(journal_path, journal)
            time.sleep(1.6)  # Stay below the legacy API's 40 writes/minute limit.
        for fid in change['deleted']:
            client.delete_feature(target['dataset'], fid)
            journal['completed'].append({'delete': fid}); write_json(journal_path, journal)
            time.sleep(1.6)
        if fingerprint(client.features(target['dataset'])) != plan['after_hash']:
            raise ValueError('Post-write verification failed; inspect the saved backup and journal')
        journal['state'] = 'dataset-updated'
        write_json(journal_path, journal)
        if publish:
            upload = client.upload(target['dataset'], target['tileset'])
            journal['upload_id'] = upload['id']
            journal['state'] = 'tileset-processing'
            write_json(journal_path, journal)
            for _ in range(120):
                if upload.get('error'): raise ValueError('Mapbox tileset processing failed; inspect upload status')
                if upload.get('complete'):
                    journal['state'] = 'published'
                    break
                time.sleep(5)
                upload = client.upload_status(upload['id'])
            else: raise ValueError('Tileset still processing; use upload-status with the saved upload_id')
    except (ValueError, RuntimeError, OSError):
        journal['state'] = 'needs-attention'
        write_json(journal_path, journal)
        raise
    journal['finished_at'] = now()
    write_json(journal_path, journal)
    return journal
