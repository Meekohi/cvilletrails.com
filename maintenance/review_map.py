"""Build a local visual review, and turn exported decisions into a new candidate."""
import copy
import re
import shutil
from pathlib import Path
from .common import ROOT, STATE, digest, read_json, write_json
from .geo import canonical, changes, fingerprint


def verify_plan(plan):
    if digest({k: v for k, v in plan.items() if k != 'approval_hash'}) != plan['approval_hash']:
        raise ValueError('Plan hash does not match its contents')
    if fingerprint(plan['before']) != plan['before_hash'] or fingerprint(plan['after']) != plan['after_hash']:
        raise ValueError('Plan dataset fingerprints do not match')


def review_rows(plan):
    verify_plan(plan)
    old = {f['id']: f for f in canonical(plan['before'])['features']}
    new = {f['id']: f for f in canonical(plan['after'])['features']}
    diff = changes(plan['before'], plan['after'])
    report = plan.get('ingest_report', {})
    retained = set(report.get('retained_missing_upstream', []))
    conflicts = {}
    for item in report.get('property_conflicts', []): conflicts.setdefault(item['feature_id'], []).append(item)
    rows = []
    for fid in sorted(old.keys() | new.keys()):
        before, after = old.get(fid), new.get(fid)
        kinds = []
        if fid in diff['added']: kinds.append('added')
        if fid in diff['deleted']: kinds.append('deleted')
        if fid in diff['geometry_changed']: kinds.append('geometry')
        if fid in retained: kinds.append('retained')
        if fid in conflicts: kinds.append('conflict')
        altered = [key for key, value in (before or {}).get('properties', {}).items() if after and (key not in after['properties'] or after['properties'][key] != value)]
        if altered: kinds.append('attributes')
        if not kinds and fid in diff['changed']: kinds.append('metadata')
        if not kinds: continue
        props = (after or before)['properties']
        name = next((props[k] for k in ('name', 'NAME', 'Name', 'TrailName') if isinstance(props.get(k), str) and props[k].strip()), 'Unnamed trail')
        rows.append({'id': fid, 'name': name, 'kinds': kinds, 'conflicts': conflicts.get(fid, []), 'changed_properties': altered})
    return rows


def verify_resolution_context(plan, context):
    verify_plan(plan)
    if digest({k: v for k, v in context.items() if k != 'context_hash'}) != context.get('context_hash'):
        raise ValueError('Resolution context hash does not match its contents')
    if context.get('plan_hash') != plan['approval_hash'] or context.get('target') != plan['target']:
        raise ValueError('Resolution context belongs to a different plan or target')
    if fingerprint(context['current_baseline']) != context['current_hash']:
        raise ValueError('Resolution context baseline changed')
    if set(context['resolutions']) - {r['id'] for r in review_rows(plan)}:
        raise ValueError('Resolution context references unknown review features')


