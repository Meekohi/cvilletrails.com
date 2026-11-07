# Albemarle County GIS: validation before replacement

[Source research](../../docs/source-research.md) · [Maintenance workflow](../../docs/maintenance-workflow.md)

The registered `county-gis` source is the County's operational [public trail view, layer 7](https://services2.arcgis.com/khVz7mitcPJHUnlM/arcgis/rest/services/County_Park_Trails_Public/FeatureServer/7). The reviewed November 6 update is published: 330 accepted source geometries plus 46 southern Biscuit records included as open per the user's local correction, with all 27 color decisions applied. The full reconciliation retains unmatched routes and cleans up superseded Biscuit GPS tracks. See [publication evidence](reviews/2026-11-06-publication.json) for exact plans, stored-data and public-tile verification. Park aliases in `pipeline.json` define comparison scope, not permission to import future source changes automatically.

## Screening and identity

The adapter requires all of: a configured location alias, `Status=Active`, `Ownership=Public` or `Public Use Trail`, `Property_Info=Open`, explicit `Hiking=Yes`, a usable name, and valid nonzero WGS84 line geometry. Proposed, inactive, private, staff, maintenance and emergency names are held. Every excluded feature appears in the ingest report, including records outside the configured scope. Conditional access, unknown access and null hiking permission are held. Null bicycle/equestrian fields remain null; they do not become a permission or prohibition. Current operator alerts still take precedence over GIS values.

The explicit exception is [access-decisions.json](access-decisions.json): 46 exact southern Biscuit IDs have user-reviewed effective access `Open` and hiking `Yes`. Each is bound to its reviewed geometry and access-relevant source attributes; changed or missing records stop normalization for review. Normalized records retain the GIS values in `source_Property_Info` and `source_Hiking`, plus the decision's provenance hashes. Color overrides cannot grant access. This separate exception does not bypass private ownership, inactive status, other access holds, or grant bicycle/equestrian permission.

Source IDs use canonical UUIDs from `GlobalID`, prefixed `albemarle:`. Missing, malformed or duplicate GlobalIDs stop normalization even on otherwise excluded records. `OBJECTID` is retained as evidence, never used as identity. GlobalID persistence through future County service republishing is not established; investigate a wholesale ID change rather than treating it as additions/deletions.

Original GIS fields are retained. `Trail_Name` supplies `name` and the legacy `TrailName`; location aliases supply the legacy `LocationNa` while retaining `Loc_Name`. The live County style assigns colors by `TrailName`. A name change is therefore a potential color change, even with identical coordinates. Existing curated IDs and properties are preserved in the saved baseline, not overwritten by the normalized source. Overrides may preserve reviewed `name`, `TrailName` and `color` values; they cannot bypass eligibility or change identity. Missing or newly held overridden records fail normalization.

## Capture and build a validation round

```sh
python3 -m maintenance fetch-arcgis \
  https://services2.arcgis.com/khVz7mitcPJHUnlM/arcgis/rest/services/County_Park_Trails_Public/FeatureServer/7 \
  --output .trail-state/ROUND/source.geojson
python3 -m maintenance inventory --output .trail-state/ROUND/inventory
python3 -m maintenance normalize albemarle .trail-state/ROUND/source.geojson \
  --source county-gis --output .trail-state/ROUND/screened.geojson
# Install maintenance/requirements-geo.txt, or use uv's isolated dependencies:
uv run --with-requirements maintenance/requirements-geo.txt python -m maintenance.albemarle_review \
  --source .trail-state/ROUND/source.geojson \
  --inventory .trail-state/ROUND/inventory \
  --output .trail-state/review-albemarle-gis
python3 -m http.server 8010 --bind 127.0.0.1 --directory .trail-state/review-albemarle-gis
```

Open **http://localhost:8010/**. Current County geometry is cyan; eligible source geometry is magenta; held records can be shown in dashed red. Other visible editable datasets are frozen reference overlays, with protected Rivanna lines in green. The base map is Mapbox Outdoors, not a fresh rendering of the custom live style. Toggle name-based colors to inspect the captured County palette. Uploaded tilesets without editable datasets and background paths are not part of geometric comparisons.

Select a park and inspect conflicts, held records and current coverage gaps. Clicking a row fits its geometry and matches; details show coverage in both directions, property changes and overlapping datasets. Save park/feature notes, then **Export validation feedback**. The export binds the review, source, baseline, style and policy hashes. Browser notes are scoped to the review hash. They must be exported before rebuilding with different inputs. Feedback is not publication approval and has no automatic importer.

## Reading the comparison

