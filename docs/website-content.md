# Website content, context titles and visitor information

[README](../README.md) · [Source research](source-research.md) · [Workflow](maintenance-workflow.md)

The product priority remains a fast answer to “which way do I turn?” The map, geolocation and heading/compass controls stay accessible. Extra information is available through the subtle changing title and an optional panel, rather than a large search/discovery interface over the map.

## Interaction contract

- Zooming into a configured network changes the title; zooming out returns to Cville Trails.
- Clicking the title opens its description. Merely entering an area does not open a panel.
- If a description is already open, the title, panel heading and panel content update together in a 160 ms fade.
- Automatic updates preserve map focus, reset panel scroll for the new content, respect reduced-motion settings and do not reopen a panel closed during the fade.
- Updates is an explicit separate view and is not replaced by automatic context changes.
- Trail taps resolve the local park from location and source-layer identity. A shared County or City layer alone does not identify the park.
- The report action creates an email draft; coordinates are included only after the user has enabled location tracking. The site does not provide offline map downloads or turn-by-turn routing.

These behaviors are implemented in [app.js](../assets/app.js), [data.js](../assets/data.js) and [style.css](../assets/style.css). `tests/context-panel-browser.mjs` exercises synchronized content/fades, rapid changes, focus, reduced motion, closing during a fade and the Updates view.

## Catalog fields

`data/systems.json` is a public array. Use stable IDs so notices, source audiences and future reviews keep referring to the same network.

| Field | Purpose |
| --- | --- |
| `id`, `name`, `area` | Stable identity, display name and location description |
| `bounds` | `[west, south, east, north]` in longitude/latitude |
| `source_layers` | Exact Mapbox vector source-layer names, not style layer IDs |
| `context_mode` | `area` for a focused area; `trail` also requires a matching rendered trail near the map center; absent for aggregate groupings |
| `context_title` | Optional shorter/different map title; the panel uses `name` |
| `context_min_zoom` | Minimum zoom to acquire the context, default 13 |
| `context_max_view_ratio` | Area-mode viewport/bounds area threshold, default 4; controls when a network dominates the view |
| `boundary` | Optional GeoJSON Polygon/MultiPolygon that excludes unrelated parts of a rectangle, including holes |
| `parent_ids` | Broader notice audiences, such as `albemarle` or `city` |
| `description`, `description_sources` | Concise description and the IDs of its evidence sources |
| `info_sources` | Registered `{id, label, url}` links for facts and description; HTTPS required |
| `visitor_info` | Ordered `{label, value, sources}` facts, generally Hours, Dogs, Trail use and important Access notes |
| `info_reviewed_on` | Actual review date in `YYYY-MM-DD`, not a guarantee of ongoing access |
| `url`, `source_label` | Primary official link, retained for fallback compatibility |
| `map_note` | Optional prominent coverage limitation; used for incomplete Biscuit Run mapping |
| `bounds_source`, `boundary_source` | Provenance for interface geometry, not property or access determinations |

Location selection prefers the smaller matching area when systems overlap. Trail-mode selection checks rendered line features within 60 pixels of the map center. Retaining the previous title allows a small zoom threshold reduction, a viewport-area tolerance and a bounding-box margin; polygon membership remains exact, so there is no buffered polygon-edge hysteresis. These are UI heuristics, not routing logic.

Large isolated networks use envelopes that include trailheads, between-trail views and lakes. Small urban parks use simplified polygons to avoid claiming adjacent neighborhoods. Keep generic City/County entries without `context_mode`. The Ragged Mountain reservoir-wide envelope was intentionally retained when a municipal polygon produced an unhelpful gap over the lake.

## Add an infobox

1. Research the official operator and current trail map. Add only supported visitor facts, preserving scope and source conflicts.
2. Determine its stable catalog ID, relevant parent audience and exact source-layer names from the live style/inventory.
3. Derive context bounds from reviewed geometry; record how they were derived. Prefer an area envelope for an isolated park and avoid using a shared County layer as a region-wide context trigger.
4. Add description/fact citations and a review date. Keep text concise and put consequential access limitations where a visitor will see them.
5. Register new official sources in an appropriate pipeline, with narrow source-level `system_ids`; reuse an existing monitor when its URL is already registered.
6. Record the research and context evidence under `pipelines/visitor-info/reviews/`.
7. Validate, build, and test the title/panel at a normal park overview, at trail junctions, at the edge and on a phone. Verify “Show on map” does not zoom to an unrelated network.

