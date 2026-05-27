"""Tests for storyforge migrate-medium command."""

import os
import shutil

import pytest

from storyforge.cmd_migrate_medium import (
    parse_args,
    step1_validate_direction,
    step2_create_archive,
    step3_snapshot_state,
    step4_update_yaml,
    step5_transform_scenes_csv,
    step6_transform_briefs_csv,
    step7_archive_and_clear_scenes_dir,
    step8_add_bible_visual_notes,
    step8b_scaffold_canon_tree,
    main,
)
from storyforge.common import get_medium


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_csv_rows(path):
    """Return (header, rows_as_dicts) from a pipe-delimited CSV."""
    with open(path, encoding='utf-8') as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    if not lines:
        return [], []
    header = lines[0].split('|')
    rows = [dict(zip(header, l.split('|'))) for l in lines[1:]]
    return header, rows


def _get_archive_dir(project_dir):
    """Return the first migration archive directory found, or None."""
    migration_root = os.path.join(project_dir, 'working', 'migration')
    if not os.path.isdir(migration_root):
        return None
    entries = sorted(os.listdir(migration_root))
    if not entries:
        return None
    return os.path.join(migration_root, entries[0])


# ---------------------------------------------------------------------------
# Test 1: Novel → GN basic
# ---------------------------------------------------------------------------

def test_migrate_novel_to_gn_basic(project_dir, monkeypatch):
    """Start with novel fixture, run migrate-medium --to graphic-novel.

    Asserts:
    - medium changed to graphic-novel
    - target_words cleared in scenes.csv
    - scenes/ archived (no .md files remain)
    - archive dir exists with expected content
    - bibles have stub note appended
    """
    monkeypatch.chdir(project_dir)

    # Verify starting state
    assert get_medium(project_dir) == 'novel'

    scenes_dir = os.path.join(project_dir, 'scenes')
    initial_scene_files = [f for f in os.listdir(scenes_dir) if f.endswith('.md')]
    assert len(initial_scene_files) > 0, 'fixture must have scene files'

    # Run migration
    main(['--to', 'graphic-novel', '--no-commit', '--force'])

    # Medium changed
    assert get_medium(project_dir) == 'graphic-novel'

    # target_words and word_count cleared
    _, rows = _read_csv_rows(os.path.join(project_dir, 'reference', 'scenes.csv'))
    for row in rows:
        assert row.get('target_words', '') == '', \
            f'target_words should be cleared, got {row.get("target_words")!r}'
        assert row.get('word_count', '') == '', \
            f'word_count should be cleared, got {row.get("word_count")!r}'

    # All scenes reset to mapped
    for row in rows:
        assert row.get('status') == 'mapped', \
            f'scene {row.get("id")} should be mapped, got {row.get("status")!r}'

    # scenes/ is cleared of .md files
    remaining = [f for f in os.listdir(scenes_dir) if f.endswith('.md')]
    assert remaining == [], f'scenes/ should be empty of .md files, found: {remaining}'

    # Archive exists and contains scenes
    archive_dir = _get_archive_dir(project_dir)
    assert archive_dir is not None, 'migration archive directory must exist'
    assert 'novel' in archive_dir and 'graphic-novel' in archive_dir

    archived_scenes = os.path.join(archive_dir, 'scenes')
    assert os.path.isdir(archived_scenes), 'archive must have scenes/ subdir'
    archived_files = [f for f in os.listdir(archived_scenes) if f.endswith('.md')]
    assert len(archived_files) == len(initial_scene_files), \
        f'all original scene files should be in archive'

    # storyforge.yaml in archive
    assert os.path.isfile(os.path.join(archive_dir, 'storyforge.yaml'))

    # scenes.csv in archive
    assert os.path.isfile(os.path.join(archive_dir, 'reference', 'scenes.csv'))

    # Bible visual notes appended
    char_bible = os.path.join(project_dir, 'reference', 'character-bible.md')
    if os.path.isfile(char_bible):
        with open(char_bible) as f:
            content = f.read()
        assert 'Graphic Novel Migration Note' in content, \
            'character-bible.md should have visual migration note'

    # T2-3: canon tree scaffolded by step8b survives the full main() run
    canon_dir = os.path.join(project_dir, 'reference', 'canon')
    assert os.path.isdir(canon_dir), \
        'reference/canon/ should be scaffolded by step8b'
    assert os.path.isfile(os.path.join(canon_dir, 'style-foundation.md')), \
        'starter canon files should be present'
    assert os.path.isfile(
        os.path.join(project_dir, 'reference', 'visual-style.md'),
    ), 'reference/visual-style.md should be scaffolded'


