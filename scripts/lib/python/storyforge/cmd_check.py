"""storyforge check — advisor mode: the gate on prose already written.

Usage:
    storyforge check act1-sc03                 # one scene
    storyforge check act1-sc01 act1-sc05       # a range, in reading order
    storyforge check --scenes a,b,c
    storyforge check --act 2
    storyforge check --pending                 # every scene waiting on the gate
    storyforge check --pending --keep-going    # ... all of them, not stopping at a failure
    storyforge check --accept act1-sc03        # accept what stopped it, then --pending

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

Cost: the threshold is one budget for the whole run (`costs.RunBudget`).
`--pending` forecasts its scenes at `gate.RECHECK_COST_PER_SCENE` before
anything is spent and exits 1 when that is over; before each scene, what
the run has spent (metered) plus the scenes left must still be within it,
or the run stops there (they stay pending; exit 1). The re-checks after a
scene get only what the run's spend and the scenes still to check leave.

`--pending --keep-going` checks every waiting scene in reading order and
doesn't stop at one that fails: each failure is listed pending as above
(a verified contradiction that stopped it is recorded in
`working/gate-blocked.csv`, so `--accept` works on that scene), and the run
goes on, re-check failures included. At the end a summary lists every
scene that didn't pass with its findings, the re-checks that failed or
weren't run, and the exact `storyforge check --accept a,b,c` for the
scenes this run recorded contradictions for (a scene that couldn't be
checked, or failed only on a broken promise, an unverified quote, an
extraction problem or a halt, has nothing to accept and is named apart),
and it exits 1 if any didn't pass. A scene checked after an earlier one
that hadn't passed (in the run, or a re-check) is provisional: the ledger
held that scene's earlier commitments, not its current prose's, which is
why the run otherwise stops. When it later passes, the scenes depending
on facts it changed are listed for a re-check, and its own check reads its
new facts against the later scenes.

A stop is the author's to fix or accept (Ben, 2026-11-02). `--accept SCENES`
accepts the verified contradictions that stopped each scene's last gate run
(`working/gate-blocked.csv`, `gate.accept_blocked`): they move to
`working/gate-reported.csv` as accepted, so later gate runs report them
instead of stopping, and a failed re-check is listed for a re-check again.
No model call; it commits, and `--pending` then checks the scenes. Only
verified contradictions a gate run recorded can be accepted: broken
promises, unverified quotes, extraction problems, halts and a check that
couldn't run still have to be fixed.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field

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
    parser.add_argument('--keep-going', action='store_true',
                        help='With --pending: check every waiting scene in reading order '
                             'instead of stopping at the first that fails. Each failure '
                             'stays pending; a summary lists them, with the --accept command '
                             'for those whose verified contradictions this run recorded; '
                             'exit 1 if any failed. Results for scenes after one that fails '
                             'are provisional: they are checked against a ledger without '
                             'its current facts.')
    parser.add_argument('--accept', metavar='SCENES',
                        help='Comma-separated scene IDs: accept the contradictions that '
                             'stopped each one\'s last gate run (no model call)')
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
    if args.accept:
        if (args.positional or args.scenes or args.act or args.from_seq or args.pending
                or args.keep_going):
            log('ERROR: --accept takes its own scene list; name no others with it.')
            sys.exit(1)
        _accept(project_dir, [s.strip() for s in args.accept.split(',') if s.strip()])
        return
    from storyforge.costs import exit_if_bad_threshold
    exit_if_bad_threshold()   # the re-checks and --pending's forecast check it
    if not (args.positional or args.scenes or args.act or args.from_seq or args.pending):
        log('ERROR: name the scenes to check (an id, a range, --scenes, --act, --from-seq '
            'or --pending).')
        sys.exit(1)
    if args.pending and (args.positional or args.scenes or args.act or args.from_seq):
        log('ERROR: --pending checks the scenes waiting on the gate; name no others with it.')
        sys.exit(1)
    if args.keep_going and not args.pending:
        log('ERROR: --keep-going goes with --pending (check every scene waiting on the gate '
            'without stopping at the first that fails).')
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
    # Every selection is forecast before anything is spent (#503's review:
    # a check by name, act or range skipped the threshold)
    from storyforge.costs import check_threshold, cost_threshold
    forecast = len(scene_ids) * gate.RECHECK_COST_PER_SCENE
    log(f'{len(scene_ids)} scene(s) to check, forecast about ${forecast:.2f}')
    if not check_threshold(forecast):
        log(f'ERROR: that is over the cost threshold (${cost_threshold():g}): nothing '
            f'checked. Raise STORYFORGE_COST_THRESHOLD, or check them a few at a time '
            f'with --scenes.')
        sys.exit(1)
    if not create_branch('check', project_dir):
        log('ERROR: could not create or find a branch to work on; nothing checked.')
        sys.exit(1)

    # The threshold is one budget for the run: the re-checks after a scene
    # get what the checks so far actually spent (metered) and the scenes
    # still to check leave (`costs.RunBudget`)
    from storyforge import api
    from storyforge.costs import RunBudget
    with api.metered() as meter:
        run = _check_scenes(project_dir, scene_ids, log_dir, RunBudget(meter),
                            keep_going=args.keep_going)

    report = run.report
    summary = _keep_going_summary(project_dir, run) if args.keep_going else []
    if summary:
        report += ['## Summary', ''] + summary + ['']
        for line in summary:   # before the commit: a failed commit mustn't hide it
            log(line)
    path = os.path.join(project_dir, REPORT_PATH)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report))
    except OSError as e:
        log(f'ERROR: could not write {REPORT_PATH} ({e}); the verdicts are in the log above.')
        report_failed = True
    else:
        log(f'Report: {path}')
        report_failed = False
    if not commit_and_push(project_dir, f'Check: {run.passed} of {len(scene_ids)} scene(s) '
                           f'passed', ['reference/commitments.csv', 'working/']):
        log('ERROR: the commit failed: the ledger and report are written but not committed.')
        sys.exit(1)
    if report_failed:
        sys.exit(1)
    if args.keep_going:
        if (run.failures or run.recheck_failures or run.not_rechecked or run.left_behind
                or run.over_budget):
            sys.exit(1)
        return
    if run.over_budget:
        log(f'ERROR: stopped before {run.stopped_at}: the run reached the cost threshold; '
            f'{run.passed} of {len(scene_ids)} scene(s) passed. Not checked: '
            f'{", ".join(run.unchecked)}.')
        sys.exit(1)
    if run.stopped_at:
        accept = (f', or accept its contradictions: `storyforge check --accept '
                  f'{run.stopped_at}`' if run.stopped_at in run.recorded else
                  ' (it has no verified contradiction this run recorded to accept)')
        log(f'ERROR: stopped at {run.stopped_at}, which {run.stop_why}; {run.passed} of '
            f'{len(scene_ids)} scene(s) passed. Edit it and check it again{accept}.')
        sys.exit(1)
    if run.recheck_trouble:
        log(f'ERROR: {run.passed} of {len(scene_ids)} scene(s) passed, but the '
            f'{run.recheck_trouble}; it is listed in {gate.PENDING_PATH} '
            f'(`storyforge check --pending`).')
        sys.exit(1)


@dataclass
class _Run:
    """What `_check_scenes` found."""
    report: list = field(default_factory=lambda: ['# Check report', ''])
    passed: int = 0
    #: the scene the run stopped at ('' when it didn't stop), and why
    stopped_at: str = ''
    stop_why: str = ''
    #: the scenes left unchecked when it stopped
    unchecked: list = field(default_factory=list)
    #: it stopped because the run reached the cost threshold
    over_budget: bool = False
    #: a re-check that failed or wasn't run (the stop-at-first run's message)
    recheck_trouble: str = ''
    #: --keep-going: scene id → the lines saying why it didn't pass (its
    #: blocking findings, or why it couldn't be checked)
    failures: dict = field(default_factory=dict)
    #: --keep-going: a scene whose re-check, run after one of the run's
    #: scenes passed, didn't pass → (the scene that passed, why)
    recheck_failures: dict = field(default_factory=dict)
    #: --keep-going: the scenes listed for a re-check that weren't run (over
    #: the cost threshold) and haven't passed since
    not_rechecked: list = field(default_factory=list)
    #: --keep-going: re-checks left unrun behind one that failed (still
    #: pending) and not passed since
    left_behind: list = field(default_factory=list)
    #: the scenes this run's own gate run recorded verified contradictions
    #: for (in working/gate-blocked.csv): the only ones `--accept` is offered
    #: for, never rows an earlier run left
    recorded: set = field(default_factory=set)
    #: --keep-going: scene id → the earlier scene that hadn't passed when it
    #: was checked (its result is provisional)
    provisional: dict = field(default_factory=dict)


def _check_scenes(project_dir: str, scene_ids: list[str], log_dir: str, budget,
                  keep_going: bool = False) -> _Run:
    """Check `scene_ids` (in reading order) through the gate, re-checking
    after each one that passes what it listed, under the run's one cost
    budget (`budget`, a `costs.RunBudget`: the re-checks get what the run's
    spend and the scenes still to check, at `gate.RECHECK_COST_PER_SCENE`,
    leave). The forecast was checked up front; before each scene, the run's
    spend plus the scenes left must still be within the threshold, or it
    stops there (the rest stay as they were: pending ones pending).

    It stops at the first scene that doesn't pass or can't be checked, and
    at a re-check left failed or unrun before a later scene of the run.
    With `keep_going` it doesn't: each failure is listed pending (and its
    contradictions recorded for `--accept`) and the run goes on; a scene
    checked after an earlier one that hadn't passed is `provisional`."""
    from storyforge import gate, ledger
    from storyforge.costs import check_threshold, cost_threshold
    run = _Run()
    report = run.report
    order = ledger.scene_order(project_dir)
    unsettled: list[str] = []   # scenes that didn't pass (or weren't re-checked)
    for n, scene_id in enumerate(scene_ids):
        rest = scene_ids[n + 1:]
        due = budget.committed((len(rest) + 1) * gate.RECHECK_COST_PER_SCENE)
        if not check_threshold(due):
            log(f'ERROR: checking {scene_id} and the {len(rest)} scene(s) after it would '
                f'bring this run to about ${due:.2f}, over the cost threshold '
                f'(${cost_threshold():g}): stopped.')
            run.stopped_at, run.over_budget = scene_id, True
            run.unchecked = scene_ids[n:]
            report += ['## Not checked', '', f'Stopped before {scene_id}: the run reached '
                       f'the cost threshold (about ${due:.2f} with the rest). Not '
                       f'checked: {", ".join(scene_ids[n:])}.', '']
            break
        log(f'--- Checking {scene_id} ---')
        earlier = [s for s in unsettled if order.get(s, -1) < order.get(scene_id, -1)]
        if earlier:
            run.provisional[scene_id] = earlier[0]
        # read again for each scene: earlier scenes' re-checks list more
        row = gate.pending(project_dir).get(scene_id, {})
        recheck = row.get('command') in (gate.RECHECK, gate.RECHECK_FAILED)
        # a failed scene stays listed as it was listed: a re-check keeps its
        # prose's writer
        listed_as = gate.RECHECK_FAILED if recheck else 'advisor'
        failed_here = False
        try:
            # this check's own logs: an earlier check of the scene keeps its own
            logs = gate.run_log_dir(os.path.join(log_dir, 'check'), scene_id)
            log(f'  logs: {os.path.relpath(logs, project_dir)}')
            result = gate.gate_scene(
                project_dir, scene_id, command='recheck' if recheck else 'advisor',
                log_dir=logs,
                introduced_by=gate._writer(project_dir, scene_id) if recheck else None)
        except gate.GateError as e:
            why = ' '.join(str(e).split())
            log(f'ERROR: {why}' + (f' (provisional: {earlier[0]}, earlier, has not passed)'
                                   if earlier else ''))
            report += [f'## {scene_id}: not checked', '', f'- {why}', '']
            gate.mark_pending(project_dir, scene_id, listed_as, f'not checked: {why}')
            run.failures[scene_id] = [f'could not be checked: {why}']
            failed_here = True
        else:
            lines = gate.report_lines(result)
            verdict = 'passed' if result.passed else 'did not pass'
            log(f'{scene_id}: {verdict}' + (f' (provisional: {earlier[0]}, earlier, has not '
                                            f'passed)' if earlier else ''))
            for line in lines:
                log(f'  {line}')
            report += [f'## {scene_id}: {verdict}', ''] + [f'- {line}' for line in lines] \
                + ([] if lines else ['- nothing to report']) + ['']
            if result.passed:
                run.passed += 1
                lines, rerun = _recheck_after(project_dir, result, log_dir, set(rest), budget)
                report += lines
                if rerun is not None:
                    # a re-check deferred or left behind earlier that passed
                    # now is settled (#503's review, SF-5)
                    for s in rerun.passed:
                        for kept in (run.not_rechecked, run.left_behind, unsettled):
                            if s in kept:
                                kept.remove(s)
                    blocked = [s for s in ([rerun.failed] if rerun.failed else rerun.left)
                               if rerun.failed or rerun.over_budget]
                    if rerun.failed:
                        run.recheck_failures[rerun.failed] = (scene_id, rerun.why)
                        if rerun.result is not None and _contradictions(rerun.result):
                            run.recorded.add(rerun.failed)
                        run.left_behind += [s for s in rerun.left
                                            if s not in run.left_behind]
                    if rerun.over_budget:
                        run.not_rechecked += [s for s in rerun.left
                                              if s not in run.not_rechecked]
                    unsettled += [s for s in blocked if s not in unsettled]
                    if blocked:
                        run.recheck_trouble = (f're-check of {rerun.failed} did not pass'
                                               if rerun.failed else
                                               f're-check of {", ".join(rerun.left)} not '
                                               f'run (over the cost threshold)')
                    # a scene of this run after one left stale would be checked
                    # against a ledger missing its facts
                    order = ledger.scene_order(project_dir)
                    first = min(blocked, key=order.get) if blocked else ''
                    if (not keep_going and first
                            and any(order[s] > order[first] for s in rest)):
                        run.stopped_at = first
                        run.stop_why = ('was re-checked and did not pass' if rerun.failed
                                        else 'was not re-checked (over the cost threshold)')
            else:
                problems = gate.blocking_lines(lines)
                gate.mark_pending(project_dir, scene_id, listed_as,
                                  f'{sum(1 for x in lines if not x.startswith(("NOTE", "COMMITTED")))} '
                                  f'problem(s); see {REPORT_PATH}')
                run.failures[scene_id] = problems or ['did not pass (see the report)']
                if _contradictions(result):
                    run.recorded.add(scene_id)
                failed_here = True
        if failed_here:
            unsettled.append(scene_id)
            if not keep_going:
                run.stopped_at, run.stop_why = scene_id, 'did not pass'
        if run.stopped_at:
            if rest:
                run.unchecked = rest
                report += ['## Not checked', '', f'Stopped at {run.stopped_at}: later scenes '
                           f'would be checked against a ledger without its facts. Not '
                           f'checked: {", ".join(rest)}.', '']
            break
    return run


