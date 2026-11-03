"""Prepare park-level geometry ownership decisions; never edits Mapbox."""
import copy
import re
import shutil
from collections import Counter
from pathlib import Path
from .common import ROOT, STATE, digest, now, read_json, write_json
from .geo import canonical, changes, fingerprint
from .overlaps import geometry_tools, coverage
from .review_map import verify_plan


def build_park_review(plan_path, inventory_dir, boundaries_path, overlaps_path, output=STATE / 'review-parks'):
    project, union, _ = geometry_tools()
    from pyproj import Transformer
    from shapely.geometry import mapping
    from shapely.ops import transform
    plan, overlaps = read_json(plan_path), read_json(overlaps_path)
    verify_plan(plan)
    if overlaps['plan_hash'] != plan['approval_hash']: raise ValueError('Overlap report belongs to another plan')
    root, output = Path(inventory_dir), Path(output)
    style = read_json(root / 'style.json')
    if digest(style) != overlaps['style_hash']: raise ValueError('Style changed since overlap analysis')
    unproject = Transformer.from_crs('EPSG:32617', 'EPSG:4326', always_xy=True).transform
    boundary_data = read_json(boundaries_path)
    parks = {}
    for feature in boundary_data['features']:
        name = (feature['properties'].get('PARKNAME') or '').strip()
        if name: parks.setdefault(name, []).append(project(feature['geometry']))
    parks = {name: union(parts) for name, parts in parks.items()}
    additions, geometry_edits = set(plan['changes']['added']), set(plan['changes']['geometry_changed'])
    proposed = {f['id']: (f, project(f['geometry'])) for f in plan['after']['features']}
    groups = {}
    for fid in sorted(additions | geometry_edits):
        feature, line = proposed[fid]
        scores = sorted(((line.intersection(area).length / max(line.length, 1e-9), name) for name, area in parks.items()), reverse=True)
        name = scores[0][1] if scores[0][0] >= .5 else f"Corridor: {feature['properties'].get('name') or 'Unnamed trail'} ({fid})"
        groups.setdefault(name, []).append(fid)
    sources = [s for s in overlaps['sources'] if s['role'] == 'trail-lines']
    inputs = {}
    for source in sources:
        original = read_json(root / 'datasets' / f"{source['dataset']}.geojson")
        if fingerprint(original) != source['hash']: raise ValueError('Dataset inventory changed since overlap analysis')
        data = plan['after'] if source['dataset'] == plan['target']['dataset'] else original
        inputs[source['dataset']] = [(f, project(f['geometry'])) for f in data['features'] if f['geometry']['type'] in {'LineString', 'MultiLineString'}]
    results = []
    city = plan['target']['dataset']
    county = next(s['dataset'] for s in sources if s['name'] == 'Albemarle County Trails')
    for name, ids in groups.items():
        print(f'Comparing {name}...', flush=True)
        outside = name.startswith('Corridor: ')
        area = union([proposed[fid][1].buffer(30) for fid in ids]) if outside else parks[name]
        clipped, options = {}, []
        for source in sources:
            did = source['dataset']
            features, shapes, crossing, names = [], [], [], set()
            for feature, geometry in inputs[did]:
                if not geometry.intersects(area): continue
                inside = geometry.intersection(area)
                parts = [inside] if inside.geom_type in {'LineString', 'MultiLineString'} else [part for part in getattr(inside, 'geoms', []) if part.geom_type in {'LineString', 'MultiLineString'}]
                if not parts or sum(part.length for part in parts) < 1: continue
                inside = union(parts)
                shapes.append(inside)
                if geometry.difference(area).length > 5: crossing.append(feature['id'])
                props = feature['properties']
                label = next((props[k] for k in ('name', 'Name', 'TrailName', 'NAME') if props.get(k)), 'Unnamed trail')
                names.add(label)
                features.append({'type': 'Feature', 'id': feature['id'], 'geometry': mapping(transform(unproject, inside)),
                                 'properties': {**props, 'comparison_name': label, 'dataset_name': source['name'], 'dataset_id': did}})
            if not shapes: continue
            combined = union(shapes)
            clipped[did] = combined
            options.append({'dataset': did, 'name': source['name'] + (' (reviewed + proposed)' if did == city else ''),
                            'length_m': round(combined.length, 1), 'feature_count': len(features), 'names': sorted(names),
                            'cross_boundary_features': crossing, 'features': features})
        city_geometry = clipped.get(city)
        for option in options:
            geometry = clipped[option['dataset']]
            if option['dataset'] == city:
                option['city_coverage'] = option['covered_by_city'] = {'10': 1.0}
                option['outside_city_10m_m'] = 0
            else:
                option['city_coverage'] = coverage(city_geometry, geometry, (10,)) if city_geometry is not None else None
                option['covered_by_city'] = coverage(geometry, city_geometry, (10,)) if city_geometry is not None else None
                option['outside_city_10m_m'] = round(geometry.length * (1 - option['covered_by_city']['10']), 1) if city_geometry is not None else None
        recommendation = county if name == 'Ivy Creek Natural Area' else None if outside else city
        reason = ('Keep the County geometry as the starting point: it retains individual trail names used by the existing color rules. Most City additions closely follow it but use the generic park name. Review the unmatched portions before adopting any City geometry.' if name == 'Ivy Creek Natural Area' else
                  'These segments are not mostly inside a named official park polygon. Keep them as individual corridor decisions rather than forcing unrelated routes into one park winner.' if outside else
                  'Use the City GIS as the proposed geometry source for this City-managed park. This is a recommendation based on management provenance, not proof of greater positional accuracy. Resolve the differences shown here before retiring other geometry.')
        cautions = ['A winner applies inside the park only. Existing features crossing its boundary must be split or retained outside; never delete their whole geometry.',
                    'Preserve official trail names, colors, route identity and access information in the winner. One winner does not require losing attributes from other sources.',
                    'Choosing a winner records a source preference, not permission to publish or delete features. The consolidation needs a separate before/after plan.']
        if name == 'Ivy Creek Natural Area': cautions.append('Verify trail names and colors against the Ivy Creek trail manager’s map before any geometry migration.')
        if name in {'Ragged Mountain', 'Heyward Community Forest'}:
            cautions.append('The dedicated Ragged dataset consists of four imported tracks; several have generic ThursdayAfternoonTrack filenames. Its dataset name does not establish park boundaries or current access.')
        if name == 'Ragged Mountain': cautions.append('Maintenance Road remains held for discussion. City also includes an Existing segment named Old bridge link (to be closed); its access status needs confirmation.')
        counts = Counter(overlaps['rows'][fid]['classification'] for fid in ids if fid in additions)
        results.append({'id': re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-'), 'name': name, 'outside_boundaries': outside,
                        'bounds': list(transform(unproject, area).bounds), 'boundary': mapping(transform(unproject, area)),
                        'city_additions': len(set(ids) & additions), 'geometry_edits': len(set(ids) & geometry_edits),
                        'review_feature_ids': ids, 'overlap_counts': dict(counts), 'recommended_dataset': recommendation,
                        'reason': reason, 'cautions': cautions, 'datasets': options,
                        'segment_comparisons': [overlaps['rows'][fid] for fid in ids]})
    results.sort(key=lambda park: (-park['city_additions'], park['name']))
    settings = read_json(ROOT / 'config/mapbox.json')
    report = {'schema_version': 1, 'created_at': now(), 'plan_hash': plan['approval_hash'], 'style_hash': digest(style),
              'boundary_source': 'https://gisweb.charlottesville.org/arcgis/rest/services/Public/OpenData_1_UpdateAll/MapServer/178',
              'boundary_hash': digest(boundary_data), 'sources': overlaps['sources'], 'uncompared_tilesets': overlaps['uncompared_tilesets'],
              'method': overlaps['method'], 'parks': results}
    report['review_hash'] = digest(report)
    token = re.search(r"mapboxgl.accessToken = '(pk\.[^']+)'", (ROOT / 'assets/app.js').read_text())[1]
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / 'review.json', {'report': report, 'ownership_policy': read_json(ROOT / 'config/park-ownership.json'), 'public_token': token, 'style': f"mapbox://styles/{settings['username']}/{settings['style_id']}"})
    for filename in ('index.html', 'review.js', 'review.css'):
        shutil.copyfile(ROOT / 'maintenance/park_review_ui' / filename, output / filename)
    return output


