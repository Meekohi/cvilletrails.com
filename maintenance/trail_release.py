"""Reconcile the confirmed TNC/USFS decisions into complete publication candidates."""
import copy
import heapq
import json
from pathlib import Path
from .common import read_json, write_json, digest
from .geo import canonical, fingerprint
from .overlaps import geometry_tools
from .trail_exceptions import verify_acceptance, confirmed_access, confirmed_decisions


def parts(g):
    if g.is_empty:return []
    if g.geom_type=='LineString':return [g] if g.length>.001 else []
    if g.geom_type not in {'MultiLineString','GeometryCollection'}:return []
    return [p for child in g.geoms for p in parts(child)]


def line_geometry(lines):
    from shapely.geometry import MultiLineString
    return lines[0] if len(lines)==1 else MultiLineString(lines)


def replace_route(old, replacements):
    """Find the old route between source endpoints; retain every other old part.

    Short connections bridge tile quantization seams in the routing graph only.
    Retained line endpoints join the selected source at explicit, logged anchors.
    """
    from shapely.geometry import Point,LineString
    from shapely.ops import substring
    lines=parts(old);cuts={i:{0.,g.length} for i,g in enumerate(lines)};anchors=[]
    for fid,new in replacements:
        if new.geom_type!='LineString':raise ValueError('Tuscarora replacement must be a line')
        pair=[]
        for coordinate in (new.coords[0],new.coords[-1]):
            point=Point(coordinate);i=min(range(len(lines)),key=lambda j:lines[j].distance(point))
            measure=lines[i].project(point);distance=lines[i].distance(point)
            if distance>40:raise ValueError('Replacement endpoint too far from old route')
            cuts[i].add(measure);pair.append((i,measure,point,distance))
        anchors.append((fid,new,pair))
    graph={};positions={}
    def edge(a,b,length,interval):
        graph.setdefault(a,[]).append((b,length,interval));graph.setdefault(b,[]).append((a,length,interval))
    for i,g in enumerate(lines):
        measures=sorted(cuts[i])
        for m in measures:positions[(i,m)]=g.interpolate(m)
        for a,b in zip(measures,measures[1:]):edge((i,a),(i,b),b-a,(i,a,b))
    ends=[(i,m) for i,g in enumerate(lines) for m in (0.,g.length)]
    for a in range(len(ends)):
        for b in range(a+1,len(ends)):
            u,v=ends[a],ends[b]
            if u[0]==v[0]:continue
            d=positions[u].distance(positions[v])
            if d<=10:edge(u,v,d,None)
    removed={i:[] for i in range(len(lines))};joins={};audit=[]
    for fid,new,pair in anchors:
        start=pair[0][:2];end=pair[1][:2];queue=[(0.,start)];dist={start:0.};previous={}
        while queue:
            cost,node=heapq.heappop(queue)
            if cost!=dist[node]:continue
            if node==end:break
            for other,length,interval in graph[node]:
                value=cost+length
                if value<dist.get(other,float('inf')):
                    dist[other]=value;previous[other]=(node,interval);heapq.heappush(queue,(value,other))
        if end not in dist:raise ValueError('Disconnected old route at '+fid)
        node=end;path=[]
        while node!=start:
            prior,interval=previous[node]
            if interval:path.append(interval)
            node=prior
        path_lines=[substring(lines[i],a,b) for i,a,b in path]
        from shapely.ops import unary_union
        route=unary_union(path_lines);agreement=route.intersection(new.buffer(50)).length/max(route.length,1)
        if not .7<dist[end]/new.length<1.3 or agreement<.8:raise ValueError('Old/new route mismatch at '+fid)
        for i,a,b in path:removed[i].append((a,b))
        for i,m,point,distance in pair:joins[(i,m)]=point
        audit.append({'id':fid,'old_length_m':dist[end],'new_length_m':new.length,'old_within_50m':agreement,
                      'endpoint_join_distances_m':[round(p[3],3) for p in pair],'old_intervals':path})
    retained=[]
    for i,g in enumerate(lines):
        intervals=sorted(removed[i]);merged=[]
        for a,b in intervals:
            if merged and a<=merged[-1][1]+.000001:merged[-1][1]=max(b,merged[-1][1])
            else:merged.append([a,b])
        cursor=0.
        for a,b in merged+[[g.length,g.length]]:
            if a-cursor>.001:
                piece=substring(g,cursor,a);coords=list(piece.coords)
                if (i,cursor) in joins:coords[0]=tuple(joins[(i,cursor)].coords[0])
                if (i,a) in joins:coords[-1]=tuple(joins[(i,a)].coords[0])
                retained.append(LineString(coords))
            cursor=b
    return line_geometry(retained),audit


