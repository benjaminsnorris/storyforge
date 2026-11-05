"""storyforge source — the project's source: a text to extract, or (#477)
the projects it adapts.

`source fetch` makes the project's manuscript from a Project Gutenberg text
(`storyforge.gutenberg`): it downloads the ebook, strips the Gutenberg
boilerplate and normalizes it into `manuscript.md`, ready for
`scenes-setup --split-manuscript`. The config is `reference/gutenberg.json`
(or `--meta`); with `verse` set, the text's line breaks survive.

A project with a `source:` block in storyforge.yaml adapts another Storyforge
project. `source import` copies each source into `reference/source/<slug>/`
with the name map applied and writes its source bible. Deterministic: no
model calls.

Usage:
    storyforge source fetch                # reference/gutenberg.json -> manuscript.md
    storyforge source fetch --meta m.json --gutenberg 981 --verse
    storyforge source fetch --input pg981.txt   # A local copy of the raw text
    storyforge source import               # Every source in storyforge.yaml
    storyforge source import --slug iliad  # One of them
    storyforge source import --dry-run     # Say what would change; write nothing
    storyforge source import --no-commit   # Write, don't commit
    storyforge source status               # The source block and coverage lines
"""

import argparse
import os
import sys

from storyforge.common import detect_project_root, install_signal_handlers, log


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge source',
        description="Import and inspect the project's source (an adaptation).")
    sub = parser.add_subparsers(dest='action', required=True)
    fetch = sub.add_parser(
        'fetch', help='Make manuscript.md from a Project Gutenberg text')
    fetch.add_argument('--meta', help='JSON config (default: reference/gutenberg.json)')
    fetch.add_argument('--gutenberg', metavar='ID',
                       help="The ebook number (overrides the config's gutenberg_id)")
    mode = fetch.add_mutually_exclusive_group()
    mode.add_argument('--verse', dest='verse', action='store_true', default=None,
                      help='Keep line breaks and stanzas (sets verse in the config)')
    mode.add_argument('--prose', dest='verse', action='store_false',
                      help='Join each paragraph onto one line (the default)')
    fetch.add_argument('--input', help='Read the raw text from this file, not Gutenberg')
    fetch.add_argument('--refresh', action='store_true',
                       help='Download again even when working/gutenberg/ has the text')
    fetch.add_argument('--force', action='store_true',
                       help='Replace a manuscript.md that differs')
    fetch.add_argument('--dry-run', action='store_true',
                       help='Say what would change; write nothing')
    fetch.add_argument('--no-commit', action='store_true',
                       help='Write the files but do not commit them')
    imp = sub.add_parser('import', help='Copy each source into reference/source/<slug>/')
    imp.add_argument('--slug', help='Import only this source')
    imp.add_argument('--dry-run', action='store_true',
                     help='Say what would change; write nothing')
    imp.add_argument('--no-commit', action='store_true',
                     help='Write the files but do not commit them')
    sub.add_parser('status', help='Show the source block and coverage')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()
    project_dir = detect_project_root()

    if args.action == 'fetch':
        return _fetch(project_dir, args)

    from storyforge import source
    try:
        cfg = source.read_config(project_dir)
    except source.SourceError as e:
        log(f'ERROR: {e}')
        return 1
    if cfg is None:
        log('ERROR: storyforge.yaml has no `source:` block; this project adapts '
            'nothing (see references/storyforge-yaml-schema.md, `source`)')
        return 1

    if args.action == 'status':
        return _status(project_dir, cfg)

    slugs = [args.slug] if args.slug else cfg.slugs()
    # Every source is built before any is written, so a failure on the
    # second source leaves the first as it was
    results = []
    for slug in slugs:
        try:
            results.append(source.plan_import(project_dir, cfg, slug))
        except source.SourceError as e:
            log(f'ERROR: {e}')
            log('Nothing was written.')
            return 1
    for r in results:
        if not args.dry_run:
            source.write_import(r)
        verb = ('would change' if args.dry_run else 'updated') if r.changed else 'unchanged'
        log(f'Source {r.slug} ({r.source_path}): {verb}; reference/source/{r.slug}/ holds '
            f'{len(r.files)} files, {r.prose_files} of them scene prose')
        if r.missing:
            log(f'  Not in the source, so not copied: {", ".join(r.missing)}')
        for note in r.notes:
            log(f'  NOTE: {note}')

    changed = [r.slug for r in results if r.changed]
    if args.dry_run:
        return 0
    # An adaptation's empty registries start as the source's cast, places
    # and values (B-013); a ranged source gives only what its range uses
    try:
        seeded, notes = source.seed_registries(project_dir, cfg)
    except source.SourceError as e:
        log(f'ERROR: {e}')
        log('The import is written but not committed, and the registries '
            'were not seeded; fix this and re-run `storyforge source import`')
        return 1
    for sd in seeded:
        part = (f' ({sd.available - sd.written} of its {sd.available} aren\'t named by '
                f'any scene in the range, so left out)' if sd.available > sd.written else '')
        log(f'Seeded {sd.path} with {sd.written} row(s) from the source (it had none){part}')
    for note in notes:
        log(f'  {note}')
    if not changed and not seeded:
        return 0
    if args.no_commit:
        log('Written, not committed (--no-commit).')
        return 0
    from storyforge.git import commit_and_push, ensure_on_branch
    ensure_on_branch('source-import', project_dir)
    message = (f'Source: import {", ".join(changed)}' if changed
               else 'Source: seed the registries')
    if not commit_and_push(project_dir, message,
                           [f'reference/source/{s}' for s in changed]
                           + [sd.path for sd in seeded]):
        log('ERROR: the import is written but the commit failed; commit '
            'reference/source/ yourself')
        return 1
    return 0


