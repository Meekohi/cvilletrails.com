from maintenance.albemarle import normalize_trails


def transform(collection, config, source_id):
    """Screen the operational GIS and retain its original properties."""
    return normalize_trails(collection, config, source_id)
