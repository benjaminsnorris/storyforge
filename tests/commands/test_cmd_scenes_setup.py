"""Tests for storyforge scenes-setup — scene file and metadata setup.

Covers parse_args, rename mode, split-chapters mode, renumber mode, dry-run mode,
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


    def test_failed_detection_leaves_the_chapter_unsplit_and_exits_1(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        """SF-1: a chapter whose detection failed (here refused in the
        batch) was split as a single scene with a permanent id."""
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        def refused(results_url, output_dir, log_dir, keep_incomplete=False):
            with open(os.path.join(output_dir, '.status-ch01'), 'w') as f:
                f.write('fail')  # what the download writes for a refusal
            return []
        monkeypatch.setattr('storyforge.cmd_scenes_setup.download_batch_results', refused)
        self._make_chapter(project_dir, 'chapters', 'ch01.md', 'One. Two. Three.\n')
        before = sorted(os.listdir(os.path.join(project_dir, 'scenes')))

        with pytest.raises(SystemExit) as exit_info:
            main(['--split-chapters', '--source', 'chapters', '--yes'])

        assert exit_info.value.code == 1
        assert sorted(os.listdir(os.path.join(project_dir, 'scenes'))) == before
        out = capsys.readouterr().out
        assert 'the chapter is not split' in out
        assert 'ch01: the batch reply errored, was refused or was cut off' in out
        assert mock_git.calls_for('commit_and_push')

    def test_failed_direct_detection_leaves_the_chapter_unsplit(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        def refuse(*a, **kw):
            raise RuntimeError('model refused the request (cyber)')
        monkeypatch.setattr('storyforge.cmd_scenes_setup.invoke_to_file', refuse)
        self._make_chapter(project_dir, 'chapters', 'ch01.md', 'One. Two. Three.\n')
        before = sorted(os.listdir(os.path.join(project_dir, 'scenes')))

        with pytest.raises(SystemExit):
            main(['--split-chapters', '--source', 'chapters', '--yes', '--direct'])

        assert sorted(os.listdir(os.path.join(project_dir, 'scenes'))) == before
        assert 'ch01: model refused the request' in capsys.readouterr().out

    def test_cut_off_direct_detection_leaves_the_chapter_unsplit(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        """A cut-off reply names only some boundaries; splitting on it wrote
        wrong scene files."""
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        mock_api.set_response_dict({'content': [{'type': 'text', 'text': 'BOUNDARY: 1'}],
                                    'usage': {'input_tokens': 1, 'output_tokens': 1},
                                    'stop_reason': 'max_tokens'})
        self._make_chapter(project_dir, 'chapters', 'ch01.md', 'One. Two. Three.\n')
        before = sorted(os.listdir(os.path.join(project_dir, 'scenes')))

        with pytest.raises(SystemExit):
            main(['--split-chapters', '--source', 'chapters', '--yes', '--direct'])

        assert sorted(os.listdir(os.path.join(project_dir, 'scenes'))) == before
        assert 'ch01: the reply was cut off at max_tokens' in capsys.readouterr().out

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

    def test_volume_headings_assign_parts(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        # Pride and Prejudice was published in three volumes, each numbering
        # its chapters from I; the volumes are the book's real parts.
        text = ('# Volume I\n\n' + self._chapter(1) + self._chapter(2)
                + '# Volume II\n\n' + self._chapter(1))
        rows = self._split(project_dir, monkeypatch, text)
        assert [r['part'] for r in rows[::2]] == ['1', '1', '2']

    def test_volume_heading_forms(self):
        from storyforge.cmd_scenes_setup import _is_part_heading
        assert _is_part_heading('VOL. II.')
        assert _is_part_heading('Volume Three')
        assert not _is_part_heading('Volume one of the encyclopaedia lay open.')


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


class TestNoTextLost:
    """Review critical #2: a part heading ended the chapter before it, so
    prose that looked like a heading cut off the rest of its chapter, and a
    book with parts but unrecognized chapter headings lost almost all text."""

    def _scene_words(self, project_dir, rows):
        total = 0
        for r in rows:
            with open(os.path.join(project_dir, 'scenes', r['id'] + '.md')) as f:
                total += len(f.read().split())
        return total

    def _split(self, project_dir, monkeypatch, text):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        with open(os.path.join(project_dir, 'manuscript.md'), 'w') as f:
            f.write(text)
        main(['--split-manuscript', '--yes'])
        _, rows = _new_rows(project_dir, 'scenes.csv')
        return rows

    def test_prose_that_starts_like_a_part_heading(self, mock_api, mock_git,
                                                   mock_costs, project_dir, monkeypatch):
        text = ('Chapter 1\n\nThe plan had three parts.\n\n'
                'Part one of the plan was simple: wait for dark.\n\n'
                'Part two was harder.\n\n***\n\nThey waited all night.\n')
        rows = self._split(project_dir, monkeypatch, text)
        assert {r['part'] for r in rows} == {''}
        # Every word survives except the *** break marker
        assert self._scene_words(project_dir, rows) == len(text.split()) - 1

    def test_parts_with_unrecognized_chapter_headings(self, mock_api, mock_git,
                                                      mock_costs, project_dir, monkeypatch):
        text = ('PART ONE\n\nI\n\nFirst chapter prose here.\n\nII\n\nSecond chapter prose.\n\n'
                'PART TWO\n\nIII\n\nThird chapter prose at the end.\n')
        rows = self._split(project_dir, monkeypatch, text)
        assert self._scene_words(project_dir, rows) == len(text.split()) - 4
        assert sorted({r['part'] for r in rows}) == ['1', '2']

    def test_part_preamble_opens_next_chapter(self, mock_api, mock_git, mock_costs,
                                              project_dir, monkeypatch):
        text = ('Chapter 1\n\nOne.\n\nPART TWO\n\nAn epigraph for part two.\n\n'
                'Chapter 2\n\nTwo.\n')
        rows = sorted(self._split(project_dir, monkeypatch, text), key=lambda r: int(r['seq']))
        assert [r['part'] for r in rows] == ['', '1']
        with open(os.path.join(project_dir, 'scenes', rows[1]['id'] + '.md')) as f:
            assert 'An epigraph for part two.' in f.read()

    def test_heading_regex_requires_whole_line(self):
        from storyforge.cmd_scenes_setup import _is_part_heading
        assert not _is_part_heading('Part one of the plan was simple: wait for dark.')
        assert _is_part_heading('Part Two: The Return')
        assert _is_part_heading('BOOK FIRST')


class TestMarkdownHeadingsWithoutChapterWord:
    """A Christmas Carol is divided into staves, not chapters. "# Stave I:
    Marley's Ghost" matched no chapter pattern, so the whole book became one
    28,000-word chapter called "Manuscript"."""

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
    def _stave(n, title):
        return f'# Stave {n}: {title}\n\nOpening of {n}.\n\n***\n\nClose of {n}.\n\n'

    def test_staves_are_chapters(self, mock_api, mock_git, mock_costs,
                                 project_dir, monkeypatch):
        text = (self._stave('I', "MARLEY'S GHOST")
                + self._stave('II', 'THE FIRST OF THE THREE SPIRITS')
                + self._stave('III', 'THE SECOND OF THE THREE SPIRITS'))
        rows = self._split(project_dir, monkeypatch, text)
        assert len(rows) == 6
        assert [_opening(project_dir, r['id']) for r in rows[::2]] == [
            "# Stave I: MARLEY'S GHOST", '# Stave II: THE FIRST OF THE THREE SPIRITS',
            '# Stave III: THE SECOND OF THE THREE SPIRITS']

    def test_title_heading_with_no_prose_is_front_matter(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        text = ('# A Christmas Carol\n\n' + self._stave('I', 'One')
                + self._stave('II', 'Two'))
        rows = self._split(project_dir, monkeypatch, text)
        assert len(rows) == 4
        assert _opening(project_dir, rows[0]['id']) == '# Stave I: One'

    def test_chapter_headings_still_win(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        # With real chapter headings, other markdown headings stay in the text.
        text = ('# Chapter 1\n\nOne.\n\n## A letter\n\nDear sir.\n\n***\n\nLater.\n\n'
                '# Chapter 2\n\nTwo.\n\n***\n\nEnd.\n')
        rows = self._split(project_dir, monkeypatch, text)
        assert len(rows) == 4
        with open(os.path.join(project_dir, 'scenes', rows[0]['id'] + '.md')) as f:
            assert '## A letter' in f.read()


    def test_prelude_and_finale_are_chapters(self, mock_api, mock_git, mock_costs,
                                             project_dir, monkeypatch):
        """F-117 (Middlemarch): among chapter headings, "# Prelude" was
        dropped as front matter and "# Finale" ran on inside the last
        chapter."""
        text = ('# Prelude\n\nSaint Theresa set out.\n\n# Book I: Miss Brooke\n\n'
                '# Chapter I\n\nMiss Brooke had beauty.\n\n# Chapter II\n\nDinner.\n\n'
                '# Finale\n\nEvery limit is a beginning.\n')
        rows = self._split(project_dir, monkeypatch, text)
        assert [_opening(project_dir, r['id']) for r in rows] == [
            '# Prelude', '# Chapter I', '# Chapter II', '# Finale']
        assert [r['part'] for r in rows] == ['', '1', '1', '1']

    def test_prose_starting_with_prologue_is_not_a_heading(self):
        from storyforge.cmd_scenes_setup import _OTHER_CHAPTER_RE
        assert not _OTHER_CHAPTER_RE.match('Prologue to the tale was long, and dull.')
        assert _OTHER_CHAPTER_RE.match('PRELUDE.')
        assert _OTHER_CHAPTER_RE.match('Epilogue: Ten Years Later')

class TestSetextUnderlineIsNotABreak:
    def test_dash_under_text_is_heading_not_break(self, mock_api, mock_git, mock_costs,
                                                  project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        ch_dir = os.path.join(project_dir, 'chapters')
        os.makedirs(ch_dir)
        with open(os.path.join(ch_dir, 'ch01.md'), 'w') as f:
            f.write('A Heading\n---\n\nProse.\n\n---\n\nMore prose.\n')
        main(['--split-chapters', '--source', 'chapters', '--yes'])
        _, rows = _new_rows(project_dir, 'scenes.csv')
        assert len(rows) == 2   # split at the blank-preceded marker only


class TestChapterMap:
    """F-102 (storyforge-evals): split-manuscript knew every chapter but never
    wrote reference/chapter-map.csv, so publish failed on every classic."""

    def _split(self, project_dir, monkeypatch, text, keep_map=False):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        map_csv = os.path.join(project_dir, 'reference', 'chapter-map.csv')
        if not keep_map:
            os.remove(map_csv)
        with open(os.path.join(project_dir, 'manuscript.md'), 'w') as f:
            f.write(text)
        main(['--split-manuscript', '--yes'])
        with open(map_csv) as f:
            lines = f.read().strip().splitlines()
        header = lines[0].split('|')
        return [dict(zip(header, l.split('|'))) for l in lines[1:]]

    @staticmethod
    def _chapter(n):
        return f'# Chapter {n}\n\nOpening of {n}.\n\n***\n\nClose of {n}.\n\n'

    def test_split_manuscript_writes_the_map(self, mock_api, mock_git,
                                             mock_costs, project_dir, monkeypatch):
        text = ('PART ONE\n\n' + self._chapter('I') + self._chapter('II')
                + 'PART TWO\n\n' + self._chapter('III'))
        rows = self._split(project_dir, monkeypatch, text)
        assert [r['chapter'] for r in rows] == ['1', '2', '3']
        assert [r['title'] for r in rows] == ['Chapter I', 'Chapter II', 'Chapter III']
        assert [r['part'] for r in rows] == ['1', '1', '2']
        # The heading stays in the first scene's text: assembly adds none.
        assert {r['heading'] for r in rows} == {'none'}
        for r in rows:
            ids = r['scenes'].split(';')
            assert len(ids) == 2
            assert _opening(project_dir, ids[0]) == f'# {r["title"]}'

    def test_written_map_is_fresh(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch):
        from storyforge.common import check_chapter_map_freshness
        # The fixture's own scenes are not in a new map; drop them.
        for name in ('scenes.csv', 'scene-intent.csv'):
            path = os.path.join(project_dir, 'reference', name)
            with open(path) as f:
                header = f.readline()
            with open(path, 'w') as f:
                f.write(header)
        self._split(project_dir, monkeypatch,
                    self._chapter(1) + self._chapter(2))
        is_fresh, missing, extra = check_chapter_map_freshness(project_dir)
        assert (is_fresh, missing, extra) == (True, [], [])

    def test_existing_map_is_left_alone(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        map_csv = os.path.join(project_dir, 'reference', 'chapter-map.csv')
        with open(map_csv) as f:
            before = f.read()
        self._split(project_dir, monkeypatch, self._chapter(1), keep_map=True)
        with open(map_csv) as f:
            assert f.read() == before

    def test_split_chapters_without_headings_titles_by_file(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        os.remove(os.path.join(project_dir, 'reference', 'chapter-map.csv'))
        ch_dir = os.path.join(project_dir, 'chapters')
        os.makedirs(ch_dir)
        with open(os.path.join(ch_dir, 'the-arrival.md'), 'w') as f:
            f.write('They came at dusk.\n\n***\n\nNobody slept.\n')
        main(['--split-chapters', '--source', 'chapters', '--yes'])
        with open(os.path.join(project_dir, 'reference', 'chapter-map.csv')) as f:
            lines = f.read().strip().splitlines()
        row = lines[1].split('|')
        assert row[:4] == ['1', 'the-arrival', 'numbered', '']
        assert len(row[4].split(';')) == 2


# ============================================================================
# main — a chapter epigraph stays with the chapter's opening scene (F-120)
# ============================================================================


_FIXTURES = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'fixtures')


class TestEpigraphStaysWithOpeningScene:
    """Middlemarch heads every chapter with an epigraph. For Chapter LVII the
    boundary model split the epigraph (114 words of verse, its line breaks
    flattened) off as its own scene, chapter-epigraph-scott-childhood-verse."""

    def _run(self, project_dir, monkeypatch, mock_api, content, response):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        mock_api.set_response(response)
        ch_dir = os.path.join(project_dir, 'chapters')
        os.makedirs(ch_dir, exist_ok=True)
        with open(os.path.join(ch_dir, 'ch01.md'), 'w') as f:
            f.write(content)
        main(['--split-chapters', '--source', 'chapters', '--yes', '--direct'])
        _, rows = _new_rows(project_dir, 'scenes.csv')
        return sorted(rows, key=lambda r: int(r['seq']))

    def test_middlemarch_ch57_epigraph_not_its_own_scene(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch,
            capsys):
        with open(os.path.join(_FIXTURES, 'scenes-setup',
                               'middlemarch-ch57-opening.md')) as f:
            content = f.read()
        rows = self._run(
            project_dir, monkeypatch, mock_api, content,
            'SCENE: 1 | chapter-epigraph-scott-childhood-verse | epigraph\n'
            'SCENE: 5 | fred-confronted-by-mrs-garth | Fred calls on Mrs. Garth\n')
        assert [r['id'] for r in rows] == ['fred-confronted-by-mrs-garth']
        assert _opening(project_dir, 'fred-confronted-by-mrs-garth') == '# Chapter LVII'
        with open(os.path.join(project_dir, 'scenes',
                               'fred-confronted-by-mrs-garth.md')) as f:
            text = f.read()
        assert 'They numbered scarce eight summers' in text
        assert 'The evening that Fred Vincy walked' in text
        out = capsys.readouterr().out
        assert 'WARNING' in out and 'epigraph' in out
        assert 'chapter-epigraph-scott-childhood-verse' in out

    def test_short_opening_scene_is_still_split(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch,
            capsys):
        # A short prose scene opening a chapter is not an epigraph.
        rows = self._run(
            project_dir, monkeypatch, mock_api,
            '# Chapter 3\n\nThe carriage came for them at nine, and Elizabeth '
            'went down to it alone.\n\nAt Rosings the next morning, Lady '
            'Catherine received them in the great hall.\n',
            'SCENE: 1 | carriage-comes-for-elizabeth | a\n'
            'SCENE: 5 | lady-catherine-receives-them | b\n')
        assert [r['id'] for r in rows] == ['carriage-comes-for-elizabeth',
                                          'lady-catherine-receives-them']
        assert 'epigraph' not in capsys.readouterr().out


# ============================================================================
# main — renumber mode
# ============================================================================


def _clean_tree(monkeypatch, status=''):
    """`git status --porcelain` output for the renumber's uncommitted check
    (mock_git's _git answers every call with the branch name)."""
    def fake(project_dir, *args, check=True):
        return subprocess.CompletedProcess(args=['git', *args], returncode=0,
                                           stdout=status, stderr='')
    monkeypatch.setattr('storyforge.cmd_scenes_setup._git', fake)


class TestRenumberMode:
    """--renumber: the command cleanup's `seq_needs_renumber` finding names.
    It didn't exist, so the finding's fix was a command that failed."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, project_dir, mock_git):
        # after mock_git, which answers every _git call with the branch name
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        self.logged = []
        monkeypatch.setattr('storyforge.cmd_scenes_setup.log', self.logged.append)
        _clean_tree(monkeypatch)

    def _write(self, project_dir, text):
        path = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(path, 'wb') as f:
            f.write(text.encode('utf-8'))
        return path

    def _run(self, *flags):
        with pytest.raises(SystemExit) as exc:
            main(['--renumber', *flags])
        return exc.value.code

    def _said(self, text):
        return [m for m in self.logged if text in m]

    def _plan(self, project_dir, rows):
        plans = os.path.join(project_dir, 'working', 'plans')
        os.makedirs(plans, exist_ok=True)
        path = os.path.join(plans, 'revision-plan.csv')
        with open(path, 'w') as f:
            f.write('pass|name|purpose|scope|status\n' + ''.join(r + '\n' for r in rows))
        return path

    def test_flag_parses(self):
        assert parse_args(['--renumber']).renumber is True
        assert parse_args([]).renumber is False

    def test_renumbers_in_reading_order_and_commits(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        """No API key and a refusing cost check: neither is consulted, and
        no model is called."""
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        def no_cost_check():
            raise AssertionError('renumber consulted the cost threshold')
        monkeypatch.setattr('storyforge.cmd_scenes_setup.exit_if_bad_threshold',
                            no_cost_check)
        path = self._write(project_dir,
                           'id|seq|title\nc|7|C\na|1|A\nb|2.5|B\nd|2|D\n')
        assert self._run() == 0
        assert open(path).read() == 'id|seq|title\na|1|A\nd|2|D\nb|3|B\nc|4|C\n'
        assert self._said('Renumbered 2 of 4 scenes')
        assert mock_git.calls_for('create_branch') == [('create_branch', 'scenes-setup')]
        commits = mock_git.calls_for('commit_and_push')
        assert len(commits) == 1
        assert commits[0][2] == [os.path.join('reference', 'scenes.csv')]
        assert '1..4' in commits[0][1]
        assert self._said(f'Committed and pushed "{commits[0][1]}"')
        assert mock_api.calls == []

    def test_already_sequential_changes_nothing(
            self, mock_api, mock_git, mock_costs, project_dir):
        """Already 1..N: no write (not even CRLF -> LF or a reorder), no
        branch, no commit."""
        text = 'id|seq|title\r\nb|2|B\r\na|1|A\r\n'
        path = self._write(project_dir, text)
        assert self._run() == 0
        assert open(path, 'rb').read() == text.encode()
        assert self._said('already 1..2')
        assert not mock_git.calls_for('create_branch')
        assert not mock_git.calls_for('commit_and_push')

    def test_twelve_numbered_rows_are_already_sequential(
            self, mock_api, mock_git, mock_costs, project_dir):
        """T-2: a text sort puts 10 before 2 and would 'renumber' 1..12."""
        self._write(project_dir, 'id|seq\n' + ''.join(f's{i}|{i}\n' for i in range(1, 13)))
        assert self._run() == 0
        assert self._said('already 1..12')
        assert not mock_git.calls_for('create_branch')
        assert not mock_git.calls_for('commit_and_push')

    def test_already_sequential_with_uncommitted_changes_exits_1(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        """SF-2: after a failed commit the file is renumbered but not
        committed; a rerun said "Nothing to change." and exited 0."""
        _clean_tree(monkeypatch, status=' M reference/scenes.csv\n')
        self._write(project_dir, 'id|seq\na|1\nb|2\n')
        assert self._run() == 1
        assert self._said('uncommitted changes')
        assert self._said('git add reference/scenes.csv && git commit')
        assert not mock_git.calls_for('commit_and_push')

    @pytest.mark.parametrize('rows', [
        'a|1|A\nb|4|B\nc|4.0|C\n',     # a tie spelled two ways
        'a|1|A\nb|3|B\nc||C\n',        # unnumbered
    ])
    def test_refuses_ties_and_unnumbered(self, mock_api, mock_git, mock_costs,
                                         project_dir, rows):
        text = 'id|seq|title\n' + rows
        path = self._write(project_dir, text)
        assert self._run() == 1
        assert open(path, 'rb').read() == text.encode()
        assert [m for m in self.logged
                if 'not renumbering scenes.csv' in m and 'Decide their order' in m]
        assert not mock_git.calls_for('create_branch')
        assert not mock_git.calls_for('commit_and_push')

    def test_dry_run_writes_nothing(self, mock_api, mock_git, mock_costs, project_dir):
        text = 'id|seq|title\na|1|A\nb|9|B\n'
        path = self._write(project_dir, text)
        assert self._run('--dry-run') == 0
        assert open(path).read() == text
        assert self._said('Would renumber 1 of 2')
        assert not mock_git.calls_for('create_branch')
        assert not mock_git.calls_for('commit_and_push')

    def test_keeps_bom_and_writes_lf(self, mock_api, mock_git, mock_costs, project_dir):
        path = self._write(project_dir, '﻿id|seq|title\r\nb|4|B\r\na|2|A\r\n')
        assert self._run() == 0
        assert open(path, 'rb').read() == '﻿id|seq|title\na|1|A\nb|2|B\n'.encode()

    def test_keeps_permissions_and_symlink(self, mock_api, mock_git, mock_costs,
                                           project_dir):
        """CR-3: the write reset 600 to 644 and replaced a symlink."""
        ref = os.path.join(project_dir, 'reference')
        real = os.path.join(ref, 'scenes-real.csv')
        with open(real, 'w') as f:
            f.write('id|seq\na|1\nb|9\n')
        os.chmod(real, 0o600)
        link = os.path.join(ref, 'scenes.csv')
        os.remove(link)
        os.symlink('scenes-real.csv', link)
        assert self._run() == 0
        assert os.path.islink(link)
        assert open(real).read() == 'id|seq\na|1\nb|2\n'
        assert os.stat(real).st_mode & 0o777 == 0o600

    def test_failed_commit_exits_1(self, mock_api, mock_git, mock_costs, project_dir):
        """T-3: says it's renumbered on disk, with the commit subject and how
        to commit it; the branch was made and the file is renumbered."""
        from storyforge import git
        mock_git.commit_success = False
        path = self._write(project_dir, 'id|seq|title\na|1|A\nb|9|B\n')
        assert self._run() == 1
        assert mock_git.calls_for('create_branch')
        assert open(path).read() == 'id|seq|title\na|1|A\nb|2|B\n'
        said = self._said('renumbered on disk but not committed')
        assert said and 'Scenes setup: renumber seq to 1..2 (1 changed)' in said[0]
        assert 'git add reference/scenes.csv' in said[0]
        assert not self._said('Committed and pushed')

    def test_no_branch_leaves_file_alone(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        """create_branch failing ('') must not leave a renumber on main."""
        monkeypatch.setattr('storyforge.cmd_scenes_setup.create_branch',
                            lambda name, d: '')
        self._plan(project_dir, ['1|p|x|2|pending'])
        text = 'id|seq|title\na|1|A\nb|9|B\nc|2|C\n'
        path = self._write(project_dir, text)
        assert self._run() == 1
        assert open(path).read() == text
        assert not mock_git.calls_for('commit_and_push')
        assert not self._said('WARNING: revision pass')   # C-1: nothing renumbered

    @pytest.mark.parametrize('text', ['id|title\na|A\n', None])
    def test_missing_file_or_seq_column_exits_1(
            self, mock_api, mock_git, mock_costs, project_dir, text):
        if text is None:
            os.remove(os.path.join(project_dir, 'reference', 'scenes.csv'))
        else:
            self._write(project_dir, text)
        assert self._run() == 1
        assert self._said('Nothing was renumbered') or self._said('no seq column')

    def test_unreadable_file_exits_1(self, mock_api, mock_git, mock_costs, project_dir):
        """T-1: invalid UTF-8 is 'cannot read', not a refusal; bytes kept."""
        path = os.path.join(project_dir, 'reference', 'scenes.csv')
        data = b'id|seq\na|1\nb|\xff9\n'
        with open(path, 'wb') as f:
            f.write(data)
        assert self._run() == 1
        assert self._said('cannot read reference/scenes.csv')
        assert open(path, 'rb').read() == data
        assert not mock_git.calls_for('create_branch')

    def test_warns_only_about_passes_it_retargets(
            self, mock_api, mock_git, mock_costs, project_dir):
        """C-1/SF-5, T-4/T-5: a pending pass whose seqs name other scenes
        after the renumber is named; one whose seqs keep their scenes, a
        completed one and an id scope are not."""
        self._plan(project_dir, [
            '1|moves|p|3|pending',          # seq 3: no scene before, b after
            '2|stays|p|1,2|pending',        # a and c keep 1 and 2
            '3|done|p|[3]|completed',
            '4|by-id|p|a;b|pending',
            '5|semicolons|p|2;3|pending',
        ])
        # a=1, b=5, c=2 -> a=1, c=2, b=3
        self._write(project_dir, 'id|seq\na|1\nb|5\nc|2\n')
        assert self._run() == 0
        warned = self._said('WARNING: revision pass')
        assert [w.split('"')[1] for w in warned] == ['moves', 'semicolons']
        assert 'now name' in warned[0]

    def test_warns_about_a_moved_seq(self, mock_api, mock_git, mock_costs, project_dir):
        self._plan(project_dir, ['1|moves|p|[2, 3]|pending', '2|first|p|1|pending'])
        self._write(project_dir, 'id|seq\na|1\nb|3\nc|4\n')   # 3: b -> c
        assert self._run('--dry-run') == 0
        warned = self._said('WARNING: revision pass')
        assert len(warned) == 1 and '"moves"' in warned[0]
        assert 'would name' in warned[0]

    def test_no_warning_when_nothing_needs_renumbering(
            self, mock_api, mock_git, mock_costs, project_dir):
        self._plan(project_dir, ['1|p|x|2|pending'])
        self._write(project_dir, 'id|seq\na|1\nb|2\n')
        assert self._run() == 0
        assert not self._said('WARNING')

    def test_a_stray_quote_hides_no_later_rows(self, mock_api, mock_git, mock_costs,
                                               project_dir):
        """SF-4: a quote-aware reader ran the rest of the file into one field."""
        self._plan(project_dir, ['1|odd "quote|p|full|pending', '2|later|p|3|pending'])
        self._write(project_dir, 'id|seq\na|1\nb|3\nc|4\n')
        assert self._run() == 0
        assert [w for w in self._said('WARNING: revision pass') if '"later"' in w]

    @pytest.mark.parametrize('kind', ['broken-link', 'bad-encoding'])
    def test_an_unreadable_plan_is_named(self, mock_api, mock_git, mock_costs,
                                         project_dir, kind):
        """SF-3/C-4: an unreadable plan returned [] with nothing said."""
        plans = os.path.join(project_dir, 'working', 'plans')
        os.makedirs(plans, exist_ok=True)
        plan = os.path.join(plans, 'revision-plan.csv')
        if kind == 'broken-link':
            os.symlink('revision-plan-3.csv', plan)
        else:
            with open(plan, 'wb') as f:
                f.write(b'pass|name|purpose|scope|status\n1|\xff|p|2|pending\n')
        self._write(project_dir, 'id|seq\na|1\nb|3\n')
        assert self._run() == 0
        assert self._said('were not checked')

    def test_no_plan_says_nothing(self, mock_api, mock_git, mock_costs, project_dir):
        self._write(project_dir, 'id|seq\na|1\nb|3\n')
        assert self._run() == 0
        assert not self._said('WARNING')

    def test_cleanup_finding_names_this_command(self):
        """The finding's command must be one scenes-setup accepts."""
        from storyforge.cmd_cleanup import _classify_issue
        finding = _classify_issue('SEQ_NEEDS_RENUMBER:gaps', {})
        argv = finding['command'].split()
        assert argv[:2] == ['storyforge', 'scenes-setup']
        assert parse_args(argv[2:]).renumber is True


class TestRenumberRealGit:
    """The renumber against real git: CR-1 (a pre-staged file rode along),
    SF-1 (a failed push was reported as pushed), and a failed commit."""

    @pytest.fixture
    def repo(self, tmp_path, monkeypatch):
        remote, work = tmp_path / 'remote.git', tmp_path / 'work'
        run = lambda *a, cwd=work: subprocess.run(a, cwd=cwd, check=True,
                                                  capture_output=True, text=True).stdout
        run('git', 'init', '-q', '--bare', str(remote), cwd=tmp_path)
        run('git', 'init', '-q', '-b', 'main', str(work), cwd=tmp_path)
        for k, v in (('user.email', 't@e.st'), ('user.name', 'T')):
            run('git', 'config', k, v)
        (work / 'reference').mkdir()
        (work / 'reference' / 'scenes.csv').write_text('id|seq\na|1\nb|5\n')
        (work / 'storyforge.yaml').write_text('project:\n  title: T\n')
        run('git', 'add', '.')
        run('git', 'commit', '-qm', 'init')
        run('git', 'remote', 'add', 'origin', str(remote))
        run('git', 'push', '-qu', 'origin', 'main')
        run('git', 'checkout', '-qb', 'storyforge/cleanup-1')
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: str(work))
        self.logged = []
        monkeypatch.setattr('storyforge.cmd_scenes_setup.log', self.logged.append)
        return remote, work, run

    def _run(self):
        with pytest.raises(SystemExit) as exc:
            main(['--renumber'])
        return exc.value.code

    def test_a_pre_staged_file_is_not_committed(self, repo):
        remote, work, run = repo
        (work / 'storyforge.yaml').write_text('project:\n  title: Changed\n')
        run('git', 'add', 'storyforge.yaml')
        assert self._run() == 0
        assert run('git', 'show', '--name-only', '--format=', 'HEAD').split() == [
            'reference/scenes.csv']
        assert run('git', 'diff', '--cached', '--name-only').split() == ['storyforge.yaml']
        assert [m for m in self.logged if m.startswith('Committed and pushed')]

    def test_a_failed_push_is_not_reported_as_pushed(self, repo):
        import shutil
        remote, work, run = repo
        shutil.rmtree(remote)
        assert self._run() == 1
        assert [m for m in self.logged if 'the push failed' in m]
        assert not [m for m in self.logged if m.startswith('Committed and pushed')]
        assert 'renumber seq' in run('git', 'log', '-1', '--format=%s')

    def test_a_failed_commit_names_gits_reason(self, repo):
        remote, work, run = repo
        hook = work / '.git' / 'hooks' / 'pre-commit'
        hook.write_text('#!/bin/sh\necho "hook says no" >&2\nexit 1\n')
        hook.chmod(0o755)
        assert self._run() == 1
        said = [m for m in self.logged if 'not committed' in m]
        assert said and 'hook says no' in said[0]
        assert (work / 'reference' / 'scenes.csv').read_text() == 'id|seq\na|1\nb|2\n'


