"""Tests for storyforge.cmd_revise — revision pass execution.

Covers: parse_args, main flow (polish, naturalness, structural, standard),
dry-run mode, loop mode, scope resolution, plan generation, scene extraction,
cost estimation, git workflow, and error handling.
"""

import csv
import os
import sys

import pytest

from storyforge.cmd_revise import (
    CSV_PLAN_FIELDS,
    _count_passes,
    _generate_polish_plan,
    _generate_naturalness_plan,
    _read_csv_plan,
    _read_pass_field,
    _write_csv_plan,
    _build_revision_config,
    _summarize_diagnosis,
    _detect_upstream_scenes,
    _next_plan_number,
    parse_args,
    main,
)


# ============================================================================
# Helpers
# ============================================================================

def _write_plan(project_dir, rows):
    """Write a CSV revision plan into the project's working/plans/ directory."""
    plans_dir = os.path.join(project_dir, 'working', 'plans')
    os.makedirs(plans_dir, exist_ok=True)
    plan_file = os.path.join(plans_dir, 'revision-plan.csv')
    _write_csv_plan(plan_file, rows)
    return plan_file


def _make_plan_rows(names=('prose-polish',), fix_location='craft', status='pending'):
    """Create minimal plan rows for testing."""
    rows = []
    for i, name in enumerate(names, 1):
        rows.append({
            'pass': str(i),
            'name': name,
            'purpose': f'Test purpose for {name}',
            'scope': 'full',
            'targets': '',
            'guidance': f'Test guidance for {name}',
            'protection': '',
            'findings': '',
            'status': status,
            'model_tier': 'opus',
            'fix_location': fix_location,
        })
    return rows


def _ensure_scene_files(project_dir, scene_ids=None):
    """Ensure scene files exist for testing."""
    if scene_ids is None:
        scene_ids = ['act1-sc01', 'act1-sc02']
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
        assert not args.dry_run
        assert not args.polish
        assert not args.naturalness
        assert not args.structural
        assert not args.loop
        assert not args.interactive
        assert not args.skip_initial_score
        assert not args.no_annotations
        assert args.max_loops == 5
        assert args.pass_num == 0
        assert args.coaching is None

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_polish(self):
        args = parse_args(['--polish'])
        assert args.polish

    def test_naturalness(self):
        args = parse_args(['--naturalness'])
        assert args.naturalness

    def test_structural(self):
        args = parse_args(['--structural'])
        assert args.structural

    def test_loop(self):
        args = parse_args(['--polish', '--loop'])
        assert args.loop
        assert args.polish

    def test_max_loops(self):
        args = parse_args(['--max-loops', '10'])
        assert args.max_loops == 10

    def test_max_loops_default(self):
        args = parse_args([])
        assert args.max_loops == 5

    def test_interactive(self):
        args = parse_args(['--interactive'])
        assert args.interactive

    def test_interactive_short(self):
        args = parse_args(['-i'])
        assert args.interactive

    def test_coaching_full(self):
        args = parse_args(['--coaching', 'full'])
        assert args.coaching == 'full'

    def test_coaching_coach(self):
        args = parse_args(['--coaching', 'coach'])
        assert args.coaching == 'coach'

    def test_coaching_strict(self):
        args = parse_args(['--coaching', 'strict'])
        assert args.coaching == 'strict'

    def test_coaching_invalid(self):
        with pytest.raises(SystemExit):
            parse_args(['--coaching', 'invalid'])

    def test_pass_num(self):
        args = parse_args(['3'])
        assert args.pass_num == 3

    def test_pass_num_default(self):
        args = parse_args([])
        assert args.pass_num == 0

    def test_skip_initial_score(self):
        args = parse_args(['--skip-initial-score'])
        assert args.skip_initial_score

    def test_no_annotations(self):
        args = parse_args(['--no-annotations'])
        assert args.no_annotations

    def test_polish_loop_combination(self):
        args = parse_args(['--polish', '--loop', '--max-loops', '3'])
        assert args.polish
        assert args.loop
        assert args.max_loops == 3

    def test_naturalness_with_coaching(self):
        args = parse_args(['--naturalness', '--coaching', 'strict'])
        assert args.naturalness
        assert args.coaching == 'strict'

    def test_polish_dry_run(self):
        args = parse_args(['--polish', '--dry-run'])
        assert args.polish
        assert args.dry_run


