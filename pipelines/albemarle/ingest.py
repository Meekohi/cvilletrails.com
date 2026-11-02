from maintenance.geo import normalize


def transform(collection, config, source_id):
    """Normalize county GeoJSON; retain TrailName for the legacy style palette."""
    return normalize(collection, config, source_id)
