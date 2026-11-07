"""Reconcile the approved County source with explicit, hash-bound legacy dispositions."""
import argparse
import copy
from collections import Counter, defaultdict
from pathlib import Path

from .albemarle import normalize_trails
from .albemarle_review import color_for
from .common import ROOT, configs, digest, now, read_json, write_json
from .geo import canonical, changes, fingerprint
from .mapbox import target_by_id, validate_plan
from .overlaps import geometry_tools


def verify_cleanup_tiles(expected, observed):
    """Reject superseded GPS geometry in sampled, quantized public tile fragments."""
    project, union, _ = geometry_tools()
    if not observed['features']:
        raise ValueError('No Strava tile geometry was sampled')
    corridor = union([project(f['geometry']) for f in expected['features']]).buffer(3)
    failures = []
    for f in observed['features']:
        g = project(f['geometry'])
        outside = g.difference(corridor).length
        if outside > 5:
            failures.append({'fragment': f['id'], 'unmatched_metres': round(outside, 2)})
    return {'sampled_fragments': len(observed['features']), 'tolerance_m': 3,
        'unmatched_threshold_m': 5, 'failures': failures, 'passed': not failures}


def trim_covered(feature, incoming, distance):
    """Keep unmatched old geometry and join cut endpoints to the replacement network."""
    from pyproj import Transformer
    from shapely.geometry import LineString, Point, mapping
    from shapely.ops import nearest_points, transform
    project, union, _ = geometry_tools()
    inverse = Transformer.from_crs('EPSG:32617', 'EPSG:4326', always_xy=True).transform
    original = project(feature['geometry'])
    network = union([project(f['geometry']) for f in incoming])
    remainder = original.difference(network.buffer(distance))
    parts, joins = [], []
    for line in getattr(remainder, 'geoms', [remainder]):
        if line.is_empty or line.geom_type != 'LineString' or line.length < .001:
            continue
        coords = list(line.coords)
        for i in (0, -1):
            point = Point(coords[i])
            gap = point.distance(network)
            # Only new cut boundaries are joined; never move original distant endpoints.
            if abs(gap - distance) < .1:
                closest = nearest_points(point, network)[1]
                joins.append({'before': list(inverse(*coords[i])), 'after': list(inverse(closest.x, closest.y)), 'distance_m': gap})
                if i == 0:
                    coords.insert(0, closest.coords[0])
                else:
                    coords.append(closest.coords[0])
        parts.append(LineString(coords))
    if not parts:
        raise ValueError('Trim would remove the whole retained feature; use an explicit replacement disposition')
    from shapely.geometry import MultiLineString
    f = copy.deepcopy(feature)
    f['geometry'] = mapping(transform(inverse, parts[0] if len(parts) == 1 else MultiLineString(parts)))
    # GeoJSON coordinates must be arrays, including before canonical validation.
    import json
    f['geometry'] = json.loads(json.dumps(f['geometry']))
    # Projection round trips can turn an existing six-decimal vertex into e.g.
    # 37.927065999999996. Remove sub-micrometre noise before the API's six-decimal
    # storage conversion, while leaving approved upstream GIS geometry untouched.
    def stable_coordinates(value):
        return [stable_coordinates(v) for v in value] if isinstance(value, list) else round(value, 12)
    f['geometry']['coordinates'] = stable_coordinates(f['geometry']['coordinates'])
    return f, {'retained_length_m': sum(g.length for g in parts), 'original_length_m': original.length, 'joins': joins}


