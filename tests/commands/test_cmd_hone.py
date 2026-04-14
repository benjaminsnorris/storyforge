"""Tests for storyforge.cmd_hone — CSV data quality tool.

Covers: parse_args, main, domain resolution, diagnose mode, loop mode,
findings-driven fixes, coaching level, dry run, scene filtering, error handling.
"""

import json
import os
import sys

import pytest

from storyforge.cmd_hone import (
    parse_args,
    main,
    ALL_DOMAINS,
    PHASE1_REGISTRY,
    PHASE2_REGISTRY,
    PHASE3_REGISTRY,
    ALL_REGISTRY_SUBS,
    _resolve_domains,
    _resolve_scene_filter,
)

from tests.commands.conftest import (
    load_api_response,
    load_api_response_text,
)


# ============================================================================
# parse_args
# ============================================================================

class TestParseArgs:
    """Exhaustive tests for argument parsing."""

    def test_defaults(self):
        args = parse_args([])
        assert args.domain is None
        assert args.phase is None
        assert args.scenes is None
        assert args.act is None
        assert args.threshold == 3.5
        assert args.coaching is None
        assert not args.diagnose
        assert not args.dry_run
        assert not args.loop
        assert args.max_loops == 5
        assert args.findings is None

    def test_domain_flag(self):
        args = parse_args(['--domain', 'briefs'])
        assert args.domain == 'briefs'

    def test_domain_comma_separated(self):
        args = parse_args(['--domain', 'briefs,intent'])
        assert args.domain == 'briefs,intent'

    def test_phase_flag(self):
        args = parse_args(['--phase', '1'])
        assert args.phase == 1

    def test_phase_2(self):
        args = parse_args(['--phase', '2'])
        assert args.phase == 2

    def test_phase_3(self):
        args = parse_args(['--phase', '3'])
        assert args.phase == 3

    def test_scenes_flag(self):
        args = parse_args(['--scenes', 'act1-sc01,act1-sc02'])
        assert args.scenes == 'act1-sc01,act1-sc02'

    def test_act_flag(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_part_alias(self):
        args = parse_args(['--part', '1'])
        assert args.act == '1'

    def test_threshold_flag(self):
        args = parse_args(['--threshold', '4.0'])
        assert args.threshold == 4.0

    def test_coaching_full(self):
        args = parse_args(['--coaching', 'full'])
        assert args.coaching == 'full'

    def test_coaching_coach(self):
        args = parse_args(['--coaching', 'coach'])
        assert args.coaching == 'coach'

    def test_coaching_strict(self):
        args = parse_args(['--coaching', 'strict'])
        assert args.coaching == 'strict'

    def test_coaching_invalid_exits(self):
        with pytest.raises(SystemExit):
            parse_args(['--coaching', 'invalid'])

    def test_diagnose_flag(self):
        args = parse_args(['--diagnose'])
        assert args.diagnose

    def test_dry_run_flag(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_loop_flag(self):
        args = parse_args(['--loop'])
        assert args.loop

    def test_max_loops_flag(self):
        args = parse_args(['--loop', '--max-loops', '10'])
        assert args.max_loops == 10

    def test_findings_flag(self):
        args = parse_args(['--findings', '/tmp/findings.csv'])
        assert args.findings == '/tmp/findings.csv'

    def test_findings_default_none(self):
        args = parse_args([])
        assert args.findings is None

    def test_combined_flags(self):
        args = parse_args([
            '--domain', 'briefs', '--scenes', 'act1-sc01',
            '--coaching', 'coach', '--threshold', '4.5', '--dry-run',
        ])
        assert args.domain == 'briefs'
        assert args.scenes == 'act1-sc01'
        assert args.coaching == 'coach'
        assert args.threshold == 4.5
        assert args.dry_run


# ============================================================================
# Constants
# ============================================================================

class TestConstants:
    """Tests for domain constants."""

    def test_all_domains_includes_expected(self):
        assert 'registries' in ALL_DOMAINS
        assert 'gaps' in ALL_DOMAINS
        assert 'structural' in ALL_DOMAINS
        assert 'briefs' in ALL_DOMAINS
        assert 'intent' in ALL_DOMAINS

    def test_all_domains_count(self):
        assert len(ALL_DOMAINS) == 5

    def test_phase1_registry(self):
        assert 'characters' in PHASE1_REGISTRY
        assert 'locations' in PHASE1_REGISTRY

    def test_phase2_registry(self):
        assert 'values' in PHASE2_REGISTRY
        assert 'mice-threads' in PHASE2_REGISTRY

    def test_phase3_registry(self):
        assert 'knowledge' in PHASE3_REGISTRY
        assert 'outcomes' in PHASE3_REGISTRY
        assert 'physical-states' in PHASE3_REGISTRY

    def test_all_registry_subs_is_complete(self):
        all_phase = set(PHASE1_REGISTRY + PHASE2_REGISTRY + PHASE3_REGISTRY)
        assert all_phase == set(ALL_REGISTRY_SUBS)


# ============================================================================
# _resolve_domains
# ============================================================================

class TestResolveDomains:
    """Tests for domain resolution logic."""

    def test_default_all_domains(self):
        args = parse_args([])
        domains = _resolve_domains(args)
        assert domains == list(ALL_DOMAINS)

    def test_single_domain(self):
        args = parse_args(['--domain', 'briefs'])
        domains = _resolve_domains(args)
        assert domains == ['briefs']

    def test_comma_separated_domains(self):
        args = parse_args(['--domain', 'briefs,intent'])
        domains = _resolve_domains(args)
        assert domains == ['briefs', 'intent']

    def test_phase_1_returns_registry_subs(self):
        args = parse_args(['--phase', '1'])
        domains = _resolve_domains(args)
        assert domains == PHASE1_REGISTRY

    def test_phase_2_returns_registry_subs(self):
        args = parse_args(['--phase', '2'])
        domains = _resolve_domains(args)
        assert domains == PHASE2_REGISTRY

    def test_phase_3_returns_registry_subs(self):
        args = parse_args(['--phase', '3'])
        domains = _resolve_domains(args)
        assert domains == PHASE3_REGISTRY

    def test_invalid_phase_returns_empty(self):
        args = parse_args(['--phase', '99'])
        domains = _resolve_domains(args)
        assert domains == []


# ============================================================================
# _resolve_scene_filter
# ============================================================================

class TestResolveSceneFilter:
    """Tests for scene filter resolution."""

    def test_no_filter_returns_none(self, project_dir):
        args = parse_args([])
        ref_dir = os.path.join(project_dir, 'reference')
        result = _resolve_scene_filter(args, ref_dir)
        assert result is None

    def test_scenes_flag_returns_list(self, project_dir):
        args = parse_args(['--scenes', 'act1-sc01,act1-sc02'])
        ref_dir = os.path.join(project_dir, 'reference')
        result = _resolve_scene_filter(args, ref_dir)
        assert result == ['act1-sc01', 'act1-sc02']

    def test_scenes_strips_whitespace(self, project_dir):
        args = parse_args(['--scenes', 'act1-sc01 , act1-sc02'])
        ref_dir = os.path.join(project_dir, 'reference')
        result = _resolve_scene_filter(args, ref_dir)
        assert result == ['act1-sc01', 'act1-sc02']

    def test_act_filter_returns_matching_scenes(self, project_dir):
        args = parse_args(['--act', '1'])
        ref_dir = os.path.join(project_dir, 'reference')
        result = _resolve_scene_filter(args, ref_dir)
        # Scenes in part 1: act1-sc01, act1-sc02, new-x1
        assert 'act1-sc01' in result
        assert 'act1-sc02' in result
        assert 'new-x1' in result
        # act2 scenes should not be included
        assert 'act2-sc01' not in result

    def test_act_filter_part_2(self, project_dir):
        args = parse_args(['--act', '2'])
        ref_dir = os.path.join(project_dir, 'reference')
        result = _resolve_scene_filter(args, ref_dir)
        assert 'act2-sc01' in result
        assert 'act1-sc01' not in result


# ============================================================================
# Dry run
# ============================================================================

class TestDryRun:
    """Tests for dry run mode — no file modifications, no API calls."""

    def test_dry_run_no_api_calls(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--dry-run'])

        assert mock_api.call_count == 0

    def test_dry_run_no_git_operations(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--dry-run'])

        assert len(mock_git.calls_for('commit_and_push')) == 0
        assert len(mock_git.calls_for('ensure_on_branch')) == 0

    def test_dry_run_briefs_shows_issues(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch, capsys):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--dry-run', '--domain', 'briefs'])

        # Should complete without error; output goes to log
        assert mock_api.call_count == 0


# ============================================================================
# Diagnose mode
# ============================================================================

class TestDiagnoseMode:
    """Tests for diagnose mode — read-only assessment."""

    def test_diagnose_no_api_calls(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch):
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--diagnose'])

        assert mock_api.call_count == 0

    def test_diagnose_no_git_operations(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--diagnose'])

        assert len(mock_git.calls_for('commit_and_push')) == 0
        assert len(mock_git.calls_for('ensure_on_branch')) == 0

    def test_diagnose_outputs_structural_scores(self, mock_api, mock_git, mock_costs,
                                                 project_dir, monkeypatch, capsys):
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--diagnose'])

        captured = capsys.readouterr()
        assert 'Structural Scores' in captured.out

    def test_diagnose_outputs_brief_quality(self, mock_api, mock_git, mock_costs,
                                             project_dir, monkeypatch, capsys):
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--diagnose'])

        captured = capsys.readouterr()
        assert 'Brief Quality' in captured.out

    def test_diagnose_outputs_gaps(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch, capsys):
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--diagnose'])

        captured = capsys.readouterr()
        assert 'Gaps' in captured.out

    def test_diagnose_outputs_summary(self, mock_api, mock_git, mock_costs,
                                       project_dir, monkeypatch, capsys):
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--diagnose'])

        captured = capsys.readouterr()
        assert 'Summary' in captured.out

    def test_diagnose_with_scene_filter(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch, capsys):
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--diagnose', '--scenes', 'act1-sc01'])

        captured = capsys.readouterr()
        assert 'Structural Scores' in captured.out


# ============================================================================
# Loop mode incompatibilities
# ============================================================================

class TestLoopIncompatibilities:
    """Tests for --loop incompatibility checks."""

    def test_loop_and_diagnose_exits(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        with pytest.raises(SystemExit):
            main(['--loop', '--diagnose'])

    def test_loop_and_dry_run_exits(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        with pytest.raises(SystemExit):
            main(['--loop', '--dry-run'])

    def test_loop_and_domain_exits(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        with pytest.raises(SystemExit):
            main(['--loop', '--domain', 'briefs'])


# ============================================================================
# Domain execution
# ============================================================================

class TestDomainExecution:
    """Tests for individual domain execution."""

    def test_structural_domain_is_noop(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        """Structural domain should log a message but make no API calls."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--domain', 'structural', '--dry-run'])

        assert mock_api.call_count == 0

    def test_unknown_domain_warns(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch, capsys):
        """Unknown domain should log warning and continue."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--domain', 'nonexistent', '--dry-run'])

        # Should not have made any API calls for an unknown domain
        assert mock_api.call_count == 0

    def test_gaps_domain_dry_run(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--domain', 'gaps', '--dry-run'])

        assert mock_api.call_count == 0
        assert len(mock_git.calls_for('commit_and_push')) == 0


# ============================================================================
# API key requirement
# ============================================================================

class TestApiKeyCheck:
    """Tests for API key validation."""

    def test_no_api_key_exits_for_active_domains(self, mock_api, mock_git,
                                                   mock_costs, project_dir,
                                                   monkeypatch):
        """Missing API key should exit when running non-dry, non-diagnose."""
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        with pytest.raises(SystemExit):
            main(['--domain', 'briefs'])

    def test_diagnose_does_not_need_api_key(self, mock_api, mock_git,
                                              mock_costs, project_dir,
                                              monkeypatch):
        """Diagnose mode should work without API key."""
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        # Should not exit
        main(['--diagnose'])

    def test_dry_run_does_not_need_api_key(self, mock_api, mock_git,
                                            mock_costs, project_dir,
                                            monkeypatch):
        """Dry run should work without API key."""
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--dry-run'])


# ============================================================================
# Coaching level
# ============================================================================

class TestCoachingLevel:
    """Tests for coaching level adaptation."""

    def test_coaching_flag_sets_env(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        # Pre-set via monkeypatch so it gets cleaned up after the test
        monkeypatch.setenv('STORYFORGE_COACHING', '')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--coaching', 'strict', '--dry-run'])

        assert os.environ.get('STORYFORGE_COACHING') == 'strict'

    def test_strict_coaching_skips_api_key_check(self, mock_api, mock_git,
                                                   mock_costs, project_dir,
                                                   monkeypatch):
        """Strict coaching with no API key should not exit."""
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        # Pre-set via monkeypatch so it gets cleaned up after the test
        monkeypatch.setenv('STORYFORGE_COACHING', '')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)
        monkeypatch.setattr(
            'storyforge.cmd_hone.get_coaching_level', lambda pd: 'strict')

        # strict coaching skips API key check
        main(['--coaching', 'strict', '--dry-run'])


# ============================================================================
# Findings-driven mode
# ============================================================================

class TestFindingsMode:
    """Tests for --findings flag (external findings file)."""

    def test_findings_flag_parsed(self):
        args = parse_args(['--findings', '/tmp/test-findings.csv'])
        assert args.findings == '/tmp/test-findings.csv'

    def test_findings_dry_run(self, mock_api, mock_git, mock_costs,
                               project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        # Create a findings file
        findings_path = os.path.join(project_dir, 'working', 'findings.csv')
        with open(findings_path, 'w') as f:
            f.write('scene_id|target_file|fields|guidance\n')
            f.write('act1-sc01|scene-briefs.csv|goal|Make goal more concrete\n')

        main(['--domain', 'briefs', '--findings', findings_path, '--dry-run'])

        assert mock_api.call_count == 0


# ============================================================================
# Effective findings file (annotation merge)
# ============================================================================

class TestEffectiveFindings:
    """Tests for _effective_findings_file — annotation merging."""

    def test_no_annotations_returns_findings_file(self, project_dir):
        from storyforge.cmd_hone import _effective_findings_file

        findings = '/tmp/some-file.csv'
        result = _effective_findings_file(project_dir, findings, dry_run=False)
        assert result == findings

    def test_no_annotations_no_findings_returns_none(self, project_dir):
        from storyforge.cmd_hone import _effective_findings_file

        result = _effective_findings_file(project_dir, None, dry_run=False)
        assert result is None


# ============================================================================
# Git operations
# ============================================================================

class TestGitOperations:
    """Tests for git branch/commit in hone."""

    def test_ensure_on_branch_called_for_active_run(self, mock_api, mock_git,
                                                      mock_costs, project_dir,
                                                      monkeypatch):
        """Active (non-dry, non-diagnose) runs should ensure we're on a branch."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        # Run a domain that's a no-op (structural) to avoid needing real hone logic
        main(['--domain', 'structural'])

        assert len(mock_git.calls_for('ensure_on_branch')) == 1

    def test_dry_run_skips_branch(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--dry-run'])

        assert len(mock_git.calls_for('ensure_on_branch')) == 0

    def test_diagnose_skips_branch(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch):
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--diagnose'])

        assert len(mock_git.calls_for('ensure_on_branch')) == 0


# ============================================================================
# Intent domain
# ============================================================================

class TestIntentDomain:
    """Tests for intent domain execution."""

    def test_intent_dry_run_no_crash(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--domain', 'intent', '--dry-run'])

        assert mock_api.call_count == 0

    def test_intent_missing_csv_skips(self, mock_api, mock_git, mock_costs,
                                       project_dir, monkeypatch):
        """If scene-intent.csv is missing, intent domain should skip gracefully."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        # Remove intent CSV
        intent_path = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        if os.path.exists(intent_path):
            os.remove(intent_path)

        main(['--domain', 'intent', '--dry-run'])

        assert mock_api.call_count == 0


# ============================================================================
# Briefs domain
# ============================================================================

class TestBriefsDomain:
    """Tests for briefs domain execution."""

    def test_briefs_dry_run_no_modifications(self, mock_api, mock_git, mock_costs,
                                              project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--domain', 'briefs', '--dry-run'])

        assert mock_api.call_count == 0
        assert len(mock_git.calls_for('commit_and_push')) == 0

    def test_briefs_with_scene_filter(self, mock_api, mock_git, mock_costs,
                                       project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_hone.detect_project_root', lambda: project_dir)

        main(['--domain', 'briefs', '--scenes', 'act1-sc01', '--dry-run'])

        assert mock_api.call_count == 0
