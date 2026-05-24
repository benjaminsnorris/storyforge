"""storyforge sync — Keep scene CSVs and scenes-review.md in sync.

The three scene CSVs (scenes.csv, scene-intent.csv, scene-briefs.csv) are
the source of truth, but they're pipe-delimited and unreadable in a PR diff.
`reference/scenes-review.md` is a regenerated mirror that makes review easy.

This command compares the working tree to `git HEAD` and routes:

  - both clean              → no-op (regenerate MD if missing entirely)
  - CSVs dirty, MD clean    → export CSVs → MD
  - MD dirty, CSVs clean    → import MD → CSVs
  - both dirty              → conflict: write working/sync-conflict.md and
                              exit non-zero so a pre-commit hook can refuse

Also installs a pre-commit hook that runs this automatically:

    storyforge sync --install-hook
"""

import argparse
import difflib
import os
import subprocess
import sys

from storyforge.common import detect_project_root, install_signal_handlers, log
from storyforge.cmd_scenes_export import (
    DEFAULT_OUTPUT_PATH, SECTION_SPECS, export_scenes,
)
from storyforge.cmd_scenes_import import import_scenes


CSV_RELS = [csv_rel for _, csv_rel in SECTION_SPECS]
CONFLICT_REPORT_PATH = os.path.join('working', 'sync-conflict.md')


# ============================================================================
# Git state helpers
# ============================================================================

def _git(project_dir, *args, check=False):
    return subprocess.run(
        ['git', *args], cwd=project_dir,
        capture_output=True, text=True, check=check,
    )


def _is_dirty(project_dir, path_rel):
    """Return True if `path_rel` differs from HEAD (or is untracked).

    Compares the working-tree state of one file to its committed version.
    Untracked files and files absent from HEAD count as dirty.
    """
    abs_path = os.path.join(project_dir, path_rel)
    # Untracked / new file → dirty if it exists on disk.
    show = _git(project_dir, 'cat-file', '-e', f'HEAD:{path_rel}')
    if show.returncode != 0:
        return os.path.isfile(abs_path)
    diff = _git(project_dir, 'diff', '--quiet', 'HEAD', '--', path_rel)
    # `git diff --quiet` exits 1 when there's a diff, 0 when there isn't.
    return diff.returncode != 0


def _file_in_head(project_dir, path_rel):
    """True if the path exists in HEAD (i.e. is tracked + committed)."""
    return _git(project_dir, 'cat-file', '-e', f'HEAD:{path_rel}').returncode == 0


def _head_content(project_dir, path_rel):
    """Return the content of `path_rel` at HEAD, or '' if not in HEAD."""
    r = _git(project_dir, 'show', f'HEAD:{path_rel}')
    return r.stdout if r.returncode == 0 else ''


# ============================================================================
# Sync state machine
# ============================================================================

def detect_state(project_dir, md_rel=DEFAULT_OUTPUT_PATH):
    """Return a dict describing what's dirty.

    Keys:
      - csv_dirty: bool — any of the three CSVs differs from HEAD
      - md_dirty: bool  — the MD differs from HEAD (or is untracked)
      - md_exists: bool — the MD exists on disk
      - md_in_head: bool — the MD has ever been committed
      - dirty_csvs: list[str] — relative paths of changed CSVs
    """
    dirty_csvs = [p for p in CSV_RELS if _is_dirty(project_dir, p)]
    md_exists = os.path.isfile(os.path.join(project_dir, md_rel))
    md_in_head = _file_in_head(project_dir, md_rel)
    md_dirty = _is_dirty(project_dir, md_rel)
    return {
        'csv_dirty': bool(dirty_csvs),
        'md_dirty': md_dirty,
        'md_exists': md_exists,
        'md_in_head': md_in_head,
        'dirty_csvs': dirty_csvs,
    }


def _write_conflict_report(project_dir, state, md_rel):
    """Write a structured description of the conflict and return its path."""
    report_path = os.path.join(project_dir, CONFLICT_REPORT_PATH)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    # Render what export would produce now (CSV-side view) for comparison.
    tmp_md = report_path + '.csv-side.md'
    try:
        export_scenes(project_dir, tmp_md)
        csv_side = open(tmp_md, encoding='utf-8').read()
    except Exception as e:
        csv_side = f'(could not render CSV-side preview: {e})'
    finally:
        if os.path.isfile(tmp_md):
            os.remove(tmp_md)

    md_path = os.path.join(project_dir, md_rel)
    md_side = open(md_path, encoding='utf-8').read() if os.path.isfile(md_path) else ''

    diff = ''.join(difflib.unified_diff(
        md_side.splitlines(keepends=True),
        csv_side.splitlines(keepends=True),
        fromfile=f'{md_rel} (working tree)',
        tofile=f'{md_rel} (would-be export from CSVs)',
        n=3,
    ))

    body = [
        '# Storyforge sync conflict',
        '',
        f'Both the scene CSVs and `{md_rel}` have uncommitted changes:',
        '',
        '## Changed CSVs',
    ]
    for csv_rel in state['dirty_csvs']:
        body.append(f'- {csv_rel}')
    body.extend([
        '',
        '## How to resolve',
        '',
        '1. Inspect the diff below to see how the two sides disagree.',
        '2. Reconcile by hand: either revert one side, or edit both to match.',
        '3. Re-run `storyforge sync` to confirm.',
        '',
        'For trickier merges, ask Claude in a session to walk through the',
        'conflict and apply the right call per the brief and story intent.',
        '',
        '## Diff (working MD → would-be export from CSVs)',
        '',
        '```diff',
        diff if diff else '(diffs are byte-equal but git sees both as dirty — '
                          'often whitespace or line-ending drift)',
        '```',
        '',
    ])
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(body))
    return report_path


