"""Import hash-bound color feedback into local County overrides; never publish."""
import argparse
import copy
import tempfile
from collections import Counter
from pathlib import Path

from .albemarle import access_fingerprint, global_id, load_access_decisions, normalize_trails, screen
from .albemarle_review import color_for
from .common import configs, digest, now, read_json, write_json


def resolve(report, feedback, style, overrides):
    if digest({k: v for k, v in report.items() if k != 'review_hash'}) != report['review_hash']:
        raise ValueError('Review hash mismatch')
    if feedback.get('schema_version') != 1 or feedback.get('kind') != 'albemarle-color-and-south-review':
        raise ValueError('Expected Albemarle color and south feedback')
    for key in ('review_hash', 'parent_review_hash', 'source_hash', 'baseline_hash'):
        if feedback.get(key) != report[key]:
            raise ValueError('Feedback does not match review: ' + key)
    if feedback.get('geometry_feedback_hash') != report['feedback_hash']:
        raise ValueError('Geometry feedback hash mismatch')
    if feedback.get('publication_authorized') is not False:
        raise ValueError('Color feedback cannot authorize publication')
    if digest(style) != report['style_hash']:
        raise ValueError('Captured style hash mismatch')
    questions = feedback.get('questions')
    if not isinstance(questions, dict):
        raise ValueError('Expected feedback questions')
    cases = {c['id']: c for c in report['cases']}
    if set(questions) - (set(cases) | {'biscuit-south'}):
        raise ValueError('Unknown feedback feature ID')
    result, resolved, pending = copy.deepcopy(overrides), [], []
    for key, question in questions.items():
        choices = {'', 'closed-geometry', 'reference-only', 'discuss'} if key == 'biscuit-south' else {
            '', 'suggested-alias', 'preserve-current', 'gis-name-color', 'discuss'}
        if not isinstance(question, dict) or question.get('decision') not in choices or not isinstance(question.get('notes'), str):
            raise ValueError('Invalid feedback decision or notes: ' + key)
    for fid, case in cases.items():
        question = questions.get(fid, {'decision': '', 'notes': ''})
        decision = question['decision']
        if decision in {'', 'discuss'}:
            pending.append({'id': fid, 'park_id': case['park_id'], 'name': case['name'], **question})
            continue
        if fid not in report['geometry_accepted_feature_ids']:
            raise ValueError('Color decision is outside accepted geometry')
        if decision == 'preserve-current':
            colors = {r['color'] for r in case['old_records']}
            if len(colors) != 1:
                raise ValueError('Preserve-current has multiple possible colors: ' + fid)
            color = colors.pop()
            alias = case['old_records'][0]['name']
        elif decision == 'suggested-alias':
            alias = case['analysis'].get('suggested_alias')
            color = case.get('suggested_color')
            if not alias or not color:
                raise ValueError('No supported suggested alias: ' + fid)
        else:
            alias, color = case['name'], case['raw_color']
        if color_for(style, alias) != color:
            raise ValueError('Chosen name does not render the reviewed color: ' + fid)
        gid = fid.removeprefix('albemarle:')
        properties = {'TrailName': alias, 'color': color}
        existing = result.get(gid, {'properties': {}})
        if set(existing) != {'properties'}:
            raise ValueError('Invalid existing override: ' + gid)
        if any(k in existing['properties'] and existing['properties'][k] != v for k, v in properties.items()):
            raise ValueError('Feedback conflicts with an existing override: ' + gid)
        result[gid] = {'properties': {**existing['properties'], **properties}}
        resolved.append({'id': fid, 'park_id': case['park_id'], 'source_name': case['name'],
            **question, 'properties': properties, 'current_feature_ids': [r['id'] for r in case['old_records']]})
    return result, resolved, pending, questions.get('biscuit-south', {'decision': '', 'notes': ''})


def southern_open_decision(report, feedback, source, config):
    """Explicit human interpretation of notes; never infer access from the dropdown."""
    south = feedback['questions'].get('biscuit-south', {})
    if south.get('decision') != 'closed-geometry' or not south.get('notes', '').strip():
        raise ValueError('Southern open interpretation requires the geometry decision and explicit user notes')
    ids = report['south']['ids']
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Expected exact reviewed southern IDs')
    raw = {'albemarle:' + global_id(f): f for f in source['features']}
    rows = {r['id']: r for r in screen(source, config, {})}
    features = {}
    for fid in ids:
        f, row = raw[fid], rows[fid]
        p = f['properties']
        if (p.get('Loc_Name') != 'Biscuit Run Park-400 Acres' or p.get('Status') != 'Active'
                or p.get('Property_Info') != 'Closed' or p.get('Hiking') not in (None, 'Yes')
                or set(row['reasons']) - {'access is closed, conditional or unknown', 'hiking permission is not explicit'}):
            raise ValueError('Southern interpretation exceeds the reviewed access-only holds')
        features[row['global_id']] = access_fingerprint(f)
    return {'schema_version': 1, 'kind': 'albemarle-reviewed-access',
        'review_hash': report['review_hash'], 'source_hash': report['source_hash'],
        'feedback_hash': digest(feedback), 'user_statement': south['notes'],
        'effective_access': 'Open', 'effective_hiking': 'Yes', 'features': features,
        'interpretation': 'The explicit user note supersedes the Closed label in the dropdown for these exact southern records. Treat them as open hiking trails in the local candidate; retain raw GIS access fields. Other use permissions remain unchanged.'}


