"""Build a Rivanna candidate from an explicit, evidence-bound review interpretation.

This command only writes local artifacts. Free-text notes are interpreted in chat;
the saved action manifest makes that interpretation repeatable and inspectable.
"""
import argparse
import copy
import re
import shutil
from pathlib import Path

from .common import ROOT, digest, read_json, write_json
from .geo import canonical, changes, fingerprint
from .mapbox import target_by_id


def reviewed_candidate(current, report, decisions, interpretation):
    if digest({k: v for k, v in report.items() if k != 'review_hash'}) != report['review_hash']:
        raise ValueError('Review report hash mismatch')
    if any(v.get('review_hash') != report['review_hash'] for v in (decisions, interpretation)):
        raise ValueError('Decisions belong to a different review')
    if any(v.get('current_hash') != fingerprint(current) for v in (report, decisions, interpretation)):
        raise ValueError('Current Rivanna baseline changed; review again')
    if interpretation['export_hash'] != digest(decisions) or interpretation['original_export'] != decisions:
        raise ValueError('Decision export differs from interpreted notes')
    rows = {r['snapshot_key']: r for r in report['rows']}
    actions = interpretation['actions']
    keys = [a['source_snapshot_key'] for a in actions]
    if len(set(keys)) != len(keys) or set(keys) != set(decisions['decisions']) or not set(keys) <= rows.keys():
        raise ValueError('Every reviewed decision must have exactly one action')
    result = copy.deepcopy(canonical(current))
    original = {f['id']: f for f in canonical(current)['features']}
    features = {f['id']: f for f in result['features']}
    closures = {}
    for action in actions:
        key = action['source_snapshot_key']
        row = rows[key]
        if action['source_semantic_key'] != row['semantic_key'] or action['source_geometry_hash'] != digest(row['geometry']):
            raise ValueError('Source identity or geometry differs from reviewed action')
        kind = action['action']
        choice = decisions['decisions'][key]
        if kind in {'add_official_road_walk', 'mark_existing_route_temporarily_closed', 'coalesce_closed_subset_annotation', 'retain_existing_primary_detour'}:
            if choice['decision'] != 'compare-geometry' or not choice.get('note', '').strip():
                raise ValueError('Action requires an explicit reviewed note')
        fid = action.get('current_feature_id')
        if kind in {'mark_existing_route_temporarily_closed', 'coalesce_closed_subset_annotation', 'retain_existing_primary_detour'} and not fid:
            raise ValueError('Existing route identity is required')
        if fid and (fid not in original or digest(original[fid]) != action['current_feature_before_hash']):
            raise ValueError('Existing feature differs from reviewed identity')
        if kind == 'add_official_road_walk':
            fid = action['proposed_feature_id']
            if not re.fullmatch(r'rtf:roadwalk:[a-z0-9-]+', fid) or fid in features:
                raise ValueError('Road walk requires a unique stable semantic ID')
            if not row['eligible_for_route_review'] or 'closure' in row['flags']:
                raise ValueError('Cannot add excluded or closed source as a road walk')
            if row['geometry']['type'] not in {'LineString', 'MultiLineString'}:
                raise ValueError('Road walks require line geometry')
            feature = {'type': 'Feature', 'id': fid, 'geometry': copy.deepcopy(row['geometry']),
                       'properties': copy.deepcopy(action['proposed_properties'])}
            result['features'].append(feature)
            features[fid] = feature
        elif kind == 'mark_existing_route_temporarily_closed':
            properties = action['proposed_property_additions']
            if set(properties) != {'access_status', 'status_reviewed_at', 'status_review_source'} or properties['access_status'] != 'temporarily-closed':
                raise ValueError('Closure may only change reviewed access metadata')
            if any(k in features[fid]['properties'] for k in properties):
                raise ValueError('Existing access metadata requires a new review')
            features[fid]['properties'].update(properties)
            closures[key] = fid
        elif kind in {'coalesce_closed_subset_annotation', 'retain_existing_primary_detour'}:
            pass
        elif kind in {'omit_new_closed_route', 'keep_current_omit_new_route'}:
            if choice['decision'] != 'keep-current':
                raise ValueError('Omission differs from the user decision')
        else:
            raise ValueError('Unknown Rivanna review action')
    for action in actions:
        if action['action'] == 'coalesce_closed_subset_annotation':
            if closures.get(action['coalesces_into_source_snapshot_key']) != action['current_feature_id']:
                raise ValueError('Closure subset must refer to the same marked existing route')
    result = canonical(result)
    delta = changes(current, result)
    if delta['deleted'] or delta['geometry_changed'] or delta['curation_changed']:
        raise ValueError('Rivanna review must retain all existing geometry and curation')
    result['ingest_report'] = {'rivanna_review': True, 'review_hash': report['review_hash'],
                               'reviewed_target': target_by_id('rivanna'),
                               'interpretation_hash': digest(interpretation),
                               'reviewed_before_hash': fingerprint(current),
                               'decisions_hash': digest(decisions), 'changes': delta}
    return result


