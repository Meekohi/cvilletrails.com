"""Explain County color differences and compare southern Biscuit geometry without publishing."""
import argparse
import copy
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .albemarle_review import color_for
from .common import ROOT, digest, now, read_json, write_json
from .geo import fingerprint
from .state_parks import bounds


def verify_inputs(report, source, baseline, feedback):
    if digest({k: v for k, v in report.items() if k != 'review_hash'}) != report['review_hash']:
        raise ValueError('Parent review hash mismatch')
    if digest(source) != report['source_hash'] or fingerprint(baseline) != report['baseline_hash']:
        raise ValueError('Follow-up inputs do not match the reviewed source and baseline')
    eligible = sorted(r['id'] for r in report['rows'] if r['category'] == 'eligible')
    if (feedback['parent_review_hash'] != report['review_hash'] or feedback['source_hash'] != report['source_hash']
            or feedback['baseline_hash'] != report['baseline_hash']
            or feedback['geometry_accepted_feature_ids'] != eligible):
        raise ValueError('Geometry feedback does not match the exact reviewed eligible IDs')


def is_junction_flag(row, matches):
    """Identify flags supported only by tiny pieces near intersections, not full route changes."""
    return bool(matches) and all(
        min(row['length_m'] * m['source_coverage']['3'], m['existing_length_m'] * m['existing_coverage']['3']) < 25
        and m['source_coverage']['3'] < .1 for m in matches)


def explain(row, evidence):
    matches = [m for m in row['matches'] if any(c['property'] == 'rendered_color' for c in m['conflicts'])]
    if is_junction_flag(row, matches):
        return {'kind': 'Junction proximity flag',
            'explanation': 'The original 10-metre overlap screen caught short nearby pieces of differently colored trails. Less than 10% of this source line and less than 25 metres of each matched piece coincide within 3 metres. This flag is not evidence that the whole route changed color.',
            'recommendation': 'Keep the existing named-route color; inspect the junction if needed. Do not repaint the full route based on this match.', 'sources': []}
    key = row['park_id'] + '/' + row['name']
    if key in evidence['notes']:
        return copy.deepcopy(evidence['notes'][key])
    return {'kind': 'Connector attribution unresolved',
        'explanation': 'The GIS uses a generic Connector name where one or more older named trail segments are nearby. Connector has no explicit color rule, so it becomes pale tan. A short junction can overlap multiple colors; the geometry match alone cannot choose its blaze.',
        'recommendation': 'Inspect this individual connector and the official map. Do not apply a park-wide replacement color.',
        'sources': ['ivy-current'] if row['park_id'] == 'ivy-creek-natural-area' else ['walnut']}


def iso_date(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc).date().isoformat()
    return value


def southern_records(source, report):
    rows = {r['global_id']: r for r in report['rows']}
    result = []
    for original in source['features']:
        p = original['properties']
        # A specific geometry-review group, not a broader eligibility exception.
        if p.get('Loc_Name') == 'Biscuit Run Park-400 Acres' and p.get('Status') == 'Active' and p.get('Property_Info') == 'Closed':
            row = rows[p['GlobalID']]
            if row['category'] != 'held' or not row['geometry_valid']:
                raise ValueError('Southern Biscuit review group changed; inspect source access and geometry')
            f = copy.deepcopy(original)
            f['id'] = row['id']
            f['properties'].update({'compare_park': 'biscuit-run', 'compare_category': 'closed-south',
                'compare_name': p['Trail_Name'], 'compare_color': '#a95713', 'compare_suggested_color': '#a95713'})
            result.append(f)
    return result