def _contradictions(result) -> bool:
    """Whether a failed gate run recorded verified contradictions for
    `--accept` (`gate._note_blocked` records `result.findings`'
    contradictions)."""
    return any(f.kind == 'contradiction' for f in result.findings)


def _keep_going_summary(project_dir: str, run: _Run) -> list[str]:
    """--keep-going's closing lines: every scene that didn't pass with why,
    the re-checks that failed or didn't run, which results are provisional,
    and the exact `--accept` command for the scenes with contradictions to
    accept."""
    from storyforge import gate
    total = run.passed + len(run.failures)
    lines = [f'{run.passed} of {total} scene(s) checked passed.']
    if run.over_budget:
        lines.append(f'ERROR: stopped before {run.stopped_at} (the cost threshold); not '
                     f'checked, still pending: {", ".join(run.unchecked)}.')
    still = set(gate.pending(project_dir))   # a deferred re-check may have run since
    run.not_rechecked[:] = [s for s in run.not_rechecked if s in still]
    run.left_behind[:] = [s for s in run.left_behind if s in still]
    if not (run.failures or run.recheck_failures or run.not_rechecked or run.left_behind):
        return lines
    lines.append('ERROR: these did not pass (each stays in '
                 f'{gate.PENDING_PATH}):')
    for sid, why in run.failures.items():
        lines.append(f'  {sid}:' + (f' (provisional: checked while {run.provisional[sid]} '
                                    f'had not passed)' if sid in run.provisional else ''))
        lines += [f'    - {w}' for w in why]
    for sid, (after, why) in run.recheck_failures.items():
        lines.append(f'  {sid} (re-checked after {after} passed): {why}')
    if run.not_rechecked:
        lines.append(f'  not re-checked (over the cost threshold; still pending): '
                     f'{", ".join(run.not_rechecked)}')
    if run.left_behind:
        lines.append(f'  not re-checked (behind a re-check that failed; still pending): '
                     f'{", ".join(run.left_behind)}')
    later = [s for s in run.provisional if s not in run.failures]
    if run.provisional:
        lines.append(
            f'Provisional: {", ".join(run.provisional)} were checked after a scene earlier in '
            f'the book that had not passed, against a ledger without that scene\'s current '
            f'facts (it keeps its earlier ones, if any). Once it passes, the scenes depending '
            f'on facts it changed are listed for a re-check, and its own check reads its new '
            f'facts against them' + (f'; {", ".join(later)} passed and committed their '
                                     f'facts meanwhile' if later else '') + '.')
    try:
        recorded = gate.blocked(project_dir)
    except gate.GateError as e:
        lines.append(f'WARNING: {gate.BLOCKED_PATH} could not be read ({e}): which of them '
                     f'can be accepted is unknown.')
        return lines
    failed = list(run.failures) + list(run.recheck_failures)
    # only what this run's check recorded (SF-2): rows an earlier run left
    # for a scene this run couldn't check are stale
    acceptable = [s for s in failed if s in run.recorded and recorded.get(s)]
    to_fix = [s for s in failed if s not in acceptable]
    if acceptable:
        lines.append(f'To accept their contradictions as written (no model call; a scene with '
                     f'other problems still stops on those): '
                     f'`storyforge check --accept {",".join(acceptable)}`, then '
                     f'`storyforge check --pending --keep-going`.')
    if to_fix:
        lines.append(f'Nothing to accept for {", ".join(to_fix)} (no verified contradiction '
                     f'stopped it in this run: a broken promise, an unverified quote, an '
                     f'extraction problem, a halt, or a check that could not run): fix the '
                     f'scene, its brief or the book, then check it again.')
    return lines


