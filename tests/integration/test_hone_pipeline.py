"""Integration tests for the hone pipeline (cmd_hone).

Tests diagnose mode, dry-run mode, domain resolution, brief issue
counting, and gap detection using real fixture data.
"""

import os
import sys

import pytest

from storyforge.cmd_hone import (
    parse_args, main, _resolve_domains, _resolve_scene_filter,
    _count_brief_issues, ALL_DOMAINS, ALL_REGISTRY_SUBS,
    PHASE1_REGISTRY, PHASE2_REGISTRY, PHASE3_REGISTRY,
)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

class TestHoneParseArgs:
    """Verify parse_args handles flags correctly."""

    def test_default_no_args(self):
        args = parse_args([])
        assert args.domain is None
        assert args.diagnose is False
        assert args.dry_run is False
        assert args.loop is False

    def test_domain_flag(self):
        args = parse_args(['--domain', 'briefs'])
        assert args.domain == 'briefs'

    def test_diagnose_flag(self):
        args = parse_args(['--diagnose'])
        assert args.diagnose is True

    def test_dry_run_flag(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_loop_flag(self):
        args = parse_args(['--loop'])
        assert args.loop is True
        assert args.max_loops == 5

    def test_max_loops(self):
        args = parse_args(['--loop', '--max-loops', '3'])
        assert args.max_loops == 3

    def test_scenes_filter(self):
        args = parse_args(['--scenes', 'act1-sc01,act1-sc02'])
        assert args.scenes == 'act1-sc01,act1-sc02'

    def test_act_filter(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_threshold(self):
        args = parse_args(['--threshold', '4.0'])
        assert args.threshold == 4.0

    def test_coaching(self):
        args = parse_args(['--coaching', 'strict'])
        assert args.coaching == 'strict'

    def test_phase_1(self):
        args = parse_args(['--phase', '1'])
        assert args.phase == 1


# ---------------------------------------------------------------------------
# Domain resolution
# ---------------------------------------------------------------------------

class TestDomainResolution:
    """Verify _resolve_domains returns correct domain lists."""

    def test_default_all_domains(self):
        args = parse_args([])
        domains = _resolve_domains(args)
        assert domains == list(ALL_DOMAINS)

    def test_single_domain(self):
        args = parse_args(['--domain', 'briefs'])
        domains = _resolve_domains(args)
        assert domains == ['briefs']

    def test_comma_separated_domains(self):
        args = parse_args(['--domain', 'briefs,gaps'])
        domains = _resolve_domains(args)
        assert domains == ['briefs', 'gaps']

    def test_phase_1_registries(self):
        args = parse_args(['--phase', '1'])
        domains = _resolve_domains(args)
        assert domains == PHASE1_REGISTRY

    def test_phase_2_registries(self):
        args = parse_args(['--phase', '2'])
        domains = _resolve_domains(args)
        assert domains == PHASE2_REGISTRY

    def test_phase_3_registries(self):
        args = parse_args(['--phase', '3'])
        domains = _resolve_domains(args)
        assert domains == PHASE3_REGISTRY


class TestSceneFilter:
    """Verify _resolve_scene_filter returns correct scene lists."""

    def test_no_filter_returns_none(self, project_dir):
        args = parse_args([])
        ref_dir = os.path.join(project_dir, 'reference')
        result = _resolve_scene_filter(args, ref_dir)
        assert result is None

    def test_scenes_filter(self, project_dir):
        args = parse_args(['--scenes', 'act1-sc01,act1-sc02'])
        ref_dir = os.path.join(project_dir, 'reference')
        result = _resolve_scene_filter(args, ref_dir)
        assert result == ['act1-sc01', 'act1-sc02']

    def test_act_filter(self, project_dir):
        args = parse_args(['--act', '1'])
        ref_dir = os.path.join(project_dir, 'reference')
        result = _resolve_scene_filter(args, ref_dir)
        # Part 1 scenes from fixture
        assert 'act1-sc01' in result
        assert 'act1-sc02' in result


# ---------------------------------------------------------------------------
# Brief issue counting
# ---------------------------------------------------------------------------

class TestBriefIssueCounting:
    """Test _count_brief_issues against fixture data."""

    def test_counts_structure(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')
        counts = _count_brief_issues(ref_dir, None)
        assert 'total' in counts
        assert 'scenes' in counts
        assert 'abstract' in counts
        assert 'overspecified' in counts
        assert 'verbose' in counts
        assert isinstance(counts['total'], int)

    def test_filtered_counts(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')
        counts = _count_brief_issues(ref_dir, ['act1-sc01'])
        # Should only count issues for act1-sc01
        assert counts['scenes'] <= 1


# ---------------------------------------------------------------------------
# Diagnose mode
# ---------------------------------------------------------------------------

class TestHoneDiagnose:
    """Diagnose mode should read data without modifying files."""

    def test_diagnose_runs(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--diagnose'])

        out = capsys.readouterr().out
        assert 'Diagnose complete' in out or 'read-only' in out

    def test_diagnose_shows_structural_scores(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--diagnose'])

        out = capsys.readouterr().out
        assert 'Structural' in out

    def test_diagnose_no_commits(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--diagnose'])

        commit_calls = [c for c in mock_git.calls
                       if isinstance(c, tuple) and c[0] == 'commit_and_push']
        assert len(commit_calls) == 0

    def test_diagnose_no_api_calls(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--diagnose'])

        assert len(mock_api.calls) == 0

    def test_diagnose_no_branch(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--diagnose'])

        branch_calls = [c for c in mock_git.calls
                       if isinstance(c, tuple) and c[0] in ('create_branch', 'ensure_on_branch')]
        assert len(branch_calls) == 0


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------

class TestHoneDryRun:
    """Dry-run should show what would change without modifying files."""

    def test_dry_run_briefs(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--domain', 'briefs', '--dry-run'])

        # Should not modify files or call API
        assert len(mock_api.calls) == 0

    def test_dry_run_gaps(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--domain', 'gaps', '--dry-run'])

        out = capsys.readouterr().out
        # Should report gap counts
        assert 'gap' in out.lower() or 'Gaps' in out

    def test_dry_run_no_commits(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--domain', 'briefs', '--dry-run'])

        commit_calls = [c for c in mock_git.calls
                       if isinstance(c, tuple) and c[0] == 'commit_and_push']
        assert len(commit_calls) == 0


# ---------------------------------------------------------------------------
# Loop incompatibility checks
# ---------------------------------------------------------------------------

class TestHoneLoopValidation:
    """Verify --loop incompatibilities are caught."""

    def test_loop_and_diagnose_incompatible(self, project_dir, mock_api, mock_git, monkeypatch):
        monkeypatch.chdir(project_dir)

        with pytest.raises(SystemExit):
            main(['--loop', '--diagnose'])

    def test_loop_and_dry_run_incompatible(self, project_dir, mock_api, mock_git, monkeypatch):
        monkeypatch.chdir(project_dir)

        with pytest.raises(SystemExit):
            main(['--loop', '--dry-run'])

    def test_loop_and_domain_incompatible(self, project_dir, mock_api, mock_git, monkeypatch):
        monkeypatch.chdir(project_dir)

        with pytest.raises(SystemExit):
            main(['--loop', '--domain', 'briefs'])
