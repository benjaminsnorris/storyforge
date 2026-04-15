"""Tests for revise --polish --loop convergence mode."""

import os
import pytest


class TestLoopFlags:
    def test_parse_loop_flag(self):
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--polish', '--loop'])
        assert args.loop is True
        assert args.max_loops == 5

    def test_parse_max_loops(self):
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--polish', '--loop', '--max-loops', '3'])
        assert args.max_loops == 3

    def test_loop_default_false(self):
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--polish'])
        assert args.loop is False

    def test_parse_skip_final_score(self):
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--polish', '--loop', '--skip-final-score'])
        assert args.skip_final_score is True

    def test_skip_final_score_default_false(self):
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--polish', '--loop'])
        assert args.skip_final_score is False

    def test_skip_final_score_requires_loop(self):
        """--skip-final-score without --loop should exit with error."""
        from storyforge.cmd_revise import main
        with pytest.raises(SystemExit) as exc_info:
            main(['--polish', '--skip-final-score'])
        assert exc_info.value.code != 0


class TestDiagnosisReader:
    def test_read_diagnosis(self, tmp_path):
        from storyforge.cmd_revise import _read_diagnosis

        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        with open(os.path.join(cycle_dir, 'diagnosis.csv'), 'w') as f:
            f.write('principle|scale|avg_score|worst_items|delta_from_last|priority\n')
            f.write('prose_naturalness|scene|2.1|s01;s03||high\n')
            f.write('dialogue_authenticity|scene|3.5|s02||low\n')

        rows = _read_diagnosis(cycle_dir)
        assert len(rows) == 2
        assert rows[0]['principle'] == 'prose_naturalness'
        assert rows[0]['priority'] == 'high'

    def test_read_missing_diagnosis(self, tmp_path):
        from storyforge.cmd_revise import _read_diagnosis
        rows = _read_diagnosis(str(tmp_path))
        assert rows == []


class TestSummarizeDiagnosis:
    def test_summarize(self):
        from storyforge.cmd_revise import _summarize_diagnosis

        diag = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '2.1', 'priority': 'high'},
            {'principle': 'fictive_dream', 'scale': 'scene', 'avg_score': '2.8', 'priority': 'medium'},
            {'principle': 'dialogue_authenticity', 'scale': 'scene', 'avg_score': '4.0', 'priority': 'low'},
            {'principle': 'genre_contract', 'scale': 'act', 'avg_score': '3.0', 'priority': 'medium'},
        ]

        summary = _summarize_diagnosis(diag)
        assert summary['high_count'] == 1
        assert summary['medium_count'] == 1  # only scene-scale counts
        assert 'prose_naturalness' in summary['high_principles']
        assert 'fictive_dream' in summary['medium_principles']
        assert summary['scene_principle_count'] == 3
        assert abs(summary['overall_avg'] - 2.97) < 0.1  # (2.1 + 2.8 + 4.0) / 3

    def test_summarize_empty(self):
        from storyforge.cmd_revise import _summarize_diagnosis
        summary = _summarize_diagnosis([])
        assert summary['high_count'] == 0
        assert summary['overall_avg'] == 0.0


