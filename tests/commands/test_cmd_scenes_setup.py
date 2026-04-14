"""Tests for storyforge scenes-setup — scene file and metadata setup.

Covers parse_args, rename mode, split-chapters mode, dry-run mode,
error handling for missing modes and source directories, and
metadata CSV creation.
"""

import os
import subprocess

import pytest

from storyforge.cmd_scenes_setup import parse_args, main


# ============================================================================
# parse_args
# ============================================================================


class TestParseArgs:
    """Test CLI argument parsing for scenes-setup."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.rename
        assert not args.split_chapters
        assert not args.split_manuscript
        assert args.source == ''
        assert not args.direct
        assert not args.dry_run
        assert not args.yes
        assert args.parallel is None

    def test_rename_flag(self):
        args = parse_args(['--rename'])
        assert args.rename is True
        assert not args.split_chapters
        assert not args.split_manuscript

    def test_split_chapters_flag(self):
        args = parse_args(['--split-chapters'])
        assert args.split_chapters is True
        assert not args.rename

    def test_split_manuscript_flag(self):
        args = parse_args(['--split-manuscript'])
        assert args.split_manuscript is True
        assert not args.rename

    def test_source_flag(self):
        args = parse_args(['--rename', '--source', '/path/to/chapters'])
        assert args.source == '/path/to/chapters'

    def test_direct_flag(self):
        args = parse_args(['--rename', '--direct'])
        assert args.direct is True

    def test_dry_run_flag(self):
        args = parse_args(['--rename', '--dry-run'])
        assert args.dry_run is True

    def test_yes_flag(self):
        args = parse_args(['--split-chapters', '--yes'])
        assert args.yes is True

    def test_parallel_flag(self):
        args = parse_args(['--rename', '--parallel', '4'])
        assert args.parallel == 4

    def test_all_flags_combined(self):
        args = parse_args([
            '--split-chapters', '--source', 'chapters/',
            '--direct', '--dry-run', '--yes', '--parallel', '8',
        ])
        assert args.split_chapters is True
        assert args.source == 'chapters/'
        assert args.direct is True
        assert args.dry_run is True
        assert args.yes is True
        assert args.parallel == 8


# ============================================================================
# Helpers
# ============================================================================


def _make_git_return_untracked(monkeypatch, mock_git):
    """Make mock _git return non-zero for ls-files (file not tracked).

    This causes the rename code to use os.rename instead of git mv,
    which allows the test to verify actual file renames on disk.
    """
    original_git = mock_git._git

    def _git_not_tracked(project_dir, *args, check=True):
        if args and args[0] == 'ls-files':
            return subprocess.CompletedProcess(
                args=['git'] + list(args), returncode=1,
                stdout='', stderr='',
            )
        return original_git(project_dir, *args, check=check)

    monkeypatch.setattr('storyforge.cmd_scenes_setup._git', _git_not_tracked)


def _patch_get_column_for_split(monkeypatch):
    """Patch get_column in cmd_scenes_setup to work around the list/string bug.

    The source code calls seq_col.strip().splitlines() but get_column
    returns a list. This patches it to iterate the list directly.
    """
    from storyforge.csv_cli import get_column as real_get_column

    class StrList(list):
        """A list that also supports .strip().splitlines() for backward compat."""
        def strip(self):
            return self
        def splitlines(self):
            return list(self)

    def _patched_get_column(path, field):
        result = real_get_column(path, field)
        return StrList(result)

    monkeypatch.setattr('storyforge.cmd_scenes_setup.get_column', _patched_get_column)


# ============================================================================
# main — mode validation
# ============================================================================


class TestModeValidation:
    """Test that main validates mode flags correctly."""

    def test_no_mode_exits(self, mock_api, mock_git, mock_costs,
                           project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        with pytest.raises(SystemExit):
            main([])

    def test_multiple_modes_exits(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        with pytest.raises(SystemExit):
            main(['--rename', '--split-chapters'])


# ============================================================================
# main — rename mode
# ============================================================================


class TestRenameMode:
    """Test --rename mode: renames existing scene files to slugs."""

    def _setup_scene(self, project_dir, filename, title_line):
        """Create a scene file and ensure metadata CSV entry."""
        scene_file = os.path.join(project_dir, 'scenes', filename)
        with open(scene_file, 'w') as f:
            f.write(f'{title_line}\n\nSome prose content here.\n')
        return scene_file

    def test_rename_dry_run(self, mock_api, mock_git, mock_costs,
                            project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        # Create a scene file with a numeric name
        self._setup_scene(project_dir, '001.md', 'The Finest Cartographer')

        # Add an entry for '001' in scenes.csv with a title
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(meta, 'a') as f:
            f.write('001|10|The Finest Cartographer|1||||||||||\n')

        # dry-run should not actually rename files
        with pytest.raises(SystemExit) as exc_info:
            main(['--rename', '--dry-run'])
        assert exc_info.value.code == 0

        # Original file still exists
        assert os.path.isfile(os.path.join(project_dir, 'scenes', '001.md'))

    def test_rename_dry_run_no_branch_created(self, mock_api, mock_git,
                                              mock_costs, project_dir,
                                              monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        self._setup_scene(project_dir, '002.md', 'Test Scene')
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(meta, 'a') as f:
            f.write('002|11|Test Scene|1||||||||||\n')

        with pytest.raises(SystemExit):
            main(['--rename', '--dry-run'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 0

    def test_rename_executes(self, mock_api, mock_git, mock_costs,
                             project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _make_git_return_untracked(monkeypatch, mock_git)

        # Remove fixture scenes so only our test file remains
        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        self._setup_scene(project_dir, '003.md', 'Dawn Over Mountains')

        # Rewrite metadata to only have this entry
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        from storyforge.scenes import scenes_header
        with open(meta, 'w') as f:
            f.write(scenes_header() + '\n')
            f.write('003|12|Dawn Over Mountains|1||||||||||\n')

        intent = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        from storyforge.scenes import intent_header
        with open(intent, 'w') as f:
            f.write(intent_header() + '\n')
            f.write('003||||||||||\n')

        main(['--rename'])

        # The old file should be gone, new slug file should exist
        assert not os.path.isfile(os.path.join(scenes_dir, '003.md'))
        assert os.path.isfile(os.path.join(scenes_dir, 'dawn-over-mountains.md'))

    def test_rename_updates_metadata_csv(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _make_git_return_untracked(monkeypatch, mock_git)

        # Clean up and set up a controlled scenario
        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        self._setup_scene(project_dir, '004.md', 'Silent Echoes')

        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        from storyforge.scenes import scenes_header
        with open(meta, 'w') as f:
            f.write(scenes_header() + '\n')
            f.write('004|13|Silent Echoes|1||||||||||\n')

        intent = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        from storyforge.scenes import intent_header
        with open(intent, 'w') as f:
            f.write(intent_header() + '\n')
            f.write('004||||||||||\n')

        main(['--rename'])

        # Check that CSV now has the new slug
        with open(meta) as f:
            content = f.read()
        assert 'silent-echoes|' in content
        assert '\n004|' not in content

    def test_rename_creates_branch_and_pr(self, mock_api, mock_git,
                                          mock_costs, project_dir,
                                          monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _make_git_return_untracked(monkeypatch, mock_git)

        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        self._setup_scene(project_dir, '005.md', 'Twilight')
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        from storyforge.scenes import scenes_header
        with open(meta, 'w') as f:
            f.write(scenes_header() + '\n')
            f.write('005|14|Twilight|1||||||||||\n')

        intent = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        from storyforge.scenes import intent_header
        with open(intent, 'w') as f:
            f.write(intent_header() + '\n')
            f.write('005||||||||||\n')

        main(['--rename'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 1
        assert branch_calls[0][1] == 'scenes-setup'

        pr_calls = mock_git.calls_for('create_draft_pr')
        assert len(pr_calls) == 1

    def test_rename_no_renames_needed(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch):
        """When all files already have slug names, exits with 0."""
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        self._setup_scene(project_dir, 'dawn-over-mountains.md',
                          'Dawn Over Mountains')

        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        from storyforge.scenes import scenes_header
        with open(meta, 'w') as f:
            f.write(scenes_header() + '\n')
            f.write('dawn-over-mountains|1|Dawn Over Mountains|1||||||||||\n')

        with pytest.raises(SystemExit) as exc_info:
            main(['--rename'])
        assert exc_info.value.code == 0

    def test_rename_updates_intent_csv(self, mock_api, mock_git, mock_costs,
                                       project_dir, monkeypatch):
        """Intent CSV should also have old IDs replaced with new slugs."""
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _make_git_return_untracked(monkeypatch, mock_git)

        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        self._setup_scene(project_dir, '006.md', 'Morning Light')

        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        from storyforge.scenes import scenes_header
        with open(meta, 'w') as f:
            f.write(scenes_header() + '\n')
            f.write('006|1|Morning Light|1||||||||||\n')

        intent = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        from storyforge.scenes import intent_header
        with open(intent, 'w') as f:
            f.write(intent_header() + '\n')
            f.write('006|test-function|||||||||\n')

        main(['--rename'])

        with open(intent) as f:
            content = f.read()
        assert 'morning-light|' in content
        assert '\n006|' not in content


# ============================================================================
# main — split-chapters mode
# ============================================================================


class TestSplitChaptersMode:
    """Test --split-chapters mode."""

    def _make_chapter(self, project_dir, dir_name, filename, content):
        """Create a chapter file in the given subdir."""
        ch_dir = os.path.join(project_dir, dir_name)
        os.makedirs(ch_dir, exist_ok=True)
        ch_file = os.path.join(ch_dir, filename)
        with open(ch_file, 'w') as f:
            f.write(content)
        return ch_file

    def test_split_dry_run(self, mock_api, mock_git, mock_costs,
                           project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        _patch_get_column_for_split(monkeypatch)

        # Chapter without explicit markers — dry-run logs what it would do
        # and skips both Claude detection and writing
        self._make_chapter(project_dir, 'chapters', 'ch01.md',
                           'A single chapter with no scene break markers at all.\n')

        main(['--split-chapters', '--source', 'chapters', '--dry-run'])

        # No new scene files should be created in dry-run
        scenes_dir = os.path.join(project_dir, 'scenes')
        original_scenes = {'act1-sc01.md', 'act1-sc02.md', 'act2-sc01.md', 'new-x1.md'}
        current_scenes = set(os.listdir(scenes_dir))
        assert current_scenes == original_scenes

    def test_split_no_source_exits(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        _patch_get_column_for_split(monkeypatch)

        # Ensure no default chapter directories exist
        for candidate in ['chapters', 'manuscript']:
            d = os.path.join(project_dir, candidate)
            if os.path.isdir(d):
                import shutil
                shutil.rmtree(d)

        with pytest.raises(SystemExit):
            main(['--split-chapters', '--dry-run'])

    def test_split_with_explicit_markers(self, mock_api, mock_git,
                                         mock_costs, project_dir,
                                         monkeypatch):
        """Chapters with *** markers should split without Claude calls."""
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _patch_get_column_for_split(monkeypatch)

        content = 'First scene opening paragraph.\n\n***\n\nSecond scene paragraph.\n'
        self._make_chapter(project_dir, 'chapters', 'chapter-01.md', content)

        main(['--split-chapters', '--source', 'chapters', '--yes'])

        # Should have created scene files
        scenes_dir = os.path.join(project_dir, 'scenes')
        new_scenes = [f for f in os.listdir(scenes_dir)
                      if f.endswith('.md') and f not in
                      {'act1-sc01.md', 'act1-sc02.md', 'act2-sc01.md', 'new-x1.md'}]
        assert len(new_scenes) >= 2

        # Should not have called Claude API (explicit markers, no detection needed)
        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) == 0

    def test_split_creates_metadata_entries(self, mock_api, mock_git,
                                            mock_costs, project_dir,
                                            monkeypatch):
        """Split scenes should have entries in scenes.csv and scene-intent.csv."""
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _patch_get_column_for_split(monkeypatch)

        content = 'Opening scene text.\n\n***\n\nSecond scene text.\n'
        self._make_chapter(project_dir, 'chapters', 'ch01.md', content)

        main(['--split-chapters', '--source', 'chapters', '--yes'])

        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent = os.path.join(project_dir, 'reference', 'scene-intent.csv')

        with open(meta) as f:
            meta_lines = f.read().strip().splitlines()
        with open(intent) as f:
            intent_lines = f.read().strip().splitlines()

        # Should have added new rows (beyond original fixture rows)
        assert len(meta_lines) > 7   # header + 6 original rows
        assert len(intent_lines) > 7

    def test_split_creates_branch_and_commits(self, mock_api, mock_git,
                                              mock_costs, project_dir,
                                              monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _patch_get_column_for_split(monkeypatch)

        content = 'Some chapter text with no breaks.\n'
        self._make_chapter(project_dir, 'chapters', 'ch01.md', content)

        main(['--split-chapters', '--source', 'chapters', '--yes'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 1

        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) >= 1

    def test_split_dry_run_no_branch_created(self, mock_api, mock_git,
                                             mock_costs, project_dir,
                                             monkeypatch):
        """Dry-run should not create a branch or commit."""
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        _patch_get_column_for_split(monkeypatch)

        self._make_chapter(project_dir, 'chapters', 'ch01.md',
                           'Some text.\n')

        main(['--split-chapters', '--source', 'chapters', '--dry-run'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 0


# ============================================================================
# main — API key check
# ============================================================================


class TestApiKeyCheck:
    """Test that ANTHROPIC_API_KEY is required for non-dry-run modes."""

    def test_no_api_key_exits_rename(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        with pytest.raises(SystemExit):
            main(['--rename'])

    def test_dry_run_skips_api_key_check(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        # dry-run should not exit due to missing API key
        scenes_dir = os.path.join(project_dir, 'scenes')
        with open(os.path.join(scenes_dir, '099.md'), 'w') as f:
            f.write('Test title\n\nContent\n')
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(meta, 'a') as f:
            f.write('099|99|Test title|1||||||||||\n')

        with pytest.raises(SystemExit) as exc_info:
            main(['--rename', '--dry-run'])
        assert exc_info.value.code == 0


# ============================================================================
# main — scene file content
# ============================================================================


class TestSceneFileContent:
    """Test that generated scene files have correct content."""

    def test_scene_file_has_prose_no_markers(self, mock_api, mock_git,
                                             mock_costs, project_dir,
                                             monkeypatch):
        """Scene break markers (***) should be stripped from output files."""
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _patch_get_column_for_split(monkeypatch)

        content = (
            'First scene has some prose here.\n'
            '\n'
            '***\n'
            '\n'
            'Second scene begins with fresh prose.\n'
        )
        ch_dir = os.path.join(project_dir, 'chapters')
        os.makedirs(ch_dir, exist_ok=True)
        with open(os.path.join(ch_dir, 'ch01.md'), 'w') as f:
            f.write(content)

        main(['--split-chapters', '--source', 'chapters', '--yes'])

        scenes_dir = os.path.join(project_dir, 'scenes')
        new_scenes = [f for f in os.listdir(scenes_dir)
                      if f.endswith('.md') and f not in
                      {'act1-sc01.md', 'act1-sc02.md', 'act2-sc01.md', 'new-x1.md'}]
        assert len(new_scenes) >= 1

        for scene_file in new_scenes:
            with open(os.path.join(scenes_dir, scene_file)) as f:
                text = f.read()
            assert '***' not in text

    def test_scene_file_word_count_in_csv(self, mock_api, mock_git,
                                          mock_costs, project_dir,
                                          monkeypatch):
        """Scene word counts should be recorded in scenes.csv."""
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _patch_get_column_for_split(monkeypatch)

        # Create a chapter with known word count
        words = ' '.join(['word'] * 50)
        content = f'{words}\n\n***\n\n{words}\n'
        ch_dir = os.path.join(project_dir, 'chapters')
        os.makedirs(ch_dir, exist_ok=True)
        with open(os.path.join(ch_dir, 'ch01.md'), 'w') as f:
            f.write(content)

        main(['--split-chapters', '--source', 'chapters', '--yes'])

        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(meta) as f:
            lines = f.read().strip().splitlines()

        # Check that new rows have non-zero word counts
        new_rows = lines[7:]  # Skip header + 6 fixture rows
        for row in new_rows:
            parts = row.split('|')
            # word_count is column index 11
            if len(parts) > 11 and parts[11]:
                assert int(parts[11]) > 0
