"""Keep curated identities/properties; make disagreements visible in the review plan."""
import copy
from .geo import canonical
from .connections import connect_endpoints


def reconcile(baseline, candidate, legacy_id, keep_properties):
    baseline = canonical(baseline)
    report = copy.deepcopy(candidate.get('ingest_report', {}))
    candidate = canonical(candidate)
    old = {}
    for feature in baseline['features']:
        key = feature['properties'].get(legacy_id)
        if key is None or str(key) in old:
            raise ValueError('Baseline needs unique upstream IDs; reconcile ambiguous features manually')
        old[str(key)] = feature
    seen, result, conflicts, preserved_geometry = set(), [], [], []
    def near(a, b):
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(near(x, y) for x, y in zip(a, b))
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= 0.000001
    for feature in candidate['features']:
        key = str(feature['properties']['source_feature_id'])
        if key in seen: raise ValueError('Candidate has duplicate upstream IDs')
        seen.add(key)
        if key in old:
            curated = old[key]
            feature['id'] = curated['id']
            merged = {**curated['properties'], **feature['properties']}
            for prop in keep_properties:
                if prop in curated['properties']:
                    if prop in feature['properties'] and curated['properties'][prop] != feature['properties'][prop]:
                        conflicts.append({'feature_id': curated['id'], 'property': prop, 'curated': curated['properties'][prop], 'upstream': feature['properties'][prop]})
                    merged[prop] = curated['properties'][prop]
            feature['properties'] = merged
            # Projection round-trips can move every vertex by a few centimetres.
            # Keep curated coordinates when topology is identical and every value
            # is within 1e-6 degrees (~0.11 m); larger edits remain reviewable.
            if feature['geometry']['type'] == curated['geometry']['type'] and near(feature['geometry']['coordinates'], curated['geometry']['coordinates']):
                if feature['geometry'] != curated['geometry']: preserved_geometry.append(feature['id'])
                feature['geometry'] = copy.deepcopy(curated['geometry'])
        result.append(feature)
    missing = [feature for key, feature in old.items() if key not in seen]
    result.extend(missing)
    report.update({'retained_missing_upstream': [f['id'] for f in missing], 'property_conflicts': conflicts, 'preserved_submeter_geometry': preserved_geometry, 'requires_review': True})
    output = canonical({'type': 'FeatureCollection', 'features': result})
    output['ingest_report'] = report
    # Preserving one feature's rounded coordinates must not undo a reviewed join
    # when the connected feature also has a larger, substantive upstream edit.
    if report.get('endpoint_connections'):
        output = connect_endpoints(output, report['endpoint_connections'])
        snapped_sources = {r['source_feature_id'] for r in output['ingest_report']['endpoint_connections'] if r['distance_m'] > 0}
        snapped_ids = {f['id'] for f in output['features'] if f['properties'].get('source_feature_id') in snapped_sources}
        output['ingest_report']['preserved_submeter_geometry'] = [fid for fid in preserved_geometry if fid not in snapped_ids]
    return output
