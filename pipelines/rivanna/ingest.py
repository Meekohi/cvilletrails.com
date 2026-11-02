from maintenance.geo import normalize


def transform(collection, config, source_id):
    """GIS input must come from the trail manager, with stable feature identities."""
    return normalize(collection, config, source_id)
