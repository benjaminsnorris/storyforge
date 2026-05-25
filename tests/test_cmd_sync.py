"""Tests for cmd_sync and the header-driven scenes-export round-trip."""

import os
import subprocess

import pytest

from storyforge.csv_cli import get_field, update_field


def _git(project_dir, *args, check=True):
    return subprocess.run(
        ['git', *args], cwd=project_dir,
        capture_output=True, text=True, check=check,
    )


@pytest.fixture
def git_project(project_dir, monkeypatch):
    """A `project_dir` fixture with an initialized git repo and an initial commit."""
    monkeypatch.chdir(project_dir)
    _git(project_dir, 'init', '-q')
    _git(project_dir, 'config', 'user.email', 'test@example.com')
    _git(project_dir, 'config', 'user.name', 'Test')
    _git(project_dir, 'add', '-A')
    _git(project_dir, 'commit', '-q', '-m', 'initial')
    return project_dir


@pytest.fixture
def git_project_gn(project_dir_gn, monkeypatch):
    monkeypatch.chdir(project_dir_gn)
    _git(project_dir_gn, 'init', '-q')
    _git(project_dir_gn, 'config', 'user.email', 'test@example.com')
    _git(project_dir_gn, 'config', 'user.name', 'Test')
    _git(project_dir_gn, 'add', '-A')
    _git(project_dir_gn, 'commit', '-q', '-m', 'initial')
    return project_dir_gn


# ---------------------------------------------------------------------------
# Header-driven export: round-trip GN columns
# ---------------------------------------------------------------------------

def test_export_includes_gn_specific_columns(project_dir_gn):
    """target_pages, panel_breakdown, etc. must appear in the exported MD."""
    from storyforge.cmd_scenes_export import export_scenes
    out = os.path.join(project_dir_gn, 'reference', 'scenes-review.md')
    export_scenes(project_dir_gn, out)
    content = open(out).read()
    assert 'target_pages: 6' in content
    assert 'page_layout: splash p1, 4-panel grid p2' in content
    assert 'panel_breakdown:' in content
    assert 'visual_keywords:' in content
    assert 'page_turn_beats:' in content
    assert 'caption_strategy:' in content


def test_gn_round_trip_preserves_specific_columns(project_dir_gn):
    """Export → edit a GN column → import flows back to the right CSV cell."""
    from storyforge.cmd_scenes_export import export_scenes
    from storyforge.cmd_scenes_import import import_scenes

    out = os.path.join(project_dir_gn, 'reference', 'scenes-review.md')
    export_scenes(project_dir_gn, out)

    content = open(out).read()
    content = content.replace(
        'target_pages: 6',
        'target_pages: 8',
    )
    with open(out, 'w') as f:
        f.write(content)

    changes = import_scenes(project_dir_gn, out, dry_run=False)
    assert any(c[2] == 'target_pages' for c in changes), \
        'target_pages change should propagate to the CSV'

    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    assert get_field(scenes_csv, 'the-blank-page', 'target_pages') == '8'


# ---------------------------------------------------------------------------
# Sync state machine
# ---------------------------------------------------------------------------

def test_sync_first_run_exports_when_no_md_in_head(git_project):
    """When the MD has never been committed, sync exports it from the CSVs."""
    from storyforge.cmd_sync import run_sync, DEFAULT_OUTPUT_PATH

    md_path = os.path.join(git_project, DEFAULT_OUTPUT_PATH)
    assert not os.path.isfile(md_path)

    status = run_sync(git_project)
    assert status == 'first-export'
    assert os.path.isfile(md_path)


def test_sync_noop_when_both_clean(git_project):
    """After export + commit, a fresh sync is a no-op."""
    from storyforge.cmd_sync import run_sync, DEFAULT_OUTPUT_PATH

    run_sync(git_project)
    _git(git_project, 'add', DEFAULT_OUTPUT_PATH)
    _git(git_project, 'commit', '-q', '-m', 'add scenes-review.md')

    status = run_sync(git_project)
    assert status == 'noop'


def test_sync_exports_when_csv_dirty(git_project):
    """CSV change with clean MD → export."""
    from storyforge.cmd_sync import run_sync, DEFAULT_OUTPUT_PATH

    run_sync(git_project)
    _git(git_project, 'add', DEFAULT_OUTPUT_PATH)
    _git(git_project, 'commit', '-q', '-m', 'add MD')

    scenes_csv = os.path.join(git_project, 'reference', 'scenes.csv')
    update_field(scenes_csv, 'act1-sc01', 'title', 'A New Title')

    status = run_sync(git_project)
    assert status == 'exported'
    md = open(os.path.join(git_project, DEFAULT_OUTPUT_PATH)).read()
    assert 'title: A New Title' in md