def run_sync(project_dir, md_rel=DEFAULT_OUTPUT_PATH, check_only=False):
    """Sync CSVs and the review MD against git HEAD. Returns one of:

      - 'noop'         — both sides clean and MD is present
      - 'exported'     — CSV changes flowed to MD
      - 'imported'     — MD changes flowed to CSVs
      - 'conflict'     — both sides changed; conflict report written
      - 'first-export' — MD never committed; treated as CSV → MD seed

    `check_only=True` returns the same status without writing anything.
    """
    state = detect_state(project_dir, md_rel)
    md_path = os.path.join(project_dir, md_rel)

    # No prior committed MD: treat CSVs as canonical and seed the MD.
    if not state['md_in_head']:
        if check_only:
            return 'first-export'
        export_scenes(project_dir, md_path)
        return 'first-export'

    if state['csv_dirty'] and state['md_dirty']:
        if check_only:
            return 'conflict'
        report_path = _write_conflict_report(project_dir, state, md_rel)
        log(f'CONFLICT: both CSVs and {md_rel} have changes vs HEAD.')
        log(f'  See {report_path} for the diff.')
        return 'conflict'

    if state['csv_dirty']:
        if check_only:
            return 'exported'
        export_scenes(project_dir, md_path)
        log(f'Exported CSV changes → {md_rel}')
        return 'exported'

    if state['md_dirty']:
        if check_only:
            return 'imported'
        changes = import_scenes(project_dir, md_path, dry_run=False)
        log(f'Imported {len(changes)} field change(s) from {md_rel} → CSVs')
        return 'imported'

    # Both clean. If the MD doesn't exist on disk somehow (e.g. wiped), regen.
    if not state['md_exists']:
        if check_only:
            return 'exported'
        export_scenes(project_dir, md_path)
        log(f'Regenerated missing {md_rel}')
        return 'exported'

    return 'noop'


# ============================================================================
# Pre-commit hook installation
# ============================================================================

HOOK_FILENAME = 'pre-commit'

HOOK_SCRIPT = '''#!/usr/bin/env bash
# Installed by `storyforge sync --install-hook`. Keeps scene CSVs and
# reference/scenes-review.md in sync before each commit.
set -e

# Only run if any tracked scene file has staged changes.
if ! git diff --cached --name-only \\
        | grep -E '^reference/(scenes|scene-intent|scene-briefs)\\.csv$|^reference/scenes-review\\.md$' \\
        >/dev/null 2>&1; then
    exit 0
fi

# Find the storyforge runner. Prefer the one on PATH; fall back to the
# user's plugin checkout.
if command -v storyforge >/dev/null 2>&1; then
    SF=storyforge
elif [ -x "$HOME/Developer/storyforge/storyforge" ]; then
    SF="$HOME/Developer/storyforge/storyforge"
else
    echo "pre-commit: 'storyforge' not on PATH; skipping sync" >&2
    exit 0
fi

if ! "$SF" sync; then
    echo "" >&2
    echo "storyforge sync refused the commit." >&2
    echo "See working/sync-conflict.md and resolve, then 'git add' and retry." >&2
    exit 1
fi

# Restage anything sync produced (e.g. regenerated scenes-review.md or
# updated CSV cells from an MD-side edit).
git add reference/scenes.csv reference/scene-intent.csv \\
        reference/scene-briefs.csv reference/scenes-review.md 2>/dev/null || true
'''


def install_hook(project_dir):
    """Write the pre-commit hook into the project's .git/hooks/. Returns path."""
    hooks_dir = os.path.join(project_dir, '.git', 'hooks')
    if not os.path.isdir(hooks_dir):
        log(f'ERROR: {hooks_dir} not found — is this a git repository?')
        sys.exit(1)
    hook_path = os.path.join(hooks_dir, HOOK_FILENAME)
    if os.path.isfile(hook_path):
        with open(hook_path, encoding='utf-8') as f:
            existing = f.read()
        if 'storyforge sync' not in existing:
            log(f'WARNING: {hook_path} already exists and is not a storyforge hook. '
                'Refusing to overwrite — back it up or merge by hand.')
            sys.exit(1)
    with open(hook_path, 'w', encoding='utf-8') as f:
        f.write(HOOK_SCRIPT)
    os.chmod(hook_path, 0o755)
    log(f'Installed pre-commit hook at {hook_path}')
    return hook_path


# ============================================================================
# CLI
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge sync',
        description='Keep scene CSVs and reference/scenes-review.md in sync.',
    )
    parser.add_argument('--check', action='store_true',
                        help='Report the sync status without writing anything')
    parser.add_argument('--install-hook', action='store_true',
                        help='Install a git pre-commit hook that runs sync')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()
    project_dir = detect_project_root()

    if args.install_hook:
        install_hook(project_dir)
        return

    status = run_sync(project_dir, check_only=args.check)
    if args.check:
        log(f'Sync status: {status}')
    if status == 'conflict':
        sys.exit(1)


if __name__ == '__main__':
    main()
