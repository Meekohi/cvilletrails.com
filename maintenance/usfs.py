"""Conservative GW/Jefferson normalization; geometry presence is not public access."""
import uuid
from .geo import canonical, validate_collection
from .common import digest
from .access_review import meaningful


def transform(collection, config, source_id):
    source = next(s for s in config['sources'] if s['id'] == source_id)
    features, held, rejected, excluded, recheck = [], [], [], [], []
    seen = set()
    for original in collection['features']:
        p = {k.lower():v for k,v in original['properties'].items()}
        if not str(p.get('admin_org', '')).startswith('0808'):
            raise ValueError('Forest Service response escaped the configured forest scope')
        try: sid = str(uuid.UUID(p['globalid'].strip('{}')))
        except (KeyError, ValueError, AttributeError):
            raise ValueError('Missing valid stable Forest Service GlobalID') from None
        if sid in seen: raise ValueError('Duplicate Forest Service GlobalID')
        seen.add(sid)
        name = str(p.get('trail_name') or '').strip().upper()
        if name in config.get('excluded_trail_names', {}):
            excluded.append({'id':'usfs-gwj:'+sid, 'name':p['trail_name'], 'reason':config['excluded_trail_names'][name]})
            continue
        exclusion = config.get('feature_exclusions', {}).get(sid)
        if exclusion:
            if digest(original['geometry']) == exclusion['geometry_hash']:
                excluded.append({'id':'usfs-gwj:'+sid, 'name':p['trail_name'], 'reason':exclusion['reason']})
                continue
            recheck.append({'id':'usfs-gwj:'+sid,'reason':'Previously rejected short geometry changed; repeat connectivity review'})
        preferred = config.get('preferred_route_sources', {}).get(str(p.get('trail_name') or '').strip().upper())
        if preferred:
            excluded.append({'id':'usfs-gwj:'+sid, 'name':p['trail_name'], 'reason':'User-selected authoritative route source', **preferred})
            continue
        reason = None
        def field(key): return str(p.get(key) or '').strip()
        if field('trail_type') != 'TERRA': reason = 'Not a terrestrial trail'
        elif config.get('access_policy') != 'assume-open-unless-contrary' and field('attributesubset') != 'TrailNFS_MGMT': reason = 'No management/access attributes'
        elif meaningful(p.get('hiker_pedestrian_restricted')): reason = 'Hiking restriction requires review'
        elif meaningful(p.get('hiker_pedestrian_disc')): reason = 'Hiking discouraged'
        elif any(word in name for word in ('DECOMMISSION', '(DECO', 'CLOSED', 'ABANDONED')):
            reason = 'Source name indicates decommissioning, closure or abandonment'
        elif config.get('access_policy') != 'assume-open-unless-contrary' and not any(field(k) == '01/01-12/31' for k in ('hiker_pedestrian_managed', 'hiker_pedestrian_accpt')):
            reason = 'No unambiguous year-round managed/accepted hiking record'
        props = {**p, 'name':p.get('trail_name') or 'Unnamed Forest Service trail',
                 'system_id':'usfs-gwj', 'pipeline_id':'usfs-gwj', 'source_id':source_id,
                 'source_feature_id':sid, 'source_url':source['url'], 'color':None,
                 'geometry_method':'official-usfs-gis', 'access_review':reason or ('No contrary access evidence; user policy assumes open; current forest orders still apply' if config.get('access_policy') == 'assume-open-unless-contrary' else 'Year-round hiking management recorded; current forest orders still apply')}
        feature = {'type':'Feature', 'id':'usfs-gwj:'+sid, 'properties':props, 'geometry':original['geometry']}
        try:
            validate_collection({'type':'FeatureCollection', 'features':[feature]})
            if original['geometry']['type'] not in {'LineString', 'MultiLineString'}:
                raise ValueError('Expected trail line geometry')
        except ValueError as error:
            rejected.append({'id':feature['id'], 'name':props['name'], 'reason':str(error)})
            continue
        features.append(feature)
        if reason: held.append({'id':feature['id'], 'reason':reason})
    result = canonical({'type':'FeatureCollection', 'features':features})
    result['ingest_report'] = {'review_only':True, 'held':held, 'excluded':excluded, 'rejected':rejected, 'source_count':len(collection['features']), 'connectivity_recheck':recheck,
        'reason':'Review access holds, existing-map overlaps and current forest orders before publication; no blaze colors inferred.'}
    return result