def retain_distinct(line,references,tolerance,minimum_shared=40):
    """Remove substantive shared runs; preserve crossings and reconnect cut ends."""
    from shapely.geometry import Point,LineString
    from shapely.ops import unary_union,nearest_points
    if not references:return line,{'removed_m':0,'joins':[]}
    ref=unary_union(references);mask=ref.buffer(tolerance)
    overlap=parts(line.intersection(mask))
    runs=[p for p in overlap if p.length>=minimum_shared or p.length>=line.length*.95]
    if not runs:return line,{'removed_m':0,'joins':[]}
    # Subtract only confirmed continuous shared runs, not every nearby crossing.
    from shapely.ops import substring
    remaining=[];joins=[];removed=0.
    for original in parts(line):
        intervals=[]
        for run in runs:
            a=original.project(Point(run.coords[0]));b=original.project(Point(run.coords[-1]))
            if abs(a-b)>.001 and original.distance(run)<.001:intervals.append(sorted((a,b)))
        intervals.sort();merged=[]
        for a,b in intervals:
            if merged and a<=merged[-1][1]+.001:merged[-1][1]=max(b,merged[-1][1])
            else:merged.append([a,b])
        cursor=0.
        for a,b in merged+[[original.length,original.length]]:
            if a-cursor>.01:
                piece=substring(original,cursor,a);coords=list(piece.coords)
                for index,is_cut in [(0,cursor>0),(-1,a<original.length)]:
                    if is_cut:
                        endpoint=Point(coords[index]);nearest=nearest_points(endpoint,ref)[1]
                        distance=endpoint.distance(nearest)
                        if distance>tolerance+.01:raise ValueError('Cut endpoint escaped connection tolerance')
                        coords[index]=tuple(nearest.coords[0]);joins.append(round(distance,3))
                remaining.append(LineString(coords))
            removed+=b-a;cursor=b
    return line_geometry(remaining),{'removed_m':round(removed,3),'joins':joins}


