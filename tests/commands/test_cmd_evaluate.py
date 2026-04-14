"""Tests for storyforge.cmd_evaluate — Multi-agent evaluation panel.

Covers: parse_args, main, evaluator dispatch, batch vs direct API,
synthesis, assessment, dry run, scene filtering, cost logging, error handling.
"""

import json
import os
import sys

import pytest

from storyforge.cmd_evaluate import (
    parse_args,
    main,
    CORE_EVALUATORS,
    _resolve_filter,
    _load_custom_evaluators,
    _resolve_voice_guide,
    _build_eval_prompt,
    _build_synthesis_prompt,
)

from tests.commands.conftest import (
    load_api_response,
    load_api_response_text,
    TESTS_DIR,
)

# The plugin root is the repo root — one level above tests/
PLUGIN_DIR = os.path.dirname(TESTS_DIR)


# ============================================================================
# parse_args
# ============================================================================

class TestParseArgs:
    """Exhaustive tests for argument parsing."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.manuscript
        assert args.chapter is None
        assert args.act is None
        assert args.scenes is None
        assert args.scene is None
        assert args.from_seq is None
        assert args.evaluator is None
        assert not args.final
        assert not args.interactive
        assert not args.direct
        assert not args.dry_run

    def test_manuscript_flag(self):
        args = parse_args(['--manuscript'])
        assert args.manuscript

    def test_chapter_flag(self):
        args = parse_args(['--chapter', '5'])
        assert args.chapter == 5

    def test_act_flag(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_part_alias(self):
        args = parse_args(['--part', '3'])
        assert args.act == '3'

    def test_scenes_flag(self):
        args = parse_args(['--scenes', 'act1-sc01,act1-sc02'])
        assert args.scenes == 'act1-sc01,act1-sc02'

    def test_scene_flag(self):
        args = parse_args(['--scene', 'act1-sc01'])
        assert args.scene == 'act1-sc01'

    def test_from_seq_flag(self):
        args = parse_args(['--from-seq', '5'])
        assert args.from_seq == '5'

    def test_evaluator_flag(self):
        args = parse_args(['--evaluator', 'line-editor'])
        assert args.evaluator == 'line-editor'

    def test_final_flag(self):
        args = parse_args(['--final'])
        assert args.final

    def test_interactive_flag(self):
        args = parse_args(['-i'])
        assert args.interactive

    def test_interactive_long_flag(self):
        args = parse_args(['--interactive'])
        assert args.interactive

    def test_direct_flag(self):
        args = parse_args(['--direct'])
        assert args.direct

    def test_dry_run_flag(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_combined_flags(self):
        args = parse_args(['--act', '1', '--evaluator', 'first-reader', '--dry-run'])
        assert args.act == '1'
        assert args.evaluator == 'first-reader'
        assert args.dry_run


# ============================================================================
# _resolve_filter
# ============================================================================

class TestResolveFilter:
    """Tests for filter mode resolution from args."""

    def test_default_returns_all(self):
        args = parse_args([])
        mode, *_ = _resolve_filter(args)
        assert mode == 'all'

    def test_manuscript_mode(self):
        args = parse_args(['--manuscript'])
        mode, *_ = _resolve_filter(args)
        assert mode == 'manuscript'

    def test_chapter_mode(self):
        args = parse_args(['--chapter', '3'])
        mode, value, *_ = _resolve_filter(args)
        assert mode == 'chapter'
        assert value == '3'

    def test_act_mode(self):
        args = parse_args(['--act', '2'])
        mode, value, *_ = _resolve_filter(args)
        assert mode == 'act'
        assert value == '2'

    def test_single_scene_mode(self):
        args = parse_args(['--scene', 'act1-sc01'])
        mode, value, range_start, *_ = _resolve_filter(args)
        assert mode == 'single'
        assert range_start == 'act1-sc01'

    def test_scenes_mode(self):
        args = parse_args(['--scenes', 'act1-sc01,act1-sc02'])
        result = _resolve_filter(args)
        assert result[0] == 'scenes'
        assert result[4] == 'act1-sc01,act1-sc02'

    def test_scenes_range_mode(self):
        args = parse_args(['--scenes', 'act1-sc01..act2-sc01'])
        result = _resolve_filter(args)
        assert result[0] == 'range'
        assert result[2] == 'act1-sc01'
        assert result[3] == 'act2-sc01'

    def test_from_seq_mode(self):
        args = parse_args(['--from-seq', '5'])
        result = _resolve_filter(args)
        assert result[0] == 'from_seq'
        assert result[5] == '5'


# ============================================================================
# _load_custom_evaluators
# ============================================================================

class TestLoadCustomEvaluators:
    """Tests for loading custom evaluators from storyforge.yaml."""

    def test_no_custom_evaluators(self, project_dir):
        result = _load_custom_evaluators(project_dir)
        assert result == []

    def test_missing_yaml(self, tmp_path):
        result = _load_custom_evaluators(str(tmp_path))
        assert result == []

    def test_with_custom_evaluators(self, tmp_path):
        yaml_content = """\
