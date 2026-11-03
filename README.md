# Cville Trails

A map for the moment you need to know which way to turn, plus a repeatable maintenance system for the curated Charlottesville / Albemarle trail network. Mapbox Studio remains responsible for the map design. The site remains a small static application on GitHub Pages.

The map fills the screen. Location tracking, device heading where available, and compass/zoom controls stay accessible. As you focus on a configured trail network, the title changes to that network's name. Tap the title for details, or tap an individual trail. **Updates** filters reviewed notices by map area or trail system. Dates and expiry determine which notices appear. There is no invented sample news in the public feed.

Context titles use `context_mode` and optional `context_title` / `context_min_zoom` in `data/systems.json`. Small parks use their bounds and zoom; the broader Rivanna network also needs a nearby rendered trail. County and city aggregate bounds do not activate titles. A small boundary/zoom tolerance reduces flickering, and zooming out restores Cville Trails. Details never open automatically, and an open description stays on the system the user selected.

## Run locally

Python 3.12+ and Node 22+ are sufficient for local development, source checks and review. Live tileset publication additionally requires Tippecanoe and the AWS CLI (see below).

```sh
npm run build
python3 -m http.server 8000 --bind 127.0.0.1 --directory dist
```

Open http://localhost:8000. Serve `dist`, **not the repository root**, which may contain local credentials and review files. The build copies only public website files. Mapbox tiles require a network connection; this version does not provide offline maps or turn-by-turn routing.

Put credentials in the ignored `.env.local` file (see `.env.example`). The Python CLI loads it without sourcing it as shell code. The website uses only its existing public Mapbox display token. Secret tokens never belong in HTML, JavaScript, Git, or GitHub Pages artifacts.

## Repository layout

| Path | Purpose |
| --- | --- |
| `index.html`, `assets/` | Map, mobile panels, geolocation, trail details, notices |
| `data/systems.json` | Public trail-system descriptions, bounds, official links, source-layer associations |
| `data/updates.json` | Reviewed, dated public notices |
| `pipelines/<name>/` | Sources, ingest adapter, durable curation overrides, review instructions |
| `maintenance/` | Shared fetching, normalization, review, reconciliation, publishing, build tools |
| `config/mapbox.json` | Existing dataset → tileset → source-layer publishing targets |
| `config/style-contract.json` | Captured trail layers and curated color expressions from the live style |
| `.trail-state/` (ignored) | Raw snapshots, reviews, candidates, Mapbox backups, plans, publish journals |

## Check sources and review here in Codex

```sh
python3 -m maintenance check
# Or run just one pipeline/source:
python3 -m maintenance check --pipeline city --source city-gis
```

The default makes **no OpenAI API calls**. Each pipeline owns its registered authoritative URLs. The checker uses conditional requests where supported, saves content-addressed snapshots, and records changed or first-seen sources in `.trail-state/reviews/`. HTML is compared after stripping scripts/styles and normalizing text; links remain visible so changed map links can be noticed. PDFs are compared as files. Sources are not crawled recursively: register linked maps/notices explicitly. A first snapshot is a baseline, not evidence that something just changed.

For a review, ask Codex to inspect `.trail-state/report.json`, the relevant review JSON, its before/after snapshot files, and that pipeline's `review.txt`. The same packet is available explicitly:

```sh
python3 -m maintenance review-packet .trail-state/reviews/PIPELINE/REVIEW.json
# Save the chat's assessment as JSON matching the packet's result_schema, then:
python3 -m maintenance record-review .trail-state/reviews/PIPELINE/REVIEW.json .trail-state/assessment.json --reviewer Codex
```

An assessment contains `summary`, `map_change`, `uncertainties`, and proposed `notices`. Source content is evidence rather than executable instructions. A model can interpret a map legend or notice, but must not manufacture trail coordinates, dates, or access permissions. Inspect map PDFs visually as well as reading their text. Record conflicting sources and unknown dates instead of filling them in.

The optional future unattended mode is `check --llm`, with `OPENAI_API_KEY` and an optional `OPENAI_MODEL` (default `gpt-4.1`). It uses the Responses API with structured output and PDF inputs. Its assessment uses the same review artifact format. Failed API reviews remain retryable without another source change. API reviews also cannot publish.

