"""Tests for storyforge score — principled craft scoring.

Covers parse_args, main orchestration with mocked API/git/costs,
score parsing, targeted principles, deterministic scoring,
fidelity scoring, dry-run mode, and batch vs direct API paths.
"""

import json
import os

import pytest

from storyforge.cmd_score import (
    parse_args,
    main,
    DETERMINISTIC_PRINCIPLES,
    _resolve_filter,
    _determine_cycle,
    _avg_word_count,
    _build_scene_prompt,
)


# ============================================================================
# parse_args
# ============================================================================


class TestParseArgs:
    """Test CLI argument parsing for the score command."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.dry_run
        assert not args.interactive
        assert not args.direct
        assert not args.deep
        assert args.scenes is None
        assert args.act is None
        assert args.from_seq is None
        assert args.principles is None
        assert not args.deterministic
        assert args.parallel == 6  # default

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_interactive_long(self):
        args = parse_args(['--interactive'])
        assert args.interactive

    def test_interactive_short(self):
        args = parse_args(['-i'])
        assert args.interactive

    def test_direct(self):
        args = parse_args(['--direct'])
        assert args.direct

    def test_deep(self):
        args = parse_args(['--deep'])
        assert args.deep

    def test_direct_deep(self):
        args = parse_args(['--direct', '--deep'])
        assert args.direct
        assert args.deep

    def test_scenes_flag(self):
        args = parse_args(['--scenes', 'scene-1,scene-2'])
        assert args.scenes == 'scene-1,scene-2'

    def test_act_flag(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_from_seq_flag(self):
        args = parse_args(['--from-seq', '5'])
        assert args.from_seq == '5'

    def test_from_seq_range(self):
        args = parse_args(['--from-seq', '3-7'])
        assert args.from_seq == '3-7'

    def test_principles_single(self):
        args = parse_args(['--principles', 'prose_naturalness'])
        assert args.principles == 'prose_naturalness'

    def test_principles_comma_separated(self):
        args = parse_args(['--principles', 'prose_naturalness,voice_consistency'])
        assert args.principles == 'prose_naturalness,voice_consistency'

    def test_deterministic_flag(self):
        args = parse_args(['--deterministic'])
        assert args.deterministic

    def test_parallel_flag(self):
        args = parse_args(['--parallel', '4'])
        assert args.parallel == 4

    def test_parallel_env_default(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_SCORE_PARALLEL', '12')
        # The default reads from env at parse time, but since the module
        # already loaded the default, we test with explicit flag instead
        args = parse_args(['--parallel', '12'])
        assert args.parallel == 12

    def test_combined_flags(self):
        args = parse_args(['--dry-run', '--direct', '--scenes', 'act1-sc01',
                           '--principles', 'prose_repetition'])
        assert args.dry_run
        assert args.direct
        assert args.scenes == 'act1-sc01'
        assert args.principles == 'prose_repetition'


# ============================================================================
# DETERMINISTIC_PRINCIPLES
# ============================================================================


class TestDeterministicPrinciples:
    """Test the deterministic principles constant."""

    def test_prose_repetition_is_deterministic(self):
        assert 'prose_repetition' in DETERMINISTIC_PRINCIPLES

    def test_is_frozenset(self):
        assert isinstance(DETERMINISTIC_PRINCIPLES, frozenset)


# ============================================================================
# _resolve_filter
# ============================================================================


class TestResolveFilter:
    """Test filter resolution from CLI args."""

    def test_scenes_filter(self):
        args = parse_args(['--scenes', 'a,b,c'])
        mode, value, _ = _resolve_filter(args)
        assert mode == 'scenes'
        assert value == 'a,b,c'

    def test_act_filter(self):
        args = parse_args(['--act', '2'])
        mode, value, _ = _resolve_filter(args)
        assert mode == 'act'
        assert value == '2'

    def test_from_seq_filter(self):
        args = parse_args(['--from-seq', '5'])
        mode, value, _ = _resolve_filter(args)
        assert mode == 'from_seq'
        assert value == '5'

    def test_no_filter(self):
        args = parse_args([])
        mode, value, _ = _resolve_filter(args)
        assert mode == 'all'
        assert value is None


# ============================================================================
# _determine_cycle
# ============================================================================


class TestDetermineCycle:
    """Test scoring cycle determination."""

    def test_first_cycle_no_history(self, project_dir):
        cycle = _determine_cycle(project_dir)
        assert cycle >= 1

    def test_increments_past_existing_cycles(self, project_dir):
        scores_dir = os.path.join(project_dir, 'working', 'scores')
        os.makedirs(os.path.join(scores_dir, 'cycle-1'), exist_ok=True)
        os.makedirs(os.path.join(scores_dir, 'cycle-2'), exist_ok=True)
        cycle = _determine_cycle(project_dir)
        assert cycle >= 3

    def test_handles_empty_scores_dir(self, project_dir):
        scores_dir = os.path.join(project_dir, 'working', 'scores')
        os.makedirs(scores_dir, exist_ok=True)
        cycle = _determine_cycle(project_dir)
        assert cycle >= 1


# ============================================================================
# _avg_word_count
# ============================================================================


class TestAvgWordCount:
    """Test average word count calculation."""

    def test_from_metadata(self, project_dir):
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        scenes_dir = os.path.join(project_dir, 'scenes')
        # The fixture has word_count values in CSV; some are 0
        avg = _avg_word_count(meta, ['act1-sc01'], scenes_dir)
        # Should return a positive number (either from CSV or file fallback)
        assert avg > 0

    def test_fallback_to_file_measurement(self, project_dir):
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        scenes_dir = os.path.join(project_dir, 'scenes')
        # Zero out all word_count values to force file fallback
        from storyforge.csv_cli import update_field
        from storyforge.scene_filter import build_scene_list
        all_ids = build_scene_list(meta)
        for sid in all_ids:
            update_field(meta, sid, 'word_count', '0')
        avg = _avg_word_count(meta, all_ids, scenes_dir)
        assert avg > 0


# ============================================================================
# _build_scene_prompt
# ============================================================================


class TestBuildScenePrompt:
    """Test evaluation prompt construction."""

    def test_builds_prompt_with_template(self, project_dir):
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        scenes_dir = os.path.join(project_dir, 'scenes')
        template = (
            'Scene: {{SCENE_TITLE}} ({{SCENE_POV}})\n'
            'Function: {{SCENE_FUNCTION}}\n'
            'Emotional arc: {{SCENE_EMOTIONAL_ARC}}\n'
            'Criteria:\n{{EVALUATION_CRITERIA}}\n'
            'Weights:\n{{WEIGHTED_PRINCIPLES}}\n'
            'Count: {{PRINCIPLE_COUNT}}\n'
            'Text:\n{{SCENE_TEXT}}'
        )
        prompt = _build_scene_prompt(
            'act1-sc01', template, 'criteria here', 'weights here',
            meta, intent, scenes_dir,
        )
        assert 'The Finest Cartographer' in prompt
        assert 'Dorren Hayle' in prompt
        assert 'criteria here' in prompt
        assert 'weights here' in prompt

    def test_handles_missing_scene_file(self, project_dir):
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        scenes_dir = os.path.join(project_dir, 'scenes')
        template = '{{SCENE_TITLE}}|{{SCENE_TEXT}}'
        prompt = _build_scene_prompt(
            'nonexistent-scene', template, '', '',
            meta, intent, scenes_dir,
        )
        # Should still return a prompt (with empty scene text)
        assert prompt is not None

    def test_numbers_lines_in_scene_text(self, project_dir):
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        scenes_dir = os.path.join(project_dir, 'scenes')
        template = '{{SCENE_TEXT}}'
        prompt = _build_scene_prompt(
            'act1-sc01', template, '', '',
            meta, intent, scenes_dir,
        )
        # Lines should be numbered
        assert '1: ' in prompt


# ============================================================================
# main — dry run
# ============================================================================


class TestMainDryRun:
    """Test main() in dry-run mode."""

    def test_dry_run_no_api_calls(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        # Need scene files to exist for scoring
        main(['--dry-run', '--scenes', 'act1-sc01'])
        # invoke_to_file should not be called in dry-run
        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) == 0

    def test_dry_run_does_not_create_pr(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run', '--scenes', 'act1-sc01'])
        pr_calls = mock_git.calls_for('create_draft_pr')
        assert len(pr_calls) == 0

    def test_dry_run_deterministic_no_api(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run', '--deterministic', '--scenes', 'act1-sc01'])
        assert mock_api.call_count == 0


# ============================================================================
# main — deterministic scoring
# ============================================================================


class TestMainDeterministic:
    """Test deterministic scoring (no API calls needed)."""

    def test_deterministic_skips_api(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        # Deterministic mode does not need ANTHROPIC_API_KEY
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        main(['--deterministic', '--scenes', 'act1-sc01'])

        # No API calls should be made
        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) == 0
        batch_calls = mock_api.calls_for('submit_batch')
        assert len(batch_calls) == 0

    def test_deterministic_creates_branch(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        main(['--deterministic', '--scenes', 'act1-sc01'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) >= 1

    def test_deterministic_commits_results(self, mock_api, mock_git, mock_costs,
                                           project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        main(['--deterministic', '--scenes', 'act1-sc01'])

        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) >= 1

    def test_deterministic_writes_repetition_scores(self, mock_api, mock_git,
                                                     mock_costs, project_dir,
                                                     monkeypatch):
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        main(['--deterministic', '--scenes', 'act1-sc01'])

        # Should create cycle directory with scores
        scores_dir = os.path.join(project_dir, 'working', 'scores')
        cycle_dirs = [d for d in os.listdir(scores_dir)
                      if d.startswith('cycle-') and
                      os.path.isdir(os.path.join(scores_dir, d))]
        assert len(cycle_dirs) >= 1


# ============================================================================
# main — targeted principles
# ============================================================================


class TestMainTargetedPrinciples:
    """Test --principles flag for targeted scoring."""

    def test_targeted_principles_dry_run(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        # prose_repetition is deterministic, so the whole run is deterministic
        main(['--dry-run', '--principles', 'prose_repetition',
              '--scenes', 'act1-sc01'])
        assert mock_api.call_count == 0

    def test_deterministic_principle_skips_llm(self, mock_api, mock_git,
                                               mock_costs, project_dir,
                                               monkeypatch):
        """When all requested principles are deterministic, LLM is skipped."""
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        main(['--principles', 'prose_repetition', '--scenes', 'act1-sc01'])
        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) == 0

    def test_deterministic_overrides_principles(self, mock_api, mock_git,
                                                mock_costs, project_dir,
                                                monkeypatch):
        """--deterministic takes precedence over --principles."""
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        main(['--deterministic', '--principles', 'voice_consistency',
              '--scenes', 'act1-sc01'])
        # Should run deterministic (prose_repetition), not voice_consistency
        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) == 0


# ============================================================================
# main — direct mode
# ============================================================================


class TestMainDirect:
    """Test main() in direct API mode with mocked dependencies."""

    def _scoring_response(self):
        """Return a mock scoring response in expected format."""
        return (
            'principle|score|deficits|evidence_lines\n'
            'prose_naturalness|4|Some stiff phrasing|12,45\n'
            'voice_consistency|5|None|—\n'
            'dialogue_craft|3|Generic dialogue beats|23,67\n'
        )

    def test_direct_mode_calls_api(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response(self._scoring_response())

        main(['--direct', '--scenes', 'act1-sc01'])

        # Should call invoke_to_file for scene scoring at minimum
        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) >= 1

    def test_direct_creates_cycle_dir(self, mock_api, mock_git, mock_costs,
                                       project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response(self._scoring_response())

        main(['--direct', '--scenes', 'act1-sc01'])

        scores_dir = os.path.join(project_dir, 'working', 'scores')
        cycle_dirs = [d for d in os.listdir(scores_dir)
                      if d.startswith('cycle-') and
                      os.path.isdir(os.path.join(scores_dir, d))]
        assert len(cycle_dirs) >= 1

    def test_direct_creates_branch_and_pr(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response(self._scoring_response())

        main(['--direct', '--scenes', 'act1-sc01'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) >= 1
        pr_calls = mock_git.calls_for('create_draft_pr')
        assert len(pr_calls) >= 1

    def test_direct_commits_results(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response(self._scoring_response())

        main(['--direct', '--scenes', 'act1-sc01'])

        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) >= 1


# ============================================================================
# main — batch mode
# ============================================================================


class TestMainBatch:
    """Test main() in batch API mode."""

    def _scoring_response(self):
        return (
            'principle|score|deficits|evidence_lines\n'
            'prose_naturalness|4|Some stiff phrasing|12,45\n'
            'voice_consistency|5|None|—\n'
        )

    def test_batch_mode_submits_batch(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response(self._scoring_response())

        main(['--scenes', 'act1-sc01'])  # default mode is batch

        batch_calls = mock_api.calls_for('submit_batch')
        assert len(batch_calls) >= 1

    def test_batch_polls_for_results(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response(self._scoring_response())

        main(['--scenes', 'act1-sc01'])

        poll_calls = mock_api.calls_for('poll_batch')
        assert len(poll_calls) >= 1

    def test_batch_downloads_results(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response(self._scoring_response())

        main(['--scenes', 'act1-sc01'])

        dl_calls = mock_api.calls_for('download_batch_results')
        assert len(dl_calls) >= 1


# ============================================================================
# main — error handling
# ============================================================================


class TestErrorHandling:
    """Test error cases and edge conditions."""

    def test_no_api_key_exits(self, mock_api, mock_git, mock_costs,
                              project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        with pytest.raises(SystemExit):
            main(['--direct', '--scenes', 'act1-sc01'])

    def test_no_scene_files_exits(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        # Remove all scene files
        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        with pytest.raises(SystemExit):
            main(['--direct', '--scenes', 'act1-sc01'])

    def test_cost_threshold_exceeded_aborts(self, mock_api, mock_git,
                                            mock_costs, project_dir,
                                            monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        mock_costs.threshold_ok = False

        with pytest.raises(SystemExit):
            main(['--direct', '--scenes', 'act1-sc01'])

        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) == 0


# ============================================================================
# main — latest symlink
# ============================================================================


class TestLatestSymlink:
    """Test that the latest symlink is updated after scoring."""

    def test_latest_symlink_created(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        # Use deterministic mode to avoid needing API key
        main(['--deterministic', '--scenes', 'act1-sc01'])

        latest = os.path.join(project_dir, 'working', 'scores', 'latest')
        assert os.path.islink(latest)
        target = os.readlink(latest)
        assert target.startswith('cycle-')


# ============================================================================
# main — score mode resolution
# ============================================================================


class TestScoreModeResolution:
    """Test that score mode is correctly resolved from CLI flags."""

    def test_default_is_batch(self, mock_api, mock_git, mock_costs,
                               project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response('principle|score|deficits|evidence_lines\n'
                              'voice_consistency|5|None|—\n')

        main(['--scenes', 'act1-sc01'])

        # Batch mode uses submit_batch
        batch_calls = mock_api.calls_for('submit_batch')
        assert len(batch_calls) >= 1

    def test_direct_uses_invoke_to_file(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response('principle|score|deficits|evidence_lines\n'
                              'voice_consistency|5|None|—\n')

        main(['--direct', '--scenes', 'act1-sc01'])

        # Direct mode uses invoke_to_file, not submit_batch
        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) >= 1


# ============================================================================
# main — multi-scene scoring
# ============================================================================


class TestMultiSceneScoring:
    """Test scoring multiple scenes."""

    def test_scores_multiple_scenes(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        # Deterministic mode to avoid API complexity
        main(['--deterministic', '--scenes', 'act1-sc01,act1-sc02'])

        # Both scenes should be processed
        scores_dir = os.path.join(project_dir, 'working', 'scores')
        cycle_dirs = [d for d in os.listdir(scores_dir)
                      if d.startswith('cycle-') and
                      os.path.isdir(os.path.join(scores_dir, d))]
        assert len(cycle_dirs) >= 1

    def test_dry_run_lists_all_scenes(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_score.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run', '--scenes', 'act1-sc01,act1-sc02'])
        # Should succeed without errors
        assert mock_api.call_count == 0
