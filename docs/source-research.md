# Authoritative sources and ingestion

[README](../README.md) · [Maintenance workflow](maintenance-workflow.md) · [Automation roadmap](automation-roadmap.md)

This guide records the source landscape discovered during the November 2–3, 2026 session. URLs, counts and access policies can change. The executable source registry is each `pipelines/<name>/pipeline.json`; the public visitor-fact citations live in `data/systems.json`.

## Evidence rules that protect the curation

Prefer the responsible land manager's current page, map and GIS. Use operator-specific rules over older general guides when the scope is clear. Preserve contradictions when it is not. A map's legend, route names and access symbols often require visual inspection even when the PDF has extractable text.

Treat geometry, allowed use, access status and display color as separate questions. A GIS line may be historic, private, proposed, a maintenance road or a crossing without public access. A path beside another path may be a distinct trail. A shorter official line does not automatically authorize removing an existing connector.

Record source date/version, URL, fetch/review time, evidence hash and the reasoning behind an interpretation. Distinguish direct source statements from geographic inference. Never infer reopening from a missing closure message, or a new opening from a newly fetched baseline.

## Existing pipeline capabilities

| Pipeline | Current input and behavior | Remaining interpretation |
| --- | --- | --- |
| `city` | Complete ArcGIS fetch; filters `Existing`; City-specific normalization and reviewed connection rules | New access permissions, substantive geometry, source overlap and manual exceptions |
| `albemarle` | Official pages/PDFs monitored; generic reviewed-GeoJSON normalization | Newly discovered County service needs a dedicated adapter, filtering, stable-ID strategy and review |
| `rivanna` | RTF pages, maps and KML monitored; separate KML comparison/candidate tools | KML identity crosswalk, route/event classification, closure wording and semantic additions |
| `monticello` | Operator pages and PDF monitored; generic reviewed-GeoJSON normalization | Map geometry, changed rules, current-vs-old PDF differences |
| `fortunes-cove` | Official TNC GeoPDF vectors with embedded UTM georeferencing; hash-bound extraction | Review changed PDF path identities, joins and current access; [pipeline guide](../pipelines/fortunes-cove/README.md) |
| `virginia-state-parks` | Complete DCR statewide GIS with GlobalIDs, blaze colors, uses and status; Lake Anna approved | Other parks remain in a [review queue](../pipelines/virginia-state-parks/README.md); GIS Open does not override current park closures |
| `visitor-info` | Official visitor pages/maps monitored, source-specific audiences | Chat review and manual catalog edits; its adapter rejects trail geometry |

The monitor does not recursively follow new links. Register a new map/PDF as a source after discovering it. A page that merely links a new map is not equivalent to having fetched and reviewed that map.

## Charlottesville GIS and official maps

