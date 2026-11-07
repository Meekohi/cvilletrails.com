"""Source-aware exception review against a frozen, user-accepted additions batch."""
import argparse
import json
import shutil
from collections import Counter
from pathlib import Path
from .common import ROOT, digest, now, read_json, write_json
from .geo import canonical, fingerprint
from .overlaps import geometry_tools, coverage

ACTIONS = {
    'pending': 'Not decided',
    'official-at': 'Prefer official NPS / ATC centerline',
    'existing': 'Keep existing source',
    'incoming': 'Prefer incoming USFS geometry; preserve verified colors',
    'split': 'Keep existing overlap; add the distinct remainder',
    'shared': 'Preserve both routes; reconcile shared tread / junction',
    'hold': 'Continue holding for evidence',
}


def verify_acceptance(root):
    report = read_json(root/'review.json')
    if digest({k:v for k,v in report.items() if k != 'review_hash'}) != report['review_hash']:
        raise ValueError('Original review changed')
    incoming = read_json(root/'incoming.geojson')
    receipt = read_json(root/'accepted/receipt.json')
    decisions = read_json(root/'accepted/user-decisions.json')
    selected = read_json(root/'accepted/additions.geojson')
    if fingerprint(incoming) != report['incoming_hash'] or receipt['review_hash'] != report['review_hash']:
        raise ValueError('Acceptance does not match the original review')
    if digest(decisions) != receipt['decision_hash'] or decisions['review_hash'] != report['review_hash']:
        raise ValueError('User decisions changed')
    accepted_ids = set(receipt['accepted_feature_ids'])
    proposed_ids = {r['id'] for r in report['rows'] if r['status'] == 'proposed'}
    if accepted_ids != proposed_ids or accepted_ids != {k for k,v in decisions['decisions'].items() if v == 'include'}:
        raise ValueError('Accepted set differs from the approved batch')
    expected = canonical({'type':'FeatureCollection','features':[f for f in incoming['features'] if f['id'] in accepted_ids]})
    if fingerprint(selected) != receipt['accepted_geometry_hash'] or canonical(selected) != expected:
        raise ValueError('Accepted geometry changed')
    for filename,key in [('style-proposal.json','style_proposal_hash'),('systems-proposal.json','systems_proposal_hash')]:
        if digest(read_json(root/filename)) != receipt[key]: raise ValueError('Accepted supporting proposal changed')
    return report, incoming, receipt


def recommendation(row, matches, peers):
    """Authority recommendations never treat proximity alone as trail identity."""
    if row['status'] == 'alternate-source':
        return 'resolved', 'existing', 'Sandy Gap: TNC approved', 'The user explicitly accepted the complete TNC route. Retain its blue map symbol and hold the USFS alternative.', []
    if row['status'] in {'access-hold','geometry-hold'}:
        return 'access', 'hold', 'Access evidence needed', 'Source authority does not resolve access restrictions, unclear hiking management, or missing geometry. Keep held until the evidence is resolved.', ['hold']
    if row['name'] == 'APPALACHIAN TRAIL':
        return 'appalachian', 'official-at', 'Appalachian Trail: use NPS / ATC', 'The live ATC map uses the NPS-owned APPA Official Centerline. Prefer that maintained route-wide source over the unlabelled January 2020 local import or a patchwork of USFS segments. Compare and replace bounded sections while preserving the rest of the existing AT.', ['official-at','existing','incoming','hold']
    if any(m['properties'].get('pipeline_id') == 'virginia-state-parks' for m in matches):
        action = 'existing' if row['status']=='duplicate' else 'split'
        return 'state-parks', action, 'State park overlap: retain DCR', 'Existing lines are already official Virginia DCR GIS, with park-specific names and blaze colors. Retain DCR on shared park tread; inspect USFS continuations outside the shared section separately.', ['existing','split','incoming','hold']
    if any(m['properties'].get('reference_source') == 'meekohi.8n5896es' for m in matches):
        action = 'incoming' if row['name'].startswith('TUSCARORA') else 'shared'
        return 'patc', action, 'Tuscarora / Massanutten: compare USFS with PATC', 'The old uploaded layer contains a documented December 2019 PATC differential-GPS survey, claimed horizontal accuracy 1–5 m, and blue blaze information. Prefer the maintained USFS feed for confirmed National Forest segments, but preserve verified colors and unaffected NPS/PATC routes. Service freshness alone does not prove better geometry. Differently named routes may share tread; retain their route identities.', ['incoming','existing','split','shared','hold']
    if row['status'] == 'incoming-overlap':
        exact = any(p['coverage_3m'] >= .95 and p['reverse_3m'] >= .95 for p in peers)
        detail = 'Near-identical geometry needs one physical representation while retaining route identities.' if exact else 'These records come from the same official USFS feed. They may be shared tread, route aliases, or nearby junctions; agency rank cannot choose between them.'
        return 'same-source', 'shared', 'Within USFS: reconcile topology', detail+' Compare trail numbers, route IDs and mileposts before merging or cutting geometry.', ['shared','hold']
    return 'at-junctions', 'split', 'AT approaches: inspect the junction', 'This is a differently named USFS trail near the existing AT, not proof of a duplicate AT route. Compare the official AT centerline, keep legitimate side-trail connections, and remove only confirmed shared tread.', ['shared','split','existing','incoming','hold']


