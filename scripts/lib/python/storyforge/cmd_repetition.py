"""storyforge repetition — Cross-chapter repeated phrase detection.

Scans the manuscript for repeated similes, character tells, blocking tics,
and signature phrases that appear across multiple scenes.

Usage:
    storyforge repetition                    # Full manuscript scan
    storyforge repetition --scenes S1,S2     # Specific scenes only
    storyforge repetition --min-occurrences 3 # Raise threshold for long books
    storyforge repetition --category simile  # Filter to one category
"""

import argparse
import os
import sys

from storyforge.common import detect_project_root, install_signal_handlers, log
from storyforge.cli import add_scene_filter_args, resolve_filter_args
from storyforge.scene_filter import build_scene_list, apply_scene_filter


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge repetition',
        description='Scan manuscript for cross-chapter repeated phrases.',
    )
    add_scene_filter_args(parser)
    parser.add_argument('--min-occurrences', type=int, default=0,
                        help='Override minimum occurrence threshold (0 = use defaults)')
    parser.add_argument('--category', choices=[
        'simile', 'character_tell', 'blocking_tic', 'sensory',
        'structural', 'signature_phrase',
    ], help='Filter findings to one category')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()
    project_dir = detect_project_root()

    from storyforge.repetition import scan_manuscript

    # Resolve scene filter
    meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    scene_ids = None
    mode, val, val2 = resolve_filter_args(args)
    if mode:
        all_ids = build_scene_list(meta_csv)
        scene_ids = apply_scene_filter(meta_csv, all_ids, mode, val, val2)
        log(f'Scanning {len(scene_ids)} scenes (filtered)')
    else:
        log('Scanning all scenes')

    findings = scan_manuscript(project_dir, scene_ids=scene_ids)

    # Apply category filter
    if args.category:
        findings = [f for f in findings if f['category'] == args.category]

    # Write report CSV
    report_dir = os.path.join(project_dir, 'working')
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, 'repetition-report.csv')

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('phrase|category|severity|count|scene_ids\n')
        for finding in findings:
            scenes_str = ';'.join(finding['scene_ids'])
            f.write(f'{finding["phrase"]}|{finding["category"]}|'
                    f'{finding["severity"]}|{finding["count"]}|{scenes_str}\n')

    # Summary
    high_count = sum(1 for f in findings if f['severity'] == 'high')
    log(f'Found {len(findings)} repeated phrases ({high_count} high-severity)')

    if findings:
        log('')
        log('Top findings:')
        for f in findings[:10]:
            scenes = ', '.join(f['scene_ids'][:3])
            if len(f['scene_ids']) > 3:
                scenes += f' +{len(f["scene_ids"]) - 3} more'
            log(f'  [{f["severity"]}] "{f["phrase"]}" — {f["count"]}x '
                f'({f["category"]}) in {scenes}')

    log(f'\nFull report: {report_path}')
