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
        """Chapters with *** markers split at the markers; Claude only names
        the scenes (one call per chapter, checked in TestSceneIds)."""
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        content = 'First scene opening paragraph.\n\n***\n\nSecond scene paragraph.\n'
        self._make_chapter(project_dir, 'chapters', 'chapter-01.md', content)

        main(['--split-chapters', '--source', 'chapters', '--yes'])

        # Should have created scene files
        scenes_dir = os.path.join(project_dir, 'scenes')
        new_scenes = [f for f in os.listdir(scenes_dir)
                      if f.endswith('.md') and f not in
                      {'act1-sc01.md', 'act1-sc02.md', 'act2-sc01.md', 'new-x1.md'}]
        assert len(new_scenes) >= 2


    def test_split_creates_metadata_entries(self, mock_api, mock_git,
                                            mock_costs, project_dir,
                                            monkeypatch):
        """Split scenes should have entries in scenes.csv and scene-intent.csv."""
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

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

        header = lines[0].split('|')
        new_rows = [dict(zip(header, row.split('|'))) for row in lines[7:]]
        assert [r['word_count'] for r in new_rows] == ['50', '50']


# ============================================================================
# main — row alignment and chapter order
# ============================================================================


def _new_rows(project_dir, csv_name):
    """Rows appended after the fixture's own rows, keyed by header column."""
    with open(os.path.join(project_dir, 'reference', csv_name)) as f:
        lines = f.read().strip().splitlines()
    header = lines[0].split('|')
    fixture_ids = {'act1-sc01', 'act1-sc02', 'act2-sc01', 'act2-sc02',
                   'act2-sc03', 'new-x1'}
    rows = [dict(zip(header, line.split('|'))) for line in lines[1:]]
    return header, [r for r in rows if r['id'] not in fixture_ids]


def _opening(project_dir, scene_id):
    """First non-blank line of a scene file."""
    with open(os.path.join(project_dir, 'scenes', f'{scene_id}.md')) as f:
        return next(l.strip() for l in f if l.strip())


