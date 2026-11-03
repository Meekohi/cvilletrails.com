from maintenance.state_parks import normalize_trails


def transform(collection, config, source_id):
    if source_id != 'trails-gis':
        raise ValueError('State-park geometry must come from the registered DCR trail service')
    return normalize_trails(collection, config, source_id)
