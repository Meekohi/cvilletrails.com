"""Prepare one statewide sanity check without approving parks or publishing data."""
import argparse
import copy
import re
import shutil
from collections import Counter
from pathlib import Path

from .common import ROOT, configs, digest, now, read_json, write_json
from .geo import canonical, changes, fingerprint
from .mapbox import stored_coordinates, target_by_id, validate_plan
from .overlaps import compare_overlaps, coverage, geometry_tools
from .state_parks import bounds, clean, global_id, hold_reasons, normalize_trails


def color_key(properties):
    value = clean(properties.get('BlazeColor')).lower()
    return 'none' if value in {'', 'none', 'n/a', 'not marked'} else value


def prepare(source, baseline, config, registry, policy):
    """Use the pilot normalizer with a temporary, explicitly unapproved scope."""
    before = canonical(baseline)
    existing = {f['id']: f for f in before['features']}
    candidate_config = copy.deepcopy(config)
    overrides = read_json(config['_directory'] / 'overrides.json')
    names = sorted({clean(f['properties'].get('LABEL')) for f in source['features']} - {''})
    systems = []
    for name in names:
        if name in config['approved_parks']:
            continue
        sid = 'dcr-' + re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        candidate_config['approved_parks'][name] = {'system_id': sid, 'palette': policy['palette']}
        candidate_config['system_ids'].append(sid)
        systems.append({'id': sid, 'name': name, 'url': registry.get(name, {}).get('visitor_guide'),
                        'status': 'proposed-context-only; visitor details not researched'})
    seen, rows, eligible = set(), [], []
    for original in source['features']:
        gid = global_id(original)
        if gid in seen:
            raise ValueError('Duplicate DCR GlobalID')
        seen.add(gid)
        fid = 'va-state-parks:' + gid
        props = original['properties']
        park = clean(props.get('LABEL')) or '(unassigned)'
        reasons = hold_reasons(original, overrides.get(gid, {}).get('properties', {}))
        if gid in config.get('held_features', {}):
            reasons.append(config['held_features'][gid])
        park_policy = candidate_config['approved_parks'].get(park)
        if park_policy and color_key(props) not in park_policy.get('palette', candidate_config.get('palette', {})):
            reasons.append('unresolved blaze color: ' + clean(props.get('BlazeColor')))
        # Validate coordinates even for held records; keep invalid shapes out of the preview.
        geometry_valid = True
        try:
            canonical({'type': 'FeatureCollection', 'features': [{**original, 'id': fid}]})
        except ValueError:
            reasons.append('invalid geometry')
            geometry_valid = False
        row = {'id': fid, 'park': park, 'name': clean(props.get('Trail_Name')), 'uses': props.get('Trail_User'),
               'blaze': props.get('BlazeColor'), 'status': props.get('Status'), 'reasons': reasons,
               'category': 'held' if reasons else 'candidate', 'geometry_valid': geometry_valid}
        if not reasons:
            eligible.append(original)
        rows.append(row)
    if set(config.get('held_features', {})) - seen:
        raise ValueError('Explicitly held DCR feature disappeared; review the source change')
    # Holds were checked against the complete source above; the adapter sees only screened rows.
    adapter_config = {**candidate_config, 'held_features': {}}
    normalized = normalize_trails({'type': 'FeatureCollection', 'features': eligible}, adapter_config, 'trails-gis')
    additions = []
    normalized_by_id = {f['id']: f for f in normalized['features']}
    for row in rows:
        if row['id'] in existing:
            incoming = normalized_by_id.get(row['id'])
            stored = copy.deepcopy(incoming)
            if stored:
                stored['geometry']['coordinates'] = stored_coordinates(stored['geometry']['coordinates'])
            unchanged = incoming == existing[row['id']] or stored == existing[row['id']]
            row['category'] = 'existing' if unchanged else 'existing-change'
            if not unchanged:
                row['reasons'].append('existing trail differs from source; preserved unchanged')
        elif row['category'] == 'candidate':
            additions.append(normalized_by_id[row['id']])
    # Never silently overwrite or remove a previously published trail in a batch of additions.
    stale = [f['id'] for f in before['features'] if f['properties'].get('pipeline_id') == config['id'] and f['id'] not in {'va-state-parks:' + gid for gid in seen}]
    candidate = canonical({'type': 'FeatureCollection', 'features': before['features'] + additions})
    candidate['ingest_report'] = {'state_parks_batch': True, 'publication_authorized': False,
        'source_hash': digest(source), 'candidate_policy_hash': digest(policy), 'pipeline_policy_hash': digest({k:v for k,v in config.items() if k != '_directory'}),
        'normalizer_code_hash': digest((ROOT / 'maintenance/state_parks.py').read_bytes()),
        'overrides_hash': digest(overrides), 'reviewed_before_hash': fingerprint(before), 'reviewed_target': target_by_id('strava'),
        'preserved_features': len(before['features']), 'proposed_additions': len(additions), 'missing_source_ids_preserved': stale}
    for system in systems:
        system['bounds'] = bounds([f for f in additions if f['properties']['system_id'] == system['id']])
    return candidate, rows, systems


def internal_overlaps(features):
    project, _, Tree = geometry_tools()
    lines = [project(f['geometry']) for f in features]
    tree = Tree(lines)
    pairs = []
    for i, line in enumerate(lines):
        for index in tree.query(line.buffer(10)):
            j = int(index)
            if j <= i:
                continue
            forward = coverage(line, lines[j], (3, 10))
            reverse = coverage(lines[j], line, (3, 10))
            # Ignore junctions and crossings; flag long shared sections or a mostly duplicated short trail.
            shared = min(line.length * forward['10'], lines[j].length * reverse['10'])
            if shared < 50 or max(forward['10'], reverse['10']) < .5:
                continue
            pairs.append({'a': features[i]['id'], 'b': features[j]['id'], 'shared_m_approx': round(shared, 1),
                          'a_coverage': forward, 'b_coverage': reverse})
    return pairs


