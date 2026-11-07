"""Prepare an addition-only TNC/USFS review; never write to Mapbox."""
import argparse
import copy
import gzip
import math
import json
import re
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .common import ROOT, digest, now, read_json, request, write_json
from .geo import canonical, fingerprint
from .overlaps import geometry_tools, coverage


def fc(features): return canonical({'type':'FeatureCollection', 'features':features})


def tile_references(inventory, incoming, output, token, force=False):
    """Read visible custom tiles without editable datasets, around candidate lines.

    z12 at this latitude resolves about 2m per vector coordinate. Tile clipping
    seams are retained, and duplicate fragments are harmless in a union.
    """
    import mapbox_vector_tile
    from shapely.geometry import box, mapping, shape
    from shapely.ops import transform
    datasets = read_json(inventory/'datasets.json')
    tilesets = read_json(inventory/'tilesets.json')
    style = read_json(inventory/'style.json')
    references, report = [], []
    zoom = 12; n = 2**zoom
    def tilexy(lon, lat):
        return int((lon+180)/360*n), int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)
    def lonlat(x, y): return x/n*360-180, math.degrees(math.atan(math.sinh(math.pi*(1-2*y/n))))
    for tid, metadata in tilesets.items():
        if any(tid.split('.',1)[1].startswith(d['id']+'-') for d in datasets): continue
        layers = {l['id'] for l in metadata['vector_layers']}
        visible = {l['source-layer'] for l in style['layers'] if l.get('source-layer') in layers and l['type']=='line' and l.get('layout',{}).get('visibility')!='none'}
        if not visible: continue
        bounds = box(*metadata['bounds']); wanted = set()
        for f in incoming['features']:
            g = shape(f['geometry']).buffer(.0005).intersection(bounds)
            if g.is_empty: continue
            west,south,east,north=g.bounds; x0,y0=tilexy(west,north); x1,y1=tilexy(east,south)
            for x in range(x0,x1+1):
                for y in range(y0,y1+1):
                    w,s=lonlat(x,y+1);e,no=lonlat(x+1,y)
                    if g.intersects(box(w,s,e,no)): wanted.add((x,y))
        def fetch_tile(xy):
            x,y=xy; path=output/'reference-tiles'/tid/str(metadata.get('modified', digest(metadata)))/str(zoom)/str(x)/(str(y)+'.pbf')
            if path.exists() and not force: data=path.read_bytes()
            else:
                from .common import RequestError
                try: data=request(f'https://api.mapbox.com/v4/{tid}/{zoom}/{x}/{y}.vector.pbf?access_token={token}')[0]
                except RequestError as error:
                    if error.status != 404: raise
                    data=b''
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            if data.startswith(b'\x1f\x8b'): data = gzip.decompress(data)
            result=[]
            for layer, decoded in (mapbox_vector_tile.decode(data).items() if data else []):
                if layer not in visible: continue
                extent=decoded['extent']
                def convert(px,py,z=None):return lonlat(x+px/extent,y+1-py/extent)
                for i,f in enumerate(decoded['features']):
                    if f['geometry']['type'] not in {'LineString','MultiLineString'}:continue
                    geometry=mapping(transform(convert,shape(f['geometry'])))
                    result.append({'type':'Feature','id':f'{tid}/{zoom}/{x}/{y}/{layer}/{i}',
                                   'geometry':geometry,'properties':{**f['properties'],'reference_source':tid,'reference_layer':layer}})
            return result
        with ThreadPoolExecutor(max_workers=6) as pool:
            for features in pool.map(fetch_tile, sorted(wanted)):references.extend(features)
        report.append({'tileset':tid,'zoom':zoom,'tiles':len(wanted),'layers':sorted(visible),'metadata_hash':digest(metadata)})
    # Convert tuples emitted by Shapely to GeoJSON lists.
    result = fc(json.loads(json.dumps(references)))
    write_json(output/'tile-references.geojson',result);write_json(output/'tile-reference-report.json',report)
    return result, report


def references(inventory, extra):
    """Retain every existing line as a conservative duplicate reference."""
    features=[]; sources=[]
    for dataset in read_json(inventory/'datasets.json'):
        data=read_json(inventory/'datasets'/(dataset['id']+'.geojson'))
        sources.append({'id':dataset['id'],'name':dataset['name'],'hash':fingerprint(data),'features':len(data['features'])})
        for f in data['features']:
            if f['geometry']['type'] not in {'LineString','MultiLineString'}:continue
            features.append({**f,'id':dataset['id']+'/'+str(f['id']), 'properties':{**f['properties'],'reference_source':dataset['name']}})
    return fc(features+extra['features']),sources