def _recheck_after(project_dir: str, result, log_dir: str, skip: set[str], budget):
    """Re-check the scenes `result` listed (not those later in this run),
    as `write` does, under the run's one budget (`skip`, the scenes still to
    check, reserved at `gate.RECHECK_COST_PER_SCENE`). Returns the report
    lines and the `gate.Recheck` (None when nothing was pending)."""
    from storyforge import gate
    from storyforge.cmd_write import budgeted_recheck, report_changes
    report_changes(result)
    run = budgeted_recheck(project_dir, os.path.join(log_dir, 'check'), skip, budget,
                           reserved=len(skip) * gate.RECHECK_COST_PER_SCENE)
    lines = [f'- {result.scene_id} changed {fid}; its dependents can\'t all be found: {why}'
             for fid, why in result.unrelated.items()]
    lines += [f'- depends on {result.scene_id} but can\'t be re-checked now: {x}'
              for x in result.not_rechecked]
    lines += [f'- dependents of {result.scene_id} matched on fewer names: {x}'
              for x in result.name_notes]
    lines += [f'- {x}' for x in result.prose_notes]
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


def _accept(project_dir: str, scene_ids: list[str]) -> None:
    """`--accept`: accept each scene's recorded contradictions and commit.
    A scene with nothing recorded is an error (nothing is accepted for any
    scene), so a typo can't pass silently."""
    from storyforge import gate
    from storyforge.git import commit_and_push, create_branch
    if not scene_ids:
        log('ERROR: --accept needs scene ids.')
        sys.exit(1)
    try:
        recorded = gate.blocked(project_dir)
    except gate.GateError as e:
        log(f'ERROR: {e}')
        sys.exit(1)
    missing = [s for s in scene_ids if not recorded.get(s)]
    if missing:
        log(f'ERROR: nothing to accept for {", ".join(missing)}: {gate.BLOCKED_PATH} has no '
            f'contradiction that stopped it (only a scene whose last gate run stopped on a '
            f'verified contradiction can be accepted; check it first, or fix what stopped '
            f'it). Nothing accepted.')
        sys.exit(1)
    if not create_branch('check', project_dir):
        log('ERROR: could not create or find a branch to work on; nothing accepted.')
        sys.exit(1)
    total = 0
    for sid in scene_ids:
        try:
            rows = gate.accept_blocked(project_dir, sid)
        except gate.GateError as e:
            log(f'ERROR: {sid}: {e}')
            sys.exit(1)
        total += len(rows)
        log(f'{sid}: accepted {len(rows)} contradiction(s):')
        for r in rows:
            log(f'  {r["finding"]}')
    if not commit_and_push(project_dir, f'Check: accept {total} contradiction(s) in '
                           f'{", ".join(scene_ids)}',
                           [gate.REPORTED_PATH, gate.BLOCKED_PATH, gate.PENDING_PATH]):
        log('ERROR: the commit failed: the files are written but not committed.')
        sys.exit(1)
    log(f'Accepted; they are reported from now on, not blocking. Check the scene(s) again: '
        f'`storyforge check --pending` (a scene that also had other problems stops on those).')


def _named(args) -> list[str]:
    """The scene ids the command line names one by one (not a range or an act)."""
    if args.scenes:
        return [s.strip() for s in args.scenes.split(',') if s.strip()]
    if len(args.positional) == 1:
        return list(args.positional)
    if len(args.positional) == 2:
        return list(args.positional)
    return []