Fetch errors are reported and make the command exit nonzero; they do not overwrite the last good snapshot or imply “no changes.” Some park websites reject automated requests. Those require an alternate authoritative endpoint or a review in the browser. The November 2026 first run successfully fetched City and RTF sources; Monticello and Albemarle web pages returned HTTP 403 from this environment.

## Per-pipeline ingestion

Each folder contains:

- `pipeline.json`: source IDs/URLs/formats, system IDs, and field mappings.
- `ingest.py`: `transform(collection, config, source_id)`, free to implement source-specific logic.
- `overrides.json`: durable manual decisions, keyed by upstream feature ID.
- `review.txt`: source-specific interpretation and review rules.

Adapters emit WGS84 GeoJSON with stable feature IDs and normalized `name`, `color`, `system_id`, `source_id`, `source_feature_id`, and `source_url` properties. Legacy properties are retained so the existing Studio expressions keep working. The normalized `color` is the official source's named color or null, not an invented display color; the Studio palette remains in the style. Missing IDs, duplicate IDs, invalid coordinates, and orphaned overrides stop ingestion.

The City pipeline fetches its official ArcGIS layer using explicit object-ID batches and checks completeness. It includes only records marked `Existing`; proposed/unknown-status and empty-geometry records are listed in its ingest report. Other folders currently monitor official documents and accept reviewed GeoJSON through their adapters. They do not yet turn PDFs into geometry automatically.

City `connections.json` holds explicit reviewed endpoint joins. The Quarry Park / Avon Yard bridge junction uses one exact shared endpoint; the rule stops ingestion if either feature disappears or their endpoints drift more than one metre apart. This preserves the reviewed connection without silently stretching geometry to accommodate a changed source. Saved user review decisions and follow-up findings live in `pipelines/city/reviews/`.

```sh
python3 -m maintenance normalize monticello path/to/reviewed.geojson --source trail-guide --output .trail-state/candidates/monticello.geojson
```

Example override (not installed as a real feature):

```json
{
  "upstream-feature-id": {
    "feature_id": "existing-mapbox-feature-id",
    "properties": {"color": "red", "TrailName": "Red"}
  }
}
```

Overrides apply last, every run. Existing manually curated geometry is backed up before edits. A source that renumbers IDs or changes its schema needs a deliberate mapping migration; do not assume row numbers identify trails.

## Reconcile and publish map data

Mapbox read access needs `datasets:list`, `datasets:read`, plus read access to the style/tilesets. Writing additionally needs `datasets:write`, `uploads:write`, and `uploads:read`. Keep this token in `.env.local`, never in the public site.

```sh
# Read-only inventory and full backups of existing datasets and style:
python3 -m maintenance inventory

# Example: combine the city import with the current curated dataset.
python3 -m maintenance reconcile \
  .trail-state/mapbox/datasets/ckuppnp9h534y23pyswjd7n1a.geojson \
  .trail-state/candidates/city/city-gis.geojson \
  --legacy-id OBJECTID --output .trail-state/candidates/city/reconciled.geojson

# Read-only comparison against Mapbox at the time of review:
python3 -m maintenance plan city .trail-state/candidates/city/reconciled.geojson \
  --evidence 'reviewed source snapshot / review reference' \
  --output .trail-state/plans/city.json
```

Reconciliation matches unique upstream IDs, retains existing Mapbox feature IDs and curated name/color properties, and preserves unmatched old features. Conflicting properties and unmatched features are reported for review. It also preserves curated coordinates when topology is identical and every coordinate differs by at most 0.000001 degrees (roughly 0.11 m), avoiding changes caused only by projection roundoff. New fields and substantive geometry edits remain in the candidate. This is a conservative first-pass merge, not proof of correct correspondence: review additions, geometry, permissions, and possible overlap with other trail datasets before accepting.