class TestRowAlignment:
    """Rows written by a split must line up with the CSV's header."""

    def _split(self, project_dir, monkeypatch, content):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        ch_dir = os.path.join(project_dir, 'chapters')
        os.makedirs(ch_dir, exist_ok=True)
        with open(os.path.join(ch_dir, 'ch01.md'), 'w') as f:
            f.write(content)
        main(['--split-chapters', '--source', 'chapters', '--yes'])

    def test_values_land_in_named_columns(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        self._split(project_dir, monkeypatch,
                    'one two three\n\n***\n\nfour five\n')
        header, rows = _new_rows(project_dir, 'scenes.csv')
        assert len(rows) == 2
        for row in rows:
            assert len(row) == len(header)
            assert row['part'] == ''   # chapter files carry no part information
            assert row['location'] == ''
            assert row['status'] == ''
        assert [r['word_count'] for r in rows] == ['3', '2']

    def test_intent_rows_match_intent_header(self, mock_api, mock_git,
                                             mock_costs, project_dir,
                                             monkeypatch):
        self._split(project_dir, monkeypatch, 'alpha\n\n***\n\nbeta\n')
        header, rows = _new_rows(project_dir, 'scene-intent.csv')
        assert len(rows) == 2
        assert all(len(r) == len(header) for r in rows)

    def test_marker_splits_leave_title_for_extraction(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        # The Great Gatsby got titles like "# Chapter I" and "Inside, the
        # crimson room bloomed with light. Tom and Miss Ba"; extraction only
        # fills empty fields, so its real titles were discarded.
        self._split(project_dir, monkeypatch,
                    '# Chapter One\n\nOpening prose here.\n\n***\n\nLater prose.\n')
        _, rows = _new_rows(project_dir, 'scenes.csv')
        assert [r['title'] for r in rows] == ['', '']


class TestChapterOrder:
    """Scenes are sequenced in reading order, not filename order."""

    def test_manuscript_roman_numerals_keep_reading_order(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        numerals = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']
        chapters = [f'Chapter {n}\n\nOpening of {n}.\n\n***\n\nClose of {n}.\n'
                    for n in numerals]
        with open(os.path.join(project_dir, 'manuscript.md'), 'w') as f:
            f.write('\n'.join(chapters))

        main(['--split-manuscript', '--yes'])

        _, rows = _new_rows(project_dir, 'scenes.csv')
        rows.sort(key=lambda r: int(r['seq']))
        assert [_opening(project_dir, r['id']) for r in rows[::2]] == [
            f'Chapter {n}' for n in numerals]

    def test_split_chapters_orders_numbers_naturally(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        ch_dir = os.path.join(project_dir, 'chapters')
        os.makedirs(ch_dir)
        for n in (1, 2, 10):
            with open(os.path.join(ch_dir, f'ch{n}.md'), 'w') as f:
                f.write(f'Ch{n} opens.\n\n***\n\nCh{n} closes.\n')

        main(['--split-chapters', '--source', 'chapters', '--yes'])

        _, rows = _new_rows(project_dir, 'scenes.csv')
        rows.sort(key=lambda r: int(r['seq']))
        assert [_opening(project_dir, r['id']) for r in rows[::2]] == [
            'Ch1 opens.', 'Ch2 opens.', 'Ch10 opens.']


class TestParts:
    """Parts come from the manuscript's own part headings. The Great Gatsby
    has none, but every five chapters used to be made into a new part."""

    def _split(self, project_dir, monkeypatch, text):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        with open(os.path.join(project_dir, 'manuscript.md'), 'w') as f:
            f.write(text)
        main(['--split-manuscript', '--yes'])
        _, rows = _new_rows(project_dir, 'scenes.csv')
        return sorted(rows, key=lambda r: int(r['seq']))

    @staticmethod
    def _chapter(n):
        return f'Chapter {n}\n\nOpening of {n}.\n\n***\n\nClose of {n}.\n\n'

    def test_book_without_parts_has_empty_part(self, mock_api, mock_git,
                                               mock_costs, project_dir, monkeypatch):
        rows = self._split(project_dir, monkeypatch,
                           ''.join(self._chapter(n) for n in range(1, 8)))
        assert len(rows) == 14
        assert {r['part'] for r in rows} == {''}

    def test_part_headings_assign_parts(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        text = ('PART ONE\n\n' + self._chapter(1) + self._chapter(2)
                + '# Part Two: The Return\n\n' + self._chapter(3))
        rows = self._split(project_dir, monkeypatch, text)
        assert [(_opening(project_dir, r['id']), r['part']) for r in rows[::2]] == [
            ('Chapter 1', '1'), ('Chapter 2', '1'), ('Chapter 3', '2')]

    def test_part_heading_is_not_a_chapter_or_scene_text(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        text = self._chapter(1) + 'Part II\n\n' + self._chapter(2)
        rows = self._split(project_dir, monkeypatch, text)
        assert len(rows) == 4
        assert [r['part'] for r in rows] == ['', '', '1', '1']
        scenes_dir = os.path.join(project_dir, 'scenes')
        for r in rows:
            with open(os.path.join(scenes_dir, r['id'] + '.md')) as f:
                assert 'Part II' not in f.read()

    def test_prose_starting_with_part_is_not_a_heading(self):
        from storyforge.cmd_scenes_setup import _is_part_heading
        assert not _is_part_heading('Part of me wanted to stay.')
        assert _is_part_heading('BOOK FIRST')
        assert _is_part_heading('Part 3')


class TestSceneIds:
    """Scene ids are 3-5 word slugs of the scene's event, never positional:
    order lives in seq, so a scene can move without its id lying."""

    def _run(self, project_dir, monkeypatch, mock_api, content, response):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        prompts = []

        def respond(prompt):
            prompts.append(prompt)
            return response
        mock_api.set_response_fn(respond)
        ch_dir = os.path.join(project_dir, 'chapters')
        os.makedirs(ch_dir, exist_ok=True)
        with open(os.path.join(ch_dir, 'ch01.md'), 'w') as f:
            f.write(content)
        main(['--split-chapters', '--source', 'chapters', '--yes', '--direct'])
        _, rows = _new_rows(project_dir, 'scenes.csv')
        return prompts, sorted(rows, key=lambda r: int(r['seq']))

    def test_marker_scenes_named_by_claude(self, mock_api, mock_git, mock_costs,
                                           project_dir, monkeypatch):
        prompts, rows = self._run(
            project_dir, monkeypatch, mock_api,
            'Nick dines at East Egg.\n\n***\n\nTom takes a call.\n',
            'SCENE: 1 | nick-dines-with-the-buchanans | a\n'
            'SCENE: 5 | tom-takes-a-secret-call | b\n')
        assert len(prompts) == 1
        assert 'already fixed by break markers, at lines 1, 5' in prompts[0]
        assert [r['id'] for r in rows] == ['nick-dines-with-the-buchanans',
                                          'tom-takes-a-secret-call']

    def test_detected_scenes_use_slug_capped_at_five_words(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        _, rows = self._run(
            project_dir, monkeypatch, mock_api,
            'Line one.\nLine two.\nLine three.\n',
            'SCENE: 1 | tom-forces-nick-to-meet-his-mistress | a\n'
            'SCENE: 3 | myrtle-buys-a-dog | b\n')
        assert [r['id'] for r in rows] == ['tom-forces-nick-to-meet', 'myrtle-buys-a-dog']
        assert [r['title'] for r in rows] == ['', '']

    def test_unnamed_scene_falls_back_to_content_not_position(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        _, rows = self._run(
            project_dir, monkeypatch, mock_api,
            '# Chapter 1\n\nGatsby stood alone on the lawn.\n\n***\n\nDawn came.\n',
            'no usable answer')
        assert [r['id'] for r in rows] == ['gatsby-stood-alone', 'dawn-came']
        assert not any('ch1' in r['id'] or 'chapter' in r['id'] for r in rows)


class TestSceneIdSlug:
    def test_caps_words(self):
        from storyforge.scenes import scene_id_slug
        assert scene_id_slug('Gatsby Reunites With Daisy At Last In The Rain') == \
            'gatsby-reunites-with-daisy'

    def test_no_dangling_function_word(self):
        from storyforge.scenes import scene_id_slug
        assert scene_id_slug('gatsby-is-shot-in-the-pool') == 'gatsby-is-shot'
        assert scene_id_slug('daisy-yields-to-tom-while-gatsby-waits') == 'daisy-yields-to-tom'

    def test_short_name_kept(self):
        from storyforge.scenes import scene_id_slug
        assert scene_id_slug('the-valley-of-ashes') == 'valley-of-ashes'
