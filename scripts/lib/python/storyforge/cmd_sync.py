"""storyforge sync — Keep scene CSVs and scenes-review.md in sync.

The three scene CSVs (scenes.csv, scene-intent.csv, scene-briefs.csv) are
the source of truth, but they're pipe-delimited and unreadable in a PR diff.
`reference/scenes-review.md` is a regenerated mirror that makes review easy.

This command compares the working tree to `git HEAD` and routes:

  - both clean              → 'noop' (regenerate MD if missing on disk only)
  - CSVs dirty, MD clean    → 'exported' (CSVs → MD)
  - MD dirty, CSVs clean    → 'imported' (MD → CSVs)
  - both dirty              → 'conflict' — write working/sync-conflict.md
                              and exit non-zero
  - MD not in HEAD, absent  → 'first-export' (seed from CSVs)
  - MD not in HEAD, present → 'untracked-md' — refuse rather than clobber
  - CSV deleted on disk     → 'missing-csv' — refuse and instruct to restore

`storyforge sync --install-hook` drops a pre-commit hook that runs sync,
restages the result, and refuses commits with unresolved conflicts.
"""

import argparse
import difflib
import os
import subprocess
import sys
import tempfile

from storyforge.common import detect_project_root, install_signal_handlers, log
from storyforge.cmd_scenes_export import (
    DEFAULT_OUTPUT_PATH, SECTION_SPECS, export_scenes,
)
from storyforge.cmd_scenes_import import import_scenes


CSV_RELS = [csv_rel for _, csv_rel in SECTION_SPECS]
CONFLICT_REPORT_PATH = os.path.join('working', 'sync-conflict.md')

# git diff --quiet exit codes
_DIFF_CLEAN = 0
_DIFF_DIRTY = 1


# ============================================================================
# Git state helpers
# ============================================================================

def _git(project_dir, *args, check=False):
    return subprocess.run(
        ['git', *args], cwd=project_dir,
        capture_output=True, text=True, check=check,
    )


def _is_git_repo(project_dir):
    """Fast check that `project_dir` is inside a git working tree."""
    return _git(project_dir, 'rev-parse', '--git-dir').returncode == 0


def _is_dirty(project_dir, path_rel):
    """Return True if `path_rel` differs from HEAD (or is untracked).

    Compares working-tree state to the committed version. Files not in HEAD
    are treated as dirty when they exist on disk. Raises RuntimeError if
    git itself fails for a reason other than "file isn't in HEAD" or
    "file differs from HEAD" — masking those would let real corruption
    look like a routine "everything is dirty" state.
    """
    abs_path = os.path.join(project_dir, path_rel)
    # File absent from HEAD → dirty iff it exists on disk (new file).
    in_head = _git(project_dir, 'cat-file', '-e', f'HEAD:{path_rel}')
    if in_head.returncode != 0:
        return os.path.isfile(abs_path)
    diff = _git(project_dir, 'diff', '--quiet', 'HEAD', '--', path_rel)
    if diff.returncode not in (_DIFF_CLEAN, _DIFF_DIRTY):
        raise RuntimeError(
            f'git diff failed unexpectedly for {path_rel}: '
            f'exit={diff.returncode} stderr={diff.stderr.strip()!r}'
        )
    return diff.returncode == _DIFF_DIRTY