def test_scenes_alias_renumber_dry_run_needs_no_api_key(project_dir):
    """T-6: `storyforge scenes` is scenes-setup, and its --renumber dry run
    runs with no API key."""
    import sys
    from storyforge.__main__ import COMMANDS
    assert COMMANDS['scenes'] == COMMANDS['scenes-setup']
    with open(os.path.join(project_dir, 'reference', 'scenes.csv'), 'w') as f:
        f.write('id|seq|title\na|1|A\nb|7|B\n')
    plugin = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = {k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'}
    env['PYTHONPATH'] = os.path.join(plugin, 'scripts', 'lib', 'python')
    r = subprocess.run([sys.executable, '-m', 'storyforge', 'scenes', '--renumber',
                        '--dry-run'], cwd=project_dir, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'Would renumber 1 of 2' in r.stdout + r.stderr


class TestVerseManuscript:
    """`source fetch --verse` manuscripts: verse lines end in a hard break
    (`\\`), and Beowulf's chapters are a Prelude and "# Fitt" headings."""

    def _split(self, project_dir, monkeypatch, mock_api, text, reply):
        monkeypatch.setattr('storyforge.cmd_scenes_setup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        mock_api.set_response(reply)
        with open(os.path.join(project_dir, 'manuscript.md'), 'w') as f:
            f.write(text)
        main(['--split-manuscript', '--yes', '--direct'])
        _, rows = _new_rows(project_dir, 'scenes.csv')
        return sorted(rows, key=lambda r: int(r['seq']))

    def test_a_scene_split_mid_stanza_drops_its_last_hard_break(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        # Line 5 (the third verse line) opens the second scene, mid-stanza: the first
        # scene's last line kept its `\`, which pandoc prints
        text = ('# Fitt I\n\nThe first line\\\nthe second line\\\nthe third line\\\n'
                'the fourth line.\n')
        rows = self._split(project_dir, monkeypatch, mock_api, text,
                           'SCENE: 1 | hero-sails-out | a\nSCENE: 5 | hero-lands-ashore | b')
        assert len(rows) == 2
        with open(os.path.join(project_dir, 'scenes', f'{rows[0]["id"]}.md')) as f:
            first = f.read()
        with open(os.path.join(project_dir, 'scenes', f'{rows[1]["id"]}.md')) as f:
            second = f.read()
        assert first.rstrip('\n').endswith('the second line')
        assert 'The first line\\\nthe second line' in first
        assert second == 'the third line\\\nthe fourth line.\n'

    def test_a_prelude_does_not_hide_the_other_headings(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        text = ('# Prelude: Of the Founder\n\nLo, praise.\n\n'
                '# Fitt I\n\nNow Beowulf bode.\n\n# Fitt II\n\nWent he forth.\n')
        rows = self._split(project_dir, monkeypatch, mock_api, text,
                           'SCENE: 1 | something-happens-here | a')
        assert [_opening(project_dir, r['id']) for r in rows] == [
            '# Prelude: Of the Founder', '# Fitt I', '# Fitt II']

    def test_a_prelude_among_chapter_headings_is_unchanged(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        text = ('# Prelude\n\nWho that cares much.\n\n# Chapter I\n\nMiss Brooke.\n\n'
                '# Finale\n\nEvery limit.\n')
        rows = self._split(project_dir, monkeypatch, mock_api, text,
                           'SCENE: 1 | something-happens-here | a')
        assert [_opening(project_dir, r['id']) for r in rows] == [
            '# Prelude', '# Chapter I', '# Finale']
