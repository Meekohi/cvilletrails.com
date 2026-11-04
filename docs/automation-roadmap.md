# Toward continuous trail updates

[README](../README.md) · [Maintenance workflow](maintenance-workflow.md) · [Source research](source-research.md)

The long-term goal is a repeatable system that notices authoritative changes, proposes useful updates, preserves the map's curation, and publishes approved changes. Different source pipelines can have different levels of automation. A stable GIS feed and an ambiguous PDF map should not be forced through the same geometry importer.

The current preference is to do model-assisted review here in chat using the personal account. API review remains optional for a future unattended worker. There is no need to turn it on to use the existing maintenance tools.

## What already works

| Capability | Current state | Limit |
| --- | --- | --- |
| Scheduled official-source checks | Daily GitHub Actions workflow, snapshots, hashes, conditional requests and review artifacts | Several official web pages block automated requests; a failed fetch is not a healthy check |
| Separate pipeline folders | Source registry, ingest adapter, overrides and review instructions per pipeline | Not every registered source has a geometry importer |
| Complete ArcGIS retrieval | Explicit object-ID enumeration, batched retrieval and completeness checks | Field semantics, access permissions and historical records still need source-specific interpretation |
| Review in chat | Review packets and recorded structured assessments | An assessment is evidence, not publication authorization |
| Optional API assessment | Explicit `--llm` local invocation or manual workflow input | No scheduled API calls by default; no automatic geometry or notice approval |
| Geometry review | Current-state plans, visual before/after maps, park overlap analysis, decision exports | Some review generators are specific to the City/consolidation/Rivanna work |
| Preserve accepted decisions | Ownership policy, protected Rivanna network, connector checks, decision-aware City review | A new source or changed identity scheme needs its own reconciliation rules |
| Mapbox publication | Authorized plan hashes, backup/journal, verified writes, named MBTiles upload and recovery commands | Nontransactional remote writes; no scheduled writer |
| Public content | Sourced infoboxes and explicitly approved, dated notices | Visitor facts are static until reviewed; source changes do not rewrite the catalog automatically |
| Website deployment | Validated allowlisted build from `master` to GitHub Pages | Separate from dataset, tileset and Studio style publication |
| Post-publication checks | Dataset verification and release-specific real-browser checks | Generic ordinary/fresh multi-zoom monitoring is still future work |

## The actual scheduled workflow

[check-sources.yml](../.github/workflows/check-sources.yml) runs daily at **11:23 UTC** on the default branch, subject to GitHub's scheduler. This is 6:23 a.m. Eastern standard time and 7:23 a.m. Eastern daylight time. It can also be dispatched manually with an optional pipeline ID.

It has read-only repository permissions, a 25-minute job timeout and a shared `trail-source-check` concurrency group that does not cancel an in-progress run. It restores `.trail-state` from an Actions cache, runs the checker, and attempts to save state and upload an artifact even when the check fails. The artifact includes hidden files and has a requested 90-day retention. There is no Mapbox editing token in this job, and it does not commit, publish or send messages.

The cache is a convenience, not durable storage. Eviction or a fresh environment creates a new baseline. Archive the evidence behind accepted changes outside the cache and artifact retention window. Inspect the job result and `report.json`; the existence of an artifact does not imply every source succeeded.

The manual `llm` input defaults to false. The current workflow adds `--llm` only when that input is true **and** a repository `OPENAI_API_KEY` secret is present. If the key is missing, the workflow currently skips API review rather than failing explicitly. That deserves a clearer status before relying on unattended assessment. A local `.env.local` is not uploaded to GitHub. The repository's configured fallback model is `gpt-4.1`, overridable with `OPENAI_MODEL`; this records current configuration, not a recommendation for a future deployment.

To inspect the workflow without changing publication behavior:

```sh
gh workflow run check-sources.yml --ref master -f pipeline=city -f llm=false
gh run list --workflow check-sources.yml --limit 5
gh run view RUN_ID
gh run download RUN_ID --dir .trail-state/downloaded-run-RUN_ID
```

Inspect the artifact directory before merging it with local state. Do not overwrite a local in-progress review merely to install a newer monitor baseline.

## Proposed automation stages

These stages are a roadmap, not claims about existing implementation. Each should leave a concrete reviewable artifact and a clear failure state.

### 1. Make monitoring dependable

- Preserve durable source history and accepted evidence bundles, with a documented restore procedure.
- Track last successful fetch, repeated failures and how old the last reviewed facts are. Treat HTTP 403 and parsing failures as unknown source health.
- Prefer reliable operator GIS/download endpoints where available. Review blocked pages in a browser until a permitted, repeatable fetch method works.
- Reduce irrelevant HTML/PDF churn without hiding meaningful link, legend or map changes. Add visual PDF comparison where text alone is insufficient.
- Make requested-but-unavailable API review explicit in workflow results.

Completion means a changed source, unchanged source, new baseline and failed source are visibly different outcomes. None of them alone authorizes a map write.

### 2. Add a County GIS adapter in shadow mode

