"""Explicit, bounded endpoint joins from reviewed curation decisions."""
import copy
from math import cos, radians, hypot, isfinite
from .geo import validate_collection


def connect_endpoints(collection, rules):
    validate_collection(collection)
    result = copy.deepcopy(collection)
    indexed = {}
    for feature in result['features']:
        sid = feature['properties'].get('source_feature_id')
        if sid is not None:
            if str(sid) in indexed: raise ValueError('Ambiguous source feature IDs for endpoint connection')
            indexed[str(sid)] = feature
    applied = []
    for rule in rules:
        source = indexed.get(rule['source_feature_id'])
        target = indexed.get(rule['target_source_feature_id'])
        if source is None or target is None:
            raise ValueError('A curated connection feature disappeared; review the connection rule')
        if source is target or source['geometry']['type'] != 'LineString' or target['geometry']['type'] != 'LineString':
            raise ValueError('Curated endpoint joins require two distinct LineStrings')
        if rule['endpoint'] not in {'start', 'end'} or rule['target_endpoint'] not in {'start', 'end'}:
            raise ValueError('Connection endpoint must be start or end')
        limit = rule['max_distance_m']
        if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not isfinite(limit) or limit <= 0:
            raise ValueError('Connection tolerance must be a positive finite distance')
        index = 0 if rule['endpoint'] == 'start' else -1
        target_index = 0 if rule['target_endpoint'] == 'start' else -1
        old = source['geometry']['coordinates'][index]
        new = target['geometry']['coordinates'][target_index]
        distance = hypot((new[0] - old[0]) * 111320 * cos(radians((old[1] + new[1]) / 2)), (new[1] - old[1]) * 111320)
        if distance > limit:
            raise ValueError(f"Curated connection moved {distance:.2f} m, beyond its {limit:g} m tolerance; review before snapping")
        source['geometry']['coordinates'][index] = copy.deepcopy(new)
        applied.append({**rule, 'distance_m': distance, 'before': old, 'after': new})
    report = result.setdefault('ingest_report', {})
    report['endpoint_connections'] = applied
    return result
