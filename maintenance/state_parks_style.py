"""Apply reviewed DCR colors without changing other supplemental trail styling."""
import argparse
import copy
from pathlib import Path
from .common import ROOT, configs, digest, load_env, read_json, write_json
from .geo import canonical, changes
from .mapbox import Mapbox, validate_plan
from .reviewed_style import publish_style


def color_style(style):
    result=copy.deepcopy(style)
    layers=[l for l in result['layers'] if l['id']=='strava-trail']
    if len(layers)!=1 or layers[0].get('source-layer')!='Strava_Sidetrails':raise ValueError('Supplemental trail layer changed')
    paint=layers[0]['paint'];old=paint['line-color']
    condition=['==',['get','pipeline_id'],'virginia-state-parks']
    palette=['coalesce',['get','display_color'],'#ded0c5']
    if isinstance(old,list) and old[:2]==['case',condition]:
        if old[2]!=palette:raise ValueError('Existing DCR styling differs; review before changing')
        return result
    paint['line-color']=['case',condition,palette,old]
    return result


def prepare(plan,style):
    validate_plan(plan,plan['approval_hash']);diff=changes(plan['before'],plan['after'])
    if plan['target']['id']!='strava' or diff['changed'] or diff['deleted']:raise ValueError('Initial DCR publication must only add reviewed Lake Anna features')
    expected=read_json(ROOT/'pipelines/virginia-state-parks/data/lake-anna.geojson')
    actual={'type':'FeatureCollection','features':[f for f in plan['after']['features'] if f['id'] in diff['added']]}
    if canonical(expected)!=canonical(actual):raise ValueError('Plan additions differ from reviewed Lake Anna geometry/properties')
    config=configs('virginia-state-parks')[0];policy={k:v for k,v in config.items() if k!='_directory'}
    proposed=color_style(style)
    manifest={'dataset_plan_hash':plan['approval_hash'],'before_hash':plan['before_hash'],'after_hash':plan['after_hash'],
        'style_before_hash':digest(style),'style_after_hash':digest(proposed),'policy_hash':digest(policy),
        'overrides_hash':digest(read_json(config['_directory']/'overrides.json')),'approved_features_hash':digest(canonical(expected))}
    manifest['proposal_hash']=digest(manifest)
    return manifest,proposed


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('plan',type=Path);p.add_argument('style',type=Path);p.add_argument('--output',required=True,type=Path)
    p=sub.add_parser('publish');p.add_argument('plan',type=Path);p.add_argument('proposal',type=Path);p.add_argument('--approve',required=True)
    args=parser.parse_args()
    if args.command=='prepare':
        manifest,style=prepare(read_json(args.plan),read_json(args.style));write_json(args.output/'manifest.json',manifest);write_json(args.output/'style-proposal.json',style);print(manifest)
    else:
        load_env();print(publish_style(Mapbox(),read_json(args.plan),read_json(args.proposal/'manifest.json'),read_json(args.proposal/'style-proposal.json'),args.approve,prepare=prepare,transform=color_style,journal_prefix='state-parks-style'))


if __name__=='__main__':main()