def _status(project_dir: str, cfg) -> int:
    from storyforge import source
    log(f'Mode: {cfg.mode}')
    log(f'Name map: {cfg.name_map or "(none)"}')
    log(f'Rules: {cfg.rules or "(none)"}')
    for p in cfg.projects:
        state = 'imported' if source.is_imported(project_dir, p.slug) else 'not imported'
        log(f'Source {p.slug}: {p.path} ({state})'
            + (f', name map {p.name_map}' if p.name_map else '')
            + (f', adapting {p.range.describe()}' if p.range else ''))
    result = source.check_coverage(project_dir, cfg)
    for line in result['lines']:
        log(line)
    for f in result['findings']:
        where = f' {f["scene_id"]}:' if f['scene_id'] else ''
        log(f'  [{f["severity"]}]{where} {f["message"]}')
    return 1 if any(f['severity'] == 'blocking' for f in result['findings']) else 0


def fetch_config(project_dir: str, meta_path: str | None = None,
                 ebook_id: str | None = None, verse: bool | None = None) -> dict:
    """The fetch config: `meta_path` (default `reference/gutenberg.json`),
    with the command line's ebook number and verse mode applied."""
    from storyforge import gutenberg
    path = meta_path or os.path.join(project_dir, gutenberg.CONFIG_REL)
    if not meta_path and not os.path.isfile(path):
        raise gutenberg.GutenbergError(
            f'no {gutenberg.CONFIG_REL}: pass --meta with the config '
            '(chapter_heading at least; see `storyforge.gutenberg`)')
    meta = dict(gutenberg.read_config(path))
    if ebook_id is not None:
        meta['gutenberg_id'] = int(ebook_id) if str(ebook_id).isdigit() else ebook_id
    if verse is not None:
        if verse:
            meta['verse'] = True
        else:
            meta.pop('verse', None)
    return gutenberg.check_config(meta)


def _fetch(project_dir: str, args) -> int:
    from storyforge import gutenberg
    try:
        meta = fetch_config(project_dir, args.meta, args.gutenberg, args.verse)
        fetched = gutenberg.build(project_dir, meta, input_path=args.input,
                                  refresh=args.refresh)
        changes = gutenberg.plan_writes(project_dir, fetched, force=args.force)
    except gutenberg.GutenbergError as e:
        log(f'ERROR: {e}')
        log('Nothing was written.')
        return 1
    stats = fetched.stats
    label = (f'Gutenberg #{meta["gutenberg_id"]}' if meta.get('gutenberg_id') is not None
             else 'the text')
    log(f'Manuscript from {label} ({"verse" if meta.get("verse") else "prose"}): '
        f'{gutenberg.describe(stats)}')
    if not stats['chapters']:
        log('WARNING: no chapter headings: scenes-setup will see one chapter; '
            'check chapter_heading against the raw text')
    if not changes:
        log('Unchanged: manuscript.md, the config and the raw text are as fetched.')
        return 0
    verb = 'Would write' if args.dry_run else 'Wrote'
    log(f'{verb}: {", ".join(sorted(changes))}')
    for rel in gutenberg.replaced(project_dir, changes):
        log(f'WARNING: {"would replace" if args.dry_run else "replaced"} {rel}, '
            'which differed (git has the old one)')
    if args.dry_run:
        return 0
    gutenberg.write_files(project_dir, changes)
    log('Next: ./storyforge scenes-setup --split-manuscript')
    if args.no_commit:
        log('Written, not committed (--no-commit).')
        return 0
    from storyforge.git import commit_and_push, ensure_on_branch
    ensure_on_branch('source-fetch', project_dir)
    if not commit_and_push(project_dir, f'Source: fetch the manuscript from {label}',
                           sorted(changes)):
        log('ERROR: the manuscript is written but the commit failed; commit '
            f'{", ".join(sorted(changes))} yourself')
        return 1
    return 0