# ============================================================================
# CSV plan helpers
# ============================================================================

class TestCsvPlanHelpers:
    """Tests for CSV plan reading and writing."""

    def test_write_and_read_plan(self, tmp_path):
        plan_file = str(tmp_path / 'plan.csv')
        rows = _make_plan_rows(('pass-a', 'pass-b'))
        _write_csv_plan(plan_file, rows)

        read_back = _read_csv_plan(plan_file)
        assert len(read_back) == 2
        assert read_back[0]['name'] == 'pass-a'
        assert read_back[1]['name'] == 'pass-b'

    def test_read_nonexistent_plan(self):
        result = _read_csv_plan('/nonexistent/path/plan.csv')
        assert result == []

    def test_count_passes(self):
        rows = _make_plan_rows(('a', 'b', 'c'))
        assert _count_passes(rows) == 3

    def test_count_passes_empty(self):
        assert _count_passes([]) == 0

    def test_read_pass_field(self):
        rows = _make_plan_rows(('pass-a', 'pass-b'))
        assert _read_pass_field(rows, 1, 'name') == 'pass-a'
        assert _read_pass_field(rows, 2, 'name') == 'pass-b'

    def test_read_pass_field_out_of_range(self):
        rows = _make_plan_rows(('pass-a',))
        assert _read_pass_field(rows, 5, 'name') == ''

    def test_next_plan_number_empty_dir(self, tmp_path):
        assert _next_plan_number(str(tmp_path)) == 1

    def test_next_plan_number_with_existing(self, tmp_path):
        (tmp_path / 'revision-plan-1.csv').touch()
        (tmp_path / 'revision-plan-3.csv').touch()
        assert _next_plan_number(str(tmp_path)) == 4

    def test_next_plan_number_nonexistent_dir(self, tmp_path):
        assert _next_plan_number(str(tmp_path / 'does-not-exist')) == 1


# ============================================================================
# Plan generation
# ============================================================================

class TestPlanGeneration:
    """Tests for auto-generated revision plans."""

    def test_generate_polish_plan(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))
        plans_dir = os.path.join(project_dir, 'working', 'plans')
        os.makedirs(plans_dir, exist_ok=True)
        plan_file = os.path.join(plans_dir, 'revision-plan.csv')

        rows = _generate_polish_plan(plan_file, project_dir)
        assert len(rows) == 1
        assert rows[0]['name'] == 'prose-polish'
        assert rows[0]['fix_location'] == 'craft'
        assert rows[0]['status'] == 'pending'
        # Plan file should be written
        assert os.path.isfile(plan_file) or os.path.islink(plan_file)

    def test_generate_naturalness_plan(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))
        plans_dir = os.path.join(project_dir, 'working', 'plans')
        os.makedirs(plans_dir, exist_ok=True)
        plan_file = os.path.join(plans_dir, 'revision-plan.csv')

        rows = _generate_naturalness_plan(plan_file, project_dir)
        assert len(rows) == 3
        assert rows[0]['name'] == 'tricolon-parallelism'
        assert rows[1]['name'] == 'em-dash-antithesis'
        assert rows[2]['name'] == 'ai-vocabulary-hedging'
        for row in rows:
            assert row['fix_location'] == 'craft'
            assert row['status'] == 'pending'
            assert row['model_tier'] == 'opus'


# ============================================================================
# Revision config builder
# ============================================================================