def build(source_path, inventory, output):
    config = configs('virginia-state-parks')[0]
    policy = read_json(config['_directory'] / 'candidate-policy.json')
    registry = read_json(config['_directory'] / 'parks.json')
    source = read_json(source_path)
    target = target_by_id('strava')
    baseline = read_json(inventory / 'datasets' / (target['dataset'] + '.geojson'))
    candidate, rows, systems = prepare(source, baseline, config, registry, policy)
    metadata = next(d for d in read_json(inventory / 'datasets.json') if d['id'] == target['dataset'])
    plan = {'schema_version': 1, 'created_at': now(), 'target': target,
            'evidence': 'Statewide candidate for user sanity check; not yet approved. Review report binds this plan hash.',
            'dataset_modified': metadata['modified'], 'ingest_report': candidate['ingest_report'],
            'before_hash': fingerprint(baseline), 'after_hash': fingerprint(candidate),
            'changes': changes(baseline, candidate), 'before': canonical(baseline), 'after': canonical(candidate)}
    plan['approval_hash'] = digest(plan)
    validate_plan(plan, plan['approval_hash'])
    overlaps = compare_overlaps(plan, inventory)
    additions = [f for f in candidate['features'] if f['id'] in set(plan['changes']['added'])]
    pairs = internal_overlaps(additions)
    by_id = {row['id']: row for row in rows}
    for fid, row in overlaps['rows'].items():
        if row['classification'] in {'partial-overlap', 'strong-overlap', 'close-match'}:
            by_id[fid]['overlaps'] = [m for m in row['matches'] if m['role'] == 'trail-lines']
    for pair in pairs:
        for fid in (pair['a'], pair['b']):
            by_id[fid].setdefault('source_overlaps', []).append(pair)
    features = []
    for original in source['features']:
        fid = 'va-state-parks:' + global_id(original)
        row = by_id[fid]
        if not row['geometry_valid']:
            continue
        f = copy.deepcopy(original)
        f['id'] = fid
        color = next((f['properties']['display_color'] for f in additions if f['id'] == fid), None)
        color = color or config['approved_parks'].get(row['park'], {}).get('palette', policy['palette']).get(color_key(original['properties']), '#888888')
        f['properties'].update({'review_id': fid, 'review_park': row['park'], 'review_category': row['category'],
            'review_attention': bool(row.get('overlaps') or row.get('source_overlaps') or row['category'] == 'existing-change'),
            'display_color': color, 'name': row['name']})
        features.append(f)
    parks = []
    for name in sorted({r['park'] for r in rows}):
        group = [r for r in rows if r['park'] == name]
        parks.append({'name': name, 'bounds': bounds([f for f in features if f['properties']['review_park'] == name]),
                      'candidate_bounds': bounds([f for f in features if f['properties']['review_park'] == name and f['properties']['review_category'] in {'candidate', 'existing'}]),
                      'counts': dict(Counter(r['category'] for r in group)),
                      'attention': sum(bool(r.get('overlaps') or r.get('source_overlaps') or r['category'] == 'existing-change') for r in group),
                      'sources': registry.get(name, {}), 'rows': group})
    report = {'schema_version': 1, 'kind': 'virginia-state-parks-batch', 'created_at': now(),
              'source_hash': digest(source), 'plan_hash': plan['approval_hash'], 'policy_hash': digest(policy),
              'inventory_captured_at': read_json(inventory / 'inventory.json')['captured_at'],
              'style_hash': overlaps['style_hash'], 'counts': dict(Counter(r['category'] for r in rows)),
              'park_count': len(parks) - int(any(p['name'] == '(unassigned)' for p in parks)),
              'candidate_park_count': sum(p['counts'].get('candidate', 0) > 0 for p in parks),
              'attention_count': sum(p['attention'] for p in parks), 'held_reasons': dict(Counter(reason for r in rows if r['category'] == 'held' for reason in r['reasons'])),
              'parks': parks, 'missing_source_ids_preserved': candidate['ingest_report']['missing_source_ids_preserved'],
              'overlap_scope': {'sources': overlaps['sources'], 'uncompared_tilesets': overlaps['uncompared_tilesets'],
                  'note': 'Editable visible custom trail datasets screened at 3/10/20 metres. Background Mapbox roads/paths are not replacements for curated trails. Unmapped custom tilesets remain visible for visual comparison.'},
              'color_note': policy['color_note'], 'internal_overlap_pairs': pairs}
    report['review_hash'] = digest(report)
    for name, value in [('review.json', report), ('trails.geojson', {'type': 'FeatureCollection', 'features': features}),
                        ('candidate.geojson', candidate), ('additions.geojson', {'type': 'FeatureCollection', 'features': additions}),
                        ('plan.json', plan), ('overlaps.json', overlaps), ('systems-proposal.json', systems),
                        ('existing-overlaps.geojson', {'type': 'FeatureCollection', 'features': overlaps['reference_features']})]:
        write_json(output / name, value)
    token = re.search(r"mapboxgl.accessToken = '(pk\.[^']+)'", (ROOT / 'assets/app.js').read_text())[1]
    write_json(output / 'preview.json', {'public_token': token, 'style': 'mapbox://styles/meekohi/ckkolybrr6tjx17mjqflqw16b'})
    shutil.copy(ROOT / 'maintenance/state_parks_batch_preview.html', output / 'index.html')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = build(args.source, args.inventory, args.output)
    print({key: report[key] for key in ('counts', 'candidate_park_count', 'attention_count', 'review_hash')})


if __name__ == '__main__':
    main()
