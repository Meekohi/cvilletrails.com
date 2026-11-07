"""Apply the user's access and short-connector policy to the frozen exception batch."""
import argparse
import json
import re
from pathlib import Path
from .common import ROOT,digest,now,read_json,write_json
from .geo import canonical,fingerprint
from .overlaps import geometry_tools
from .trail_exceptions import verify_acceptance


def meaningful(value):
    return str(value or '').strip().upper() not in {'','N/A','NA','NONE','UNKNOWN','NULL','NO','FALSE'}


def contrary_reason(feature, rules):
    p=feature['properties'];name=p.get('name',p.get('trail_name',''))
    if meaningful(p.get('hiker_pedestrian_restricted')):return 'Explicit hiking restriction in source attributes'
    if meaningful(p.get('hiker_pedestrian_disc')):return 'Source explicitly discourages hiking'
    if re.search(r'\b(DECO|DECOMMISSIONED|CLOSED|ABANDONED)\b',name,re.I):return 'Source name indicates decommissioning, closure or abandonment'
    for rule in rules['holds']:
        if re.search(rule['name_pattern'],name,re.I):return rule['reason']
    return None


def short_connectivity(short_features, useful_features, tolerance=10):
    """Evaluate connected short components, so tiny stubs cannot justify each other.

    Keep a component that joins two useful records, or two separated positions
    on one useful line (a shortcut). All contacts and distances remain reviewable.
    """
    from shapely.geometry import Point
    from shapely.ops import nearest_points
    project,union,Tree=geometry_tools()
    short=[project(f['geometry']) for f in short_features]
    useful=[project(f['geometry']) for f in useful_features]
    tree=Tree(short);other_tree=Tree(useful);parent=list(range(len(short)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,g in enumerate(short):
        for j in tree.query(g.buffer(tolerance)):
            j=int(j)
            if g.distance(short[j])<=tolerance:parent[find(j)]=find(i)
    groups={}
    for i in range(len(short)):groups.setdefault(find(i),[]).append(i)
    result={}
    for indices in groups.values():
        contacts=[];anchors={}
        for i in indices:
            g=short[i];parts=[g] if g.geom_type=='LineString' else list(g.geoms)
            for part in parts:
                for xy in (part.coords[0],part.coords[-1]):
                    point=Point(xy)
                    for j in other_tree.query(point.buffer(tolerance)):
                        j=int(j);distance=point.distance(useful[j])
                        if distance>tolerance:continue
                        ref=useful_features[j];contact=nearest_points(point,useful[j])[1]
                        anchors.setdefault(ref['id'],[]).append(contact)
                        contacts.append({'short_id':short_features[i]['id'],'reference_id':ref['id'],
                            'reference_name':ref['properties'].get('name') or ref['properties'].get('Name') or 'Existing trail',
                            'distance_m':round(distance,2)})
        shortcut=any(a.distance(b)>2*tolerance for points in anchors.values() for a in points for b in points)
        useful_connection=len(anchors)>=2 or shortcut
        evidence={'component_ids':[short_features[i]['id'] for i in indices], 'useful_connection':useful_connection,
                  'reference_count':len(anchors),'contacts':contacts,'tolerance_m':tolerance}
        for i in indices:result[short_features[i]['id']]=evidence
    return result


def resolve(root, output):
    original,incoming,receipt=verify_acceptance(root)
    exception=read_json(root/'exceptions/exceptions.json')
    if exception['incoming_hash']!=fingerprint(incoming):raise ValueError('Exception inputs changed')
    policy=read_json(ROOT/'pipelines/usfs-gwj/access-policy.json')
    rules=read_json(ROOT/'pipelines/usfs-gwj/review-rules.json')
    project,_,_=geometry_tools()
    by_id={f['id']:f for f in incoming['features']}
    access=[r for r in exception['rows'] if r['category']=='access']
    rejected_names=set(policy['reject_names'])
    preliminary={}
    for row in access:
        f=by_id[row['id']]
        if row['name'] in rejected_names:action,reason='reject',policy['reject_names'][row['name']]
        elif reason:=contrary_reason(f,rules):action='hold'
        else:action,reason='approve','No contrary access evidence; approved under the user’s open-unless-contrary policy'
        preliminary[row['id']]={'action':action,'reason':reason}
    short=[by_id[r['id']] for r in access if preliminary[r['id']]['action']=='approve' and r['length_m']<policy['minimum_standalone_miles']*1609.344]
    short_ids={f['id'] for f in short}
    useful=[]
    for f in incoming['features']:
        if f['id'] in short_ids or f['properties']['name'] in rejected_names or contrary_reason(f,rules):continue
        if project(f['geometry']).length >= policy['minimum_standalone_miles']*1609.344:
            useful.append(f)
    # Existing custom trails are useful context, not roads from the basemap.
    for dataset in read_json(root/'inventory/datasets.json'):
        for f in read_json(root/'inventory/datasets'/(dataset['id']+'.geojson'))['features']:
            if f['geometry']['type'] in {'LineString','MultiLineString'}:
                useful.append({**f,'id':dataset['id']+'/'+f['id']})
    connectivity=short_connectivity(short,useful,policy['connection_tolerance_m'])
    rows=[];approved=[];append=[];replacement=[]
    for row in access:
        fid=row['id'];decision=preliminary[fid];connection=connectivity.get(fid)
        if connection and not connection['useful_connection']:
            decision={'action':'reject','reason':'Under 0.1 mile; its short-segment component does not connect two useful trail records or form a substantial shortcut'}
        elif connection:
            decision={'action':'approve','reason':'Under 0.1 mile but connects useful trail geometry; preserve the connector'}
        kind=None
        if decision['action']=='approve':
            approved.append(by_id[fid])
            # These are accepted as source replacements, never appended over the
            # existing Tuscarora layer. Other proximity flags remain explicit.
            kind='source-replacement' if row['name'].startswith('TUSCARORA') and row['coverage']['20']>=.8 else 'addition'
            (replacement if kind=='source-replacement' else append).append(by_id[fid])
        rows.append({'id':fid,'name':row['name'],'length_m':row['length_m'],**decision,'geometry_use':kind,
                     'connectivity':connection,'existing_coverage':row['coverage'],'incoming_match_ids':[p['id'] for p in row['peers']]})
    from collections import Counter
    report={'schema_version':1,'kind':'tnc-usfs-access-decisions','recorded_at':now(),'review_hash':exception['review_hash'],
            'acceptance_hash':exception['acceptance_hash'],'incoming_hash':fingerprint(incoming),'policy_hash':digest(policy),
            'method':'explicit-user-policy-in-chat-with-connectivity-analysis','user_statement':policy['user_statement'],
            'scope':'The 168 access-hold records in this exception round; previous 967 accepted additions remain unchanged.',
            'counts':dict(Counter(r['action'] for r in rows)),'addition_count':len(append),'source_replacement_count':len(replacement),
            'rows':rows,'published':False,'limitations':['Connections use a 10 m tolerance, not a guarantee of trail conditions.',
            'Access approval is separate from source replacement; Tuscarora overlaps must not be appended over existing lines.',
            'Source geometry, explicit restrictions and current forest orders still require review on future changes.']}
    report['decision_hash']=digest(report)
    write_json(output/'access-decisions.json',report)
    for filename,features in [('approved-access.geojson',approved),('access-additions.geojson',append),('access-replacements.geojson',replacement)]:
        data=canonical({'type':'FeatureCollection','features':features});data['ingest_report']={'review_only':True,'access_decision_hash':report['decision_hash'],'reason':'User-approved access selection; combine with the exact reviewed publication plans'};write_json(output/filename,data)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(resolve(a.root,a.output)['counts'])


if __name__=='__main__':main()
