from maintenance.geo import normalize
from maintenance.common import read_json
from maintenance.connections import connect_endpoints


def transform(collection, config, source_id):
    """City GIS uses NAME. Preserve stable upstream IDs and all original fields."""
    missing = [str(f.get('id')) for f in collection['features'] if not f.get('geometry') or not f['geometry'].get('coordinates')]
    nonexisting = [str(f.get('id')) for f in collection['features'] if f['properties'].get('STATUS') != 'Existing'] if source_id == 'city-gis' else []
    drawable = {**collection, 'features': [f for f in collection['features'] if str(f.get('id')) not in missing + nonexisting]}
    result = normalize(drawable, config, source_id)
    result['ingest_report'] = {
        'source_features': len(collection['features']), 'normalized_features': len(result['features']),
        'excluded_empty_geometry': missing,
        'excluded_nonexisting': nonexisting,
        'requires_review': bool(missing or nonexisting),
    }
    if source_id == 'city-gis':
        result = connect_endpoints(result, read_json(config['_directory'] / 'connections.json'))
    return result