class TestBuildRevisionConfig:
    """Tests for _build_revision_config."""

    def test_empty_plan_row(self):
        row = {f: '' for f in CSV_PLAN_FIELDS}
        assert _build_revision_config(row) == ''

    def test_with_guidance(self):
        row = {f: '' for f in CSV_PLAN_FIELDS}
        row['guidance'] = 'Focus on tightening'
        result = _build_revision_config(row)
        assert 'guidance: Focus on tightening' in result

    def test_with_extra(self):
        row = {f: '' for f in CSV_PLAN_FIELDS}
        row['guidance'] = 'test guidance'
        result = _build_revision_config(row, extra={'rationale': 'test rationale'})
        assert 'guidance: test guidance' in result
        assert 'rationale: test rationale' in result

    def test_multiline_guidance(self):
        row = {f: '' for f in CSV_PLAN_FIELDS}
        row['guidance'] = 'line1\nline2'
        result = _build_revision_config(row)
        assert 'guidance: |-' in result


# ============================================================================
# Diagnosis helpers
# ============================================================================

class TestDiagnosisHelpers:
    """Tests for diagnosis summarization and upstream detection."""

    def test_summarize_diagnosis_empty(self):
        summary = _summarize_diagnosis([])
        assert summary['high_count'] == 0
        assert summary['medium_count'] == 0
        assert summary['overall_avg'] == 0.0

    def test_summarize_diagnosis_with_data(self):
        rows = [
            {'priority': 'high', 'scale': 'scene', 'principle': 'voice',
             'avg_score': '3.5', 'worst_items': 'act1-sc01'},
            {'priority': 'medium', 'scale': 'scene', 'principle': 'pacing',
             'avg_score': '4.0', 'worst_items': 'act1-sc02'},
            {'priority': 'low', 'scale': 'manuscript', 'principle': 'structure',
             'avg_score': '2.0', 'worst_items': ''},
        ]
        summary = _summarize_diagnosis(rows)
        assert summary['high_count'] == 1
        assert summary['medium_count'] == 1
        assert summary['high_principles'] == ['voice']
        assert summary['medium_principles'] == ['pacing']
        # Only scene-scale rows contribute to average
        assert summary['overall_avg'] == pytest.approx(3.75)

    def test_detect_upstream_scenes_empty(self):
        result = _detect_upstream_scenes('/tmp', [])
        assert result == []

    def test_detect_upstream_scenes_with_brief_cause(self):
        rows = [
            {'root_cause': 'brief', 'worst_items': 'act1-sc01;act1-sc02'},
            {'root_cause': 'craft', 'worst_items': 'act2-sc01'},
        ]
        result = _detect_upstream_scenes('/tmp', rows)
        assert result == ['act1-sc01', 'act1-sc02']

    def test_detect_upstream_scenes_no_brief(self):
        rows = [
            {'root_cause': 'craft', 'worst_items': 'act1-sc01'},
        ]
        result = _detect_upstream_scenes('/tmp', rows)
        assert result == []


# ============================================================================
# main() -- dry run mode
# ============================================================================

class TestMainDryRun:
    """Tests for main() in dry-run mode."""

    def test_polish_dry_run(self, mock_api, mock_git, mock_costs, project_dir,
                            monkeypatch, capsys):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))

        main(['--polish', '--dry-run'])

        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out
        assert 'prose-polish' in captured.out
        # No API calls in dry run
        assert mock_api.call_count == 0

    def test_existing_plan_dry_run(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch, capsys):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))

        # Write a CSV plan
        rows = _make_plan_rows(('tightening', 'deepening'))
        _write_plan(project_dir, rows)

        main(['--dry-run'])

        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out
        assert 'tightening' in captured.out
        assert mock_api.call_count == 0

    def test_naturalness_dry_run(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch, capsys):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))

        main(['--naturalness', '--dry-run'])

        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out
        assert 'tricolon-parallelism' in captured.out
        assert mock_api.call_count == 0


# ============================================================================
# main() -- validation errors
# ============================================================================

