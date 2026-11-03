# Fortune’s Cove: extracting official GeoPDF trails

[Main workflow](../../docs/maintenance-workflow.md) · [Import audit](reviews/2026-11-03-import.json) · [Extracted GeoJSON](data/trails.geojson)

The TNC June 2020 map is an ArcMap GeoPDF with a `trails` vector layer and embedded NAD83 / UTM zone 17N control points. This pipeline reads those vectors directly. It does not trace pixels, infer coordinates with a model, or import OpenStreetMap routes.

`pipeline.json` monitors the official PDF and visitor page. `extraction.json` binds semantic route IDs to seven colored paths in the exact reviewed PDF. Black outlines duplicate the colored paths and are excluded, along with legends, the elevation profile, roads and the preserve boundary. The PDF has six yellow segments (including an overlook spur) and one white shortcut. The white loop also uses shared yellow sections; importing a second complete white loop would duplicate them.

The map's inverted-y viewport requires care: its local `(0,0)` control point is the northwest corner. The extractor projects the latitude/longitude control points into the declared UTM grid, fits an affine transformation, then converts drawing vertices to WGS84. It checks the projection, viewport, control residual, path membership, colors, segment counts and continuity. A changed PDF hash stops extraction for review. Its precise transformation does **not** establish survey-grade accuracy; these remain cartographic trails from 2020.

The first extraction produced 1,192 line segments across seven features. Its closest trail vertex was about 13 metres from the operator page's entrance pin. Lengths are consistent with the mapped 5.1-mile outer and 3.7-mile shorter walks. Colored paths stop on opposite sides of the parking area where the map instead shows roads. That separation is retained; private-road geometry is not imported as public trail access.

## Repeat the extraction

Run from the repository root. Install optional dependencies through `uv` or an isolated environment:

```sh
python3 -m maintenance check --pipeline fortunes-cove
# Locate the downloaded PDF in that run's review/snapshot record.
uv run --with-requirements pipelines/fortunes-cove/requirements-pdf.txt \
  python -m maintenance.fortunes_cove extract PATH_TO_OFFICIAL_PDF \
  --output .trail-state/fortunes-cove-next
```

The output contains `trails.geojson` and `extraction-report.json`. The checked-in `data/trails.geojson` is the accepted first extraction, not a full replacement of the shared Mapbox dataset. Do not pass those seven features alone to `maintenance plan strava`: that would propose deleting unrelated trails.

For a changed map, first inspect its vectors, georeferencing, route topology and current operator guidance. Update the hash/path selectors only after matching each semantic feature to the new source. Do not assign IDs by the new drawing order automatically. Reconcile the reviewed Fortune’s Cove subset against a fresh supplemental-dataset inventory, preserving all other features exactly. Review removals, changed junctions and source date before generating a full-dataset plan.

## Publishing and preview

The publishing target is the existing `strava` target / `Strava_Sidetrails` source layer, reused as the supplemental network container to avoid an additional tileset. Feature provenance explicitly identifies the official TNC source. The website resolves these trails to `fortunes-cove` using their area and source layer.

The first-publication helper accepts only the seven expected additions, with no changes/deletions to existing features. A future geometry revision uses the ordinary reviewed-plan workflow; the helper's addition-only restriction should not be weakened just to replay it.

```sh
python3 -m maintenance.fortunes_cove preview PLAN.json CURRENT_STYLE.json \
  EXTRACTION_DIRECTORY PATH_TO_OFFICIAL_PDF \
  --output .trail-state/review-fortunes-cove
python3 -m http.server 8007 --bind 127.0.0.1 \
  --directory .trail-state/review-fortunes-cove
```

The preview uses extracted GeoJSON over the real basemap and links the original PDF and downloadable geometry. Its green dot is the operator's entrance pin, an independent alignment check. It is not proof that live tiles contain the proposal.

After the exact dataset plan is authorized and published, the first import also requires its reviewed style proposal:

```sh
python3 -m maintenance.fortunes_cove publish-style PLAN.json \
  .trail-state/review-fortunes-cove --approve EXACT_STYLE_PROPOSAL_HASH
```

This changes only `strava-trail`'s line-color expression, selecting yellow/white for `system_id == fortunes-cove` and preserving the prior expression as the fallback. It retains all layer ordering, Rivanna styling and unrelated Studio draft edits. Live and draft are backed up and journaled separately; a stale style or an attempted write stops for investigation. Subsequent geometry-only updates need no additional style write.

Verify ordinary public tiles at several zoom levels and use fresh diagnostic tile keys only to investigate propagation. Keep plan, extraction report, PDF, source reviews, backup and publication journals with the tracked audit. Archive complete accepted plans under `.trail-state/published-plans/`.

## Visitor information

The official page supplies dawn-to-dusk hours, no-pet rules (service animals welcome), no biking/horseback riding/camping, facilities and the road-erosion warning. The page mentions both 5.5 miles and 5.1 miles for the longer hike; the infobox explicitly attributes 5.1/3.7 miles to the map. The erosion warning is a static fact as reviewed on November 3, 2026, and must be rechecked rather than treated as an automatically expiring closure.

With the built website served on port 8000 and Playwright/Chromium installed:

```sh
node tests/system-info-browser.mjs pipelines/fortunes-cove/reviews/2026-11-03-import.json
node tests/fortunes-cove-publication-browser.mjs
# Only when diagnosing a stale ordinary result:
node tests/fortunes-cove-publication-browser.mjs --fresh
```

The publication check uses real remote tiles, without substituting the extracted GeoJSON. It checks all seven semantic segment IDs at overview zooms 10/12/14 and each segment at zoom 16. Fresh mode changes both the tile query key and the optimized-style variable; it distinguishes a working new release from cached public results but does not isolate those two cache layers from each other.
