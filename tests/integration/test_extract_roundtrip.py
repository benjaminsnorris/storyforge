"""Integration tests for the extract pipeline (cmd_extract).

Tests dry-run mode, scene sorting, argument parsing, and the
extraction helper modules that parse API responses into CSV fields.
"""

import json
import os
import sys

import pytest

from storyforge.cmd_extract import parse_args, main, _build_sorted_scene_ids


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

class TestExtractParseArgs:
    """Verify parse_args handles flags correctly."""

    def test_default_no_args(self):
        args = parse_args([])
        assert args.phase is None
        assert args.dry_run is False
        assert args.force is False
        assert args.cleanup is False
        assert args.expand is False

    def test_phase_flag(self):
        args = parse_args(['--phase', '1'])
        assert args.phase == 1

    def test_dry_run_flag(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_force_flag(self):
        args = parse_args(['--force'])
        assert args.force is True

    def test_cleanup_flag(self):
        args = parse_args(['--cleanup'])
        assert args.cleanup is True

    def test_cleanup_only_flag(self):
        args = parse_args(['--cleanup-only'])
        assert args.cleanup_only is True

    def test_expand_flag(self):
        args = parse_args(['--expand'])
        assert args.expand is True


# ---------------------------------------------------------------------------
# Scene sorting
# ---------------------------------------------------------------------------

class TestBuildSortedSceneIds:
    """Verify scene ID sorting uses CSV seq when available."""

    def test_sorts_by_csv_seq(self, project_dir):
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        ids = _build_sorted_scene_ids(scenes_dir, ref_dir)
        # act1-sc01 has seq=1, act1-sc02 has seq=2, etc.
        assert ids.index('act1-sc01') < ids.index('act1-sc02')

    def test_includes_all_scene_files(self, project_dir):
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        ids = _build_sorted_scene_ids(scenes_dir, ref_dir)
        # Should include all .md files from scenes/
        scene_files = [f.removesuffix('.md') for f in os.listdir(scenes_dir)
                      if f.endswith('.md')]
        for sid in scene_files:
            assert sid in ids

    def test_no_csv_falls_back_to_alpha(self, project_dir):
        """Without CSV seq data, scenes should sort alphabetically."""
        scenes_dir = os.path.join(project_dir, 'scenes')
        # Use a non-existent ref_dir so no CSV is found
        ref_dir = os.path.join(project_dir, 'nonexistent-ref')
        ids = _build_sorted_scene_ids(scenes_dir, ref_dir)
        assert len(ids) > 0
        assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------

class TestExtractDryRun:
    """Dry-run should print prompts without invoking Claude."""

    def test_dry_run_phase_0(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--phase', '0', '--dry-run'])

        out = capsys.readouterr().out
        assert 'DRY RUN' in out

    def test_dry_run_phase_1(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--phase', '1', '--dry-run'])

        out = capsys.readouterr().out
        assert 'DRY RUN' in out

    def test_dry_run_no_api_calls(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--phase', '0', '--dry-run'])

        assert len(mock_api.calls) == 0

    def test_dry_run_no_commits(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--phase', '0', '--dry-run'])

        commit_calls = [c for c in mock_git.calls
                       if isinstance(c, tuple) and c[0] == 'commit_and_push']
        assert len(commit_calls) == 0


# ---------------------------------------------------------------------------
# API key and prerequisite checks
# ---------------------------------------------------------------------------

class TestExtractPrerequisites:
    """Test prerequisite checks."""

    def test_api_key_required(self, project_dir, mock_api, mock_git, monkeypatch):
        monkeypatch.chdir(project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        with pytest.raises(SystemExit) as exc_info:
            main(['--phase', '0'])
        assert exc_info.value.code == 1

    def test_no_scenes_exits(self, project_dir, mock_api, mock_git, monkeypatch):
        """Should exit if no scene files exist."""
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        # Remove all scene files
        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        with pytest.raises(SystemExit) as exc_info:
            main(['--phase', '0'])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Extract module helpers
# ---------------------------------------------------------------------------

class TestExtractHelpers:
    """Test extraction helper functions."""

    def test_build_characterize_prompt(self, project_dir):
        from storyforge.extract import build_characterize_prompt
        prompt = build_characterize_prompt(project_dir)
        assert prompt is not None
        assert len(prompt) > 100
        # Should include scene content
        assert 'Dorren' in prompt or 'cartograph' in prompt.lower()

    def test_parse_skeleton_response_extracts_fields(self):
        from storyforge.extract import parse_skeleton_response
        response = """TITLE: Test Scene
POV: Alice
LOCATION: Library
TIMELINE_DAY: 1
TIME_OF_DAY: morning
DURATION: 1 hour
TYPE: character
TARGET_WORDS: 2500
PART: 1"""
        result = parse_skeleton_response(response, 'test-sc01')
        assert result.get('id') == 'test-sc01'
        assert result.get('title') == 'Test Scene'
        assert result.get('pov') == 'Alice'
        assert result.get('location') == 'Library'
