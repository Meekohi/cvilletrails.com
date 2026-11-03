"""Read-only screening of a proposal against the style's editable datasets."""
from collections import Counter
from pathlib import Path
from .common import digest, now, read_json
from .geo import fingerprint
from .review_map import verify_plan


def geometry_tools():
    try:
        from pyproj import Transformer
        from shapely.geometry import shape
        from shapely.ops import transform, unary_union
        from shapely.strtree import STRtree
    except ImportError:
        raise ValueError('Overlap analysis needs maintenance/requirements-geo.txt; other maintenance commands do not') from None
    project = Transformer.from_crs('EPSG:4326', 'EPSG:32617', always_xy=True).transform
    return lambda geometry: transform(project, shape(geometry)), unary_union, STRtree


def coverage(line, other, distances=(1, 3, 10, 20)):
    if line.length == 0: return {str(d): 0 for d in distances}
    return {str(d): round(min(1, line.intersection(other.buffer(d)).length / line.length), 4) for d in distances}


def classify(fractions, length):
    if length < 10: return 'short-segment'
    if fractions['3'] >= .9: return 'close-match'
    if fractions['10'] >= .8: return 'strong-overlap'
    if fractions['10'] >= .25: return 'partial-overlap'
    return 'no-substantial-overlap'


def compare_overlaps(plan, inventory_dir):
    verify_plan(plan)
    project, union, Tree = geometry_tools()
    root = Path(inventory_dir)
    style, tilesets = read_json(root / 'style.json'), read_json(root / 'tilesets.json')
    datasets = read_json(root / 'datasets.json')
    baseline = read_json(root / 'datasets' / f"{plan['target']['dataset']}.geojson")
    if fingerprint(baseline) != plan['before_hash']:
        raise ValueError('Overlap inventory is stale for this review plan')
    records, geometries, sources, skipped = [], [], [], []
    for dataset in datasets:
        matched_tiles = [tid for tid in tilesets if tid.split('.', 1)[1].startswith(dataset['id'] + '-')]
        if not matched_tiles:
            skipped.append({'dataset': dataset['id'], 'reason': 'not referenced by the captured style'})
            continue
        layers = {l['id'] for tid in matched_tiles for l in tilesets[tid]['vector_layers']}
        style_layers = [l for l in style['layers'] if l.get('source-layer') in layers and l.get('layout', {}).get('visibility') != 'none']
        role = 'trail-lines' if any(l['type'] == 'line' for l in style_layers) else 'labels-only' if any(l['type'] == 'symbol' for l in style_layers) else 'not-visible'
        data = read_json(root / 'datasets' / f"{dataset['id']}.geojson")
        source = {'dataset': dataset['id'], 'name': dataset['name'], 'role': role, 'source_layers': sorted(layers), 'hash': fingerprint(data), 'style_layers': [l['id'] for l in style_layers]}
        sources.append(source)
        if role == 'not-visible': continue
        for feature in data['features']:
            if feature['geometry']['type'] not in {'LineString', 'MultiLineString'}: continue
            geometry = project(feature['geometry'])
            if geometry.is_empty or geometry.length == 0: continue
            records.append((source, feature))
            geometries.append(geometry)
    tree = Tree(geometries)
    rows, reference_features = {}, {}
    additions = set(plan['changes']['added'])
    # Include substantive geometry edits, notably the held Maintenance Road.
    review_ids = additions | set(plan['changes']['geometry_changed'])
    for feature in plan['after']['features']:
        fid = feature['id']
        if fid not in review_ids: continue
        line = project(feature['geometry'])
        matches, by_source, all_visible = [], {}, []
        for index in tree.query(line.buffer(20)):
            source, existing = records[index]
            if source['dataset'] == plan['target']['dataset'] and existing['id'] == fid: continue
            geometry = geometries[index]
            fractions = coverage(line, geometry)
            # Small crossings and nearby endpoints are not trail duplication.
            if fractions['10'] < .1 or (line.length * fractions['10'] < 10 and fractions['10'] < .5): continue
            key = f"{source['dataset']}/{existing['id']}"
            reverse = coverage(geometry, line)
            props = existing['properties']
            matches.append({'key': key, 'dataset': source['dataset'], 'dataset_name': source['name'], 'role': source['role'],
                            'feature_id': existing['id'], 'name': next((props[k] for k in ('name', 'Name', 'TrailName', 'NAME') if props.get(k)), 'Unnamed trail'),
                            'location': props.get('LocationNa'), 'city_coverage': fractions, 'existing_coverage': reverse,
                            'existing_length_m': round(geometry.length, 1), 'minimum_distance_m': round(line.distance(geometry), 2),
                            'properties': props})
            reference_features[key] = {'type': 'Feature', 'id': key, 'geometry': existing['geometry'], 'properties': {**props, 'overlap_key': key, 'dataset_name': source['name'], 'role': source['role']}}
            by_source.setdefault(source['dataset'], {'source': source, 'geometry': []})['geometry'].append(geometry)
            if source['role'] == 'trail-lines': all_visible.append(geometry)
        visible = coverage(line, union(all_visible)) if all_visible else {str(d): 0 for d in (1, 3, 10, 20)}
        groups = [{'dataset': did, 'name': entry['source']['name'], 'role': entry['source']['role'], 'city_coverage': coverage(line, union(entry['geometry']))} for did, entry in by_source.items()]
        matches.sort(key=lambda m: (m['role'] == 'trail-lines', m['city_coverage']['3'], m['city_coverage']['10']), reverse=True)
        rows[fid] = {'feature_id': fid, 'name': feature['properties'].get('name', ''), 'kind': 'addition' if fid in additions else 'geometry',
                     'length_m': round(line.length, 1), 'classification': classify(visible, line.length), 'visible_city_coverage': visible,
                     'datasets': groups, 'matches': matches}
    mapped = {tid for source in sources for tid in tilesets if tid.split('.', 1)[1].startswith(source['dataset'] + '-')}
    return {'schema_version': 1, 'checked_at': now(), 'plan_hash': plan['approval_hash'], 'style_hash': digest(style),
            'method': {'projection': 'EPSG:32617 (meters)', 'distance_bands_m': [1, 3, 10, 20],
                       'interpretation': 'Fraction of City line length within a buffer of existing lines. Nearby parallel trails can match; proximity is not proof of identity, access, or superior accuracy. Reverse coverage identifies existing geometry that must be retained.'},
            'summary': dict(Counter(row['classification'] for row in rows.values() if row['kind'] == 'addition')),
            'sources': sources, 'skipped_datasets': skipped, 'uncompared_tilesets': sorted(set(tilesets) - mapped),
            'rows': rows, 'reference_features': list(reference_features.values())}
