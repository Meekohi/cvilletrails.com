"""Read-only RTF KML comparison. Snapshot keys are not stable source identities."""
import argparse
import copy
from collections import Counter
from html import unescape
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

from .common import ROOT, digest, now, read_json, write_json
from .geo import canonical, fingerprint
from .overlaps import geometry_tools, coverage

KML_NS = {'k': 'http://www.opengis.net/kml/2.2'}
SOURCE_URL = 'https://www.google.com/maps/d/kml?mid=1No2V69q9UmHLUaqGXqTG5HomnrYibaDL&forcekml=1'
OFFICIAL_PAGE = 'https://www.rivannatrails.org/Map'


def plain(value):
    return ' '.join(unescape(re.sub('<[^>]+>', ' ', value or '')).split())


def parse_kml(content):
    """Keep folder context and exclusion reasons; never interpret event lines as RT."""
    root = ET.fromstring(content)
    records, folders = [], []
    for folder in root.findall('.//k:Folder', KML_NS):
        label = plain(folder.findtext('k:name', namespaces=KML_NS))
        counts = Counter()
        for ordinal, mark in enumerate(folder.findall('k:Placemark', KML_NS)):
            name = plain(mark.findtext('k:name', namespaces=KML_NS))
            description = plain(mark.findtext('k:description', namespaces=KML_NS))
            lines = []
            for line in mark.findall('.//k:LineString', KML_NS):
                coords = [[float(v) for v in item.split(',')[:2]] for item in line.findtext('k:coordinates', default='', namespaces=KML_NS).split()]
                if len(coords) > 1: lines.append(coords)
            kind = 'line' if lines else 'point' if mark.find('.//k:Point', KML_NS) is not None else 'other'
            counts[kind] += 1
            event = 'loop deville' in label.lower()
            eligible = bool(lines) and not event and (label.startswith('Section #') or label == 'RTF River North Trail')
            text = (name + ' ' + description).lower()
            flags = []
            if re.search(r'\bclosed\b|\bclosure\b', text): flags.append('closure')
            if 'detour' in text: flags.append('detour')
            if re.search(r'\bnew\b|\b2023\b', text): flags.append('source-describes-new-route')
            if 'road walk' in text: flags.append('road-walk')
            if 'old rt route' in text: flags.append('former-main-route')
            geometry = {'type': 'LineString', 'coordinates': lines[0]} if len(lines) == 1 else {'type': 'MultiLineString', 'coordinates': lines} if lines else None
            semantic_key = f'{label.casefold()} / {name.casefold()}'
            record = {'name': name, 'folder': label, 'description': description, 'kind': kind,
                      'embedded_date_text': re.findall(r'\b\d{1,2}\.\d{1,2}\.20\d{2}\b|\b20\d{2}\b|\bmid January\b', description, re.IGNORECASE),
                      'source_id': mark.get('id'), 'source_ordinal': ordinal,
                      'semantic_key': semantic_key, 'snapshot_key': 'kml:' + digest([label, name, geometry, ordinal])[:20],
                      'style_url': mark.findtext('k:styleUrl', default='', namespaces=KML_NS),
                      'eligible_for_route_review': eligible, 'flags': flags,
                      'exclusion_reason': None if eligible else 'event-only layer' if event else 'non-line reference marker' if not lines else 'unrecognized folder',
                      'geometry': geometry}
            records.append(record)
        folders.append({'name': label, 'counts': dict(counts)})
    duplicates = {key: count for key, count in Counter(r['semantic_key'] for r in records).items() if count > 1}
    return {'folders': folders, 'records': records, 'duplicate_semantic_keys': duplicates}


