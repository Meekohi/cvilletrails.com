# George Washington and Jefferson National Forest trails

The authoritative source is the Forest Service's [National Forest System Trails service](https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_TrailNFSPublish_01/MapServer/0). The query is scoped to `admin_org LIKE '0808%'`; the [official organization list](https://gacc.nifc.gov/sacc/dc/msmicc/administrative/finance/org_list%281%29.pdf) identifies 0808 as George Washington/Jefferson. Administrative scope includes forest lands in neighboring states, not only Virginia. `security_id` is not used as a geographic/administrative substitute: one returned segment has security ID 0804 but an 0808 administrative organization.

ArcGIS acquisition uses explicit object IDs, batches of 200, exact returned-ID checks and a second filtered membership query. It refuses truncation, duplicate IDs, substituted records or changing membership. A stable segment GlobalID supplies identity; `trail_cn` is shared between segments and cannot serve as a feature ID. Missing/invalid geometry is reported separately and never fabricated. All raw attributes are retained on normalized features.

The user-approved access policy is **assume open unless there is contrary evidence** (`access-policy.json`). Missing management fields or seasonal managed dates alone no longer cause a hold. Explicit hiking restrictions, discouraged hiking, decommissioned/closed names, non-terrestrial records and documented current closures remain held. `review-rules.json` records forest closure evidence; those rules apply during combined review. Alerts are monitored alongside GIS; a missing notice alone does not clear a recorded closure.

The November 7 access review approved 139 records, rejected 17, and retained 12 holds (8 Virginia Creeper, 3 Rocky Run explicitly discouraging hiking, and the old Cascades bridge spur marked for decommissioning). Rejections comprise 12 High Knob Loop records, Cascades Overlook, three tiny Deets stub fragments and isolated Round Mountain. Ten sub-0.1-mile connectors remain useful and were retained. Connectivity uses 10 m endpoint proximity and evaluates connected short components together. Short rejections are geometry-hash-bound; changed geometry returns for connectivity review. This round applies the short rule to the 168 access exceptions, preserving the previously accepted 967 segments.

Of the 139 access approvals, 137 are additions and two Tuscarora–Doll Ridge records are replacements, which must not be appended over existing PATC geometry. See the exact [access receipt](reviews/2026-11-07-access-acceptance.json) and [source preference acceptance](reviews/2026-11-07-source-preference-acceptance.json). All 137 non-access source preferences are confirmed. Main AT geometry is excluded from this adapter in favor of the dedicated NPS/ATC pipeline; AT approaches remain separate. High Knob Loop and Cascades Overlook are explicitly excluded.

Before these decisions, the November 7 source returned 1,294 records: 37 had no geometry and 160 of the remaining 1,257 had access holds before current-alert and overlap screening. These are segments, not counts of distinct trails. USFS supplies no blaze color; the proposed brown display is neutral. Existing official colors are retained wherever source data overlaps.

The adapter always emits `ingest_report.review_only`. It cannot automatically publish through the normal plan builder. Run:

```sh
python3 -m maintenance check --pipeline usfs-gwj --state-dir .trail-state/tnc-usfs-review/source-check-usfs
```

Then follow the [combined TNC/USFS review workflow](../tnc-virginia/README.md). No source-check result grants permission to replace or delete existing map data. Whole and partial overlaps are held, rather than trimming geometry and risking broken connections. The combined review also checks incoming records against each other and preserves the full existing Appalachian Trail and Rivanna datasets.

## Authorized November 7 release

The user subsequently instructed publication. `maintenance.trail_release` translates the frozen decisions into the full supplemental candidate: all 559 existing records remain unchanged, the 1,104 accepted additions retain their exact geometry, and reconciled source exceptions bring the new-record count to 1,162. Six fully shared records are represented by retained geometry and their identities in the reconciliation evidence; other routes keep distinct continuations. Alternate names and source IDs are attached to retained supplemental records where applicable. Crossings shorter than the substantive shared-run threshold are retained, and clipped ends rejoin the preferred line within the recorded tolerance.

Fifteen Tuscarora records, including the two Doll Ridge access approvals, replace approximately 41 miles of the old route. The original PATC upload has no editable dataset. `maintenance.legacy_tile_capture` locates the entire outside-park 2019 Tuscarora feature at zoom 12 and captures its geometry at zoom 16, removing tile buffers in global tile coordinates. The release retains approximately 187 miles outside the replacement intervals. This is captured tile geometry, not a new PATC survey; the original uploaded tileset remains available unchanged. The style filter excludes only the exact old route identified by trail name, outside-park location name, and GPS date. Other NPS/PATC routes, including Tuscarora inside Shenandoah, retain their original source and style. Verified blue is carried onto the USFS replacements and the retained PATC portions.

The route-replacement graph bridges gaps of at most 10 m when finding the old path; it does not rewrite unrelated old geometry. Replacement endpoints must lie within 40 m, route lengths must agree within 30%, and at least 80% of the old path must lie within 50 m of the replacement. Actual endpoint adjustments are recorded and peak at 25.9 m. DCR remains authoritative on park tread. The dedicated AT pipeline supplies the complete bounded NPS/ATC replacement.

Local exact plans, capture tiles, merge evidence, style manifest and tile/render checks are under `.trail-state/tnc-usfs-publish/`. Publication journals are under `.trail-state/publishes/`. The preparation commands are specific to this frozen round; do not replay them against the now-published data.

```sh
uv run --with-requirements pipelines/tnc-virginia/requirements-review.txt python -m maintenance.legacy_tile_capture .trail-state/tnc-usfs-publish/patc .trail-state/tnc-usfs-review
uv run --with-requirements pipelines/tnc-virginia/requirements-review.txt python -m maintenance.trail_release .trail-state/tnc-usfs-review .trail-state/tnc-usfs-publish
python3 -m maintenance.trail_release_style .trail-state/tnc-usfs-publish
# Only after both exact dataset plans have published and their journals verify:
python3 -m maintenance.trail_release_style .trail-state/tnc-usfs-publish --publish
node tests/trail-release-publication-browser.mjs
```

The style release also moves the uniquely named AT tileset to the front of the composite URL, preserving all members and every other member’s relative order. Mapbox confirmed the same layer names and a distinct vector-tile cache path. This creates one stable cache transition so legacy Tuscarora filtering does not expose cached tiles without its replacement; it adds no per-request cache-busting parameter. Do not fetch the new composite vector tiles before both uploads finish.

## Publication completed — November 7

The approved release is published to Mapbox, including live and Studio draft styles. The [publication receipt](reviews/2026-11-07-publication.json) records exact plans, upload IDs and stored-data verification. Ordinary public tiles passed all 22 checks, including zooms 10, 12, 14 and 16 for Bear Loop, Tuscarora, a useful short connector, retained PATC geometry and the NPS/ATC centerline. DCR and Rivanna also passed preservation checks. Earlier review receipts marked unpublished remain historical evidence; this publication receipt supersedes their publication status.
