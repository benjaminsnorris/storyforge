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


def _rewrites_a_scene(run, project_dir):
    """Wrap a fake subprocess.run so scene extraction changes a scene file,
    as a real pass does (a pass that changes nothing halts; see
    TestPassThatChangesNothing)."""
    def wrapped(cmd, **kwargs):
        if 'extract-scenes' in ' '.join(str(c) for c in cmd):
            scenes = os.path.join(project_dir, 'scenes')
            name = sorted(f for f in os.listdir(scenes) if f.endswith('.md'))[0]
            with open(os.path.join(scenes, name), 'a') as f:
                f.write('\nRevised.\n')
        return run(cmd, **kwargs)
    return wrapped


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

    @pytest.mark.parametrize('fixed, commits', [
        ([], []),
        (['act1-sc01'], ['Naturalness: upstream brief fixes for 1 scenes']),
    ])
    def test_naturalness_commits_brief_fixes_only_when_made(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, fixed, commits):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root', lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir',
                            lambda: os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.dirname(
                                    os.path.dirname(__file__))))))
        latest = os.path.join(project_dir, 'working', 'scores', 'latest')
        os.makedirs(latest, exist_ok=True)
        open(os.path.join(latest, 'diagnosis.csv'), 'w').close()
        monkeypatch.setattr('storyforge.cmd_revise._read_diagnosis', lambda d: [{}])
        monkeypatch.setattr('storyforge.cmd_revise._detect_upstream_scenes',
                            lambda p, rows: ['act1-sc01'])
        monkeypatch.setattr('storyforge.cmd_revise._fix_and_redraft',
                            lambda p, ids: (fixed, {} if fixed else {'act1-sc01': 'no reply'}))
        made = []
        monkeypatch.setattr('storyforge.cmd_revise.commit_and_push',
                            lambda p, msg, *a, **kw: made.append(msg))

        main(['--naturalness', '--dry-run'])

        assert [m for m in made if 'upstream' in m] == commits


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

        monkeypatch.setattr('subprocess.run', _rewrites_a_scene(mock_subprocess_run, project_dir))

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

        monkeypatch.setattr('subprocess.run', _rewrites_a_scene(mock_subprocess_run, project_dir))
        mock_api.set_response('Revised content')

        # Start from pass 2 explicitly
        main(['2'])

        # Only one API call (for pass 2)
        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) >= 1
        # a craft pass rewrites prose, so it opts into the refusal fallback
        assert all(c['fallback'] for c in api_calls)


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

        monkeypatch.setattr('subprocess.run', _rewrites_a_scene(mock_subprocess_run, project_dir))
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

        monkeypatch.setattr('subprocess.run', _rewrites_a_scene(mock_subprocess_run, project_dir))
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

        monkeypatch.setattr('subprocess.run', _rewrites_a_scene(mock_subprocess_run, project_dir))
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


# ============================================================================
# Regressions: a pass that changes nothing (understory 5ac1c26) and a
# structural pass that writes duplicate seq / blank pov (understory bbfc945)
# ============================================================================

def _run_pass_setup(project_dir, monkeypatch, fix_location):
    import subprocess as sp
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_revise.detect_project_root', lambda: project_dir)
    plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(__file__)))))
    monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir', lambda: plugin_dir)
    plan_file = _write_plan(project_dir, _make_plan_rows(('the-pass',), fix_location=fix_location))
    _ensure_scene_files(project_dir)

    def run(cmd, **kwargs):  # extraction finds nothing to write
        if 'build-prompt' in ' '.join(str(c) for c in cmd):
            return sp.CompletedProcess(cmd, 0, stdout='Revision prompt.', stderr='')
        return sp.CompletedProcess(cmd, 0, stdout='', stderr='')
    monkeypatch.setattr('subprocess.run', run)
    return plan_file