def screen(incoming, existing, access_holds, rules):
    from shapely.geometry import shape
    project, union, Tree=geometry_tools()
    old=[project(f['geometry']) for f in existing['features']]; tree=Tree(old)
    new=[project(f['geometry']) for f in incoming['features']]; newtree=Tree(new)
    rows=[]
    for i,f in enumerate(incoming['features']):
        line=new[i]; matches=[]; nearby=[]
        for index in tree.query(line.buffer(30)):
            g=old[index]; overlap=line.intersection(g.buffer(20)).length
            if line.length <= 0 or (overlap < 30 and overlap/line.length < .8):continue
            other=existing['features'][index];nearby.append(g)
            matches.append({'id':other['id'],'name':next((other['properties'][k] for k in ('name','Name','NAME','TrailName') if other['properties'].get(k)), 'Unnamed'),
                            'source':other['properties']['reference_source'],'coverage_20m':round(overlap/line.length,4)})
        cov=coverage(line,union(nearby),(3,10,20,30)) if nearby else {str(d):0 for d in (3,10,20,30)}
        conflicts=[]
        for index in newtree.query(line.buffer(20)):
            if index==i:continue
            other=incoming['features'][index]
            if f['properties']['pipeline_id'] == other['properties']['pipeline_id'] == 'tnc-virginia' and f['properties']['source_id'] == other['properties']['source_id']:
                continue  # Independently selected paths in one reviewed official map.
            # Shared trail junctions do not warrant holds. Significant same-line
            # segments are held together; no order-dependent silent winner.
            overlap=line.intersection(new[index].buffer(20)).length
            reverse=overlap/max(new[index].length,1)
            if line.length > 0 and ((overlap >= 60 and (overlap/line.length >= .2 or reverse >= .8))
                    or (overlap/line.length >= .8 and reverse >= .8)):
                conflicts.append(other['id'])
        reason=access_holds.get(f['id']); status='access-hold' if reason else 'proposed'
        if not reason and (line.length<=0 or not line.is_valid):status='geometry-hold';reason='Invalid or zero-length geometry'
        if not reason and f['properties'].get('pipeline_id')=='usfs-gwj':
            for rule in rules['holds']:
                if re.search(rule['name_pattern'],f['properties']['name'],re.I):
                    status='access-hold';reason=rule['reason'];break
        if not reason and cov['20']>=.8:status='duplicate';reason='Existing map already covers at least 80% within 20 m; retain existing geometry and colors'
        elif not reason and (cov['20']>=.15 or cov['20']*line.length>=150):status='overlap-hold';reason='Partial overlap with existing map; retain whole source record for review, without trimming'
        if not reason and conflicts:status='incoming-overlap';reason='Overlaps another incoming source segment; choose a source before including'
        rows.append({'id':f['id'],'name':f['properties']['name'],'pipeline':f['properties']['pipeline_id'],
                     'group':f['properties']['source_id'] if f['properties']['pipeline_id']=='tnc-virginia' else f['properties']['admin_org'],
                     'status':status,'reason':reason or 'Hiking source verified; no substantial overlap found',
                     'length_m':round(line.length,1),'bounds':list(shape(f['geometry']).bounds),'coverage':cov,
                     'matches':sorted(matches,key=lambda x:x['coverage_20m'],reverse=True),'incoming_matches':sorted(conflicts),
                     'source_url':f['properties']['source_url'], 'color':f['properties'].get('color')})
    return rows


