"""Minimal color and legacy-route style changes for the reviewed release."""
import copy
from .common import digest,read_json


def transform(style):
    result=copy.deepcopy(style)
    layer=next(l for l in result['layers'] if l['id']=='strava-trail')
    if layer.get('source-layer')!='Strava_Sidetrails':raise ValueError('Supplemental style target changed')
    if 'legacy-patc' in str(layer['paint']['line-color']):raise ValueError('Release style already applied')
    layer['paint']['line-color']=['case',['in',['get','pipeline_id'],['literal',['tnc-virginia','usfs-gwj','legacy-patc']]],
        ['coalesce',['get','map_color'],'#8a6250'],layer['paint']['line-color']]
    excluded=['all',['==',['get','TRAIL_NAME'],'Tuscarora Trail'],
        ['==',['get','Loc_Name'],'Tuscarora Trail (outside park boundary)'],['==',['get','GPSDate'],'12/21/2019']]
    found=[]
    for layer in result['layers']:
        if layer.get('source-layer')=='shen-08a9vs':
            prior=layer.get('filter');layer['filter']=['all',prior,['!',excluded]] if prior else ['!',excluded]
            found.append(layer['id'])
    if set(found)!={'shenandoah-np fringe','shenandoah-np-trail'}:raise ValueError('Legacy route layer mapping changed')
    return result


def prepare(plan,style):
    proposed=transform(style)
    manifest={'kind':'tnc-usfs-release-style','dataset_plan_hash':plan['approval_hash'],
              'before_style_hash':digest(style),'after_style_hash':digest(proposed),
              'changed_layers':['strava-trail','shenandoah-np fringe','shenandoah-np-trail'],
              'reason':'Show approved TNC map colors, neutral USFS lines, verified Tuscarora blue; replace only the captured outside-park PATC route while retaining its full unaffected remainder.'}
    manifest['proposal_hash']=digest(manifest)
    return manifest,proposed


def main():
    import argparse
    from pathlib import Path
    from .common import load_env,write_json,STATE
    from .mapbox import Mapbox,verify_written
    from .reviewed_style import publish_style
    p=argparse.ArgumentParser();p.add_argument('release',type=Path);p.add_argument('--publish',action='store_true');a=p.parse_args()
    load_env();client=Mapbox();plan=read_json(a.release/'supplemental-plan.json')
    if not a.publish:
        live=client.call(f'styles/v1/{client.username}/{client.style_id}',params={'optimize':'false'})[0]
        manifest,proposed=prepare(plan,live)
        write_json(a.release/'style-manifest.json',manifest);write_json(a.release/'style-proposed.json',proposed)
        print(manifest['proposal_hash']);return
    at=read_json(a.release/'at-plan.json');receipt=read_json(STATE/'publishes'/(at['approval_hash']+'.json'))
    if receipt['state']!='published':raise ValueError('AT publication is not complete')
    verify_written(at,client.features(at['target']['dataset']))
    capture=read_json(a.release/'patc/capture.json')
    if digest(client.tileset(capture['tileset']))!=capture['metadata_hash']:raise ValueError('Legacy PATC source changed during publication')
    protected='cjawyutol0r7d2wo1z7eb0wiy'
    from .geo import fingerprint
    if fingerprint(client.features(protected))!=fingerprint(read_json(a.release/'inventory/datasets'/(protected+'.geojson'))):raise ValueError('Protected Rivanna dataset changed')
    manifest=read_json(a.release/'style-manifest.json');proposed=read_json(a.release/'style-proposed.json')
    result=publish_style(client,plan,manifest,proposed,manifest['proposal_hash'],prepare=prepare,transform=transform,journal_prefix='tnc-usfs-style')
    print(result['state'])


if __name__=='__main__':main()