class TestPassThatChangesNothing:

    def _status(self, plan_file):
        return _read_csv_plan(plan_file)[0]['status']

    def test_prose_pass_with_no_scene_changes_halts_pending(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        plan_file = _run_pass_setup(project_dir, monkeypatch, 'craft')
        mock_api.set_response('I reviewed the scenes and they read well.')
        with pytest.raises(SystemExit):
            main([])
        assert self._status(plan_file) != 'completed'
        assert not mock_git.calls_for('commit_and_push')

    def test_structural_pass_with_no_csv_block_halts_pending(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        plan_file = _run_pass_setup(project_dir, monkeypatch, 'structural')
        mock_api.set_response('The structure is sound; no changes needed.')
        with pytest.raises(SystemExit):
            main([])
        assert self._status(plan_file) != 'completed'
        assert not mock_git.calls_for('commit_and_push')

    def test_structural_pass_that_applies_is_completed(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        plan_file = _run_pass_setup(project_dir, monkeypatch, 'structural')
        mock_api.set_response('```briefs-csv\nid|goal\nact1-sc01|A sharper goal\n```')
        main([])
        assert self._status(plan_file) == 'completed'


class TestApplyUpstreamBlocks:

    def _ref(self, project_dir, name):
        with open(os.path.join(project_dir, 'reference', name)) as f:
            return f.read()

    def test_new_scene_without_pov_writes_nothing(self, project_dir):
        from storyforge.cmd_revise import UpstreamApplyError, _apply_upstream_blocks
        before = (self._ref(project_dir, 'scenes.csv'), self._ref(project_dir, 'scene-briefs.csv'))
        reply = ('```briefs-csv\nid|goal\nact1-sc01|Changed\n```\n'
                 '```scenes-csv\nid|seq|title|pov\nbridge|99|Bridge|\n```')
        with pytest.raises(UpstreamApplyError, match='pov'):
            _apply_upstream_blocks(project_dir, reply)
        assert (self._ref(project_dir, 'scenes.csv'),
                self._ref(project_dir, 'scene-briefs.csv')) == before

    def test_duplicate_seq_writes_nothing(self, project_dir):
        from storyforge.cmd_revise import UpstreamApplyError, _apply_upstream_blocks
        before = self._ref(project_dir, 'scenes.csv')
        reply = '```scenes-csv\nid|seq|title|pov\nbridge|2|Bridge|Dorren Hayle\n```'
        with pytest.raises(UpstreamApplyError, match='seq 2'):
            _apply_upstream_blocks(project_dir, reply)
        assert self._ref(project_dir, 'scenes.csv') == before

    def test_a_valid_new_scene_is_added_in_seq_order(self, project_dir):
        from storyforge.cmd_revise import _apply_upstream_blocks
        from storyforge.elaborate import _read_csv
        reply = '```scenes-csv\nid|seq|title|pov\nbridge|2.5|Bridge|Dorren Hayle\n```'
        files, affected = _apply_upstream_blocks(project_dir, reply)
        assert files == ['scenes.csv'] and affected == {'bridge'}
        ids = [r['id'] for r in _read_csv(os.path.join(project_dir, 'reference', 'scenes.csv'))]
        assert ids.index('bridge') == ids.index('act1-sc02') + 1

    def test_an_old_duplicate_elsewhere_does_not_block(self, project_dir):
        from storyforge.cmd_revise import _apply_upstream_blocks
        from storyforge.csv_cli import update_field
        scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        update_field(scenes_csv, 'act2-sc01', 'seq', '3')  # duplicates new-x1
        reply = '```scenes-csv\nid|seq|title\nact1-sc01|1|New Title\n```'
        assert _apply_upstream_blocks(project_dir, reply)[1] == {'act1-sc01'}


class TestPolishLoopPass:
    """H3: the polish loop called extract-scenes with flags it does not take,
    so its reply was never written and the pass was still marked completed."""

    def _run(self, project_dir, monkeypatch, reply_text, plan_dir=None):
        import json
        import subprocess as sp
        from storyforge import cmd_revise
        real_run = sp.run
        calls = []

        def fake_run(cmd, **kwargs):
            if 'build-prompt' in [str(c) for c in cmd]:
                return sp.CompletedProcess(cmd, 0, stdout='Prompt text', stderr='')
            if "extract-scenes" in [str(c) for c in cmd]:
                return real_run(cmd, **kwargs)  # the real one
            raise AssertionError(f"unexpected subprocess: {cmd}")

        def fake_invoke(prompt, model, log_file, max_tokens=4096, label='', timeout=600,
                        system=None, output_schema=None, fallback=False):
            calls.append(fallback)
            response = {'content': [{'type': 'text', 'text': reply_text}],
                        'stop_reason': 'end_turn', 'usage': {}}
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, 'w') as f:
                json.dump(response, f)
            return response

        monkeypatch.setattr('subprocess.run', fake_run)
        monkeypatch.setattr('storyforge.api.invoke_to_file', fake_invoke)
        monkeypatch.setattr('storyforge.common.build_shared_context', lambda *a, **k: [])
        monkeypatch.setattr('storyforge.common.select_revision_model', lambda *a, **k: 'm')
        monkeypatch.setattr('storyforge.cmd_revise.max_output_tokens', lambda m: 1000)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        commits = []
        monkeypatch.setattr('storyforge.git.commit_and_push',
                            lambda d, msg, paths: commits.append(msg))
        # scripts/lib/python/storyforge/cmd_revise.py -> the plugin root
        plugin_dir = os.path.abspath(os.path.join(
            os.path.dirname(cmd_revise.__file__), '..', '..', '..', '..'))
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir', lambda: plugin_dir)
        rows = _make_plan_rows()
        plan_file = _write_plan(project_dir, rows)
        cmd_revise._execute_single_pass(project_dir, plan_file, rows, 1)
        return rows, commits, calls

    def test_reply_is_written_and_opts_into_the_fallback(self, project_dir, monkeypatch):
        prose = 'The rain kept on. ' * 50
        rows, commits, calls = self._run(
            project_dir, monkeypatch,
            f'=== SCENE: act1-sc01 ===\n{prose}\n=== END SCENE: act1-sc01 ===')
        with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md')) as f:
            assert f.read().strip() == prose.strip()
        assert rows[0]['status'] == 'completed' and commits
        assert calls == [True]

    def test_failed_extraction_is_not_marked_completed(self, project_dir, monkeypatch):
        with pytest.raises(SystemExit) as exc:
            self._run(project_dir, monkeypatch, '')
        assert exc.value.code == 1
        rows = _read_csv_plan(os.path.join(project_dir, 'working', 'plans',
                                           'revision-plan.csv'))
        assert rows[0]['status'] == 'in_progress'



class TestPassFallback:
    """T1: prose passes opt into the refusal fallback; structural and
    registry passes, which write CSV, do not."""

    @pytest.mark.parametrize('fix_location, expected', [
        ('craft', True), ('structural', False), ('registry', False)])
    def test_opt_in_follows_fix_location(self, mock_api, mock_git, mock_costs, project_dir,
                                         monkeypatch, fix_location, expected):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root', lambda: project_dir)
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(__file__)))))
        monkeypatch.setattr('storyforge.cmd_revise.get_plugin_dir', lambda: plugin_dir)
        _write_plan(project_dir, _make_plan_rows(('pass-a',), fix_location=fix_location))
        _ensure_scene_files(project_dir)
        import subprocess as sp

        def fake_run(cmd, **kwargs):
            out = 'Prompt text' if 'storyforge.revision' in ' '.join(map(str, cmd)) else ''
            return sp.CompletedProcess(cmd, 0, stdout=out, stderr='')
        monkeypatch.setattr('subprocess.run', _rewrites_a_scene(fake_run, project_dir))
        mock_api.set_response('Revised content')
        try:
            main(['1'])
        except SystemExit:
            pass  # an upstream pass with no CSV blocks halts; the call is what matters
        calls = mock_api.calls_for('invoke_to_file')
        assert calls and calls[0]['fallback'] is expected


