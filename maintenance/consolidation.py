"""Prepare reviewable park ownership candidates while retaining protected networks."""
import copy
import re
import shutil
from pathlib import Path
from .common import ROOT, digest, now, read_json, write_json
from .geo import canonical, changes, fingerprint
from .overlaps import geometry_tools
from .review_map import verify_plan


def validate_decisions(report, decisions):
    if digest({k: v for k, v in report.items() if k != 'review_hash'}) != report['review_hash']:
        raise ValueError('Park review contents do not match their hash')
    if decisions.get('review_hash') != report['review_hash'] or decisions.get('plan_hash') != report['plan_hash']:
        raise ValueError('Park decisions belong to another review')
    parks = {p['id']: p for p in report['parks']}
    for pid, choice in decisions.get('decisions', {}).items():
        if pid not in parks or choice.get('decision') not in {'choose', 'discuss', 'unreviewed'}:
            raise ValueError('Unknown park or decision')
        if choice.get('decision') == 'choose' and choice.get('dataset') not in {s['dataset'] for s in parks[pid]['datasets']}:
            raise ValueError('Selected dataset was not present in the reviewed park')


def protected_ids(policy):
    return {p['dataset'] for p in policy['protected_datasets'] if p.get('retain_entire_dataset')}


def preserve_protected(before, after, policy):
    for did in protected_ids(policy):
        if did not in before or did not in after or fingerprint(before[did]) != fingerprint(after[did]):
            raise ValueError('Park consolidation cannot modify the protected Rivanna network')


