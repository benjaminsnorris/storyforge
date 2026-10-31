"""storyforge check — advisor mode: the gate on prose already written.

Usage:
    storyforge check act1-sc03                 # one scene
    storyforge check act1-sc01 act1-sc05       # a range, in reading order
    storyforge check --scenes a,b,c
    storyforge check --act 2
    storyforge check --pending                 # every scene waiting on the gate

For prose the author wrote (rethink plan §3.2, "in advisor mode, step 3
becomes a report"): each scene, in reading order, goes through the gate
(`storyforge.gate.gate_scene`, command `advisor`): its commitments are
extracted, checked against the rest of the book and its brief, and reported.
Nothing in the prose is ever edited.

A scene that passes has its commitments committed to the ledger (and any
brief fact it was found to establish gets its quote). The first scene that
doesn't pass (or can't be checked) stops the run: the ledger keeps what it
had for that scene, its findings are the report, it is listed in
`working/gate-pending.csv` (`write` won't draft past it until a check or
redraft passes), and the later scenes are listed as not checked, since
they'd be checked against a ledger without its facts (plan §3.2: fail
loud). The report is written to `working/check-report.md` and committed
with the ledger. Exit 1 when a scene did not pass, a named scene isn't one
that can be checked, or the commit fails.

A scene that passes and changed facts later scenes depend on lists those
scenes for a re-check (Phase 4, `docs/plans/2026-10-31-phase4-safe-revision-design.md`),
and they are re-checked after it, in reading order, under the cost threshold
(`gate.recheck_pending`); scenes later in this run are checked by the run
itself. `--pending` checks every scene in `working/gate-pending.csv`; one
listed for a re-check keeps the command that wrote its prose.
"""

from __future__ import annotations

import argparse
import os
import sys

from storyforge.common import detect_project_root, install_signal_handlers, log, set_log_file

