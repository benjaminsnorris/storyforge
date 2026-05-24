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
    from storyforge.cmd_sync import install_hook

    hook_path = install_hook(git_project)
    assert os.path.isfile(hook_path)
    assert os.access(hook_path, os.X_OK), 'hook must be executable'
    content = open(hook_path).read()
    assert 'storyforge sync' in content


def test_install_hook_refuses_to_overwrite_foreign_hook(git_project):
    """If an existing hook isn't ours, we bail rather than clobber."""
    from storyforge.cmd_sync import install_hook

    hook_path = os.path.join(git_project, '.git', 'hooks', 'pre-commit')
    with open(hook_path, 'w') as f:
        f.write('#!/bin/sh\necho "not the storyforge hook"\n')

    with pytest.raises(SystemExit) as exc_info:
        install_hook(git_project)
    assert exc_info.value.code != 0