def reconcile(source, county, strava, manifest, style):
    for key, actual in [('source_hash', digest(source)), ('county_hash', fingerprint(county)),
                        ('strava_hash', fingerprint(strava)), ('style_hash', digest(style))]:
        if manifest[key] != actual:
            raise ValueError('Reconciliation input changed: ' + key)
    if not manifest.get('publication_authorized') or manifest.get('authorization') != 'ship it':
        raise ValueError('Expected explicit publication authorization for this reconciliation')
    incoming = {f['id']: copy.deepcopy(f) for f in source['features']}
    if set(incoming) != set(manifest['accepted_source_ids']):
        raise ValueError('Reconciliation must account for every accepted source geometry')
    if len(manifest['accepted_source_ids']) != len(incoming):
        raise ValueError('Duplicate accepted source ID')
    old = {f['id']: f for f in county['features']}
    rules = manifest['county_dispositions']
    if set(rules) != set(old):
        raise ValueError('Every existing County feature needs an explicit disposition')
    lineage = defaultdict(list)
    for fid, rule in rules.items():
        if rule['action'] not in {'retain', 'replace', 'trim'} or not rule.get('reason'):
            raise ValueError('Invalid legacy disposition')
        for sid in rule.get('source_ids', []):
            if sid not in incoming:
                raise ValueError('Legacy disposition references unaccepted source geometry')
            lineage[sid].append(fid)
        if rule['action'] != 'retain' and not rule.get('source_ids'):
            raise ValueError('Replacement or trim needs explicit source geometry')
    reused, after, trim_report = set(), [], {}
    for sid, feature in incoming.items():
        fid = manifest['legacy_ids'].get(sid, sid)
        if fid in reused or (fid in old and rules[fid]['action'] != 'replace'):
            raise ValueError('Legacy identity collision or attempted replacement of retained feature')
        if sid in manifest['legacy_ids'] and (fid not in old or sid not in rules[fid]['source_ids']):
            raise ValueError('Legacy identity lacks an explicit replacement relationship')
        reused.add(fid)
        feature['id'] = fid
        if fid in old:
            feature['properties'] = {**old[fid]['properties'], **feature['properties']}
        feature['properties']['reviewed_source_id'] = sid
        feature['properties']['legacy_feature_ids'] = ','.join(sorted(str(fid) for fid in lineage[sid]))
        if sid in manifest.get('continuity_colors', {}):
            choice = manifest['continuity_colors'][sid]
            feature['properties'].update({'TrailName': choice['TrailName'], 'color': choice['color']})
            if color_for(style, choice['TrailName']) != choice['color']:
                raise ValueError('Continuity alias does not match the captured palette')
        after.append(feature)
    for fid, feature in old.items():
        rule = rules[fid]
        if rule['action'] == 'retain':
            after.append(copy.deepcopy(feature))
        elif rule['action'] == 'trim':
            f, detail = trim_covered(feature, [incoming[s] for s in rule['source_ids']], rule['distance_m'])
            after.append(f)
            trim_report[fid] = detail
    county_after = canonical({'type': 'FeatureCollection', 'features': after})
    strava_old = {f['id']: f for f in strava['features']}
    if set(manifest['strava_dispositions']) - set(strava_old):
        raise ValueError('Missing Strava feature in reviewed reconciliation')
    strava_after, strava_trims = [], {}
    for fid, feature in strava_old.items():
        rule = manifest['strava_dispositions'].get(fid, {'action': 'retain'})
        if rule['action'] == 'retain':
            strava_after.append(copy.deepcopy(feature))
        elif rule['action'] in {'trim', 'replace'}:
            if not rule.get('reason') or not rule.get('source_ids') or set(rule['source_ids']) - set(incoming):
                raise ValueError('Strava change lacks reviewed replacement geometry')
            if any(incoming[s]['properties']['park_id'] != 'biscuit-run' for s in rule['source_ids']):
                raise ValueError('Strava cleanup is limited to reviewed Biscuit geometry')
            if rule['action'] == 'trim':
                f, detail = trim_covered(feature, [incoming[s] for s in rule['source_ids']], rule['distance_m'])
                strava_after.append(f)
                strava_trims[fid] = detail
        else:
            raise ValueError('Unknown Strava disposition')
    return county_after, canonical({'type': 'FeatureCollection', 'features': strava_after}), {
        'county_trims': trim_report, 'strava_trims': strava_trims,
        'county_dispositions': dict(Counter(r['action'] for r in rules.values())),
        'legacy_ids_reused': len(manifest['legacy_ids']), 'accepted_source_features': len(incoming)}


def build(source_path, inventory, manifest_path, output):
    manifest = read_json(manifest_path)
    raw = read_json(source_path)
    source = normalize_trails(raw, configs('albemarle')[0], 'county-gis')
    county_target, strava_target = target_by_id('albemarle'), target_by_id('strava')
    county = read_json(inventory / 'datasets' / (county_target['dataset'] + '.geojson'))
    strava = read_json(inventory / 'datasets' / (strava_target['dataset'] + '.geojson'))
    style = read_json(inventory / 'style.json')
    after, strava_after, detail = reconcile(source, county, strava, manifest, style)
    policy = read_json(ROOT / 'config/park-ownership.json')
    for protected in policy['protected_datasets']:
        data = read_json(inventory / 'datasets' / (protected['dataset'] + '.geojson'))
        if fingerprint(data) != manifest['protected_hashes'][protected['dataset']]:
            raise ValueError('Protected network differs from the reconciliation inventory')
    audit = {'kind': 'albemarle-publication-preparation', 'created_at': now(),
        'manifest_hash': digest(manifest), 'raw_source_hash': digest(raw), **detail, 'plans': {}}
    metadata = {d['id']: d for d in read_json(inventory / 'datasets.json')}
    for target, before, candidate in [(county_target, county, after), (strava_target, strava, strava_after)]:
        candidate['ingest_report'] = {'albemarle_reconciliation': True, 'publication_authorized': True,
            'reviewed_before_hash': fingerprint(before), 'reviewed_target': target,
            'manifest_hash': digest(manifest), 'raw_source_hash': digest(raw),
            'park_consolidation': True, 'ownership_policy_hash': digest(policy),
            'protected_hashes': manifest['protected_hashes']}
        plan = {'schema_version': 1, 'created_at': now(), 'target': target,
            'evidence': 'User: ship it. Completed geometry/color/access feedback and exact dispositions in ' + str(manifest_path),
            'dataset_modified': metadata[target['dataset']]['modified'], 'ingest_report': candidate['ingest_report'],
            'before_hash': fingerprint(before), 'after_hash': fingerprint(candidate),
            'changes': changes(before, candidate), 'before': canonical(before), 'after': canonical(candidate)}
        plan['approval_hash'] = digest(plan)
        validate_plan(plan, plan['approval_hash'])
        write_json(output / (target['id'] + '-candidate.geojson'), candidate)
        write_json(output / (target['id'] + '-plan.json'), plan)
        audit['plans'][target['id']] = {'approval_hash': plan['approval_hash'], 'before_hash': plan['before_hash'],
            'after_hash': plan['after_hash'], 'changes': {k: len(v) for k, v in plan['changes'].items()},
            'before_features': len(before['features']), 'after_features': len(candidate['features'])}
    write_json(output / 'preparation.json', audit)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'inventory', 'manifest', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(build(args.source, args.inventory, args.manifest, args.output))


if __name__ == '__main__':
    main()