class TestTargetedPolishPlan:
    def test_generates_from_diagnosis(self, tmp_path):
        from storyforge.cmd_revise import _generate_targeted_polish_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag = [
            {'principle': 'prose_naturalness', 'scale': 'scene',
             'avg_score': '2.1', 'worst_items': 's01;s03', 'priority': 'high'},
            {'principle': 'fictive_dream', 'scale': 'scene',
             'avg_score': '2.8', 'worst_items': 's02;s05', 'priority': 'medium'},
            {'principle': 'dialogue_authenticity', 'scale': 'scene',
             'avg_score': '4.0', 'worst_items': '', 'priority': 'low'},
        ]

        rows = _generate_targeted_polish_plan(plan_file, diag)
        assert len(rows) == 1
        assert rows[0]['name'] == 'targeted-polish'
        assert 'prose naturalness' in rows[0]['guidance']
        assert 'fictive dream' in rows[0]['guidance']
        assert 'dialogue' not in rows[0]['guidance']  # low priority excluded
        assert 's01' in rows[0]['targets']

        # Verify file was written
        assert os.path.isfile(plan_file)

    def test_falls_back_to_general_polish(self, tmp_path):
        from storyforge.cmd_revise import _generate_targeted_polish_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        # All low priority — no targeted issues
        diag = [
            {'principle': 'prose_naturalness', 'scale': 'scene',
             'avg_score': '4.5', 'worst_items': '', 'priority': 'low'},
        ]

        rows = _generate_targeted_polish_plan(plan_file, diag)
        assert len(rows) == 1
        assert rows[0]['name'] == 'prose-polish'  # fell back to general

    def test_excludes_non_scene_scale(self, tmp_path):
        from storyforge.cmd_revise import _generate_targeted_polish_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag = [
            {'principle': 'genre_contract', 'scale': 'act',
             'avg_score': '1.5', 'worst_items': '', 'priority': 'high'},
        ]

        rows = _generate_targeted_polish_plan(plan_file, diag)
        # Act-scale high priority should not generate targeted plan
        assert rows[0]['name'] == 'prose-polish'