def _file_in_head(project_dir, path_rel):
    """True if the path exists in HEAD (i.e. is tracked + committed)."""
    return _git(project_dir, 'cat-file', '-e', f'HEAD:{path_rel}').returncode == 0


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
      - missing_csvs: list[str] — CSVs tracked in HEAD but absent from disk
    """
    if not _is_git_repo(project_dir):
        raise RuntimeError(
            f'{project_dir} is not inside a git working tree. '
            'storyforge sync requires git for state detection.'
        )
    dirty_csvs = [p for p in CSV_RELS if _is_dirty(project_dir, p)]
    missing_csvs = [
        p for p in CSV_RELS
        if _file_in_head(project_dir, p)
        and not os.path.isfile(os.path.join(project_dir, p))
    ]
    md_exists = os.path.isfile(os.path.join(project_dir, md_rel))
    md_in_head = _file_in_head(project_dir, md_rel)
    md_dirty = _is_dirty(project_dir, md_rel)
    return {
        'csv_dirty': bool(dirty_csvs),
        'md_dirty': md_dirty,
        'md_exists': md_exists,
        'md_in_head': md_in_head,
        'dirty_csvs': dirty_csvs,
        'missing_csvs': missing_csvs,
    }


def _write_conflict_report(project_dir, state, md_rel):
    """Write a structured description of the conflict and return its path."""
    report_path = os.path.join(project_dir, CONFLICT_REPORT_PATH)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    # Render what export would produce now (CSV-side view) for comparison.
    # Use a NamedTemporaryFile so we don't leave junk on disk if anything
    # raises before the explicit cleanup below.
    csv_side = ''
    with tempfile.NamedTemporaryFile(
        suffix='.md', mode='w', delete=False,
        dir=os.path.dirname(report_path), encoding='utf-8',
    ) as tmp:
        tmp_md = tmp.name
    try:
        export_scenes(project_dir, tmp_md)
        with open(tmp_md, encoding='utf-8') as f:
            csv_side = f.read()
    except (OSError, UnicodeError, ValueError) as e:
        # Narrow except: surface real bugs in export (schema drift, missing
        # CSVs, encoding) loudly rather than burying them in the report body.
        log(f'WARNING: could not render CSV-side preview for conflict report: {e}')
        csv_side = f'(could not render CSV-side preview: {e}; see log above)'
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
        '2. Reconcile by hand: revert one side, or edit both to match.',
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

      - 'noop'         — both sides clean and MD present
      - 'exported'     — CSV changes flowed to MD (or MD regenerated because
                         it was missing on disk)
      - 'imported'     — MD changes flowed to CSVs
      - 'conflict'     — both sides changed; conflict report written
      - 'first-export' — MD never committed and absent on disk; seeded
      - 'untracked-md' — MD exists on disk but not in HEAD; refused to clobber
      - 'missing-csv'  — a CSV tracked in HEAD is missing on disk; refused

    `check_only=True` returns the same status without writing anything.
    """
    state = detect_state(project_dir, md_rel)
    md_path = os.path.join(project_dir, md_rel)

    # Hard refuse: a CSV is tracked but missing from disk. Sync can't proceed
    # safely — restoring it requires the user's intent.
    if state['missing_csvs']:
        if check_only:
            return 'missing-csv'
        log(f'ERROR: CSV(s) tracked in HEAD but missing on disk: '
            f'{", ".join(state["missing_csvs"])}')
        log('  Restore with: git checkout HEAD -- <path>')
        log('  Or commit the deletion explicitly before re-running sync.')
        return 'missing-csv'

    # MD never committed but already exists on disk → could be hand-edits.
    # Refuse rather than silently overwrite.
    if not state['md_in_head'] and state['md_exists']:
        if check_only:
            return 'untracked-md'
        log(f'ERROR: {md_rel} exists on disk but is not committed.')
        log('  If those edits are yours, `git add` and commit them, then re-run sync.')
        log('  If you want to discard them and regenerate from the CSVs, delete '
            'the file and re-run sync.')
        return 'untracked-md'

    # MD truly absent: seed from CSVs.
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
        # import_scenes raises RuntimeError on unknown scene IDs etc.
        changes = import_scenes(project_dir, md_path, dry_run=False)
        log(f'Imported {len(changes)} field change(s) from {md_rel} → CSVs')
        return 'imported'

    # Both clean and committed. If MD was wiped from disk somehow, regen.
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

SYNC_TRACKED_PATHS = [
    'reference/scenes.csv',
    'reference/scene-intent.csv',
    'reference/scene-briefs.csv',
    'reference/scenes-review.md',
]

