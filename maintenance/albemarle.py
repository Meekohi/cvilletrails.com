"""Screen the County's operational GIS; never infer public access from a line."""
import copy
import re
from collections import Counter
from uuid import UUID

from .common import digest, read_json
from .geo import canonical, validate_collection


def clean(value):
    return ' '.join(str(value or '').split())


def global_id(feature):
    try:
        return str(UUID(clean(feature['properties'].get('GlobalID'))))
    except (ValueError, AttributeError, KeyError):
        raise ValueError('County feature has no valid GlobalID; do not fall back to OBJECTID') from None


def locations(config):
    result = {}
    for park_id, park in config['locations'].items():
        if park['system_id'] not in config['system_ids']:
            raise ValueError('County location has an unregistered system audience')
        for alias in park['aliases']:
            key = clean(alias).casefold()
            if not key or key in result:
                raise ValueError('County location aliases must be nonempty and unique')
            result[key] = (park_id, park)
    return result


def access_fingerprint(feature):
    """Bind a local access decision to geometry and access-relevant source facts."""
    return digest({'geometry': feature['geometry'], 'properties': {
        k: feature['properties'].get(k) for k in ('GlobalID', 'Loc_Name', 'Trail_Name',
            'Status', 'Ownership', 'Property_Info', 'Hiking', 'Surface')}})


def load_access_decisions(config):
    path = config['_directory'] / 'access-decisions.json'
    return read_json(path) if path.exists() else {}


def screen(collection, config, access_decisions=None):
    if collection.get('type') != 'FeatureCollection' or collection.get('crs') or not isinstance(collection.get('features'), list):
        raise ValueError('Expected WGS84 GeoJSON FeatureCollection without crs')
    aliases = locations(config)
    access_decisions = load_access_decisions(config) if access_decisions is None else access_decisions
    if access_decisions and (access_decisions.get('kind') != 'albemarle-reviewed-access'
            or access_decisions.get('schema_version') != 1
            or access_decisions.get('effective_access') != 'Open'
            or access_decisions.get('effective_hiking') != 'Yes'
            or not access_decisions.get('user_statement')
            or not access_decisions.get('review_hash')
            or not access_decisions.get('feedback_hash')):
        raise ValueError('Invalid County reviewed access decision')
    access_features = access_decisions.get('features', {})
    if not isinstance(access_features, dict):
        raise ValueError('Reviewed access features must be explicit IDs')
    rows, seen = [], set()
    for original in collection['features']:
        gid = global_id(original)
        if gid in seen:
            raise ValueError('Duplicate County GlobalID')
        seen.add(gid)
        p = original['properties']
        access_reviewed = gid in access_features
        if access_reviewed and access_fingerprint(original) != access_features[gid]:
            raise ValueError('Reviewed access source facts or geometry changed: ' + gid)
        park_id, park = aliases.get(clean(p.get('Loc_Name')).casefold(), (None, None))
        reasons = []
        if not park:
            reasons.append('location outside configured adapter scope')
        if clean(p.get('Status')) != 'Active':
            reasons.append('status is not Active')
        if clean(p.get('Ownership')) not in {'Public', 'Public Use Trail'}:
            reasons.append('ownership is not explicitly public')
        if clean(p.get('Property_Info')) != 'Open':
            reasons.append('access is closed, conditional or unknown')
        if clean(p.get('Hiking')) != 'Yes':
            reasons.append('hiking permission is not explicit')
        name = clean(p.get('Trail_Name'))
        if name.casefold() in {'', '<null>', 'null', 'n/a', 'na'}:
            reasons.append('missing trail name')
        if re.search(r'\b(inactive|closed|abandoned|private|proposed|future|pending|staff|maintenance|emergency)\b|flagged route|under construction', name, re.I):
            reasons.append('trail name needs access review')
        if clean(p.get('Surface')).casefold() == 'water':
            reasons.append('water route')
        geometry_valid = True
        try:
            if (original.get('geometry') or {}).get('type') not in {'LineString', 'MultiLineString'}:
                raise ValueError('Expected line geometry')
            validate_collection({'type': 'FeatureCollection', 'features': [{**original, 'id': gid}]})
            lines = original['geometry']['coordinates']
            if original['geometry']['type'] == 'LineString':
                lines = [lines]
            if any(not any(p[:2] != line[0][:2] for p in line[1:]) for line in lines):
                raise ValueError('Zero length line')
        except ValueError:
            geometry_valid = False
            reasons.append('invalid or empty line geometry')
        if access_reviewed:
            reasons = [r for r in reasons if r not in {
                'access is closed, conditional or unknown', 'hiking permission is not explicit'}]
            if reasons:
                raise ValueError('Reviewed access cannot bypass other eligibility holds: ' + gid)
        rows.append({'id': 'albemarle:' + gid, 'global_id': gid, 'object_id': p.get('OBJECTID'),
                     'park_id': park_id or 'outside-scope', 'location': clean(p.get('Loc_Name')) or '(unassigned)',
                     'name': name, 'status': p.get('Status'), 'ownership': p.get('Ownership'),
                     'access': 'Open' if access_reviewed else p.get('Property_Info'),
                     'hiking': 'Yes' if access_reviewed else p.get('Hiking'),
                     'source_access': p.get('Property_Info'), 'source_hiking': p.get('Hiking'),
                     'access_reviewed': access_reviewed,
                     'category': 'held' if reasons else 'eligible', 'reasons': reasons,
                     'geometry_valid': geometry_valid})
    if set(access_features) - seen:
        raise ValueError('Reviewed access record disappeared; investigate the source change')
    return rows


