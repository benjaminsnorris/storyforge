"""Integration tests for the elaboration pipeline (cmd_elaborate).

Tests stage dispatch, dry-run mode, and stage validation for
spine/architecture/map/briefs/gap-fill/mice-fill stages.
"""

import os
import sys

import pytest

from storyforge.cmd_elaborate import parse_args, main, VALID_STAGES, _run_main_stage


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

class TestElaborateParseArgs:
    """Verify parse_args handles stage flags correctly."""

    def test_stage_flag(self):
        args = parse_args(['--stage', 'spine'])
        assert args.stage == 'spine'

    def test_direct_stage_flag_briefs(self):
        args = parse_args(['--briefs'])
        assert args.stage == 'briefs'

    def test_direct_stage_flag_gap_fill(self):
        args = parse_args(['--gap-fill'])
        assert args.stage == 'gap-fill'

    def test_direct_stage_flag_mice_fill(self):
        args = parse_args(['--mice-fill'])
        assert args.stage == 'mice-fill'

    def test_missing_stage_errors(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_dry_run_flag(self):
        args = parse_args(['--stage', 'spine', '--dry-run'])
        assert args.dry_run is True

    def test_interactive_flag(self):
        args = parse_args(['--stage', 'map', '-i'])
        assert args.interactive is True

    def test_seed_text(self):
        args = parse_args(['--stage', 'spine', '--seed', 'A cartographer discovers danger'])
        assert args.seed == 'A cartographer discovers danger'

    def test_coaching_flag(self):
        args = parse_args(['--stage', 'spine', '--coaching', 'strict'])
        assert args.coaching == 'strict'


class TestElaborateValidStages:
    """Verify stage name validation."""

    def test_valid_stages_set(self):
        expected = {'spine', 'architecture', 'map', 'briefs', 'gap-fill', 'mice-fill'}
        assert VALID_STAGES == expected

    def test_unknown_stage_exits(self, project_dir, mock_api, mock_git, monkeypatch):
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        with pytest.raises(SystemExit) as exc_info:
            main(['--stage', 'nonexistent'])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------

class TestElaborateDryRun:
    """Dry-run should print prompts without invoking Claude or git."""

    def test_dry_run_spine(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--stage', 'spine', '--dry-run'])

        out = capsys.readouterr().out
        assert 'DRY RUN' in out

    def test_dry_run_no_api_calls(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--stage', 'architecture', '--dry-run'])

        assert len(mock_api.calls) == 0

    def test_dry_run_no_branch_created(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--stage', 'map', '--dry-run'])

        branch_calls = [c for c in mock_git.calls
                       if isinstance(c, tuple) and c[0] == 'create_branch']
        assert len(branch_calls) == 0

    def test_dry_run_briefs(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--stage', 'briefs', '--dry-run'])

        out = capsys.readouterr().out
        assert 'DRY RUN' in out


# ---------------------------------------------------------------------------
# Stage dispatch
# ---------------------------------------------------------------------------

class TestElaborateStageDispatch:
    """Verify main() dispatches to the correct stage handler."""

    def test_api_key_required_for_autonomous(self, project_dir, mock_api, mock_git, monkeypatch):
        """Should exit if no API key for non-dry-run, non-interactive mode."""
        monkeypatch.chdir(project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        with pytest.raises(SystemExit) as exc_info:
            main(['--stage', 'spine'])
        assert exc_info.value.code == 1

    def test_gap_fill_dry_run(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        """gap-fill --dry-run should analyze gaps without modifying files."""
        monkeypatch.chdir(project_dir)

        main(['--stage', 'gap-fill', '--dry-run'])

        out = capsys.readouterr().out
        # Either "No gaps found" or "DRY RUN — would fill"
        assert 'gap' in out.lower() or 'DRY RUN' in out

    def test_mice_fill_dry_run(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        """mice-fill --dry-run should detect dormancy gaps without modifying files."""
        monkeypatch.chdir(project_dir)

        main(['--stage', 'mice-fill', '--dry-run'])

        out = capsys.readouterr().out
        # Either "No MICE dormancy gaps" or dry-run gap report
        assert 'MICE' in out or 'dormancy' in out or 'gap' in out.lower()

    def test_coaching_override(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        """--coaching should set the environment variable."""
        monkeypatch.chdir(project_dir)

        main(['--stage', 'spine', '--dry-run', '--coaching', 'strict'])

        assert os.environ.get('STORYFORGE_COACHING') == 'strict'
