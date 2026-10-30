"""storyforge visualize -- Write the manuscript dashboard's data.

Storyforge defines the dashboard's data and Bookshelf renders it (#371,
benjaminsnorris/bookshelf#30). This command writes that data, exactly as
`publish` sends it, to working/dashboard-data.json so it can be inspected;
the contract is documented in docs/agent-reference.md ("Dashboard data").
To see the rendered dashboard, publish the book and open it in Bookshelf.

Usage:
    storyforge visualize              # Write working/dashboard-data.json
    storyforge visualize --dry-run    # Show what would be written
"""

import argparse
import json
import os
import sys

from storyforge.common import detect_project_root, log


DATA_FILE = os.path.join('working', 'dashboard-data.json')


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge visualize',
        description="Write the manuscript dashboard's data (Bookshelf renders it).",
    )
    # Deprecated no-op: there is no local HTML to open any more (#371)
    parser.add_argument('--open', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be written without writing')
    return parser.parse_args(argv)


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])

    project_dir = detect_project_root()
    from storyforge.ledger import exit_if_not_migrated
    exit_if_not_migrated(project_dir)  # the registries live in the ledger
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    data_file = os.path.join(project_dir, DATA_FILE)

    if not os.path.isfile(metadata_csv):
        print(f'ERROR: reference/scenes.csv not found at {metadata_csv}', file=sys.stderr)
        sys.exit(1)

    from storyforge.visualize import load_dashboard_data
    data = load_dashboard_data(project_dir)
    lists = {k: len(v) for k, v in data.items() if isinstance(v, list)}

    if args.dry_run:
        log(f'DRY RUN -- would write {data_file}')
    else:
        os.makedirs(os.path.dirname(data_file), exist_ok=True)
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        log(f'Dashboard data written: {data_file}')
    log(f'  Project: {data["project"]["title"]} (schema version {data["schema_version"]})')
    log(f'  Rows: {", ".join(f"{k} {n}" for k, n in lists.items() if n)}')
    log('Bookshelf renders the dashboard from this data: run `storyforge publish` '
        'and open the book in Bookshelf to see it.')
    if args.open:
        log('Note: --open is a no-op — there is no local dashboard page any more.')