def build(root, research, output):
    report,incoming,receipt = verify_acceptance(root)
    project,union,Tree = geometry_tools()
    by_id = {f['id']:f for f in incoming['features']}
    rows_by_id = {r['id']:r for r in report['rows']}
    existing = read_json(root/'existing-overlaps.geojson')
    old_by_id = {f['id']:f for f in existing['features']}
    official = read_json(research/'at-official-regional.geojson')
    official_geoms = [project(f['geometry']) for f in official['features']]
    official_tree = Tree(official_geoms)
    geometries = {fid:project(f['geometry']) for fid,f in by_id.items()}
    accepted_ids = set(receipt['accepted_feature_ids'])
    rows=[]; used_official=set()
    for row in report['rows']:
        if row['id'] in accepted_ids: continue
        line=geometries[row['id']]
        peers=[]
        for fid in row['incoming_matches']:
            other=geometries[fid];p=by_id[fid]['properties']
            forward=coverage(line,other,(3,20));reverse=coverage(other,line,(3,20))
            peers.append({'id':fid,'name':p['name'],'accepted':fid in accepted_ids,'status':rows_by_id[fid]['status'],
                          'trail_no':p.get('trail_no'),'trail_cn':p.get('trail_cn'),'bmp':p.get('bmp'),'emp':p.get('emp'),
                          'coverage_3m':forward['3'],'coverage_20m':forward['20'],'reverse_3m':reverse['3'],'reverse_20m':reverse['20']})
        matches=[old_by_id[m['id']] for m in row['matches']]
        category,action,title,reason,options = recommendation(row,matches,peers)
        found=[int(i) for i in official_tree.query(line.buffer(100))]
        used_official.update(found)
        at_union=union([official_geoms[i] for i in found])
        official_coverage=coverage(line,at_union,(3,10,20,30)) if found else {str(d):0 for d in (3,10,20,30)}
        p=by_id[row['id']]['properties']
        existing_evidence=[]
        for m,f in zip(row['matches'],matches):
            props=f['properties']
            existing_evidence.append({**m,'name':next((props[k] for k in ('name','Trail_Name','TRAIL_NAME','Loc_Name','Name') if props.get(k)), m['name']),
                'provenance':{k:props[k] for k in ('pipeline_id','source_url','source_feature_id','Blaze','BlazeColor','SrcDt','GPSDate','MAINT_BY','MapMeth','HAcrcy') if props.get(k)}})
        rows.append({**row,'category':category,'recommendation':action,'recommendation_title':title,'explanation':reason,
                     'options':options,'matches':existing_evidence,'peers':peers,'official_at_coverage':official_coverage,
                     'official_at_ids':['official-at:'+str(official['features'][i]['id']) for i in found],
                     'source_attributes':{k:p.get(k) for k in ('trail_no','trail_cn','globalid','admin_org','bmp','emp','hiker_pedestrian_managed','hiker_pedestrian_accpt','hiker_pedestrian_accpt_disc','hiker_pedestrian_disc','hiker_pedestrian_restricted')}})
    source_evidence=read_json(ROOT/'pipelines/usfs-gwj/source-preferences.json')
    result={'schema_version':1,'created_at':now(),'kind':'tnc-usfs-source-exceptions','accepted_review_hash':report['review_hash'],
            'acceptance_hash':digest(receipt),'incoming_hash':fingerprint(incoming),'existing_hash':fingerprint(existing),
            'official_at_hash':digest(official),'source_preferences_hash':digest(source_evidence),
            'accepted_count':receipt['accepted_count'],'published':False,'rows':rows,'sources':source_evidence,
            'summary':dict(Counter(r['category'] for r in rows)),'rejected':report['rejected'],'notices':report['notices'],
            'actions':ACTIONS,'limitations':['These are source preferences, not approved replacement geometry or deletion plans.',
                'Service refresh timestamps are not per-segment survey dates. Most regional NPS/ATC records cite older GPS surveys.',
                'Coverage buffers can flag crossings and parallel trails; no automatic trimming or deletion is performed.',
                'The 967 accepted additions are immutable context for this round. Existing Rivanna geometry remains protected.']}
    result['review_hash']=digest(result)
    write_json(output/'exceptions.json',result)
    # Compact display properties; full immutable source properties remain in the original review.
    display=[]
    for f in incoming['features']:
        display.append({**f,'properties':{'review_id':f['id'],'name':f['properties']['name'],'accepted':f['id'] in accepted_ids,
                                         'map_color':f['properties'].get('map_color','#8a6250')}})
    for f in existing['features']:f['properties']['review_id']=f['id']
    refs=[{'type':'Feature','id':'official-at:'+str(f['id']),'geometry':f['geometry'],
           'properties':{'review_id':'official-at:'+str(f['id']),'name':f['properties'].get('Name'),'Source':f['properties'].get('Source'),
                         'Edit_Date':f['properties'].get('Edit_Date'),'GPS_Date':f['properties'].get('GPS_Date')}} for i,f in enumerate(official['features']) if i in used_official]
    for filename,features in [('incoming.geojson',display),('existing.geojson',existing['features']),('official-at.geojson',refs)]:
        (output/filename).write_text(json.dumps({'type':'FeatureCollection','features':features},separators=(',',':'))+'\n')
    shutil.copy(root/'preview.json',output/'preview.json')
    shutil.copy(root/'inventory/style.json',output/'style.json')
    for filename in ('index.html','review.js','review.css'):shutil.copy(ROOT/'maintenance/trail_exceptions_ui'/filename,output/filename)
    return result


