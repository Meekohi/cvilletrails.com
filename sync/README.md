# Trail data sync

Pulls authoritative trail data and pushes it into the Mapbox datasets/tilesets behind the map.

```
source (Google My Maps KML)  ->  Mapbox dataset  ->  Mapbox tileset  ->  map style (index.html)
```

The style reads **tilesets**, so a dataset change only shows up on the site after `--publish`.

## Usage

```sh
export MAPBOX_TOKEN=sk....        # secret token: datasets:read/write, uploads:write
python3 sync/trailsync.py rivanna-trail                    # dry run: fetch, convert, diff
python3 sync/trailsync.py rivanna-trail --kml-file x.kml   # dry run from a downloaded KML/KMZ
python3 sync/trailsync.py rivanna-trail --apply --publish  # update dataset and live tileset
```

Every run writes a backup of the current dataset and a preview of the converted source to
`sync/backups/` (git-ignored). `--apply` refuses if the source has under half the current trail
length unless `--force` is given. After `--apply`, commit `sync/data/<trail>.geojson` so git keeps a
history of trail changes.

## Adding a trail

Add an entry to `sources.json` with the source and the Mapbox `dataset`, `tileset` and
`tileset_name` (the tileset name is the source-layer the style references, so keep it unchanged).
