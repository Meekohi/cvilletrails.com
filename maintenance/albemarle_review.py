"""Compare County GIS to a frozen inventory without choosing replacements or writing Mapbox."""
import argparse
import copy
import re
import shutil
from collections import Counter
from pathlib import Path

from .albemarle import clean, locations, normalize_trails, screen
from .common import ROOT, configs, digest, now, read_json, write_json
from .geo import canonical, fingerprint
from .mapbox import target_by_id
from .overlaps import coverage, geometry_tools
from .state_parks import bounds


def color_for(style, name):
    layer = next((l for l in style['layers'] if l['id'] == 'albemarle-trail'), None)
    if not layer:
        raise ValueError('County style layer is missing; review the palette before comparing')
    expression = layer['paint']['line-color']
    if not isinstance(expression, list) or expression[:2] != ['match', ['get', 'TrailName']]:
        raise ValueError('County color expression changed; review the palette before comparing')
    for keys, color in zip(expression[2:-1:2], expression[3:-1:2]):
        if name in (keys if isinstance(keys, list) else [keys]):
            return color
    return expression[-1]


def pair_metrics(line, other):
    forward, reverse = coverage(line, other, (3, 10, 20)), coverage(other, line, (3, 10, 20))
    shared = min(line.length * forward['10'], other.length * reverse['10'])
    if shared < min(10, min(line.length, other.length) * .8):
        return None
    if max(forward['10'], reverse['10']) < .1:
        return None
    return {'source_coverage': forward, 'existing_coverage': reverse,
            'source_length_m': round(line.length, 2), 'existing_length_m': round(other.length, 2),
            'length_ratio': round(min(line.length, other.length) / max(line.length, other.length), 4)}


def strong_pair(match):
    return min(match['source_coverage']['3'], match['existing_coverage']['3'], match['length_ratio']) >= .98