def prepare_consolidation(plan, report, decisions, policy, inventory_dir, output):
    project, union, _ = geometry_tools()
    from pyproj import Transformer
    from shapely.geometry import mapping
    from shapely.ops import transform
    verify_plan(plan)
    validate_decisions(report, decisions)
    if report['plan_hash'] != plan['approval_hash']: raise ValueError('Park report and proposal differ')
    inverse = Transformer.from_crs('EPSG:32617', 'EPSG:4326', always_xy=True).transform
    parks = {p['id']: p for p in report['parks']}
    root, output = Path(inventory_dir), Path(output)
    style = read_json(root / 'style.json')
    if digest(style) != report['style_hash']:
        raise ValueError('Style inventory changed since park review')
    before = {}
    for source in report['sources']:
        data = read_json(root / 'datasets' / f"{source['dataset']}.geojson")
        if fingerprint(data) != source['hash']: raise ValueError('Inventory changed since park review')
        before[source['dataset']] = canonical(data)
    if fingerprint(before[plan['target']['dataset']]) != plan['before_hash']:
        raise ValueError('City baseline changed since park review')
    protected = protected_ids(policy)
    selected = []
    for rule in policy['parks']:
        pid = rule['id']
        if pid not in decisions['decisions']: continue
        choice = decisions['decisions'][pid]
        if choice['decision'] == 'unreviewed': continue
        if choice['decision'] == 'choose' and rule['geometry_dataset'] != choice['dataset']:
            raise ValueError('Ownership rule conflicts with the exported park choice')
        if choice['decision'] == 'discuss' and not rule.get('clarification'):
            raise ValueError('Discussion items need an explicit recorded user clarification')
        selected.append((rule, project(parks[pid]['boundary'])))
    retained = {}
    replacements = {}
    for rule, _ in selected:
        for item in rule.get('retain_features', []):
            did, fid = item['dataset'], item['feature_id']
            if not any(f['id'] == fid for f in before.get(did, {}).get('features', [])):
                raise ValueError('Retained connector is missing from the reviewed inventory')
            retained[(did, fid)] = {**item, 'park': rule['id']}
        for item in rule.get('geometry_replacements', []):
            did, fid = item['dataset'], item['feature_id']
            original = next((f for f in before.get(did, {}).get('features', []) if f['id'] == fid), None)
            if original is None or digest(original) != item['before_feature_hash']:
                raise ValueError('Connector replacement no longer matches its reviewed source feature')
            if did in protected or (did, fid) in retained or (did, fid) in replacements:
                raise ValueError('Connector replacement conflicts with a protected or retained feature')
            # Validate the explicit replacement with the same rules as datasets.
            canonical({'type': 'FeatureCollection', 'features': [{**original, 'geometry': item['geometry']}]})
            replacements[(did, fid)] = {**item, 'park': rule['id']}
    # Overlapping polygons need explicit precedence, recorded in the review manifest.
    adjustments = []
    priority = policy.get('boundary_priority', [])
    for i, (a, area_a) in enumerate(selected):
        for j in range(i + 1, len(selected)):
            b, area_b = selected[j]
            if a['mode'] == b['mode'] == 'winner' and a['geometry_dataset'] != b['geometry_dataset'] and area_a.intersection(area_b).area > 1:
                if a['id'] not in priority or b['id'] not in priority:
                    raise ValueError('Selected park boundaries overlap with conflicting geometry owners')
                overlap = area_a.intersection(area_b).area
                if priority.index(a['id']) < priority.index(b['id']):
                    selected[j] = (b, area_b.difference(area_a)); winner = a['id']
                else:
                    area_a = area_a.difference(area_b); selected[i] = (a, area_a); winner = b['id']
                adjustments.append({'parks': [a['id'], b['id']], 'overlap_m2': round(overlap, 2), 'priority': winner, 'requires_boundary_review': True})
    def line_geometry(geometry):
        if geometry.is_empty: return None
        parts = [geometry] if geometry.geom_type in {'LineString', 'MultiLineString'} else [g for g in getattr(geometry, 'geoms', []) if g.geom_type in {'LineString', 'MultiLineString'} and g.length > 0]
        if not parts: return None
        return mapping(transform(inverse, union(parts)))
    after = copy.deepcopy(before)
    edits = []
    visible = {s['dataset'] for s in report['sources'] if s['role'] == 'trail-lines'}
    for did in visible - protected:
        masks = [(rule['id'], area) for rule, area in selected if rule['mode'] == 'winner' and rule['geometry_dataset'] != did]
        if not masks: continue
        removal = union([a for _, a in masks])
        kept = []
        for feature in after[did]['features']:
            if (did, feature['id']) in retained or (did, feature['id']) in replacements:
                kept.append(feature); continue
            geometry = project(feature['geometry'])
            if geometry.length == 0 or geometry.intersection(removal).length == 0:
                kept.append(feature); continue
            remaining = geometry.difference(removal)
            replacement = line_geometry(remaining)
            edits.append({'dataset': did, 'feature_id': feature['id'], 'action': 'trim' if replacement else 'delete',
                          'parks': [pid for pid, area in masks if geometry.intersection(area).length > 0],
                          'removed_m': round(geometry.length - remaining.length, 2), 'retained_outside_m': round(remaining.length, 2),
                          'properties_preserved': True})
            if replacement:
                feature['geometry'] = replacement; kept.append(feature)
        after[did]['features'] = kept
    city = plan['target']['dataset']
    include = [area for rule, area in selected if rule['geometry_dataset'] == city and rule['mode'] in {'winner', 'keep-both'}]
    mask = union(include)
    supplemental = {fid for rule, _ in selected if rule['mode'] == 'supplement' and rule.get('supplemental_dataset') == city for fid in rule.get('supplemental_features', [])}
    added = set(plan['changes']['added'])
    for feature in plan['after']['features']:
        if feature['id'] not in added: continue
        geometry = project(feature['geometry'])
        selected_geometry = geometry if feature['id'] in supplemental else geometry.intersection(mask)
        if selected_geometry.length < 1: continue
        item = copy.deepcopy(feature)
        clipped = not selected_geometry.equals(geometry)
        if clipped: item['geometry'] = line_geometry(selected_geometry)
        after[city]['features'].append(item)
        edits.append({'dataset': city, 'feature_id': item['id'], 'action': 'add', 'clipped_to_selected_parks': clipped,
                      'included_m': round(selected_geometry.length, 2), 'excluded_outside_m': round(geometry.length - selected_geometry.length, 2)})
    # mapping() produces tuples; serialize to ordinary GeoJSON lists before validation.
    for (did, fid), replacement in replacements.items():
        feature = next(f for f in after[did]['features'] if f['id'] == fid)
        feature['geometry'] = copy.deepcopy(replacement['geometry'])
        edits.append({'dataset': did, 'feature_id': fid, 'action': 'replace-connector',
                      'parks': [replacement['park']], 'properties_preserved': True,
                      'reason': replacement['reason']})
    import json
    after = {did: canonical(json.loads(json.dumps(data))) for did, data in after.items()}
    preserve_protected(before, after, policy)
    for did, fid in retained:
        original = next(f for f in before[did]['features'] if f['id'] == fid)
        preserved = next((f for f in after[did]['features'] if f['id'] == fid), None)
        if original != preserved:
            raise ValueError('Consolidation modified an explicitly retained connector')
    targets = {t['dataset']: t for t in read_json(ROOT / 'config/mapbox.json')['targets']}
    retired_layers = []
    manifest = {'schema_version': 1, 'created_at': now(), 'review_hash': report['review_hash'], 'plan_hash': plan['approval_hash'],
                'policy_hash': digest(policy), 'status': 'prepared_for_review', 'edits': edits, 'datasets': [], 'boundary_adjustments': adjustments,
                'retained_features': [{**item, 'unchanged': True} for item in retained.values()],
                'connector_replacements': list(replacements.values()),
                'protected_datasets': [{'dataset': did, 'features': len(before[did]['features']), 'hash': fingerprint(before[did]), 'unchanged': True} for did in sorted(protected)],
                'limitations': ['Boundary cuts need a visual junction check before publication.', 'Connector endpoint adjustments are recorded explicitly; other coordinates are not snapped.', 'Other unreviewed additions and metadata edits remain excluded.']}
    for did, data in after.items():
        diff = changes(before[did], data)
        if not any(diff[k] for k in ['added', 'changed', 'deleted']): continue
        if did not in targets: raise ValueError('Changed dataset needs a configured Mapbox publishing target')
        target = targets[did]
        retirement = not data['features']
        if retirement:
            # An empty Uploads API replacement is unsafe. Keep the original dataset
            # archived and propose hiding its style layers instead.
            for layer in style['layers']:
                if layer.get('source-layer') == target['source_layer']:
                    layer.setdefault('layout', {})['visibility'] = 'none'
                    retired_layers.append(layer['id'])
        data['ingest_report'] = {'park_consolidation': True, 'ownership_policy_hash': digest(policy), 'reviewed_before_hash': fingerprint(before[did]),
                                 'reviewed_target': target, 'park_review_hash': report['review_hash'], 'requires_review': True}
        path = output / f"{target['id']}.geojson"
        write_json(path, data)
        manifest['datasets'].append({'target': target['id'], 'dataset': did, 'candidate': str(path),
                                     'publication_method': 'retire-style-layers-keep-dataset' if retirement else 'reviewed-dataset-update',
                                     'before_hash': fingerprint(before[did]), 'after_hash': fingerprint(data),
                                     'changes': {k: len(v) for k, v in diff.items()}})
    if retired_layers:
        write_json(output / 'style-proposed.json', style)
        manifest['style_proposal'] = {'path': str(output / 'style-proposed.json'), 'before_hash': report['style_hash'],
                                      'after_hash': digest(style), 'hide_layers': retired_layers,
                                      'rivanna_untouched': True, 'requires_review': True}
    write_json(output / 'manifest.json', manifest)
    return manifest


