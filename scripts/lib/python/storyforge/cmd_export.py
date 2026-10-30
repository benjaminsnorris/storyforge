"""storyforge export -- Write the book's structured state as one JSON bundle.

The bundle (plan §3.5; contract in docs/agent-reference.md, "Export bundle")
carries every reference CSV, the ledger, the latest complete score cycle, the
timeline's stored cues, the audit log's CSVs (provisional), the dashboard's
data and the project's metadata, under a `schema_version`. Each table is
stored losslessly, so `export.tables_from_bundle` writes it back
byte-for-byte. Eval results are not part of a book and are not exported.
No API calls; nothing is committed.

Usage:
    storyforge export                 # Write working/export/bundle.json
    storyforge export --output PATH   # Write it somewhere else
    storyforge export --stdout        # Print it (logs go to stderr)
"""

import argparse
import os
import sys

from storyforge.common import detect_project_root, install_signal_handlers, log


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge export',
        description="Write the book's structured state as one JSON bundle.",
    )
    where = parser.add_mutually_exclusive_group()
    where.add_argument('--output', metavar='PATH',
                       help='Write the bundle here (default: working/export/bundle.json)')
    where.add_argument('--stdout', action='store_true',
                       help='Print the bundle to stdout instead of writing a file')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()
    project_dir = detect_project_root()

    from storyforge import export, ledger

    def say(msg):
        if args.stdout:
            print(msg, file=sys.stderr, flush=True)
        else:
            log(msg)

    try:
        bundle = export.build_bundle_quietly(project_dir)
    except ledger.LedgerError as e:
        say(f'ERROR: {e}')
        sys.exit(1)

    for warning in bundle['warnings']:
        say(f'WARNING: {warning}')

    if args.stdout:
        sys.stdout.write(export.dumps(bundle))
        sys.stdout.flush()
    else:
        path = args.output or os.path.join(project_dir, export.DEFAULT_OUTPUT)
        try:
            export.write_bundle(bundle, path)
        except OSError as e:
            say(f'ERROR: could not write the bundle to {path}: {e.strerror or e}')
            sys.exit(1)
        say(f'Export bundle written: {path}')

    kinds: dict[str, int] = {}
    for table in bundle['tables'].values():
        kinds[table['kind']] = kinds.get(table['kind'], 0) + 1
    say(f'  Schema version {bundle["schema_version"]}; tables: '
        + (', '.join(f'{k} {n}' for k, n in sorted(kinds.items())) or 'none'))
    say(f'  Score cycle: {bundle["score_cycle"] or "none"}')
    if bundle['warnings']:
        say(f'  {len(bundle["warnings"])} warning(s), listed above and in the bundle\'s warnings')
