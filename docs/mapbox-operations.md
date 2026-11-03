# Mapbox publication, caching and website deployment

[README](../README.md) · [Workflow](maintenance-workflow.md) · [Dated cache evidence](evidence/2026-11-03-mapbox-cache.json)

## Four distinct things can be current or stale

| Component | Role | How it changes |
| --- | --- | --- |
| Editable Mapbox dataset | Feature identities, properties and geometry edited in Studio/API | Dataset writes |
| Tileset | Tiled geometry delivered to the map | Upload/export and tile processing |
| Studio style | Source references, colors, layer order, labels and visibility | Separate live/draft style changes |
| Website | HTML, scripts, infobox catalog and dated notices | GitHub Pages deployment of `dist/` |

Editing a dataset does not itself rebuild its tileset. A new website deploy does not refresh a Mapbox tileset. An infobox addition does not establish that all its trails are mapped. A complete upload says processing succeeded; it does not mean every browser and CDN edge has discarded previous tiles.

The current Mapbox owner/style and publishing targets live in [config/mapbox.json](../config/mapbox.json). The style is `meekohi/ckkolybrr6tjx17mjqflqw16b`. Read the config rather than copying target IDs into an ad hoc upload script. [config/style-contract.json](../config/style-contract.json) records the captured curation expressions; review a deliberate style migration against the actual live and draft styles as well.

## Credentials and publication dependencies

Keep the private maintenance token in ignored `.env.local`. Read-only inventory uses dataset-list/read and relevant style/tileset read access. Data publication additionally needs dataset writes and upload read/write access. The specialized style publishers also need style-write access. The website uses its public display token; private maintenance credentials must not enter browser code, documentation, command output or the served build.

The publisher requires Tippecanoe and AWS CLI. Mapbox supplies temporary staging credentials; the code gives them only to the staging subprocess. A separate AWS account credential setup is not required. Do not archive or print staging secrets.

## Why we publish explicitly named MBTiles

During the first live test, the export/upload produced an internal vector layer named `original`. The existing style expected `City_Trails_2021-10-13`, so a successful upload was not sufficient to make it display correctly. A subsequent attempt also encountered the account's maximum tile zoom of 16.

The current [tile builder](../maintenance/tiles.py) therefore:

1. Writes the reviewed full GeoJSON candidate.
2. Runs Tippecanoe with the configured source-layer name, minimum zoom 0 and maximum zoom 16.
3. Disables line simplification, feature limits and tile-size limits for these curated datasets.
4. Verifies the MBTiles contains the expected internal layer and nonempty tile data.
5. Uploads that archive into the existing target tileset.

Map views above zoom 16 overzoom the available tiles. This does not mean the style must hide the trails above 16. If datasets become much larger, revisit tile size/performance explicitly; do not silently drop routes to make publication pass.

Reuse current dataset/tileset/source-layer identities for routine work. A future consolidated standard format is possible, but changing source-layer names or moving features between tilesets needs a reviewed style migration. The observed style composites 15 tilesets; do not treat that count as a verified account quota.

## Publication sequence

1. Take a fresh inventory and prepare a full candidate against it.
2. Generate a plan; review before/after geometry, properties, deletions, curation and protected networks.
3. Apply the exact authorized plan with its full `approval_hash`.
4. Verify the stored dataset and retain the write journal/backup.
5. Start or resume publication of the existing tileset; wait for upload completion and validate the expected layer.
6. Publish any separately reviewed style changes only when their replacement data is ready.
7. Check ordinary public rendering and a diagnostic fresh request if needed, at several zooms.
8. Record whether caches still differ; do not label a fresh-only result as universal propagation.

```sh
python3 -m maintenance plan TARGET .trail-state/ROUND/candidate.geojson \
  --evidence 'reviewed source and decision references' \
  --output .trail-state/ROUND/accepted-plan.json
# Remote write: use only the exact authorized plan/hash.
python3 -m maintenance apply .trail-state/ROUND/accepted-plan.json \
  --approve FULL_APPROVAL_HASH --publish
python3 -m maintenance upload-status UPLOAD_ID
```