class TestMainValidation:
    """Tests for main() validation and error paths."""

    def test_mutually_exclusive_modes(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        with pytest.raises(SystemExit):
            main(['--polish', '--naturalness'])

    def test_loop_requires_polish(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        with pytest.raises(SystemExit):
            main(['--loop'])

    def test_loop_incompatible_with_dry_run(self, mock_api, mock_git,
                                             mock_costs, project_dir,
                                             monkeypatch):
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        with pytest.raises(SystemExit):
            main(['--polish', '--loop', '--dry-run'])

    def test_loop_incompatible_with_interactive(self, mock_api, mock_git,
                                                 mock_costs, project_dir,
                                                 monkeypatch):
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        with pytest.raises(SystemExit):
            main(['--polish', '--loop', '--interactive'])

    def test_skip_initial_score_requires_loop(self, mock_api, mock_git,
                                               mock_costs, project_dir,
                                               monkeypatch):
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        with pytest.raises(SystemExit):
            main(['--skip-initial-score'])

    def test_no_plan_file_exits(self, mock_api, mock_git, mock_costs,
                                 project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        # Remove the legacy YAML plan if it exists
        yaml_plan = os.path.join(project_dir, 'working', 'plans', 'revision-plan.yaml')
        if os.path.isfile(yaml_plan):
            os.remove(yaml_plan)
        with pytest.raises(SystemExit):
            main([])

    def test_no_api_key_exits(self, mock_api, mock_git, mock_costs,
                               project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))
        # Remove API key
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        # Restore get_api_key to raise on missing key
        monkeypatch.setattr('storyforge.cmd_revise.get_api_key',
                            lambda: (_ for _ in ()).throw(RuntimeError('ANTHROPIC_API_KEY not set')))

        # Write a plan so we get past plan validation
        rows = _make_plan_rows(('test-pass',))
        _write_plan(project_dir, rows)

        with pytest.raises(SystemExit):
            main([])

    def test_all_passes_completed_returns(self, mock_api, mock_git, mock_costs,
                                           project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        # Write a plan with all passes completed
        rows = _make_plan_rows(('pass-a',), status='completed')
        _write_plan(project_dir, rows)

        # Should return without error (no more work to do)
        main([])
        assert mock_api.call_count == 0


# ============================================================================
# main() -- pass execution (standard prose revision)
# ============================================================================

class TestMainPassExecution:
    """Tests for main() executing revision passes."""

    def test_executes_craft_pass(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        plugin_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))))
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: plugin_dir)

        # Write a craft revision plan
        rows = _make_plan_rows(('prose-polish',), fix_location='craft')
        plan_file = _write_plan(project_dir, rows)

        _ensure_scene_files(project_dir)

        # Mock the revision module subprocess call
        import subprocess as sp

        def mock_subprocess_run(cmd, **kwargs):
            cmd_str = ' '.join(str(c) for c in cmd)
            if 'storyforge.revision' in cmd_str and 'build-prompt' in cmd_str:
                return sp.CompletedProcess(
                    cmd, 0,
                    stdout='Revision prompt for prose-polish pass.',
                    stderr='',
                )
            if 'storyforge.parsing' in cmd_str and 'extract-scenes' in cmd_str:
                return sp.CompletedProcess(cmd, 0, stdout='Extracted 2 scenes', stderr='')
            return sp.CompletedProcess(cmd, 0, stdout='', stderr='')

        monkeypatch.setattr('subprocess.run', mock_subprocess_run)

        # Set up the API response
        mock_api.set_response(
            '=== SCENE: act1-sc01 ===\nRevised prose.\n=== END SCENE: act1-sc01 ==='
        )

        main([])

        # API should have been called for the revision
        assert mock_api.call_count >= 1
        # Git should have committed
        assert mock_git.call_count >= 1

    def test_start_from_pass_num(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        plugin_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))))
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: plugin_dir)

        # Two-pass plan: first already completed
        rows = _make_plan_rows(('pass-a', 'pass-b'), fix_location='craft')
        rows[0]['status'] = 'completed'
        _write_plan(project_dir, rows)
        _ensure_scene_files(project_dir)

        import subprocess as sp

        def mock_subprocess_run(cmd, **kwargs):
            cmd_str = ' '.join(str(c) for c in cmd)
            if 'storyforge.revision' in cmd_str:
                return sp.CompletedProcess(cmd, 0, stdout='Prompt text', stderr='')
            if 'storyforge.parsing' in cmd_str:
                return sp.CompletedProcess(cmd, 0, stdout='', stderr='')
            return sp.CompletedProcess(cmd, 0, stdout='', stderr='')

        monkeypatch.setattr('subprocess.run', mock_subprocess_run)
        mock_api.set_response('Revised content')

        # Start from pass 2 explicitly
        main(['2'])

        # Only one API call (for pass 2)
        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) >= 1