def build_resolution_context(plan, audit, park_report, policy, inventory_dir):
    """Annotate an old review without changing its plan or saved decision history.

    Only an approved, published consolidation can resolve rows. Nearness to the
    chosen source is used to flag exceptions, never to approve new geometry.
    """
    from .overlaps import geometry_tools
    from .mapbox import stored_coordinates
    verify_plan(plan)
    report = park_report.get('report', park_report)
    manifest = audit['prepared_changes']
    receipt = audit['publication_receipt']
    manifest_hash = digest(manifest)
    if not audit.get('publication_status', '').startswith('published') or receipt.get('status') != 'published':
        raise ValueError('Resolution context requires a published consolidation')
    if manifest_hash != audit['approval']['manifest_hash'] or manifest_hash != receipt['manifest_hash']:
        raise ValueError('Consolidation approval or publication does not match the manifest')
    if digest(policy) != manifest['policy_hash'] or digest(policy) != audit['policy_hash']:
        raise ValueError('Ownership policy changed since the published consolidation')
    if manifest['plan_hash'] != plan['approval_hash'] or report['plan_hash'] != plan['approval_hash']:
        raise ValueError('Consolidation belongs to another City proposal')
    if digest({k: v for k, v in report.items() if k != 'review_hash'}) != report['review_hash'] or report['review_hash'] != manifest['review_hash']:
        raise ValueError('Park review hash does not match the published consolidation')
    style_hash = digest(read_json(Path(inventory_dir) / 'style.json'))
    if style_hash != receipt.get('style_readback', {}).get('published', {}).get('hash'):
        raise ValueError('Current style differs from the verified published consolidation')
    current = {}
    published_hashes = {d['target']: d['stored_hash'] for d in receipt['datasets']}
    changed = {d['dataset']: d for d in manifest['datasets']}
    for source in report['sources']:
        did = source['dataset']
        item = changed.get(did)
        expected = published_hashes[item['target']] if item and item['publication_method'] == 'reviewed-dataset-update' else source['hash']
        current[did] = canonical(read_json(Path(inventory_dir) / 'datasets' / f'{did}.geojson'))
        if fingerprint(current[did]) != expected:
            raise ValueError('Current inventory differs from the published consolidation; refresh and reconcile')
    city = plan['target']['dataset']
    current_city = {f['id']: f for f in current[city]['features']}
    proposed = {f['id']: f for f in plan['after']['features']}
    project, union, _ = geometry_tools()
    parks = {p['id']: p for p in report['parks']}
    selected = [(rule, project(parks[rule['id']]['boundary'])) for rule in policy['parks']
                if rule['id'] in audit['original_export']['decisions'] and audit['original_export']['decisions'][rule['id']]['decision'] != 'unreviewed']
    # Respect the same explicitly recorded boundary precedence as publication.
    priority = policy.get('boundary_priority', [])
    selected.sort(key=lambda pair: priority.index(pair[0]['id']) if pair[0]['id'] in priority else len(priority))
    occupied = union([])
    regions = []
    for rule, area in selected:
        if rule['mode'] == 'winner':
            region = area.difference(occupied)
            occupied = union([occupied, area])
            regions.append((rule, region))
    owners = {rule['geometry_dataset'] for rule, _ in regions if rule['geometry_dataset'] != city}
    owner_lines = {did: union([project(f['geometry']) for f in current[did]['features']]).buffer(10) for did in owners}
    resolutions = {}
    for row in review_rows(plan):
        fid = row['id']
        if 'added' not in row['kinds']: continue
        feature = proposed[fid]
        live = current_city.get(fid)
        geometry = project(feature['geometry'])
        if live:
            stored = copy.deepcopy(feature)
            stored['geometry']['coordinates'] = stored_coordinates(stored['geometry']['coordinates'])
            if live == feature or live == stored:
                resolutions[fid] = {'status': 'published', 'needs_review': False, 'accept_allowed': False,
                                    'explanation': 'This complete addition was already approved and published. No individual acceptance is needed.'}
                continue
            remainder = geometry.difference(project(live['geometry']).buffer(.2))
        else:
            remainder = geometry
        owned = union([])
        covered = union([])
        owner_names = []
        for rule, area in regions:
            if rule['geometry_dataset'] == city: continue
            piece = remainder.intersection(area.buffer(1))
            if piece.length < .1: continue
            owner_names.append(parks[rule['id']]['name'])
            owned = union([owned, piece])
            covered = union([covered, piece.intersection(owner_lines[rule['geometry_dataset']])])
        if not live and owned.length < .1: continue
        outside_m = remainder.difference(owned.buffer(.05)).length
        unmatched_m = max(0, owned.length - covered.length)
        # Avoid treating a strong aggregate overlap as proof that a connector
        # or a long unmatched section is dispensable.
        coverage = covered.length / owned.length if owned.length else 1
        exception = outside_m > 2 or unmatched_m > 20 or coverage < .95
        status = 'split-published' if live else 'excluded-by-owner'
        explanation = ('Only the approved park portion was published; accepting the original whole line would reintroduce excluded geometry.' if live else
                       'The approved park choice keeps the existing owner dataset instead of adding this overlapping City line.')
        if exception:
            status += '-exception'
            explanation += ' A boundary remainder or unmatched stretch still needs discussion; do not accept the whole original proposal.'
        else:
            explanation += ' This is resolved by the published park decision; no individual acceptance is needed.'
        resolutions[fid] = {'status': status, 'needs_review': exception, 'accept_allowed': False,
                            'explanation': explanation, 'parks': owner_names,
                            'metrics': {'unpublished_length_m': round(remainder.length, 2), 'outside_decided_owner_m': round(outside_m, 2),
                                        'unmatched_owner_m': round(unmatched_m, 2), 'owner_coverage_10m': round(coverage, 4)}}
    context = {'schema_version': 1, 'plan_hash': plan['approval_hash'], 'target': plan['target'],
               'manifest_hash': manifest_hash, 'policy_hash': digest(policy), 'park_review_hash': report['review_hash'],
               'current_style_hash': style_hash,
               'published_at': receipt['finished_at'], 'current_baseline': current[city], 'current_hash': fingerprint(current[city]),
               'resolutions': resolutions,
               'method': 'Published additions and approved owner choices; exceptions remain if >2 m outside decided ownership, >20 m unmatched, or <95% within 10 m of the selected owner. No geometry is accepted automatically.'}
    context['context_hash'] = digest(context)
    return context