def test_sync_imports_when_md_dirty(git_project):
    """MD change with clean CSVs → import."""
    from storyforge.cmd_sync import run_sync, DEFAULT_OUTPUT_PATH

    run_sync(git_project)
    md_path = os.path.join(git_project, DEFAULT_OUTPUT_PATH)
    _git(git_project, 'add', DEFAULT_OUTPUT_PATH)
    _git(git_project, 'commit', '-q', '-m', 'add MD')

    content = open(md_path).read().replace(
        'title: The Finest Cartographer',
        'title: The Last Cartographer',
    )
    with open(md_path, 'w') as f:
        f.write(content)

    status = run_sync(git_project)
    assert status == 'imported'
    scenes_csv = os.path.join(git_project, 'reference', 'scenes.csv')
    assert get_field(scenes_csv, 'act1-sc01', 'title') == 'The Last Cartographer'


def test_sync_conflicts_when_both_dirty(git_project):
    """Both sides changed → conflict + report file written, exit non-zero."""
    from storyforge.cmd_sync import run_sync, CONFLICT_REPORT_PATH, DEFAULT_OUTPUT_PATH

    run_sync(git_project)
    md_path = os.path.join(git_project, DEFAULT_OUTPUT_PATH)
    _git(git_project, 'add', DEFAULT_OUTPUT_PATH)
    _git(git_project, 'commit', '-q', '-m', 'add MD')

    # Edit CSV
    scenes_csv = os.path.join(git_project, 'reference', 'scenes.csv')
    update_field(scenes_csv, 'act1-sc01', 'pov', 'Someone Else')

    # And edit MD
    content = open(md_path).read().replace(
        'title: The Finest Cartographer',
        'title: A Different Title',
    )
    with open(md_path, 'w') as f:
        f.write(content)

    status = run_sync(git_project)
    assert status == 'conflict'
    report = os.path.join(git_project, CONFLICT_REPORT_PATH)
    assert os.path.isfile(report)

    report_text = open(report).read()
    assert 'sync conflict' in report_text.lower()
    assert 'reference/scenes.csv' in report_text

    # CSV must NOT have been overwritten with MD's pov change, and MD must NOT
    # have been overwritten with CSV-side title — both sides preserved.
    assert get_field(scenes_csv, 'act1-sc01', 'pov') == 'Someone Else'
    assert 'A Different Title' in open(md_path).read()


def test_sync_conflict_with_header_only_scenes_does_not_crash(git_project):
    """Regression: when both scenes.csv (header-only) and the MD are dirty,
    the conflict-report rendering used to call build_scene_list, which
    SystemExit'd on empty scenes — taking down the whole sync. The conflict
    report should render with a 'pre-scene-map phase' note instead."""
    from storyforge.cmd_sync import run_sync, CONFLICT_REPORT_PATH, DEFAULT_OUTPUT_PATH

    run_sync(git_project)
    md_path = os.path.join(git_project, DEFAULT_OUTPUT_PATH)
    _git(git_project, 'add', DEFAULT_OUTPUT_PATH)
    _git(git_project, 'commit', '-q', '-m', 'add MD')

    # Reduce scenes.csv to header-only (simulates dropping back to architecture phase)
    scenes_csv = os.path.join(git_project, 'reference', 'scenes.csv')
    with open(scenes_csv) as f:
        header = f.readline()
    with open(scenes_csv, 'w') as f:
        f.write(header)

    # And edit MD
    with open(md_path, 'a') as f:
        f.write('\n## stray scene-section-from-md\n')

    status = run_sync(git_project)
    assert status == 'conflict'
    report = os.path.join(git_project, CONFLICT_REPORT_PATH)
    assert os.path.isfile(report)
    report_text = open(report).read()
    # The conflict report should note the empty-scenes state rather than
    # crash trying to build a scene list from zero rows.
    assert 'pre-scene-map phase' in report_text


def test_sync_check_only_does_not_write(git_project):
    """--check returns the status without performing the sync."""
    from storyforge.cmd_sync import run_sync, DEFAULT_OUTPUT_PATH

    status = run_sync(git_project, check_only=True)
    assert status == 'first-export'
    assert not os.path.isfile(os.path.join(git_project, DEFAULT_OUTPUT_PATH))