def annotate_next_area_review(report, assessment):
    """Attach human-readable investigation notes without approving any additions."""
    import copy
    if digest({k: v for k, v in report.items() if k != 'review_hash'}) != report['review_hash']:
        raise ValueError('Park report contents do not match their hash')
    if assessment.get('plan_hash') != report['plan_hash']:
        raise ValueError('Next-area assessment belongs to another plan')
    notes = {item['area_id']: item for item in assessment['areas']}
    if len(notes) != len(assessment['areas']) or set(notes) != {p['id'] for p in report['parks']}:
        raise ValueError('Next-area assessment must cover exactly the reviewed areas')
    result = copy.deepcopy(report)
    for park in result['parks']:
        note = notes[park['id']]
        if set(note['feature_ids']) != set(park['review_feature_ids']):
            raise ValueError('Next-area assessment feature IDs differ from the park review')
        park['assessment'] = copy.deepcopy(note)
        # Source selection is not the decision in this round. Every feature is a
        # proposed addition; existing networks are retained regardless of choice.
        park['recommended_dataset'] = None
        park['reason'] = note['recommendation']
        park['cautions'] = [
            'This round proposes additions only. Keeping or including a City feature never removes Rivanna or other existing trails.',
            'Distances screen for possible duplicates; they do not establish trail identity or public access.',
            *note.get('cautions', []),
        ]
    result['parks'].sort(key=lambda p: (p['assessment']['priority'], p['name']))
    result['review_kind'] = 'remaining-additions'
    result['assessment_hash'] = digest(assessment)
    result['source_verification'] = assessment['source_verification']
    result['review_scope'] = assessment['scope']
    result['review_hash'] = digest({k: v for k, v in result.items() if k != 'review_hash'})
    return result


