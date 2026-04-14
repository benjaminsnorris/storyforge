"""Tests for storyforge review — pipeline review dispatch.

Covers: parse_args (all flags), main orchestration with mocked dependencies,
review type auto-detection from branch name, PR detection, dry-run mode,
error handling for missing branch.
"""

import os
import subprocess
import sys

import pytest

from storyforge.cmd_review import parse_args, main


# ============================================================================
# parse_args
# ============================================================================


class TestParseArgs:
    """Exhaustive tests for argument parsing."""

    def test_defaults(self):
        args = parse_args([])
        assert args.review_type == 'manual'
        assert not args.interactive
        assert not args.dry_run

    def test_type_drafting(self):
        args = parse_args(['--type', 'drafting'])
        assert args.review_type == 'drafting'

    def test_type_evaluation(self):
        args = parse_args(['--type', 'evaluation'])
        assert args.review_type == 'evaluation'

    def test_type_revision(self):
        args = parse_args(['--type', 'revision'])
        assert args.review_type == 'revision'

    def test_type_assembly(self):
        args = parse_args(['--type', 'assembly'])
        assert args.review_type == 'assembly'

    def test_type_manual(self):
        args = parse_args(['--type', 'manual'])
        assert args.review_type == 'manual'

    def test_interactive_long(self):
        args = parse_args(['--interactive'])
        assert args.interactive

    def test_interactive_short(self):
        args = parse_args(['-i'])
        assert args.interactive

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_combined_flags(self):
        args = parse_args(['--dry-run', '--type', 'revision', '-i'])
        assert args.dry_run
        assert args.review_type == 'revision'
        assert args.interactive

    def test_invalid_type_rejected(self):
        with pytest.raises(SystemExit):
            parse_args(['--type', 'bogus'])


# ============================================================================
# main — dry run
# ============================================================================


class TestMainDryRun:
    """Test main() in dry-run mode — no review phase should run."""

    def test_dry_run_no_review(self, mock_api, mock_git, mock_costs,
                               project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 1, stdout='', stderr=''))
        main(['--dry-run'])
        review_calls = mock_git.calls_for('run_review_phase')
        assert len(review_calls) == 0

    def test_dry_run_logs_would_run(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 1, stdout='', stderr=''))
        main(['--dry-run'])
        output = capsys.readouterr().out
        assert 'DRY RUN' in output


# ============================================================================
# main — review dispatch
# ============================================================================


class TestMainReviewDispatch:
    """Test that main() dispatches to run_review_phase correctly."""

    def test_dispatches_with_explicit_type(self, mock_api, mock_git,
                                           mock_costs, project_dir,
                                           monkeypatch):
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 1, stdout='', stderr=''))
        main(['--type', 'drafting'])
        review_calls = mock_git.calls_for('run_review_phase')
        assert len(review_calls) == 1
        assert review_calls[0][1] == 'drafting'

    def test_auto_detects_type_from_branch(self, mock_api, mock_git,
                                           mock_costs, project_dir,
                                           monkeypatch):
        mock_git.branch = 'storyforge/write-20260414'
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 1, stdout='', stderr=''))
        main([])
        review_calls = mock_git.calls_for('run_review_phase')
        assert len(review_calls) == 1
        assert review_calls[0][1] == 'drafting'

    def test_auto_detects_revise_branch(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        mock_git.branch = 'storyforge/revise-20260414'
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 1, stdout='', stderr=''))
        main([])
        review_calls = mock_git.calls_for('run_review_phase')
        assert len(review_calls) == 1
        assert review_calls[0][1] == 'revision'

    def test_auto_detects_evaluate_branch(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        mock_git.branch = 'storyforge/evaluate-20260414'
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 1, stdout='', stderr=''))
        main([])
        review_calls = mock_git.calls_for('run_review_phase')
        assert len(review_calls) == 1
        assert review_calls[0][1] == 'evaluation'

    def test_auto_detects_assemble_branch(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        mock_git.branch = 'storyforge/assemble-20260414'
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 1, stdout='', stderr=''))
        main([])
        review_calls = mock_git.calls_for('run_review_phase')
        assert len(review_calls) == 1
        assert review_calls[0][1] == 'assembly'

    def test_non_storyforge_branch_stays_manual(self, mock_api, mock_git,
                                                mock_costs, project_dir,
                                                monkeypatch):
        mock_git.branch = 'feature/something'
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 1, stdout='', stderr=''))
        main([])
        review_calls = mock_git.calls_for('run_review_phase')
        assert len(review_calls) == 1
        assert review_calls[0][1] == 'manual'


# ============================================================================
# main — PR detection
# ============================================================================


class TestMainPRDetection:
    """Test PR number detection via subprocess (gh pr view)."""

    def test_finds_pr_number(self, mock_api, mock_git, mock_costs,
                             project_dir, monkeypatch, capsys):
        mock_git.has_gh = True
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)

        def fake_subprocess_run(cmd, **kwargs):
            if cmd and cmd[0] == 'gh':
                return subprocess.CompletedProcess(cmd, 0, stdout='99\n', stderr='')
            return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            fake_subprocess_run)
        main(['--type', 'drafting'])
        output = capsys.readouterr().out
        assert '#99' in output

    def test_no_pr_found(self, mock_api, mock_git, mock_costs,
                         project_dir, monkeypatch, capsys):
        mock_git.has_gh = True
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 1, stdout='', stderr=''))
        main(['--dry-run'])
        output = capsys.readouterr().out
        assert 'No PR found' in output

    def test_no_gh_cli(self, mock_api, mock_git, mock_costs, project_dir,
                       monkeypatch, capsys):
        mock_git.has_gh = False
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 1, stdout='', stderr=''))
        main(['--dry-run'])
        # Should not crash and should not show PR number
        output = capsys.readouterr().out
        assert '#' not in output or 'PR' not in output.split('#')[0]


# ============================================================================
# main — error handling
# ============================================================================


class TestMainErrors:
    """Test error handling in main()."""

    def test_no_branch_exits(self, mock_api, mock_git, mock_costs,
                             project_dir, monkeypatch):
        mock_git.branch = ''
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 1, stdout='', stderr=''))
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_interactive_creates_flag_file(self, mock_api, mock_git, mock_costs,
                                           project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_review.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_review.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 1, stdout='', stderr=''))
        main(['-i', '--type', 'manual'])
        interactive_file = os.path.join(project_dir, 'working', '.interactive')
        assert os.path.isfile(interactive_file)
