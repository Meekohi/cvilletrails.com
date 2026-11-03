"""Build explicitly named vector layers before replacing an existing tileset."""
import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
from .common import write_json


def publishing_tools():
    tippecanoe = shutil.which(os.environ.get('TIPPECANOE', 'tippecanoe'))
    aws = shutil.which('aws')
    if not tippecanoe or not aws:
        raise ValueError('Publishing requires Tippecanoe and the AWS CLI; install them before applying a plan with --publish')
    return tippecanoe, aws


def build_tiles(collection, layer, directory):
    tippecanoe, _ = publishing_tools()
    source, output = Path(directory) / 'reviewed.geojson', Path(directory) / 'reviewed.mbtiles'
    write_json(source, collection)
    result = subprocess.run([
        tippecanoe, '--output', str(output), '--layer', layer,
        '--minimum-zoom', '0', '--maximum-zoom', '16',
        '--no-line-simplification', '--no-feature-limit', '--no-tile-size-limit', str(source),
    ], capture_output=True)
    if result.returncode: raise RuntimeError('Tippecanoe failed to build the reviewed tileset')
    with sqlite3.connect(f'file:{output}?mode=ro', uri=True) as db:
        metadata = dict(db.execute('SELECT name, value FROM metadata'))
        layers = json.loads(metadata['json'])['vector_layers']
        if [entry['id'] for entry in layers] != [layer] or not db.execute('SELECT count(*) FROM tiles').fetchone()[0]:
            raise ValueError('Built tileset does not contain the required source layer and tiles')
    return output


def stage_tiles(path, credentials):
    _, aws = publishing_tools()
    env = {**os.environ,
           'AWS_ACCESS_KEY_ID': credentials['accessKeyId'],
           'AWS_SECRET_ACCESS_KEY': credentials['secretAccessKey'],
           'AWS_SESSION_TOKEN': credentials['sessionToken'],
           'AWS_DEFAULT_REGION': 'us-east-1', 'AWS_EC2_METADATA_DISABLED': 'true', 'AWS_PAGER': ''}
    result = subprocess.run([aws, 's3', 'cp', str(path),
                             f"s3://{credentials['bucket']}/{credentials['key']}",
                             '--region', 'us-east-1', '--only-show-errors'], env=env, capture_output=True)
    if result.returncode: raise RuntimeError('Could not stage the verified tileset in Mapbox storage')
    return credentials['url']