# ---------------------------------------------------------------------------
# Test 2: GN → novel basic
# ---------------------------------------------------------------------------

def test_migrate_gn_to_novel_basic(project_dir_gn, monkeypatch, tmp_path):
    """Start with GN fixture (with a drafted scene), run migrate-medium --to novel.

    Asserts:
    - medium changed to novel
    - target_pages, panel_count, page_count cleared
    - GN brief columns cleared
    - scenes/ archived
    """
    monkeypatch.chdir(project_dir_gn)

    assert get_medium(project_dir_gn) == 'graphic-novel'

    # Add a drafted scene file to the GN fixture
    scenes_dir = os.path.join(project_dir_gn, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    test_scene = os.path.join(scenes_dir, 'the-blank-page.md')
    with open(test_scene, 'w') as f:
        f.write('## Page 1\n\n**Panel 1**\nFake panel script.\n')

    main(['--to', 'novel', '--no-commit', '--force'])

    # Medium changed
    assert get_medium(project_dir_gn) == 'novel'

    # GN scene columns cleared
    _, rows = _read_csv_rows(os.path.join(project_dir_gn, 'reference', 'scenes.csv'))
    for row in rows:
        for col in ('target_pages', 'panel_count', 'page_count'):
            assert row.get(col, '') == '', \
                f'{col} should be cleared, got {row.get(col)!r}'
        assert row.get('status') == 'mapped'

    # GN brief columns cleared
    _, brief_rows = _read_csv_rows(
        os.path.join(project_dir_gn, 'reference', 'scene-briefs.csv')
    )
    gn_cols = ['page_layout', 'panel_breakdown', 'visual_keywords',
               'page_turn_beats', 'caption_strategy']
    for row in brief_rows:
        for col in gn_cols:
            if col in row:
                assert row[col] == '', \
                    f'GN column {col} should be cleared, got {row[col]!r}'

    # scenes/ cleared
    remaining = [f for f in os.listdir(scenes_dir)
                 if f.endswith('.md') and f != '.gitkeep']
    assert remaining == [], f'scenes/ should be empty after migration, found: {remaining}'

    # Archive exists with scenes/
    archive_dir = _get_archive_dir(project_dir_gn)
    assert archive_dir is not None
    archived = os.path.join(archive_dir, 'scenes')
    assert os.path.isdir(archived)
    assert 'the-blank-page.md' in os.listdir(archived)


# ---------------------------------------------------------------------------
# Test 3: Refuses when already in target medium
# ---------------------------------------------------------------------------

def test_migrate_refuses_when_already_target(project_dir_gn, monkeypatch):
    """Running migrate-medium --to graphic-novel on a GN project exits 1."""
    monkeypatch.chdir(project_dir_gn)
    assert get_medium(project_dir_gn) == 'graphic-novel'

    with pytest.raises(SystemExit) as exc_info:
        main(['--to', 'graphic-novel', '--no-commit'])
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Test 4: --force bypasses refusal
# ---------------------------------------------------------------------------

def test_migrate_force_bypasses_refusal(project_dir_gn, monkeypatch):
    """Running with --force on an already-target project exits 0 and archives."""
    monkeypatch.chdir(project_dir_gn)
    assert get_medium(project_dir_gn) == 'graphic-novel'

    # Should NOT raise SystemExit(1)
    main(['--to', 'graphic-novel', '--no-commit', '--force'])

    # Archive was still created
    archive_dir = _get_archive_dir(project_dir_gn)
    assert archive_dir is not None, 'archive should be created even with --force'


# ---------------------------------------------------------------------------
# Test 5: --dry-run makes no changes
# ---------------------------------------------------------------------------

def test_migrate_dry_run_makes_no_changes(project_dir, monkeypatch):
    """--dry-run does not modify any files."""
    monkeypatch.chdir(project_dir)

    # Capture original file contents
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    scenes_csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')

    with open(yaml_path) as f:
        original_yaml = f.read()
    with open(scenes_csv_path) as f:
        original_scenes_csv = f.read()
    original_scene_files = sorted(os.listdir(scenes_dir))

    main(['--to', 'graphic-novel', '--dry-run'])

    # Nothing changed
    with open(yaml_path) as f:
        assert f.read() == original_yaml, 'storyforge.yaml should not be changed in dry-run'
    with open(scenes_csv_path) as f:
        assert f.read() == original_scenes_csv, 'scenes.csv should not be changed in dry-run'
    assert sorted(os.listdir(scenes_dir)) == original_scene_files, \
        'scenes/ should not be changed in dry-run'

    # No migration archive created
    migration_root = os.path.join(project_dir, 'working', 'migration')
    assert not os.path.isdir(migration_root) or not os.listdir(migration_root), \
        'migration archive should not be created in dry-run'


# ---------------------------------------------------------------------------
# Test 6: Archive contains snapshot
# ---------------------------------------------------------------------------

def test_archive_contains_snapshot(project_dir, monkeypatch):
    """Verify archive has copies of storyforge.yaml, scenes.csv, scene-briefs.csv, and scenes/."""
    monkeypatch.chdir(project_dir)

    main(['--to', 'graphic-novel', '--no-commit', '--force'])

    archive_dir = _get_archive_dir(project_dir)
    assert archive_dir is not None

    # storyforge.yaml
    assert os.path.isfile(os.path.join(archive_dir, 'storyforge.yaml'))

    # scenes.csv
    assert os.path.isfile(os.path.join(archive_dir, 'reference', 'scenes.csv'))

    # scene-briefs.csv
    assert os.path.isfile(os.path.join(archive_dir, 'reference', 'scene-briefs.csv'))

    # scenes/ files
    archived_scenes = os.path.join(archive_dir, 'scenes')
    assert os.path.isdir(archived_scenes), 'archive must contain scenes/'
    archived_files = [f for f in os.listdir(archived_scenes) if f.endswith('.md')]
    assert len(archived_files) > 0, 'archive must contain at least one scene file'


# ---------------------------------------------------------------------------
# Unit tests for individual steps
# ---------------------------------------------------------------------------

def test_step1_validate_direction_exits_when_already_target(project_dir):
    """step1 exits 1 if project is already at target and force=False."""
    # novel fixture → asking for novel should exit 1
    with pytest.raises(SystemExit) as exc_info:
        step1_validate_direction(project_dir, 'novel', force=False)
    assert exc_info.value.code == 1


def test_step1_validate_direction_allows_force(project_dir):
    """step1 returns (from, to) without exiting when force=True."""
    from_m, to_m = step1_validate_direction(project_dir, 'novel', force=True)
    assert from_m == 'novel'
    assert to_m == 'novel'


def test_step5_clears_novel_columns_for_novel_to_gn(project_dir):
    """N→GN clears target_words and word_count."""
    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    _, before_rows = _read_csv_rows(scenes_csv)
    # Ensure there's something to clear
    assert any(r.get('target_words') for r in before_rows)

    step5_transform_scenes_csv(project_dir, 'novel', 'graphic-novel', dry_run=False)

    _, after_rows = _read_csv_rows(scenes_csv)
    for row in after_rows:
        assert row.get('target_words', '') == ''
        assert row.get('word_count', '') == ''
        assert row.get('status') == 'mapped'


def test_step5_clears_gn_columns_for_gn_to_novel(project_dir_gn):
    """GN→novel clears target_pages, panel_count, page_count."""
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    _, before_rows = _read_csv_rows(scenes_csv)
    assert any(r.get('target_pages') for r in before_rows)

    step5_transform_scenes_csv(project_dir_gn, 'graphic-novel', 'novel', dry_run=False)

    _, after_rows = _read_csv_rows(scenes_csv)
    for row in after_rows:
        assert row.get('target_pages', '') == ''
        assert row.get('status') == 'mapped'


def test_step6_clears_gn_brief_columns(project_dir_gn):
    """GN→novel clears all five GN brief columns."""
    briefs_csv = os.path.join(project_dir_gn, 'reference', 'scene-briefs.csv')
    _, before = _read_csv_rows(briefs_csv)
    assert any(r.get('panel_breakdown') for r in before), \
        'fixture should have panel_breakdown populated'

    step6_transform_briefs_csv(project_dir_gn, 'graphic-novel', 'novel', dry_run=False)

    _, after = _read_csv_rows(briefs_csv)
    gn_cols = ['page_layout', 'panel_breakdown', 'visual_keywords',
               'page_turn_beats', 'caption_strategy']
    for row in after:
        for col in gn_cols:
            if col in row:
                assert row[col] == '', f'{col} should be cleared'


def test_step6_widens_header_for_novel_to_gn(project_dir):
    """step6 widens scene-briefs.csv to the full schema on novel→GN.

    The five GN columns are added (empty) so the author can populate them
    after migration without manually editing the header.
    """
    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    with open(briefs_csv) as f:
        original_header = f.readline().strip().split('|')
    # Novel fixture should NOT have GN columns yet
    assert 'page_layout' not in original_header

    result = step6_transform_briefs_csv(project_dir, 'novel', 'graphic-novel', dry_run=False)
    assert result.startswith('done')

    with open(briefs_csv) as f:
        new_header = f.readline().strip().split('|')
    # After widening, GN columns must be present
    for col in ('page_layout', 'panel_breakdown', 'visual_keywords',
                'page_turn_beats', 'caption_strategy'):
        assert col in new_header, f'{col} must be in widened header'


def test_step8_appends_visual_note_when_no_visual_sections(project_dir):
    """step8 appends visual note to bibles that lack ### Visual sections."""
    char_bible = os.path.join(project_dir, 'reference', 'character-bible.md')
    assert os.path.isfile(char_bible)
    with open(char_bible) as f:
        content = f.read()
    assert '### Visual' not in content, 'fixture bible should not have ### Visual'

    modified = step8_add_bible_visual_notes(project_dir, dry_run=False)
    assert char_bible in modified or any(char_bible == m for m in modified)

    with open(char_bible) as f:
        updated = f.read()
    assert 'Graphic Novel Migration Note' in updated


def test_step8b_scaffolds_canon_tree(project_dir):
    """step8b copies templates/reference/canon/ + visual-style.md so the
    author can start authoring canon blocks immediately after the
    novel→GN migration completes."""
    assert not os.path.isdir(os.path.join(project_dir, 'reference', 'canon'))
    assert not os.path.isfile(
        os.path.join(project_dir, 'reference', 'visual-style.md'),
    )
    created = step8b_scaffold_canon_tree(project_dir, dry_run=False)
    assert 'reference/canon/' in created
    assert 'reference/visual-style.md' in created
    # Starter templates landed.
    assert os.path.isfile(
        os.path.join(project_dir, 'reference', 'canon',
                     'style-foundation.md'),
    )
    assert os.path.isfile(
        os.path.join(project_dir, 'reference', 'canon', 'characters',
                     '_template.md'),
    )


def test_step8b_idempotent_when_canon_dir_exists(project_dir):
    """If reference/canon/ already exists (author started canon work
    between migration runs), step8b must not clobber it."""
    canon_dir = os.path.join(project_dir, 'reference', 'canon')
    os.makedirs(canon_dir)
    with open(os.path.join(canon_dir, 'authors-own-canon.md'), 'w') as f:
        f.write('AUTHOR WORK — do not clobber')
    created = step8b_scaffold_canon_tree(project_dir, dry_run=False)
    assert 'reference/canon/' not in created
    # The author's file survives.
    with open(os.path.join(canon_dir, 'authors-own-canon.md')) as f:
        assert f.read() == 'AUTHOR WORK — do not clobber'
    # The starter templates were NOT copied (because canon/ existed).
    assert not os.path.isfile(
        os.path.join(canon_dir, 'style-foundation.md'),
    )


def test_step8b_skips_when_canon_dir_exists_even_if_incomplete(project_dir):
    """T2-4: step8b respects any pre-existing reference/canon/ directory,
    even when it contains only a partial canon tree (e.g., the author
    deleted some of the root files). This is deliberate — the author may
    have purposefully removed canon they don't want — but it's silent
    by design. Pinned so a future "helpful" change to fill in missing
    files doesn't sneak past review."""
    canon_dir = os.path.join(project_dir, 'reference', 'canon', 'characters')
    os.makedirs(canon_dir)
    # Only a subdir file — no root canon.
    with open(os.path.join(canon_dir, 'lucien.md'), 'w') as f:
        f.write('# canon')
    created = step8b_scaffold_canon_tree(project_dir, dry_run=False)
    assert 'reference/canon/' not in created
    # Root canon files were NOT filled in.
    assert not os.path.isfile(
        os.path.join(project_dir, 'reference', 'canon', 'style-foundation.md'),
    )
    # Author's file is untouched.
    assert os.path.isfile(os.path.join(canon_dir, 'lucien.md'))


def test_step8b_dry_run_makes_no_changes(project_dir):
    """In dry-run mode, step8b reports what it would do but writes
    nothing."""
    created = step8b_scaffold_canon_tree(project_dir, dry_run=True)
    assert 'reference/canon/' in created
    assert not os.path.isdir(
        os.path.join(project_dir, 'reference', 'canon'),
    )


def test_step8_appends_even_when_visual_already_present(project_dir_gn):
    """step8 always appends the migration note, even when ### Visual sections exist.

    A partial migration (some characters already have a Visual section) would
    otherwise leave the remaining characters without a migration cue. The note
    is additive and harmless to delete; skipping silently leaves gaps.
    """
    char_bible = os.path.join(project_dir_gn, 'reference', 'character-bible.md')
    with open(char_bible) as f:
        content_before = f.read()
    assert '### Visual' in content_before, 'GN fixture should already have ### Visual'

    modified = step8_add_bible_visual_notes(project_dir_gn, dry_run=False)
    # The note SHOULD be appended (changed behavior)
    assert char_bible in modified, 'char_bible should be in modified list'

    with open(char_bible) as f:
        content_after = f.read()
    assert 'Graphic Novel Migration Note' in content_after, \
        'migration note should be appended even when ### Visual exists'
    # The original content is preserved at the front
    assert content_after.startswith(content_before)


def test_migrate_preserves_cut_and_merged_statuses(project_dir, monkeypatch):
    """Scenes with status=cut or status=merged are terminal editorial states
    and MUST be preserved across migration. Resetting them to 'mapped'
    would reactivate scenes the author deliberately removed."""
    monkeypatch.chdir(project_dir)
    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    # Append rows with terminal statuses (13 columns to match the header:
    # id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words)
    with open(scenes_csv, 'a') as f:
        f.write('cut-scene|99|Cut Scene|1|||||||cut||\n')
        f.write('merged-scene|100|Merged Scene|1|||||||merged||\n')
    from storyforge import cmd_migrate_medium
    cmd_migrate_medium.main(['--to', 'graphic-novel', '--no-commit'])

    # Verify cut and merged scenes still have their terminal statuses
    from storyforge.csv_cli import get_field
    assert get_field(scenes_csv, 'cut-scene', 'status') == 'cut', \
        'cut scene status must survive migration'
    assert get_field(scenes_csv, 'merged-scene', 'status') == 'merged', \
        'merged scene status must survive migration'


def test_parse_args_requires_to():
    """parse_args exits with error if --to is missing."""
    with pytest.raises(SystemExit):
        parse_args([])


def test_parse_args_accepts_both_mediums():
    args = parse_args(['--to', 'novel'])
    assert args.target == 'novel'
    args = parse_args(['--to', 'graphic-novel'])
    assert args.target == 'graphic-novel'


def test_parse_args_dry_run_and_force():
    args = parse_args(['--to', 'novel', '--dry-run', '--force'])
    assert args.dry_run is True
    assert args.force is True


# ---------------------------------------------------------------------------
# Regression: Fix #1 — branch creation
# ---------------------------------------------------------------------------

def test_migrate_creates_branch_when_on_main(project_dir, monkeypatch, tmp_path):
    """Per CLAUDE.md, migrate-medium MUST create a feature branch if on main.

    Skipping this would commit a medium conversion directly to main.
    """
    import subprocess
    monkeypatch.chdir(project_dir)
    # Initialize a git repo on main
    subprocess.run(['git', 'init', '-b', 'main'], cwd=project_dir, check=True,
                   capture_output=True)
    subprocess.run(['git', 'add', '-A'], cwd=project_dir, check=True,
                   capture_output=True)
    subprocess.run(['git', '-c', 'user.email=test@test', '-c', 'user.name=test',
                    'commit', '-m', 'initial'], cwd=project_dir, check=True,
                   capture_output=True)
    from storyforge import cmd_migrate_medium
    cmd_migrate_medium.main(['--to', 'graphic-novel'])
    # After migration, HEAD should be on a storyforge/migrate-medium-* branch
    result = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                            cwd=project_dir, capture_output=True, text=True)
    branch = result.stdout.strip()
    assert branch.startswith('storyforge/migrate-medium-'), (
        f'expected feature branch, but on {branch}'
    )


