"""Recover one legacy uploaded route without modifying its tileset or other routes."""
import argparse
import gzip
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .common import read_json, write_json, request, RequestError, digest


def tilexy(lon,lat,z):
    n=2**z
    return int((lon+180)/360*n),int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)


def capture(output,token,metadata):
    import mapbox_vector_tile
    from shapely.geometry import shape,box,mapping
    from shapely.ops import transform,unary_union,linemerge
    tid='meekohi.8n5896es';layer='shen-08a9vs'
    def selected(p):
        return p.get('TRAIL_NAME')=='Tuscarora Trail' and p.get('Loc_Name')=='Tuscarora Trail (outside park boundary)' and p.get('GPSDate')=='12/21/2019'
    def fetch(key):
        z,x,y=key;p=output/'tiles'/str(z)/str(x)/(str(y)+'.pbf')
        if p.exists():data=p.read_bytes()
        else:
            try:data=request(f'https://api.mapbox.com/v4/{tid}/{z}/{x}/{y}.vector.pbf?access_token={token}')[0]
            except RequestError as e:
                if e.status!=404:raise
                data=b''
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        if data.startswith(b'\x1f\x8b'):data=gzip.decompress(data)
        decoded=mapbox_vector_tile.decode(data).get(layer) if data else None
        if not decoded:return []
        extent=decoded['extent'];n=2**z
        result=[]
        for f in decoded['features']:
            if not selected(f['properties']):continue
            # Work in global integer tile coordinates to avoid seam rounding.
            g=transform(lambda px,py,z=None:(x*extent+px,(y+1)*extent-py),shape(f['geometry']))
            g=g.intersection(box(x*extent,y*extent,(x+1)*extent,(y+1)*extent))
            if g.is_empty or g.geom_type not in {'LineString','MultiLineString'}:continue
            result.append((g,f['properties'],extent))
        return result
    w,s,e,n=metadata['bounds'];x0,y0=tilexy(w,n,12);x1,y1=tilexy(e,s,12)
    coarse=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for records in pool.map(fetch,[(12,x,y) for x in range(x0,x1+1) for y in range(y0,y1+1)]):coarse.extend(records)
    if not coarse:raise ValueError('Legacy Tuscarora route not found')
    wanted=set()
    for g,p,extent in coarse:
        g=transform(lambda x,y,z=None:(x*16/extent,y*16/extent),g).buffer(.25)
        a,b,c,d=g.bounds
        for x in range(math.floor(a),math.floor(c)+1):
            for y in range(math.floor(b),math.floor(d)+1):
                if g.intersects(box(x,y,x+1,y+1)):wanted.add((16,x,y))
    print(f'Capturing {len(wanted)} high-resolution legacy route tiles',flush=True)
    detailed=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for records in pool.map(fetch,sorted(wanted)):detailed.extend(records)
    if not detailed:raise ValueError('No high-resolution route geometry')
    if {r[2] for r in detailed}!={4096}:raise ValueError('Unexpected legacy tile extent')
    geometry=unary_union([g for g,p,e in detailed])
    if geometry.geom_type=='MultiLineString':geometry=linemerge(geometry)
    scale=2**16*4096
    geometry=transform(lambda x,y,z=None:(x/scale*360-180,math.degrees(math.atan(math.sinh(math.pi*(1-2*y/scale))))),geometry)
    import json
    feature={'type':'Feature','id':'legacy-patc:tuscarora-outside-2019','geometry':json.loads(json.dumps(mapping(geometry))),
             'properties':{**detailed[0][1],'pipeline_id':'legacy-patc','name':'Tuscarora Trail','system_id':'usfs-gwj','map_color':'hsl(211, 59%, 77%)','source_tileset':tid,'capture_zoom':16}}
    result={'type':'FeatureCollection','features':[feature]}
    write_json(output/'captured.geojson',result)
    write_json(output/'capture.json',{'tileset':tid,'metadata_hash':digest(metadata),'zoom':16,'tile_count':len(wanted),'geometry_hash':digest(result),'filter':{'TRAIL_NAME':'Tuscarora Trail','Loc_Name':'Tuscarora Trail (outside park boundary)','GPSDate':'12/21/2019'},'method':'Locate entire route at z12; capture z16 corridor with 1/4 tile margin; clip tile buffers in global integer coordinates, union and merge. Other source features remain in original tileset unchanged.'})
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('review',type=Path);a=p.parse_args()
    capture(a.output,read_json(a.review/'preview.json')['public_token'],read_json(a.review/'inventory/tilesets.json')['meekohi.8n5896es'])
