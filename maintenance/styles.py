"""Retire reviewed display layers while keeping their original datasets archived."""
import copy
from pathlib import Path
from .common import ROOT, STATE, digest, now, read_json, write_json
from .geo import fingerprint
from .mapbox import validate_plan, verify_written, target_by_id


def hide_layers(style, layer_ids, source_layers):
    result = copy.deepcopy(style)
    selected = [layer for layer in result['layers'] if layer['id'] in layer_ids]
    if not layer_ids or len(selected) != len(set(layer_ids)):
        raise ValueError('Retirement layer IDs do not match the style')
    for layer in selected:
        if layer.get('source-layer') not in source_layers:
            raise ValueError('Retirement would hide a layer outside the reviewed datasets')
        layer.setdefault('layout', {})['visibility'] = 'none'
    return result


def editable_style(style):
    # The Styles API rejects these server-owned timestamps on PATCH.
    return {k: v for k, v in style.items() if k not in {'created', 'modified'}}


def retire_style_layers(client, manifest_path, approval, state_dir=STATE):
    manifest_path = Path(manifest_path)
    manifest = read_json(manifest_path)
    if digest(manifest) != approval:
        raise ValueError('Approval does not match the exact consolidation manifest')
    policy = read_json(ROOT / 'config/park-ownership.json')
    if manifest['policy_hash'] != digest(policy):
        raise ValueError('Ownership policy changed since review')
    proposal = manifest['style_proposal']
    proposed_style = read_json(proposal['path'])
    if digest(proposed_style) != proposal['after_hash']:
        raise ValueError('Style proposal changed since review')
    path = state_dir / 'publishes' / f'style-{approval}.json'
    if path.exists():
        raise ValueError('Style retirement already attempted; inspect its saved journal before retrying')
    archived = []
    for item in manifest['datasets']:
        if item['publication_method'] == 'retire-style-layers-keep-dataset':
            data = client.features(item['dataset'])
            if fingerprint(data) != item['before_hash']:
                raise ValueError('Dataset to archive changed since review')
            archived.append((item, data))
        else:
            plan = read_json(manifest_path.parent / f"{item['target']}-plan.json")
            validate_plan(plan, plan['approval_hash'])
            if plan['after_hash'] != item['after_hash'] or plan['before_hash'] != item['before_hash']:
                raise ValueError('Published plan does not match the consolidation manifest')
            journal = read_json(state_dir / 'publishes' / f"{plan['approval_hash']}.json")
            if journal['state'] != 'published':
                raise ValueError('Replacement datasets must finish publication before layer retirement')
            verify_written(plan, client.features(item['dataset']))
    for item in manifest['protected_datasets']:
        if fingerprint(client.features(item['dataset'])) != item['hash']:
            raise ValueError('Protected network changed since consolidation review')
    live = client.style()
    if digest(live) != proposal['before_hash']:
        raise ValueError('Live style changed since review')
    source_layers = {target_by_id(item['target'])['source_layer'] for item, _ in archived}
    protected_layers = {item['source_layer'] for item in policy['protected_datasets']}
    if source_layers & protected_layers:
        raise ValueError('Cannot retire protected network layers')
    expected = hide_layers(live, proposal['hide_layers'], source_layers)
    if expected != proposed_style:
        raise ValueError('Style proposal contains changes beyond the reviewed layer retirement')
    endpoint = f'styles/v1/{client.username}/{client.style_id}'
    draft = client.call(endpoint + '/draft')[0]
    draft_after = hide_layers(draft, proposal['hide_layers'], source_layers)
    backup = state_dir / 'backups' / f'style-{approval}'
    write_json(backup / 'published.json', live)
    write_json(backup / 'draft.json', draft)
    for item, data in archived:
        write_json(backup / f"{item['target']}.geojson", data)
    journal = {'approval_hash': approval, 'started_at': now(), 'state': 'prepared',
               'hide_layers': proposal['hide_layers'], 'archived_datasets': [item['dataset'] for item, _ in archived],
               'protected_networks_unchanged': True, 'completed': []}
    write_json(path, journal)
    for version, before, after, url in [('draft', draft, draft_after, endpoint + '/draft'),
                                       ('published', live, expected, endpoint)]:
        if digest(client.call(url)[0]) != digest(before):
            raise ValueError('Style changed immediately before retirement; inspect the journal')
        journal['state'] = f'updating-{version}'
        write_json(path, journal)
        response = client.call(url, 'PATCH', editable_style(after))[0]
        write_json(backup / f'{version}-response.json', response)
        if editable_style(response) != editable_style(after):
            raise ValueError('Style update response differs from the exact retirement; inspect the journal')
        journal['completed'].append({'version': version, 'response_hash': digest(response)})
        write_json(path, journal)
    journal.update(state='published', finished_at=now())
    write_json(path, journal)
    return journal
