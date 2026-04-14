"""Tests for storyforge migrate — project migration to normalized registries.

Covers: parse_args (all flags), individual migration steps, main orchestration
with mocked dependencies, dry-run mode, no-commit mode, idempotency,
and error handling for missing files.
"""

import os
import sys

import pytest

from storyforge.cmd_migrate import (
    parse_args,
    main,
    step1_rename_scene_type,
    step2_remove_threads,
    step3_seed_registries,
    _slugify,
    _read_csv,
    _write_registry,
)


# ============================================================================
# parse_args
# ============================================================================


class TestParseArgs:
    """Exhaustive tests for argument parsing."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.dry_run
        assert not args.no_commit

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_no_commit(self):
        args = parse_args(['--no-commit'])
        assert args.no_commit

    def test_combined_flags(self):
        args = parse_args(['--dry-run', '--no-commit'])
        assert args.dry_run
        assert args.no_commit


# ============================================================================
# _slugify
# ============================================================================


class TestSlugify:
    """Test the slugify helper."""

    def test_simple_text(self):
        assert _slugify('Hello World') == 'hello-world'

    def test_special_characters(self):
        assert _slugify("It's a test!") == 'its-a-test'

    def test_multiple_spaces(self):
        assert _slugify('a   b   c') == 'a-b-c'

    def test_leading_trailing_whitespace(self):
        assert _slugify('  hello  ') == 'hello'

    def test_preserves_hyphens(self):
        assert _slugify('already-slugged') == 'already-slugged'

    def test_empty_string(self):
        assert _slugify('') == ''


# ============================================================================
# _read_csv
# ============================================================================


class TestReadCsv:
    """Test the CSV reader helper."""

    def test_reads_valid_csv(self, tmp_path):
        csv_file = tmp_path / 'test.csv'
        csv_file.write_text('id|name|value\na|Alice|10\nb|Bob|20\n')
        header, rows = _read_csv(str(csv_file))
        assert header == ['id', 'name', 'value']
        assert len(rows) == 2
        assert rows[0] == {'id': 'a', 'name': 'Alice', 'value': '10'}
        assert rows[1] == {'id': 'b', 'name': 'Bob', 'value': '20'}

    def test_missing_file(self, tmp_path):
        header, rows = _read_csv(str(tmp_path / 'nonexistent.csv'))
        assert header == []
        assert rows == []

    def test_empty_file(self, tmp_path):
        csv_file = tmp_path / 'empty.csv'
        csv_file.write_text('')
        header, rows = _read_csv(str(csv_file))
        assert header == []
        assert rows == []

    def test_header_only(self, tmp_path):
        csv_file = tmp_path / 'header.csv'
        csv_file.write_text('id|name\n')
        header, rows = _read_csv(str(csv_file))
        assert header == ['id', 'name']
        assert rows == []

    def test_strips_crlf(self, tmp_path):
        csv_file = tmp_path / 'crlf.csv'
        csv_file.write_bytes(b'id|name\r\na|Alice\r\n')
        header, rows = _read_csv(str(csv_file))
        assert header == ['id', 'name']
        assert rows[0]['name'] == 'Alice'


# ============================================================================
# step1_rename_scene_type
# ============================================================================


class TestStep1RenameSceneType:
    """Test renaming scene_type -> action_sequel in scene-intent.csv."""

    def test_renames_column(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text('id|scene_type|other\nsc1|action|x\nsc2|sequel|y\n')
        result = step1_rename_scene_type(ref_dir, dry_run=False)
        assert result == 'done:2'
        with open(str(intent_path)) as f:
            header = f.readline()
        assert 'action_sequel' in header
        assert 'scene_type' not in header

    def test_dry_run_does_not_modify(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        original = 'id|scene_type|other\nsc1|action|x\n'
        intent_path.write_text(original)
        result = step1_rename_scene_type(ref_dir, dry_run=True)
        assert result == 'done:1'
        assert intent_path.read_text() == original

    def test_already_renamed(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text('id|action_sequel|other\nsc1|action|x\n')
        result = step1_rename_scene_type(ref_dir, dry_run=False)
        assert result == 'skip:already renamed'

    def test_no_file(self, tmp_path):
        result = step1_rename_scene_type(str(tmp_path), dry_run=False)
        assert result == 'skip:no scene-intent.csv'

    def test_empty_file(self, tmp_path):
        ref_dir = str(tmp_path)
        (tmp_path / 'scene-intent.csv').write_text('')
        result = step1_rename_scene_type(ref_dir, dry_run=False)
        assert result == 'skip:empty file'


# ============================================================================
# step2_remove_threads
# ============================================================================


class TestStep2RemoveThreads:
    """Test removing the threads column from scene-intent.csv."""

    def test_removes_threads_column(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text('id|threads|other\nsc1|t1|x\nsc2|t2|y\n')
        result = step2_remove_threads(ref_dir, dry_run=False)
        assert result == 'done:2'
        with open(str(intent_path)) as f:
            content = f.read()
        assert 'threads' not in content
        # Check remaining columns are preserved
        assert 'id|other' in content

    def test_dry_run_does_not_modify(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        original = 'id|threads|other\nsc1|t1|x\n'
        intent_path.write_text(original)
        result = step2_remove_threads(ref_dir, dry_run=True)
        assert result == 'done:1'
        assert intent_path.read_text() == original

    def test_already_removed(self, tmp_path):
        ref_dir = str(tmp_path)
        (tmp_path / 'scene-intent.csv').write_text('id|other\nsc1|x\n')
        result = step2_remove_threads(ref_dir, dry_run=False)
        assert result == 'skip:already removed'

    def test_no_file(self, tmp_path):
        result = step2_remove_threads(str(tmp_path), dry_run=False)
        assert result == 'skip:no scene-intent.csv'


# ============================================================================
# step3_seed_registries
# ============================================================================


class TestStep3SeedRegistries:
    """Test seeding registry files from scene data."""

    def test_seeds_values_csv(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text(
            'id|value_at_stake|mice_threads\n'
            'sc1|truth|\n'
            'sc2|safety|\n'
        )
        # Need scene-briefs.csv for knowledge seeding
        briefs_path = tmp_path / 'scene-briefs.csv'
        briefs_path.write_text('id|knowledge_in|knowledge_out\nsc1||\n')

        results = step3_seed_registries(ref_dir, dry_run=False)
        values_result = [r for r in results if r.startswith('values.csv')][0]
        assert 'done:2' in values_result
        assert os.path.isfile(os.path.join(ref_dir, 'values.csv'))

    def test_seeds_knowledge_csv(self, tmp_path):
        ref_dir = str(tmp_path)
        # Intent file for values/mice
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text('id|value_at_stake|mice_threads\nsc1||\n')
        # Briefs with knowledge
        briefs_path = tmp_path / 'scene-briefs.csv'
        briefs_path.write_text(
            'id|knowledge_in|knowledge_out\n'
            'sc1|fact-a|fact-b\n'
        )
        results = step3_seed_registries(ref_dir, dry_run=False)
        knowledge_result = [r for r in results if r.startswith('knowledge.csv')][0]
        assert 'done:2' in knowledge_result
        assert os.path.isfile(os.path.join(ref_dir, 'knowledge.csv'))

    def test_seeds_mice_threads_csv(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text(
            'id|value_at_stake|mice_threads\n'
            'sc1||+inquiry:map-anomaly\n'
        )
        briefs_path = tmp_path / 'scene-briefs.csv'
        briefs_path.write_text('id|knowledge_in|knowledge_out\nsc1||\n')

        results = step3_seed_registries(ref_dir, dry_run=False)
        mice_result = [r for r in results if r.startswith('mice-threads.csv')][0]
        assert 'done:1' in mice_result

    def test_skips_existing_registry(self, tmp_path):
        ref_dir = str(tmp_path)
        # Pre-create values.csv with entries
        values_path = tmp_path / 'values.csv'
        values_path.write_text('id|name|aliases\ntruth|truth|\n')
        # Intent file
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text('id|value_at_stake|mice_threads\nsc1|truth|\n')
        briefs_path = tmp_path / 'scene-briefs.csv'
        briefs_path.write_text('id|knowledge_in|knowledge_out\nsc1||\n')

        results = step3_seed_registries(ref_dir, dry_run=False)
        values_result = [r for r in results if r.startswith('values.csv')][0]
        assert 'skip' in values_result

    def test_dry_run_does_not_create_files(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text('id|value_at_stake|mice_threads\nsc1|truth|\n')
        briefs_path = tmp_path / 'scene-briefs.csv'
        briefs_path.write_text('id|knowledge_in|knowledge_out\nsc1|fact-a|\n')

        results = step3_seed_registries(ref_dir, dry_run=True)
        # Files should not be created
        assert not os.path.isfile(os.path.join(ref_dir, 'values.csv'))
        assert not os.path.isfile(os.path.join(ref_dir, 'knowledge.csv'))


# ============================================================================
# main — dry run
# ============================================================================


class TestMainDryRun:
    """Test main() in dry-run mode."""

    def test_dry_run_no_file_modifications(self, mock_api, mock_git, mock_costs,
                                           project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        # Patch step5_validate since it imports elaborate/enrich/schema
        monkeypatch.setattr('storyforge.cmd_migrate.step5_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        main(['--dry-run'])
        # No git commits in dry-run mode
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) == 0

    def test_dry_run_no_branch_creation(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_migrate.step5_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        main(['--dry-run'])
        branch_calls = mock_git.calls_for('ensure_on_branch')
        assert len(branch_calls) == 0


# ============================================================================
# main — no-commit mode
# ============================================================================


class TestMainNoCommit:
    """Test main() with --no-commit flag."""

    def test_no_commit_skips_git(self, mock_api, mock_git, mock_costs,
                                 project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        # Patch normalize (step4) and validate (step5) which have heavy imports
        monkeypatch.setattr('storyforge.cmd_migrate.step4_normalize',
                            lambda ref_dir, proj_dir: 0)
        monkeypatch.setattr('storyforge.cmd_migrate.step5_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        main(['--no-commit'])
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) == 0

    def test_no_commit_no_branch_creation(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_migrate.step4_normalize',
                            lambda ref_dir, proj_dir: 0)
        monkeypatch.setattr('storyforge.cmd_migrate.step5_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        main(['--no-commit'])
        branch_calls = mock_git.calls_for('ensure_on_branch')
        assert len(branch_calls) == 0


# ============================================================================
# main — full run
# ============================================================================


class TestMainFullRun:
    """Test main() full migration path."""

    def test_commits_on_full_run(self, mock_api, mock_git, mock_costs,
                                 project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_migrate.step4_normalize',
                            lambda ref_dir, proj_dir: 0)
        monkeypatch.setattr('storyforge.cmd_migrate.step5_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        main([])
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) == 1
        assert 'Migrate' in commit_calls[0][1]

    def test_ensures_on_branch(self, mock_api, mock_git, mock_costs,
                               project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_migrate.step4_normalize',
                            lambda ref_dir, proj_dir: 0)
        monkeypatch.setattr('storyforge.cmd_migrate.step5_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        main([])
        branch_calls = mock_git.calls_for('ensure_on_branch')
        assert len(branch_calls) == 1


# ============================================================================
# main — error handling
# ============================================================================


class TestMainErrors:
    """Test error handling in main()."""

    def test_missing_scenes_csv_exits(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        # Remove scenes.csv to trigger the error
        scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        if os.path.isfile(scenes_csv):
            os.remove(scenes_csv)
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_idempotent_steps(self, mock_api, mock_git, mock_costs,
                              project_dir, monkeypatch):
        """Running migration twice should not cause errors."""
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_migrate.step4_normalize',
                            lambda ref_dir, proj_dir: 0)
        monkeypatch.setattr('storyforge.cmd_migrate.step5_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        # First run
        main(['--no-commit'])
        # Second run (should not raise)
        main(['--no-commit'])
        # Both runs complete successfully (no assertion needed beyond no-raise)
        assert True


# ============================================================================
# _write_registry
# ============================================================================


class TestWriteRegistry:
    """Test registry file writing."""

    def test_writes_header_and_rows(self, tmp_path):
        path = str(tmp_path / 'test.csv')
        _write_registry(path, 'id|name|aliases', ['a|Alice|', 'b|Bob|'])
        with open(path) as f:
            content = f.read()
        assert content == 'id|name|aliases\na|Alice|\nb|Bob|\n'

    def test_empty_rows(self, tmp_path):
        path = str(tmp_path / 'test.csv')
        _write_registry(path, 'id|name', [])
        with open(path) as f:
            content = f.read()
        assert content == 'id|name\n'
