"""Hash-locked extraction of reviewed ArcMap trail vectors; optional geo dependencies."""
import hashlib
from pathlib import Path
from .common import digest
from .geo import canonical, fingerprint


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
    colors = manifest['palette']
    actual = {i for i, d in enumerate(drawings) if d.get('layer') == manifest['vector_layer']
              and d.get('color') and any(max(abs(a-b) for a,b in zip(d['color'], colors[p['color']])) < 0.0001
                  and abs(d['width'] - p['width']) < .0001 for p in manifest['paths'])}
    if actual != selected | set(manifest.get('excluded_casings', [])):
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
        props = {'name': item['name'], 'color': item['color'],
                 'map_color': '#' + ''.join(f'{round(v*255):02x}' for v in colors[item['color']]), 'source_map_date': manifest['map_date'],
                 'pipeline_id': 'tnc-virginia', 'system_id': manifest['system_id'],
                 'source_id': manifest['id'], 'source_url': manifest['url'],
                 'geometry_method': 'official-geopdf-vector-extraction', 'source_sha256': manifest['pdf_sha256']}
        raw.append({'type': 'Feature', 'id': 'tnc-virginia:' + manifest['id'] + ':' + item['id'], 'properties': props,
                    'geometry': {'type': 'LineString', 'coordinates': coords}})
        lengths[item['id']] = round(geod.line_length(*zip(*coords)), 2)
    result = canonical({'type':'FeatureCollection', 'features':raw})
    coordinates = [c for f in result['features'] for c in f['geometry']['coordinates']]
    bounds = [min(c[0] for c in coordinates), min(c[1] for c in coordinates),
              max(c[0] for c in coordinates), max(c[1] for c in coordinates)]
    expected = manifest['expected_bounds']
    if any(abs(a-b) > .00001 for a,b in zip(bounds, expected)):
        raise ValueError('Extracted trails differ from reviewed geographic extent')
    report = {'pdf_sha256': manifest['pdf_sha256'], 'manifest_hash': digest(manifest),
              'crs':crs.to_string(), 'control_residual_m':residual.tolist(),
              'bounds':bounds, 'lengths_m':lengths,
              'feature_count':len(result['features']), 'geometry_hash':fingerprint(result),
              'limitations':['Cartographic linework; control residual is transform fit, not surveyed accuracy.',
                             'Only manifest-selected trails; Bottom Creek includes its designated walking entrance road.',
                             'Parking-area gaps in colored paths are retained; no private-road access inferred.']}
    return result, report