REPORT_PATH = 'working/check-report.md'


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
    parser.add_argument('--pending', action='store_true',
                        help='Every scene waiting on the gate (working/gate-pending.csv)')
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
    if not (args.positional or args.scenes or args.act or args.from_seq or args.pending):
        log('ERROR: name the scenes to check (an id, a range, --scenes, --act, --from-seq '
            'or --pending).')
        sys.exit(1)
    if args.pending and (args.positional or args.scenes or args.act or args.from_seq):
        log('ERROR: --pending checks the scenes waiting on the gate; name no others with it.')
        sys.exit(1)
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    set_log_file(os.path.join(log_dir, 'check-log.txt'))

    try:
        waiting = gate.pending(project_dir)
    except gate.GateError as e:
        log(f'ERROR: {e}')
        sys.exit(1)
    if args.pending:
        if not waiting:
            log('Nothing is waiting on the gate.')
            return
        in_book = ledger.scene_order(project_dir)
        gone = [s for s in waiting if s not in in_book]
        if gone:
            log(f'WARNING: {", ".join(gone)} in {gate.PENDING_PATH} are no longer scenes in '
                f'scenes.csv: not checked; remove their rows.')
        scene_ids = [s for s in waiting if s in in_book]
        if not scene_ids:
            log('Nothing in the book is waiting on the gate.')
            return
        unknown = []
    else:
        scene_ids = _scene_ids(args, project_dir)
        unknown = [s for s in _named(args) if s not in scene_ids]
    if unknown:
        log(f'ERROR: not scenes that can be checked (no such id, or cut or merged): '
            f'{", ".join(unknown)}')
        sys.exit(1)
    order = ledger.scene_order(project_dir)
    scene_ids = sorted(scene_ids, key=lambda s: order.get(s, -1))
    missing = [s for s in scene_ids if not os.path.isfile(
        os.path.join(project_dir, 'scenes', f'{s}.md'))]
    if missing:
        log(f'ERROR: no prose for {len(missing)} scene(s): {", ".join(missing)}')
        sys.exit(1)
    if not scene_ids:
        log('ERROR: no scene matches.')
        sys.exit(1)
    if not create_branch('check', project_dir):
        log('ERROR: could not create or find a branch to work on; nothing checked.')
        sys.exit(1)

    report = ['# Check report', '']
    passed, stopped_at, stop_why, recheck_trouble = 0, '', '', ''
    spent = 0.0   # this run's re-checks, forecast
    for n, scene_id in enumerate(scene_ids):
        log(f'--- Checking {scene_id} ---')
        # read again for each scene: earlier scenes' re-checks list more
        row = gate.pending(project_dir).get(scene_id, {})
        recheck = row.get('command') in (gate.RECHECK, gate.RECHECK_FAILED)
        # a failed scene stays listed as it was listed: a re-check keeps its
        # prose's writer
        listed_as = gate.RECHECK_FAILED if recheck else 'advisor'
        try:
            result = gate.gate_scene(
                project_dir, scene_id, command='recheck' if recheck else 'advisor',
                log_dir=os.path.join(log_dir, 'check'),
                introduced_by=gate._writer(project_dir, scene_id) if recheck else None)
        except gate.GateError as e:
            why = ' '.join(str(e).split())
            log(f'ERROR: {why}')
            report += [f'## {scene_id}: not checked', '', f'- {why}', '']
            gate.mark_pending(project_dir, scene_id, listed_as, f'not checked: {why}')
            stopped_at, stop_why = scene_id, 'did not pass'
        else:
            lines = gate.report_lines(result)
            verdict = 'passed' if result.passed else 'did not pass'
            log(f'{scene_id}: {verdict}')
            for line in lines:
                log(f'  {line}')
            report += [f'## {scene_id}: {verdict}', ''] + [f'- {line}' for line in lines] \
                + ([] if lines else ['- nothing to report']) + ['']
            if result.passed:
                passed += 1
                lines, run = _recheck_after(project_dir, result, log_dir,
                                            set(scene_ids[n + 1:]), spent)
                report += lines
                if run is not None:
                    spent = run.spent
                    blocked = [s for s in ([run.failed] if run.failed else run.left)
                               if run.failed or run.over_budget]
                    if blocked:
                        recheck_trouble = (f're-check of {run.failed} did not pass'
                                           if run.failed else
                                           f're-check of {", ".join(run.left)} not run '
                                           f'(over the cost threshold)')
                    # a scene of this run after one left stale would be checked
                    # against a ledger missing its facts
                    order = ledger.scene_order(project_dir)
                    first = min(blocked, key=order.get) if blocked else ''
                    if first and any(order[s] > order[first] for s in scene_ids[n + 1:]):
                        stopped_at = first
                        stop_why = ('was re-checked and did not pass' if run.failed
                                    else 'was not re-checked (over the cost threshold)')
            else:
                gate.mark_pending(project_dir, scene_id, listed_as,
                                  f'{sum(1 for x in lines if not x.startswith(("NOTE", "COMMITTED")))} '
                                  f'problem(s); see {REPORT_PATH}')
                stopped_at, stop_why = scene_id, 'did not pass'
        if stopped_at:
            rest = scene_ids[n + 1:]
            if rest:
                report += ['## Not checked', '', f'Stopped at {stopped_at}: later scenes would '
                           f'be checked against a ledger without its facts. Not checked: '
                           f'{", ".join(rest)}.', '']
            break

    path = os.path.join(project_dir, REPORT_PATH)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    log(f'Report: {path}')
    if not commit_and_push(project_dir, f'Check: {passed} of {len(scene_ids)} scene(s) passed',
                           ['reference/commitments.csv', 'working/']):
        log('ERROR: the commit failed: the ledger and report are written but not committed.')
        sys.exit(1)
    if stopped_at:
        log(f'ERROR: stopped at {stopped_at}, which {stop_why}; {passed} of '
            f'{len(scene_ids)} scene(s) passed. Edit it and check it again.')
        sys.exit(1)
    if recheck_trouble:
        log(f'ERROR: {passed} of {len(scene_ids)} scene(s) passed, but the {recheck_trouble}; '
            f'it is listed in {gate.PENDING_PATH} (`storyforge check --pending`).')
        sys.exit(1)


def _recheck_after(project_dir: str, result, log_dir: str, skip: set[str], spent: float):
    """Re-check the scenes `result` listed (not those later in this run),
    as `write` does. Returns the report lines and the `gate.Recheck` (None
    when nothing was pending)."""
    from storyforge.cmd_write import report_changes, run_recheck
    report_changes(result)
    run = run_recheck(project_dir, os.path.join(log_dir, 'check'), skip, spent_before=spent)
    lines = [f'- {result.scene_id} changed {fid}; its dependents can\'t all be found: {why}'
             for fid, why in result.unrelated.items()]
    lines += [f'- depends on {result.scene_id} but can\'t be re-checked now: {x}'
              for x in result.not_rechecked]
    lines += [f'- registry link to a commitment {result.scene_id} no longer makes: {x}'
              for x in result.dangling]
    if run is None:
        return lines + ([''] if lines else []), None
    lines += [f'- re-check passed: {s}' for s in run.passed]
    if run.failed:
        lines.append(f'- re-check of {run.failed} did not pass: {run.why} (listed pending)')
    if run.over_budget:
        lines.append(f'- re-check of {len(run.left)} scene(s) not run: forecast '
                     f'${run.forecast:.2f} is over the cost threshold (listed pending)')
    return [f'### Re-check after {result.scene_id}', ''] + lines + [''], run


def _named(args) -> list[str]:
    """The scene ids the command line names one by one (not a range or an act)."""
    if args.scenes:
        return [s.strip() for s in args.scenes.split(',') if s.strip()]
    if len(args.positional) == 1:
        return list(args.positional)
    if len(args.positional) == 2:
        return list(args.positional)
    return []
