# Appalachian Trail official centerline

The user selected NPS/ATC for all AT geometry. The [source selection receipt](reviews/2026-11-07-source-selection.json) records that instruction for the 73 USFS AT exceptions. USFS normalization now excludes main AT records; it retains separately named approaches.

The [ATC interactive map](https://appalachiantrail.org/experience/interactive-map/) embeds ArcGIS Experience `c218db84e3ec430db52249797f4cff43`, using web map `f0759fe58dcb4c5f9e0f9682a41678cc`. Its AT layer is the NPS-owned [APPA Official Centerline](https://services1.arcgis.com/fBc8EJBxQRMcHlei/arcgis/rest/services/ANST_Centerline/FeatureServer/0), item `71975f7fc14347c7a6c1059fdb593f91`. The adapter selects `Status = 'Official A.T. Route'`, follows stable GlobalIDs, preserves source attributes, and retains the existing white AT styling. Service edits do not establish recent field surveys; many records have older survey dates.

`scope.json` pins the existing dataset and its actual geometry bounds. ArcGIS acquisition uses a slightly larger envelope, verified ID batches and a repeated bounded membership check. Preparation clips to the old map extent and records all clipped/out-of-scope IDs. Stale dataset metadata bounds are not used. The full replacement is review-only and does not alter other datasets or the Rivanna network.

```sh
python3 -m maintenance check --pipeline appalachian-trail --state-dir .trail-state/at-source-switch/monitor
uv run --with-requirements pipelines/tnc-virginia/requirements-review.txt python -m maintenance.appalachian_trail .trail-state/tnc-usfs-review/inventory/datasets/ck578grpj01232ipbxr2ampjj.geojson .trail-state/at-source-switch/monitor/candidates/appalachian-trail/official-centerline.geojson --output .trail-state/tnc-usfs-review/at --preview-context .trail-state/tnc-usfs-review/exceptions
node tests/at-review-browser.mjs
```

The [side-by-side comparison](http://localhost:8011/at/) shows 627 old records and 791 official records within existing coverage. Fifteen old records have less than 95% of their length within 100 m of the official reference. Select each difference or the entire coverage; orange on the right is an optional overlay of the old alignment. Geometry length changes from 547.9 to 560.2 miles, which is not evidence of new trail construction. Exact geometry hashes, clipping IDs and coverage measures are in `comparison.json`.

Existing destination: dataset `ck578grpj01232ipbxr2ampjj`, tileset `meekohi.ck578grpj01232ipbxr2ampjj-7v6dv`, source layer `Appalachian_Trail`. Publication requires a fresh inventory and exact bounded plan under the maintenance workflow. This pipeline does not publish automatically.
