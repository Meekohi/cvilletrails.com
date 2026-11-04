"""Normalize DCR park trails conservatively and prepare a statewide review queue."""
import argparse
import copy
import re
import shutil
from collections import Counter
from pathlib import Path
from uuid import UUID

from .common import ROOT, configs, digest, now, read_json, write_json
from .geo import canonical, validate_collection

USE_CODES = {'H','B','E','HB','HE','HBE'}
UNKNOWN_COLORS = {'','none','n/a','not marked'}


def clean(value):
    return ' '.join(str(value or '').split())


def global_id(feature):
    try: return str(UUID(clean(feature['properties'].get('GlobalID'))))
    except (ValueError, AttributeError): raise ValueError('DCR feature has no valid stable GlobalID') from None


def hold_reasons(feature, override=None):
    p=feature['properties'];override=override or {}
    reasons=[]
    name=clean(p.get('Trail_Name'))
    if not clean(p.get('LABEL')): reasons.append('missing park')
    if not name: reasons.append('missing trail name')
    if re.search(r'propos|rerout|future|staff|maintenance',name,re.I): reasons.append('proposed/reroute or staff name')
    if re.search(r'\b(closed|abandoned|decommissioned)\b|under construction',name,re.I): reasons.append('closed or abandoned trail name')
    if clean(p.get('Status')).lower()!='open': reasons.append('not explicitly open in GIS')
    use=clean(override.get('trail_use',p.get('Trail_User')))
    if use not in USE_CODES: reasons.append('staff, water or ambiguous trail use')
    if clean(p.get('Surfacing')).lower()=='water': reasons.append('water route')
    if clean(p.get('outside_park')).lower()!='no': reasons.append('outside park or unknown boundary status')
    if clean(p.get('Restrictions')).lower() not in {'no','none','n/a'}: reasons.append('unknown or special restrictions')
    if (feature.get('geometry') or {}).get('type') not in {'LineString','MultiLineString'}: reasons.append('missing or unsupported line geometry')
    return reasons


def normalize_trails(collection,config,source_id):
    if collection.get('type')!='FeatureCollection' or collection.get('crs'): raise ValueError('Expected WGS84 source collection')
    source=next(s for s in config['sources'] if s['id']==source_id)
    overrides=read_json(config['_directory']/'overrides.json')
    seen=set();included=[];held=[];unreviewed=Counter();used_overrides=set()
    for original in collection['features']:
        gid=global_id(original)
        if gid in seen: raise ValueError('Duplicate DCR GlobalID')
        seen.add(gid)
        p=original['properties'];park=clean(p.get('LABEL'));policy=config['approved_parks'].get(park)
        if not policy: unreviewed[park or '(unassigned)']+=1;continue
        if policy['system_id'] not in config['system_ids']:raise ValueError('Approved park has no registered system audience')
        override=overrides.get(gid,{}).get('properties',{})
        reasons=hold_reasons(original,override)
        if gid in config.get('held_features',{}): reasons.append(config['held_features'][gid])
        if reasons:
            held.append({'global_id':gid,'name':clean(p.get('Trail_Name')),'park':park,'reasons':reasons});continue
        if gid in overrides:used_overrides.add(gid)
        color=clean(p.get('BlazeColor')).lower()
        if color in UNKNOWN_COLORS:color='none'
        palette=policy.get('palette',config.get('palette',{}))
        if color not in palette:raise ValueError(f'Unreviewed blaze color for {park}: {color}')
        f=copy.deepcopy(original);f['id']='va-state-parks:'+gid
        f['properties'].update({'name':clean(p['Trail_Name']),'color':color,'display_color':palette[color],
            'system_id':policy['system_id'],'pipeline_id':'virginia-state-parks','source_id':source_id,
            'source_feature_id':gid,'source_url':source['url'],'trail_use':clean(p.get('Trail_User')),
            'difficulty':clean(p.get('Difficulty')),'attribution':'Virginia Department of Conservation and Recreation'})
        f['properties'].update(override)
        included.append(f)
    if set(overrides)-used_overrides:raise ValueError('Reviewed DCR override disappeared or is no longer eligible; investigate before importing')
    if set(config.get('held_features',{}))-seen:raise ValueError('Explicitly held DCR feature disappeared; review the source change')
    result=canonical({'type':'FeatureCollection','features':included})
    result['ingest_report']={'source_features':len(collection['features']),'included':len(included),'held':held,
        'unreviewed_parks':dict(sorted(unreviewed.items())),'policy_hash':digest({k:v for k,v in config.items() if k!='_directory'}),'overrides_hash':digest(overrides)}
    return result


def coordinate_pairs(value):
    if isinstance(value,list) and len(value)>=2 and isinstance(value[0],(int,float)):yield value[:2]
    elif isinstance(value,list):
        for part in value:yield from coordinate_pairs(part)


def bounds(features):
    points=[p for f in features for p in coordinate_pairs((f.get('geometry') or {}).get('coordinates',[]))]
    if not points:return None
    return [min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)]


def queue(collection, registry, config):
    groups={};overrides=read_json(config['_directory']/'overrides.json')
    for original in collection['features']:
        park=clean(original['properties'].get('LABEL')) or '(unassigned)'
        groups.setdefault(park,[]).append(original)
    parks=[];features=[]
    for name,group in sorted(groups.items()):
        policy=config['approved_parks'].get(name);rows=[]
        for original in group:
            gid=global_id(original);reasons=hold_reasons(original,overrides.get(gid,{}).get('properties',{}));p=original['properties']
            if gid in config.get('held_features',{}): reasons.append(config['held_features'][gid])
            rows.append({'global_id':gid,'name':clean(p.get('Trail_Name')),'status':p.get('Status'),'uses':p.get('Trail_User'),'blaze':p.get('BlazeColor'),'hold_reasons':reasons})
            if (original.get('geometry') or {}).get('type') in {'LineString','MultiLineString'}:
                f=copy.deepcopy(original);f['id']='va-state-parks:'+gid
                f['properties'].update({'review_park':name,'review_held':bool(reasons),'review_reason':'; '.join(reasons),'name':clean(p.get('Trail_Name'))})
                features.append(f)
        parks.append({'name':name,'bounds':bounds(group),'total':len(group),'eligible':sum(not r['hold_reasons'] for r in rows),
            'held':sum(bool(r['hold_reasons']) for r in rows),'status':'pilot' if policy else 'needs-review',
            'sources':registry.get(name,{}),'trails':rows})
    report={'schema_version':1,'created_at':now(),'source_hash':digest(collection),'parks':parks,
            'notice':'Eligibility is a screening result, not approval. Check current operator alerts, map colors, off-site access and duplicates before preparing a publication plan.'}
    report['review_hash']=digest(report)
    return report,{'type':'FeatureCollection','features':features}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('--registry',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();config=configs('virginia-state-parks')[0]
    report,features=queue(read_json(args.source),read_json(args.registry),config)
    write_json(args.output/'review.json',report);write_json(args.output/'trails.geojson',features)
    token=re.search(r"mapboxgl.accessToken = '(pk\.[^']+)'",(ROOT/'assets/app.js').read_text())[1]
    write_json(args.output/'preview.json',{'public_token':token,'style':'mapbox://styles/meekohi/ckkolybrr6tjx17mjqflqw16b'})
    shutil.copy(ROOT/'maintenance/state_parks_preview.html',args.output/'index.html')
    print(f"Prepared {len(report['parks'])} groups for review")


if __name__=='__main__':main()