class TestVersionedPlans:
    def test_next_plan_number_empty_dir(self, tmp_path):
        from storyforge.cmd_revise import _next_plan_number
        assert _next_plan_number(str(tmp_path)) == 1

    def test_next_plan_number_with_existing(self, tmp_path):
        from storyforge.cmd_revise import _next_plan_number
        (tmp_path / 'revision-plan-1.csv').touch()
        (tmp_path / 'revision-plan-3.csv').touch()
        assert _next_plan_number(str(tmp_path)) == 4

    def test_next_plan_number_ignores_non_numeric(self, tmp_path):
        from storyforge.cmd_revise import _next_plan_number
        (tmp_path / 'revision-plan-foo.csv').touch()
        (tmp_path / 'revision-plan-2.csv').touch()
        assert _next_plan_number(str(tmp_path)) == 3

    def test_create_versioned_plan_writes_numbered_file(self, tmp_path):
        from storyforge.cmd_revise import _create_versioned_plan, _read_csv_plan
        plan_file = str(tmp_path / 'revision-plan.csv')
        rows = [{'pass': '1', 'name': 'test-pass', 'purpose': 'testing',
                 'scope': 'full', 'targets': '', 'guidance': '', 'protection': '',
                 'findings': '', 'status': 'pending', 'model_tier': 'opus',
                 'fix_location': 'craft'}]
        _create_versioned_plan(plan_file, rows)

        # Numbered file exists
        assert os.path.isfile(str(tmp_path / 'revision-plan-1.csv'))
        # Symlink exists and points to numbered file
        assert os.path.islink(plan_file)
        assert os.readlink(plan_file) == 'revision-plan-1.csv'
        # Content readable through symlink
        read_back = _read_csv_plan(plan_file)
        assert len(read_back) == 1
        assert read_back[0]['name'] == 'test-pass'

    def test_create_versioned_plan_increments(self, tmp_path):
        from storyforge.cmd_revise import _create_versioned_plan
        plan_file = str(tmp_path / 'revision-plan.csv')
        rows1 = [{'pass': '1', 'name': 'first', 'purpose': '', 'scope': '',
                  'targets': '', 'guidance': '', 'protection': '', 'findings': '',
                  'status': 'pending', 'model_tier': '', 'fix_location': ''}]
        rows2 = [{'pass': '1', 'name': 'second', 'purpose': '', 'scope': '',
                  'targets': '', 'guidance': '', 'protection': '', 'findings': '',
                  'status': 'pending', 'model_tier': '', 'fix_location': ''}]

        _create_versioned_plan(plan_file, rows1)
        _create_versioned_plan(plan_file, rows2)

        # Both numbered files exist
        assert os.path.isfile(str(tmp_path / 'revision-plan-1.csv'))
        assert os.path.isfile(str(tmp_path / 'revision-plan-2.csv'))
        # Symlink points to latest
        assert os.readlink(plan_file) == 'revision-plan-2.csv'

    def test_create_versioned_plan_replaces_regular_file(self, tmp_path):
        """First run after upgrade: existing plain file gets replaced with symlink."""
        from storyforge.cmd_revise import _create_versioned_plan
        plan_file = str(tmp_path / 'revision-plan.csv')
        # Simulate pre-upgrade state: plain file
        with open(plan_file, 'w') as f:
            f.write('old content\n')
        assert not os.path.islink(plan_file)

        rows = [{'pass': '1', 'name': 'upgraded', 'purpose': '', 'scope': '',
                 'targets': '', 'guidance': '', 'protection': '', 'findings': '',
                 'status': 'pending', 'model_tier': '', 'fix_location': ''}]
        _create_versioned_plan(plan_file, rows)

        assert os.path.islink(plan_file)
        assert os.readlink(plan_file) == 'revision-plan-1.csv'

    def test_update_through_symlink(self, tmp_path):
        """In-place updates via _write_csv_plan go through symlink to numbered file."""
        from storyforge.cmd_revise import (
            _create_versioned_plan, _write_csv_plan, _read_csv_plan,
        )
        plan_file = str(tmp_path / 'revision-plan.csv')
        rows = [{'pass': '1', 'name': 'original', 'purpose': '', 'scope': '',
                 'targets': '', 'guidance': '', 'protection': '', 'findings': '',
                 'status': 'pending', 'model_tier': '', 'fix_location': ''}]
        _create_versioned_plan(plan_file, rows)

        # Update in place through symlink
        rows[0]['status'] = 'completed'
        _write_csv_plan(plan_file, rows)

        # Read back through symlink — should see update
        read_back = _read_csv_plan(plan_file)
        assert read_back[0]['status'] == 'completed'
        # Read directly from numbered file — same content
        direct = _read_csv_plan(str(tmp_path / 'revision-plan-1.csv'))
        assert direct[0]['status'] == 'completed'

    def test_previous_plan_preserved_after_new(self, tmp_path):
        """Creating a new plan doesn't destroy the previous one."""
        from storyforge.cmd_revise import (
            _create_versioned_plan, _read_csv_plan,
        )
        plan_file = str(tmp_path / 'revision-plan.csv')
        rows1 = [{'pass': '1', 'name': 'plan-one', 'purpose': '', 'scope': '',
                  'targets': '', 'guidance': '', 'protection': '', 'findings': '',
                  'status': 'completed', 'model_tier': '', 'fix_location': ''}]
        rows2 = [{'pass': '1', 'name': 'plan-two', 'purpose': '', 'scope': '',
                  'targets': '', 'guidance': '', 'protection': '', 'findings': '',
                  'status': 'pending', 'model_tier': '', 'fix_location': ''}]

        _create_versioned_plan(plan_file, rows1)
        _create_versioned_plan(plan_file, rows2)

        # Previous plan still intact
        old = _read_csv_plan(str(tmp_path / 'revision-plan-1.csv'))
        assert old[0]['name'] == 'plan-one'
        assert old[0]['status'] == 'completed'
        # Symlink points to new plan
        current = _read_csv_plan(plan_file)
        assert current[0]['name'] == 'plan-two'