# ---------------------------------------------------------------------------
# Regression: Fix #2 — partial-Visual detection is binary
# ---------------------------------------------------------------------------

def test_migrate_appends_visual_note_even_when_one_visual_section_exists(
        project_dir, monkeypatch):
    """If a bible has SOME ### Visual sections already (partial migration),
    the migration still appends the prompt so the author has a complete cue
    for the un-migrated characters."""
    monkeypatch.chdir(project_dir)
    char_bible = os.path.join(project_dir, 'reference', 'character-bible.md')
    # Seed a partial state: one Visual section
    with open(char_bible, 'a') as f:
        f.write('\n## Alice\n\n### Visual\n\nAlice has red hair.\n\n## Bob\n\n(needs visual)\n')
    from storyforge import cmd_migrate_medium
    cmd_migrate_medium.main(['--to', 'graphic-novel', '--no-commit'])
    # The migration note should still appear at end of file
    with open(char_bible) as f:
        content = f.read()
    assert 'Graphic Novel Migration Note' in content, \
        'migration note must be appended even when partial ### Visual sections exist'
    # Alice's section was NOT removed — original content is intact
    assert '## Alice' in content
    assert '## Bob' in content


# ---------------------------------------------------------------------------
# Regression: Fix #3 — non-scene .md files must not be archived
# ---------------------------------------------------------------------------