def confirmed_decisions(directory, report):
    path=directory/'confirmed-decisions.json'
    if not path.exists(): return None
    value=read_json(path)
    if digest({k:v for k,v in value.items() if k!='decision_hash'}) != value.get('decision_hash'):
        raise ValueError('Confirmed source decision changed')
    if value.get('review_hash') != report['review_hash'] or value.get('acceptance_hash') != report['acceptance_hash']:
        raise ValueError('Confirmed source decision belongs to another review')
    rows={r['id']:r for r in report['rows']}
    if any(fid not in rows or action not in rows[fid]['options'] for fid,action in value.get('decisions',{}).items()):
        raise ValueError('Confirmed source decision contains an unsupported action')
    return value


def confirmed_access(directory, report):
    path=directory/'access-decisions.json'
    if not path.exists():return None
    value=read_json(path)
    if digest({k:v for k,v in value.items() if k!='decision_hash'})!=value.get('decision_hash'):
        raise ValueError('Confirmed access decisions changed')
    if value.get('review_hash')!=report['review_hash'] or value.get('acceptance_hash')!=report['acceptance_hash']:
        raise ValueError('Confirmed access decisions belong to another review')
    expected={r['id'] for r in report['rows'] if r['category']=='access'}
    if len(value['rows'])!=len(expected) or {r['id'] for r in value['rows']}!=expected or any(r['action'] not in {'approve','reject','hold'} for r in value['rows']):
        raise ValueError('Confirmed access decisions do not match the access batch')
    return value


def import_preferences(directory, input_path, output):
    report=read_json(directory/'exceptions.json');value=read_json(input_path)
    if digest({k:v for k,v in report.items() if k!='review_hash'}) != report['review_hash']:
        raise ValueError('Exception report changed')
    if value.get('kind') != report['kind'] or value.get('review_hash') != report['review_hash'] or value.get('acceptance_hash') != report['acceptance_hash']:
        raise ValueError('Preferences do not match the reviewed exceptions and accepted batch')
    expected={r['id']:r for r in report['rows'] if r['options']}
    decisions=value.get('decisions',{})
    if set(decisions)!=set(expected): raise ValueError('Expected one preference for every unresolved record')
    if any(action not in expected[fid]['options']+['pending'] for fid,action in decisions.items()):
        raise ValueError('Unsupported source preference; access holds cannot become trail approvals')
    confirmed=confirmed_decisions(directory,report)
    if confirmed:
        if value.get('confirmed_hash') != confirmed['decision_hash']:
            raise ValueError('Export predates the confirmed source choices')
        if any(decisions.get(fid)!=action for fid,action in confirmed['decisions'].items()):
            raise ValueError('Export cannot change source choices already confirmed by the user')
    access=confirmed_access(directory,report)
    if access:
        if value.get('access_hash')!=access['decision_hash']:
            raise ValueError('Export predates the confirmed access decisions')
        if any(decisions.get(r['id'])!='hold' for r in access['rows']):
            raise ValueError('Source-choice export cannot alter separately approved access decisions')
    result={**value,'status':'source-preferences-only','review_only':True,
            'next_step':'Prepare exact bounded replacements and retained continuations before approving any geometry edits.'}
    write_json(output,result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('root',type=Path);b.add_argument('--research',type=Path,required=True);b.add_argument('--output',type=Path,required=True)
    i=sub.add_parser('import');i.add_argument('directory',type=Path);i.add_argument('input',type=Path);i.add_argument('--output',type=Path,required=True)
    a=parser.parse_args()
    if a.command=='build':print(build(a.root,a.research,a.output)['summary'])
    else:print(import_preferences(a.directory,a.input,a.output)['status'])


if __name__=='__main__':main()
