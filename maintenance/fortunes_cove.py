"""Extract the reviewed TNC GeoPDF and publish its narrowly scoped trail colors."""
import argparse
import copy
import hashlib
import re
import shutil
from pathlib import Path

from .common import ROOT, STATE, configs, digest, load_env, now, read_json, write_json
from .geo import canonical, changes, fingerprint
from .ingest import run_adapter
from .mapbox import Mapbox, validate_plan, verify_written
from .styles import editable_style

PIPELINE = ROOT / 'pipelines/fortunes-cove'


def extract(pdf, manifest):
    # Optional dependencies are isolated from ordinary source checks and site builds.
    import numpy as np
    import pymupdf
    from pypdf import PdfReader
    from pyproj import CRS, Transformer, Geod

    if hashlib.sha256(Path(pdf).read_bytes()).hexdigest() != manifest['pdf_sha256']:
        raise ValueError('PDF changed: review georeferencing and semantic path assignments first')
    reader = PdfReader(pdf)
    page = reader.pages[manifest['page']]
    viewports = [v.get_object() for v in page['/VP'] if v.get_object()['/Name'] == manifest['viewport_name']]
    if len(viewports) != 1 or page.get('/Rotate', 0) != 0:
        raise ValueError('Unexpected PDF viewport or rotation')
    viewport = viewports[0]
    measure = viewport['/Measure']
    crs = CRS.from_wkt(str(measure['/GCS']['/WKT']))
    if crs.to_epsg() != manifest['expected_crs_epsg']:
        raise ValueError('Unexpected PDF coordinate reference system')
    local = np.array(measure['/LPTS'], dtype=float).reshape(-1, 2)
    geographic = np.array(measure['/GPTS'], dtype=float).reshape(-1, 2)
    if local.shape != (4, 2) or geographic.shape != (4, 2):
        raise ValueError('Expected four reviewed viewport control points')
    to_grid = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
    east, north = to_grid.transform(geographic[:, 1], geographic[:, 0])
    grid = np.column_stack([east, north])
    design = np.column_stack([local, np.ones(4)])
    affine, _, rank, _ = np.linalg.lstsq(design, grid, rcond=None)
    residual = np.linalg.norm(design @ affine - grid, axis=1)
    if rank != 3 or max(residual) > manifest['max_control_residual_m']:
        raise ValueError('PDF control points do not support the reviewed affine transform')
    to_wgs = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
    document = pymupdf.open(pdf)
    drawing_page = document[manifest['page']]
    x0, y_top, x1, y_bottom = map(float, viewport['/BBox'])
    # This ArcMap PDF has an inverted-y BBox: LPTS (0,0) is its north-west corner.
    top = drawing_page.rect.height - y_top
    bottom = drawing_page.rect.height - y_bottom
    if not (x0 < x1 and top < bottom):
        raise ValueError('Unexpected viewport orientation')

    def coordinate(point):
        uv = [(point.x - x0) / (x1 - x0), (point.y - top) / (bottom - top)]
        if not all(0 <= v <= 1 for v in uv):
            raise ValueError('Trail path outside the georeferenced map viewport')
        xy = np.array([*uv, 1]) @ affine
        return [round(v, 8) for v in to_wgs.transform(*xy)]

    drawings = drawing_page.get_drawings()
    selected = {item['drawing'] for item in manifest['paths']}
    colors = {'yellow': (1, 0.88235, 0.3098), 'white': (1, 1, 1)}
    actual = {i for i, d in enumerate(drawings) if d.get('layer') == manifest['vector_layer']
              and d.get('color') and any(max(abs(a-b) for a,b in zip(d['color'], c)) < 0.0001 for c in colors.values())}
    if actual != selected:
        raise ValueError('Colored trail path membership differs from the reviewed manifest')
    raw, lengths = [], {}
    geod = Geod(ellps='WGS84')
    for item in manifest['paths']:
        drawing = drawings[item['drawing']]
        if len(drawing['items']) != item['segments'] or max(abs(a-b) for a,b in zip(drawing['color'], colors[item['color']])) > .0001:
            raise ValueError('Reviewed path shape/color changed')
        points = []
        for segment in drawing['items']:
            if segment[0] != 'l' or (points and segment[1] != points[-1]):
                raise ValueError('Expected a continuous polyline; no implicit jumps or curve tracing')
            if not points: points.append(segment[1])
            points.append(segment[2])
        coords = [coordinate(p) for p in points]
        props = {'name': item['name'], 'color': item['color'], 'source_map_date': '2020-06',
                 'geometry_method': 'official-geopdf-vector-extraction', 'source_sha256': manifest['pdf_sha256']}
        raw.append({'type': 'Feature', 'id': item['id'], 'properties': props,
                    'geometry': {'type': 'LineString', 'coordinates': coords}})
        lengths[item['id']] = round(geod.line_length(*zip(*coords)), 2)
    result = run_adapter({'type':'FeatureCollection', 'features':raw}, configs('fortunes-cove')[0], 'trail-map')
    coordinates = [c for f in result['features'] for c in f['geometry']['coordinates']]
    bounds = [min(c[0] for c in coordinates), min(c[1] for c in coordinates),
              max(c[0] for c in coordinates), max(c[1] for c in coordinates)]
    pin = manifest['operator_map_pin']
    nearest = min(abs(geod.inv(*pin, *c)[2]) for c in coordinates)
    if nearest > 150:
        raise ValueError('Extracted trails do not align with the operator’s parking map pin')
    report = {'pdf_sha256': manifest['pdf_sha256'], 'manifest_hash': digest(manifest),
              'crs':crs.to_string(), 'control_residual_m':residual.tolist(),
              'bounds':bounds, 'lengths_m':lengths, 'nearest_vertex_to_operator_pin_m':round(nearest, 2),
              'feature_count':len(result['features']), 'geometry_hash':fingerprint(result),
              'limitations':['Cartographic 2020 linework, not surveyed GPS precision.',
                             'No roads, boundary dashes, legend/profile strokes or black casings imported.',
                             'Parking-area gaps in colored paths are retained; no private-road access inferred.']}
    return result, report