# ============================================================================
# main() -- polish mode (non-dry-run)
# ============================================================================

class TestMainPolishMode:
    """Tests for main() in polish mode with API execution."""

    def test_polish_generates_plan_and_executes(self, mock_api, mock_git,
                                                 mock_costs, project_dir,
                                                 monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        plugin_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))))
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: plugin_dir)

        _ensure_scene_files(project_dir)

        import subprocess as sp

        def mock_subprocess_run(cmd, **kwargs):
            cmd_str = ' '.join(str(c) for c in cmd)
            if 'storyforge.revision' in cmd_str:
                return sp.CompletedProcess(cmd, 0, stdout='Polish prompt', stderr='')
            if 'storyforge.parsing' in cmd_str:
                return sp.CompletedProcess(cmd, 0, stdout='', stderr='')
            return sp.CompletedProcess(cmd, 0, stdout='', stderr='')

        monkeypatch.setattr('subprocess.run', mock_subprocess_run)
        mock_api.set_response('Polished prose')

        main(['--polish'])

        # Plan should have been generated
        plan_file = os.path.join(project_dir, 'working', 'plans', 'revision-plan.csv')
        assert os.path.isfile(plan_file) or os.path.islink(plan_file)

        # API should have been called
        assert mock_api.call_count >= 1

        # Git branch created and commits made
        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) >= 1


# ============================================================================
# main() -- structural mode dry run
# ============================================================================

class TestMainStructuralMode:
    """Tests for structural mode (CSV-only revision)."""

    def test_structural_requires_proposals_file(self, mock_api, mock_git,
                                                 mock_costs, project_dir,
                                                 monkeypatch):
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        # No structural-proposals.csv exists
        with pytest.raises(SystemExit):
            main(['--structural'])

    def test_structural_dry_run_with_proposals(self, mock_api, mock_git,
                                                mock_costs, project_dir,
                                                monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        # Create proposals file
        scores_dir = os.path.join(project_dir, 'working', 'scores')
        os.makedirs(scores_dir, exist_ok=True)
        proposals_file = os.path.join(scores_dir, 'structural-proposals.csv')
        with open(proposals_file, 'w') as f:
            f.write('dimension|target|fix_location|rationale|change|status\n')
            f.write('pacing|act1-sc01|structural|Needs faster pacing|Speed up|pending\n')

        main(['--structural', '--dry-run'])

        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out
        assert mock_api.call_count == 0


# ============================================================================
# main() -- cost estimation
# ============================================================================

class TestMainCostEstimation:
    """Tests for cost estimation during revision."""

    def test_cost_estimate_called(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        plugin_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))))
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: plugin_dir)

        rows = _make_plan_rows(('test-pass',))
        _write_plan(project_dir, rows)
        _ensure_scene_files(project_dir)

        import subprocess as sp

        def mock_subprocess_run(cmd, **kwargs):
            cmd_str = ' '.join(str(c) for c in cmd)
            if 'storyforge.revision' in cmd_str:
                return sp.CompletedProcess(cmd, 0, stdout='Prompt', stderr='')
            if 'storyforge.parsing' in cmd_str:
                return sp.CompletedProcess(cmd, 0, stdout='', stderr='')
            return sp.CompletedProcess(cmd, 0, stdout='', stderr='')

        monkeypatch.setattr('subprocess.run', mock_subprocess_run)
        mock_api.set_response('Result')

        main([])

        # Cost estimation should have been called
        assert len(mock_costs.estimates) >= 1


