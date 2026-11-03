"""Build a local visual review, and turn exported decisions into a new candidate."""
import copy
import re
import shutil
from .common import ROOT, STATE, digest, read_json, write_json
from .geo import canonical, changes, fingerprint


def verify_plan(plan):
    if digest({k: v for k, v in plan.items() if k != 'approval_hash'}) != plan['approval_hash']:
        raise ValueError('Plan hash does not match its contents')
    if fingerprint(plan['before']) != plan['before_hash'] or fingerprint(plan['after']) != plan['after_hash']:
        raise ValueError('Plan dataset fingerprints do not match')


def review_rows(plan):
    verify_plan(plan)
    old = {f['id']: f for f in canonical(plan['before'])['features']}
    new = {f['id']: f for f in canonical(plan['after'])['features']}
    diff = changes(plan['before'], plan['after'])
    report = plan.get('ingest_report', {})
    retained = set(report.get('retained_missing_upstream', []))
    conflicts = {}
    for item in report.get('property_conflicts', []): conflicts.setdefault(item['feature_id'], []).append(item)
    rows = []
    for fid in sorted(old.keys() | new.keys()):
        before, after = old.get(fid), new.get(fid)
        kinds = []
        if fid in diff['added']: kinds.append('added')
        if fid in diff['deleted']: kinds.append('deleted')
        if fid in diff['geometry_changed']: kinds.append('geometry')
        if fid in retained: kinds.append('retained')
        if fid in conflicts: kinds.append('conflict')
        altered = [key for key, value in (before or {}).get('properties', {}).items() if after and (key not in after['properties'] or after['properties'][key] != value)]
        if altered: kinds.append('attributes')
        if not kinds and fid in diff['changed']: kinds.append('metadata')
        if not kinds: continue
        props = (after or before)['properties']
        name = next((props[k] for k in ('name', 'NAME', 'Name', 'TrailName') if isinstance(props.get(k), str) and props[k].strip()), 'Unnamed trail')
        rows.append({'id': fid, 'name': name, 'kinds': kinds, 'conflicts': conflicts.get(fid, []), 'changed_properties': altered})
    return rows


def build_review(plan_path, state_dir=STATE, overlaps_path=None):
    plan = read_json(plan_path)
    rows = review_rows(plan)
    overlaps = read_json(overlaps_path) if overlaps_path else None
    if overlaps and overlaps.get('plan_hash') != plan['approval_hash']:
        raise ValueError('Overlap comparison belongs to a different review plan')
    target = plan['target']['id']
    if not re.fullmatch(r'[a-z0-9-]+', target): raise ValueError('Invalid target identifier')
    output = state_dir / f'review-{target}'
    output.mkdir(parents=True, exist_ok=True)
    for filename in ('index.html', 'review.js', 'review.css'):
        shutil.copyfile(ROOT / 'maintenance/review_ui' / filename, output / filename)
    token = re.search(r"mapboxgl.accessToken = '(pk\.[^']+)'", (ROOT / 'assets/app.js').read_text())
    if not token: raise ValueError('Public map token not found in website configuration')
    settings = read_json(ROOT / 'config/mapbox.json')
    write_json(output / 'review.json', {
        'plan': plan, 'rows': rows, 'public_token': token[1],
        'style': f"mapbox://styles/{settings['username']}/{settings['style_id']}",
        'overlaps': overlaps,
    })
    return output


def reviewed_candidate(plan, decisions):
    verify_plan(plan)
    if decisions.get('plan_hash') != plan['approval_hash']:
        raise ValueError('Decisions belong to a different plan')
    rows = {r['id'] for r in review_rows(plan)}
    selections = decisions.get('decisions')
    if not isinstance(selections, dict): raise ValueError('Expected a decisions object')
    for fid, choice in selections.items():
        if fid not in rows or not isinstance(choice, dict) or choice.get('decision') not in {'accept', 'defer', 'discuss', 'unreviewed'}:
            raise ValueError('Unknown feature or invalid review decision')
    result = {f['id']: copy.deepcopy(f) for f in canonical(plan['before'])['features']}
    proposed = {f['id']: f for f in canonical(plan['after'])['features']}
    for fid, choice in selections.items():
        if choice['decision'] != 'accept': continue
        if fid in proposed: result[fid] = copy.deepcopy(proposed[fid])
        else: result.pop(fid, None)
    candidate = canonical({'type': 'FeatureCollection', 'features': list(result.values())})
    candidate['ingest_report'] = {
        'reviewed_plan_hash': plan['approval_hash'],
        'reviewed_before_hash': plan['before_hash'],
        'reviewed_target': plan['target'],
        'decisions': selections,
        'original_ingest_report': plan.get('ingest_report', {}),
        'requires_review': True,
    }
    return candidate