The first City comparison produced 133 additions, 10 substantive geometry edits, and retained 13 unmatched curated features. Nine reviewed geometry edits were published on November 2, 2026; the full import remains pending. The publication receipt is in `pipelines/city/reviews/2026-11-02-geometry.json`. Counts will change with upstream data. The existing City label layer uses the older `City_Trails` source layer while lines use `City_Trails_2021-10-13`; review that label migration and overlaps with dedicated park datasets before publishing the large import.

A plan embeds the complete before/after datasets, evidence reference, target, ingest report, change lists, and an approval hash. For visual review:

```sh
python3 -m maintenance review-map .trail-state/plans/city.json
python3 -m http.server 8001 --bind 127.0.0.1 --directory .trail-state/review-city
```

Open http://localhost:8001. Start with **Geometry changes**, then inspect additions, retained unmatched trails, name conflicts, and existing attribute changes. Orange is the saved current geometry; blue is the proposal. The view selector can show either version alone, and other networks stay visible to help identify duplicates. Changes to existing easement/ownership fields are separated from new metadata. The background comes from the live style; the colored before/after overlays come from the saved plan.

Record **Accept proposal**, **Keep current for now**, or **Needs discussion**, with optional notes. Browser storage is scoped to the exact plan hash. **Export decisions** saves a JSON file, including unfinished notes. It does not publish or change Mapbox. To generate a candidate containing only accepted changes:

```sh
python3 -m maintenance review-candidate .trail-state/plans/city.json \
  /path/to/city-review-decisions.json --output .trail-state/candidates/city/accepted.geojson
python3 -m maintenance plan city .trail-state/candidates/city/accepted.geojson \
  --evidence 'visual review and exported decisions' --output .trail-state/plans/city-accepted.json
```

Unreviewed, deferred, and discussion items preserve their current features; unaccepted additions are left out. Exported decisions cannot be applied to a different plan. The fresh plan still checks for intervening Studio edits before application. After reviewing the exact plan you intend to publish:

```sh
# Updates the editable dataset only:
python3 -m maintenance apply .trail-state/plans/city.json --approve FULL_APPROVAL_HASH

# Alternatively, update the dataset AND process its existing live tileset:
python3 -m maintenance apply .trail-state/plans/city.json --approve FULL_APPROVAL_HASH --publish
```

Choose one apply command; a plan cannot be reused after application. `--publish` starts the Mapbox upload and polls processing status. Without it, use Studio's export/publish control afterwards. Existing IDs and source-layer names are retained; no new tileset is created and the style is not rewritten. The current style references 15 tilesets, so routine updates must reuse those targets. Consolidating several datasets into a new standardized tileset is a separate future style migration; the normalized schema makes that repeatable.

Publishing requires **Tippecanoe** and the **AWS CLI** on PATH (`TIPPECANOE` may specify an alternate executable). These are not needed for source checks, review, or website builds. The publisher builds MBTiles with the configured source-layer name, validates the archive, stages it using short-lived credentials from Mapbox, and replaces the existing tileset. It uses zooms 0–16 (the account’s Uploads API limit) with no line simplification or feature dropping; higher map zooms overzoom those tiles. AWS account credentials are not required. Direct dataset export is deliberately avoided: the first live test produced an internal layer called `original`, incompatible with the existing style. Supplying an explicit MBTiles layer fixes this and keeps the style unchanged.

The publisher verifies the target layer, validates geometry, checks the approval hash, and refuses a dataset changed since review. It saves a complete backup and a per-write journal, paces writes below the API limit, and verifies the resulting dataset before starting tileset processing. Mapbox feature edits are not transactional: avoid simultaneous Studio editing during application. A network failure can leave a partially edited dataset; inspect `.trail-state/publishes/`. Do not blindly retry an attempted plan. Create a new plan against the current remote state, using the saved backup as the candidate to restore it. If an upload is still processing, use `python3 -m maintenance upload-status UPLOAD_ID`; an upload timeout does not mean Mapbox cancelled it.

Dataset reads use unique cache keys because the first live test returned cached data despite `Cache-Control: no-cache`. That test also established that Mapbox truncates written coordinates toward zero to six decimal places. Verification accepts the exact proposal or that specific storage conversion for written features only; all properties, feature IDs, topology and untouched features must still match. The journal records the actual stored hash.

