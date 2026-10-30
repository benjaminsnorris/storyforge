"""storyforge audit — the ledger digest, and marking facts seen or rejected.

Usage:
    storyforge audit                           # the per-act digest
    storyforge audit --act 2                   # one act
    storyforge audit --character dorren-hayle  # facts about / known by one character
    storyforge audit --scenes act1-sc01..act1-sc03
    storyforge audit --thread map-anomaly      # facts from scenes carrying a MICE thread
    storyforge audit --all                     # every act at once
    storyforge audit --mark seen fact-a fact-b
    storyforge audit --mark seen all --act 1   # every fact the listing shows
    storyforge audit --mark rejected fact-c
    storyforge audit --json

Rethink plan decision 2 (`docs/plans/2026-10-28-storyforge-rethink.md`). The
digest lists binding facts in `reference/commitments.csv` whose `reviewed` is
blank, in tiers (`fixed` facts, then relationship and knowledge, then
physical state, then other state facts), grouped by subject within each.

With no scope it is the per-act digest: the earliest act, in reading order,
with an unreviewed fact, plus any unreviewed fact with no scene (it holds
from before scene 1). Marking that act's facts is what moves the digest on
to the next. Facts with `origin=migrated` (moved from knowledge.csv and
physical-states.csv) are left out unless `--include-migrated`: they predate
the audit, and a first digest of hundreds of them would bury the new ones.

`--mark seen|rejected IDS` sets `reviewed` to `seen:<date>` or
`rejected:<date>` (rejected also sets `status=rejected`), writes through the
ledger (so the marks are in `working/audit-log.csv`), and commits. A rejected
fact's scenes are listed (the briefs that name it) for re-checking; the
dependency graph that finds every scene leaning on it is Phase 4.

The run-time cadence option (`--review-every N`) belongs to Phase 3's gate,
which surfaces digests during a run; this command is the on-demand view.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from storyforge import audit, ledger
from storyforge.common import detect_project_root, install_signal_handlers, log
from storyforge.git import commit_and_push, ensure_on_branch


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge audit',
        description='List the ledger facts waiting for review (per act by '
                    'default), or mark facts seen or rejected.')
    scope = parser.add_argument_group('scope (combine to narrow)')
    scope.add_argument('--act', help='Facts established in scenes of this act '
                       '(scenes.csv `act`)')
    scope.add_argument('--character', metavar='ID',
                       help='Facts whose subject is this id or that it knows (known_by)')
    scope.add_argument('--scenes', metavar='A..B',
                       help='Facts established from scene A to scene B in reading '
                            'order (one id for a single scene)')
    scope.add_argument('--thread', metavar='ID',
                       help='Facts established in scenes whose scene-intent '
                            '`mice_threads` carries this thread')
    scope.add_argument('--all', action='store_true', dest='all_acts',
                       help='Every act at once instead of the per-act digest')
    scope.add_argument('--include-reviewed', action='store_true',
                       help='Also list facts already reviewed, rejected or superseded')
    scope.add_argument('--include-migrated', action='store_true',
                       help='Also list facts moved in from knowledge.csv / '
                            'physical-states.csv')
    parser.add_argument('--mark', choices=audit.VERDICTS,
                        help='Mark the IDS (or `all`: every fact the listing shows)')
    parser.add_argument('ids', nargs='*', metavar='IDS',
                        help='Fact ids to mark (space- or comma-separated), or `all`')
    parser.add_argument('--dry-run', action='store_true',
                        help='With --mark: say what would be marked, change nothing')
    parser.add_argument('--json', action='store_true', dest='json_output',
                        help='Emit JSON')
    args = parser.parse_args(argv)
    args.ids = [i.strip() for a in args.ids for i in a.split(',') if i.strip()]
    if args.ids and not args.mark:
        parser.error('fact ids are only taken with --mark seen|rejected')
    if args.mark and not args.ids:
        parser.error('--mark needs fact ids, or `all`')
    return args


def _scope(args) -> audit.Scope:
    scenes = None
    if args.scenes:
        a, sep, b = args.scenes.partition('..')
        scenes = (a.strip(), (b if sep else a).strip())
    return audit.Scope(character=args.character, scenes=scenes, thread=args.thread,
                       act=args.act, all_acts=args.all_acts,
                       include_reviewed=args.include_reviewed,
                       include_migrated=args.include_migrated)


def _fact_json(r: dict) -> dict:
    keys = ('id', 'scene_id', 'type', 'subject', 'statement', 'quote', 'mutable',
            'status', 'reviewed', 'origin', 'introduced_by', 'known_by', 'supersedes')
    return {k: r.get(k, '') for k in keys} | {'tier': audit.tier_of(r)}


def render(digest: audit.Digest, *, include_reviewed: bool = False) -> str:
    n = len(digest.facts)
    what = '' if include_reviewed else ' to review'
    lines = [f'Audit: {digest.title} — {n} fact{"" if n == 1 else "s"}{what}'
             if n else f'Audit: {digest.title} — nothing{what or " in scope"}']
    for note in digest.notes:
        lines.append(f'  ({note})')
    for g in audit.group(digest.facts):
        count = sum(len(s['facts']) for s in g['subjects'])
        lines += ['', f'{g["label"].upper()} ({count})']
        for s in g['subjects']:
            lines.append(f'  {s["subject"] or "(no subject)"}')
            for r in s['facts']:
                where = r.get('scene_id') or 'before scene 1'
                extra = ', '.join(filter(None, [
                    where, r.get('type', ''), r.get('introduced_by', ''),
                    r.get('status', '') if r.get('status') != 'binding' else '',
                    r.get('reviewed', '')]))
                lines.append(f'    {r["id"]}: {r.get("statement", "")}')
                lines.append(f'      [{extra}]')
    if digest.remaining:
        later = ', '.join(f'act {a or "(none)"}: {c}' for a, c in digest.remaining.items())
        lines += ['', f'Still to review after this act — {later}']
    if n:
        lines += ['', 'Mark them: storyforge audit --mark seen all'
                  + (f' --act {digest.act}' if digest.act else '')
                  + '   (or --mark seen|rejected ID ...)']
    return '\n'.join(lines)


def _fail(message: str) -> None:
    log(f'ERROR: {message}')
    raise SystemExit(1)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()
    project_dir = detect_project_root()
    ledger.exit_if_not_migrated(project_dir)
    rows = ledger.load(project_dir)
    try:
        order = ledger.scene_order(project_dir)
    except ValueError as e:
        _fail(f'reading order: {e}')
    scope = _scope(args)
    if args.mark and args.ids != ['all'] and not scope.narrowed():
        # Explicit ids: no per-act narrowing hides one from the listing
        scope.all_acts = True
    try:
        digest = audit.select(rows, project_dir, scope, order)
    except audit.ScopeError as e:
        _fail(str(e))

    if not args.mark:
        if args.json_output:
            print(json.dumps({
                'title': digest.title, 'act': digest.act, 'notes': digest.notes,
                'remaining': digest.remaining,
                'facts': [_fact_json(r) for r in digest.facts],
                'groups': [{'tier': g['tier'], 'label': g['label'],
                            'subjects': [{'subject': s['subject'],
                                          'facts': [r['id'] for r in s['facts']]}
                                         for s in g['subjects']]}
                           for g in audit.group(digest.facts)],
            }, indent=2))
        else:
            print(render(digest, include_reviewed=args.include_reviewed))
        return

    if 'all' in args.ids:
        if args.ids != ['all']:
            _fail('`all` marks every fact the listing shows; give it alone')
        ids = [r['id'] for r in digest.facts]
    else:
        ids = args.ids
    if not ids:
        print(f'Audit: {digest.title} — nothing to mark')
        return
    try:
        changed = audit.mark(rows, ids, args.mark)
    except ValueError as e:
        _fail(str(e))
    recheck = audit.leaning_scenes(project_dir, changed) if args.mark == 'rejected' else {}
    if not args.dry_run and changed:
        ensure_on_branch('audit', project_dir)
        ledger.save(project_dir, rows, command='audit')
        commit_and_push(project_dir,
                        f'Audit: mark {len(changed)} fact{"" if len(changed) == 1 else "s"} '
                        f'{args.mark}',
                        [f'reference/{ledger.LEDGER_FILE}', audit.LOG_PATH])
    if args.json_output:
        print(json.dumps({'verdict': args.mark, 'marked': changed,
                          'dry_run': args.dry_run, 'recheck': recheck}, indent=2))
        return
    verb = 'Would mark' if args.dry_run else 'Marked'
    print(f'{verb} {len(changed)} fact{"" if len(changed) == 1 else "s"} {args.mark}'
          + (f': {", ".join(changed)}' if changed else ' (already marked)'))
    for fid, scenes in recheck.items():
        print(f'  {fid}: ' + (f'named by the briefs of {", ".join(scenes)} — re-check them'
                              if scenes else 'no brief names it'))