def test_sync_gn_first_export(git_project_gn):
    """GN-mode project: first sync produces an MD with GN-specific fields."""
    from storyforge.cmd_sync import run_sync, DEFAULT_OUTPUT_PATH

    status = run_sync(git_project_gn)
    assert status == 'first-export'
    md = open(os.path.join(git_project_gn, DEFAULT_OUTPUT_PATH)).read()
    assert 'target_pages: 6' in md
    assert 'panel_breakdown:' in md


# ---------------------------------------------------------------------------
# Hook installation
# ---------------------------------------------------------------------------

def test_install_hook_writes_executable_script(git_project):
    """--install-hook drops a pre-commit hook in .git/hooks/."""
    from storyforge.cmd_sync import install_hook, _default_runner_path

    hook_path = install_hook(git_project)
    assert os.path.isfile(hook_path)
    assert os.access(hook_path, os.X_OK), 'hook must be executable'
    content = open(hook_path).read()
    assert 'storyforge sync' in content
    # The placeholder must have been substituted with a real path
    assert '__STORYFORGE_RUNNER_PATH__' not in content
    runner = _default_runner_path()
    assert runner and runner in content, (
        'install_hook should bake the plugin runner path into the hook'
    )


def test_install_hook_refuses_to_overwrite_foreign_hook(git_project):
    """If an existing hook isn't ours, we bail rather than clobber."""
    from storyforge.cmd_sync import install_hook

    hook_path = os.path.join(git_project, '.git', 'hooks', 'pre-commit')
    with open(hook_path, 'w') as f:
        f.write('#!/bin/sh\necho "not the storyforge hook"\n')

    with pytest.raises(SystemExit) as exc_info:
        install_hook(git_project)
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# Regression tests for review fixes
# ---------------------------------------------------------------------------

def test_sync_refuses_to_overwrite_untracked_md(git_project):
    """If MD exists on disk but is not in HEAD, refuse rather than seed.

    Without this guard, a hand-edited MD copied in from another branch / a
    backup / etc. would be silently destroyed on the first sync run.
    """
    from storyforge.cmd_sync import run_sync, DEFAULT_OUTPUT_PATH

    md_path = os.path.join(git_project, DEFAULT_OUTPUT_PATH)
    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    sentinel = '## from-another-project\n\n### Whatever\nfoo: bar\n'
    with open(md_path, 'w') as f:
        f.write(sentinel)

    status = run_sync(git_project)
    assert status == 'untracked-md'
    # File is unchanged
    assert open(md_path).read() == sentinel


def test_sync_first_export_only_when_md_truly_absent(git_project):
    """The first-export branch still works when MD doesn't exist on disk."""
    from storyforge.cmd_sync import run_sync, DEFAULT_OUTPUT_PATH

    md_path = os.path.join(git_project, DEFAULT_OUTPUT_PATH)
    assert not os.path.isfile(md_path)
    status = run_sync(git_project)
    assert status == 'first-export'
    assert os.path.isfile(md_path)


def test_sync_refuses_when_csv_deleted_on_disk(git_project):
    """Tracked CSV deleted from disk → missing-csv status, no MD writes."""
    from storyforge.cmd_sync import run_sync, DEFAULT_OUTPUT_PATH

    # Get a baseline MD in HEAD so we exercise the post-bootstrap path.
    run_sync(git_project)
    _git(git_project, 'add', DEFAULT_OUTPUT_PATH)
    _git(git_project, 'commit', '-q', '-m', 'add MD')

    os.remove(os.path.join(git_project, 'reference', 'scenes.csv'))
    md_before = open(os.path.join(git_project, DEFAULT_OUTPUT_PATH)).read()

    status = run_sync(git_project)
    assert status == 'missing-csv'
    # MD must NOT be regenerated against a half-broken project state
    assert open(os.path.join(git_project, DEFAULT_OUTPUT_PATH)).read() == md_before


def test_parse_markdown_unknown_field_does_not_clobber_previous(project_dir):
    """A 'field: value'-shaped line whose field is unknown must NOT merge
    into the prior real field's value — that's silent CSV corruption.
    """
    from storyforge.cmd_scenes_import import parse_markdown
    from storyforge.cmd_scenes_export import get_sections

    section_map = {
        name: (csv_rel, set(fields))
        for name, csv_rel, fields in get_sections(project_dir)
    }
    md = (
        '## act1-sc01\n'
        '\n'
        '### Brief\n'
        'goal: fill the blank page\n'
        'note_to_author: revisit later\n'
        'conflict: nothing comes\n'
    )
    parsed = parse_markdown(md, section_map)
    assert parsed['act1-sc01']['Brief']['goal'] == 'fill the blank page'
    assert parsed['act1-sc01']['Brief']['conflict'] == 'nothing comes'
    assert 'note_to_author' not in parsed['act1-sc01']['Brief']