def build_consolidation_review(manifest_path, review_path, policy_path, inventory_dir, output):
    manifest, report, policy = read_json(manifest_path), read_json(review_path)['report'], read_json(policy_path)
    if manifest['policy_hash'] != digest(policy) or manifest['review_hash'] != report['review_hash']:
        raise ValueError('Consolidation preview inputs do not match the preparation')
    targets = {t['dataset']: t for t in read_json(ROOT / 'config/mapbox.json')['targets']}
    datasets = []
    for item in manifest['datasets']:
        before = read_json(Path(inventory_dir) / 'datasets' / f"{item['dataset']}.geojson")
        after = read_json(item['candidate'])
        if fingerprint(before) != item['before_hash'] or fingerprint(after) != item['after_hash']:
            raise ValueError('Prepared geometry changed before preview')
        datasets.append({**item, 'source_layer': targets[item['dataset']]['source_layer'], 'before': canonical(before), 'after': canonical(after)})
    settings = read_json(ROOT / 'config/mapbox.json')
    token = re.search(r"mapboxgl.accessToken = '(pk\.[^']+)'", (ROOT / 'assets/app.js').read_text())[1]
    selected = {p['id'] for p in policy['parks']}
    payload = {'manifest': manifest, 'policy': policy, 'datasets': datasets, 'parks': [p for p in report['parks'] if p['id'] in selected],
               'public_token': token, 'style': f"mapbox://styles/{settings['username']}/{settings['style_id']}"}
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    write_json(output / 'review.json', payload)
    for filename in ('index.html', 'review.js', 'review.css'):
        shutil.copyfile(ROOT / 'maintenance/consolidation_ui' / filename, output / filename)
    return output
