"""Tests for storyforge.cmd_assemble — manuscript assembly and book production.

Covers: parse_args, format resolution, dry-run mode, main flow,
chapter map reading, output directory creation, git workflow, and error handling.
"""

import os
import subprocess
import sys

import pytest

from storyforge.cmd_assemble import (
    VALID_FORMATS,
    _resolve_formats,
    _word_count,
    parse_args,
    main,
)


# ============================================================================
# Helpers
# ============================================================================

def _ensure_scene_files(project_dir, scene_ids=None):
    """Ensure scene files exist for testing."""
    if scene_ids is None:
        scene_ids = ['act1-sc01', 'act1-sc02', 'act2-sc01']
    scenes_dir = os.path.join(project_dir, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    for sid in scene_ids:
        path = os.path.join(scenes_dir, f'{sid}.md')
        if not os.path.isfile(path):
            with open(path, 'w') as f:
                f.write(f'Scene prose for {sid}. ' * 50 + '\n')


# ============================================================================
# parse_args
# ============================================================================

class TestParseArgs:
    """Tests for parse_args."""

    def test_defaults(self):
        args = parse_args([])
        assert args.formats == []
        assert not args.all_formats
        assert not args.draft
        assert args.annotate is True
        assert not args.interactive
        assert not args.dry_run
        assert not args.skip_validation
        assert not args.no_pr

    def test_format_epub(self):
        args = parse_args(['--format', 'epub'])
        assert args.formats == ['epub']

    def test_format_multiple(self):
        args = parse_args(['--format', 'epub', '--format', 'pdf'])
        assert args.formats == ['epub', 'pdf']

    def test_all_formats(self):
        args = parse_args(['--all'])
        assert args.all_formats

    def test_draft(self):
        args = parse_args(['--draft'])
        assert args.draft

    def test_no_annotate(self):
        args = parse_args(['--no-annotate'])
        assert args.annotate is False

    def test_interactive(self):
        args = parse_args(['--interactive'])
        assert args.interactive

    def test_interactive_short(self):
        args = parse_args(['-i'])
        assert args.interactive

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_skip_validation(self):
        args = parse_args(['--skip-validation'])
        assert args.skip_validation

    def test_no_pr(self):
        args = parse_args(['--no-pr'])
        assert args.no_pr

    def test_combined_flags(self):
        args = parse_args(['--format', 'epub', '--dry-run', '--skip-validation', '--no-pr'])
        assert args.formats == ['epub']
        assert args.dry_run
        assert args.skip_validation
        assert args.no_pr

    def test_draft_with_no_annotate(self):
        args = parse_args(['--draft', '--no-annotate'])
        assert args.draft
        assert args.annotate is False


# ============================================================================
# _resolve_formats
# ============================================================================

class TestResolveFormats:
    """Tests for _resolve_formats."""

    def test_default_is_markdown(self):
        args = parse_args([])
        result = _resolve_formats(args)
        assert result == ['markdown']

    def test_draft_forces_markdown(self):
        args = parse_args(['--draft'])
        result = _resolve_formats(args)
        assert result == ['markdown']

    def test_all_flag(self):
        args = parse_args(['--all'])
        result = _resolve_formats(args)
        assert result == ['all']

    def test_single_format(self):
        args = parse_args(['--format', 'epub'])
        result = _resolve_formats(args)
        assert result == ['epub']

    def test_multiple_formats(self):
        args = parse_args(['--format', 'epub', '--format', 'html'])
        result = _resolve_formats(args)
        assert result == ['epub', 'html']

    def test_comma_separated_formats(self):
        args = parse_args(['--format', 'epub,html'])
        result = _resolve_formats(args)
        assert result == ['epub', 'html']

    def test_invalid_format_exits(self):
        args = parse_args(['--format', 'docx'])
        with pytest.raises(SystemExit):
            _resolve_formats(args)

    def test_draft_overrides_format(self):
        """Draft flag should override any explicit format specification."""
        args = parse_args(['--draft', '--format', 'epub'])
        result = _resolve_formats(args)
        assert result == ['markdown']

    def test_all_overrides_format(self):
        """All flag takes precedence over explicit formats."""
        args = parse_args(['--all', '--format', 'epub'])
        result = _resolve_formats(args)
        assert result == ['all']


# ============================================================================
# VALID_FORMATS
# ============================================================================

class TestValidFormats:
    """Tests for the VALID_FORMATS constant."""

    def test_contains_expected_formats(self):
        assert 'epub' in VALID_FORMATS
        assert 'pdf' in VALID_FORMATS
        assert 'html' in VALID_FORMATS
        assert 'web' in VALID_FORMATS
        assert 'markdown' in VALID_FORMATS
        assert 'all' in VALID_FORMATS

    def test_no_unexpected_formats(self):
        assert len(VALID_FORMATS) == 6


# ============================================================================
# _word_count
# ============================================================================

class TestWordCount:
    """Tests for _word_count."""

    def test_counts_words(self, tmp_path):
        f = tmp_path / 'test.md'
        f.write_text('one two three four five')
        assert _word_count(str(f)) == 5

    def test_empty_file(self, tmp_path):
        f = tmp_path / 'empty.md'
        f.write_text('')
        assert _word_count(str(f)) == 0

    def test_multiline(self, tmp_path):
        f = tmp_path / 'multi.md'
        f.write_text('line one\nline two\nline three')
        assert _word_count(str(f)) == 6


# ============================================================================
# main() -- dry-run mode
# ============================================================================

class TestMainDryRun:
    """Tests for main() in dry-run mode."""

    def test_dry_run_prints_plan(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_assemble.detect_project_root',
                            lambda: project_dir)
        plugin_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))))
        monkeypatch.setattr('storyforge.cmd_assemble.get_plugin_dir',
                            lambda: plugin_dir)

        _ensure_scene_files(project_dir)

        # Mock _run_assembly_cmd for chapter counting and scene listing
        def mock_assembly_cmd(*args):
            args_str = ' '.join(str(a) for a in args)
            if 'count-chapters' in args_str:
                return '2'
            if 'chapter-scenes' in args_str:
                ch_num = args[1]
                if ch_num == '1':
                    return 'act1-sc01\nact1-sc02'
                elif ch_num == '2':
                    return 'act2-sc01'
                return ''
            if 'read-chapter-field' in args_str:
                ch_num = args[1]
                if ch_num == '1':
                    return 'The Finest Cartographer'
                elif ch_num == '2':
                    return 'Into the Blank'
                return 'Unknown'
            return ''

        monkeypatch.setattr('storyforge.cmd_assemble._run_assembly_cmd',
                            mock_assembly_cmd)

        main(['--dry-run'])

        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out
        assert "Cartographer's Silence" in captured.out
        assert 'Chapters: 2' in captured.out
        assert 'Markdown' in captured.out or 'markdown' in captured.out

        # No API calls, no git commits
        assert mock_api.call_count == 0
        assert mock_git.calls_for('commit_and_push') == []

    def test_dry_run_with_epub_format(self, mock_api, mock_git, mock_costs,
                                       project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_assemble.detect_project_root',
                            lambda: project_dir)
        plugin_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))))
        monkeypatch.setattr('storyforge.cmd_assemble.get_plugin_dir',
                            lambda: plugin_dir)

        _ensure_scene_files(project_dir)

        def mock_assembly_cmd(*args):
            args_str = ' '.join(str(a) for a in args)
            if 'count-chapters' in args_str:
                return '2'
            if 'chapter-scenes' in args_str:
                ch_num = args[1]
                if ch_num == '1':
                    return 'act1-sc01\nact1-sc02'
                return 'act2-sc01'
            if 'read-chapter-field' in args_str:
                return 'Chapter Title'
            return ''

        monkeypatch.setattr('storyforge.cmd_assemble._run_assembly_cmd',
                            mock_assembly_cmd)

        main(['--format', 'epub', '--dry-run'])

        captured = capsys.readouterr()
        assert 'epub3' in captured.out

    def test_dry_run_shows_missing_scenes(self, mock_api, mock_git, mock_costs,
                                           project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_assemble.detect_project_root',
                            lambda: project_dir)
        plugin_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))))
        monkeypatch.setattr('storyforge.cmd_assemble.get_plugin_dir',
                            lambda: plugin_dir)

        # Only create some scene files, leaving one missing
        _ensure_scene_files(project_dir, ['act1-sc01'])

        def mock_assembly_cmd(*args):
            args_str = ' '.join(str(a) for a in args)
            if 'count-chapters' in args_str:
                return '1'
            if 'chapter-scenes' in args_str:
                return 'act1-sc01\nmissing-scene'
            if 'read-chapter-field' in args_str:
                return 'Chapter One'
            return ''

        monkeypatch.setattr('storyforge.cmd_assemble._run_assembly_cmd',
                            mock_assembly_cmd)

        main(['--dry-run'])

        captured = capsys.readouterr()
        assert 'MISSING' in captured.out


