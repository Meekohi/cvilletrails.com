from maintenance.geo import normalize


def transform(collection, config, source_id):
    """Keep named trail colors and apply durable manual curation last."""
    return normalize(collection, config, source_id)
