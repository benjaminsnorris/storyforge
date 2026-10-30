"""storyforge check — advisor mode: the gate on prose already written.

Usage:
    storyforge check act1-sc03                 # one scene
    storyforge check act1-sc01 act1-sc05       # a range, in reading order
    storyforge check --scenes a,b,c
    storyforge check --act 2

For prose the author wrote (rethink plan §3.2, "in advisor mode, step 3
becomes a report"): each scene, in reading order, goes through the gate
(`storyforge.gate.gate_scene`, command `advisor`): its commitments are
extracted, checked against the rest of the book and its brief, and reported.
Nothing in the prose is ever edited.

A scene that passes has its commitments committed to the ledger (and any
brief fact it was found to establish gets its quote); one that doesn't
leaves the ledger as it was, and its findings are the report. Later scenes
are still checked, but without a failing scene's facts in the ledger: the
report says so. The report is written to `working/check-report.md` and
committed with the ledger. Exit 1 when any scene did not pass.
"""

from __future__ import annotations

import argparse
import os
import sys

from storyforge.common import detect_project_root, install_signal_handlers, log, set_log_file


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge check',
        description='Check written scenes against the book and their briefs, '
                    'and report (advisor mode: prose is never edited).')
    parser.add_argument('positional', nargs='*', default=[],
                        help='Scene ID(s): one for a single scene, two for a range')
    parser.add_argument('--scenes', help='Comma-separated scene IDs')
    parser.add_argument('--act', '--part', help='Every scene in act N')
    parser.add_argument('--from-seq', help='From sequence number (N or N-M range)')
    return parser.parse_args(argv)


def _scene_ids(args, project_dir: str) -> list[str]:
    from storyforge.cmd_write import _resolve_filter
    from storyforge.scene_filter import apply_scene_filter, build_scene_list
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    mode, value, value2 = _resolve_filter(args)
    return apply_scene_filter(metadata_csv, build_scene_list(metadata_csv, min_words=0),
                              mode, value, value2)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()
    project_dir = detect_project_root()
    from storyforge import gate, ledger
    from storyforge.git import commit_and_push, create_branch
    ledger.exit_if_not_migrated(project_dir)
    ledger.exit_if_unordered(project_dir)
    if not (args.positional or args.scenes or args.act or args.from_seq):
        log('ERROR: name the scenes to check (an id, a range, --scenes, --act or --from-seq).')
        sys.exit(1)
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    set_log_file(os.path.join(log_dir, 'check-log.txt'))

    scene_ids = _scene_ids(args, project_dir)
    missing = [s for s in scene_ids if not os.path.isfile(
        os.path.join(project_dir, 'scenes', f'{s}.md'))]
    if missing:
        log(f'ERROR: no prose for {len(missing)} scene(s): {", ".join(missing)}')
        sys.exit(1)
    if not scene_ids:
        log('ERROR: no scene matches.')
        sys.exit(1)
    create_branch('check', project_dir)

    report = ['# Check report', '']
    failed, unchecked_after = [], []
    for scene_id in scene_ids:
        log(f'--- Checking {scene_id} ---')
        try:
            result = gate.gate_scene(project_dir, scene_id, command='advisor',
                                     log_dir=os.path.join(log_dir, 'check'))
        except gate.GateError as e:
            log(f'ERROR: {e}')
            report += [f'## {scene_id}: not checked', '', f'- {e}', '']
            failed.append(scene_id)
            continue
        lines = gate.report_lines(result)
        verdict = 'passed' if result.passed else 'did not pass'
        log(f'{scene_id}: {verdict}' + (f' ({len(result.proposed)} fact(s) committed)'
                                        if result.committed else ''))
        for line in lines:
            log(f'  {line}')
        report += [f'## {scene_id}: {verdict}', ''] + [f'- {line}' for line in lines] \
            + ([] if lines else ['- nothing to report']) + ['']
        if result.passed:
            if failed:
                unchecked_after.append(scene_id)
        else:
            failed.append(scene_id)

    if unchecked_after:
        report += ['## Note', '', f'Checked without the facts of the scene(s) that did not '
                   f'pass ({", ".join(failed)}): {", ".join(unchecked_after)}.', '']
    path = os.path.join(project_dir, 'working', 'check-report.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    log(f'Report: {path}')
    commit_and_push(project_dir, f'Check: {len(scene_ids) - len(failed)} of '
                    f'{len(scene_ids)} scene(s) passed',
                    ['reference/commitments.csv', 'working/'])
    if failed:
        log(f'ERROR: {len(failed)} scene(s) did not pass: {", ".join(failed)}')
        sys.exit(1)