def import_feedback(review_path, feedback_path, source_path, style_path, output, config=None, southern_open=False):
    config = config or configs('albemarle')[0]
    report, feedback = read_json(review_path), read_json(feedback_path)
    source, style = read_json(source_path), read_json(style_path)
    override_path = config['_directory'] / 'overrides.json'
    before = read_json(override_path)
    overrides, resolved, pending, south = resolve(report, feedback, style, before)
    if digest(source) != report['source_hash']:
        raise ValueError('Source differs from reviewed snapshot')
    before_access = load_access_decisions(config)
    access = southern_open_decision(report, feedback, source, config) if southern_open else before_access
    if before_access and southern_open and access != before_access:
        raise ValueError('New southern interpretation conflicts with existing access decisions')
    raw_eligible = sorted(r['id'] for r in screen(source, config, {}) if r['category'] == 'eligible')
    if raw_eligible != report['geometry_accepted_feature_ids']:
        raise ValueError('Current source screening differs from the accepted geometry IDs')
    # Validate the entire screened subset before changing persistent overrides.
    with tempfile.TemporaryDirectory() as directory:
        staged_config = {**config, '_directory': Path(directory)}
        write_json(Path(directory) / 'overrides.json', overrides)
        if access:
            write_json(Path(directory) / 'access-decisions.json', access)
        candidate = normalize_trails(source, staged_config, 'county-gis')
    accepted = set(raw_eligible) | {'albemarle:' + gid for gid in access.get('features', {})}
    if set(f['id'] for f in candidate['features']) != accepted:
        raise ValueError('Current screening differs from the accepted geometry IDs')
    audit = {'schema_version': 1, 'kind': 'albemarle-color-feedback-import', 'recorded_at': now(),
        'review_hash': report['review_hash'], 'parent_review_hash': report['parent_review_hash'],
        'source_hash': report['source_hash'], 'baseline_hash': report['baseline_hash'], 'style_hash': report['style_hash'],
        'geometry_feedback_hash': report['feedback_hash'], 'feedback_hash': digest(feedback),
        'original_file_hash': digest(feedback_path.read_bytes()), 'publication_authorized': False, 'remote_writes': False,
        'overrides_before_hash': digest(before), 'overrides_after_hash': digest(overrides),
        'candidate_hash': digest(candidate), 'geometry_accepted_count': len(raw_eligible),
        'normalized_features': len(candidate['features']), 'southern_open_features': len(access.get('features', {})),
        'access_decisions_before_hash': digest(before_access), 'access_decisions_hash': digest(access),
        'southern_access_interpretation': access.get('interpretation'),
        'decision_counts': dict(Counter(r['decision'] for r in resolved)), 'resolved': resolved,
        'pending_color_cases': pending, 'southern_feedback': south,
        'note': 'Explicit color decisions are applied to local per-feature overrides. Raw GIS names and accepted geometry are retained. Reviewed access corrections are separately recorded with raw source access preserved. Missing decisions remain pending. This screened subset is not a full replacement dataset.'}
    output.mkdir(parents=True, exist_ok=True)
    (output / 'original-feedback.json').write_bytes(feedback_path.read_bytes())
    write_json(output / 'screened-with-reviewed-colors.geojson', candidate)
    write_json(output / 'decisions.json', audit)
    write_json(override_path, overrides)
    if access:
        write_json(config['_directory'] / 'access-decisions.json', access)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('review', 'feedback', 'source', 'style', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--southern-open', action='store_true',
        help='Apply an explicit user note directing open access for the exact reviewed southern records; do not infer this from the dropdown')
    args = parser.parse_args()
    result = import_feedback(args.review, args.feedback, args.source, args.style, args.output, southern_open=args.southern_open)
    print({'applied': len(result['resolved']), 'pending_color_cases': len(result['pending_color_cases']),
        'southern_decision': result['southern_feedback']['decision'] or 'not supplied',
        'southern_open_features': result['southern_open_features'],
        'publication_authorized': False})


if __name__ == '__main__':
    main()
