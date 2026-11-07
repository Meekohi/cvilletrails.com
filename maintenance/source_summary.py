"""Render source-check coverage and failures into the GitHub Actions summary."""
import argparse
import html
from collections import Counter
from pathlib import Path
from .common import read_json


def cell(value):
    return html.escape(str(value or 'None')).replace('|', '&#124;').replace('\n', ' ')


def render(report):
    counts = Counter(s['state'] for s in report['sources'])
    manual = report.get('manual_review', [])
    errors = report['errors']
    lines = ['## Authoritative trail source check', '',
        f"Checked at: {cell(report['checked_at'])}", '',
        f"**{len(report['sources'])} sources checked successfully; {len(manual)} require manual review; {len(errors)} errors.**", '',
        f"New baselines: {counts['baseline']}. Changed: {counts['changed']}. Unchanged: {counts['unchanged']}. "
        f"Retry attempts: {len(report.get('retries', []))}.", '',
        'This job prepares evidence only. It does not publish trail data or visitor notices. '
        'A baseline is the first successful snapshot, not evidence of a recent change.', '']
    if errors:
        lines += ['### Errors — run failed', '', '| Source | Error | Last successful check |', '| --- | --- | --- |']
        for row in errors:
            lines.append(f"| {cell(row['source'])} | {cell(row['error'])} | {cell(row.get('last_success'))} |")
        lines.append('')
    if manual:
        lines += ['### Manual review required — incomplete automated coverage', '',
            'These explicitly registered sources still return HTTP 403. Their content was **not checked**. '
            'Open the official sources in a browser and record evidence before updating the map or visitor information. '
            'They are probed again on every run; successful responses automatically resume normal checking. '
            'Other failures still fail the job.', '',
            '| Source | Official URL | Reason | Last successful check |', '| --- | --- | --- | --- |']
        for row in manual:
            lines.append(f"| {cell(row['source'])} | {cell(row['url'])} | {cell(row['reason'])} | {cell(row.get('last_success'))} |")
        lines.append('')
    lines += ['### Successful source checks', '', '| Source | Result | Review artifact path |', '| --- | --- | --- |']
    for row in report['sources']:
        lines.append(f"| {cell(row['source'])} | {cell(row['state'])} | {cell(row.get('review'))} |")
    lines += ['', 'Download the `trail-source-reviews` artifact for `report.json`, snapshots, candidate GeoJSON, '
        'and pending reviews. Artifacts are retained for 90 days.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.report.exists():
        with args.output.open('a') as output:
            output.write('## Source check did not produce a report\n\nInspect the failed step; automated coverage is unknown.\n')
        raise SystemExit('No current source report; refusing to summarize a previous run.')
    report = read_json(args.report)
    with args.output.open('a') as output:
        output.write(render(report))
    if report.get('manual_review'):
        print(f"::warning title=Manual trail-source review required::{len(report['manual_review'])} known blocked sources were not checked. See the job summary for official URLs and coverage gaps.")
    if report['errors']:
        print(f"::error title=Trail-source check failures::{len(report['errors'])} errors. See the job summary for affected sources.")


if __name__ == '__main__':
    main()
