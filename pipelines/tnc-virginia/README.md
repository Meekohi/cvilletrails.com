# TNC Virginia trail review

This pipeline inventories TNC's Virginia preserves and extracts the **five explicitly reviewed GeoPDF maps**, covering Bear Loop, Ingalls Overlook, Sandy Gap, Bottom Creek Gorge, and Cumberland Marsh. Nothing is published automatically. Fortune's Cove stays in its existing pipeline.

The preserve finder embeds `mapItems`. The catalog parser selects physical Virginia locations rather than Virginia tags (which also include Kyles Ford, Tennessee). Access, URLs, locations and descriptions are monitored semantically; rotating images are ignored. Catalog pins are not trailheads, ownership polygons or hiking permission. The three selected preserve pages also monitor visitor guidance and PDF links. `discover` crawls all 25 preserve pages for future map candidates; unselected PDF links are discovery evidence only, not automatically extracted or individually monitored.

Each map manifest pins the PDF SHA256, viewport, NAD83 UTM CRS, affine control residual, named vector layer, palette, stroke width, drawing membership, segment counts and expected geographic extent. Coordinates are extracted from vector strokes, not inferred by a language model. The transform handles the ArcMap viewport's inverted vertical bounds. The residual measures fit to rounded embedded controls, **not survey accuracy**. Colors are official map symbols, not independent confirmation of painted blazes.

Bottom Creek includes its explicitly designated black walking entrance road. Black casings, preserve boundaries, legend strokes, roads without public access and neighboring Douthat paths are excluded. Path identifiers belong to these exact reviewed PDFs and must not be reassigned by drawing number after a source changes.

## Reproduce the review

Run from the repository root. `uv` provides optional dependencies without changing ordinary website/source-check requirements.

```sh
python3 -m maintenance.tnc discover --output .trail-state/tnc-discovery
python3 -m maintenance.tnc download-maps --output .trail-state/tnc-pdfs
uv run --with-requirements pipelines/tnc-virginia/requirements-review.txt python -m maintenance.tnc extract .trail-state/tnc-pdfs --output .trail-state/tnc-usfs-review
python3 -m maintenance check --pipeline usfs-gwj --state-dir .trail-state/tnc-usfs-review/source-check-usfs
cp .trail-state/tnc-usfs-review/source-check-usfs/candidates/usfs-gwj/trails.geojson .trail-state/tnc-usfs-review/usfs.geojson
cp .trail-state/tnc-discovery/catalog.json .trail-state/tnc-usfs-review/catalog.json
python3 -m maintenance inventory --output .trail-state/tnc-usfs-review/inventory
uv run --with-requirements pipelines/tnc-virginia/requirements-review.txt python -m maintenance.trail_expansion build .trail-state/tnc-usfs-review --inventory .trail-state/tnc-usfs-review/inventory --refresh-tiles
python3 -m http.server 8011 --bind 127.0.0.1 --directory .trail-state/tnc-usfs-review
```

Open http://localhost:8011/. The first view is Bear Loop. Current and proposed maps move together. Magenta highlights additions; uncheck that option to see official map colors. Cyan dashed records are held or duplicate alternatives. Orange identifies the selected source on the right and matched existing records on the left. Use area/status/search filters, decisions and notes, then **Export feedback**. “Hold shown proposals” allows the entire Forest Service batch to be deferred while retaining the TNC additions. Decisions persist locally for the exact review hash. Held records cannot be included without a follow-up resolution.

```sh
python3 -m maintenance.trail_expansion feedback .trail-state/tnc-usfs-review /path/to/tnc-usfs-feedback.json --output .trail-state/tnc-usfs-reviewed.geojson
```

The imported feedback remains review-only. Publication requires a fresh inventory, an addition-only merge into the supplemental dataset, an exact reviewed plan, the matching style/catalog proposals, explicit user authorization and the existing publication workflow. Do not pass an additions-only file as a full replacement dataset. Existing features, official colors and the entire Rivanna network must remain unchanged. `systems-proposal.json` and `style-proposal.json` are local proposals only; public files and Mapbox remain unchanged.

## Source choice and duplicate review

The review checks all 13 editable datasets, including the Appalachian Trail and older data, plus visible custom Shenandoah vector tiles near incoming lines at zoom 12. Background basemap paths are context, not editable custom trail records. Tile fragments are cached against captured tileset metadata; source/style scope changes invalidate the reference set, and `--refresh-tiles` re-downloads it. Geometry coverage uses 3/10/20/30 m buffers; nearby parallel trails can conservatively trigger a hold. No feature is silently trimmed or used to replace an existing trail.

`resolutions.json` selects TNC's complete Sandy Gap route (including the western approach and official blue map color) and holds the alternative USFS alignment. Both are bound to exact feature hashes. This is a consistent source choice, not a claim that 2020 cartography is more accurate than current GIS. FSR 125 D has a current approach-road closure notice; the review does not infer that Bear Loop itself is closed.

## Checks

```sh
uv run --with-requirements pipelines/tnc-virginia/requirements-review.txt python -m unittest discover -s tests -p 'test_*.py'
node tests/trail-expansion-browser.mjs
```

