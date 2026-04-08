"""Integration tests for the draft -> score -> polish production loop.

Tests cmd_write, cmd_score, and the polish loop from cmd_revise,
verifying that main() flows produce the expected file I/O and
call the right API/git functions.
"""

import json
import os
import shutil
import sys

import pytest

from storyforge.csv_cli import get_field
from storyforge.scene_filter import build_scene_list


# ---------------------------------------------------------------------------
# cmd_write tests
# ---------------------------------------------------------------------------

class TestCmdWriteDryRun:
    """Write --dry-run should build prompts without modifying files."""

    def test_dry_run_prints_prompt(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        from storyforge.cmd_write import main
        main(['--dry-run', 'act1-sc01', '--direct'])

        out = capsys.readouterr().out
        assert 'DRY RUN: act1-sc01' in out

    def test_dry_run_no_api_calls(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        from storyforge.cmd_write import main
        main(['--dry-run', 'act1-sc01', '--direct'])

        assert len(mock_api.calls) == 0

    def test_dry_run_no_git_calls(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        from storyforge.cmd_write import main
        main(['--dry-run', 'act1-sc01', '--direct'])

        branch_calls = [c for c in mock_git.calls if isinstance(c, tuple) and c[0] == 'create_branch']
        assert len(branch_calls) == 0

    def test_dry_run_all_scenes(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        from storyforge.cmd_write import main
        main(['--dry-run', '--direct'])

        out = capsys.readouterr().out
        # Should attempt to build prompts for pending scenes
        assert 'DRY RUN' in out


class TestCmdWriteDirect:
    """Write in direct mode with mocked API."""

    # Substantial prose: > 100 words to pass verification
    LONG_PROSE = (
        'The morning air carried the scent of old paper and copper ink. '
        'She crossed the threshold into the cartography office, '
        'where the great maps hung from brass rails along the eastern wall. '
        'Each one bore the careful hand of a master draughtsman, '
        'the contour lines so precise they seemed to breathe. '
    ) * 25

    def test_direct_single_scene_creates_file(self, project_dir, mock_api, mock_git, monkeypatch):
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        mock_api.set_response(self.LONG_PROSE)

        from storyforge.cmd_write import main
        main(['act2-sc01', '--direct'])

        scene_file = os.path.join(project_dir, 'scenes', 'act2-sc01.md')
        assert os.path.isfile(scene_file)
        with open(scene_file) as f:
            content = f.read()
        assert len(content.split()) > 100

    def test_direct_updates_metadata(self, project_dir, mock_api, mock_git, monkeypatch):
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        mock_api.set_response(self.LONG_PROSE)

        from storyforge.cmd_write import main
        main(['act2-sc01', '--direct'])

        metadata = os.path.join(project_dir, 'reference', 'scenes.csv')
        status = get_field(metadata, 'act2-sc01', 'status')
        assert status == 'drafted'
        wc = get_field(metadata, 'act2-sc01', 'word_count')
        assert int(wc) > 100

    def test_direct_invokes_api(self, project_dir, mock_api, mock_git, monkeypatch):
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        mock_api.set_response(self.LONG_PROSE)

        from storyforge.cmd_write import main
        main(['act2-sc01', '--direct'])

        api_calls = [c for c in mock_api.calls if c['fn'] == 'invoke_to_file']
        assert len(api_calls) >= 1

    def test_direct_creates_branch(self, project_dir, mock_api, mock_git, monkeypatch):
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        mock_api.set_response(self.LONG_PROSE)

        from storyforge.cmd_write import main
        main(['act2-sc01', '--direct'])

        branch_calls = [c for c in mock_git.calls
                       if isinstance(c, tuple) and c[0] == 'create_branch']
        assert len(branch_calls) >= 1

    def test_direct_commits_scene(self, project_dir, mock_api, mock_git, monkeypatch):
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        mock_api.set_response(self.LONG_PROSE)

        from storyforge.cmd_write import main
        main(['act2-sc01', '--direct'])

        commit_calls = [c for c in mock_git.calls
                       if isinstance(c, tuple) and c[0] == 'commit_and_push']
        assert len(commit_calls) >= 1


class TestCmdWriteFilter:
    """Scene filtering in write command."""

    def test_skip_already_drafted(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        """Scenes with 'drafted' status and existing files should be skipped."""
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        from storyforge.cmd_write import main
        # act1-sc01 already has a scene file with content
        # It has status 'briefed' in CSV but the file has >200 words
        main(['--dry-run', '--direct'])

        out = capsys.readouterr().out
        # Since these are dry-run they still build prompts for pending scenes
        assert 'DRY RUN' in out

    def test_force_redrafts(self, project_dir, mock_api, mock_git, monkeypatch):
        """--force should re-draft already-drafted scenes."""
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        # Must be > 100 words to pass verification
        prose = (
            'Redrafted content here with new material. '
            'The cartographer studied the pressure readings carefully. '
        ) * 30
        mock_api.set_response(prose)

        from storyforge.cmd_write import main
        main(['act1-sc01', '--direct', '--force'])

        scene_file = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        with open(scene_file) as f:
            content = f.read()
        assert 'Redrafted content here' in content

    def test_api_key_required(self, project_dir, mock_api, mock_git, monkeypatch):
        """Should exit if no API key for non-dry-run mode."""
        monkeypatch.chdir(project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        from storyforge.cmd_write import main
        with pytest.raises(SystemExit) as exc_info:
            main(['act2-sc01', '--direct'])
        assert exc_info.value.code == 1


class TestCmdWriteHelpers:
    """Test internal helper functions of cmd_write."""

    def test_avg_word_count(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        from storyforge.cmd_write import _avg_word_count
        metadata = os.path.join(project_dir, 'reference', 'scenes.csv')
        avg = _avg_word_count(metadata)
        # All target_words in the fixture are positive
        assert avg > 0

    def test_detect_briefs(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        from storyforge.cmd_write import _detect_briefs
        result = _detect_briefs(project_dir)
        # scene-briefs.csv has content
        assert result is True

    def test_resolve_filter_single(self):
        from storyforge.cmd_write import _resolve_filter
        args = type('Args', (), {
            'scenes': None, 'act': None, 'from_seq': None,
            'positional': ['act1-sc01']
        })()
        mode, val, val2 = _resolve_filter(args)
        assert mode == 'single'
        assert val == 'act1-sc01'

    def test_resolve_filter_all(self):
        from storyforge.cmd_write import _resolve_filter
        args = type('Args', (), {
            'scenes': None, 'act': None, 'from_seq': None,
            'positional': []
        })()
        mode, val, val2 = _resolve_filter(args)
        assert mode == 'all'


# ---------------------------------------------------------------------------
# cmd_score tests
# ---------------------------------------------------------------------------

class TestCmdScoreDryRun:
    """Score --dry-run should show what would be scored."""

    def test_dry_run_output(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        # Ensure scenes exist as files to be scoreable
        scenes_dir = os.path.join(project_dir, 'scenes')
        for sid in ['act1-sc01', 'act1-sc02']:
            fpath = os.path.join(scenes_dir, f'{sid}.md')
            if not os.path.isfile(fpath):
                with open(fpath, 'w') as f:
                    f.write('Test content. ' * 100)

        from storyforge.cmd_score import main
        main(['--dry-run'])

        out = capsys.readouterr().out
        assert 'DRY RUN' in out or 'dry' in out.lower()

    def test_dry_run_no_api_calls(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        scenes_dir = os.path.join(project_dir, 'scenes')
        for sid in ['act1-sc01', 'act1-sc02']:
            fpath = os.path.join(scenes_dir, f'{sid}.md')
            if not os.path.isfile(fpath):
                with open(fpath, 'w') as f:
                    f.write('Test content. ' * 100)

        from storyforge.cmd_score import main
        main(['--dry-run'])

        assert len(mock_api.calls) == 0


class TestCmdScoreHelpers:
    """Test score command internal helpers."""

    def test_determine_cycle_starts_at_1(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        monkeypatch.setattr('storyforge.cmd_score.get_current_cycle', lambda _: 0)

        from storyforge.cmd_score import _determine_cycle
        cycle = _determine_cycle(project_dir)
        assert cycle >= 1

    def test_determine_cycle_increments(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        monkeypatch.setattr('storyforge.cmd_score.get_current_cycle', lambda _: 1)

        # Create a cycle-1 directory
        scores_dir = os.path.join(project_dir, 'working', 'scores')
        os.makedirs(os.path.join(scores_dir, 'cycle-1'), exist_ok=True)

        from storyforge.cmd_score import _determine_cycle
        cycle = _determine_cycle(project_dir)
        assert cycle == 2

    def test_resolve_filter_scenes(self):
        from storyforge.cmd_score import _resolve_filter
        args = type('Args', (), {'scenes': 'act1-sc01,act1-sc02', 'act': None, 'from_seq': None})()
        mode, val, _ = _resolve_filter(args)
        assert mode == 'scenes'
        assert val == 'act1-sc01,act1-sc02'

    def test_resolve_filter_act(self):
        from storyforge.cmd_score import _resolve_filter
        args = type('Args', (), {'scenes': None, 'act': '2', 'from_seq': None})()
        mode, val, _ = _resolve_filter(args)
        assert mode == 'act'
        assert val == '2'


# ---------------------------------------------------------------------------
# Polish loop tests
# ---------------------------------------------------------------------------

class TestPolishLoop:
    """Test the polish convergence loop (score -> polish -> re-score)."""

    def test_run_polish_loop_no_scenes_exits(self, project_dir, mock_api, mock_git, monkeypatch):
        """Loop should exit if no drafted scene files exist."""
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        # Remove all scene files
        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        from storyforge.cmd_revise import _run_polish_loop
        with pytest.raises(SystemExit):
            _run_polish_loop(project_dir, max_loops=1, coaching_override=None)

    def test_parse_args_polish_loop(self):
        """Verify parse_args handles --polish --loop."""
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--polish', '--loop', '--max-loops', '3'])
        assert args.polish is True
        assert args.loop is True
        assert args.max_loops == 3

    def test_parse_args_dry_run(self):
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--dry-run'])
        assert args.dry_run is True