def prepare(root,release):
    from shapely.geometry import mapping
    from shapely.ops import transform
    from pyproj import Transformer
    _,incoming,_=verify_acceptance(root)
    report=read_json(root/'exceptions/exceptions.json');sources=confirmed_decisions(root/'exceptions',report);access=confirmed_access(root/'exceptions',report)
    by_id={f['id']:f for f in incoming['features']};rows={r['id']:r for r in report['rows']}
    project,union,Tree=geometry_tools();inverse=Transformer.from_crs(32617,4326,always_xy=True).transform
    def geo(g):return json.loads(json.dumps(mapping(transform(inverse,g))))
    base=read_json(release/'inventory/datasets/cjd3c6ua70tt52wqjqzmjg4ls.geojson')
    additions=read_json(root/'accepted/combined-additions.geojson')['features']
    if len(additions)!=1104:raise ValueError('Accepted additions changed')
    result=copy.deepcopy(additions);audit=[]
    tuscarora=[by_id[fid] for fid,action in sources['decisions'].items() if action=='incoming']+read_json(root/'access-accepted/access-replacements.geojson')['features']
    captured=read_json(release/'patc/captured.geojson')['features'][0]
    retained,route_audit=replace_route(project(captured['geometry']),[(f['id'],project(f['geometry'])) for f in tuscarora])
    retained_feature=copy.deepcopy(captured);retained_feature['geometry']=geo(retained)
    retained_feature['properties']['system_id']='tuscarora-trail';result.append(retained_feature)
    for original in tuscarora:
        f=copy.deepcopy(original);f['properties'].update(map_color='hsl(211, 59%, 77%)',color='blue',color_source='PATC 2019 survey; retained existing rendered blue')
        result.append(f)
    existing={f['id']:f for f in base['features']}
    at=read_json(root/'at/candidate.geojson')['features'];at_geoms=[project(f['geometry']) for f in at];at_tree=Tree(at_geoms)
    old_refs={f['id']:f for f in read_json(root/'existing-overlaps.geojson')['features']}
    # Long records first so route aliases can reference an already retained line.
    pending=sorted([(rows[fid],action) for fid,action in sources['decisions'].items() if action in {'split','shared'}],key=lambda x:-x[0]['length_m'])
    for row,action in pending:
        fid=row['id'];f=copy.deepcopy(by_id[fid]);line=project(f['geometry']);refs=[];ref_ids=[];tolerance=3;minimum=40
        if row['category']=='state-parks':
            for m in row['matches']:
                ref=old_refs[m['id']]
                if ref['properties'].get('pipeline_id')=='virginia-state-parks':refs.append(project(ref['geometry']));ref_ids.append(m['id'])
            tolerance=20
        elif row['category']=='at-junctions':
            found=[int(i) for i in at_tree.query(line.buffer(20))];refs=[at_geoms[i] for i in found];ref_ids=[at[i]['id'] for i in found];tolerance=20
        else:
            related={p['id'] for p in row['peers']}
            for ref in result:
                if ref['id'] in related or (row['category']=='patc' and (ref['id'].startswith('legacy-patc:') or ref['properties'].get('name','').startswith('TUSCARORA'))):
                    g=project(ref['geometry'])
                    if line.distance(g)<=20:refs.append(g);ref_ids.append(ref['id'])
            if row['category']=='patc':tolerance=20
        geometry,detail=retain_distinct(line,refs,tolerance,minimum)
        if detail['removed_m']:
            # Keep alternate route identities on the physical representation.
            # Existing DCR/AT data remains immutable; its membership is recorded
            # in the release evidence instead.
            for ref in result:
                if ref['id'] not in ref_ids:continue
                shared=line.intersection(project(ref['geometry']).buffer(tolerance)).length
                if shared>=minimum or shared>=line.length*.95:
                    p=ref['properties']
                    p['shared_route_names']=sorted(set(p.get('shared_route_names',[])+[row['name']]))
                    p['shared_source_ids']=sorted(set(p.get('shared_source_ids',[])+[fid]))
        f['properties'].update(shared_route_ids=ref_ids,source_reconciliation=action)
        audit.append({'id':fid,'name':row['name'],'category':row['category'],'before_m':round(line.length,3),'after_m':round(geometry.length,3),'references':ref_ids,**detail})
        if not geometry.is_empty:
            f['geometry']=geo(geometry) if detail['removed_m'] else f['geometry'];result.append(f)
    candidate=canonical({'type':'FeatureCollection','features':base['features']+result})
    forbidden={r['id'] for r in access['rows'] if r['action']!='approve'}|{fid for fid,action in sources['decisions'].items() if action in {'existing','official-at'}}
    if forbidden & {f['id'] for f in result}:raise ValueError('Rejected/held/alternate feature entered release')
    if any(f!=existing[f['id']] for f in candidate['features'] if f['id'] in existing):raise ValueError('Existing supplemental geometry changed')
    from .mapbox import target_by_id
    candidate['ingest_report']={'reviewed_before_hash':fingerprint(base),'reviewed_target':target_by_id('strava'),'source_decision_hash':sources['decision_hash'],'access_decision_hash':access['decision_hash'],'publication_authorization':'User: Go ahead and publish.','preserved_existing':len(base['features']),'accepted_additions':len(additions),'source_reconciliation':audit,'tuscarora_replacements':route_audit}
    write_json(release/'supplemental-candidate.geojson',candidate)
    write_json(release/'merge-evidence.json',{'shared_routes':audit,'tuscarora':route_audit,'retained_patc_m':retained.length,'new_feature_count':len(result),'candidate_hash':fingerprint(candidate),'source_decision_hash':sources['decision_hash'],'access_decision_hash':access['decision_hash']})
    return candidate


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('release',type=Path);a=p.parse_args()
    print(len(prepare(a.root,a.release)['features']))