The browser test uses Playwright and a running review server, verifies rendered trail geometry, current/proposed separation, filters, official colors, batch and individual decisions, held-record guards, hash-bound exports, local persistence and mobile layout. See repository README for Playwright installation or set `PLAYWRIGHT_MODULE` and `PLAYWRIGHT_CHROMIUM_EXECUTABLE`.

## Accepted batch and source exceptions (November 7)

The user explicitly accepted the 967 proposed segments, including both TNC Sandy Gap segments. The tracked [acceptance receipt](reviews/2026-11-07-acceptance.json) records the exact review hash, accepted feature IDs, geometry hash and user's wording. This is acceptance of the reviewed batch; it is not a publication receipt. Local decision and selected-geometry artifacts are under `.trail-state/tnc-usfs-review/accepted/`. Keep the original review frozen: rebuilding it would invalidate that receipt.

The separate [source-exceptions review](http://localhost:8011/exceptions/) originally presented 305 unresolved records and the already-resolved Sandy Gap alternative. Accepted additions are immutable context. The source hierarchy and limitations are recorded in [source-preferences.json](../usfs-gwj/source-preferences.json):

- Appalachian Trail: use the maintained NPS/ATC route-wide centerline, also used by ATC's current public map. The new reference is purple on both maps and can be toggled off. The regional sample contains 892 official-route records; all 73 held USFS AT segments have at least 80% coverage within 20 m of it. A service edit timestamp does not establish a recent survey for every record.
- DCR state parks: keep the official operator GIS and verified blazes on shared park tread; examine USFS continuations separately.
- Tuscarora: the existing upload has documented 2019 PATC differential-GPS provenance. Prefer the monitorable USFS feed for confirmed National Forest Tuscarora segments while preserving verified colors; differently named routes need shared-tread review, not automatic replacement.
- Same-source/junction cases: inspect route numbers, mileposts and reciprocal geometric coverage. Two route names can legitimately share a physical trail.
- Access decisions now follow the user’s open-unless-contrary policy; explicit restrictions and closure evidence still take precedence.

The comparison shows captured existing matches in orange, selected incoming geometry in magenta, NPS/ATC reference in purple, and related incoming records in dashed teal. “Use recommendations in this group” records source preferences for that group. It does not alter geometry. Export **tnc-usfs-source-choices.json** when finished.

```sh
uv run --with-requirements pipelines/tnc-virginia/requirements-review.txt python -m maintenance.trail_exceptions build .trail-state/tnc-usfs-review --research .trail-state/tnc-usfs-exceptions-research --output .trail-state/tnc-usfs-review/exceptions
python3 -m maintenance.trail_exceptions import .trail-state/tnc-usfs-review/exceptions /path/to/tnc-usfs-source-choices.json --output .trail-state/tnc-usfs-source-preferences.json
node tests/trail-exceptions-browser.mjs
```

The research directory archives the ATC page → embedded Experience → Web Map → NPS service provenance chain, ArcGIS metadata, and regional reference GeoJSON. Reference acquisition used complete ID batches plus a repeated membership check for the WGS84 envelope `[-84, 36.4, -77.4, 39.7]`. Restore those artifacts before reproducing this exact review. Later snapshots require a new comparison, not reuse of these hashes.

Imported preferences remain review-only. The next step is a concrete bounded replacement/merge plan with all retained continuations and official colors visible. Nothing in this round deletes existing AT, state-park, NPS/PATC or Rivanna geometry.


## Confirmed exception decisions (November 7)

All 137 source preferences are now confirmed, including NPS/ATC for all AT and USFS for Tuscarora. The access review approved 139, rejected 17, and retained 12 contrary-evidence holds. Ten short connectors survived the 0.1-mile filter. Two approved Tuscarora records require replacement of existing geometry, leaving 137 new additions; combined with the frozen original 967, `accepted/combined-additions.geojson` contains 1,104 accepted additions. It is still review-only.

The [exceptions page](http://localhost:8011/exceptions/) opens on the 12 remaining holds and offers approved/rejected filters. Source choices are locked to the recorded instructions. Exports bind both confirmation receipts and cannot overwrite them. No further export is needed to confirm these decisions. Rebuilding the original review would invalidate the accepted hashes; refresh UI assets without rebuilding frozen evidence. Exact source replacements and publication remain separate from source/access acceptance.

The bounded [AT source comparison](http://localhost:8011/at/) now shows the current and NPS/ATC geometry side by side, including 15 old segments with substantial alignment differences. See the [AT adapter guide](../appalachian-trail/README.md) for scope and provenance.

## Publication completed — November 7

The approved release is published to Mapbox, including live and Studio draft styles. The [publication receipt](reviews/2026-11-07-publication.json) records exact plans, upload IDs and stored-data verification. Ordinary public tiles passed all 22 checks, including zooms 10, 12, 14 and 16 for Bear Loop, Tuscarora, a useful short connector, retained PATC geometry and the NPS/ATC centerline. DCR and Rivanna also passed preservation checks. Earlier review receipts marked unpublished remain historical evidence; this publication receipt supersedes their publication status.