# Regex the hook uses to decide whether the current commit touches any
# sync-tracked path. Defined here so it can be unit-tested in Python.
HOOK_PATH_FILTER = (
    r'^reference/(scenes|scene-intent|scene-briefs)\.csv$'
    r'|^reference/scenes-review\.md$'
)

HOOK_SCRIPT = f'''#!/usr/bin/env bash
# Installed by `storyforge sync --install-hook`. Keeps scene CSVs and
# reference/scenes-review.md in sync before each commit.
#
# Behavior:
#   1. Skip unless the staged change touches a sync-tracked path.
#   2. Refuse the commit if any sync-tracked file has *unstaged* changes,
#      so sync can't accidentally bundle unrelated work into the commit.
#   3. Run `storyforge sync`. Refuse the commit if sync writes a conflict
#      report or otherwise exits non-zero.
#   4. Stage the four sync-tracked files so anything sync produced lands
#      in the commit.
#
# Bypass for one-off cases: STORYFORGE_SYNC_SKIP=1 git commit ...
set -e

if [ "${{STORYFORGE_SYNC_SKIP:-}}" = "1" ]; then
    exit 0
fi

# Step 1: only run if the staged change touches a sync-tracked path.
if ! git diff --cached --name-only \\
        | grep -E '{HOOK_PATH_FILTER}' \\
        >/dev/null 2>&1; then
    exit 0
fi

# Step 2: refuse if any sync-tracked file has unstaged working-tree changes.
# (Otherwise sync would mix those edits into the commit, or be blocked by
# a spurious "both dirty" conflict.)
UNSTAGED=$(git diff --name-only -- {' '.join(SYNC_TRACKED_PATHS)} || true)
if [ -n "$UNSTAGED" ]; then
    echo "" >&2
    echo "ERROR: storyforge sync refuses to run with unstaged scene changes:" >&2
    echo "$UNSTAGED" | sed 's/^/  /' >&2
    echo "" >&2
    echo "Stash, stage, or revert those changes, then commit again." >&2
    echo "(Set STORYFORGE_SYNC_SKIP=1 to bypass.)" >&2
    exit 1
fi

# Step 3: find the storyforge runner. Fail closed if we can't.
if command -v storyforge >/dev/null 2>&1; then
    SF=storyforge
elif [ -n "${{STORYFORGE_HOME:-}}" ] && [ -x "$STORYFORGE_HOME/storyforge" ]; then
    SF="$STORYFORGE_HOME/storyforge"
else
    echo "" >&2
    echo "ERROR: pre-commit hook needs 'storyforge' on PATH (or \\$STORYFORGE_HOME" >&2
    echo "set to the plugin checkout) to keep scene files in sync." >&2
    echo "Install storyforge or set STORYFORGE_SYNC_SKIP=1 to bypass." >&2
    exit 1
fi

if ! "$SF" sync; then
    echo "" >&2
    echo "storyforge sync refused the commit." >&2
    echo "See working/sync-conflict.md (or the error above) and resolve, " >&2
    echo "then 'git add' and retry." >&2
    exit 1
fi

# Step 4: stage whatever sync produced. No `|| true` — a failure here means
# the commit would land with stale files and we want to know about it.
for f in {' '.join(SYNC_TRACKED_PATHS)}; do
    if [ -f "$f" ]; then
        git add "$f"
    fi
done
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

# Status codes that should cause the CLI / hook to exit non-zero.
_FAILURE_STATUSES = {'conflict', 'untracked-md', 'missing-csv'}


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

    try:
        status = run_sync(project_dir, check_only=args.check)
    except RuntimeError as e:
        log(f'ERROR: {e}')
        sys.exit(1)

    if args.check:
        log(f'Sync status: {status}')
    if status in _FAILURE_STATUSES:
        sys.exit(1)


if __name__ == '__main__':
    main()