project:
  title: Test
custom_evaluators:
  - name: beta-reader
    persona_file: reference/beta-reader.md
  - name: sensitivity-reader
    persona_file: reference/sensitivity.md
"""
        (tmp_path / 'storyforge.yaml').write_text(yaml_content)
        (tmp_path / 'reference').mkdir(exist_ok=True)
        (tmp_path / 'reference' / 'beta-reader.md').write_text('Beta reader persona')
        (tmp_path / 'reference' / 'sensitivity.md').write_text('Sensitivity persona')

        result = _load_custom_evaluators(str(tmp_path))
        assert len(result) == 2
        assert result[0][0] == 'beta-reader'
        assert result[1][0] == 'sensitivity-reader'


# ============================================================================
# _resolve_voice_guide
# ============================================================================

class TestResolveVoiceGuide:
    """Tests for voice guide resolution."""

    def test_finds_voice_guide(self, project_dir):
        path, content = _resolve_voice_guide(project_dir)
        assert path is not None
        assert 'Voice Guide' in content

    def test_no_voice_guide(self, tmp_path):
        (tmp_path / 'storyforge.yaml').write_text('project:\n  title: Test\n')
        path, content = _resolve_voice_guide(str(tmp_path))
        assert path is None
        assert content == ''


# ============================================================================
# CORE_EVALUATORS
# ============================================================================

class TestCoreEvaluators:
    """Tests for evaluator constants."""

    def test_six_core_evaluators(self):
        assert len(CORE_EVALUATORS) == 6

    def test_expected_evaluators(self):
        expected = {
            'literary-agent', 'developmental-editor', 'line-editor',
            'genre-expert', 'first-reader', 'writing-coach',
        }
        assert set(CORE_EVALUATORS) == expected


# ============================================================================
# Dry run
# ============================================================================

class TestDryRun:
    """Tests for dry run mode."""

    def test_dry_run_no_api_calls(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.detect_project_root', lambda: project_dir)
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.get_plugin_dir',
            lambda: PLUGIN_DIR)

        # Need scene files to exist
        scenes_dir = os.path.join(project_dir, 'scenes')
        for sf in ['act1-sc01.md', 'act1-sc02.md']:
            with open(os.path.join(scenes_dir, sf), 'w') as f:
                f.write('Test scene content here.')

        main(['--dry-run', '--scene', 'act1-sc01'])

        assert mock_api.call_count == 0
        assert len(mock_git.calls_for('create_branch')) == 0

    def test_dry_run_prints_evaluator_prompts(self, mock_api, mock_git, mock_costs,
                                               project_dir, monkeypatch, capsys):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.detect_project_root', lambda: project_dir)
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.get_plugin_dir',
            lambda: PLUGIN_DIR)

        scenes_dir = os.path.join(project_dir, 'scenes')
        with open(os.path.join(scenes_dir, 'act1-sc01.md'), 'w') as f:
            f.write('Test scene content.')

        main(['--dry-run', '--scene', 'act1-sc01'])

        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out
        assert 'synthesis' in captured.out.lower()


# ============================================================================
# Direct mode evaluation
# ============================================================================

class TestDirectMode:
    """Tests for direct API evaluation mode."""

    def _setup_project(self, project_dir, monkeypatch):
        """Common setup for direct mode tests."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.detect_project_root', lambda: project_dir)
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.get_plugin_dir',
            lambda: PLUGIN_DIR)
        # Patch get_api_key to not raise
        monkeypatch.setattr('storyforge.cmd_evaluate.get_api_key', lambda: 'test-key')

        # Write scene content
        scenes_dir = os.path.join(project_dir, 'scenes')
        with open(os.path.join(scenes_dir, 'act1-sc01.md'), 'w') as f:
            f.write('Dorren studied the map. The eastern sector readings were wrong.')

    def test_direct_single_evaluator(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        """Single evaluator in direct mode should make one API call."""
        self._setup_project(project_dir, monkeypatch)

        eval_text = load_api_response_text('evaluation')
        synth_text = load_api_response_text('synthesis')
        mock_api.set_response(eval_text)

        main(['--direct', '--scene', 'act1-sc01', '--evaluator', 'line-editor'])

        # Single evaluator mode: one evaluator call, no synthesis
        invoke_calls = mock_api.calls_for('invoke_to_file')
        assert len(invoke_calls) >= 1

        # Should NOT have created a branch (single evaluator mode)
        assert len(mock_git.calls_for('create_branch')) == 0

    def test_direct_all_evaluators_creates_branch(self, mock_api, mock_git, mock_costs,
                                                    project_dir, monkeypatch):
        """Full evaluation should create a branch and PR."""
        self._setup_project(project_dir, monkeypatch)

        eval_text = load_api_response_text('evaluation')

        # Build a synthesis response with the expected delimiters
        synth_response_text = (
            '--- BEGIN synthesis.md ---\n'
            '## Consensus Findings\nStrong voice.\n'
            '--- END synthesis.md ---\n'
            '--- BEGIN findings.yaml ---\n'
            'metadata:\n  title: Test\nfindings:\n  - id: F001\n'
            '    category: prose\n    severity: minor\n'
            '    summary: "Opening hook"\n    fix_location: craft\n'
            '--- END findings.yaml ---\n'
        )
        mock_api.set_response_fn(
            lambda prompt: synth_response_text if 'reconciling' in prompt.lower()
            else eval_text
        )

        main(['--direct', '--scene', 'act1-sc01'])

        # Should have created a branch
        assert len(mock_git.calls_for('create_branch')) == 1
        # Should have created a draft PR
        assert len(mock_git.calls_for('create_draft_pr')) == 1
        # Should have committed
        assert len(mock_git.calls_for('commit_and_push')) >= 1

    def test_direct_calls_six_evaluators(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        """Default evaluation should invoke all 6 core evaluators."""
        self._setup_project(project_dir, monkeypatch)

        eval_text = load_api_response_text('evaluation')
        synth_response_text = (
            '--- BEGIN synthesis.md ---\n'
            '## Consensus\nGood.\n'
            '--- END synthesis.md ---\n'
            '--- BEGIN findings.yaml ---\n'
            'findings: []\n'
            '--- END findings.yaml ---\n'
        )
        mock_api.set_response_fn(
            lambda prompt: synth_response_text if 'reconciling' in prompt.lower()
            else eval_text
        )

        main(['--direct', '--scene', 'act1-sc01'])

        # Count evaluator invoke_to_file calls (6 evaluators + synthesis + possibly assessment)
        invoke_calls = mock_api.calls_for('invoke_to_file')
        # At least 6 (evaluators) + 1 (synthesis)
        assert len(invoke_calls) >= 7


# ============================================================================
# Batch mode
# ============================================================================

class TestBatchMode:
    """Tests for batch API evaluation mode."""

    def _setup_project(self, project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.detect_project_root', lambda: project_dir)
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.get_plugin_dir',
            lambda: PLUGIN_DIR)
        monkeypatch.setattr('storyforge.cmd_evaluate.get_api_key', lambda: 'test-key')

        scenes_dir = os.path.join(project_dir, 'scenes')
        with open(os.path.join(scenes_dir, 'act1-sc01.md'), 'w') as f:
            f.write('Dorren studied the map.')

    def test_batch_submits_and_polls(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        """Batch mode should submit_batch, poll_batch, download_batch_results."""
        self._setup_project(project_dir, monkeypatch)

        # download_batch_results creates report files; simulate that
        eval_dir_holder = {}

        original_download = mock_api._download_batch_results

        def fake_download(results_url, output_dir, log_dir):
            original_download(results_url, output_dir, log_dir)
            # Create evaluator report files and status files so synthesis runs
            for name in CORE_EVALUATORS:
                report_path = os.path.join(output_dir, f'{name}.md')
                status_path = os.path.join(output_dir, f'.status-{name}')
                txt_path = os.path.join(log_dir, f'{name}.txt')
                with open(report_path, 'w') as f:
                    f.write(f'## {name} Report\nGood work.')
                with open(status_path, 'w') as f:
                    f.write('ok')
                with open(txt_path, 'w') as f:
                    f.write(f'## {name} Report\nGood work.')
            return list(CORE_EVALUATORS)

        monkeypatch.setattr('storyforge.api.download_batch_results', fake_download)
        monkeypatch.setattr('storyforge.cmd_evaluate.download_batch_results', fake_download)

        synth_response_text = (
            '--- BEGIN synthesis.md ---\n'
            '## Consensus\nGood.\n'
            '--- END synthesis.md ---\n'
            '--- BEGIN findings.yaml ---\n'
            'findings: []\n'
            '--- END findings.yaml ---\n'
        )
        mock_api.set_response(synth_response_text)

        main(['--scene', 'act1-sc01'])

        assert len(mock_api.calls_for('submit_batch')) == 1
        assert len(mock_api.calls_for('poll_batch')) == 1


# ============================================================================
# Synthesis prompt
# ============================================================================

class TestSynthesisPrompt:
    """Tests for synthesis prompt construction."""

    def test_synthesis_includes_evaluator_names(self, project_dir):
        eval_dir = os.path.join(project_dir, 'working', 'evaluations', 'eval-test')
        os.makedirs(eval_dir, exist_ok=True)

        for name in ['line-editor', 'first-reader']:
            with open(os.path.join(eval_dir, f'{name}.md'), 'w') as f:
                f.write(f'## {name} Report\nFindings here.')

        prompt = _build_synthesis_prompt(
            project_dir, eval_dir, 'test', 'test scope',
            'Test Book', 'fantasy', 'A test logline', 'scenes',
            ['line-editor', 'first-reader'], False, True,
        )

        assert 'line-editor' in prompt
        assert 'first-reader' in prompt
        assert 'Test Book' in prompt

    def test_synthesis_final_includes_readiness(self, project_dir):
        eval_dir = os.path.join(project_dir, 'working', 'evaluations', 'eval-test')
        os.makedirs(eval_dir, exist_ok=True)

        prompt = _build_synthesis_prompt(
            project_dir, eval_dir, 'test', 'test scope',
            'Test', 'fantasy', '', 'scenes',
            ['line-editor'], True, True,
        )

        assert 'Beta Reader Readiness' in prompt

    def test_synthesis_non_final_no_readiness(self, project_dir):
        eval_dir = os.path.join(project_dir, 'working', 'evaluations', 'eval-test')
        os.makedirs(eval_dir, exist_ok=True)

        prompt = _build_synthesis_prompt(
            project_dir, eval_dir, 'test', 'test scope',
            'Test', 'fantasy', '', 'scenes',
            ['line-editor'], False, True,
        )

        assert 'Beta Reader Readiness' not in prompt

    def test_synthesis_includes_fix_location_schema(self, project_dir):
        eval_dir = os.path.join(project_dir, 'working', 'evaluations', 'eval-test')
        os.makedirs(eval_dir, exist_ok=True)

        prompt = _build_synthesis_prompt(
            project_dir, eval_dir, 'test', 'test scope',
            'Test', 'fantasy', '', 'scenes',
            ['line-editor'], False, True,
        )

        assert 'fix_location' in prompt
        assert 'brief' in prompt
        assert 'craft' in prompt


# ============================================================================
# Eval prompt building
# ============================================================================

class TestBuildEvalPrompt:
    """Tests for evaluator prompt construction."""

    def test_prompt_includes_project_title(self, project_dir):
        plugin_dir = PLUGIN_DIR

        prompt = _build_eval_prompt(
            'line-editor', False, True, project_dir, plugin_dir,
            ['scenes/act1-sc01.md'], 'test scope', 'scenes',
            'Test Title', 'fantasy', 'A test logline',
            'Voice guide content', False, '20260101-000000',
            [],
        )

        assert prompt is not None
        assert 'Test Title' in prompt

    def test_prompt_includes_genre(self, project_dir):
        plugin_dir = PLUGIN_DIR

        prompt = _build_eval_prompt(
            'first-reader', False, True, project_dir, plugin_dir,
            ['scenes/act1-sc01.md'], 'test scope', 'scenes',
            'Test Title', 'fantasy (secondary world)', 'logline',
            '', False, '20260101-000000', [],
        )

        assert prompt is not None
        assert 'fantasy' in prompt

    def test_prompt_api_mode_includes_manuscript_inline(self, project_dir):
        """API mode should inline scene content in prompt."""
        plugin_dir = PLUGIN_DIR

        # Write scene content
        scene_path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        with open(scene_path, 'w') as f:
            f.write('The cartographer studied her instruments.')

        prompt = _build_eval_prompt(
            'first-reader', False, True, project_dir, plugin_dir,
            ['scenes/act1-sc01.md'], 'test scope', 'scenes',
            'Test', 'fantasy', '', '', False, '20260101-000000', [],
        )

        assert 'The cartographer studied her instruments.' in prompt

    def test_prompt_non_api_mode_no_inline(self, project_dir):
        """Non-API mode should reference files but not inline content."""
        plugin_dir = PLUGIN_DIR

        prompt = _build_eval_prompt(
            'first-reader', False, False, project_dir, plugin_dir,
            ['scenes/act1-sc01.md'], 'test scope', 'scenes',
            'Test', 'fantasy', '', '', False, '20260101-000000', [],
        )

        assert prompt is not None
        assert 'Read the scene files' in prompt
        assert 'MANUSCRIPT' not in prompt

    def test_final_eval_adds_context(self, project_dir):
        """--final should add evaluation context block."""
        plugin_dir = PLUGIN_DIR

        prompt = _build_eval_prompt(
            'first-reader', False, True, project_dir, plugin_dir,
            ['scenes/act1-sc01.md'], 'test scope', 'scenes',
            'Test', 'fantasy', '', '', True, '20260101-000000', [],
        )

        assert 'final evaluation' in prompt.lower()
        assert 'beta reader' in prompt.lower()

    def test_unknown_evaluator_returns_none(self, project_dir):
        plugin_dir = PLUGIN_DIR

        prompt = _build_eval_prompt(
            'nonexistent-evaluator', False, True, project_dir, plugin_dir,
            ['scenes/act1-sc01.md'], 'test scope', 'scenes',
            'Test', 'fantasy', '', '', False, '20260101-000000', [],
        )

        assert prompt is None


# ============================================================================
# Scene filtering in main
# ============================================================================

class TestSceneFiltering:
    """Tests for scene filtering through main."""

    def _setup(self, project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.detect_project_root', lambda: project_dir)
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.get_plugin_dir',
            lambda: PLUGIN_DIR)

        scenes_dir = os.path.join(project_dir, 'scenes')
        for sf in ['act1-sc01.md', 'act1-sc02.md', 'act2-sc01.md']:
            with open(os.path.join(scenes_dir, sf), 'w') as f:
                f.write('Test scene content.')

    def test_act_filter_dry_run(self, mock_api, mock_git, mock_costs,
                                 project_dir, monkeypatch, capsys):
        self._setup(project_dir, monkeypatch)
        main(['--dry-run', '--act', '1'])
        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out

    def test_from_seq_filter_dry_run(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch, capsys):
        self._setup(project_dir, monkeypatch)
        main(['--dry-run', '--from-seq', '3'])
        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out


# ============================================================================
# Error handling
# ============================================================================

class TestErrorHandling:
    """Tests for error conditions."""

    def test_no_api_key_exits(self, mock_api, mock_git, mock_costs,
                               project_dir, monkeypatch):
        """Missing API key should exit in batch/direct mode."""
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.detect_project_root', lambda: project_dir)
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.get_plugin_dir',
            lambda: PLUGIN_DIR)
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.get_api_key',
            lambda: (_ for _ in ()).throw(RuntimeError('no key')))

        with pytest.raises(SystemExit):
            main(['--scene', 'act1-sc01'])

    def test_unknown_evaluator_exits(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        """Unknown --evaluator name should exit."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.detect_project_root', lambda: project_dir)
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.get_plugin_dir',
            lambda: PLUGIN_DIR)
        monkeypatch.setattr('storyforge.cmd_evaluate.get_api_key', lambda: 'test-key')

        with pytest.raises(SystemExit):
            main(['--direct', '--scene', 'act1-sc01', '--evaluator', 'nonexistent'])

    def test_no_scene_files_exits(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        """If no scene files exist for the filter, should exit."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.detect_project_root', lambda: project_dir)
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.get_plugin_dir',
            lambda: PLUGIN_DIR)
        monkeypatch.setattr('storyforge.cmd_evaluate.get_api_key', lambda: 'test-key')

        # Remove all scene files
        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        with pytest.raises(SystemExit):
            main(['--direct'])


# ============================================================================
# Cost logging
# ============================================================================

class TestCostTracking:
    """Tests for cost estimation and logging."""

    def test_cost_estimate_called_during_evaluation(self, mock_api, mock_git,
                                                     mock_costs, project_dir,
                                                     monkeypatch):
        """Cost estimation should be called during a real evaluation."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.detect_project_root', lambda: project_dir)
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.get_plugin_dir',
            lambda: PLUGIN_DIR)
        monkeypatch.setattr('storyforge.cmd_evaluate.get_api_key', lambda: 'test-key')

        scenes_dir = os.path.join(project_dir, 'scenes')
        with open(os.path.join(scenes_dir, 'act1-sc01.md'), 'w') as f:
            f.write('Test scene content words here.')

        eval_text = load_api_response_text('evaluation')
        synth_text = (
            '--- BEGIN synthesis.md ---\n'
            '## Consensus\nGood.\n'
            '--- END synthesis.md ---\n'
            '--- BEGIN findings.yaml ---\n'
            'findings: []\n'
            '--- END findings.yaml ---\n'
        )
        mock_api.set_response_fn(
            lambda prompt: synth_text if 'reconciling' in prompt.lower() else eval_text
        )

        main(['--direct', '--scene', 'act1-sc01', '--evaluator', 'line-editor'])

        # estimate_cost should have been called
        assert len(mock_costs.estimates) >= 1

    def test_print_summary_called(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        """print_summary should be called at the end."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.detect_project_root', lambda: project_dir)
        monkeypatch.setattr(
            'storyforge.cmd_evaluate.get_plugin_dir',
            lambda: PLUGIN_DIR)
        monkeypatch.setattr('storyforge.cmd_evaluate.get_api_key', lambda: 'test-key')

        scenes_dir = os.path.join(project_dir, 'scenes')
        with open(os.path.join(scenes_dir, 'act1-sc01.md'), 'w') as f:
            f.write('Test content.')

        mock_api.set_response(load_api_response_text('evaluation'))

        main(['--direct', '--scene', 'act1-sc01', '--evaluator', 'line-editor'])

        summary_calls = [op for op in mock_costs.operations
                        if op.get('fn') == 'print_summary']
        assert len(summary_calls) >= 1