def closure_style(style):
    """Preserve layer ordering and all unrelated style settings."""
    result = copy.deepcopy(style)
    expected = {'rivanna-trail fringe': ('line', 'line-color', '#991b1b'),
                'rivanna-trail': ('line', 'line-color', '#f87171'),
                'rivanna-trail-label': ('symbol', 'text-field', None)}
    selected = [layer for layer in result['layers'] if layer['id'] in expected]
    if len(selected) != len(expected):
        raise ValueError('Expected Rivanna style layers are missing or duplicated')
    closed = ['==', ['get', 'access_status'], 'temporarily-closed']
    for layer in selected:
        kind, prop, color = expected[layer['id']]
        if layer['type'] != kind or layer.get('source-layer') != 'Rivanna_Trail':
            raise ValueError('Rivanna layer identity changed')
        group = layer['paint'] if kind == 'line' else layer['layout']
        original = group[prop]
        replacement = color if color else ['concat', ['to-string', ['get', 'Name']], ' · TEMPORARILY CLOSED']
        group[prop] = ['case', closed, replacement, original]
    return result


def build(current_path, review_path, decisions_path, interpretation_path, style_path, output):
    current, report, decisions, interpretation, style = map(read_json, (current_path, review_path, decisions_path, interpretation_path, style_path))
    candidate = reviewed_candidate(current, report, decisions, interpretation)
    proposed = closure_style(style)
    output = Path(output)
    write_json(output/'candidate.geojson', candidate)
    write_json(output/'style-proposal.json', proposed)
    manifest = {'status': 'prepared_not_published', 'interpretation_hash': digest(interpretation),
                'before_hash': fingerprint(current), 'after_hash': fingerprint(candidate),
                'changes': changes(current, candidate), 'style_before_hash': digest(style),
                'style_after_hash': digest(proposed)}
    manifest['proposal_hash'] = digest(manifest)
    write_json(output/'manifest.json', manifest)
    # Preview uses the proposed production layer definitions and local candidate,
    # while retaining the live basemap and other trail networks.
    preview = copy.deepcopy(proposed)
    preview['sources']['reviewed-rivanna'] = {'type': 'geojson', 'data': canonical(candidate)}
    for layer in preview['layers']:
        if layer.get('source-layer') == 'Rivanna_Trail':
            layer['source'] = 'reviewed-rivanna'
            del layer['source-layer']
    token = re.search(r"mapboxgl.accessToken = '(pk\.[^']+)'", (ROOT/'assets/app.js').read_text())[1]
    preview_actions = [{**action, 'review_note': decisions['decisions'][action['source_snapshot_key']]['note']}
                       for action in interpretation['actions']]
    write_json(output/'preview.json', {'style': preview, 'candidate': canonical(candidate), 'manifest': manifest,
                                      'public_token': token, 'actions': preview_actions})
    for name in ('index.html', 'preview.js', 'preview.css'):
        shutil.copyfile(ROOT/'maintenance/rivanna_candidate_ui'/name, output/name)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('current', 'review', 'decisions', 'interpretation', 'style', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(build(args.current, args.review, args.decisions, args.interpretation, args.style, args.output))
