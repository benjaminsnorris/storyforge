"""storyforge bibles — the bibles as facts, not essays (#657, `storyforge.bibles`).

Usage:
    storyforge bibles                     # where the bibles stand, and the plan's gaps
    storyforge bibles import FACTS [--voices FILE] [--notes FILE]
    storyforge bibles retire NAME [--force]

`import` adds a pipe-delimited file of facts (`type|subject|statement`, and
optionally `known_by`, `scene_id`, `category`, `id`) to the ledger as plan
facts; `--voices` adds `character|line` rows to character-voices.csv and
`--notes` appends a file to bible-notes.md. `retire` moves a converted essay
(character-bible.md, world-bible.md, systems-bible.md) to reference/archive/,
where nothing reads it. Both take --dry-run and --no-commit, and commit and
push otherwise. No API calls.
"""

from __future__ import annotations

import argparse
import os
import sys

from storyforge.common import detect_project_root, install_signal_handlers, log


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge bibles',
        description='The character, world and systems bibles as rows: status and the '
                    "plan's gaps (the two-writers test), import facts, retire an essay.")
    sub = parser.add_subparsers(dest='action')
    sub.add_parser('status', help="Where the bibles stand, and the plan's gaps (the default)")
    imp = sub.add_parser('import', help='Add facts (and voices, notes) from files')
    imp.add_argument('facts', nargs='?', default='',
                     help='Pipe-delimited facts: type|subject|statement[|known_by|scene_id|category|id]')
    imp.add_argument('--voices', default='', help='character|line rows for character-voices.csv')
    imp.add_argument('--notes', default='', help='A file of terse notes to append to bible-notes.md')
    ret = sub.add_parser('retire', help='Move a converted essay to reference/archive/')
    ret.add_argument('name', help='character-bible.md, world-bible.md or systems-bible.md')
    ret.add_argument('--force', action='store_true',
                     help='Retire it even with no rows of its types in the ledger')
    for p in (imp, ret):
        p.add_argument('--dry-run', action='store_true', help='Say what would change; write nothing')
        p.add_argument('--no-commit', action='store_true', help='Write, but don\'t commit')
    return parser.parse_args(argv)


def _status(project_dir: str) -> int:
    from storyforge import bibles, ledger
    for name in bibles.ESSAYS:
        state = bibles.essay_state(project_dir, name)
        print({'essay': f'{name}: an essay, still read (convert it, then retire it)',
               'retired': f'{name}: retired to {bibles.ARCHIVE_DIR}/ (read by nothing)',
               'template': f'{name}: the template, unfilled (read by nothing)',
               'none': f'{name}: none'}[state])
    try:
        rows = ledger.load(project_dir)
    except ledger.LedgerError as e:
        print(f'ERROR: the ledger can\'t be read: {e}')
        return 1
    facts = [r for r in rows if bibles.is_bible_fact(r)]
    by_type = {t: sum(r['type'] == t for r in facts) for t in bibles.FACT_TYPES}
    print(f'Facts: {len(facts)} ('
          + ', '.join(f'{n} {t}' for t, n in by_type.items()) + ')'
          + f', {len(bibles.standing_facts(rows))} true from the start')
    voices, problems = bibles.read_voices(project_dir)
    print(f'Voices: {sum(map(len, voices.values()))} line(s) for {len(voices)} character(s)')
    for p in problems:
        print(f'  WARNING: {p}')
    print(f'Notes: {"reference/" + bibles.NOTES_FILE if bibles.notes_text(project_dir) else "none"}')
    gaps, notes = bibles.plan_gaps(os.path.join(project_dir, 'reference'))
    print()
    print(f'The two-writers test: {len(gaps)} gap(s)' + (':' if gaps else ''))
    for g in gaps:
        print(f'  {g.message()}')
    for n in notes:
        print(f'  NOTE: {n}')
    return 0


def _commit(project_dir: str, args, message: str, paths: list[str]) -> None:
    from storyforge.git import commit_and_push, ensure_on_branch
    if args.dry_run:
        log('Dry run: nothing was written.')
        return
    if args.no_commit:
        log('Written, not committed (--no-commit).')
        return
    ensure_on_branch('bibles', project_dir)
    if commit_and_push(project_dir, message, paths):
        log('Committed.')


def _import(project_dir: str, args) -> int:
    from storyforge import bibles
    if not (args.facts or args.voices or args.notes):
        log('ERROR: nothing to import: give a facts file, --voices or --notes')
        return 1
    paths, said = [], []
    try:
        if args.facts:
            items = bibles.read_import(args.facts)
            added, notes = bibles.add_facts(project_dir, items, command='bibles',
                                            dry_run=args.dry_run)
            for n in notes:
                log(f'NOTE: {n}')
            log(f'Facts: {len(added)} added to reference/commitments.csv'
                + (' (dry run)' if args.dry_run else ''))
            if added:
                paths += ['reference/commitments.csv', 'working/audit-log.csv',
                          'working/.audit-snapshot.csv']
                said.append(f'{len(added)} fact(s)')
        if args.voices:
            lines = bibles.read_voice_import(args.voices)
            before = sum(map(len, bibles.read_voices(project_dir)[0].values()))
            for n in bibles.add_voices(project_dir, lines, dry_run=args.dry_run):
                log(f'NOTE: {n}')
            after = sum(map(len, bibles.read_voices(project_dir)[0].values()))
            log(f'Voices: {after - before} line(s) added to reference/{bibles.VOICES_FILE}'
                + (' (dry run)' if args.dry_run else ''))
            if after > before:
                paths.append(f'reference/{bibles.VOICES_FILE}')
                said.append('voices')
        if args.notes:
            if not os.path.isfile(args.notes):
                raise bibles.BiblesError(f'{args.notes} doesn\'t exist')
            with open(args.notes, encoding='utf-8-sig') as f:
                text = f.read()
            if bibles.add_notes(project_dir, text, dry_run=args.dry_run):
                log(f'Notes: appended to reference/{bibles.NOTES_FILE}'
                    + (' (dry run)' if args.dry_run else ''))
                paths.append(f'reference/{bibles.NOTES_FILE}')
                said.append('notes')
            else:
                log(f'NOTE: {args.notes} is empty; no notes added')
    except bibles.BiblesError as e:
        log(f'ERROR: {e}')
        return 1
    if paths:
        _commit(project_dir, args, f'Bibles: import {", ".join(said)}', paths)
    return 0


def _retire(project_dir: str, args) -> int:
    from storyforge import bibles
    try:
        dest = bibles.retire(project_dir, args.name, force=args.force, dry_run=args.dry_run)
    except bibles.BiblesError as e:
        log(f'ERROR: {e}')
        return 1
    log(f'reference/{args.name} → {dest}' + (' (dry run)' if args.dry_run else '')
        + ': Storyforge no longer reads it; the rows stand in for it')
    _commit(project_dir, args, f'Bibles: retire {args.name}',
            [f'reference/{args.name}', dest])
    return 0


def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()
    project_dir = detect_project_root()
    from storyforge import ledger
    ledger.exit_if_not_migrated(project_dir)
    action = args.action or 'status'
    code = {'status': lambda: _status(project_dir),
            'import': lambda: _import(project_dir, args),
            'retire': lambda: _retire(project_dir, args)}[action]()
    if code:
        sys.exit(code)