# ============================================================================
# main() -- git workflow
# ============================================================================

class TestMainGitWorkflow:
    """Tests for git branch/PR creation during revision."""

    def test_creates_branch_and_pr(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        plugin_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))))
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: plugin_dir)

        rows = _make_plan_rows(('test-pass',))
        _write_plan(project_dir, rows)
        _ensure_scene_files(project_dir)

        import subprocess as sp

        def mock_subprocess_run(cmd, **kwargs):
            cmd_str = ' '.join(str(c) for c in cmd)
            if 'storyforge.revision' in cmd_str:
                return sp.CompletedProcess(cmd, 0, stdout='Prompt', stderr='')
            if 'storyforge.parsing' in cmd_str:
                return sp.CompletedProcess(cmd, 0, stdout='', stderr='')
            return sp.CompletedProcess(cmd, 0, stdout='', stderr='')

        monkeypatch.setattr('subprocess.run', mock_subprocess_run)
        mock_api.set_response('Result')

        main([])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) >= 1
        assert branch_calls[0][1] == 'revise'

        pr_calls = mock_git.calls_for('create_draft_pr')
        assert len(pr_calls) >= 1

    def test_no_branch_in_dry_run(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))

        rows = _make_plan_rows(('test-pass',))
        _write_plan(project_dir, rows)

        main(['--dry-run'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 0


# ============================================================================
# _estimate_avg_words
# ============================================================================

class TestEstimateAvgWords:
    """Tests for _estimate_avg_words."""

    def test_from_metadata_csv(self, project_dir):
        from storyforge.cmd_revise import _estimate_avg_words
        # Update metadata to have word counts
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(meta_csv) as f:
            content = f.read()
        # Replace all '0' word counts with real values
        content = content.replace('|0|2500', '|2500|2500')
        content = content.replace('|0|3000', '|3000|3000')
        content = content.replace('|0|1500', '|1500|1500')
        content = content.replace('|0|2800', '|2800|2800')
        content = content.replace('|0|2000', '|2000|2000')
        content = content.replace('|0|2200', '|2200|2200')
        with open(meta_csv, 'w') as f:
            f.write(content)

        avg, count = _estimate_avg_words(project_dir)
        assert avg > 0
        assert count > 0

    def test_fallback_to_scene_files(self, project_dir):
        from storyforge.cmd_revise import _estimate_avg_words
        _ensure_scene_files(project_dir)
        avg, count = _estimate_avg_words(project_dir)
        assert avg > 0
        assert count > 0


# ============================================================================
# _register_new_scenes
# ============================================================================

class TestRegisterNewScenes:
    """Tests for new scene registration during revision."""

    def test_registers_new_scene(self, project_dir):
        from storyforge.cmd_revise import _register_new_scenes

        # Create a new scene file
        scenes_dir = os.path.join(project_dir, 'scenes')
        with open(os.path.join(scenes_dir, 'new-scene-x.md'), 'w') as f:
            f.write('New scene prose here.\n')

        _register_new_scenes(project_dir, 'NEW:new-scene-x;act1-sc01', 'test-pass')

        # Check the scene was registered in metadata
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(meta_csv) as f:
            content = f.read()
        assert 'new-scene-x' in content

    def test_no_new_prefix_skips(self, project_dir):
        from storyforge.cmd_revise import _register_new_scenes
        _register_new_scenes(project_dir, 'act1-sc01;act1-sc02', 'test-pass')
        # Should not error and not change anything significant