def compare_rivanna(content, current, sources, inventory_dir=None):
    project, union, Tree = geometry_tools()
    current = canonical(current)
    parsed = parse_kml(content)
    features = [f for f in current['features'] if f['geometry']['type'] in {'LineString', 'MultiLineString'}]
    shapes = [project(f['geometry']) for f in features]
    tree = Tree(shapes)
    current_union = union(shapes)
    current_buffers = {str(d): current_union.buffer(d) for d in (3, 10, 20)}
    def buffered_coverage(line, buffers):
        return {key: round(min(1, line.intersection(buffer).length/line.length), 4) if line.length else 0 for key, buffer in buffers.items()}
    other_networks = []
    if inventory_dir:
        inventory = Path(inventory_dir)
        style = read_json(inventory/'style.json')
        active = {layer.get('source-layer') for layer in style['layers'] if layer['type']=='line' and layer.get('layout',{}).get('visibility')!='none'}
        tilesets = read_json(inventory/'tilesets.json')
        configured = {t['dataset']:t for t in read_json(ROOT/'config/mapbox.json')['targets']}
        official_extent = union([project(r['geometry']) for r in parsed['records'] if r['eligible_for_route_review']])
        for dataset in read_json(inventory/'datasets.json'):
            layers = {l['id'] for tid, tiles in tilesets.items() if tid.split('.',1)[1].startswith(dataset['id']+'-') for l in tiles['vector_layers']}
            if 'Rivanna_Trail' in layers or not layers & active: continue
            target = configured.get(dataset['id'], {'id':dataset['name'],'dataset':dataset['id']})
            fc = read_json(inventory/'datasets'/f"{dataset['id']}.geojson")
            geometry = union([project(f['geometry']) for f in fc['features'] if f['geometry']['type'] in {'LineString','MultiLineString'}])
            if geometry.is_empty or geometry.distance(official_extent)>20: continue
            other_networks.append((target, geometry, fingerprint(fc), {'10': geometry.buffer(10)}))
    rows = []
    for source in parsed['records']:
        if not source['eligible_for_route_review']: continue
        geometry = project(source['geometry'])
        if not geometry.length: continue
        matches = []
        for index in tree.query(geometry.buffer(20)):
            existing, other = features[index], shapes[index]
            forward, reverse = coverage(geometry, other, (3, 10, 20)), coverage(other, geometry, (3, 10, 20))
            if forward['10'] * geometry.length < 15 and reverse['10'] < .5: continue
            matches.append({'feature_id': existing['id'], 'name': existing['properties'].get('Name', ''),
                            'source_coverage': forward, 'current_coverage': reverse,
                            'current_properties': existing['properties']})
        matches.sort(key=lambda m: (m['source_coverage']['10'], m['current_coverage']['10']), reverse=True)
        reciprocal = [m['feature_id'] for m in matches if m['source_coverage']['3'] >= .99 and m['current_coverage']['3'] >= .99]
        fractions = buffered_coverage(geometry, current_buffers)
        unmatched = geometry.difference(current_buffers['10'])
        needs_identity = not source['source_id'] or source['semantic_key'] in parsed['duplicate_semantic_keys']
        classification = 'close-existing-route' if fractions['3'] >= .9 else 'mostly-existing-route' if fractions['10'] >= .8 else 'partial-route-difference' if fractions['10'] >= .25 else 'substantial-route-difference'
        priority = 'access-status' if any(f in source['flags'] for f in ('closure', 'detour')) else 'geometry' if fractions['10'] < .8 else 'identity-and-curation'
        rows.append({**source, 'length_m': round(geometry.length, 1), 'coverage_of_source': fractions,
                     'unmatched_10m_m': round(unmatched.length, 1), 'matches': matches,
                     'other_network_coverage': [{'target': target['id'], 'dataset': target['dataset'], 'coverage': buffered_coverage(geometry, buffers)}
                                                for target, other, _, buffers in other_networks if geometry.distance(other)<20],
                     'classification': classification, 'review_priority': priority,
                     'crosswalk_proposal': {'status': 'strong-geometric-correspondence' if len(reciprocal)==1 else 'manual-identity-review',
                                           'current_feature_ids': reciprocal,
                                           'approved': False, 'preserve_current_id_and_properties': True},
                     'identity_requires_review': needs_identity})
    official_union = union([project(r['geometry']) for r in rows])
    official_buffers = {str(d): official_union.buffer(d) for d in (3, 10, 20)}
    current_rows = []
    for feature, geometry in zip(features, shapes):
        fractions = buffered_coverage(geometry, official_buffers)
        current_rows.append({'feature_id': feature['id'], 'name': feature['properties'].get('Name', ''),
                             'length_m': round(geometry.length, 1), 'coverage_by_official': fractions,
                             'unmatched_10m_m': round(geometry.length * (1-fractions['10']), 1),
                             'action': 'retain-entire-feature', 'properties': feature['properties']})
    rows.sort(key=lambda r: ({'access-status': 0, 'geometry': 1, 'identity-and-curation': 2}[r['review_priority']], -r['unmatched_10m_m']))
    report = {'schema_version': 1, 'created_at': now(), 'review_type': 'read-only-source-comparison',
              'sources': sources, 'official_page': OFFICIAL_PAGE, 'current_hash': fingerprint(current),
              'current_feature_count': len(current['features']), 'current_features_preserved': True,
              'folders': parsed['folders'], 'placemark_count': len(parsed['records']),
              'stable_source_ids': sum(bool(r['source_id']) for r in parsed['records']),
              'duplicate_semantic_keys': parsed['duplicate_semantic_keys'],
              'other_networks': [{'target':target['id'],'dataset':target['dataset'],'hash':fingerprint_} for target,_,fingerprint_,_ in other_networks],
              'excluded': [{k: r[k] for k in ('snapshot_key', 'folder', 'name', 'kind', 'exclusion_reason')} for r in parsed['records'] if not r['eligible_for_route_review']],
              'rows': rows, 'current_rows': current_rows,
              'summary': {'official_route_records': len(rows), 'priorities': dict(Counter(r['review_priority'] for r in rows)),
                          'classes': dict(Counter(r['classification'] for r in rows)),
                          'official_unique_line_m': round(official_union.length, 1), 'current_unique_line_m': round(current_union.length, 1),
                          'official_unique_unmatched_10m_m': round(official_union.difference(current_union.buffer(10)).length, 1),
                          'current_unique_unmatched_10m_m': round(current_union.difference(official_union.buffer(10)).length, 1)},
              'limitations': ['Distance screening does not establish identity, access, or superior accuracy.',
                              'Snapshot keys and name/folder semantic keys are not persistent upstream IDs.',
                              'Descriptions and style colors are evidence, not approved changes to curated route classes.',
                              'Closed and detour lines remain in this comparison but are not proposed as open trails.',
                              'All current Rivanna features are retained; unmatched current geometry is not a deletion proposal.',
                              'Other-network coverage includes active editable datasets near these routes; basemap roads and uneditable external tilesets are excluded.',
                              'No publishable replacement candidate or Mapbox writes are produced.']}
    report['review_hash'] = digest(report)
    return report


def build_review(kml_path, current_path, sources_path, output, inventory_dir=None):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    current = read_json(current_path)
    report = compare_rivanna(Path(kml_path).read_bytes(), current, read_json(sources_path), inventory_dir)
    token = re.search(r"mapboxgl.accessToken = '(pk\.[^']+)'", (ROOT/'assets/app.js').read_text())[1]
    settings = read_json(ROOT/'config/mapbox.json')
    write_json(output/'review.json', {'report': report, 'current': copy.deepcopy(current), 'public_token': token,
                                     'style': f"mapbox://styles/{settings['username']}/{settings['style_id']}"})
    write_json(output/'report.json', report)
    for name in ('index.html', 'review.js', 'review.css'):
        shutil.copyfile(ROOT/'maintenance/rivanna_review_ui'/name, output/name)
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kml', type=Path, required=True); parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--sources', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inventory', type=Path)
    args=parser.parse_args(); result=build_review(args.kml,args.current,args.sources,args.output,args.inventory)
    print({'review_hash':result['review_hash'], **result['summary']})
