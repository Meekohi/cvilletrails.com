# Virginia State Parks: one source, reviewed park by park

[Main workflow](../../docs/maintenance-workflow.md) · [Lake Anna import](reviews/2026-11-03-lake-anna.json) · [Statewide queue audit](reviews/2026-11-03-statewide.json)

DCR maintains a public [VSP Trails service](https://www.arcgis.com/home/item.html?id=55d9567f69fe44adaaa9bd0142e7167c), owned by `Peter.lostritto_vdcr` in the verified **Virginia Department of Conservation and Recreation** organization `PxUNqSbaWFvFgHnJ`. The current endpoint is:

```text
https://services1.arcgis.com/PxUNqSbaWFvFgHnJ/arcgis/rest/services/SP_Trails/FeatureServer/0
```

The November 3 snapshot has **631 records in 43 named parks**, plus one record with no park name. This is service coverage, not a promise that every Virginia State Park or current trail is present. The service includes Breaks Interstate Park and developing areas. The similarly named `StateParkTrails` service is an older alternative; use the reviewed endpoint above.

The user chose **publish Lake Anna; queue the other parks for review**. That initial scope was completed, then the user accepted the combined statewide proposal. `pipeline.json` now registers 40 parks: Lake Anna plus the 39 parks represented in the accepted 492-addition batch. Culpeper Battlefields, Hayfields and Mayo River remain unapproved; the unassigned record is also held. The frozen previews retain the original reviewed state. An eligible row is a screening result, not publication authorization or proof of current public access.

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

The shared palette in `pipeline.json` is used by the newly accepted parks; Lake Anna retains its park-specific palette. `held_features` preserves the explicit mixed orange/white blaze exception so normalization cannot silently include it. Removing or resolving that hold requires a new review. Every excluded record in an approved park appears in the ingest report. Unreviewed parks are counted separately. Empty/malformed geometry, duplicate or invalid GlobalIDs, unreviewed colors and missing overrides cannot silently produce a successful import. `overrides.json` records evidence for exceptions; original GIS fields remain available alongside normalized fields.

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

The shared ArcGIS fetcher enumerates object IDs, retrieves explicit batches and rechecks membership. The monitor saves raw snapshots and candidates, never publishes them. There are now 45 registered sources: the original six plus 39 scoped visitor pages. All fetched successfully during the statewide publication. DCR pet-policy and map-directory audiences exclude Breaks Interstate Park; its own official visitor page is registered separately.

## Review another park

[parks.json](parks.json) links the reviewed source catalog: 42 verified visitor-page links and 40 GeoPDF links for the 43 named GIS parks. Missing links fall back to DCR's directory; no guessed visitor-page URLs are installed. The registry was derived from DCR's official park directory and map table, and should be refreshed as parks or links change.

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

## Statewide sanity check

The batch builder uses the same normalizer in a temporary candidate configuration. Building a review does **not** expand `pipeline.json`'s approved park list or change the live website. The original November 3 batch has since been accepted; the frozen review files and its audit preserve exactly what was reviewed. [candidate-policy.json](candidate-policy.json) supplies a proposed shared palette for the other DCR blaze names; the Lake Anna palette and all existing supplemental features are preserved. Shades outside Lake Anna approximate the source color names, rather than claiming to have sampled every park PDF. The mixed `Orange, White` record remains held.

```sh
python3 -m maintenance fetch-arcgis \
  https://services1.arcgis.com/PxUNqSbaWFvFgHnJ/arcgis/rest/services/SP_Trails/FeatureServer/0 \
  --output .trail-state/state-parks-statewide/source.geojson
python3 -m maintenance inventory --output .trail-state/state-parks-statewide/inventory
# Install maintenance/requirements-geo.txt in your environment for overlap screening.
python3 -m maintenance.state_parks_batch \
  --source .trail-state/state-parks-statewide/source.geojson \
  --inventory .trail-state/state-parks-statewide/inventory \
  --output .trail-state/review-state-parks-batch
python3 -m http.server 8009 --bind 127.0.0.1 \
  --directory .trail-state/review-state-parks-batch
```

Open **http://localhost:8009/**. Start with the statewide view; click a park marker, choose a park, or use Next park. New lines use their proposed colors. Held records are optional red dashed lines. The preview starts focused on proposed trails; showing held records expands the extent to include them. The existing live map remains underneath for comparison.

There is one **Looks good — accept proposed batch** decision. Individual park/trail exclusions and a general note are optional. Export **virginia-state-parks-batch-decisions.json**; it includes the review, source and exact proposed plan hashes, explicit included feature IDs, exclusions and notes. Held records can be inspected but cannot accidentally enter the accepted batch. Browser notes are scoped to the exact review hash; export before rebuilding. The older park-by-park queue at 8008 is separate and retains its prior export format.

The November 3 batch proposes **492 additions in 39 parks**, preserves **14 already published Lake Anna records**, and holds **125 records** across the full 631-record source. The holds include incomplete metadata, off-site segments, staff/water routes, proposed/closed names and the mixed-color record; they are not all known closures. Culpeper Battlefields, Hayfields and Mayo River have no records passing the current filter. Lake Anna's three prior holds and the one unassigned feature are included in the held total. An explicitly named **Potomac Heritage Trail - closed section** was held despite GIS `Status=Open`; the shared normalizer now checks closed/abandoned names as well as proposed/staff names.

All 492 additions screened as having no substantial overlap with the **visible editable custom trail datasets**, including the Appalachian and Rivanna trails. Four pairs within the DCR candidate flag seven records: the named Smyth route follows High Bridge Trail, a James River connector runs close to Taylor Pond Loop, and Pocahontas contains overlapping named routes/connectors. These are inspection hints, not automatic deletions. The shared segments remain in the proposed batch. One uploaded Shenandoah tileset (`meekohi.8n5896es`) lacks an editable dataset in the inventory, so it is explicitly outside the geometric comparison and remains visible for visual comparison. Background Mapbox roads/paths are likewise not used as a reason to delete authoritative DCR trails.

The generated directory contains `candidate.geojson` (the complete desired supplemental dataset), `additions.geojson`, `plan.json`, `review.json`, `overlaps.json`, reference geometry and `systems-proposal.json`. The last file contains proposed names, IDs, extents and known official URLs only. Publication added basic info panels for the 39 accepted parks and dated notes for 19 operator alerts; comprehensive hours, rules and hike descriptions remain separate work. The current batch is **additions only**: existing source changes or missing previously published IDs are surfaced and preserved, never silently overwritten or deleted.

After the user's sanity check, verify the export's hashes and that its included IDs exactly equal candidate IDs minus explicit exclusions. Interpret any notes before publishing. Prepare a new exact plan for any excluded subset against fresh Mapbox data; if the source or baseline changed, reconcile the review first. Register accepted park policies and any desired infoboxes before enabling their ongoing monitoring. The builder itself makes no remote writes, and the candidate plan is not authorization to apply it.

Regression checks: `python3 -m unittest tests.test_state_parks tests.test_state_parks_batch` and, with the preview server running, `node tests/state-parks-batch-browser.mjs`. The browser test exercises rendered geometry, batch acceptance, park/trail exclusions, export hashes and exact inclusion counts, persistence, the closed-name exception and mobile layout.

## Accepted statewide publication

The [publication audit](reviews/2026-11-03-statewide-batch-publication.json) records the user’s explicit acceptance of the complete batch, the frozen review hash, a fresh-source match and the publication plan. [Accepted additions](data/statewide-2026-11-03.geojson) preserve the exact 492 reviewed features in compact GeoJSON. The full target grows from 76 to 568 features without changing or deleting any existing feature, including all Lake Anna and Fortune’s Cove trails and the Heyward connector. Rivanna and the other datasets are untouched. The DCR color expression installed with Lake Anna already covers these features; no further style write is needed.

The registered pipeline reproduces the accepted 492 features plus Lake Anna’s 14 exactly from the source snapshot. Future changes still produce candidates for review, not automatic publication. Refresh the complete desired supplemental dataset against a fresh Mapbox baseline before making a new plan; never submit the 506-feature DCR subset as a replacement for the shared target.

All 39 newly used official visitor pages returned successfully. Basic info panels now identify the accepted parks, link to their operator and map, and show dated summaries of relevant operator alerts. Temporary closures do not erase the underlying trail geometry. Those notes are static, explicitly dated November 3, and require review when conditions change; an elapsed date alone is not evidence of reopening.

The dataset API publisher deliberately waits between feature writes to respect its 40-write-per-minute limit. A batch of this size needs roughly fifteen to twenty minutes for writes and upload, plus rendering checks (this round took about eighteen minutes before tile verification). Its durable journal records each completed write. If interrupted, inspect that journal and compare current features before continuing; do not rerun a partially completed plan blindly.

After publication, `node tests/state-parks-batch-publication-browser.mjs` checks real remote overview tiles for all 492 IDs in all 39 parks and one zoom-16 detail view per park, including the display color. `--fresh` diagnoses tile-cache propagation separately. The browser uses three pages concurrently; it never substitutes the local candidate for remote tiles.

## Lake Anna first-import publication

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
