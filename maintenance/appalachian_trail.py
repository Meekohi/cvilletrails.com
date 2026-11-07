"""Official NPS/ATC centerline adapter and bounded, review-only AT replacement."""
import argparse
import copy
import json
import shutil
import uuid
from pathlib import Path
from .common import ROOT, digest, read_json, write_json
from .geo import canonical, fingerprint, validate_collection

PIPELINE = ROOT/'pipelines/appalachian-trail'


def transform(collection, config, source_id):
    if source_id != 'official-centerline': raise ValueError('Only the official centerline supplies AT geometry')
    source=next(s for s in config['sources'] if s['id']==source_id)
    features=[]; held=[]; rejected=[]; seen=set()
    for original in collection['features']:
        props=copy.deepcopy(original['properties'])
        try:sid=str(uuid.UUID(props['GlobalID'].strip('{}')))
        except (KeyError,ValueError,AttributeError):raise ValueError('Official AT record needs a stable GlobalID') from None
        if sid in seen:raise ValueError('Duplicate official AT GlobalID')
        seen.add(sid)
        fid='nps-atc:'+sid
        if props.get('Status')!='Official A.T. Route':
            held.append({'id':fid,'reason':'Not explicitly the official AT centerline','status':props.get('Status')});continue
        props.update(name='Appalachian Trail',Name='Appalachian Trail',color='white',pipeline_id=config['id'],
                     system_id=config['system_id'],source_id=source_id,source_feature_id=sid,source_url=source['url'],
                     attribution='National Park Service / Appalachian Trail Conservancy')
        feature={'type':'Feature','id':fid,'geometry':original['geometry'],'properties':props}
        try:
            validate_collection({'type':'FeatureCollection','features':[feature]})
            if feature['geometry']['type'] not in {'LineString','MultiLineString'}:raise ValueError('Expected centerline geometry')
        except ValueError as e:
            rejected.append({'id':fid,'reason':str(e)});continue
        features.append(feature)
    result=canonical({'type':'FeatureCollection','features':features})
    result['ingest_report']={'review_only':True,'source_count':len(collection['features']),'held':held,'rejected':rejected,
                             'reason':'Official source selected by user; prepare bounded full-dataset replacement before publication'}
    return result


def prepare(baseline, source, output, scope=None):
    from shapely.geometry import box, shape, mapping
    from .overlaps import geometry_tools, coverage
    scope=scope or read_json(PIPELINE/'scope.json')
    if digest(baseline)!=scope['baseline_hash']:raise ValueError('Existing AT dataset changed; refresh the bounded comparison')
    if source.get('ingest_report',{}).get('held') or source.get('ingest_report',{}).get('rejected'):
        raise ValueError('Official centerline contains held or invalid records; resolve them before full replacement')
    clip=box(*scope['bounds']);features=[];clipped=[];excluded=[]
    def lines(g):
        if g.is_empty:return []
        if g.geom_type=='LineString':return [g] if g.length else []
        if g.geom_type not in {'MultiLineString','GeometryCollection'}:return []
        return [p for child in g.geoms for p in lines(child)]
    for f in source['features']:
        g=shape(f['geometry']);parts=lines(g.intersection(clip))
        if not parts:excluded.append(f['id']);continue
        from shapely.geometry import MultiLineString
        trimmed=parts[0] if len(parts)==1 else MultiLineString(parts)
        feature=copy.deepcopy(f)
        feature['geometry']=json.loads(json.dumps(mapping(trimmed)))
        feature['properties']['scope_clipped']=not g.equals(trimmed)
        if feature['properties']['scope_clipped']:clipped.append(f['id'])
        features.append(feature)
    candidate=canonical({'type':'FeatureCollection','features':features})
    if not features:raise ValueError('No official centerline inside the existing map coverage')
    project,union,Tree=geometry_tools()
    new_geometries=[project(f['geometry']) for f in features];tree=Tree(new_geometries)
    rows=[];total=0;covered=0
    for f in baseline['features']:
        line=project(f['geometry']);total+=line.length
        nearby=[new_geometries[int(i)] for i in tree.query(line.buffer(100))]
        # Union local buffers, not one statewide buffered network.
        fractions={str(d):round(line.intersection(union([g.buffer(d) for g in nearby])).length/max(line.length,1),4) for d in (10,20,100)}
        covered+=fractions['100']*line.length
        rows.append({'id':f['id'],'length_m':round(line.length,2),'coverage':fractions,'bounds':list(shape(f['geometry']).bounds),
                     'attention':fractions['100']<.95})
    old_length=total;new_length=sum(g.length for g in new_geometries)
    candidate['ingest_report']={'review_only':True,'reason':'Bounded AT source replacement comparison; endpoint cuts and alignment changes require inclusion in the publication plan',
                               'reviewed_before_hash':fingerprint(baseline),'preferred_source':'NPS / ATC','scope_hash':digest(scope)}
    report={'schema_version':1,'status':'source-approved-replacement-prepared','published':False,'source_selection':read_json(PIPELINE/'reviews/2026-11-07-source-selection.json')['decision_hash'],
            'before_hash':fingerprint(baseline),'after_hash':fingerprint(candidate),'source_hash':fingerprint(source),'scope':scope,
            'before_count':len(baseline['features']),'after_count':len(features),'before_miles':old_length/1609.344,'after_miles':new_length/1609.344,
            'old_coverage_within_100m':covered/max(total,1),'clipped_ids':clipped,'out_of_scope_ids':excluded,'rows':rows,
            'limitations':['Clipping uses the actual old geometry extent, not stale dataset metadata.',
                          'Clipped terminal records are explicit; no straight-line extensions or GPS traces were invented.',
                          'Differences can be old survey error or realignment; the reference does not prove when a physical trail moved.',
                          'The existing white AT layer styling is retained; no other datasets are changed.']}
    report['comparison_hash']=digest(report)
    write_json(output/'candidate.geojson',candidate);write_json(output/'before.geojson',baseline);write_json(output/'comparison.json',report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('source',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--preview-context',type=Path);a=p.parse_args()
    r=prepare(read_json(a.baseline),read_json(a.source),a.output)
    if a.preview_context:
        style=read_json(a.preview_context/'style.json')
        style['layers']=[layer for layer in style['layers'] if layer['id'] not in {'appalachian-trail','appalachian-trail fringe'}]
        write_json(a.output/'style.json',style)
        shutil.copy(a.preview_context/'preview.json',a.output/'preview.json')
        for filename in ('index.html','review.js','review.css'):
            shutil.copy(ROOT/'maintenance/appalachian_trail_ui'/filename,a.output/filename)
    print({k:r[k] for k in ('before_count','after_count','before_miles','after_miles','old_coverage_within_100m')})


if __name__=='__main__':main()