def build_review(plan_path, state_dir=STATE, overlaps_path=None, resolution_context_path=None):
    plan = read_json(plan_path)
    rows = review_rows(plan)
    context = read_json(resolution_context_path) if resolution_context_path else None
    if context:
        verify_resolution_context(plan, context)
        for row in rows:
            if row['id'] in context['resolutions']: row['resolution'] = context['resolutions'][row['id']]
    overlaps = read_json(overlaps_path) if overlaps_path else None
    if overlaps and overlaps.get('plan_hash') != plan['approval_hash']:
        raise ValueError('Overlap comparison belongs to a different review plan')
    target = plan['target']['id']
    if not re.fullmatch(r'[a-z0-9-]+', target): raise ValueError('Invalid target identifier')
    output = state_dir / f'review-{target}'
    output.mkdir(parents=True, exist_ok=True)
    for filename in ('index.html', 'review.js', 'review.css'):
        shutil.copyfile(ROOT / 'maintenance/review_ui' / filename, output / filename)
    token = re.search(r"mapboxgl.accessToken = '(pk\.[^']+)'", (ROOT / 'assets/app.js').read_text())
    if not token: raise ValueError('Public map token not found in website configuration')
    settings = read_json(ROOT / 'config/mapbox.json')
    write_json(output / 'review.json', {
        'plan': plan, 'rows': rows, 'public_token': token[1],
        'style': f"mapbox://styles/{settings['username']}/{settings['style_id']}",
        'overlaps': overlaps,
        'resolution_context': context,
    })
    return output


def reviewed_candidate(plan, decisions, resolution_context=None):
    verify_plan(plan)
    if decisions.get('plan_hash') != plan['approval_hash']:
        raise ValueError('Decisions belong to a different plan')
    if decisions.get('resolution_context_hash') and resolution_context is None:
        raise ValueError('This export requires its resolution context; never apply it to the historical baseline')
    if resolution_context:
        verify_resolution_context(plan, resolution_context)
        if decisions.get('resolution_context_hash') != resolution_context['context_hash']:
            raise ValueError('Decisions do not match the current resolution context')
        if digest(read_json(ROOT / 'config/park-ownership.json')) != resolution_context['policy_hash']:
            raise ValueError('Ownership policy changed; refresh the resolution context before building a candidate')
    rows = {r['id'] for r in review_rows(plan)}
    selections = decisions.get('decisions')
    if not isinstance(selections, dict): raise ValueError('Expected a decisions object')
    for fid, choice in selections.items():
        if fid not in rows or not isinstance(choice, dict) or choice.get('decision') not in {'accept', 'defer', 'discuss', 'unreviewed'}:
            raise ValueError('Unknown feature or invalid review decision')
    baseline = resolution_context['current_baseline'] if resolution_context else plan['before']
    result = {f['id']: copy.deepcopy(f) for f in canonical(baseline)['features']}
    old = {f['id']: f for f in plan['before']['features']}
    proposed = {f['id']: f for f in canonical(plan['after'])['features']}
    for fid, choice in selections.items():
        if choice['decision'] != 'accept': continue
        if resolution_context and not resolution_context['resolutions'].get(fid, {}).get('accept_allowed', True):
            raise ValueError(f'{fid} is governed by a published park decision; whole-proposal acceptance is blocked')
        if resolution_context and fid in old and fid in proposed:
            if fid not in result: raise ValueError('Reviewed feature no longer exists in the current baseline')
            a, b, current = old[fid], proposed[fid], result[fid]
            if a['geometry'] != b['geometry']:
                if current['geometry'] not in (a['geometry'], b['geometry']):
                    raise ValueError('Geometry changed since the original review; reconcile this feature separately')
                current['geometry'] = copy.deepcopy(b['geometry'])
            for key in a['properties'].keys() | b['properties'].keys():
                old_state = (key in a['properties'], a['properties'].get(key))
                new_state = (key in b['properties'], b['properties'].get(key))
                if old_state == new_state: continue
                current_state = (key in current['properties'], current['properties'].get(key))
                if current_state not in (old_state, new_state):
                    raise ValueError('A property changed since the original review; reconcile this feature separately')
                if key in b['properties']: current['properties'][key] = copy.deepcopy(b['properties'][key])
                else: current['properties'].pop(key, None)
        elif fid in proposed:
            if resolution_context and fid in result:
                raise ValueError('Proposed addition already exists in the published baseline')
            result[fid] = copy.deepcopy(proposed[fid])
        else:
            if resolution_context and fid in result and result[fid] != old.get(fid):
                raise ValueError('Deletion would remove a feature changed since the original review')
            result.pop(fid, None)
    candidate = canonical({'type': 'FeatureCollection', 'features': list(result.values())})
    candidate['ingest_report'] = {
        'reviewed_plan_hash': plan['approval_hash'],
        'reviewed_before_hash': fingerprint(baseline),
        'reviewed_target': plan['target'],
        'decisions': selections,
        'original_ingest_report': plan.get('ingest_report', {}),
        'requires_review': True,
    }
    if resolution_context:
        candidate['ingest_report']['resolution_context_hash'] = resolution_context['context_hash']
        candidate['ingest_report']['historical_decisions'] = decisions.get('historical_decisions', {})
    return candidate