def compare(source, baseline, config, style, references=()):
    """All identity matches are suggestions. Unmatched old features remain untouched."""
    project, union, Tree = geometry_tools()
    before = canonical(baseline)
    normalized = normalize_trails(source, config, 'county-gis')
    incoming = {f['id']: f for f in normalized['features']}
    rows = screen(source, config)
    aliases = locations(config)
    old = before['features']
    if any(f['geometry']['type'] not in {'LineString', 'MultiLineString'} for f in old):
        raise ValueError('County baseline contains non-line geometry; review it before comparison')
    old_lines = [project(f['geometry']) for f in old]
    if any(g.is_empty or g.length == 0 for g in old_lines):
        raise ValueError('County baseline contains empty lines')
    tree = Tree(old_lines)
    old_rows = {f['id']: {'id': f['id'], 'name': f['properties'].get('TrailName'),
        'park_id': aliases.get(clean(f['properties'].get('LocationNa')).casefold(), ('outside-scope',))[0],
        'location': f['properties'].get('LocationNa'), 'matches': [], 'eligible_matches': [],
        'length_m': round(g.length, 2)} for f, g in zip(old, old_lines)}
    source_lines, eligible_by_old = {}, {}
    for original, row in zip(source['features'], rows):
        row['matches'] = []
        row['other_overlaps'] = []
        if not row['geometry_valid']:
            continue
        line = project(original['geometry'])
        source_lines[row['id']] = line
        row['length_m'] = round(line.length, 2)
        for index in tree.query(line.buffer(20)):
            index = int(index)
            match = pair_metrics(line, old_lines[index])
            if not match:
                continue
            existing = old[index]
            p = existing['properties']
            same_park = row['park_id'] == old_rows[existing['id']]['park_id'] != 'outside-scope'
            match.update({'existing_id': existing['id'], 'existing_name': p.get('TrailName'),
                          'same_park': same_park, 'conflicts': []})
            if row['category'] == 'eligible':
                new_props = incoming[row['id']]['properties']
                # Nearby junctions are useful geometry context, not evidence of a renamed trail.
                if same_park and max(match['source_coverage']['10'], match['existing_coverage']['10']) >= .5:
                    for key in ('TrailName', 'Hiking', 'Biking', 'Equestrian', 'Surface', 'Ownership'):
                        if p.get(key) != new_props.get(key):
                            match['conflicts'].append({'property': key, 'existing': p.get(key), 'source': new_props.get(key)})
                    a, b = color_for(style, p.get('TrailName')), color_for(style, new_props['TrailName'])
                    if a != b:
                        match['conflicts'].append({'property': 'rendered_color', 'existing': a, 'source': b})
                eligible_by_old.setdefault(existing['id'], []).append((row['id'], match))
                old_rows[existing['id']]['eligible_matches'].append(row['id'])
            row['matches'].append(match)
            old_rows[existing['id']]['matches'].append(row['id'])
        row['matches'].sort(key=lambda m: (-min(m['source_coverage']['3'], m['existing_coverage']['3']),
                                           -m['source_coverage']['10'], m['existing_id']))
    by_id = {r['id']: r for r in rows}
    crosswalk = []
    for row in rows:
        if row['category'] == 'held':
            row['comparison'] = 'held'
            continue
        qualified = [m for m in row['matches'] if m['same_park'] and strong_pair(m)]
        row['comparison'] = 'overlap-needs-review' if row['matches'] else 'new-coverage'
        if len(qualified) == 1:
            match = qualified[0]
            competitors = [fid for fid, m in eligible_by_old[match['existing_id']] if m['same_park'] and strong_pair(m)]
            if len(competitors) == 1:
                row['comparison'] = 'one-to-one-suggestion'
                row['suggested_existing_id'] = match['existing_id']
                crosswalk.append({'source_id': row['id'], 'global_id': row['global_id'],
                    'existing_id': match['existing_id'], 'approved': False, 'metrics': match})
        row['color_conflict'] = any(any(c['property'] == 'rendered_color' for c in m['conflicts']) for m in row['matches'])
    # Reverse coverage catches missing legs even where a short replacement looks like a match.
    for feature, line in zip(old, old_lines):
        row = old_rows[feature['id']]
        lines = [source_lines[fid] for fid in row['eligible_matches']]
        row['eligible_coverage'] = coverage(line, union(lines), (3, 10, 20)) if lines else {'3': 0, '10': 0, '20': 0}
        row['comparison'] = ('no-eligible-counterpart' if not lines else
                             'coverage-gap' if row['eligible_coverage']['10'] < .98 else 'covered-needs-review')
    # Flag duplicate/near-identical eligible source records, regardless of their IDs or names.
    eligible = [r for r in rows if r['category'] == 'eligible']
    lines = [source_lines[r['id']] for r in eligible]
    duplicates, source_tree = [], Tree(lines)
    for i, line in enumerate(lines):
        for index in source_tree.query(line.buffer(3)):
            j = int(index)
            if j <= i:
                continue
            metrics = pair_metrics(line, lines[j])
            if metrics and strong_pair(metrics):
                pair = [eligible[i]['id'], eligible[j]['id']]
                duplicates.append(pair)
                for fid in pair:
                    by_id[fid].setdefault('duplicate_candidates', []).append(next(x for x in pair if x != fid))
    # Other editable, visible trail datasets are context; the protected Rivanna route stays intact.
    reference_lines = [project(f['geometry']) for f in references]
    reference_tree = Tree(reference_lines)
    for row in eligible:
        line = source_lines[row['id']]
        for index in reference_tree.query(line.buffer(20)):
            index = int(index)
            metrics = pair_metrics(line, reference_lines[index])
            if metrics:
                f = references[index]
                row['other_overlaps'].append({'key': f['id'], 'dataset_name': f['properties']['review_dataset'],
                    'protected': f['properties']['review_protected'], **metrics})
        row['other_overlaps'].sort(key=lambda m: (-m['source_coverage']['10'], m['key']))
    parks = []
    for park_id in sorted({r['park_id'] for r in rows} | {r['park_id'] for r in old_rows.values()}):
        group = [r for r in rows if r['park_id'] == park_id]
        previous = [r for r in old_rows.values() if r['park_id'] == park_id]
        geometry = [f for f, r in zip(source['features'], rows) if r['park_id'] == park_id and r['geometry_valid']]
        geometry.extend(f for f in old if old_rows[f['id']]['park_id'] == park_id)
        parks.append({'id': park_id, 'name': config['locations'].get(park_id, {}).get('legacy_location', 'Other / unassigned locations'),
            'bounds': bounds(geometry), 'source_counts': dict(Counter(r['category'] for r in group)),
            'comparison_counts': dict(Counter(r['comparison'] for r in group)), 'existing_count': len(previous),
            'coverage_gaps': sum(r['comparison'] != 'covered-needs-review' for r in previous),
            'color_conflicts': sum(r.get('color_conflict', False) for r in group),
            'other_overlaps': sum(bool(r['other_overlaps']) for r in group)})
    report = {'schema_version': 1, 'kind': 'albemarle-gis-validation', 'created_at': now(),
        'review_only': True, 'publication_authorized': False, 'source_hash': digest(source),
        'baseline_hash': fingerprint(before), 'style_hash': digest(style),
        'policy_hash': normalized['ingest_report']['policy_hash'],
        'overrides_hash': normalized['ingest_report']['overrides_hash'],
        'method': {'projection': 'EPSG:32617 (metres)', 'distance_bands_m': [3, 10, 20],
            'identity_suggestion': 'Mutually unique same-park pair with >=98% bidirectional coverage at 3m and >=98% length ratio. Not identity proof or approval.',
            'limitations': 'Nearby parallel trails may match. Split/merge candidates and unmatched old lines require visual review. GIS eligibility does not supersede operator alerts.'},
        'counts': {'source': len(rows), 'eligible': len(eligible), 'held': len(rows) - len(eligible),
            'existing_preserved': len(old), 'crosswalk_suggestions': len(crosswalk),
            'existing_coverage_gaps': sum(r['comparison'] != 'covered-needs-review' for r in old_rows.values()),
            'source_duplicate_pairs': len(duplicates), 'color_conflicts': sum(r.get('color_conflict', False) for r in rows),
            'other_dataset_overlaps': sum(bool(r['other_overlaps']) for r in rows)},
        'held_reasons': normalized['ingest_report']['held_reasons'], 'parks': parks, 'rows': rows,
        'existing_rows': list(old_rows.values()), 'crosswalk_suggestions': crosswalk, 'source_duplicate_pairs': duplicates}
    return report, normalized


