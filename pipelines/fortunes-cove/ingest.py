from maintenance.geo import normalize


def transform(collection, config, source_id):
    if source_id != 'trail-map':
        raise ValueError('Only reviewed official-map vectors supply Fortune’s Cove geometry')
    return normalize(collection, config, source_id)
