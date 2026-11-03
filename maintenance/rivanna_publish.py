"""Publish only the closure styling from an approved Rivanna preview."""
import argparse
from pathlib import Path

from .common import STATE, digest, load_env, now, read_json, write_json
from .geo import changes
from .mapbox import Mapbox, validate_plan, verify_written
from .rivanna_candidate import closure_style
from .styles import editable_style


def publish_style(client, plan, manifest, proposed, approval, state_dir=STATE):
    unsigned = {k: v for k, v in manifest.items() if k != 'proposal_hash'}
    if digest(unsigned) != approval or manifest['proposal_hash'] != approval:
        raise ValueError('Approval does not match the exact Rivanna preview')
    target = validate_plan(plan, plan['approval_hash'])
    if (target['id'] != 'rivanna' or plan['before_hash'] != manifest['before_hash']
            or plan['after_hash'] != manifest['after_hash']
            or changes(plan['before'], plan['after']) != manifest['changes']
            or plan.get('ingest_report', {}).get('interpretation_hash') != manifest['interpretation_hash']):
        raise ValueError('Dataset plan differs from the approved Rivanna preview')
    if digest(proposed) != manifest['style_after_hash']:
        raise ValueError('Proposed style changed since review')
    receipt = read_json(state_dir/'publishes'/f"{plan['approval_hash']}.json")
    if (receipt.get('state') != 'published' or receipt.get('target') != target
            or receipt.get('approval_hash') != plan['approval_hash']):
        raise ValueError('Reviewed Rivanna dataset must finish publication first')
    verification = verify_written(plan, client.features(target['dataset']))
    if verification['stored_hash'] != receipt['verification']['stored_hash']:
        raise ValueError('Published dataset differs from its receipt')
    path = state_dir/'publishes'/f'rivanna-style-{approval}.json'
    if path.exists():
        raise ValueError('Style publication already attempted; inspect its journal before retrying')
    endpoint = f'styles/v1/{client.username}/{client.style_id}'
    live = client.call(endpoint, params={'optimize':'false'})[0]
    if digest(live) != manifest['style_before_hash'] or closure_style(live) != proposed:
        raise ValueError('Live style changed or proposal contains unrelated style changes')
    draft = client.call(endpoint+'/draft', params={'optimize':'false'})[0]
    draft_after = closure_style(draft)
    backup = state_dir/'backups'/f'rivanna-style-{approval}'
    write_json(backup/'published.json', live)
    write_json(backup/'draft.json', draft)
    write_json(backup/'published-proposed.json', proposed)
    write_json(backup/'draft-proposed.json', draft_after)
    journal = {'approval_hash':approval, 'dataset_plan_hash':plan['approval_hash'],
               'started_at':now(), 'state':'prepared', 'completed':[],
               'dataset_verification':verification,
               'changed_layers':['rivanna-trail fringe','rivanna-trail','rivanna-trail-label']}
    write_json(path, journal)
    for version, before, after, url in [('draft',draft,draft_after,endpoint+'/draft'),
                                       ('published',live,proposed,endpoint)]:
        if digest(client.call(url, params={'optimize':'false'})[0]) != digest(before):
            raise ValueError('Style changed immediately before publication; inspect journal')
        journal['state'] = 'updating-'+version
        write_json(path, journal)
        response = client.call(url, 'PATCH', editable_style(after))[0]
        write_json(backup/f'{version}-response.json', response)
        if editable_style(response) != editable_style(after):
            raise ValueError('Style response differs from the exact proposal; inspect journal')
        journal['completed'].append({'version':version,'before_hash':digest(before),
                                     'response_hash':digest(response)})
        write_json(path, journal)
    journal.update(state='published', finished_at=now())
    write_json(path, journal)
    return journal


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('preview', type=Path)
    parser.add_argument('--approve', required=True, help='Exact proposal_hash from the approved preview manifest')
    args = parser.parse_args()
    load_env()
    print(publish_style(Mapbox(), read_json(args.plan), read_json(args.preview/'manifest.json'),
                        read_json(args.preview/'style-proposal.json'), args.approve))