def color_style(style):
    """Only these source-tagged features get the official yellow/white palette."""
    result = copy.deepcopy(style)
    layers = [l for l in result['layers'] if l['id'] == 'strava-trail']
    if len(layers) != 1 or layers[0].get('source-layer') != 'Strava_Sidetrails':
        raise ValueError('Supplemental trail layer changed')
    paint = layers[0]['paint']
    old = paint['line-color']
    condition = ['==', ['get', 'system_id'], 'fortunes-cove']
    palette = ['match', ['get', 'color'], 'yellow', '#ffe14f', 'white', '#ffffff', '#ded0c5']
    if isinstance(old, list) and old[:2] == ['case', condition]:
        if old[2] != palette: raise ValueError('Existing Fortune’s Cove palette differs; review before changing')
        return result
    paint['line-color'] = ['case', condition, palette, old]
    return result


def prepare_style(plan, style):
    validate_plan(plan, plan['approval_hash'])
    diff = changes(plan['before'], plan['after'])
    if plan['target']['id'] != 'strava' or diff['changed'] or diff['deleted']:
        raise ValueError('First Fortune’s Cove publication must only add to the supplemental dataset')
    added = [f for f in plan['after']['features'] if f['id'] in diff['added']]
    expected = {'fortunes-cove:'+p['id'] for p in read_json(PIPELINE/'extraction.json')['paths']}
    if {f['id'] for f in added} != expected or any(f['properties'].get('system_id') != 'fortunes-cove' for f in added):
        raise ValueError('Plan additions differ from the reviewed Fortune’s Cove paths')
    proposed = color_style(style)
    manifest = {'dataset_plan_hash':plan['approval_hash'], 'before_hash':plan['before_hash'],
                'after_hash':plan['after_hash'], 'style_before_hash':digest(style),
                'style_after_hash':digest(proposed), 'extraction_manifest_hash':digest(read_json(PIPELINE/'extraction.json'))}
    manifest['proposal_hash'] = digest(manifest)
    return manifest, proposed