# ============================================================================
# main() -- validation errors
# ============================================================================

class TestMainValidation:
    """Tests for main() validation paths."""

    def test_missing_chapter_map_exits(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_assemble.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_assemble.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))

        # Remove chapter map
        chapter_map = os.path.join(project_dir, 'reference', 'chapter-map.csv')
        if os.path.isfile(chapter_map):
            os.remove(chapter_map)

        with pytest.raises(SystemExit):
            main([])

    def test_empty_chapter_map_exits(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_assemble.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_assemble.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))

        def mock_assembly_cmd(*args):
            args_str = ' '.join(str(a) for a in args)
            if 'count-chapters' in args_str:
                return '0'
            return ''

        monkeypatch.setattr('storyforge.cmd_assemble._run_assembly_cmd',
                            mock_assembly_cmd)

        with pytest.raises(SystemExit):
            main([])

    def test_invalid_format_exits(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_assemble.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_assemble.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))

        with pytest.raises(SystemExit):
            main(['--format', 'docx'])


# ============================================================================
# main() -- full assembly flow
# ============================================================================

class TestMainAssembly:
    """Tests for main() full assembly execution."""

    def test_draft_mode(self, mock_api, mock_git, mock_costs, project_dir,
                         monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_assemble.detect_project_root',
                            lambda: project_dir)
        plugin_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))))
        monkeypatch.setattr('storyforge.cmd_assemble.get_plugin_dir',
                            lambda: plugin_dir)

        _ensure_scene_files(project_dir)

        # Track subprocess calls
        calls = []


        def mock_assembly_cmd(*args):
            args_str = ' '.join(str(a) for a in args)
            if 'count-chapters' in args_str:
                return '2'
            if 'chapter-scenes' in args_str:
                ch_num = args[1]
                if ch_num == '1':
                    return 'act1-sc01\nact1-sc02'
                return 'act2-sc01'
            if 'read-chapter-field' in args_str:
                return 'Chapter Title'
            if 'assemble' in args_str and args_str.startswith('assemble'):
                return '5000'
            return ''

        monkeypatch.setattr('storyforge.cmd_assemble._run_assembly_cmd',
                            mock_assembly_cmd)

        def mock_subprocess_run(cmd, **kwargs):
            cmd_str = ' '.join(str(c) for c in cmd)
            calls.append(cmd_str)
            if 'storyforge.assembly' in cmd_str and 'chapter' in cmd_str:
                return subprocess.CompletedProcess(
                    cmd, 0,
                    stdout='Chapter content here with some words in it.',
                    stderr='',
                )
            return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

        monkeypatch.setattr('subprocess.run', mock_subprocess_run)

        main(['--draft', '--no-pr'])

        captured = capsys.readouterr()
        combined = captured.out
        assert 'draft' in combined.lower() or 'Draft' in combined

        # Draft mode should create chapter files
        chapters_dir = os.path.join(project_dir, 'manuscript', 'chapters')
        assert os.path.isdir(chapters_dir)