def build_next_area_review(plan_path, inventory_dir, boundaries_path, overlaps_path, assessment_path,
                           output=STATE / 'review-next-areas'):
    output = Path(output)
    # Never replace the first-round bundle: its hash keys existing browser notes.
    if output.resolve() == (STATE / 'review-parks').resolve():
        raise ValueError('Next-area review requires a separate output directory')
    assessment = read_json(assessment_path)
    plan = read_json(plan_path)
    if assessment.get('plan_hash') != plan.get('approval_hash'):
        raise ValueError('Next-area assessment belongs to another plan')
    if any(plan['changes'][k] for k in ('changed', 'deleted')):
        raise ValueError('Next-area review supports additions only')
    build_park_review(plan_path, inventory_dir, boundaries_path, overlaps_path, output)
    bundle = read_json(output / 'review.json')
    bundle['report'] = annotate_next_area_review(bundle['report'], assessment)
    bundle['assessment'] = assessment
    write_json(output / 'review.json', bundle)
    return output


def remaining_addition_candidate(plan, report, decisions):
    """Apply explicit inclusion choices to the exact reviewed current baseline."""
    verify_plan(plan)
    if digest({k: v for k, v in report.items() if k != 'review_hash'}) != report.get('review_hash'):
        raise ValueError('Remaining-addition report contents do not match their hash')
    if report.get('review_kind') != 'remaining-additions' or decisions.get('review_kind') != 'remaining-additions' or decisions.get('schema_version') != 2:
        raise ValueError('Expected a remaining-additions export, not park ownership decisions')
    if decisions.get('review_hash') != report['review_hash'] or decisions.get('plan_hash') != plan['approval_hash'] or report['plan_hash'] != plan['approval_hash']:
        raise ValueError('Addition decisions belong to another review or plan')
    diff = changes(plan['before'], plan['after'])
    if diff['changed'] or diff['deleted']:
        raise ValueError('Remaining-addition decisions cannot edit or delete existing features')
    areas = {area['id']: area for area in report['parks']}
    ids = [fid for area in report['parks'] for fid in area['review_feature_ids']]
    if len(areas) != len(report['parks']) or len(ids) != len(set(ids)) or set(ids) != set(diff['added']):
        raise ValueError('Reviewed areas do not cover exactly the proposed additions')
    selected = decisions.get('decisions')
    if not isinstance(selected, dict):
        raise ValueError('Expected an addition decisions object')
    included, held, kept, unreviewed = [], [], [], []
    for area_id, area in areas.items():
        choice = selected.get(area_id)
        if choice is None:
            unreviewed.extend(area['review_feature_ids']); continue
        if not isinstance(choice, dict) or choice.get('decision') not in {'include', 'keep-existing', 'discuss', 'unreviewed'}:
            raise ValueError('Invalid addition review decision')
        feature_ids = choice.get('feature_ids')
        if not isinstance(feature_ids, list) or not all(isinstance(fid, str) for fid in feature_ids) or len(feature_ids) != len(set(feature_ids)) or set(feature_ids) != set(area['review_feature_ids']):
            raise ValueError('Exported feature IDs differ from the reviewed area')
        if choice.get('dataset') is not None or not isinstance(choice.get('note', ''), str):
            raise ValueError('Addition decisions must not select replacement datasets and notes must be text')
        destination = {'include': included, 'keep-existing': kept, 'discuss': held, 'unreviewed': unreviewed}[choice['decision']]
        destination.extend(feature_ids)
    if set(selected) - set(areas):
        raise ValueError('Addition export contains an unknown area')
    proposed = {feature['id']: feature for feature in plan['after']['features']}
    candidate = canonical(copy.deepcopy(plan['before']))
    candidate['features'].extend(copy.deepcopy(proposed[fid]) for fid in sorted(included))
    candidate = canonical(candidate)
    candidate['ingest_report'] = {
        'reviewed_before_hash': plan['before_hash'], 'reviewed_target': plan['target'],
        'reviewed_plan_hash': plan['approval_hash'], 'remaining_additions_review_hash': report['review_hash'],
        'decision_export_hash': digest(decisions), 'decisions': copy.deepcopy(selected),
        'included': sorted(included), 'kept_existing': sorted(kept),
        'held_for_discussion': sorted(held), 'unreviewed': sorted(unreviewed),
        'requires_review': True,
    }
    return candidate