An existing entry such as `walnut-creek` is a better template than copying a hypothetical schema. The catalog validator checks IDs, bounds, parent references, optional polygon validity, HTTPS evidence links, date parsing and registered fact/description citations. Passing validation proves structure, not factual accuracy or usable context boundaries.

An audit used by `tests/system-info-browser.mjs` supplies `added_systems`, `preview_centers`, optional `preview_fit_bounds`/`preview_zoom`, and optional `mobile_system`. Preview centers are `[longitude, latitude]`, while a website hash is `#zoom/latitude/longitude`.

```sh
python3 -m maintenance validate
npm run build
python3 -m http.server 8000 --bind 127.0.0.1 --directory dist
# In another terminal, with Playwright/Chromium installed:
node tests/system-info-browser.mjs pipelines/visitor-info/reviews/2026-11-03-regional-networks.json
node tests/context-panel-browser.mjs
```

The browser test's supplied audit is a fixture for those particular networks; create an appropriate audit for another batch. It also exercises an existing shared-source McIntire tap. Screenshots wait for fade completion so transitional opacity is not mistaken for a low-contrast design.

## Visitor facts and temporary updates have different lifecycles

`visitor_info` belongs to the network description and stays until edited. `data/updates.json` contains explicitly approved notices with display start/expiry dates. The current construction notes in several infoboxes are reviewed static facts, not automatically expiring feed notices. Revisit them as part of source review; removal of old wording alone does not prove a trail reopened.

The monitor creates a source review with its source-level `system_ids` if configured, otherwise the pipeline's audience. The current assessment schema does not contain a separate audience per proposed notice. `approve-notice` copies the audience from the review record. Inspect and narrow it before approval; for notices with different audiences, use separately scoped reviewed records and preserve the original evidence. A source registry change does not rewrite older stored review records.

```sh
python3 -m maintenance approve-notice .trail-state/reviews/PIPELINE/REVIEW.json \
  --index 0 --reviewer YOUR_NAME \
  --starts START_WITH_TIMEZONE --expires EXPIRY_WITH_TIMEZONE
```

Use ISO timestamps with time zones, for example `2026-11-03T12:00:00Z`. Missing start or expiry dates must be resolved explicitly. The command updates the local feed; build and deploy the website separately. It does not change a trail's geometry or Mapbox closure styling.

Only approved, active, unexpired notices display. An empty feed is not an all-clear. Expiry ends display and is not proof of reopening. A park inherits broad City/County notices through `parent_ids`; it does not inherit a sibling park's closure. Selecting a parent includes its children. Map-wide relevance currently uses system bounds, not distance to a trail segment or precise closure polygon.

Descriptions, facts and notices render as text, with HTTPS source links. Do not add raw source HTML. Keep implementation details out of visitor copy unless they explain a practical limitation, such as incomplete map coverage.

## Catalog at the November handoff

There are 67 entries: 65 specific networks and two aggregate groupings. Adding an infobox does not add route geometry or change Mapbox styling. The executable catalog remains authoritative for later additions.