`apply` without `--publish` changes the editable dataset only. Do not then run `apply --publish` on the same already-attempted plan. If its writes completed, use `resume-publish` after inspecting its journal.

The verification code accounts for observed Mapbox storage behavior: written coordinates may be truncated toward zero to six decimal places. It accepts the exact proposal or that specific conversion for written features; unrelated properties, IDs, topology and untouched features must still agree. It records the actual stored hash. This is not a general tolerance for arbitrary geometric drift.

Dataset reads use unique cache keys because the API returned stale data even with a no-cache request header during the initial publication. Do not add those arbitrary parameters to the Styles API: it rejects unknown parameters. Treat dataset read freshness, style retrieval and vector tile caching as different interfaces.

## Failure and recovery

Mapbox feature writes are not a transaction. Avoid simultaneous manual Studio edits during application.

| Observed state | Action |
| --- | --- |
| Some feature PUT/DELETE requests completed | Inspect the journal and current remote state; reconcile and create a new plan, or a reviewed restoration plan from the backup |
| All writes verified, upload not started | `resume-publish PLAN --approve HASH` verifies the prior write record and current data before uploading |
| Saved upload ID is still processing | Poll that ID; a local timeout did not cancel it |
| Upload submission outcome is unknown | Inspect recent uploads and the journal; do not blindly submit a second upload |
| Upload failed or completed with the wrong internal layer | Inspect layer metadata; `resume-publish … --repair-layer` is available for the narrowly checked mismatch case |
| Correct tiles and style under a fresh request, ordinary URL still old | Record cache propagation; repeated publication does not purge the CDN |
| Style write stopped after one version | Inspect live and draft styles plus the style journal before retrying; preserve unrelated draft work |

```sh
python3 -m maintenance resume-publish .trail-state/ROUND/accepted-plan.json \
  --approve FULL_APPROVAL_HASH
# Only for the checked completed/failed upload with an incompatible source layer:
python3 -m maintenance resume-publish .trail-state/ROUND/accepted-plan.json \
  --approve FULL_APPROVAL_HASH --repair-layer
```

A rollback is also a new reviewed change against the current dataset. Use the backup as candidate input and verify what would be removed or restored. Keep the original attempted plan and journal; never erase the evidence to make the publisher accept a replay.

## Live style and Studio draft are separate

The park consolidation hid the two obsolete `Ragged_Mountain_Trails` line layers while retaining their archived dataset. The old four GPS tracks were inside Heyward; this did not remove the Ragged Mountain park or its County trails. Do not upload an empty replacement merely to retire a display layer.

`retire-style-layers MANIFEST --approve MANIFEST_HASH` verifies replacement publications and protected data, backs up live/draft styles and limits its changes to the reviewed layer visibility edits.

The Rivanna publication similarly used `python3 -m maintenance.rivanna_publish PLAN PREVIEW --approve PROPOSAL_HASH` after dataset publication. It changed only the three Rivanna display layers to show the reviewed Fontaine closure, kept the active detour and preserved unrelated Studio draft edits. `proposal_hash` is not the dataset plan's `approval_hash`.

The entire Rivanna layer draws above other trail networks, even when routes overlap. The old City label source remains a known follow-up: `City_Trails` supplies labels while `City_Trails_2021-10-13` supplies updated lines. Old text labels can therefore be a source mismatch rather than a tile-cache problem.

## Diagnose old data at one zoom and new data at another

During the November session, a fresh browser reproduced this exact symptom. Ordinary public requests at zoom 10 lacked the new Fontaine closure status and road walks; zooms 12, 14 and 16 had them. Adding a unique query key to v4 tile requests, with the same public style, returned current data at zooms 10 and 11. See the [sanitized evidence record](evidence/2026-11-03-mapbox-cache.json).

