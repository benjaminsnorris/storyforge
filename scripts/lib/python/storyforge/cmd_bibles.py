"""storyforge bibles — the bibles as facts, not essays (#657, `storyforge.bibles`).

Usage:
    storyforge bibles                     # where the bibles stand, and the plan's gaps
    storyforge bibles import FACTS [--essay NAME] [--voices FILE] [--notes FILE]
    storyforge bibles retire NAME [--force]

`import` adds a pipe-delimited file of facts, with a header row (type,
subject, statement required; known_by, scene_id, category, id optional), to
the ledger as plan facts; `--essay NAME` marks them as that essay's
conversion, which `retire` asks for. `--voices` adds `character|line` rows to
character-voices.csv and `--notes` appends a file's new lines to
bible-notes.md. Every input is read and checked before anything is written,
so a bad file writes nothing. `retire` moves a converted essay
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
    from storyforge.bibles import ESSAYS
    parser = argparse.ArgumentParser(
        prog='storyforge bibles',
        description='The character, world and systems bibles as rows: status and the '
                    "plan's gaps (the two-writers test), import facts, retire an essay.")
    sub = parser.add_subparsers(dest='action')
    sub.add_parser('status', help="Where the bibles stand, and the plan's gaps (the default)")
    imp = sub.add_parser('import', help='Add facts (and voices, notes) from files')
    imp.add_argument('facts', nargs='?', default='',
                     help='A pipe-delimited file with a header row: type, subject, statement '
                          '(required), and optionally known_by, scene_id, category, id')
    imp.add_argument('--essay', choices=ESSAYS, default='',
                     help='The essay these facts convert (retire asks for its conversion)')
    imp.add_argument('--voices', default='', help='character|line rows for character-voices.csv')
    imp.add_argument('--notes', default='',
                     help='A file of terse notes; its lines bible-notes.md lacks are appended')
    ret = sub.add_parser('retire', help='Move a converted essay to reference/archive/')
    ret.add_argument('name', help='character-bible.md, world-bible.md or systems-bible.md')
    ret.add_argument('--force', action='store_true',
                     help='Retire it even though it isn\'t converted')
    for p in (imp, ret):
        p.add_argument('--dry-run', action='store_true', help='Say what would change; write nothing')
        p.add_argument('--no-commit', action='store_true', help='Write, but don\'t commit')
    return parser.parse_args(argv)


def _status(project_dir: str) -> int:
    from storyforge import bibles, ledger
    from storyforge.common import ReferenceDocError
    for name in bibles.ESSAYS:
        state = bibles.essay_state(project_dir, name)
        print({'essay': f'{name}: an essay, still read (convert it, then retire it)',
               'retired': f'{name}: retired to {bibles.ARCHIVE_DIR}/ (read by nothing)',
               'template': f'{name}: the template, unfilled (read by nothing)',
               'none': f'{name}: none'}[state])
    try:
        rows = ledger.load(project_dir)
        voices, problems = bibles.read_voices(project_dir)
        notes_doc = bibles.notes_text(project_dir)
    except (ledger.LedgerError, ReferenceDocError) as e:
        print(f'ERROR: {e}')
        return 1
    facts = [r for r in rows if bibles.is_bible_fact(r)]
    secrets = [r for r in rows if bibles.is_plan_fact(r) and r.get('type') == 'knowledge']
    by_type = {t: sum(r['type'] == t for r in facts) for t in bibles.FACT_TYPES}
    print(f'Facts: {len(facts)} ('
          + ', '.join(f'{n} {t}' for t, n in by_type.items()) + ')'
          + f', {len(bibles.standing_facts(rows))} true from the start; '
          + f'{len(secrets)} planned knowledge fact(s)')
    print(f'Voices: {sum(map(len, voices.values()))} line(s) for {len(voices)} character(s)')
    for p in problems:
        print(f'  WARNING: {p}')
    print(f'Notes: {"reference/" + bibles.NOTES_FILE if notes_doc else "none"}')
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
    from storyforge import bibles, ledger
    from storyforge.common import ReferenceDocError
    if not (args.facts or args.voices or args.notes):
        log('ERROR: nothing to import: give a facts file, --voices or --notes')
        return 1
    if args.essay and not args.facts:
        log('ERROR: --essay names the essay a facts file converts; give the facts file')
        return 1
    writer = bibles.essay_writer(args.essay) if args.essay else bibles.WRITER
    # Read and check every input before writing any (#697's review CR-2): a
    # bad voices or notes file must not leave the facts written uncommitted
    try:
        items = bibles.read_import(args.facts) if args.facts else []
        lines = bibles.read_voice_import(args.voices) if args.voices else []
        notes_doc = ''
        if args.notes:
            if not os.path.isfile(args.notes):
                raise bibles.BiblesError(f'{args.notes} doesn\'t exist')
            try:
                with open(args.notes, encoding='utf-8-sig') as f:
                    notes_doc = f.read()
            except (OSError, UnicodeDecodeError) as e:
                raise bibles.BiblesError(f'{args.notes} can\'t be read as UTF-8 text ({e})') from e
        added, fact_notes = bibles.add_facts(project_dir, items, command='bibles',
                                             writer=writer, dry_run=True)
        voiced, voice_notes = (bibles.add_voices(project_dir, lines, dry_run=True)
                               if lines else (0, []))
        noted = bibles.add_notes(project_dir, notes_doc, dry_run=True) if notes_doc else 0
        if not args.dry_run:
            if added:
                bibles.add_facts(project_dir, items, command='bibles', writer=writer)
            if voiced:
                bibles.add_voices(project_dir, lines)
            if noted:
                bibles.add_notes(project_dir, notes_doc)
    except bibles.BiblesError as e:
        log(f'ERROR: {e}')
        return 1
    except (ledger.LedgerError, ReferenceDocError) as e:
        log(f'ERROR: {e}; nothing was added')
        return 1
    dry = ' (dry run)' if args.dry_run else ''
    for n in fact_notes + voice_notes:
        log(f'NOTE: {n}')
    paths, said = [], []
    if args.facts:
        log(f'Facts: {len(added)} added to reference/commitments.csv'
            + (f' as the conversion of {args.essay}' if args.essay else '') + dry)
        if added:
            paths += ['reference/commitments.csv', 'working/audit-log.csv',
                      'working/.audit-snapshot.csv']
            said.append(f'{len(added)} fact(s)')
    if args.voices:
        log(f'Voices: {voiced} line(s) added to reference/{bibles.VOICES_FILE}{dry}')
        if voiced:
            paths.append(f'reference/{bibles.VOICES_FILE}')
            said.append('voices')
    if args.notes:
        log(f'Notes: {noted} line(s) appended to reference/{bibles.NOTES_FILE}{dry}')
        if noted:
            paths.append(f'reference/{bibles.NOTES_FILE}')
            said.append('notes')
    if paths:
        _commit(project_dir, args, f'Bibles: import {", ".join(said)}', paths)
    return 0


def _retire(project_dir: str, args) -> int:
    from storyforge import bibles
    try:
        dest, notes = bibles.retire(project_dir, args.name, force=args.force,
                                    dry_run=args.dry_run)
    except bibles.BiblesError as e:
        log(f'ERROR: {e}')
        return 1
    for n in notes:
        log(f'NOTE: {n}')
    log(f'reference/{args.name} → {dest}' + (' (dry run)' if args.dry_run else '')
        + ': Storyforge no longer reads it; the rows stand in for it')
    _commit(project_dir, args, f'Bibles: retire {args.name}',
            [f'reference/{args.name}', dest, 'storyforge.yaml'])
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
