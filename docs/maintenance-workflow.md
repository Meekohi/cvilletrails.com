# Repeatable trail maintenance workflow

[README](../README.md) · [Source research](source-research.md) · [Mapbox operations](mapbox-operations.md) · [Session record](session-2026-11-02.md)

This is the procedure for the next maintenance session. Examples run from the repository root. Replace `ROUND`, `REVIEW.json`, `DECISIONS.json` and approval-hash placeholders with the actual files for that round. Historical files are examples of evidence, not permission to replay an old publication.

## Resume with the right state

```sh
git status --short
git log -8 --oneline
python3 -m maintenance --help
python3 -m maintenance validate
```

Read the latest tracked audit in the relevant `pipelines/<name>/reviews/` directory, the current [park ownership policy](../config/park-ownership.json), and the last local publication journals. Check whether the user has edited Studio since the previous session. Existing user authorization and curation decisions should carry forward; new geometry still needs a concrete review against current data.

A fresh clone has code, policies, public content and tracked audits. It does not have raw source snapshots, complete Mapbox inventories, full plans, local previews or ignored publication journals. Restore those from the archived round before resuming a historical review. If they are unavailable, take a new inventory and build a new review; do not recreate an old approval from its hash alone.

Dependencies:

| Work | Requirements |
| --- | --- |
| Source checks, normalization, reviews, build | Python 3.12+; Node 22+ for JavaScript checks |
| Overlap analysis and consolidation | `uv run --with-requirements maintenance/requirements-geo.txt python …`, or install those pinned packages in a virtual environment |
| Real browser checks | Playwright and Chromium; `PLAYWRIGHT_MODULE` and `PLAYWRIGHT_CHROMIUM_EXECUTABLE` can select an installation |
| Live tileset publication | Tippecanoe and AWS CLI on PATH; `TIPPECANOE` can override its executable |
| GitHub workflow inspection | GitHub CLI authenticated to the repository, or the Actions web interface |

Use `.env.example` as a template for ignored `.env.local`. The maintenance CLI loads it as data. Do not source it as shell code, put secrets in command arguments, or serve the repository root. Review in chat uses the current interactive account; an OpenAI API key is optional and is not needed for the normal workflow.

## 1. Capture source evidence and current map data

```sh
python3 -m maintenance check --pipeline city --source city-gis
python3 -m maintenance inventory --output .trail-state/ROUND/inventory
```

`check` writes `.trail-state/report.json`, a manifest, source snapshots, pending reviews and supported candidate GeoJSON. Use `--state-dir .trail-state/ROUND/source-state` when a deliberately separate baseline is needed. Normally retain the existing state directory so comparisons have history. Every check updates `report.json`; archive the report relevant to a decision before the next check overwrites it.

Read errors first. A 403, timeout, malformed document or incomplete ArcGIS response must not be interpreted as an unchanged source or an empty trail network. Successful fetches may coexist with errors. An initial `baseline` is not proof of a newly opened trail or a recent closure.

The inventory is read-only and captures editable datasets, their metadata, style references and tileset metadata. A proposal must use the inventory it was compared against. Inventories and source candidates are separate inputs.

## 2. Review evidence in chat

```sh
python3 -m maintenance review-packet .trail-state/reviews/PIPELINE/REVIEW.json
python3 -m maintenance record-review \
  .trail-state/reviews/PIPELINE/REVIEW.json \
  .trail-state/ROUND/assessment.json --reviewer Codex
```

Ask the model to inspect the packet, before/after snapshots and `review.txt`; visually inspect maps as well as extracting their text. Save an assessment matching the packet's schema. `record-review` validates and attaches it, but does not apply geometry, approve a notice or publish anything.

Classify each finding:

