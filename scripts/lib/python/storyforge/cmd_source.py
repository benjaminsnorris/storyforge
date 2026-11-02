"""storyforge source — the project's source, for an adaptation (#477).

A project with a `source:` block in storyforge.yaml adapts another Storyforge
project. `source import` copies each source into `reference/source/<slug>/`
with the name map applied and writes its source bible. Deterministic: no
model calls.

Usage:
    storyforge source import               # Every source in storyforge.yaml
    storyforge source import --slug iliad  # One of them
    storyforge source import --dry-run     # Say what would change; write nothing
    storyforge source import --no-commit   # Write, don't commit
    storyforge source status               # The source block and coverage lines
"""

import argparse
import sys

from storyforge.common import detect_project_root, install_signal_handlers, log


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge source',
        description="Import and inspect the project's source (an adaptation).")
    sub = parser.add_subparsers(dest='action', required=True)
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
    if args.dry_run or not changed:
        return 0
    if args.no_commit:
        log('Written, not committed (--no-commit).')
        return 0
    from storyforge.git import commit_and_push, ensure_on_branch
    ensure_on_branch('source-import', project_dir)
    if not commit_and_push(project_dir, f'Source: import {", ".join(changed)}',
                           [f'reference/source/{s}' for s in changed]):
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
            + (f', name map {p.name_map}' if p.name_map else ''))
    result = source.check_coverage(project_dir, cfg)
    for line in result['lines']:
        log(line)
    for f in result['findings']:
        where = f' {f["scene_id"]}:' if f['scene_id'] else ''
        log(f'  [{f["severity"]}]{where} {f["message"]}')
    return 1 if any(f['severity'] == 'blocking' for f in result['findings']) else 0