def proposals(incoming, style):
    """Prepare catalog/style additions for later publication, without changing live files."""
    from .site import validate_systems
    metadata = {
        'warm-springs-mountain': ('Warm Springs Mountain Preserve', 'Bath County',
            'Bear Loop near Ingalls Field, Ingalls Overlook off Route 39, and Sandy Gap are mapped from official TNC trail maps. Check approach-road conditions before visiting.',
            'https://www.nature.org/en-us/get-involved/how-to-help/places-we-protect/warm-springs-mountain/'),
        'bottom-creek-gorge': ('Bottom Creek Gorge Preserve', 'Montgomery County',
            'TNC walking trails reach the gorge overlook. Open dawn to dusk; dogs and fishing are not permitted.',
            'https://www.nature.org/en-us/get-involved/how-to-help/places-we-protect/bottom-creek-gorge/'),
        'cumberland-marsh': ('Vandell Preserve at Cumberland Marsh', 'New Kent County',
            'TNC hiking trails and marsh viewing areas. Open dawn to dusk; dogs are not permitted.',
            'https://www.nature.org/en-us/get-involved/how-to-help/places-we-protect/vandell-preserve-at-cumberland-marsh/'),
        'usfs-gwj': ('George Washington and Jefferson National Forests', 'Virginia and neighboring forest lands',
            'Forest Service trail geometry with recorded hiking management. Check current forest alerts and orders; GIS management dates do not establish current opening status.',
            'https://www.fs.usda.gov/r08/gwj/alerts')}
    from shapely.geometry import shape
    systems = []
    for sid,(name,area,description,url) in metadata.items():
        boxes = [shape(f['geometry']).bounds for f in incoming['features'] if f['properties']['system_id']==sid]
        systems.append({'id':sid,'name':name,'area':area,'description':description,
            'bounds':[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)],
            'source_layers':['Strava_Sidetrails'],'url':url,'source_label':'US Forest Service' if sid=='usfs-gwj' else 'The Nature Conservancy',
            'context_mode':'trail','context_min_zoom':14,'info_reviewed_on':'2026-11-07',
            'info_sources':[{'id':'visitor-guide','label':'Official visitor guidance','url':url}], 'description_sources':['visitor-guide']})
    existing=read_json(ROOT/'data/systems.json')
    if set(s['id'] for s in existing) & set(metadata): raise ValueError('System catalog already includes these additions; reconcile before rebuilding')
    validate_systems(existing+systems)
    proposed=copy.deepcopy(style)
    layers=[l for l in proposed['layers'] if l['id']=='strava-trail' and l.get('source-layer')=='Strava_Sidetrails']
    if len(layers)!=1:raise ValueError('Supplemental trail style changed')
    paint=layers[0]['paint']
    paint['line-color']=['case',['in',['get','pipeline_id'],['literal',['tnc-virginia','usfs-gwj']]],
                         ['coalesce',['get','map_color'],'#8a6250'],paint['line-color']]
    return systems,proposed


