import argparse
import json
import sys
from pathlib import Path
from .common import ROOT, STATE, configs, load_env, read_json, write_json
from .ingest import run_adapter, fetch_arcgis
from .monitor import check
from .mapbox import Mapbox, inventory, make_plan, apply_plan, resume_publish, target_by_id
from .site import approve_notice, build_site, validate_updates
from .review import review_packet, record_review
from .reconcile import reconcile
from .review_map import build_review, reviewed_candidate


def main():
    load_env()
    parser = argparse.ArgumentParser(description='Cville Trails maintenance tools')
    commands = parser.add_subparsers(dest='command', required=True)
    monitor = commands.add_parser('check', help='Snapshot sources and prepare reviews; never publishes')
    monitor.add_argument('--pipeline')
    monitor.add_argument('--source')
    monitor.add_argument('--llm', action='store_true')
    monitor.add_argument('--state-dir', type=Path, default=STATE)
    ingest = commands.add_parser('normalize', help='Normalize a source GeoJSON using pipeline field mappings and overrides')
    ingest.add_argument('pipeline')
    ingest.add_argument('input', type=Path)
    ingest.add_argument('--source', required=True)
    ingest.add_argument('--output', type=Path, required=True)
    merge = commands.add_parser('reconcile', help='Match upstream IDs while retaining curation and missing features')
    merge.add_argument('baseline', type=Path)
    merge.add_argument('candidate', type=Path)
    merge.add_argument('--legacy-id', required=True)
    merge.add_argument('--keep', nargs='+', default=['color', 'TrailName', 'NAME', 'Name', 'name'])
    merge.add_argument('--output', type=Path, required=True)
    inv = commands.add_parser('inventory', help='Read and back up all existing Mapbox datasets and the current style')
    inv.add_argument('--output', type=Path, default=STATE / 'mapbox')
    fetch = commands.add_parser('fetch-arcgis', help='Save a complete ArcGIS layer as WGS84 GeoJSON for analysis')
    fetch.add_argument('url')
    fetch.add_argument('--output', type=Path, required=True)
    plan = commands.add_parser('plan', help='Compare a full candidate dataset with live Mapbox data')
    plan.add_argument('target')
    plan.add_argument('candidate', type=Path)
    plan.add_argument('--evidence', required=True)
    plan.add_argument('--output', required=True, type=Path)
    apply = commands.add_parser('apply', help='Apply an exact reviewed plan; optionally publish its existing tileset')
    apply.add_argument('plan', type=Path)
    apply.add_argument('--approve', required=True, help='Full approval_hash from the reviewed plan')
    apply.add_argument('--publish', action='store_true')
    resume = commands.add_parser('resume-publish', help='Verify completed writes and resume tileset publication without rewriting features')
    resume.add_argument('plan', type=Path)
    resume.add_argument('--approve', required=True)
    resume.add_argument('--repair-layer', action='store_true', help='Replace a completed incompatible upload with the explicitly named source layer')
    upload = commands.add_parser('upload-status')
    upload.add_argument('upload_id')
    notice = commands.add_parser('approve-notice', help='Add a reviewed LLM draft to the local website feed')
    notice.add_argument('review', type=Path)
    notice.add_argument('--index', type=int, required=True)
    notice.add_argument('--reviewer', required=True)
    notice.add_argument('--starts')
    notice.add_argument('--expires')
    packet = commands.add_parser('review-packet', help='Print a source-change packet for review in this chat; no API call')
    packet.add_argument('review', type=Path)
    record = commands.add_parser('record-review', help='Attach a structured chat assessment to a source-change record')
    record.add_argument('review', type=Path)
    record.add_argument('assessment', type=Path)
    record.add_argument('--reviewer', required=True)
    visual = commands.add_parser('review-map', help='Build a local visual comparison and decision recorder')
    visual.add_argument('plan', type=Path)
    visual.add_argument('--overlaps', type=Path)
    overlaps = commands.add_parser('compare-overlaps', help='Screen City additions and geometry changes against a saved Mapbox inventory')
    overlaps.add_argument('plan', type=Path)
    overlaps.add_argument('--inventory', required=True, type=Path)
    overlaps.add_argument('--output', required=True, type=Path)
    parks = commands.add_parser('review-parks', help='Build a separate park-level dataset ownership review')
    parks.add_argument('plan', type=Path)
    parks.add_argument('--inventory', required=True, type=Path)
    parks.add_argument('--boundaries', required=True, type=Path)
    parks.add_argument('--overlaps', required=True, type=Path)
    parks.add_argument('--output', type=Path, default=STATE / 'review-parks')
    consolidation = commands.add_parser('prepare-consolidation', help='Prepare park ownership candidates without publishing; protected networks are retained in full')
    consolidation.add_argument('plan', type=Path)
    consolidation.add_argument('--review', required=True, type=Path)
    consolidation.add_argument('--decisions', required=True, type=Path)
    consolidation.add_argument('--policy', type=Path, default=ROOT / 'config/park-ownership.json')
    consolidation.add_argument('--inventory', required=True, type=Path)
    consolidation.add_argument('--output', required=True, type=Path)
    preview = commands.add_parser('review-consolidation', help='Preview prepared geometry using the live style and intact Rivanna overlay')
    preview.add_argument('manifest', type=Path)
    preview.add_argument('--review', required=True, type=Path)
    preview.add_argument('--policy', type=Path, default=ROOT / 'config/park-ownership.json')
    preview.add_argument('--inventory', required=True, type=Path)
    preview.add_argument('--output', required=True, type=Path)
    retirement = commands.add_parser('retire-style-layers', help='Hide reviewed obsolete layers in live style and Studio draft after replacement datasets finish publishing')
    retirement.add_argument('manifest', type=Path)
    retirement.add_argument('--approve', required=True, help='Exact consolidation manifest hash')
    selection = commands.add_parser('review-candidate', help='Build a candidate containing only accepted changes; does not publish')
    selection.add_argument('plan', type=Path)
    selection.add_argument('decisions', type=Path)
    selection.add_argument('--output', required=True, type=Path)
    commands.add_parser('build-site')
    commands.add_parser('validate')
    args = parser.parse_args()
    if args.command == 'check':
        report = check(args.pipeline, args.llm, args.state_dir, args.source)
        print(json.dumps(report, indent=2))
        return 1 if report['errors'] else 0
    if args.command == 'normalize':
        result = run_adapter(read_json(args.input), configs(args.pipeline)[0], args.source)
        write_json(args.output, result)
        print(f"Wrote {len(result['features'])} normalized features to {args.output}")
    elif args.command == 'inventory':
        print(json.dumps(inventory(Mapbox(), args.output), indent=2))
    elif args.command == 'fetch-arcgis':
        if not args.url.startswith('https://'): raise ValueError('ArcGIS source requires HTTPS')
        result = json.loads(fetch_arcgis(args.url))
        write_json(args.output, result)
        print(f"Saved {len(result['features'])} features to {args.output}")
    elif args.command == 'reconcile':
        result = reconcile(read_json(args.baseline), read_json(args.candidate), args.legacy_id, args.keep)
        write_json(args.output, result)
        print(json.dumps(result['ingest_report'], indent=2))
    elif args.command == 'plan':
        plan = make_plan(Mapbox(), target_by_id(args.target), read_json(args.candidate), args.evidence)
        write_json(args.output, plan)
        print(json.dumps({'changes': {key: len(ids) for key, ids in plan['changes'].items()}, 'plan': str(args.output), 'approval_hash': plan['approval_hash']}, indent=2))
    elif args.command == 'apply':
        print(json.dumps(apply_plan(Mapbox(), read_json(args.plan), args.approve, args.publish), indent=2))
    elif args.command == 'resume-publish':
        print(json.dumps(resume_publish(Mapbox(), read_json(args.plan), args.approve, repair_layer=args.repair_layer), indent=2))
    elif args.command == 'upload-status':
        print(json.dumps(Mapbox().upload_status(args.upload_id), indent=2))
    elif args.command == 'approve-notice':
        result = approve_notice(args.review, args.index, args.reviewer, args.starts, args.expires)
        print(f"Added reviewed notice: {result['title']}. Build and deploy the site to publish it.")
    elif args.command == 'build-site':
        build_site()
        print('Built dist/ from public files only')
    elif args.command == 'review-packet':
        print(json.dumps(review_packet(args.review), indent=2))
    elif args.command == 'review-map':
        print(f'Review files: {build_review(args.plan, overlaps_path=args.overlaps)}')
    elif args.command == 'compare-overlaps':
        from .overlaps import compare_overlaps
        result = compare_overlaps(read_json(args.plan), args.inventory)
        write_json(args.output, result)
        print(json.dumps(result['summary'], indent=2))
    elif args.command == 'review-parks':
        from .park_review import build_park_review
        print(f'Review files: {build_park_review(args.plan, args.inventory, args.boundaries, args.overlaps, args.output)}')
    elif args.command == 'prepare-consolidation':
        from .consolidation import prepare_consolidation
        result = prepare_consolidation(read_json(args.plan), read_json(args.review)['report'], read_json(args.decisions), read_json(args.policy), args.inventory, args.output)
        print(json.dumps({'datasets': result['datasets'], 'protected_datasets': result['protected_datasets'], 'boundary_adjustments': result['boundary_adjustments']}, indent=2))
    elif args.command == 'review-consolidation':
        from .consolidation import build_consolidation_review
        print(build_consolidation_review(args.manifest, args.review, args.policy, args.inventory, args.output))
    elif args.command == 'retire-style-layers':
        from .styles import retire_style_layers
        print(json.dumps(retire_style_layers(Mapbox(), args.manifest, args.approve), indent=2))
    elif args.command == 'review-candidate':
        candidate = reviewed_candidate(read_json(args.plan), read_json(args.decisions))
        write_json(args.output, candidate)
        print(f'Wrote {args.output}. Generate a fresh plan before publishing.')
    elif args.command == 'record-review':
        record_review(args.review, args.assessment, args.reviewer)
        print('Saved chat review. Notices and map changes still require a separate publishing step.')
    elif args.command == 'validate':
        validate_updates(read_json(ROOT / 'data/updates.json'), read_json(ROOT / 'data/systems.json'))
        configs()
        print('Content and pipeline configuration loaded successfully')
    return 0


if __name__ == '__main__':
    try: sys.exit(main())
    except (RuntimeError, ValueError, OSError, KeyError, IndexError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
