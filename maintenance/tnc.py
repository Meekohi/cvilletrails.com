"""Discover Virginia TNC preserves and extract only reviewed, hash-locked trail maps."""
import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from .common import ROOT, digest, read_json, request, write_json
from .geo import canonical

PIPELINE = ROOT / 'pipelines/tnc-virginia'
CATALOG_URL = 'https://www.nature.org/en-us/get-involved/how-to-help/places-we-protect/'
MAP_IDS = ('bear-loop', 'ingalls-overlook', 'sandy-gap', 'bottom-creek-gorge', 'cumberland-marsh')


def catalog(data):
    text = data.decode('utf-8')
    marker = '{"openHighlightPin"'
    if text.count(marker) != 1:
        raise ValueError('TNC catalog structure changed; expected one embedded map configuration')
    config, _ = json.JSONDecoder().raw_decode(text[text.index(marker):])
    items = config.get('mapItems')
    if not isinstance(items, list) or not items:
        raise ValueError('TNC catalog has no map items')
    rows = []
    for item in items:
        # Tags include out-of-state partners; location is the scope boundary.
        if item.get('markerSubtitle') != 'Virginia': continue
        url = item.get('link', '')
        if urlparse(url).hostname != 'www.nature.org' or not url.startswith('https://'):
            raise ValueError('Unexpected TNC preserve URL')
        status = item.get('preserveStatus')
        if status not in {'Open to the Public', 'Limited Access', 'Closed to the Public'}:
            raise ValueError('Unknown preserve access status')
        rows.append({'id':url.rstrip('/').split('/')[-1], 'name':item['title'], 'url':url,
                     'access':status, 'location':item.get('locationTitle'),
                     'latitude':float(item['markerLatitude']), 'longitude':float(item['markerLongitude']),
                     'hours':item.get('hoursDesc'), 'description':item.get('description'),
                     'tags':sorted(t['tag'] for t in item.get('preserveTags', []))})
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Missing Virginia preserves or duplicate catalog identities')
    return sorted(rows, key=lambda r:r['id'])


class PDFLinks(HTMLParser):
    def __init__(self, url):
        super().__init__(); self.url = url; self.links = set()

    def handle_starttag(self, tag, attrs):
        if tag != 'a': return
        url = urljoin(self.url, dict(attrs).get('href', ''))
        parsed = urlparse(url)
        if parsed.scheme == 'https' and parsed.hostname == 'www.nature.org' and parsed.path.lower().endswith('.pdf'):
            self.links.add(url)


def discover(output):
    data = request(CATALOG_URL)[0]
    rows = catalog(data)
    write_json(output/'catalog.json', rows)
    (output/'catalog.html').write_bytes(data)
    # All preserves remain in the inventory, including closed sites. PDF links are
    # discovery evidence, never permission to extract or publish their contents.
    for row in rows:
        data = request(row['url'])[0]
        (output/(row['id']+'.html')).write_bytes(data)
        parser = PDFLinks(row['url']); parser.feed(data.decode('utf-8'))
        row['pdfs'] = sorted(parser.links)
        row['page_sha256'] = digest(data)
    write_json(output/'preserve-inventory.json', rows)
    return rows


def download_maps(output):
    output.mkdir(parents=True, exist_ok=True)
    for sid in MAP_IDS:
        manifest = read_json(PIPELINE/(sid+'.json'))
        data = request(manifest['url'])[0]
        if digest(data) != manifest['pdf_sha256']:
            raise ValueError(f'{sid}: official PDF changed; review extraction manifest before continuing')
        (output/manifest['filename']).write_bytes(data)
    return len(MAP_IDS)


def extract_maps(pdf_directory, output):
    from .geopdf import extract
    features, reports = [], {}
    for sid in MAP_IDS:
        manifest = read_json(PIPELINE/(sid+'.json'))
        collection, report = extract(pdf_directory/manifest['filename'], manifest)
        features.extend(collection['features']); reports[sid] = report
    result = canonical({'type':'FeatureCollection', 'features':features})
    result['ingest_report'] = {'review_only':True, 'reason':'Requires overlap decisions and final review', 'maps':reports}
    write_json(output/'tnc.geojson', result)
    write_json(output/'extraction-report.json', reports)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    d = sub.add_parser('discover'); d.add_argument('--output', type=Path, required=True)
    dl = sub.add_parser('download-maps'); dl.add_argument('--output', type=Path, required=True)
    e = sub.add_parser('extract'); e.add_argument('pdf_directory', type=Path); e.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'download-maps':
        print('Verified maps:', download_maps(args.output)); return
    result = discover(args.output) if args.command == 'discover' else extract_maps(args.pdf_directory, args.output)
    print('Preserves:', len(result)) if isinstance(result, list) else print('Trail segments:', len(result['features']))


if __name__ == '__main__': main()