def publish_style(client, plan, manifest, proposed, approval, state_dir=STATE):
    if digest({k:v for k,v in manifest.items() if k != 'proposal_hash'}) != approval or manifest['proposal_hash'] != approval:
        raise ValueError('Approval does not match exact style proposal')
    target = validate_plan(plan, plan['approval_hash'])
    endpoint = f'styles/v1/{client.username}/{client.style_id}'
    live = client.call(endpoint, params={'optimize':'false'})[0]
    expected_manifest, expected_style = prepare_style(plan, live)
    if expected_manifest != manifest or expected_style != proposed:
        raise ValueError('Style, plan or extraction policy changed since review')
    receipt = read_json(state_dir/'publishes'/f"{plan['approval_hash']}.json")
    if receipt.get('state') != 'published' or receipt.get('target') != target:
        raise ValueError('Dataset publication must complete before style changes')
    verification = verify_written(plan, client.features(target['dataset']))
    if verification['stored_hash'] != receipt['verification']['stored_hash']:
        raise ValueError('Dataset differs from its publication receipt')
    path = state_dir/'publishes'/f'fortunes-cove-style-{approval}.json'
    if path.exists(): raise ValueError('Style write already attempted; inspect journal before retrying')
    draft = client.call(endpoint+'/draft', params={'optimize':'false'})[0]
    draft_after = color_style(draft)
    backup = state_dir/'backups'/f'fortunes-cove-style-{approval}'
    for name, value in [('published',live),('draft',draft),('published-proposed',proposed),('draft-proposed',draft_after)]:
        write_json(backup/f'{name}.json',value)
    journal = {'state':'prepared','started_at':now(),'proposal_hash':approval,
               'dataset_plan_hash':plan['approval_hash'],'completed':[], 'dataset_verification':verification}
    write_json(path,journal)
    for name,before,after,url in [('draft',draft,draft_after,endpoint+'/draft'),('published',live,proposed,endpoint)]:
        if digest(client.call(url,params={'optimize':'false'})[0]) != digest(before):
            raise ValueError('Style changed immediately before write; inspect journal')
        journal['state']='updating-'+name;write_json(path,journal)
        response=client.call(url,'PATCH',editable_style(after))[0]
        write_json(backup/f'{name}-response.json',response)
        if editable_style(response) != editable_style(after): raise ValueError('Style response differs from proposal')
        journal['completed'].append({'version':name,'response_hash':digest(response)});write_json(path,journal)
    journal.update(state='published',finished_at=now());write_json(path,journal)
    return journal



def build_preview(plan_path, style_path, extraction_dir, pdf, output):
    plan, style = read_json(plan_path), read_json(style_path)
    manifest, proposed = prepare_style(plan, style)
    trails = read_json(extraction_dir/'trails.geojson')
    expected = [f for f in plan['after']['features'] if f['id'] in plan['changes']['added']]
    if canonical({'type':'FeatureCollection','features':expected}) != canonical(trails):
        raise ValueError('Preview geometry differs from dataset plan')
    report = read_json(extraction_dir/'extraction-report.json')
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != report['pdf_sha256']:
        raise ValueError('Preview PDF differs from extracted source')
    bounds = report['bounds']
    token = re.search(r"mapboxgl.accessToken = '(pk\.[^']+)'", (ROOT/'assets/app.js').read_text())[1]
    write_json(output/'manifest.json', manifest)
    write_json(output/'style-proposal.json', proposed)
    write_json(output/'trails.geojson', trails)
    write_json(output/'preview.json', {'public_token':token, 'bounds':bounds,
        'center':[(bounds[0]+bounds[2])/2,(bounds[1]+bounds[3])/2],
        'operator_map_pin':read_json(PIPELINE/'extraction.json')['operator_map_pin']})
    shutil.copy(ROOT/'maintenance/fortunes_cove_preview.html',output/'index.html')
    shutil.copy(pdf,output/'official-map.pdf')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    ext=sub.add_parser('extract');ext.add_argument('pdf',type=Path);ext.add_argument('--output',required=True,type=Path)
    prep=sub.add_parser('prepare-style');prep.add_argument('plan',type=Path);prep.add_argument('style',type=Path);prep.add_argument('--output',required=True,type=Path)
    view=sub.add_parser('preview');view.add_argument('plan',type=Path);view.add_argument('style',type=Path);view.add_argument('extraction_dir',type=Path);view.add_argument('pdf',type=Path);view.add_argument('--output',required=True,type=Path)
    pub=sub.add_parser('publish-style');pub.add_argument('plan',type=Path);pub.add_argument('preview',type=Path);pub.add_argument('--approve',required=True)
    args=parser.parse_args()
    if args.command=='extract':
        data,report=extract(args.pdf,read_json(PIPELINE/'extraction.json'))
        write_json(args.output/'trails.geojson',data);write_json(args.output/'extraction-report.json',report)
        print(report)
    elif args.command=='preview':
        build_preview(args.plan,args.style,args.extraction_dir,args.pdf,args.output)
        print('Preview:',args.output)
    elif args.command=='prepare-style':
        manifest,style=prepare_style(read_json(args.plan),read_json(args.style))
        write_json(args.output/'manifest.json',manifest);write_json(args.output/'style-proposal.json',style)
        print(manifest)
    else:
        load_env()
        print(publish_style(Mapbox(),read_json(args.plan),read_json(args.preview/'manifest.json'),read_json(args.preview/'style-proposal.json'),args.approve))


if __name__=='__main__': main()