# ============================================================================
# main() -- git workflow
# ============================================================================

class TestMainGitWorkflow:
    """Tests for git workflow in assembly."""

    def test_creates_branch(self, mock_api, mock_git, mock_costs, project_dir,
                             monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_assemble.detect_project_root',
                            lambda: project_dir)
        plugin_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))))
        monkeypatch.setattr('storyforge.cmd_assemble.get_plugin_dir',
                            lambda: plugin_dir)

        _ensure_scene_files(project_dir)

        def mock_assembly_cmd(*args):
            args_str = ' '.join(str(a) for a in args)
            if 'count-chapters' in args_str:
                return '1'
            if 'chapter-scenes' in args_str:
                return 'act1-sc01'
            if 'read-chapter-field' in args_str:
                return 'Chapter One'
            if 'assemble' in args_str and args_str.startswith('assemble'):
                return '1000'
            return ''

        monkeypatch.setattr('storyforge.cmd_assemble._run_assembly_cmd',
                            mock_assembly_cmd)

        def mock_subprocess_run(cmd, **kwargs):
            cmd_str = ' '.join(str(c) for c in cmd)
            if 'storyforge.assembly' in cmd_str:
                return subprocess.CompletedProcess(
                    cmd, 0,
                    stdout='Assembly content.',
                    stderr='',
                )
            return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

        monkeypatch.setattr('subprocess.run', mock_subprocess_run)

        main(['--draft', '--no-pr'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) >= 1
        assert branch_calls[0][1] == 'assemble'

    def test_no_pr_flag_skips_pr(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_assemble.detect_project_root',
                            lambda: project_dir)
        plugin_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))))
        monkeypatch.setattr('storyforge.cmd_assemble.get_plugin_dir',
                            lambda: plugin_dir)

        _ensure_scene_files(project_dir)

        def mock_assembly_cmd(*args):
            args_str = ' '.join(str(a) for a in args)
            if 'count-chapters' in args_str:
                return '1'
            if 'chapter-scenes' in args_str:
                return 'act1-sc01'
            if 'read-chapter-field' in args_str:
                return 'Chapter One'
            if 'assemble' in args_str and args_str.startswith('assemble'):
                return '1000'
            return ''

        monkeypatch.setattr('storyforge.cmd_assemble._run_assembly_cmd',
                            mock_assembly_cmd)

        def mock_subprocess_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout='Content.', stderr='')

        monkeypatch.setattr('subprocess.run', mock_subprocess_run)

        main(['--draft', '--no-pr'])

        pr_calls = mock_git.calls_for('create_draft_pr')
        assert len(pr_calls) == 0

    def test_dry_run_skips_git(self, mock_api, mock_git, mock_costs,
                                project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_assemble.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_assemble.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))

        _ensure_scene_files(project_dir)

        def mock_assembly_cmd(*args):
            args_str = ' '.join(str(a) for a in args)
            if 'count-chapters' in args_str:
                return '1'
            if 'chapter-scenes' in args_str:
                return 'act1-sc01'
            if 'read-chapter-field' in args_str:
                return 'Chapter One'
            return ''

        monkeypatch.setattr('storyforge.cmd_assemble._run_assembly_cmd',
                            mock_assembly_cmd)

        main(['--dry-run'])

        # Dry run should not create branch or commit
        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 0
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) == 0