class TestLogUsage:
    def test_fallback_reply_is_costed_as_its_model(self, project_dir, mock_costs, tmp_path):
        """T4"""
        import json
        from storyforge.cmd_revise import _log_usage
        log = tmp_path / 'r.json'
        log.write_text(json.dumps({
            'model': 'claude-opus-5', 'stop_reason': 'end_turn', 'content': [],
            'usage': {'input_tokens': 1, 'output_tokens': 1,
                      'iterations': [{'type': 'fallback_message'}]}}))
        _log_usage(project_dir, str(log), 'revise', 'pass-a', 'claude-opus-5-5')
        assert [op['model'] for op in mock_costs.operations] == ['claude-opus-5']

    def test_unreadable_log_warns(self, project_dir, mock_costs, tmp_path, capsys):
        """I3: was a silent pass"""
        from storyforge.cmd_revise import _log_usage
        log = tmp_path / 'r.json'
        log.write_text('{not json')
        _log_usage(project_dir, str(log), 'revise', 'pass-a', 'm')
        assert 'WARNING: could not log the cost of revise pass-a' in capsys.readouterr().out


class TestHoneDelegationRedraftsOnlyChangedScenes:
    """A brief pass delegated to hone redrafted every target, including a
    scene whose rewrite hone refused: its prose was redrafted from the brief
    it already had."""

    def test_a_refused_scene_is_not_redrafted(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        from storyforge import cmd_revise
        plan_file = _run_pass_setup(project_dir, monkeypatch, 'brief')
        rows = _read_csv_plan(plan_file)
        rows[0]['targets'] = 'act1-sc01;act1-sc02'
        rows[0]['scope'] = 'targeted'
        _write_plan(project_dir, rows)
        briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')

        def hone(**kw):
            from storyforge.csv_cli import update_field
            update_field(briefs_csv, 'act1-sc01', 'goal', 'A sharper goal')
            return {'scenes_rewritten': 1, 'fields_rewritten': 1, 'changed': ['act1-sc01'],
                    'rejected': {'act1-sc02': ['evaluation rewrite of goal named Ruzek']}}
        monkeypatch.setattr('storyforge.hone.hone_briefs', hone)
        redrafted = []
        monkeypatch.setattr(cmd_revise, '_redraft_from_briefs',
                            lambda pd, ids, *a, **kw: redrafted.append(list(ids)))

        main([])

        assert redrafted == [['act1-sc01']]
        assert 'Rewrite refused for act1-sc02' in capsys.readouterr().out