- [City Trails, layer 177](https://gisweb.charlottesville.org/arcgis/rest/services/Public/OpenData_1_UpdateAll/MapServer/177) is the registered City geometry source.
- [City park areas, layer 178](https://gisweb.charlottesville.org/arcgis/rest/services/Public/OpenData_1_UpdateAll/MapServer/178) supports park ownership reviews and small-park infobox context.
- [City trail guide](https://www.charlottesville.gov/659/Trails) links official park information and maps.
- The exact City, Ragged and Heyward PDF URLs are in [the City pipeline](../pipelines/city/pipeline.json).

`fetch-arcgis` retrieves explicit object-ID batches and verifies membership again afterward. Do not substitute one `resultRecordCount=1000` request: the County investigation initially returned exactly 1,000 rows without an obvious transfer-limit flag, while the complete service contained 1,902.

The City adapter uses its own status vocabulary, stable IDs, field mappings and `connections.json`. Reconcile against current curated City data with the established `OBJECTID` legacy mapping. Do not assume those conventions apply to other GIS providers.

Park polygons are useful context, but not always the best viewport envelope. The City's Ragged polygon excluded part of the reservoir view, so the website retained its reservoir-wide bounds. Small City park polygons help distinguish adjacent parks; large isolated networks use broader envelopes so a title does not disappear over a lake or between trails. Neither an infobox envelope nor a display polygon grants access.

## Albemarle County: newly discovered GIS

The earlier [County source audit](../pipelines/albemarle/reviews/2026-11-02-source-audit.json) reported that no usable downloadable replacement had been established. The later [regional-network audit](../pipelines/visitor-info/reviews/2026-11-03-regional-networks.json) supersedes that finding.

| Resource | Address |
| --- | --- |
| Current public County trail view | [County Park Trails, layer 7](https://services2.arcgis.com/khVz7mitcPJHUnlM/arcgis/rest/services/County_Park_Trails_Public/FeatureServer/7) |
| ArcGIS item and description | [County Park Trails item](https://www.arcgis.com/home/item.html?id=68ea9d11952a431c9eef119ec5caf79a) |
| County park polygons | [County Parks, layer 0](https://services2.arcgis.com/khVz7mitcPJHUnlM/arcgis/rest/services/County_Parks/FeatureServer/0) |
| Operator maps and guidance | [County trails directory](https://www.albemarle.org/government/parks-recreation/trails) |

The ArcGIS organization ID is `khVz7mitcPJHUnlM`, named **Albemarle County, VA**. The public trail item owner is `AGOL_Data_Publisher`; its description identifies a read-only public view of the operational park-trail dataset. Validate ownership/organization when finding similarly named services: the search also returned student and third-party copies.

Download complete fresh snapshots:

```sh
python3 -m maintenance fetch-arcgis \
  https://services2.arcgis.com/khVz7mitcPJHUnlM/arcgis/rest/services/County_Park_Trails_Public/FeatureServer/7 \
  --output .trail-state/ROUND/county-trails.geojson
python3 -m maintenance fetch-arcgis \
  https://services2.arcgis.com/khVz7mitcPJHUnlM/arcgis/rest/services/County_Parks/FeatureServer/0 \
  --output .trail-state/ROUND/county-parks.geojson
```

These are read-only downloads, **not an approved ingest candidate**. The snapshot reviewed in this session had 1,902 features and included duplicates across lifecycle states, private trails and future connections. The 11-feature park-polygon snapshot did not include Biscuit Run. Infobox extents used named active public trail records plus applicable existing geometry; no County route refresh was published from this source.

Important schema differences:

| Current service field | Legacy curated County field / issue |
| --- | --- |
| `Trail_Name` | `TrailName`; preserve this legacy property where Studio depends on it |
| `Loc_Name` | `LocationNa`; historical and current names vary (`Byrom Park` versus full preserve name, for example) |
| `GlobalID`, `OBJECTID` | Candidate identity inputs; persistence across service republishing still needs verification |
| `Status` | Observed `Active`, `Inactive`, `Future`, `Pending`; never import them all as open trails |
| `Ownership` | Observed both `Public` and `Public Use Trail`, plus other/missing values; inspect actual values, not just coded-domain metadata |
| `Hiking`, `Biking`, `Equestrian` | May be `Yes`, `No` or null; null is not permission or a ban |
| `CREATED`, `UPDATED`, `CreationDate`, `EditDate` | Investigate which edits these represent before using them for change detection |

A dedicated adapter should select reviewed park/location aliases, exclude nonpublic and nonactive records from automatic proposals, retain excluded records in an ingest report, and preserve the existing map until correspondence is established. `Active` in GIS is not sufficient evidence to override a current construction closure. Do not pass this service straight to the current generic County adapter and publish it.

The next concrete implementation is an ID crosswalk and comparison against the current `Albemarle_County_Trails` dataset, starting with a single isolated park. Check reverse coverage, colors, trail names, line direction, endpoint joins, private crossings, splits and merges. Retain unmatched curated features until reviewed. The `GlobalID` field's existence alone does not establish long-term stability.

## Rivanna Trails Foundation

Start at [RTF maps](https://www.rivannatrails.org/Map), then follow the current official primary map, difficulty map and linked Google My Maps export. Exact registered URLs are in [the Rivanna pipeline](../pipelines/rivanna/pipeline.json).

The KML contains route folders, reference points, events, descriptions, detours and possible overlapping representations. Snapshot name/folder/geometry keys help compare one captured version; they are not trustworthy permanent trail IDs. Filter event-only layers and reference markers before route comparison.

Use `python3 -m maintenance.rivanna_compare --help` and the [README Rivanna sequence](../README.md#review-the-next-round-after-publication). The follow-up `rivanna_candidate` tool consumes an explicit interpretation manifest, rather than executing free-text review notes. New road walks received semantic IDs such as `rtf:roadwalk:ivy-railroad-detour`; those identities should survive future wording changes.

The entire current Rivanna network is protected from park consolidation and draws above overlapping park trails. An RTF source refresh is a separate review that may add or update features while preserving that route identity. The session's closure flag did not remove its underlying geometry.

## Visitor-information research lessons

These are dated research decisions, not a permanent list of current park rules. Recheck the linked operator sources in the [catalog](../data/systems.json) before editing facts.

| Network | What required care |
| --- | --- |
| Washington Park | City facility and regulations pages disagreed on 9 p.m. versus 10 p.m. closing; the snippet flags the conflict |
| Saunders–Monticello | Current operator pages allowed leashed dogs on boardwalks, superseding older map wording; boardwalk bicycle/weather rules are separate |
| Montpelier | Current operator admission requirements superseded older descriptions of free trail access |
| Wintergreen | Nature Foundation office hours are not trail hours; general community dog rules and hiking-trail guidance differ |
| UVA / O-Hill | No sufficiently clear trail-specific hours or pet policy was established; campus recreation-field rules were not generalized to forest trails |
| Ragged Mountain | Construction/access details and City-wide exception wording did not establish a precise new cycling rule |
| Mint Springs | Facility/project pages gave differing completion schedules; publish the access issue without promising a reopening date |
| Preddy Creek | Current official 16-mile network exceeded the old curated geometry's approximate mileage; an infobox is not a route refresh |
| Biscuit Run | Official signed network and access projects are newer than our verified map coverage; keep the coverage note and operator link |
| Totier Creek | Mileage differed across official documents; omit unnecessary precision and retain the clear no-swimming rule |

Summaries should be short enough to use on a phone. Hours, dogs, allowed trail uses, important access notes and a source link usually matter more than promotional descriptions. Prefer large standalone destinations when expanding coverage.

## Fetch failures and monitoring limits

The City and RTF sources generally fetched during the session. Some Monticello and County endpoints returned HTTP 403, as did UVA Hereford. The first visitor-information run established 20 successful baselines and one failed UVA fetch; the later 14-source County research check returned 403 for all direct requests tested. Search-indexed official pages supplied research evidence, but that is not equivalent to a successful automated monitor.

Save errors, keep the last good snapshot and distinguish three outcomes: changed, unchanged, and unavailable. Do not replace a blocked operator page with an unofficial source without recording the authority tradeoff. An alternative official ArcGIS endpoint can support geometry research while an operator page remains necessary for current access rules. Newer map links or altered document IDs require discovery beyond simple snapshots.

## Add or evolve a pipeline

Use a separate folder when a source has substantially different ingestion/review requirements; do not create a Mapbox dataset per folder or per infobox. The current style already composites 15 tilesets, so reuse the configured publishing targets. Fifteen is an observed style count, not a verified free-plan quota.

Each pipeline needs `pipeline.json`, `ingest.py`, `overrides.json` and `review.txt`. Pipeline IDs must match their directory; source IDs must be unique simple identifiers with HTTPS URLs and supported formats. Source-level `system_ids` must be a nonempty subset of the pipeline's systems when specified.

The transform signature is `transform(collection, config, source_id)`. Emit valid WGS84 GeoJSON with stable feature IDs and retain any source fields required by existing style expressions. The normalizer records `system_id`, `source_id`, `source_feature_id`, `source_url`, normalized `name`/`color`, and applies durable overrides last. Validate the actual field mappings; `visitor-info` is deliberately evidence-only.

Write source-specific review instructions explaining authority, status semantics, exclusions, colors, uncertainty, and whether interpretation requires chat/human judgment. Register documents individually. Give park-specific sources narrow audiences: the Biscuit Run page/map in the County pipeline now use `system_ids: ["biscuit-run"]`. Older saved review records retain their recorded audiences and need inspection before approving notices.

Run `python3 -m maintenance validate`, fetch a baseline, inspect normalization/exclusions, and exercise a change/empty/error case before relying on a new adapter. The initial import should remain a visual review against a fresh Mapbox inventory.
