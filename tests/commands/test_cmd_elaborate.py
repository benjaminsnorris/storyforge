"""Tests for storyforge elaborate -- elaboration stage orchestration.

Covers parse_args, main dispatch, dry-run mode, stage flags (spine/
architecture/map/briefs/gap-fill/mice-fill), coaching level override,
MICE fill, gap-fill, interactive mode, and error handling.
"""

import json
import os
import subprocess

import pytest

from storyforge.cmd_elaborate import (
    parse_args,
    main,
    VALID_STAGES,
    _run_mice_fill,
    _run_gap_fill,
    _run_main_stage,
)


# ============================================================================
# parse_args
# ============================================================================


class TestParseArgs:
    """Test CLI argument parsing for the elaborate command."""

    def test_stage_spine(self):
        args = parse_args(['--stage', 'spine'])
        assert args.stage == 'spine'

    def test_stage_architecture(self):
        args = parse_args(['--stage', 'architecture'])
        assert args.stage == 'architecture'

    def test_stage_map(self):
        args = parse_args(['--stage', 'map'])
        assert args.stage == 'map'

    def test_stage_briefs(self):
        args = parse_args(['--stage', 'briefs'])
        assert args.stage == 'briefs'

    def test_stage_gap_fill(self):
        args = parse_args(['--stage', 'gap-fill'])
        assert args.stage == 'gap-fill'

    def test_stage_mice_fill(self):
        args = parse_args(['--stage', 'mice-fill'])
        assert args.stage == 'mice-fill'

    def test_direct_flag_spine(self):
        args = parse_args(['--spine'])
        assert args.stage == 'spine'

    def test_direct_flag_architecture(self):
        args = parse_args(['--architecture'])
        assert args.stage == 'architecture'

    def test_direct_flag_briefs(self):
        args = parse_args(['--briefs'])
        assert args.stage == 'briefs'

    def test_direct_flag_gap_fill(self):
        args = parse_args(['--gap-fill'])
        assert args.stage == 'gap-fill'

    def test_direct_flag_mice_fill(self):
        args = parse_args(['--mice-fill'])
        assert args.stage == 'mice-fill'

    def test_dry_run(self):
        args = parse_args(['--stage', 'spine', '--dry-run'])
        assert args.dry_run

    def test_interactive_long(self):
        args = parse_args(['--stage', 'spine', '--interactive'])
        assert args.interactive

    def test_interactive_short(self):
        args = parse_args(['--stage', 'spine', '-i'])
        assert args.interactive

    def test_seed_flag(self):
        args = parse_args(['--stage', 'spine', '--seed', 'A cartographer discovers truth'])
        assert args.seed == 'A cartographer discovers truth'

    def test_seed_default_empty(self):
        args = parse_args(['--stage', 'spine'])
        assert args.seed == ''

    def test_coaching_full(self):
        args = parse_args(['--stage', 'spine', '--coaching', 'full'])
        assert args.coaching == 'full'

    def test_coaching_coach(self):
        args = parse_args(['--stage', 'spine', '--coaching', 'coach'])
        assert args.coaching == 'coach'

    def test_coaching_strict(self):
        args = parse_args(['--stage', 'spine', '--coaching', 'strict'])
        assert args.coaching == 'strict'

    def test_coaching_default_none(self):
        args = parse_args(['--stage', 'spine'])
        assert args.coaching is None

    def test_coaching_invalid_rejected(self):
        with pytest.raises(SystemExit):
            parse_args(['--stage', 'spine', '--coaching', 'invalid'])

    def test_no_stage_exits(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_combined_flags(self):
        args = parse_args(['--stage', 'briefs', '--dry-run', '--coaching', 'strict'])
        assert args.stage == 'briefs'
        assert args.dry_run
        assert args.coaching == 'strict'

    def test_stage_flag_overrides_direct_flag(self):
        """--stage takes precedence when both are given."""
        args = parse_args(['--stage', 'map', '--spine'])
        assert args.stage == 'map'


# ============================================================================
# VALID_STAGES constant
# ============================================================================


class TestValidStages:
    """Test the valid stages constant."""

    def test_contains_all_expected(self):
        expected = {'spine', 'architecture', 'map', 'briefs', 'gap-fill', 'mice-fill'}
        assert VALID_STAGES == expected

    def test_is_set(self):
        assert isinstance(VALID_STAGES, set)


# ============================================================================
# main -- dry run
# ============================================================================


class TestMainDryRun:
    """Test main() in dry-run mode for various stages."""

    def test_dry_run_spine_no_api_calls(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        main(['--stage', 'spine', '--dry-run'])
        assert mock_api.call_count == 0

    def test_dry_run_does_not_create_branch(self, mock_api, mock_git, mock_costs,
                                             project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        main(['--stage', 'spine', '--dry-run'])
        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 0

    def test_dry_run_does_not_create_pr(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        main(['--stage', 'architecture', '--dry-run'])
        pr_calls = mock_git.calls_for('create_draft_pr')
        assert len(pr_calls) == 0

    def test_dry_run_briefs_prints_prompt(self, mock_api, mock_git, mock_costs,
                                           project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        main(['--stage', 'briefs', '--dry-run'])
        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out

    def test_dry_run_gap_fill_no_branch(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        main(['--stage', 'gap-fill', '--dry-run'])
        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 0


# ============================================================================
# main -- error handling
# ============================================================================


class TestErrorHandling:
    """Test error cases and edge conditions."""

    def test_no_api_key_exits(self, mock_api, mock_git, mock_costs,
                              project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        with pytest.raises(SystemExit):
            main(['--stage', 'spine'])

    def test_invalid_stage_exits(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        with pytest.raises(SystemExit):
            main(['--stage', 'nonexistent'])

    def test_dry_run_does_not_need_api_key(self, mock_api, mock_git, mock_costs,
                                            project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        # Should NOT raise SystemExit
        main(['--stage', 'spine', '--dry-run'])
        assert mock_api.call_count == 0


# ============================================================================
# main -- coaching level
# ============================================================================


class TestCoachingLevel:
    """Test coaching level override via --coaching flag."""

    def test_coaching_sets_env_var(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        # Pre-set via monkeypatch so it gets cleaned up after the test
        monkeypatch.setenv('STORYFORGE_COACHING', '')
        main(['--stage', 'spine', '--dry-run', '--coaching', 'strict'])
        assert os.environ.get('STORYFORGE_COACHING') == 'strict'

    def test_coaching_not_set_when_not_provided(self, mock_api, mock_git,
                                                 mock_costs, project_dir,
                                                 monkeypatch):
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('STORYFORGE_COACHING', raising=False)
        main(['--stage', 'spine', '--dry-run'])
        # Should not have been set
        assert os.environ.get('STORYFORGE_COACHING') is None


# ============================================================================
# main -- stage dispatch
# ============================================================================


class TestStageDispatch:
    """Test that main correctly dispatches to stage runners."""

    def test_spine_stage_invokes_api(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_elaborate.subprocess.Popen',
                            lambda *a, **kw: type('P', (), {'wait': lambda s: None, 'returncode': 0})())
        mock_api.set_response(
            '```scenes-csv\n'
            'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
            'act1-sc01|1|Test|1|Dorren|Office|1|morning|2 hours|scene|mapped|0|2500\n'
            '```'
        )
        main(['--stage', 'spine'])

        # Should have invoked the API via invoke_to_file
        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) >= 1

    def test_spine_creates_branch_and_pr(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response('No structured output blocks found')

        main(['--stage', 'spine'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) >= 1
        assert branch_calls[0][1] == 'elaborate-spine'

        pr_calls = mock_git.calls_for('create_draft_pr')
        assert len(pr_calls) >= 1

    def test_architecture_creates_correct_branch(self, mock_api, mock_git,
                                                   mock_costs, project_dir,
                                                   monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response('No structured output')

        main(['--stage', 'architecture'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) >= 1
        assert branch_calls[0][1] == 'elaborate-architecture'

    def test_stage_commits_results(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response('No structured output')

        main(['--stage', 'map'])

        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) >= 1

    def test_stage_runs_review_phase(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response('No structured output')

        main(['--stage', 'briefs'])

        review_calls = mock_git.calls_for('run_review_phase')
        assert len(review_calls) >= 1
        assert review_calls[0][1] == 'elaboration'


# ============================================================================
# main -- mice-fill dispatch
# ============================================================================


class TestMiceFill:
    """Test MICE dormancy fill stage."""

    def test_mice_fill_dry_run(self, mock_api, mock_git, mock_costs,
                                project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        # Dry-run should not invoke API
        main(['--stage', 'mice-fill', '--dry-run'])
        assert mock_api.call_count == 0

    def test_mice_fill_no_gaps_returns_early(self, mock_api, mock_git,
                                              mock_costs, project_dir,
                                              monkeypatch):
        """When no dormancy gaps exist, mice-fill returns without API calls."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)

        # Patch detect_mice_dormancy to return empty list
        monkeypatch.setattr('storyforge.hone.detect_mice_dormancy', lambda ref_dir: [])

        main(['--stage', 'mice-fill'])

        assert mock_api.call_count == 0


# ============================================================================
# main -- gap-fill dispatch
# ============================================================================


class TestGapFill:
    """Test gap-fill stage."""

    def test_gap_fill_dry_run(self, mock_api, mock_git, mock_costs,
                               project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        main(['--stage', 'gap-fill', '--dry-run'])
        assert mock_api.call_count == 0
        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 0

    def test_gap_fill_no_gaps_skips_api(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        """When analyze_gaps finds nothing, no batch is submitted."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)

        # Patch analyze_gaps to return no gaps
        monkeypatch.setattr('storyforge.elaborate.analyze_gaps', lambda ref_dir: {
            'total_gaps': 0,
            'groups': {},
            'validation': {'failures': []},
        })
        # Patch validate_structure to pass
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True,
            'failures': [],
            'checks': ['check1'],
        })

        main(['--stage', 'gap-fill'])

        # No batch API calls should have been made
        batch_calls = mock_api.calls_for('submit_batch')
        assert len(batch_calls) == 0


# ============================================================================
# main -- response parsing for main stages
# ============================================================================


class TestResponseParsing:
    """Test that structured output blocks in API response are applied."""

    def test_scenes_csv_block_applied(self, mock_api, mock_git, mock_costs,
                                       project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)

        # Response with a scenes-csv block that parse_stage_response can find
        response_text = (
            '```scenes-csv\n'
            'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
            'test-scene|99|Test Scene|1|Narrator|Library|1|night|1 hour|scene|mapped|0|1000\n'
            '```\n'
        )
        mock_api.set_response(response_text)

        main(['--stage', 'spine'])

        # Check that scenes.csv was updated
        scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(scenes_csv) as f:
            content = f.read()
        assert 'test-scene' in content

    def test_validation_report_written(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response('No structured output')

        main(['--stage', 'spine'])

        validate_dir = os.path.join(project_dir, 'working', 'validation')
        assert os.path.isdir(validate_dir)
        reports = [f for f in os.listdir(validate_dir) if f.startswith('validate-')]
        assert len(reports) >= 1