def build(parent, source_path, inventory, feedback_path, evidence_dir, output):
    if output.resolve() == parent.resolve():
        raise ValueError('Follow-up must not overwrite the approved parent review')
    report, source = read_json(parent / 'review.json'), read_json(source_path)
    baseline = read_json(parent / 'preserved.geojson')
    feedback = read_json(feedback_path)
    verify_inputs(report, source, baseline, feedback)
    style = read_json(inventory / 'style.json')
    if digest(style) != report['style_hash']:
        raise ValueError('Captured style changed from parent review')
    evidence = read_json(ROOT / 'pipelines/albemarle/color-evidence.json')
    raw = {f['properties']['GlobalID']: f for f in source['features']}
    cases = []
    for row in report['rows']:
        if not row.get('color_conflict'):
            continue
        p = raw[row['global_id']]['properties']
        note = explain(row, evidence)
        matches = [m for m in row['matches'] if any(c['property'] == 'rendered_color' for c in m['conflicts'])]
        cases.append({'id': row['id'], 'park_id': row['park_id'], 'name': row['name'],
            'length_m': row['length_m'], 'bounds': bounds([raw[row['global_id']]]), 'analysis': note,
            'matches': matches, 'raw_color': color_for(style, row['name']),
            'suggested_color': color_for(style, note['suggested_alias']) if note.get('suggested_alias') else None,
            'raw_attributes': {key: p.get(key) for key in ['Trail_Name', 'Status', 'Property_Info', 'Comments', 'Map_Method', 'CREATED', 'UPDATED', 'CreationDate', 'EditDate']},
            'edit_date': iso_date(p.get('EditDate')),
            'old_records': [{'id': m['existing_id'], 'name': m['existing_name'], 'color': color_for(style, m['existing_name']),
                'updated': next(f['properties'].get('Updated') for f in baseline['features'] if f['id'] == m['existing_id'])} for m in matches]})
    cases.sort(key=lambda c: (c['name'] != 'Blue Wheel', c['park_id'], c['name'], c['id']))
    old_preview = read_json(parent / 'existing.geojson')
    for f in old_preview['features']:
        p = f['properties']
        p.update({'compare_park': p['review_park'], 'compare_name': p.get('TrailName', ''), 'compare_category': 'current', 'compare_color': p['review_color']})
    incoming = read_json(parent / 'source.geojson')
    for f in incoming['features']:
        p = f['properties']
        alias = evidence['notes'].get(p['review_park'] + '/' + (p.get('Trail_Name') or '').strip(), {}).get('suggested_alias')
        p.update({'compare_park': p['review_park'], 'compare_name': (p.get('Trail_Name') or '').strip(),
            'compare_category': p['review_category'], 'compare_color': p['review_color'],
            'compare_suggested_color': color_for(style, alias) if alias else p['review_color']})
    south = southern_records(source, report)
    south_ids = {f['id'] for f in south}
    incoming['features'] = [f for f in incoming['features'] if f['id'] not in south_ids] + south
    # Biscuit's rough current lines are in other datasets, not the County target.
    from shapely.geometry import box, mapping, shape
    park = next(p for p in report['parks'] if p['id'] == 'biscuit-run')
    extent = box(*park['bounds'])
    references = read_json(parent / 'references.geojson')
    rough = []
    for original in references['features']:
        line = shape(original['geometry']).intersection(extent)
        if line.is_empty or line.geom_type not in {'LineString', 'MultiLineString'} or line.length == 0:
            continue
        f = copy.deepcopy(original)
        f['geometry'] = mapping(line)
        p = f['properties']
        p.update({'compare_park': 'biscuit-run', 'compare_name': next((p[k] for k in ['name', 'Name', 'TrailName', 'NAME'] if p.get(k)), 'Current trail'),
            'compare_category': 'current', 'compare_color': '#008fa8'})
        rough.append(f)
    old_preview['features'].extend(rough)
    out_evidence = output / 'evidence'
    out_evidence.mkdir(parents=True, exist_ok=True)
    for item in evidence['sources'].values():
        for key in ('file', 'image'):
            if item.get(key):
                file = evidence_dir / item[key]
                if not file.exists():
                    raise ValueError('Missing inspected official-map evidence: ' + str(file))
                item[key + '_hash'] = digest(file.read_bytes())
                shutil.copy(file, out_evidence / file.name)
    southern_report = {'count': len(south), 'ids': sorted(south_ids), 'bounds': bounds(south),
        'current_rough_features': len(rough),
        'status_counts': dict(Counter(f['properties']['Status'] for f in south)),
        'access_counts': dict(Counter(f['properties']['Property_Info'] for f in south)),
        'map_method_counts': dict(Counter(str(f['properties'].get('Map_Method')) for f in south)),
        'hiking_counts': dict(Counter(str(f['properties'].get('Hiking')) for f in south)),
        'note': f'{len(south)} southern 400-acre GIS records are mapped as Active but explicitly Closed. The submeter mapping label is a source claim, not independent accuracy verification. Compare their geometry separately from access. Other held records include inactive and future lines; they are not interchangeable.',
        'proposed_use': 'Prepare a better southern geometry reference with explicit Closed status. Do not silently promote these records to open trails or include every held line.'}
    followup = {'schema_version': 1, 'kind': 'albemarle-color-and-south-review', 'created_at': now(),
        'parent_review_hash': report['review_hash'], 'source_hash': report['source_hash'], 'baseline_hash': report['baseline_hash'],
        'style_hash': report['style_hash'], 'feedback_hash': digest(feedback), 'publication_authorized': False,
        'geometry_accepted_count': len(feedback['geometry_accepted_feature_ids']), 'geometry_accepted_feature_ids': feedback['geometry_accepted_feature_ids'],
        'evidence': evidence, 'cases': cases, 'classification_counts': dict(Counter(c['analysis']['kind'] for c in cases)),
        'south': southern_report, 'parks': [p for p in report['parks'] if p['id'] in {'ivy-creek-natural-area', 'walnut-creek', 'biscuit-run'}],
        'comparison_note': 'Left: saved current map geometry and colors. Right: reviewed GIS geometry colored by the same existing lookup. Suggested aliases affect preview colors only. Raw GIS has no blaze-color field. No public map changes are made.',
        'code_hash': digest({p: (ROOT / p).read_text() for p in ['maintenance/albemarle_followup.py', 'maintenance/albemarle_followup_ui/index.html', 'maintenance/albemarle_followup_ui/compare.js', 'maintenance/albemarle_followup_ui/compare.css']})}
    followup['artifact_hashes'] = {'current': digest(old_preview), 'incoming': digest(incoming)}
    followup['review_hash'] = digest(followup)
    for filename, value in [('review.json', followup), ('current.geojson', old_preview), ('incoming.geojson', incoming)]:
        write_json(output / filename, value)
    shutil.copy(parent / 'preview.json', output / 'preview.json')
    for name in ('index.html', 'compare.js', 'compare.css'):
        shutil.copy(ROOT / 'maintenance/albemarle_followup_ui' / name, output / name)
    return followup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('parent', 'source', 'inventory', 'feedback', 'evidence-dir', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = build(args.parent, args.source, args.inventory, args.feedback, args.evidence_dir, args.output)
    print({'review_hash': result['review_hash'], 'color_cases': len(result['cases']),
           'classification_counts': result['classification_counts'], 'southern_closed_records': result['south']['count']})


if __name__ == '__main__':
    main()
