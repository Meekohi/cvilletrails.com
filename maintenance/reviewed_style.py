"""Apply an exact data-backed style proposal to live and draft with recovery journals."""
from .common import STATE, digest, now, read_json, write_json
from .mapbox import validate_plan, verify_written
from .styles import editable_style


def publish_style(client, plan, manifest, proposed, approval, *, prepare, transform, journal_prefix, state_dir=STATE):
    if digest({k:v for k,v in manifest.items() if k != 'proposal_hash'}) != approval or manifest['proposal_hash'] != approval:
        raise ValueError('Approval does not match exact style proposal')
    target = validate_plan(plan, plan['approval_hash'])
    endpoint = f'styles/v1/{client.username}/{client.style_id}'
    live = client.call(endpoint, params={'optimize':'false'})[0]
    expected_manifest, expected_style = prepare(plan, live)
    if expected_manifest != manifest or expected_style != proposed:
        raise ValueError('Style, plan or extraction policy changed since review')
    receipt = read_json(state_dir/'publishes'/f"{plan['approval_hash']}.json")
    if receipt.get('state') != 'published' or receipt.get('target') != target:
        raise ValueError('Dataset publication must complete before style changes')
    verification = verify_written(plan, client.features(target['dataset']))
    if verification['stored_hash'] != receipt['verification']['stored_hash']:
        raise ValueError('Dataset differs from its publication receipt')
    path = state_dir/'publishes'/f'{journal_prefix}-{approval}.json'
    if path.exists(): raise ValueError('Style write already attempted; inspect journal before retrying')
    draft = client.call(endpoint+'/draft', params={'optimize':'false'})[0]
    draft_after = transform(draft)
    backup = state_dir/'backups'/f'{journal_prefix}-{approval}'
    for name, value in [('published',live),('draft',draft),('published-proposed',proposed),('draft-proposed',draft_after)]:
        write_json(backup/f'{name}.json',value)
    journal = {'state':'prepared','started_at':now(),'proposal_hash':approval,
               'dataset_plan_hash':plan['approval_hash'],'completed':[], 'dataset_verification':verification}
    write_json(path,journal)
    for name,before,after,url in [('draft',draft,draft_after,endpoint+'/draft'),('published',live,proposed,endpoint)]:
        if digest(client.call(url,params={'optimize':'false'})[0]) != digest(before):
            raise ValueError('Style changed immediately before write; inspect journal')
        journal['state']='updating-'+name;write_json(path,journal)
        response=client.call(url,'PATCH',editable_style(after))[0]
        write_json(backup/f'{name}-response.json',response)
        if editable_style(response) != editable_style(after): raise ValueError('Style response differs from proposal')
        journal['completed'].append({'version':name,'response_hash':digest(response)});write_json(path,journal)
    journal.update(state='published',finished_at=now());write_json(path,journal)
    return journal
