# Virginia State Parks: one source, reviewed park by park

[Main workflow](../../docs/maintenance-workflow.md) · [Lake Anna import](reviews/2026-11-03-lake-anna.json) · [Statewide queue audit](reviews/2026-11-03-statewide.json)

DCR maintains a public [VSP Trails service](https://www.arcgis.com/home/item.html?id=55d9567f69fe44adaaa9bd0142e7167c), owned by `Peter.lostritto_vdcr` in the verified **Virginia Department of Conservation and Recreation** organization `PxUNqSbaWFvFgHnJ`. The current endpoint is:

```text
https://services1.arcgis.com/PxUNqSbaWFvFgHnJ/arcgis/rest/services/SP_Trails/FeatureServer/0
```

The November 3 snapshot has **631 records in 43 named parks**, plus one record with no park name. This is service coverage, not a promise that every Virginia State Park or current trail is present. The service includes Breaks Interstate Park and developing areas. The similarly named `StateParkTrails` service is an older alternative; use the reviewed endpoint above.

The user chose **publish Lake Anna; queue the other parks for review**. Only Lake Anna is in `pipeline.json`'s `approved_parks`. The remaining 42 named parks and unassigned record are available in the visual review. An eligible row is a screening result, not publication authorization or proof of current public access.

## Data and authority

| Field | Treatment |
| --- | --- |
| `GlobalID` | Canonical UUID; stable feature identity `va-state-parks:<uuid>` |
| `OBJECTID` | Retained evidence, never used as the stable identity |
| `LABEL` | Park grouping and explicit approved-park policy |
| `Trail_Name` | Whitespace normalized into `name`; proposed/reroute/staff names held |
| `Status` | Only explicit `Open` is eligible; current operator alerts still take priority |
| `Trail_User` | H/B/E combinations for hiking/biking/equestrian; unknown, Staff, W and ambiguous codes held |
| `BlazeColor` | Preserved original; normalized color and park-specific reviewed display palette |
| `Difficulty` | Retained, with normalized display property |
| `outside_park` | Only explicit No is eligible; other records require access/overlap review |
| `Restrictions` | Missing or nontrivial restrictions held for review |

Every excluded record in an approved park appears in the ingest report. Unreviewed parks are counted separately. Empty/malformed geometry, duplicate or invalid GlobalIDs, unreviewed colors and missing overrides cannot silently produce a successful import. `overrides.json` records evidence for exceptions; original GIS fields remain available alongside normalized fields.

The item metadata requires credit to Virginia DCR and prohibits redistribution for profit. The source attribution is retained in each imported feature, infobox links and the map attribution. Preserve that credit and the source terms when reusing the data.

## Lake Anna decisions

[Accepted GeoJSON](data/lake-anna.geojson) contains 14 records, not a full replacement for the shared Mapbox dataset. The three `Proposed/Reroute Trail` records are held even though their GIS status says Open. Campground Walkway's missing use code is resolved to hiking from the official paper guide. Its original null `Trail_User` remains unchanged.

The official [paper guide](https://www.dcr.virginia.gov/state-parks/document/data/trail-guide-lakeanna.pdf) has no georeferencing. The separate [Avenza GeoPDF](https://www.dcr.virginia.gov/state-parks/document/data/lake-anna-avenza-map.pdf) does. Its EPSG:2283 projection uses **US survey feet**, so distance comparisons must convert to metres; do not label raw projected lengths or buffers as metres. The captured comparison found almost complete agreement within ten metres, with a small Mill Pond difference. It is screening evidence, not proof of field accuracy.

Lake Anna's palette follows the GeoPDF's blaze colors. The GIS Connector Trail aligns with an unlabeled tan segment in the older GeoPDF but explicitly has a current Blue blaze; that conflict is recorded and the current GIS Blue is used. The paper guide's twelve named trails plus campground walkway account for thirteen entries; the separately named GIS connector makes fourteen imported records.

The current park page lists a November 2–3 resource-management closure despite normal dawn-to-dusk hours and the GIS Open values. The infobox prominently records the alert and review date. Do not infer reopening solely from the calendar or GIS status. Recheck the page and update this static note; it does not expire automatically.

## Repeat source checks and normalization

```sh
python3 -m maintenance check --pipeline virginia-state-parks
python3 -m maintenance fetch-arcgis \
  https://services1.arcgis.com/PxUNqSbaWFvFgHnJ/arcgis/rest/services/SP_Trails/FeatureServer/0 \
  --output .trail-state/ROUND/state-park-trails.geojson
python3 -m maintenance normalize virginia-state-parks \
  .trail-state/ROUND/state-park-trails.geojson --source trails-gis \
  --output .trail-state/ROUND/approved-parks.geojson
```

The shared ArcGIS fetcher enumerates object IDs, retrieves explicit batches and rechecks membership. The monitor saves raw snapshots and candidates, never publishes them. The six registered sources (GIS, map directory, Lake Anna page, paper guide, GeoPDF and pet policy) all fetched during this session.

## Review another park

[parks.json](parks.json) links the reviewed source catalog: 39 directly matched visitor-page links and 40 GeoPDF links for the 43 named GIS parks. Missing links fall back to DCR's directory; no guessed visitor-page URLs are installed. The registry was derived from DCR's official park directory and map table, and should be refreshed as parks or links change.

```sh
python3 -m maintenance.state_parks .trail-state/ROUND/state-park-trails.geojson \
  --registry pipelines/virginia-state-parks/parks.json \
  --output .trail-state/review-state-parks
python3 -m http.server 8008 --bind 127.0.0.1 \
  --directory .trail-state/review-state-parks
```

Select a park, inspect eligible lines and red held records, read its official map and current alerts, and record notes. **Queue eligible trails for import** records the desired next step; it does not publish or override held records. Export `virginia-state-parks-decisions.json`. Notes persist in browser storage keyed to the exact review hash; export before rebuilding the review. The export includes the review and source hashes and must not be applied to a different snapshot.

Preview colors for unreviewed parks are approximate and have a neutral fallback. Before accepting a park, compare its official legend and establish its palette. Review disconnected park units, trailhead access, off-site segments, and duplication with existing Appalachian Trail, Shenandoah and other sources. Preserve the entire Rivanna dataset. Add a sourced infobox and narrow source audiences for the new park; do not turn a generic statewide source change into a notice for every park.

The next step after an export is to interpret its notes, verify hashes, resolve exceptions, and add the reviewed park policy/overrides. There is deliberately no command that turns a statewide queue export directly into Mapbox writes. Prepare a complete desired target dataset against a **fresh** inventory, replacing only explicitly reviewed pipeline-owned IDs. Preserve unrelated features. Unmatched historical features and source deletions require review.

## Publication

Lake Anna reuses the existing supplemental `strava` target, adding 14 features while retaining its 62 existing features, including Fortune’s Cove and the Heyward connector. It does not consume another Mapbox source. The display condition uses `pipeline_id == virginia-state-parks` and the reviewed `display_color`; the complete previous color expression remains the fallback for all other features.

The November 3 publication completed for both the dataset and live/draft styles. Ordinary requests initially retained an older style and missing zoom-13 tiles even while zooms 10, 12 and 16 had new data. Inspect the tracked Lake Anna audit for the separate ordinary and fresh-request rendering checks; upload completion alone does not mean all Mapbox caches are current.

The first-import style helper verifies that the dataset plan contains exactly the reviewed Lake Anna additions and no changes/deletions:

```sh
python3 -m maintenance.state_parks_style prepare PLAN.json CURRENT_STYLE.json \
  --output .trail-state/ROUND/style-proposal
# Apply the authorized dataset plan through the normal maintenance publisher first.
python3 -m maintenance.state_parks_style publish PLAN.json \
  .trail-state/ROUND/style-proposal --approve EXACT_STYLE_PROPOSAL_HASH
```

The common style writer verifies the data receipt, checks live/draft state, preserves unrelated draft edits and keeps recovery journals. It refuses blind replay. After the first installation, new DCR parks with reviewed `display_color` properties use the same style expression; routine data additions do not require another style change.

With the built website on 8000 and review on 8008, the relevant browser checks are:

```sh
node tests/system-info-browser.mjs pipelines/virginia-state-parks/reviews/2026-11-03-lake-anna.json
node tests/state-parks-review-browser.mjs
node tests/state-parks-publication-browser.mjs
# Diagnostic only if ordinary requests are stale:
node tests/state-parks-publication-browser.mjs --fresh
```

Archive source snapshots, the exact generated queue, user exports, baseline inventory, accepted plans and publication journals. Tracked audits preserve key findings and receipts; a fresh clone does not contain the ignored review map or raw snapshots. Rebuild new reviews from fresh sources if those original inputs cannot be restored.