def build(root, inventory, refresh_tiles=False):
    tnc,usfs=read_json(root/'tnc.geojson'),read_json(root/'usfs.geojson')
    incoming=fc(tnc['features']+usfs['features'])
    token=re.search(r"mapboxgl.accessToken = '(pk\.[^']+)'",(ROOT/'assets/app.js').read_text())[1]
    scope={'incoming_hash':fingerprint(incoming),'tilesets_hash':digest(read_json(inventory/'tilesets.json')),
           'style_hash':digest(read_json(inventory/'style.json'))}
    scope_path=root/'tile-reference-scope.json'
    if refresh_tiles or not scope_path.exists() or read_json(scope_path)!=scope:
        extra,tile_report=tile_references(inventory,incoming,root,token,force=refresh_tiles)
        write_json(scope_path,scope)
    else:extra,tile_report=read_json(root/'tile-references.geojson'),read_json(root/'tile-reference-report.json')
    existing,sources=references(inventory,extra)
    access={r['id']:r['reason'] for r in usfs['ingest_report']['held']}
    rules=read_json(ROOT/'pipelines/usfs-gwj/review-rules.json')
    rows=screen(incoming,existing,access,rules)
    resolutions=read_json(ROOT/'pipelines/tnc-virginia/resolutions.json')
    by_id={f['id']:f for f in incoming['features']}
    by_row={r['id']:r for r in rows}
    for resolution in resolutions:
        for fid, expected in resolution['feature_hashes'].items():
            if fid not in by_id or digest(by_id[fid]) != expected:
                raise ValueError('Resolved source geometry changed; review source preference again')
        for fid in resolution['prefer']:
            row=by_row[fid]
            if row['status'] in {'proposed','incoming-overlap'}:
                row.update(status='proposed',reason=resolution['reason'])
        for fid in resolution['hold']:
            row=by_row[fid]
            if row['status'] in {'proposed','incoming-overlap'}:
                row.update(status='alternate-source',reason=resolution['reason'])
    accepted={r['id'] for r in rows if r['status']=='proposed'}
    additions=fc([f for f in incoming['features'] if f['id'] in accepted])
    additions['ingest_report']={'review_only':True,'reason':'Awaiting final review; additions only'}
    report={'schema_version':1,'created_at':now(),'incoming_hash':fingerprint(incoming),'existing_hash':fingerprint(existing),
            'inventory_sources':sources,'style_hash':digest(read_json(inventory/'style.json')),
            'tile_references':tile_report,'rules_hash':digest(rules),'resolutions_hash':digest(resolutions),'summary':dict(Counter(r['status'] for r in rows)),
            'rejected':usfs['ingest_report']['rejected'],'rows':rows,'notices':rules['notices'],
            'method':'All 13 editable datasets plus z12 custom Shenandoah tile fragments near candidate lines. Length coverage at 3/10/20/30 m. Crossings under 30 m excluded. No existing geometry, colors or Rivanna records changed. Parallel nearby trails can trigger conservative holds.',
            'limitations':['PDF control residual measures transform fit, not ground accuracy.','USFS has no blaze colors: neutral brown is a display choice.','Access records are not current opening guarantees; forest orders override them.','Basemap paths are background context, not editable custom trail records.']}
    systems,style_proposal=proposals(incoming,read_json(inventory/'style.json'))
    report['systems_proposal_hash']=digest(systems);report['style_proposal_hash']=digest(style_proposal)
    report['review_hash']=digest(report)
    write_json(root/'systems-proposal.json',systems);write_json(root/'style-proposal.json',style_proposal)
    write_json(root/'review.json',report);write_json(root/'incoming.geojson',incoming);write_json(root/'additions.geojson',additions)
    preview_features=[{**f,'properties':{k:v for k,v in f['properties'].items() if k in
        {'name','color','map_color','source_map_date','pipeline_id','system_id','source_id','source_url'}}} for f in incoming['features']]
    (root/'preview-trails.geojson').write_text(json.dumps(fc(preview_features),separators=(',',':'))+'\n')
    matched={m['id'] for r in rows for m in r['matches']}
    write_json(root/'existing-overlaps.geojson',fc([f for f in existing['features'] if f['id'] in matched]))
    write_json(root/'preview.json',{'public_token':token,'style':'mapbox://styles/meekohi/ckkolybrr6tjx17mjqflqw16b'})
    for filename in ('index.html','review.js','review.css'):
        shutil.copy(ROOT/'maintenance/trail_expansion_ui'/filename,root/filename)
    return report


def feedback(root, feedback_path, output):
    report=read_json(root/'review.json');incoming=read_json(root/'incoming.geojson');value=read_json(feedback_path)
    if value.get('review_hash')!=report['review_hash'] or fingerprint(incoming)!=report['incoming_hash']:
        raise ValueError('Feedback does not match the exact reviewed inputs')
    unhashed={k:v for k,v in report.items() if k!='review_hash'}
    if digest(unhashed)!=report['review_hash']:raise ValueError('Review report changed')
    rows={r['id']:r for r in report['rows']};decisions=value.get('decisions',{})
    if set(decisions)!=set(rows) or any(v not in {'include','exclude','hold'} for v in decisions.values()):
        raise ValueError('Feedback must contain a valid decision for every record')
    selected={fid for fid,decision in decisions.items() if decision=='include'}
    for fid in selected:
        if rows[fid]['status']!='proposed':
            raise ValueError('Held/duplicate records need a separately reviewed resolution; feedback alone cannot override them')
    result=fc([f for f in incoming['features'] if f['id'] in selected])
    result['ingest_report']={'review_only':True,'review_hash':report['review_hash'], 'feedback_hash':digest(value),
                             'reason':'Reviewed selection only; fresh inventory and explicit publication plan still required'}
    write_json(output,result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    b=s.add_parser('build');b.add_argument('root',type=Path);b.add_argument('--inventory',type=Path,required=True);b.add_argument('--refresh-tiles',action='store_true')
    f=s.add_parser('feedback');f.add_argument('root',type=Path);f.add_argument('feedback',type=Path);f.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.command=='build':print(build(a.root,a.inventory,a.refresh_tiles)['summary'])
    else:print('Selected segments:',len(feedback(a.root,a.feedback,a.output)['features']))


if __name__=='__main__':main()