| Finding | Next artifact |
| --- | --- |
| Hours, dogs, admission, operator links | Edit `data/systems.json` with per-fact citations and a review date |
| Time-sensitive closure/access notice | Proposed notice with affected systems, evidence and explicit display dates |
| New or changed trail geometry | Reviewed source geometry → full candidate → Mapbox plan |
| A duplicate across datasets | Park ownership comparison, including retained exceptions and cross-boundary pieces |
| Conflicting or incomplete evidence | Recorded uncertainty and follow-up; preserve the existing data unless a change is specifically justified |

Missing source content is not proof of deletion or reopening. New text on a fetched page may be navigation, an old event or a different park. Search-indexed official text can help when the site blocks direct requests, but record that limitation and do not claim a successful automated snapshot.

## 3. Normalize and reconcile a full candidate

For the established City adapter:

```sh
python3 -m maintenance reconcile \
  .trail-state/ROUND/inventory/datasets/ckuppnp9h534y23pyswjd7n1a.geojson \
  .trail-state/candidates/city/city-gis.geojson \
  --legacy-id OBJECTID \
  --output .trail-state/ROUND/city-reconciled.geojson
python3 -m maintenance plan city .trail-state/ROUND/city-reconciled.geojson \
  --evidence 'source snapshot and review references for this round' \
  --output .trail-state/ROUND/city-plan.json
```

The candidate is the **entire desired target dataset**, not merely a collection of new lines. A plan compares the whole before/after state, so omitted existing features can become deletions. The conservative reconciler retains unmatched old features, stable Mapbox IDs and curated name/color fields; inspect its conflict report rather than assuming every match is correct.

Preserve the official color semantics and legacy properties used by Studio expressions. A `color` string in normalized GeoJSON is not a replacement for reviewing the Studio palette. Do not reuse the City's `OBJECTID` mapping for the newly discovered County schema without a reviewed crosswalk.

## 4. Choose the correct visual review

| Review | Command | Decision meaning |
| --- | --- | --- |
| Individual additions/geometry changes | `review-map`, then `review-candidate` | Accept a specific feature proposal, keep current, or discuss |
| Competing sources for a park | `review-parks` | Preferred dataset; does not itself approve deletions |
| Concrete cross-dataset consolidation | `prepare-consolidation`, then `review-consolidation` | Inspect the actual clipped candidates and layer retirements |
| Remaining additions after consolidation | `review-next-areas`, then `remaining-addition-candidate` | Explicitly include a new line, keep existing map, or discuss |
| Official Rivanna source update | `maintenance.rivanna_compare`, then `maintenance.rivanna_candidate` | Interpret source review into an explicit action manifest |

