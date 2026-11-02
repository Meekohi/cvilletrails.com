"""Repeatable normalization. Geometry comes from GIS or reviewed GeoJSON, never an LLM."""
import copy
import math
from .common import digest, read_json


def validate_collection(collection):
    if collection.get('type') != 'FeatureCollection' or not isinstance(collection.get('features'), list):
        raise ValueError('Expected a GeoJSON FeatureCollection')
    if collection.get('crs'):
        raise ValueError('Reproject to WGS84 longitude/latitude and remove crs before importing')
    ids = set()

    def point(value):
        if not isinstance(value, list) or not 2 <= len(value) <= 3:
            raise ValueError('Expected longitude/latitude coordinate')
        if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in value):
            raise ValueError('Coordinates must be finite numbers')
        if not -180 <= value[0] <= 180 or not -90 <= value[1] <= 90:
            raise ValueError('Coordinates are outside longitude/latitude bounds')

    def line(value, ring=False):
        if not isinstance(value, list) or len(value) < (4 if ring else 2):
            raise ValueError('Line or ring has too few coordinates')
        for coordinate in value:
            point(coordinate)
        if ring and value[0] != value[-1]:
            raise ValueError('Polygon rings must be closed')

    for feature in collection['features']:
        if feature.get('type') != 'Feature' or not isinstance(feature.get('properties'), dict):
            raise ValueError('Each feature needs type Feature and object properties')
        fid = feature.get('id')
        if isinstance(fid, bool) or not isinstance(fid, (str, int)) or str(fid) == '':
            raise ValueError('Every feature needs a stable string/integer id')
        if str(fid) in ids:
            raise ValueError(f'Duplicate feature id: {fid}')
        ids.add(str(fid))
        geometry = feature.get('geometry') or {}
        kind, coords = geometry.get('type'), geometry.get('coordinates')
        if not isinstance(coords, list) or not coords:
            raise ValueError('Empty geometry is not supported')
        if kind == 'Point': point(coords)
        elif kind == 'MultiPoint':
            for p in coords: point(p)
        elif kind == 'LineString': line(coords)
        elif kind == 'MultiLineString':
            for l in coords: line(l)
        elif kind == 'Polygon':
            for ring in coords: line(ring, True)
        elif kind == 'MultiPolygon':
            for polygon in coords:
                if not polygon: raise ValueError('Empty polygon')
                for ring in polygon: line(ring, True)
        else: raise ValueError(f'Unsupported geometry: {kind}')
    return collection


def canonical(collection):
    validate_collection(collection)
    # Ignore API collection metadata and feature ordering, but retain all properties.
    return {'type': 'FeatureCollection', 'features': sorted([
        {'type': 'Feature', 'id': str(f['id']), 'geometry': f['geometry'], 'properties': f['properties']}
        for f in collection['features']], key=lambda f: f['id'])}


def normalize(collection, config, source_id):
    source = next((s for s in config['sources'] if s['id'] == source_id), None)
    if not source:
        raise ValueError('Source must be registered in this pipeline')
    if collection.get('type') != 'FeatureCollection' or collection.get('crs'):
        raise ValueError('Expected WGS84 GeoJSON FeatureCollection without crs')
    overrides = read_json(config['_directory'] / 'overrides.json')
    mapping = config['fields']
    features = []
    used = set()
    for original in collection['features']:
        f = copy.deepcopy(original)
        props = f['properties']
        source_feature_id = props.get(mapping['id']) if mapping.get('id') else f.get('id')
        if source_feature_id is None or str(source_feature_id) == '':
            raise ValueError('Missing stable upstream id; configure fields.id, never use row numbers')
        sid = str(source_feature_id)
        used.add(sid)
        override = overrides.get(sid, {})
        f['id'] = str(override.get('feature_id', f"{config['id']}:{sid}"))
        props.update({
            'name': props.get(mapping.get('name', 'name')) or 'Unnamed trail',
            'color': props.get(mapping.get('color', 'color')) or None,
            'system_id': config['system_id'],
            'source_id': source_id,
            'source_feature_id': sid,
            'source_url': source['url'],
        })
        props.update(override.get('properties', {}))
        features.append(f)
    orphaned = set(overrides) - used
    if orphaned:
        raise ValueError(f'Upstream removed curated features; review overrides before proceeding: {sorted(orphaned)}')
    return canonical({'type': 'FeatureCollection', 'features': features})


def changes(before, after):
    old = {f['id']: f for f in canonical(before)['features']}
    new = {f['id']: f for f in canonical(after)['features']}
    changed = [fid for fid in old.keys() & new.keys() if old[fid] != new[fid]]
    return {
        'added': sorted(new.keys() - old.keys()),
        'deleted': sorted(old.keys() - new.keys()),
        'changed': sorted(changed),
        'geometry_changed': sorted(fid for fid in changed if old[fid]['geometry'] != new[fid]['geometry']),
        'curation_changed': sorted(fid for fid in changed if any(k in old[fid]['properties'] and old[fid]['properties'].get(k) != new[fid]['properties'].get(k) for k in ('color', 'TrailName', 'name', 'NAME', 'Name', 'system_id'))),
    }


def fingerprint(collection):
    return digest(canonical(collection))