- Coverage is line length within 3/10/20-metre buffers in EPSG:32617. Close parallel trails and junctions can match; proximity is not proof of identity or superior accuracy.
- A crosswalk suggestion requires a mutually unique same-park pair with at least 98% coverage in both directions at 3 metres and at least 98% length ratio. All suggestions have `approved=false`.
- Splits and merges generally appear as multiple partial matches. Current features with less than 98% union coverage at 10 metres, or no eligible source counterpart, are flagged. A gap can reflect displacement, segmentation, eligibility holds or missing source coverage; it is not proof that the existing map is correct or the trail is gone.
- Potential name/color/use conflicts are reported for substantial same-park overlaps. Near-identical eligible source records are flagged separately. Neither is automatically merged or deleted.
- The entire baseline is saved unmodified as `preserved.geojson`. `screened.geojson` is only a source subset and carries `ingest_report.review_only=true`; the plan builder and publisher reject it. No publication plan is emitted by this review builder.

The November 4 round captured 1,902 source records and 350 current County features. It screened 330 source records and held 1,572, with 14 unapproved identity suggestions, 125 current coverage gaps, 27 potential source color conflicts, one near-duplicate source pair and 36 eligible records overlapping other visible editable datasets. These are screening counts, not accepted edits. See [the validation audit](reviews/2026-11-04-gis-validation.json).

Review Ragged Mountain, Walnut Creek, Ivy Creek and Mint Springs carefully. Ragged has no eligible replacement records in this snapshot. Biscuit Run's 400-acre records include 46 Active/public rows explicitly marked Closed. The near-duplicate pair is Mid-Way Connector / Mid-Way Trail at Biscuit Run. None of these findings authorizes deletion, reopening, or adding closed geometry to the public map.

## November 5 color and southern geometry follow-up

[Geometry feedback](reviews/2026-11-05-geometry-feedback.json) records the user's acceptance against the exact parent review, source and baseline hashes and 330 feature IDs. Preserve that parent preview. The separate follow-up presents synchronized current/GIS panes, per-segment color explanations, optional color aliases, and the inspected 2017/May 2024 Ivy Creek maps. [Color evidence](color-evidence.json) distinguishes naming differences from route changes and records the unavailable current Walnut PDF.

```sh
uv run --with-requirements maintenance/requirements-geo.txt python -m maintenance.albemarle_followup \
  --parent .trail-state/review-albemarle-gis \
  --source .trail-state/albemarle-gis-2026-11-04/source.geojson \
  --inventory .trail-state/albemarle-gis-2026-11-04/inventory \
  --feedback pipelines/albemarle/reviews/2026-11-05-geometry-feedback.json \
  --evidence-dir .trail-state/albemarle-followup-2026-11-05/evidence \
  --output .trail-state/review-albemarle-gis/followup
```

The evidence directory must contain the inspected PDFs and rendered PNGs listed in `color-evidence.json`; the output records their hashes. With the original server running, open **http://localhost:8010/followup/**. Alias previews change display colors only. Six of the 27 original flags reflect tiny junction matches; seven are missing aliases, three use the older curated Purple name for official Field, and eleven need individual route/connector interpretation.

The frozen Biscuit pane compares existing rough reference lines with the 58 already-reviewed eligible lines and 46 southern 400-acre lines marked `Active`, `Closed`, and `Submeter` in the source. It preserves the original review, drawing those 46 separately in dashed amber; the later user access correction is recorded below. Other held lines are an independent optional overlay. A source mapping-method label does not independently establish positional accuracy. Exported color/south feedback is tied to the follow-up and original geometry feedback hashes; it is not a publication plan.

Validate with `python3 -m unittest tests.test_albemarle_followup` and `node tests/albemarle-followup-browser.mjs`. Browser checks cover both map panes, alias previews, camera synchronization, official-map images, closed southern geometry, feedback export/persistence and mobile layout.

## November 6 feedback import

The [first feedback export](reviews/2026-11-06-color-feedback.json) resolved all 14 Walnut Creek color questions: eight preserve the current color and six use the GIS name's color. The [first import audit](reviews/2026-11-06-color-feedback-import.json) records those choices. The subsequent [complete export](reviews/2026-11-06-complete-feedback.json) and [complete import audit](reviews/2026-11-06-complete-feedback-import.json) resolve all 27 color questions: ten preserve the current color, fourteen use the GIS name's color, and three use the suggested Field/Purple alias. Orange Loop uses the raw GIS name's pale-tan fallback as explicitly selected. The original comparison stays frozen.

`maintenance.albemarle_feedback` validates the review/source/style hashes, rejects unknown IDs and ambiguous preserve-current choices, and applies only explicit color decisions to per-feature `overrides.json` entries. `TrailName` retains the selected style lookup key; `name` and raw `Trail_Name` retain the GIS name. A corresponding `color` property records the reviewed value. Color import does not change geometry, grant access, choose replacement/deletion identities or publish data. Conflicting existing overrides require reconciliation instead of silent replacement.