# ============================================================================
# main() -- chapter map freshness check
# ============================================================================

class TestChapterMapFreshness:
    """Tests for chapter map freshness warning in main."""

    def test_warns_about_stale_chapter_map(self, mock_api, mock_git, mock_costs,
                                            project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_assemble.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_assemble.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))

        _ensure_scene_files(project_dir)

        def mock_assembly_cmd(*args):
            args_str = ' '.join(str(a) for a in args)
            if 'count-chapters' in args_str:
                return '1'
            if 'chapter-scenes' in args_str:
                return 'act1-sc01'
            if 'read-chapter-field' in args_str:
                return 'Chapter One'
            return ''

        monkeypatch.setattr('storyforge.cmd_assemble._run_assembly_cmd',
                            mock_assembly_cmd)

        # The fixture has scenes not in chapter map (new-x1, act2-sc02, act2-sc03)
        # This should trigger a freshness warning
        main(['--dry-run'])

        captured = capsys.readouterr()
        # The warning is logged, which goes to stdout
        assert 'chapter map' in captured.out.lower() or 'Chapter map' in captured.out


# ============================================================================
# main() -- all-formats dry run
# ============================================================================

class TestMainAllFormats:
    """Tests for --all flag behavior."""

    def test_all_formats_dry_run(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_assemble.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_assemble.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))

        _ensure_scene_files(project_dir)

        def mock_assembly_cmd(*args):
            args_str = ' '.join(str(a) for a in args)
            if 'count-chapters' in args_str:
                return '1'
            if 'chapter-scenes' in args_str:
                return 'act1-sc01'
            if 'read-chapter-field' in args_str:
                return 'Chapter One'
            return ''

        monkeypatch.setattr('storyforge.cmd_assemble._run_assembly_cmd',
                            mock_assembly_cmd)

        main(['--all', '--dry-run'])

        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out
        # All formats should be listed
        assert 'Markdown' in captured.out
        assert 'epub3' in captured.out
        assert 'HTML' in captured.out
        assert 'Web book' in captured.out
        assert 'PDF' in captured.out