The observed composite tile responses had:

```text
Cache-Control: max-age=43200,s-maxage=7200,stale-while-revalidate=300,stale-if-error=600
Age: 7044
X-Cache: Hit from cloudfront
```

That observation means a 12-hour browser lifetime and a two-hour shared-cache lifetime for those responses; the sampled old zoom-10 tiles were about 117 minutes old. A fresh diagnostic request was a cache miss and contained the update. These are observed headers, not a promise that every Mapbox endpoint or edge has the same lifetime. The [Mapbox caching guide](https://docs.mapbox.com/help/dive-deeper/api-caching/) explains the separate device/CDN caches and notes that the CDN cannot be explicitly invalidated.

Repeat the investigation in this order:

1. Verify the correct website is deployed and inspect the live style's source references, filters, visibility and zoom settings.
2. Confirm the editable target contains the expected IDs/properties/geometry, and its saved upload reports `complete: true` without an error.
3. Pick a distinctive change: a new semantic ID, route property or named closure. Inspect the same location at low, middle and high zoom using ordinary public tile requests in a new browser context.
4. Inspect the vector responses' cache headers. Different zooms use different tile keys; some may have been cached before the upload and others afterward.
5. Compare a temporary unique-query tile request, keeping the style and location constant. Check feature properties as well as appearance. A cached old style is a separate variable; investigate it separately if needed.
6. If fresh tiles are current and ordinary tiles are old, record cache propagation instead of rebuilding the dataset. If both are wrong, investigate the uploaded tileset, source layer, geometry and zoom behavior.
7. Recheck ordinary URLs later. A private window clears the browser-cache variable but can still receive stale CDN tiles. A hard reload is not a CDN purge.

Do not put a random cache-busting parameter on every production tile request. Normal caching is important for mobile speed, bandwidth and map costs. A deliberate publication-version strategy could be evaluated later, with measurements and propagation checks.

The existing historical verification command is:

```sh
# Requires the saved Rivanna plan, proposal and a built site served on port 8000.
node tests/rivanna-publication-browser.mjs
node tests/rivanna-publication-browser.mjs --fresh
```

That script checks the November proposal's nine relevant features and closure style; its `--fresh` mode also requests an unoptimized style. It is not an isolated comparison of just one cache variable, nor a complete generic multi-zoom release test. The later recorded investigation held the style constant while changing only the tile query key. For another release, adapt the target markers/zooms and retain both ordinary and diagnostic results. [A generic publication probe is still planned](automation-roadmap.md).

## Website deployment is a separate release

The public site is GitHub Pages at [cvilletrails.com](https://cvilletrails.com/), using **GitHub Actions** as the Pages build source. The deployment branch is `master`, configured by [deploy.yml](../.github/workflows/deploy.yml). Pushing another working branch does not publish it. Manual workflow dispatch is also available and should target the intended ref.

The old Calendar button persisted earlier because the website was not deploying the updated branch/build. The fix was to deploy the validated allowlisted `dist/` artifact from `master`, retaining the custom domain and HTTPS. Treat old application controls as a website deployment/cache question before attributing them to Mapbox tiles.

```sh
python3 -m maintenance validate
npm run build
python3 -m http.server 8000 --bind 127.0.0.1 --directory dist
# After reviewing and committing the intended changes:
git push origin master
gh run list --branch master --limit 5
gh run watch RUN_ID --exit-status
```

The builder copies only `index.html`, `CNAME`, `assets/`, the two public data JSON files and `.nojekyll`. Documentation, source snapshots, maintenance code, private tokens and review exports are not website assets. Never point Pages or a local public server at the repository root to work around a build issue.

After the correct deployment completes, compare the served `assets/app.js`, `assets/style.css` and `data/systems.json` with the local build, then perform the relevant public browser check. Git commit success and a green source-check job are not substitutes for a successful Pages deployment.