If all feature writes completed but publication stopped, use `python3 -m maintenance resume-publish PLAN_PATH --approve FULL_APPROVAL_HASH`. This checks the original plan, backup, complete write journal and current dataset before uploading, without rewriting features. An existing upload ID is polled instead of submitting another upload. If the upload POST's outcome is unknown, it stops for inspection of recent Mapbox uploads rather than risking a duplicate submission. Partial feature writes still require reconciliation.

For a completed or failed upload whose internal layer does not match the configured layer, `resume-publish ... --repair-layer` verifies the reviewed dataset again, records the prior upload, and builds a replacement with the explicit layer name. It refuses this repair while an upload is still processing or when the expected layer is already present. Successful publication requires both upload completion and a matching layer referenced by the current style.

Tileset publication changes the map used by the existing website after Mapbox cache propagation; it does not require a website deploy. Website code and notice changes use GitHub Pages separately.

## Publish trail notices

Review each proposed notice's source, affected systems, wording, and dates. Narrow `system_ids` in the review record if its pipeline covers several systems. Missing end dates require an explicit review expiry; expiry means “stop displaying this notice,” not “the trail reopened.” Closures need rechecking before expiry.

```sh
python3 -m maintenance approve-notice .trail-state/reviews/PIPELINE/REVIEW.json \
  --index 0 --reviewer YOUR_NAME \
  --starts 2026-11-02T00:00:00Z --expires 2026-11-09T00:00:00Z
```

This writes the local `data/updates.json` feed, ready for review in Git. It does not deploy. Notices are rendered as text, linked to their official source, and filtered by date and trail-system bounds. The first version uses system-level map relevance rather than distance from an individual trail segment. GPS is used locally; the report link includes coordinates in an email draft only after the user has enabled location tracking.

## Automation and deployment

- **Validate:** tests and an allowlisted website build on pushes and pull requests. Uploads a website preview artifact.
- **Check authoritative trail sources:** daily snapshots and review artifacts, with no OpenAI API calls by default. Manual runs can opt into the API reviewer. The workflow has read-only repository permissions and no Mapbox editing token. It never publishes or messages anyone.
- **Deploy website:** manual GitHub Pages deployment of the validated `dist/` artifact. Select **GitHub Actions** as the Pages source in repository settings before using this workflow. The prior branch-based deployment remains whatever is currently configured until that setting is changed.

The source-check workflow retains snapshots/reviews in an Actions cache and a 90-day artifact. Cache eviction creates a fresh baseline, not a deletion. Archive important evidence and accepted review decisions outside that retention window. Workflows are supplied in the repository but do not run until pushed to GitHub. An optional future API reviewer requires a repository `OPENAI_API_KEY` secret; local `.env.local` is never uploaded. There is no scheduled production writer in this first version.

## Verify

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
npm test
npm run check
npm run build
```

Optional browser smoke test: install Playwright/Chromium in your development environment, then run `npm run test:browser`. It exercises the actual Mapbox page, mock device geolocation, automatic network titles, click-title details, updates, keyboard close, desktop layout, and exclusion of `.env.local` from the served build. With the City review page running on port 8001, `node tests/review-browser.mjs` checks overlays, filtering, decisions, notes, export, and persistence. `PLAYWRIGHT_MODULE` and `PLAYWRIGHT_CHROMIUM_EXECUTABLE` can select an existing installation. Real device heading and outdoor GPS accuracy still need a phone check.

## API references

[Mapbox legacy datasets](https://docs.mapbox.com/help/glossary/dataset/) remain accessible via the [Datasets API](https://docs.mapbox.com/api/maps/datasets/). The publisher uses the [Uploads API's staged-file upload](https://docs.mapbox.com/api/maps/uploads/); new tiling architecture should consider MTS separately. [Geolocation controls](https://docs.mapbox.com/mapbox-gl-js/api/markers/) document tracking and heading behavior. Optional API reviews use [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) and [PDF file inputs](https://developers.openai.com/api/docs/guides/file-inputs).