```sh
python3 -m maintenance.albemarle_feedback \
  --review .trail-state/review-albemarle-gis/followup/review.json \
  --feedback /mnt/c/Users/meeko/Downloads/albemarle-color-and-south-feedback.json \
  --source .trail-state/albemarle-gis-2026-11-04/source.geojson \
  --style .trail-state/albemarle-gis-2026-11-04/inventory/style.json \
  --output .trail-state/albemarle-feedback-ROUND
```

Use a new output directory for each export to retain its original bytes, interpretation and review-only screened subset. Missing entries are not approval; existing overrides persist when importing another partial export. Tests: `python3 -m unittest tests.test_albemarle_feedback`.

The complete export's southern dropdown says `closed-geometry`, but its explicit note says: “Just mark it as open -- this section is open in practice even if the GIS hasn't been updated yet.” The note takes precedence. The import used `--southern-open` to record this human interpretation in `access-decisions.json`, retaining the note verbatim. Use that flag only for an explicit user instruction about access, never merely because the dropdown selected geometry. This local correction is not a claim that the County updated its GIS. The reviewed source subset now includes 330 originally eligible records plus those 46 southern records, with all 1,526 other held records still excluded.

## After validation in future rounds

Interpret the feedback into a reviewed crosswalk that handles one-to-one matches, splits, merges, additions and retained unmatched geometry explicitly. Preserve existing Mapbox feature IDs and official color associations. Prepare a full desired County dataset against a fresh inventory; compare the protected Rivanna network and existing park ownership decisions again. Only then prepare an exact publication plan for a separate user review. Do not use the City's `OBJECTID` reconciler for this migration, and do not simply remove the review-only marker from the source subset.

## Authorized November 6 replacement

The user subsequently authorized publication with “ship it.” The [complete reconciliation](reviews/2026-11-06-reconciliation.json) binds the fresh inventory, approved source, access decisions, colors, protected network hashes and every old-feature disposition. [Publication evidence](reviews/2026-11-06-publication.json) records preparation, journals and verification status.

`maintenance.albemarle_candidate` builds full County and Strava datasets from that explicit manifest. It retains all 376 accepted source geometries exactly, reuses 175 legacy IDs with substantial bidirectional route overlap, preserves 32 unmatched County features unchanged (including all 22 Ragged records), and retains uncovered tails of two more. It replaces nine rough Biscuit GPS records and trims two others while retaining their unmatched extensions. Other Strava features and the entire Rivanna network are preserved. Cut boundaries join to the replacement network; these joins and their distances are recorded in preparation evidence.

The final County candidate contains 410 features; Strava contains 559. All 27 explicit color choices remain intact. The agreed Blue Wheel blue alias also covers two displaced records with the identical route name that the original overlap screen missed. The short reviewed Mid-Way near-duplicate pair is retained, rather than silently dropping one accepted source record. No style edit is required.

Publication required a [two-record precision repair](reviews/2026-11-06-coordinate-repair.json): inverse projection put seven retained-tail vertices just below six-decimal boundaries. Derived trim coordinates are now stabilized at 12 decimals before Mapbox's six-decimal storage conversion. The repair preserved every other written record and passed the existing strict verification; the initial journal is retained and explicitly linked to the successful repair. Do not retry the original plan.

```sh
uv run --with-requirements maintenance/requirements-geo.txt python -m maintenance.albemarle_candidate \
  --source .trail-state/albemarle-gis-2026-11-04/source.geojson \
  --inventory .trail-state/albemarle-publish-2026-11-06/inventory \
  --manifest pipelines/albemarle/reviews/2026-11-06-reconciliation.json \
  --output .trail-state/albemarle-rebuild-check
```

This is a reproducibility command for the archived inputs, not permission to replay a published plan. Read current journals before any write. The publication probe `node tests/albemarle-publication-browser.mjs` checks actual public tiles across all imported parks and representative zooms 10, 14 and 16; `--fresh` changes only tile cache keys for diagnosis. It checks the original palette, reviewed colors/access, and retained Ragged geometry. For a later update, reconcile against a fresh inventory and use the persisted upstream IDs and lineage, never an old blanket replacement.

Checks: `python3 -m unittest tests.test_albemarle` (geometry cases need the optional dependencies), `python3 -m maintenance validate`, and `node tests/albemarle-review-browser.mjs` with the preview server running. The browser check saves screenshots in `test-results/` and exercises rendered overlays, conflicts, coverage gaps, feedback export, persistence and mobile layout.