Start with one substantial park, rather than replacing the whole County layer. [The newly discovered service](source-research.md#albemarle-county-newly-discovered-gis) has 1,902 records in the captured snapshot, including inactive, future and private routes.

The adapter needs explicit field mapping, active/public filtering, park-name aliases and an identity strategy. Compare `GlobalID` and `OBJECTID` stability against existing feature IDs. Build a reviewed crosswalk rather than converting every existing trail into a deletion/addition. Preserve official-map colors and other curated properties through normalization. Unknown permissions must remain unknown.

Generate full candidates and overlap reports without publishing. Check intended routes, excluded lifecycle states, connections and boundary-crossing geometry. Preserve the entire Rivanna network and the accepted Heyward connector. Once a park's adapter is reproducible, expand with fixtures for the actual edge cases found.

### 3. Consolidate the review queue

Present source evidence, proposed visitor facts/notices and geometry changes together while keeping their decisions distinct. Carry accepted park ownership and published additions forward so already-resolved proposals do not recur. Bind decisions to the source snapshot, candidate and current inventory; mark them stale if these inputs change materially.

A future pull request can contain the proposed catalog edits and small durable decision manifests, with larger preview/evidence files in an archive. Review effort should concentrate on changed rules, closures, ambiguous geometry, connectivity and disagreements between authoritative sources. Similar-looking lines are not automatically duplicates.

### 4. Add API review only when unattended work needs it

Reuse the structured review contract and pipeline-specific instructions. Record source hashes, prompt/schema version, model configuration, assessment and uncertainty. Treat fetched documents as evidence, never as instructions to the worker. Bound retries and cost, and allow a failed model step to be resumed without refetching or publishing.

An API assessment should propose actions and cite the captured evidence. It should not invent access rules, infer reopening from an expired notice, or reconstruct precise trail geometry from an unclear PDF. Route those cases to a human/chat review. An apparently confident model response is not a replacement for the chosen publishing policy.

### 5. Introduce bounded automatic publication

Before any unattended writer is enabled, choose the classes of changes it may publish and the evidence required. Previously accepted park choices remain policy; authorization for today's exact plan does not establish a general future auto-publish rule.

Use a separate credentialed publisher that consumes approved artifacts, serializes work per dataset, checks current remote state, validates protected geometry/curation and preserves backups/journals. Separate dataset, tileset, style and website release states. Retry from recorded state instead of replaying nontransactional writes or submitting duplicate uploads.

A useful future state progression is:

```text
fetched → assessed → candidate ready → approved → dataset verified
        → upload processing → tileset ready → public cache propagation
        → ordinary public rendering verified
```

Failures and stale approvals must be explicit branches. “Upload complete” must not skip the rendering/propagation states. Routine infobox changes can use the Git/website path without touching Mapbox.

### 6. Monitor the public result

Generalize the release-specific browser checks into a probe that accepts changed feature markers and relevant locations. Check ordinary public URLs at low, middle and high zoom. If they differ, compare diagnostic fresh tiles with the same style and record response cache headers.

Distinguish publication failure, style mismatch and expected cache propagation. Keep checking ordinary URLs until the chosen acceptance criteria pass; record the observed locations/zooms instead of asserting worldwide invalidation. Add escalation for long-running failures or time-sensitive notices through a channel the user explicitly chooses.

### 7. Standardize end datasets deliberately

The user is open to standardized end datasets if the conversion is repeatable. Pipeline boundaries do not need to equal Mapbox dataset boundaries: many source adapters can feed a small set of curated publishing targets.

Define stable feature identity, provenance, route class, access status and style properties before migrating. Preserve archived originals and reviewed mappings. Generate a style migration alongside any source-layer rename, and verify current account limits before choosing a tileset layout. The 15 tilesets observed in the current composite are not evidence of a particular free-plan quota.

## State-parks follow-up

The [Virginia State Parks pipeline](../pipelines/virginia-state-parks/README.md) now supplies a second structured GIS workflow. Lake Anna was the pilot; the user subsequently accepted 492 more trails in 39 parks. Forty parks are now registered for monitoring, while three named areas and other held records remain excluded. Its conservative filters, stable GlobalIDs and per-park color policies provide a repeatable path, while actual park closures and ambiguous records still require review. Do not confuse the existence of a statewide candidate with approval to publish every park.

## Concrete next priorities

1. **Biscuit Run:** improve incomplete route coverage from current official evidence; keep its visible map limitation until the geometry is reviewed and published.
2. **County freshness:** pilot the new adapter on a large standalone park. Preddy's official 16-mile description versus roughly 11 miles in the old curated subset is a useful investigation signal, not proof that a specific route is missing. Walnut Creek, Mint Springs and Byrom are further candidates.
3. **Crozet:** review public, private and future greenway records before adding a coherent network context or route import.
4. **Source health:** resolve or explicitly track blocked County/UVA page fetches so daily jobs can be trusted as monitoring.
5. **City labels:** migrate the legacy label source after reviewing names against current line data.
6. **Time-sensitive access:** recheck Fontaine and construction notices; do not infer reopening from a date or missing source text.
7. **Generic publication probe and durable archive:** make the next update easier to verify and resume before enabling an unattended writer.

Keep the navigation-first website independent of this growing maintenance machinery. Pipeline internals belong in these tools and documents; visitors need a responsive map, clear coverage limitations and concise current information.