def test_parse_markdown_continuation_still_works(project_dir):
    """Multi-line field values (continuation without `field:` prefix) still
    work after the unknown-field fix.
    """
    from storyforge.cmd_scenes_import import parse_markdown
    from storyforge.cmd_scenes_export import get_sections

    section_map = {
        name: (csv_rel, set(fields))
        for name, csv_rel, fields in get_sections(project_dir)
    }
    md = (
        '## act1-sc01\n'
        '\n'
        '### Brief\n'
        'goal: fill the blank page\n'
        '  with steady deliberate movements\n'
    )
    parsed = parse_markdown(md, section_map)
    assert parsed['act1-sc01']['Brief']['goal'] == (
        'fill the blank page with steady deliberate movements'
    )


def test_export_omits_sections_for_scenes_with_no_row(project_dir):
    """Scenes that don't have a row in scene-intent.csv or scene-briefs.csv
    should not have those empty sections rendered at all."""
    from storyforge.cmd_scenes_export import export_scenes
    from storyforge.csv_cli import _read_lines, _write_lines

    # Strip the brief row for act1-sc01 so it has Structural + Intent only.
    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    lines = _read_lines(briefs_csv)
    kept = [lines[0]] + [l for l in lines[1:] if not l.startswith('act1-sc01|')]
    _write_lines(briefs_csv, kept)

    out = os.path.join(project_dir, 'reference', 'scenes-review.md')
    export_scenes(project_dir, out)
    content = open(out).read()

    # Locate the act1-sc01 block in the rendered MD
    start = content.index('## act1-sc01')
    end = content.index('## act1-sc02')
    block = content[start:end]
    assert '### Structural' in block
    assert '### Intent' in block
    assert '### Brief' not in block, (
        'Brief section should be omitted when the scene has no brief row'
    )


def test_hook_path_filter_matches_expected_paths():
    """Regression: the regex the hook uses to decide whether to fire must
    match every sync-tracked path and reject lookalikes."""
    import re
    from storyforge.cmd_sync import HOOK_PATH_FILTER

    rx = re.compile(HOOK_PATH_FILTER, re.MULTILINE)
    for good in (
        'reference/scenes.csv',
        'reference/scene-intent.csv',
        'reference/scene-briefs.csv',
        'reference/spine.csv',
        'reference/architecture.csv',
        'reference/scenes-review.md',
        'reference/spine.md',
        'reference/architecture.md',
    ):
        assert rx.search(good), f'expected hook to fire for {good!r}'
    for bad in (
        'reference/voice-profile.csv',     # different CSV
        'scenes-review.md',                # wrong directory
        'reference/scenes.csv.bak',        # extension boundary
        'reference/scene-briefs.csv.tmp',  # extension boundary
        'docs/reference/scenes.csv',       # wrong directory prefix
    ):
        assert not rx.search(bad), f'hook must not fire for {bad!r}'


def test_csv_rels_includes_spine_and_architecture():
    """detect_state must track spine.csv + architecture.csv so a dirty
    spine triggers sync export of spine.md (and same for architecture)."""
    from storyforge.cmd_sync import CSV_RELS
    assert 'reference/spine.csv' in CSV_RELS
    assert 'reference/architecture.csv' in CSV_RELS
    assert 'reference/scenes.csv' in CSV_RELS
    assert 'reference/scene-intent.csv' in CSV_RELS
    assert 'reference/scene-briefs.csv' in CSV_RELS


def test_missing_one_way_csv_does_not_block_sync(git_project):
    """Deleting spine.csv after committing it should NOT trigger
    'missing-csv' refusal — one-way CSVs are author-deletable (sync
    just stops regenerating their derived MD)."""
    from storyforge.cmd_sync import run_sync, detect_state, DEFAULT_OUTPUT_PATH

    # First, seed a spine.csv and commit it (so it's "in HEAD")
    spine_csv = os.path.join(git_project, 'reference', 'spine.csv')
    with open(spine_csv, 'w') as f:
        f.write('id|seq|title|summary|function|part\n')
        f.write('ev-1|1|t|sentence.|f|1\n')
    _git(git_project, 'add', 'reference/spine.csv')
    _git(git_project, 'commit', '-q', '-m', 'add spine.csv')

    # Now delete the file from disk (mimics author removing it)
    os.remove(spine_csv)

    # detect_state should NOT list spine.csv in missing_csvs
    state = detect_state(git_project)
    assert 'reference/spine.csv' not in state['missing_csvs'], (
        f'one-way CSV should not block sync; got missing_csvs={state["missing_csvs"]!r}'
    )