def test_migrate_preserves_readme_and_notes_in_scenes_dir(project_dir, monkeypatch):
    """README.md, NOTES.md, and other non-scene .md files in scenes/ must
    NOT be archived as scenes — they are author notes."""
    monkeypatch.chdir(project_dir)
    scenes_dir = os.path.join(project_dir, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    # Create a scene-shaped file and a README
    for sid in ['the-opening', 'README', 'NOTES']:
        with open(os.path.join(scenes_dir, f'{sid}.md'), 'w') as f:
            f.write(f'# {sid}\n')
    # Make 'the-opening' an actual scene in scenes.csv
    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    with open(scenes_csv, 'a') as f:
        f.write('the-opening|99|Opening|1|||||||drafted||||\n')
    from storyforge import cmd_migrate_medium
    cmd_migrate_medium.main(['--to', 'graphic-novel', '--no-commit'])
    # README.md and NOTES.md should still be in scenes/
    assert os.path.isfile(os.path.join(scenes_dir, 'README.md')), \
        'README.md must not be archived'
    assert os.path.isfile(os.path.join(scenes_dir, 'NOTES.md')), \
        'NOTES.md must not be archived'
    # the-opening.md should NOT be in scenes/ (archived)
    assert not os.path.isfile(os.path.join(scenes_dir, 'the-opening.md')), \
        'the-opening.md should have been archived'