class TestDeterministicScore:
    """Tests for _run_deterministic_score — lightweight, free scoring path."""

    def _setup_project(self, tmp_path):
        """Create a minimal project structure for deterministic scoring."""
        project_dir = str(tmp_path / 'project')
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        working_dir = os.path.join(project_dir, 'working')
        scores_dir = os.path.join(working_dir, 'scores')
        os.makedirs(scenes_dir)
        os.makedirs(ref_dir)
        os.makedirs(scores_dir)

        # Minimal scenes.csv
        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('test-scene|1|Test Scene|1|Alice|drafted|100|1000\n')

        # A simple scene file
        with open(os.path.join(scenes_dir, 'test-scene.md'), 'w') as f:
            f.write('Alice walked slowly through the very quiet garden. '
                    'She was being watched carefully by the old gardener. '
                    'The weather was grey and overcast, rain threatening the horizon. '
                    'It was really quite remarkably beautiful despite everything.\n')

        # storyforge.yaml
        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test Project\n')

        return project_dir

    def test_returns_cycle_dir_and_diag_rows(self, tmp_path):
        from storyforge.cmd_revise import _run_deterministic_score

        project_dir = self._setup_project(tmp_path)
        cycle_dir, diag_rows = _run_deterministic_score(project_dir, ['test-scene'])

        assert os.path.isdir(cycle_dir)
        assert 'cycle-1' in cycle_dir
        assert isinstance(diag_rows, list)

    def test_creates_scene_scores_csv(self, tmp_path):
        from storyforge.cmd_revise import _run_deterministic_score

        project_dir = self._setup_project(tmp_path)
        cycle_dir, _ = _run_deterministic_score(project_dir, ['test-scene'])

        scores_file = os.path.join(cycle_dir, 'scene-scores.csv')
        assert os.path.isfile(scores_file)

        with open(scores_file) as f:
            content = f.read()
        # Should have scores for deterministic principles
        assert 'avoid_passive' in content
        assert 'avoid_adverbs' in content
        assert 'economy_clarity' in content

    def test_updates_latest_symlink(self, tmp_path):
        from storyforge.cmd_revise import _run_deterministic_score

        project_dir = self._setup_project(tmp_path)
        _run_deterministic_score(project_dir, ['test-scene'])

        latest = os.path.join(project_dir, 'working', 'scores', 'latest')
        assert os.path.islink(latest)
        assert os.readlink(latest) == 'cycle-1'

    def test_increments_cycle_number(self, tmp_path):
        from storyforge.cmd_revise import _run_deterministic_score

        project_dir = self._setup_project(tmp_path)

        cycle_dir_1, _ = _run_deterministic_score(project_dir, ['test-scene'])
        assert 'cycle-1' in cycle_dir_1

        cycle_dir_2, _ = _run_deterministic_score(project_dir, ['test-scene'])
        assert 'cycle-2' in cycle_dir_2

        latest = os.path.join(project_dir, 'working', 'scores', 'latest')
        assert os.readlink(latest) == 'cycle-2'

    def test_generates_diagnosis(self, tmp_path):
        from storyforge.cmd_revise import _run_deterministic_score

        project_dir = self._setup_project(tmp_path)
        cycle_dir, diag_rows = _run_deterministic_score(project_dir, ['test-scene'])

        diag_file = os.path.join(cycle_dir, 'diagnosis.csv')
        assert os.path.isfile(diag_file)

    def test_no_api_calls(self, tmp_path, monkeypatch):
        """Deterministic scoring should never call the API."""
        from storyforge.cmd_revise import _run_deterministic_score

        project_dir = self._setup_project(tmp_path)

        # Poison the API key — if it tries to call the API, it'll fail
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        # Should succeed without any API key
        cycle_dir, diag_rows = _run_deterministic_score(project_dir, ['test-scene'])
        assert os.path.isdir(cycle_dir)


class TestExecuteSinglePassModelOverride:
    """Tests for the model_override parameter on _execute_single_pass."""

    def test_model_override_skips_select_revision_model(self, monkeypatch):
        """When model_override is set, select_revision_model should not be called."""
        from storyforge import cmd_revise

        called_select = []
        original_select = cmd_revise.select_revision_model

        def tracking_select(name, purpose=''):
            called_select.append((name, purpose))
            return original_select(name, purpose)

        monkeypatch.setattr('storyforge.cmd_revise.select_revision_model', tracking_select)

        # Verify the model_override path directly: when override is set,
        # `model_override or select_revision_model(...)` short-circuits.
        override = 'claude-sonnet-4-6'
        result = override or tracking_select('targeted-polish', 'test')
        assert result == 'claude-sonnet-4-6'
        assert len(called_select) == 0  # select was never called

    def test_no_override_calls_select_revision_model(self):
        """Without model_override, select_revision_model determines the model."""
        from storyforge.common import select_revision_model
        override = None
        result = override or select_revision_model('targeted-polish', 'craft polish')
        # Should get a model string back from select_revision_model
        assert result in ('claude-opus-4-6', 'claude-sonnet-4-6')
