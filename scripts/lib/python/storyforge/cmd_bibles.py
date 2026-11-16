"""storyforge bibles — the bibles as facts, not essays (#657, `storyforge.bibles`).

Usage:
    storyforge bibles                     # where the bibles stand, and the plan's gaps
    storyforge bibles import FACTS [--essay NAME] [--voices FILE] [--notes FILE]
    storyforge bibles retire NAME [--force]
    storyforge bibles voices              # lines from the voice anchors
    storyforge bibles convert NAME [--import] [--model M]   # paid: an essay into rows

`import` adds a pipe-delimited file of facts, with a header row (type,
subject, statement required; known_by, scene_id, category, id optional), to
the ledger as plan facts; `--essay NAME` marks them as that essay's
conversion, which `retire` asks for. `--voices` adds `character|line` rows to
character-voices.csv and `--notes` appends a file's new lines to
bible-notes.md. Every input is read and checked before anything is written,
so a bad file writes nothing. `retire` moves a converted essay
(character-bible.md, world-bible.md, systems-bible.md) to reference/archive/,
where nothing reads it. `voices` adds the lines each character speaks in
the voice anchors (reference/voice/anchors/, passages the author wrote or
chose) to character-voices.csv: a voice line is the author's, never a
model's (#702). `convert` (#702, `storyforge.bibles_convert`) is the one
paid action: one call turns an essay into facts, the lines it quotes and
notes, written to working/bibles/<essay>/ for the author to read before
`import ... --essay NAME`, or imported at once with `--import`. Each takes
--dry-run (no call, for convert: the forecast) and --no-commit, and commits
and pushes what it writes otherwise (convert only with --import: its
review files are in working/, which isn't committed).
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
                    "plan's gaps (the two-writers test), import facts, retire an essay, "
                    'voice lines from the anchors, convert an essay (paid).')
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
    voi = sub.add_parser('voices', help="Add each character's lines from the voice anchors "
                                        'to character-voices.csv')
    con = sub.add_parser('convert', help='Paid: turn an essay into rows with one model call '
                                         '(written for review; --import to import them)')
    con.add_argument('name', choices=ESSAYS, help='The essay to convert')
    con.add_argument('--import', dest='do_import', action='store_true',
                     help='Import the rows at once as the essay\'s conversion')
    con.add_argument('--model', default='', help='The model (default: the evaluation tier)')
    con.add_argument('--overwrite', action='store_true',
                     help='Replace the review files an earlier convert left (and any edits '
                          'made to them)')
    for p in (imp, ret, voi, con):
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
    if not (args.facts or args.voices or args.notes):
        log('ERROR: nothing to import: give a facts file, --voices or --notes')
        return 1
    if args.essay and not args.facts:
        log('ERROR: --essay names the essay a facts file converts; give the facts file')
        return 1
    return _import_files(project_dir, args)


def _import_files(project_dir: str, args) -> int:
    """Import `args.facts` / `args.voices` / `args.notes` (any may be ''),
    the facts as `args.essay`'s conversion when it's set."""
    from storyforge import bibles, ledger
    from storyforge.common import ReferenceDocError
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


def _voices(project_dir: str, args) -> int:
    from storyforge import bibles
    from storyforge.common import ReferenceDocError
    try:
        lines, notes = bibles.anchor_voices(project_dir)
        pairs = [(v.character, v.line) for v in lines]
        added, add_notes = (bibles.add_voices(project_dir, pairs, dry_run=True)
                            if pairs else (0, []))
        if added and not args.dry_run:
            bibles.add_voices(project_dir, pairs)
    except bibles.BiblesError as e:
        log(f'ERROR: {e}')
        return 1
    except ReferenceDocError as e:
        log(f'ERROR: {e}; nothing was added')
        return 1
    for n in notes + add_notes:
        log(f'NOTE: {n}')
    if not lines:
        log('No voice line found in the anchors: nothing to add')
        return 0
    for v in lines:
        log(f'  {v.character}: {v.line[:70]!r} ({v.source})')
    dry = ' (dry run)' if args.dry_run else ''
    log(f'Voices: {added} line(s) added to reference/{bibles.VOICES_FILE} from the anchors{dry}')
    if added:
        _commit(project_dir, args, 'Bibles: voice lines from the anchors',
                [f'reference/{bibles.VOICES_FILE}'])
    return 0


def _convert(project_dir: str, args) -> int:
    import argparse as _argparse
    from storyforge import api, bibles_convert as bc
    from storyforge.common import ReferenceDocError, select_model
    from storyforge.costs import check_threshold, cost_threshold, exit_if_bad_threshold
    exit_if_bad_threshold()
    try:
        essay = bc.essay_text(project_dir, args.name)
        prompt = bc.build_prompt(args.name, essay, bc._registry(project_dir, 'characters.csv'),
                                 bc._registry(project_dir, 'locations.csv'))
        model = args.model or select_model(bc.MODEL_TASK)
    except (bc.ConvertError, ReferenceDocError) as e:
        log(f'ERROR: {e}')
        return 1
    earlier = bc.existing_review(project_dir, args.name)
    if earlier and not args.overwrite:
        log(f'ERROR: an earlier conversion is still in {os.path.relpath(os.path.dirname(earlier[0]), project_dir)}/ '
            f'(edited, maybe): import it, move it, or pass --overwrite; no call made')
        return 1
    cost = bc.forecast(model, prompt)
    log(f'Converting reference/{args.name} with {model}: one call, about ${cost:.2f}')
    if args.dry_run:
        log('Dry run: no call made, nothing written.')
        return 0
    if not check_threshold(cost):
        log(f'ERROR: the forecast ${cost:.2f} is over the cost threshold '
            f'(${cost_threshold():.2f}); nothing sent')
        return 1
    log_file = os.path.join(project_dir, 'working', 'logs',
                            f'bibles-convert-{os.path.splitext(args.name)[0]}.json')
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    if os.path.exists(log_file):
        os.remove(log_file)   # an older reply must never be named as this one's
    try:
        conv, response = bc.convert(project_dir, args.name, model, log_file)
    except (bc.ConvertError, ReferenceDocError) as e:
        if getattr(e, 'response', None):
            api.log_reply(project_dir, e.response, 'bibles-convert', args.name, model)
        log(f'ERROR: {e}; nothing written'
            + (f' (the reply is in {os.path.relpath(log_file, project_dir)})'
               if os.path.isfile(log_file) else ''))
        return 1
    except RuntimeError as e:
        log(f'ERROR: the call failed ({e}); nothing written')
        return 1
    spent = api.log_reply(project_dir, response, 'bibles-convert', args.name, model)
    try:
        written, removed = bc.write_review(project_dir, conv)
    except OSError as e:
        log(f'ERROR: the review files could not be written ({e}); the reply is in '
            f'{os.path.relpath(log_file, project_dir)}')
        return 1
    for path in removed:
        log(f'  removed {os.path.relpath(path, project_dir)} (the earlier conversion\'s; this '
            f'one has none of that kind)')
    log(f'{len(conv.facts)} fact(s), {len(conv.voices)} voice line(s), {len(conv.notes)} '
        f'note(s) (${spent:.2f})')
    for item in conv.left_out:
        log(f'  left out: {item}')
    for kind, path in written.items():
        log(f'  {kind}: {os.path.relpath(path, project_dir)}')
    if not (conv.facts or conv.voices or conv.notes):
        log(f'WARNING: the reply gave nothing to import from reference/{args.name}')
        return 1
    paths = bc.review_paths(project_dir, args.name)
    if not args.do_import:
        rel = {k: os.path.relpath(v, project_dir) for k, v in paths.items()}
        cmd = ['storyforge bibles import', rel['facts'] if 'facts' in written else '']
        cmd += [f'--essay {args.name}'] if 'facts' in written else []
        cmd += [f'--voices {rel["voices"]}'] if 'voices' in written else []
        cmd += [f'--notes {rel["notes"]}'] if 'notes' in written else []
        log('Read and edit them, then import: ' + ' '.join(c for c in cmd if c))
        return 0
    imp = _argparse.Namespace(facts=written.get('facts', ''), voices=written.get('voices', ''),
                              notes=written.get('notes', ''),
                              essay=args.name if 'facts' in written else '',
                              dry_run=False, no_commit=args.no_commit)
    return _import_files(project_dir, imp)


def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()
    project_dir = detect_project_root()
    from storyforge import ledger
    ledger.exit_if_not_migrated(project_dir)
    action = args.action or 'status'
    code = {'status': lambda: _status(project_dir),
            'import': lambda: _import(project_dir, args),
            'retire': lambda: _retire(project_dir, args),
            'voices': lambda: _voices(project_dir, args),
            'convert': lambda: _convert(project_dir, args)}[action]()
    if code:
        sys.exit(code)