The [README](../README.md#compare-overlapping-datasets-by-park) contains the detailed park and Rivanna command sequences. These exports have distinct kinds and hashes; they are not interchangeable.

For a plain feature review:

```sh
python3 -m maintenance review-map .trail-state/ROUND/city-plan.json
python3 -m http.server 8001 --bind 127.0.0.1 --directory .trail-state/review-city
```

In another terminal, serve the built website on 8000 if needed. The preview's live background is for orientation; its before/after overlays are the saved review proposal. Export decisions before closing or rebuilding the preview. Browser local storage is convenience state, scoped to the review hash, not the durable decision record.

If the export is in Windows Downloads, provide the actual accessible path. In WSL that may be `/mnt/c/Users/meeko/Downloads/city-review-decisions.json`; verify the mount instead of assuming that path exists everywhere. Copy the export into the round's archived evidence and retain the original wording of notes.

```sh
python3 -m maintenance review-candidate .trail-state/ROUND/city-plan.json \
  /path/to/city-review-decisions.json \
  --output .trail-state/ROUND/city-accepted.geojson
python3 -m maintenance plan city .trail-state/ROUND/city-accepted.geojson \
  --evidence 'saved decision export and reviewed exceptions' \
  --output .trail-state/ROUND/city-accepted-plan.json
```

Check the fresh plan before publishing. If remote data changed, rebuild the review against that state. If part of a historic review was already published, use `review-resolution-context` with the relevant park audit and every later `--published-additions` audit, in order. Its current inventory must match the most recent publication. This prevents accepting an old proposal from restoring removed duplicates or overwriting new Studio edits.

## 5. Apply and verify the exact approved plan

The next command writes Mapbox data and its existing tileset. Run it only for the plan the user has authorized:

```sh
python3 -m maintenance apply .trail-state/ROUND/city-accepted-plan.json \
  --approve FULL_APPROVAL_HASH --publish
```

Wait for upload completion; verify the dataset and source-layer identity. Coordinate any separately reviewed style change after its replacement data is ready. See [publication and recovery](mapbox-operations.md#publication-sequence).

Test the affected area from ordinary public tiles at low, middle and high zoom, including boundaries and the exact changed junctions. A local GeoJSON preview is not proof that the live tiles updated. Keep upload success, stored-data verification, style verification and ordinary-cache visibility as separate results.

## 6. Publish website content and preserve the handoff

```sh
python3 -m maintenance validate
python3 -m unittest discover -s tests -p 'test_*.py'
npm test
npm run check
npm run build
```

Install the optional geo dependencies when testing geometry tools; otherwise some Python tests skip. Use relevant browser tests for interaction changes, not every historical preview test for every edit. Commit the intended content and audit files, then push `master` when publishing the website is authorized. See [deployment](mapbox-operations.md#website-deployment-is-a-separate-release).

## Artifacts and approval boundaries

| Artifact | Meaning | Does not mean |
| --- | --- | --- |
| Source snapshot / hash | What the source said at a time | All routes are open or current |
| Chat/API assessment | Structured interpretation of evidence | Permission to write Mapbox |
| Browser decision export | User choices for a particular review hash | Acceptance of another proposal or later source version |
| Ownership policy | Persistent source preferences and exceptions | Permission to erase all overlapping Rivanna lines |
| Candidate | Desired full data prepared locally | Published data |
| Plan + `approval_hash` | Exact before/after target and evidence | Remote state can no longer change |
| Publication journal / receipt | What writes and upload actually completed | All browser/CDN caches contain the new tiles |
| Website commit + successful Pages run | Public app/content release | A separate Mapbox tileset was republished |

The CLI hash is a guard against applying the wrong plan. Possessing a hash is not a substitute for the user's authorization of the concrete change.

## Archive a completed or paused update

Preserve the following outside the ephemeral working environment:

- Source snapshots, source URLs, timestamps, fetch errors and manifest/report files.
- The exact baseline inventory and any live/draft style backups.
- Original decision exports, review bundles, interpretations, ownership-policy version and overrides.
- Full proposed/accepted plans, their hashes, candidates, publication journals and upload IDs.
- Public rendering checks, cache observations and unresolved questions.
- A concise tracked audit under `pipelines/<name>/reviews/` linking the evidence by stable IDs/hashes.

Archive `.trail-state/` or the complete referenced subset in an appropriate private backup; do not include `.env.local` or secret credentials. Inspect contents before sharing. Tracked audit summaries often refer to ignored files and cannot replace those full recovery inputs. Source-check Actions artifacts last 90 days under the current workflow; the Actions cache is not permanent storage. A snapshot regenerated later is new evidence, even if its filename looks familiar.

## Prompt for the next session

> Read README.md, docs/maintenance-workflow.md, docs/session-2026-11-02.md and the current pipeline policies. Inspect Git state and the latest source/publication artifacts. Check the authoritative sources for [network], review differences here without OpenAI API calls, and prepare a concrete visual review. Preserve official colors, existing curated feature identities and the entire Rivanna network. Reuse existing Mapbox targets. Identify what is already published so old proposals cannot restore superseded geometry. Record source gaps and uncertain access. Continue within the authorization I give for the reviewed result, then verify uploads, both relevant style versions, ordinary tiles at multiple zooms, and the website release separately.