| ID | Network | Context | Primary official link |
| --- | --- | --- | --- |
| `rivanna` | Rivanna Trail | trail | [Operator information](https://www.rivannatrails.org/Map) |
| `ragged-mountain` | Ragged Mountain | area | [Operator information](https://www.charlottesville.gov/671/Visiting-the-Natural-Area) |
| `monticello` | Saunders–Monticello | area | [Operator information](https://www.monticello.org/visit/hiking-trails/saunders-monticello-trail) |
| `city` | Charlottesville trails | aggregate only | [Operator information](https://charlottesville.gov/659/Trails) |
| `albemarle` | Albemarle County trails | aggregate only | [Operator information](https://www.albemarle.org/government/parks-recreation/trails) |
| `ivy-creek-natural-area` | Ivy Creek Natural Area | area | [Operator information](https://ivycreekfoundation.org/overview) |
| `heyward-community-forest` | Heyward Community Forest | area | [Operator information](https://www.charlottesville.gov/facilities/facility/details/Heyward-Community-Forest-66) |
| `mcintire-park` | McIntire Park | area | [Operator information](https://charlottesville.gov/Facilities/Facility/Details/McIntire-Park-25) |
| `quarry-park` | Quarry Park | area | [Operator information](https://www.charlottesville.gov/facilities/facility/details/Quarry-Park-60) |
| `azalea-park` | Azalea Park | area | [Operator information](https://www.charlottesville.gov/Facilities/Facility/Details/Azalea-Park-5) |
| `pen-park` | Pen Park | area | [Operator information](https://www.charlottesville.gov/Facilities/Facility/Details/Pen-Park-26) |
| `washington-park` | Booker T. Washington Park | area | [Operator information](https://www.charlottesville.gov/Facilities/Facility/Details/Booker-T-Washington-Park-56) |
| `jordan-park` | Jordan Park | area | [Operator information](https://www.charlottesville.gov/Facilities/Facility/Details/Jordan-Park-11) |
| `meadow-creek` | Meadow Creek Trails | area | [Operator information](https://www.charlottesville.gov/659/Trails) |
| `uva` | UVA / Observatory Hill Trails | trail | [Operator information](https://www.fm.virginia.edu/resources/ohill-trails.html) |
| `pleasant-grove` | Pleasant Grove Park | trail | [Operator information](https://www.fluvanna.gov/parksrec/page/trails-pleasant-grove) |
| `montpelier` | Montpelier Trails | trail | [Operator information](https://www.montpelier.org/visit/trails/) |
| `wintergreen` | Wintergreen Trails | trail | [Operator information](https://tnfw.org/resources/hiking-and-walking-trails/) |
| `preddy-creek` | Preddy Creek Trails | area | [Operator information](https://www.albemarle.org/Home/Components/FacilityDirectory/FacilityDirectory/57/360) |
| `walnut-creek` | Walnut Creek Park | area | [Operator information](https://www.albemarle.org/Home/Components/FacilityDirectory/FacilityDirectory/60/360?widgetId=139) |
| `mint-springs` | Mint Springs Valley Park | area | [Operator information](https://www.albemarle.org/Home/Components/FacilityDirectory/FacilityDirectory/70/) |
| `byrom` | Patricia Ann Byrom Forest Preserve | area | [Operator information](https://www.albemarle.org/Home/Components/FacilityDirectory/FacilityDirectory/56/) |
| `chris-greene` | Chris Greene Lake Park | area | [Operator information](https://www.albemarle.org/Home/Components/FacilityDirectory/FacilityDirectory/52/33?widgetId=134) |
| `totier-creek` | Totier Creek Park | area | [Operator information](https://www.albemarle.org/Home/Components/FacilityDirectory/FacilityDirectory/59/) |
| `biscuit-run` | Biscuit Run Park | area | [Operator information](https://www.albemarle.org/Home/Components/FacilityDirectory/FacilityDirectory/36/360) |
| `highland` | James Monroe’s Highland | area | [Operator information](https://highland.org/plan-your-visit/highland-trails/) |
| `fortunes-cove` | Fortune’s Cove Preserve | area | [Operator information](https://www.nature.org/en-us/get-involved/how-to-help/places-we-protect/fortunes-cove-preserve/) |
| `lake-anna` | Lake Anna State Park | area | [Operator information](https://www.dcr.virginia.gov/state-parks/lake-anna) |

Highland was added after the initial session handoff; its [audit](../pipelines/visitor-info/reviews/2026-11-03-highland.json) records visitor rules and context evidence. Fortune’s Cove has a [dedicated GeoPDF pipeline and import audit](../pipelines/fortunes-cove/README.md).

Priority for the next expansion: substantial standalone trail destinations and the Crozet greenway network after an access review. Smaller City parks along Rivanna remain useful local contexts, but should not displace this regional coverage work.

The statewide DCR publication adds 39 basic park entries alongside Lake Anna. These provide automatic titles, official park/map links, and dated operator alerts where relevant. Detailed hours, permitted activities and recommended hikes remain future research. Context footprints are derived from accepted trails, using a 300 m buffer and a convex hull for each connected group, rather than treating a long or disconnected trail network’s whole bounding rectangle as park land. These footprints are not legal boundaries. The [publication audit](../pipelines/virginia-state-parks/reviews/2026-11-03-statewide-batch-publication.json) lists all 39 systems and source checks. Dated alert notes do not expire automatically; revisit them when official pages change.