def reference_data(inventory, target, policy):
    style, tilesets = read_json(inventory / 'style.json'), read_json(inventory / 'tilesets.json')
    protected = {d['dataset'] for d in policy['protected_datasets']}
    features, sources, mapped = [], [], set()
    for dataset in read_json(inventory / 'datasets.json'):
        ids = [tid for tid in tilesets if tid.split('.', 1)[1].startswith(dataset['id'] + '-')]
        mapped.update(ids)
        layers = {l['id'] for tid in ids for l in tilesets[tid]['vector_layers']}
        visible = any(l.get('source-layer') in layers and l['type'] == 'line' and l.get('layout', {}).get('visibility') != 'none' for l in style['layers'])
        if not visible or dataset['id'] == target['dataset']:
            continue
        data = canonical(read_json(inventory / 'datasets' / (dataset['id'] + '.geojson')))
        sources.append({'id': dataset['id'], 'name': dataset['name'], 'hash': fingerprint(data), 'protected': dataset['id'] in protected})
        for f in data['features']:
            if f['geometry']['type'] in {'LineString', 'MultiLineString'}:
                f = copy.deepcopy(f)
                f['id'] = dataset['id'] + '/' + f['id']
                f['properties'].update({'review_dataset': dataset['name'], 'review_protected': dataset['id'] in protected})
                features.append(f)
    return features, sources, sorted(set(tilesets) - mapped)


def build(source_path, inventory, output):
    config = configs('albemarle')[0]
    target = target_by_id('albemarle')
    source = read_json(source_path)
    baseline = canonical(read_json(inventory / 'datasets' / (target['dataset'] + '.geojson')))
    style = read_json(inventory / 'style.json')
    policy = read_json(ROOT / 'config/park-ownership.json')
    references, reference_sources, uncompared = reference_data(inventory, target, policy)
    report, normalized = compare(source, baseline, config, style, references)
    report.update({'target': target, 'inventory_captured_at': read_json(inventory / 'inventory.json')['captured_at'],
        'ownership_policy_hash': digest(policy), 'reference_sources': reference_sources,
        'uncompared_tilesets': uncompared,
        'code_hash': digest({p: (ROOT / p).read_text() for p in ['maintenance/albemarle.py', 'maintenance/albemarle_review.py',
            'maintenance/overlaps.py', 'maintenance/geo.py', 'maintenance/albemarle_review_ui/index.html',
            'maintenance/albemarle_review_ui/review.js', 'maintenance/albemarle_review_ui/review.css']}),
        'notice': 'Validation round only. Every existing County feature is preserved; Rivanna and all other datasets are unchanged. Export records review feedback, not publication approval.'})
    report['review_hash'] = digest(report)
    normalized_by_id = {f['id']: f for f in normalized['features']}
    source_preview = []
    for original, row in zip(source['features'], report['rows']):
        if row['geometry_valid']:
            f = copy.deepcopy(original)
            f['id'] = row['id']
            style_name = normalized_by_id.get(row['id'], {}).get('properties', {}).get('TrailName', row['name'])
            f['properties'].update({'review_park': row['park_id'], 'review_category': row['category'],
                'review_id': row['id'], 'review_color': color_for(style, style_name)})
            source_preview.append(f)
    before_preview = copy.deepcopy(baseline)
    old_rows = {r['id']: r for r in report['existing_rows']}
    for f in before_preview['features']:
        f['properties'].update({'review_id': f['id'], 'review_park': old_rows[f['id']]['park_id'],
                               'review_color': color_for(style, f['properties'].get('TrailName'))})
    for name, value in [('review.json', report), ('screened.geojson', normalized), ('preserved.geojson', baseline),
        ('source.geojson', {'type': 'FeatureCollection', 'features': source_preview}), ('existing.geojson', before_preview),
        ('references.geojson', {'type': 'FeatureCollection', 'features': references})]:
        write_json(output / name, value)
    token = re.search(r"mapboxgl.accessToken = '(pk\.[^']+)'", (ROOT / 'assets/app.js').read_text())[1]
    write_json(output / 'preview.json', {'public_token': token})
    for name in ('index.html', 'review.js', 'review.css'):
        shutil.copy(ROOT / 'maintenance/albemarle_review_ui' / name, output / name)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--inventory', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = build(args.source, args.inventory, args.output)
    print({'counts': report['counts'], 'review_hash': report['review_hash']})


if __name__ == '__main__':
    main()