def normalize_trails(collection, config, source_id):
    if source_id != 'county-gis':
        raise ValueError('County geometry must use the registered county-gis source')
    source = next(s for s in config['sources'] if s['id'] == source_id)
    access_decisions = load_access_decisions(config)
    rows = screen(collection, config, access_decisions)
    overrides = read_json(config['_directory'] / 'overrides.json')
    features, used = [], set()
    for original, row in zip(collection['features'], rows):
        if row['reasons']:
            continue
        gid = row['global_id']
        park = config['locations'][row['park_id']]
        feature = copy.deepcopy(original)
        feature['id'] = row['id']
        p = feature['properties']
        p.update({'name': row['name'], 'TrailName': row['name'], 'LocationNa': park['legacy_location'],
                  'pipeline_id': 'albemarle', 'system_id': park['system_id'], 'park_id': row['park_id'],
                  'source_id': source_id, 'source_feature_id': gid, 'source_url': source['url'],
                  'attribution': 'Albemarle County, VA'})
        if row['access_reviewed']:
            p.update({'source_Property_Info': p.get('Property_Info'), 'source_Hiking': p.get('Hiking'),
                'Property_Info': row['access'], 'Hiking': row['hiking'],
                'access_basis': 'user-reviewed local correction',
                'access_feedback_hash': access_decisions['feedback_hash'],
                'access_review_hash': access_decisions['review_hash']})
        # Overrides may preserve reviewed curation, but cannot grant access or change identity.
        if gid in overrides:
            override = overrides[gid]
            if set(override) != {'properties'} or set(override['properties']) - {'name', 'TrailName', 'color'}:
                raise ValueError('County overrides may only preserve name, TrailName and color')
            p.update(override['properties'])
            used.add(gid)
        features.append(feature)
    if set(overrides) - used:
        raise ValueError('County override disappeared or is no longer eligible; investigate the source change')
    result = canonical({'type': 'FeatureCollection', 'features': features})
    result['ingest_report'] = {
        'review_only': True, 'requires_review': True, 'publication_authorized': False,
        'source_features': len(rows), 'normalized_features': len(features),
        'held': [r for r in rows if r['reasons']],
        'held_reasons': dict(Counter(reason for r in rows for reason in r['reasons'])),
        'source_hash': digest(collection),
        'policy_hash': digest({k: v for k, v in config.items() if k != '_directory'}),
        'overrides_hash': digest(overrides),
        'access_decisions_hash': digest(access_decisions),
        'reviewed_access_features': [r['id'] for r in rows if r['access_reviewed']],
        'note': 'Screened source subset, not a replacement dataset. Review a geometry crosswalk against a fresh inventory; retain unmatched curated trails.',
    }
    return result