def test_missing_round_trip_csv_still_blocks_sync(git_project):
    """Round-trip CSVs (scenes.csv etc.) still hard-refuse when deleted —
    scenes-review.md depends on them."""
    from storyforge.cmd_sync import detect_state

    scenes_csv = os.path.join(git_project, 'reference', 'scenes.csv')
    assert os.path.isfile(scenes_csv)
    # The fixture's scenes.csv is in HEAD. Remove it from disk.
    os.remove(scenes_csv)
    state = detect_state(git_project)
    assert 'reference/scenes.csv' in state['missing_csvs']


def test_sync_tracked_paths_includes_outline_md():
    """The pre-commit hook only stages files in SYNC_TRACKED_PATHS after
    sync regenerates them. outline.md MUST be in the list — otherwise
    every commit that touches a summary column leaves outline.md
    perpetually unstaged."""
    from storyforge.cmd_sync import SYNC_TRACKED_PATHS
    assert 'reference/outline.md' in SYNC_TRACKED_PATHS
    # And the existing one-way MDs too, for completeness.
    assert 'reference/spine.md' in SYNC_TRACKED_PATHS
    assert 'reference/architecture.md' in SYNC_TRACKED_PATHS


def test_hook_script_uses_staged_diff(git_project):
    """The hook reads --cached (staged) changes, not the full working tree,
    so partial-staging commits don't trigger spurious conflict reports."""
    from storyforge.cmd_sync import HOOK_SCRIPT
    # The first git diff in the script must filter by --cached.
    first_diff = HOOK_SCRIPT.find('git diff')
    assert first_diff != -1
    assert '--cached' in HOOK_SCRIPT[first_diff:first_diff + 100]


def test_hook_script_fails_closed_without_storyforge():
    """When no runner is discoverable (PATH, $STORYFORGE_HOME, baked-in),
    the hook must exit 1 — not silently exit 0 and let desync ship.
    """
    from storyforge.cmd_sync import HOOK_SCRIPT
    idx = HOOK_SCRIPT.find("can't find a 'storyforge' runner")
    assert idx != -1, 'expected the runner-not-found error branch in HOOK_SCRIPT'
    tail = HOOK_SCRIPT[idx:idx + 500]
    assert 'exit 1' in tail
    pre_exit = tail[:tail.index('exit 1')]
    assert 'exit 0' not in pre_exit


def test_sync_in_non_git_directory_errors_clearly(tmp_path):
    """Running sync outside a git repo must surface the missing-repo case
    rather than mis-classifying everything as 'dirty'."""
    from storyforge.cmd_sync import detect_state
    # tmp_path is a non-git directory
    import pytest
    with pytest.raises(RuntimeError, match='not inside a git working tree'):
        detect_state(str(tmp_path))


def test_sync_regenerates_wiped_md(git_project):
    """If a tracked MD is deleted on disk, sync should re-export from the
    CSVs rather than crashing trying to import from a missing file.
    """
    from storyforge.cmd_sync import run_sync, DEFAULT_OUTPUT_PATH

    run_sync(git_project)
    _git(git_project, 'add', DEFAULT_OUTPUT_PATH)
    _git(git_project, 'commit', '-q', '-m', 'add MD')

    md_path = os.path.join(git_project, DEFAULT_OUTPUT_PATH)
    os.remove(md_path)

    status = run_sync(git_project)
    assert status == 'exported'
    assert os.path.isfile(md_path)


def test_import_silently_skips_scene_with_row_only_in_one_csv(project_dir):
    """A scene present in scenes.csv but missing from scene-briefs.csv must
    not raise — only IDs missing from *all* CSVs are an error.
    """
    from storyforge.cmd_scenes_export import export_scenes
    from storyforge.cmd_scenes_import import import_scenes
    from storyforge.csv_cli import _read_lines, _write_lines

    # Remove act1-sc01 from scene-briefs.csv (still in scenes + intent).
    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    lines = _read_lines(briefs_csv)
    kept = [lines[0]] + [l for l in lines[1:] if not l.startswith('act1-sc01|')]
    _write_lines(briefs_csv, kept)

    out = os.path.join(project_dir, 'reference', 'scenes-review.md')
    export_scenes(project_dir, out)

    # The MD references act1-sc01 (it's in scenes.csv). Import must succeed.
    changes = import_scenes(project_dir, out, dry_run=True)
    assert changes == [], 'expected no diff round-trip immediately after export'
