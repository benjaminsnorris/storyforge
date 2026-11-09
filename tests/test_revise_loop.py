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


class TestLightweightScore:
    def test_failed_scenes_leave_latest_where_it_was(self, project_dir, monkeypatch):
        """A polish-loop re-score with a refused scene used to repoint latest
        at a cycle without that scene's scores."""
        from storyforge.cmd_revise import _run_lightweight_score
        scores_base = os.path.join(project_dir, 'working', 'scores')
        os.makedirs(os.path.join(scores_base, 'cycle-1'))
        os.symlink('cycle-1', os.path.join(scores_base, 'latest'))
        monkeypatch.setattr('storyforge.cmd_score._score_direct',
                            lambda *a, **kw: (1, ['act1-sc02']))
        monkeypatch.setattr('storyforge.scoring.generate_diagnosis',
                            lambda *a, **kw: None)

        cycle_dir, _ = _run_lightweight_score(project_dir, ['act1-sc01', 'act1-sc02'])

        assert os.readlink(os.path.join(scores_base, 'latest')) == 'cycle-1'
        assert 'act1-sc02' in open(os.path.join(cycle_dir, 'incomplete.txt')).read()

    def test_a_complete_re_score_moves_latest(self, project_dir, monkeypatch):
        from storyforge.cmd_revise import _run_lightweight_score
        scores_base = os.path.join(project_dir, 'working', 'scores')
        monkeypatch.setattr('storyforge.cmd_score._score_direct',
                            lambda *a, **kw: (1, []))
        monkeypatch.setattr('storyforge.scoring.generate_diagnosis',
                            lambda *a, **kw: None)

        cycle_dir, _ = _run_lightweight_score(project_dir, ['act1-sc01'])

        assert os.path.realpath(os.path.join(scores_base, 'latest')) == os.path.realpath(cycle_dir)


class TestPolishLoopOrchestration:
    """Integration tests for _run_polish_loop two-phase orchestration."""

    def _setup_project(self, tmp_path):
        """Create a minimal project with one scene for loop testing."""
        project_dir = str(tmp_path / 'project')
        for d in ('scenes', 'reference', 'working/scores', 'working/plans',
                  'working/logs'):
            os.makedirs(os.path.join(project_dir, d))

        with open(os.path.join(project_dir, 'reference', 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('s01|1|Test|1|Alice|drafted|100|1000\n')

        with open(os.path.join(project_dir, 'scenes', 's01.md'), 'w') as f:
            f.write('Alice walked slowly through the very quiet garden.\n')

        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n')

        return project_dir

    def _make_diag(self, high=1, medium=0, avg=3.0):
        """Build fake diagnosis rows."""
        rows = []
        if high:
            rows.append({'principle': 'avoid_passive', 'scale': 'scene',
                         'avg_score': str(avg), 'worst_items': 's01',
                         'delta_from_last': '', 'priority': 'high',
                         'root_cause': 'craft'})
        if medium:
            rows.append({'principle': 'avoid_adverbs', 'scale': 'scene',
                         'avg_score': str(avg + 0.5), 'worst_items': 's01',
                         'delta_from_last': '', 'priority': 'medium',
                         'root_cause': 'craft'})
        return rows

    def test_phase1_uses_deterministic_score(self, tmp_path, monkeypatch):
        """Phase 1 should call _run_deterministic_score, not _run_lightweight_score."""
        from storyforge.cmd_revise import _run_polish_loop

        project_dir = self._setup_project(tmp_path)
        calls = {'deterministic': 0, 'lightweight': 0}

        converged_diag = self._make_diag(high=0, medium=0)

        def fake_deterministic(proj, scene_ids):
            calls['deterministic'] += 1
            cycle_dir = os.path.join(proj, 'working', 'scores', f'cycle-{calls["deterministic"]}')
            os.makedirs(cycle_dir, exist_ok=True)
            return cycle_dir, converged_diag

        def fake_lightweight(proj, scene_ids):
            calls['lightweight'] += 1
            cycle_dir = os.path.join(proj, 'working', 'scores', f'cycle-full-{calls["lightweight"]}')
            os.makedirs(cycle_dir, exist_ok=True)
            return cycle_dir, converged_diag

        monkeypatch.setattr('storyforge.cmd_revise._run_deterministic_score', fake_deterministic)
        monkeypatch.setattr('storyforge.cmd_revise._run_lightweight_score', fake_lightweight)
        monkeypatch.setattr('storyforge.cmd_revise.create_branch', lambda *a: None)
        monkeypatch.setattr('storyforge.cmd_revise.ensure_branch_pushed', lambda *a: None)
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **kw: True)
        monkeypatch.setattr('storyforge.cmd_revise.create_draft_pr',
                            lambda title, body, pd, work_type='': '')
        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body', lambda pd, pr: '')
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', lambda pd, pr, b: None)
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment', lambda pd, pr, body: None)

        _run_polish_loop(project_dir, 3, None)

        # Phase 1 used deterministic, Phase 2 used lightweight
        assert calls['deterministic'] == 1
        assert calls['lightweight'] == 1

    def _patch_loop(self, monkeypatch, diag):
        def fake_deterministic(proj, scene_ids):
            cycle_dir = os.path.join(proj, 'working', 'scores', 'cycle-1')
            os.makedirs(cycle_dir, exist_ok=True)
            return cycle_dir, diag
        monkeypatch.setattr('storyforge.cmd_revise._run_deterministic_score', fake_deterministic)
        for name, fn in (('create_branch', lambda *a: None),
                         ('ensure_branch_pushed', lambda *a: None),
                         ('create_draft_pr', lambda title, body, pd, work_type='': ''),
                         ('get_pr_body', lambda pd, pr: ''),
                         ('set_pr_body', lambda pd, pr, b: None),
                         ('add_pr_comment', lambda pd, pr, body: None)):
            monkeypatch.setattr(f'storyforge.cmd_revise.{name}', fn)
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **kw: True)

    def test_source_drift_is_fixed_before_convergence(self, tmp_path, monkeypatch):
        """#477 review (SF-4/T-1): clean craft scores don't skip source drift."""
        from storyforge.cmd_revise import _run_polish_loop
        project_dir = self._setup_project(tmp_path)
        self._patch_loop(monkeypatch, self._make_diag(high=0, medium=0))
        drift = {'s01': ['brief outcome: the source ends no-but']}
        monkeypatch.setattr('storyforge.cmd_revise._source_drift_scenes',
                            lambda p, quiet=False: drift)
        fixed_calls = []

        def fake_fix(proj, scenes):
            fixed_calls.append(scenes)
            drift.clear()          # the redraft changes the brief: no longer drift
            return scenes, {}
        monkeypatch.setattr('storyforge.cmd_revise._fix_and_redraft', fake_fix)
        _run_polish_loop(project_dir, 3, None, skip_final_score=True)
        assert fixed_calls == [['s01']]

    def test_a_brief_root_cause_alone_still_converges(self, tmp_path, monkeypatch):
        """Without a source, clean craft scores converge as before."""
        from storyforge.cmd_revise import _run_polish_loop
        project_dir = self._setup_project(tmp_path)
        diag = [{'principle': 'x', 'scale': 'scene', 'avg_score': '4', 'worst_items': 's01',
                 'delta_from_last': '', 'priority': 'low', 'root_cause': 'brief'}]
        self._patch_loop(monkeypatch, diag)
        fixed_calls = []
        monkeypatch.setattr('storyforge.cmd_revise._fix_and_redraft',
                            lambda p, s: fixed_calls.append(s) or ([], {}))
        _run_polish_loop(project_dir, 3, None, skip_final_score=True)
        assert fixed_calls == []

    def test_a_blamed_brief_with_craft_issues_left_is_named_not_fixed(
            self, tmp_path, monkeypatch, capsys):
        """Plan decision 9 (PR #675's review T-2): with craft issues left and
        the diagnosis blaming a brief, the real `_detect_upstream_scenes`
        names the scene for the author and nothing is sent to a brief fix;
        the craft pass still runs."""
        from storyforge.cmd_revise import NO_BRIEF_FIX, _run_polish_loop
        project_dir = self._setup_project(tmp_path)
        diag = self._make_diag(high=1)
        diag[0]['root_cause'] = 'brief'
        self._patch_loop(monkeypatch, diag)
        fixed_calls, passes = [], []
        monkeypatch.setattr('storyforge.cmd_revise._fix_and_redraft',
                            lambda p, s: fixed_calls.append(s) or ([], {}))
        monkeypatch.setattr('storyforge.cmd_revise._execute_single_pass',
                            lambda *a, **k: passes.append(a[3]))
        _run_polish_loop(project_dir, 1, None, skip_final_score=True)
        assert fixed_calls == [] and passes == [1]
        out = capsys.readouterr().out
        assert f'the diagnosis blames the briefs of s01; not rewritten: {NO_BRIEF_FIX}' in out

    def test_drift_only_in_the_authors_notes_is_not_upstream(self, tmp_path, monkeypatch,
                                                              capsys):
        """PR #675's review SF-1, SF-2, CR-1: no fix rewrites an author's
        note, so drift only there is no upstream work and no "drift fixed"."""
        from storyforge import cmd_revise, source, source_fidelity
        from types import SimpleNamespace
        project_dir = self._setup_project(tmp_path)
        monkeypatch.setattr(source, 'read_config',
                            lambda p: SimpleNamespace(mode='faithful'))
        monkeypatch.setattr(source_fidelity, 'drift_state', lambda p: SimpleNamespace(
            drift={'s01': ['brief goal: the source wants the cup'],
                   's02': ['brief outcome: drifted', 'brief key_dialogue: a line']},
            checked=True, stale=[], pretag=None))
        assert cmd_revise._detect_upstream_scenes(project_dir, []) == ['s02']
        out = capsys.readouterr().out
        assert 'source drift only in the author\'s notes, not rewritten' in out
        assert 's01 (brief goal: the source wants the cup)' in out
        assert cmd_revise._source_drift_scenes(project_dir, quiet=True) == {
            's02': ['brief outcome: drifted', 'brief key_dialogue: a line']}

    def test_skip_final_score_skips_phase2(self, tmp_path, monkeypatch):
        """--skip-final-score should prevent _run_lightweight_score from being called."""
        from storyforge.cmd_revise import _run_polish_loop

        project_dir = self._setup_project(tmp_path)
        calls = {'lightweight': 0}

        converged_diag = self._make_diag(high=0, medium=0)

        def fake_deterministic(proj, scene_ids):
            cycle_dir = os.path.join(proj, 'working', 'scores', 'cycle-1')
            os.makedirs(cycle_dir, exist_ok=True)
            return cycle_dir, converged_diag

        def fake_lightweight(proj, scene_ids):
            calls['lightweight'] += 1
            return '', converged_diag

        monkeypatch.setattr('storyforge.cmd_revise._run_deterministic_score', fake_deterministic)
        monkeypatch.setattr('storyforge.cmd_revise._run_lightweight_score', fake_lightweight)
        monkeypatch.setattr('storyforge.cmd_revise.create_branch', lambda *a: None)
        monkeypatch.setattr('storyforge.cmd_revise.ensure_branch_pushed', lambda *a: None)
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **kw: True)
        monkeypatch.setattr('storyforge.cmd_revise.create_draft_pr',
                            lambda title, body, pd, work_type='': '')
        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body', lambda pd, pr: '')
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', lambda pd, pr, b: None)
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment', lambda pd, pr, body: None)

        _run_polish_loop(project_dir, 3, None, skip_final_score=True)

        assert calls['lightweight'] == 0  # Phase 2 was skipped

    def test_polish_uses_sonnet_model(self, tmp_path, monkeypatch):
        """Phase 1 polish passes should use Sonnet, not Opus."""
        from storyforge.cmd_revise import _run_polish_loop

        project_dir = self._setup_project(tmp_path)
        captured_overrides = []

        # First call: high issues (triggers polish). Second call: converged.
        call_count = [0]
        def fake_deterministic(proj, scene_ids):
            call_count[0] += 1
            cycle_dir = os.path.join(proj, 'working', 'scores', f'cycle-{call_count[0]}')
            os.makedirs(cycle_dir, exist_ok=True)
            if call_count[0] == 1:
                return cycle_dir, self._make_diag(high=1, avg=2.0)
            return cycle_dir, self._make_diag(high=0, medium=0, avg=4.5)

        def fake_execute(proj, plan_file, plan_rows, iteration, model_override=None):
            captured_overrides.append(model_override)

        monkeypatch.setattr('storyforge.cmd_revise._run_deterministic_score', fake_deterministic)
        monkeypatch.setattr('storyforge.cmd_revise._run_lightweight_score',
                            lambda p, s: ('', self._make_diag(high=0)))
        monkeypatch.setattr('storyforge.cmd_revise._execute_single_pass', fake_execute)
        monkeypatch.setattr('storyforge.cmd_revise.create_branch', lambda *a: None)
        monkeypatch.setattr('storyforge.cmd_revise.ensure_branch_pushed', lambda *a: None)
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **kw: True)
        monkeypatch.setattr('storyforge.cmd_revise.create_draft_pr',
                            lambda title, body, pd, work_type='': '')
        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body', lambda pd, pr: '')
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', lambda pd, pr, b: None)
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment', lambda pd, pr, body: None)

        _run_polish_loop(project_dir, 3, None)

        assert len(captured_overrides) == 1
        from storyforge.common import model_for_tier
        assert captured_overrides[0] == model_for_tier('sonnet')

    def test_convergence_stops_loop(self, tmp_path, monkeypatch):
        """Loop should stop when avg doesn't improve between iterations."""
        from storyforge.cmd_revise import _run_polish_loop

        project_dir = self._setup_project(tmp_path)

        call_count = [0]
        def fake_deterministic(proj, scene_ids):
            call_count[0] += 1
            cycle_dir = os.path.join(proj, 'working', 'scores', f'cycle-{call_count[0]}')
            os.makedirs(cycle_dir, exist_ok=True)
            # Same score every time — should converge after iteration 2
            return cycle_dir, self._make_diag(high=1, avg=3.0)

        polish_count = [0]
        def fake_execute(proj, plan_file, plan_rows, iteration, model_override=None):
            polish_count[0] += 1

        monkeypatch.setattr('storyforge.cmd_revise._run_deterministic_score', fake_deterministic)
        monkeypatch.setattr('storyforge.cmd_revise._run_lightweight_score',
                            lambda p, s: ('', []))
        monkeypatch.setattr('storyforge.cmd_revise._execute_single_pass', fake_execute)
        monkeypatch.setattr('storyforge.cmd_revise.create_branch', lambda *a: None)
        monkeypatch.setattr('storyforge.cmd_revise.ensure_branch_pushed', lambda *a: None)
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **kw: True)
        monkeypatch.setattr('storyforge.cmd_revise.create_draft_pr',
                            lambda title, body, pd, work_type='': '')
        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body', lambda pd, pr: '')
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', lambda pd, pr, b: None)
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment', lambda pd, pr, body: None)

        _run_polish_loop(project_dir, 5, None, skip_final_score=True)

        # Baseline (1) + iteration 1 re-score (2) + iteration 2 re-score (3)
        assert call_count[0] == 3
        # Iteration 1 polished + iteration 2 polished before convergence detected
        assert polish_count[0] == 2

    def test_brief_fix_skips_turned_down_scenes_and_empty_commits(self, tmp_path, monkeypatch):
        """A scene whose brief fix was turned down is not sent again, and an
        iteration that fixed nothing commits nothing."""
        from storyforge.cmd_revise import _run_polish_loop

        project_dir = self._setup_project(tmp_path)

        call_count = [0]
        def fake_deterministic(proj, scene_ids):
            call_count[0] += 1
            cycle_dir = os.path.join(proj, 'working', 'scores', f'cycle-{call_count[0]}')
            os.makedirs(cycle_dir, exist_ok=True)
            return cycle_dir, self._make_diag(high=1, avg=3.0)

        sent = []
        def fake_fix(proj, ids):
            sent.append(list(ids))
            return [], {sid: 'named Mallen' for sid in ids}

        commits = []
        monkeypatch.setattr('storyforge.cmd_revise._run_deterministic_score', fake_deterministic)
        monkeypatch.setattr('storyforge.cmd_revise._detect_upstream_scenes',
                            lambda p, diag: ['s01'] if len(sent) == 0 else ['s01', 's02'])
        monkeypatch.setattr('storyforge.cmd_revise._fix_and_redraft', fake_fix)
        monkeypatch.setattr('storyforge.cmd_revise._execute_single_pass', lambda *a, **kw: None)
        monkeypatch.setattr('storyforge.cmd_revise.create_branch', lambda *a: None)
        monkeypatch.setattr('storyforge.cmd_revise.ensure_branch_pushed', lambda *a: None)
        monkeypatch.setattr('storyforge.git.commit_and_push',
                            lambda p, msg, *a, **kw: commits.append(msg) or True)
        monkeypatch.setattr('storyforge.cmd_revise.create_draft_pr',
                            lambda title, body, pd, work_type='': '')
        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body', lambda pd, pr: '')
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', lambda pd, pr, b: None)
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment', lambda pd, pr, body: None)

        _run_polish_loop(project_dir, 5, None, skip_final_score=True)

        assert sent == [['s01'], ['s02']]
        assert not any('upstream' in m for m in commits)

    def test_zero_max_loops_no_crash(self, tmp_path, monkeypatch):
        """max_loops=0 should not crash even with skip_final_score=True."""
        from storyforge.cmd_revise import _run_polish_loop

        project_dir = self._setup_project(tmp_path)

        monkeypatch.setattr('storyforge.cmd_revise.create_branch', lambda *a: None)
        monkeypatch.setattr('storyforge.cmd_revise.ensure_branch_pushed', lambda *a: None)
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **kw: True)
        monkeypatch.setattr('storyforge.cmd_revise.create_draft_pr',
                            lambda title, body, pd, work_type='': '')
        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body', lambda pd, pr: '')
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', lambda pd, pr, b: None)
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment', lambda pd, pr, body: None)

        # Should not raise NameError
        _run_polish_loop(project_dir, 0, None, skip_final_score=True)

    def test_skip_initial_score_exits_on_empty_diagnosis(self, tmp_path, monkeypatch):
        """--skip-initial-score with no diagnosis.csv should error, not silently converge."""
        from storyforge.cmd_revise import _run_polish_loop

        project_dir = self._setup_project(tmp_path)

        # Create a latest dir with no diagnosis.csv
        latest_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
        os.makedirs(latest_dir, exist_ok=True)

        monkeypatch.setattr('storyforge.cmd_revise.create_branch', lambda *a: None)
        monkeypatch.setattr('storyforge.cmd_revise.ensure_branch_pushed', lambda *a: None)
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **kw: True)
        monkeypatch.setattr('storyforge.cmd_revise.create_draft_pr',
                            lambda title, body, pd, work_type='': '')
        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body', lambda pd, pr: '')
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', lambda pd, pr, b: None)
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment', lambda pd, pr, body: None)

        with pytest.raises(SystemExit):
            _run_polish_loop(project_dir, 3, None, skip_initial_score=True)

    def test_creates_pr_with_initial_scores(self, tmp_path, monkeypatch):
        """Loop should create a draft PR after initial scoring."""
        from storyforge.cmd_revise import _run_polish_loop

        project_dir = self._setup_project(tmp_path)
        pr_calls = {'create': [], 'comment': []}

        converged_diag = self._make_diag(high=0, medium=0, avg=4.5)

        def fake_deterministic(proj, scene_ids):
            cycle_dir = os.path.join(proj, 'working', 'scores', 'cycle-1')
            os.makedirs(cycle_dir, exist_ok=True)
            return cycle_dir, converged_diag

        monkeypatch.setattr('storyforge.cmd_revise._run_deterministic_score', fake_deterministic)
        monkeypatch.setattr('storyforge.cmd_revise._run_lightweight_score',
                            lambda p, s: ('', converged_diag))
        monkeypatch.setattr('storyforge.cmd_revise.create_branch', lambda *a: 'storyforge/revise-test')
        monkeypatch.setattr('storyforge.cmd_revise.ensure_branch_pushed', lambda *a: None)
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **kw: True)
        monkeypatch.setattr('storyforge.cmd_revise.create_draft_pr',
                            lambda title, body, pd, work_type='': pr_calls['create'].append(body) or '99')
        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body', lambda pd, pr: '')
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', lambda pd, pr, b: None)
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment',
                            lambda pd, pr, body: pr_calls['comment'].append(body))

        _run_polish_loop(project_dir, 3, None)

        # PR was created
        assert len(pr_calls['create']) == 1
        pr_body = pr_calls['create'][0]
        assert 'Initial Deterministic Scores' in pr_body
        assert '- [x] Initial deterministic scoring' in pr_body

        # Final comment was posted
        assert len(pr_calls['comment']) == 1
        assert 'Deterministic Score Changes' in pr_calls['comment'][0]

    def test_updates_pr_body_each_iteration(self, tmp_path, monkeypatch):
        """Loop should update PR body after each polish iteration."""
        from storyforge.cmd_revise import _run_polish_loop

        project_dir = self._setup_project(tmp_path)
        body_updates = []

        call_count = [0]
        def fake_deterministic(proj, scene_ids):
            call_count[0] += 1
            cycle_dir = os.path.join(proj, 'working', 'scores', f'cycle-{call_count[0]}')
            os.makedirs(cycle_dir, exist_ok=True)
            if call_count[0] == 1:
                return cycle_dir, self._make_diag(high=1, avg=2.0)
            return cycle_dir, self._make_diag(high=0, medium=0, avg=4.5)

        def fake_set_body(pd, pr, body):
            body_updates.append(body)

        monkeypatch.setattr('storyforge.cmd_revise._run_deterministic_score', fake_deterministic)
        monkeypatch.setattr('storyforge.cmd_revise._run_lightweight_score',
                            lambda p, s: ('', self._make_diag(high=0, avg=4.5)))
        monkeypatch.setattr('storyforge.cmd_revise._execute_single_pass',
                            lambda *a, **kw: None)
        monkeypatch.setattr('storyforge.cmd_revise.create_branch', lambda *a: 'storyforge/revise-test')
        monkeypatch.setattr('storyforge.cmd_revise.ensure_branch_pushed', lambda *a: None)
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **kw: True)
        monkeypatch.setattr('storyforge.cmd_revise.create_draft_pr',
                            lambda title, body, pd, work_type='': '99')
        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body',
                            lambda pd, pr: '## Progress\n\n- [x] Initial deterministic scoring\n')
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', fake_set_body)
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment', lambda pd, pr, body: None)

        _run_polish_loop(project_dir, 3, None)

        # At least one body update (iteration 1 converged after re-score)
        assert len(body_updates) >= 1
        assert any('Iteration' in u for u in body_updates)


class TestFormatScoresTable:
    def test_formats_principles_as_markdown_table(self):
        from storyforge.cmd_revise import _format_scores_table

        diag_rows = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01;s03', 'priority': 'high'},
            {'principle': 'avoid_adverbs', 'scale': 'scene', 'avg_score': '3.5',
             'worst_items': 's02', 'priority': 'medium'},
            {'principle': 'economy_clarity', 'scale': 'scene', 'avg_score': '4.2',
             'worst_items': '', 'priority': 'low'},
        ]

        table = _format_scores_table(diag_rows)
        assert '| Principle' in table
        assert '| avoid passive' in table
        assert '| 2.10' in table
        assert '| high' in table
        # Low priority still shown
        assert '| economy clarity' in table

    def test_empty_diag_returns_no_issues(self):
        from storyforge.cmd_revise import _format_scores_table
        table = _format_scores_table([])
        assert 'No issues' in table

    def test_only_scene_scale_included(self):
        from storyforge.cmd_revise import _format_scores_table

        diag_rows = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high'},
            {'principle': 'genre_contract', 'scale': 'act', 'avg_score': '1.5',
             'worst_items': '', 'priority': 'high'},
        ]
        table = _format_scores_table(diag_rows)
        assert 'avoid passive' in table
        assert 'genre contract' not in table


class TestBuildPolishPrBody:
    def test_contains_initial_scores_table(self):
        from storyforge.cmd_revise import _build_polish_pr_body

        diag_rows = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high'},
        ]
        body = _build_polish_pr_body('Test Novel', 5, 3, diag_rows)
        assert '## Initial Deterministic Scores' in body
        assert 'avoid passive' in body
        assert '2.10' in body

    def test_contains_task_checklist(self):
        from storyforge.cmd_revise import _build_polish_pr_body

        diag_rows = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high'},
        ]
        body = _build_polish_pr_body('Test Novel', 5, 3, diag_rows)
        assert '- [x] Initial deterministic scoring' in body
        assert '## Progress' in body

    def test_contains_metadata(self):
        from storyforge.cmd_revise import _build_polish_pr_body

        body = _build_polish_pr_body('My Novel', 10, 5, [])
        assert 'My Novel' in body
        assert '10 scenes' in body
        assert '5 max iterations' in body


class TestUpdatePrBodyIteration:
    def test_appends_iteration_line(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _update_pr_body_iteration

        project_dir = str(tmp_path)
        existing_body = (
            '## Progress\n\n'
            '- [x] Initial deterministic scoring\n'
        )

        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body',
                            lambda pd, pr: existing_body)
        captured = {}
        def fake_set(pd, pr, body):
            captured['body'] = body
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', fake_set)

        summary = {'overall_avg': 3.5, 'high_count': 1, 'medium_count': 0,
                   'high_principles': ['avoid_passive'], 'medium_principles': [],
                   'scene_principle_count': 3}
        _update_pr_body_iteration(project_dir, '42', 1, summary)

        assert '- [x] Iteration 1' in captured['body']
        assert 'avg 3.50' in captured['body']
        assert '1 high' in captured['body']

    def test_no_op_without_pr_number(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _update_pr_body_iteration

        # Should not raise
        _update_pr_body_iteration(str(tmp_path), '', 1,
                                  {'overall_avg': 0, 'high_count': 0, 'medium_count': 0,
                                   'high_principles': [], 'medium_principles': [],
                                   'scene_principle_count': 0})

    def test_appends_convergence_line(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _update_pr_body_iteration

        project_dir = str(tmp_path)
        existing_body = (
            '## Progress\n\n'
            '- [x] Initial deterministic scoring\n'
            '- [x] Iteration 1 — avg 3.50, 1 high / 0 medium\n'
        )

        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body',
                            lambda pd, pr: existing_body)
        captured = {}
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body',
                            lambda pd, pr, body: captured.update({'body': body}))

        summary = {'overall_avg': 4.0, 'high_count': 0, 'medium_count': 0,
                   'high_principles': [], 'medium_principles': [],
                   'scene_principle_count': 3}
        _update_pr_body_iteration(project_dir, '42', 2, summary, converged=True)

        assert '- [x] Iteration 2' in captured['body']
        assert 'converged' in captured['body'].lower()


class TestPostPolishSummaryComment:
    def test_posts_comparison_comment(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _post_polish_summary_comment

        project_dir = str(tmp_path)
        captured = {}
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment',
                            lambda pd, pr, body: captured.update({'body': body}))

        baseline_diag = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high'},
        ]
        final_det_diag = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '3.8',
             'worst_items': 's01', 'priority': 'low'},
        ]
        final_llm_diag = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '3.5',
             'worst_items': 's01', 'priority': 'low'},
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '3.0',
             'worst_items': 's01', 'priority': 'medium'},
        ]

        _post_polish_summary_comment(project_dir, '42',
                                     baseline_diag, final_det_diag,
                                     final_llm_diag=final_llm_diag)

        body = captured['body']
        assert '## Deterministic Score Changes' in body
        assert 'avoid passive' in body
        assert '2.10' in body  # baseline
        assert '3.80' in body  # final
        assert '## Full LLM Scores' in body
        assert 'prose naturalness' in body

    def test_skips_llm_section_when_none(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _post_polish_summary_comment

        project_dir = str(tmp_path)
        captured = {}
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment',
                            lambda pd, pr, body: captured.update({'body': body}))

        baseline = [{'principle': 'avoid_passive', 'scale': 'scene',
                     'avg_score': '2.1', 'worst_items': '', 'priority': 'high'}]
        final = [{'principle': 'avoid_passive', 'scale': 'scene',
                  'avg_score': '3.5', 'worst_items': '', 'priority': 'low'}]

        _post_polish_summary_comment(project_dir, '42', baseline, final)

        body = captured['body']
        assert '## Deterministic Score Changes' in body
        assert '## Full LLM Scores' not in body

    def test_no_op_without_pr_number(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _post_polish_summary_comment
        # Should not raise
        _post_polish_summary_comment(str(tmp_path), '', [], [])


class TestPolishLoopForecast:
    """#503 left `--polish --loop` with no up-front forecast: it spent on
    passes unchecked, and that spend came out of its own re-checks' budget.
    Costs here: a pass $2, a scene's brief fix and redraft $3, the full
    score $5."""

    H = TestPolishLoopOrchestration()

    def _setup(self, tmp_path, monkeypatch, diags, threshold, upstream=(), charge=0.0,
               fix_charge=0.0):
        """`upstream`: the scenes `_detect_upstream_scenes` finds, or a
        function of how many times it was called."""
        from storyforge import cmd_revise
        from storyforge.costs import RunBudget
        project_dir = self.H._setup_project(tmp_path)
        self.H._patch_loop(monkeypatch, diags[0])
        scores = iter(diags)
        last = [diags[0]]

        def fake_deterministic(proj, scene_ids):
            last[0] = next(scores, last[0])
            return '', last[0]
        monkeypatch.setattr(cmd_revise, '_run_deterministic_score', fake_deterministic)
        budget = RunBudget()
        monkeypatch.setattr(cmd_revise, '_RUN_BUDGET', budget)
        monkeypatch.setattr(cmd_revise, '_pass_cost', lambda p, m: 2.0)
        monkeypatch.setattr(cmd_revise, '_upstream_fix_cost', lambda p, ids: 3.0 * len(ids))
        monkeypatch.setattr(cmd_revise, 'estimate_cost', lambda op, n, w, m: 5.0)
        found = [0]

        def detect(p, d):
            found[0] += 1
            return list(upstream(found[0]) if callable(upstream) else upstream)
        monkeypatch.setattr(cmd_revise, '_detect_upstream_scenes', detect)
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', str(threshold))
        events, commits, branches = [], [], []
        self.prs, self.bodies, self.comments = [], [], []

        def fake_execute(proj, plan_file, rows, iteration, model_override=None):
            events.append(('pass', iteration, budget.owed))
            budget.charge(charge)   # what the pass cost

        def fake_fix(proj, ids):
            events.append(('fix', list(ids), budget.owed))
            budget.charge(fix_charge)
            return [], {sid: 'turned down' for sid in ids}

        def fake_score(proj, ids):
            events.append(('score',))
            return '', diags[-1]
        monkeypatch.setattr(cmd_revise, '_execute_single_pass', fake_execute)
        monkeypatch.setattr(cmd_revise, '_fix_and_redraft', fake_fix)
        monkeypatch.setattr(cmd_revise, '_run_lightweight_score', fake_score)
        monkeypatch.setattr(cmd_revise, 'create_branch', lambda *a: branches.append(a))
        monkeypatch.setattr('storyforge.git.commit_and_push',
                            lambda p, msg, *a, **k: commits.append(msg) or True)
        monkeypatch.setattr(cmd_revise, 'create_draft_pr',
                            lambda title, body, pd, work_type='': self.prs.append(title) or '7')
        monkeypatch.setattr(cmd_revise, 'get_pr_body', lambda pd, pr: 'body')
        monkeypatch.setattr(cmd_revise, 'set_pr_body', lambda pd, pr, b: self.bodies.append(b))
        monkeypatch.setattr(cmd_revise, 'add_pr_comment',
                            lambda pd, pr, body: self.comments.append(body))
        return project_dir, events, commits, branches

    def test_over_the_threshold_up_front_it_spends_nothing(
            self, tmp_path, monkeypatch, capsys):
        from storyforge.cmd_revise import _run_polish_loop
        high = self.H._make_diag(high=1)
        project_dir, events, commits, branches = self._setup(
            tmp_path, monkeypatch, [high], 13.5, upstream=['s01'])
        with pytest.raises(SystemExit) as e:
            _run_polish_loop(project_dir, 3, None)
        assert e.value.code == 1
        assert events == [] and commits == [] and branches == []
        assert self.prs == []   # T-6: no draft PR
        out = capsys.readouterr().out
        # every iteration, the brief fix known now, the full score (C-3)
        assert 'Cost forecast: ~$14.00 for up to 3 iterations @ ~$2.00' in out
        assert 'Not in it: the gate on each scene a pass rewrites' in out
        # SF-8: each way that can bring it under
        assert 'the forecast (~$14.00) is over the cost threshold ($13.5): nothing ' \
            'revised. Raise STORYFORGE_COST_THRESHOLD, or lower `--max-loops` (~$2.00 an ' \
            'iteration), or add `--skip-final-score` (~$5.00), or fix the briefs of s01 ' \
            'first (`storyforge hone`, ~$3.00).' in out

    def test_a_refusal_takes_back_the_scores_it_wrote(self, tmp_path, monkeypatch, capsys):
        """SF-2: the refused loop left a scores cycle written and latest
        repointed at it, for --scores and --naturalness to plan from."""
        from storyforge import cmd_revise
        from storyforge.cmd_revise import _run_polish_loop
        high = self.H._make_diag(high=1)
        project_dir, _, _, _ = self._setup(tmp_path, monkeypatch, [high], 1)
        scores = os.path.join(project_dir, 'working', 'scores')
        os.makedirs(os.path.join(scores, 'cycle-1'))
        os.symlink('cycle-1', os.path.join(scores, 'latest'))

        def score(proj, ids):   # as `_run_deterministic_score` writes
            os.makedirs(os.path.join(scores, 'cycle-2'))
            os.remove(os.path.join(scores, 'latest'))
            os.symlink('cycle-2', os.path.join(scores, 'latest'))
            return os.path.join(scores, 'cycle-2'), high
        monkeypatch.setattr(cmd_revise, '_run_deterministic_score', score)
        with pytest.raises(SystemExit):
            _run_polish_loop(project_dir, 3, None)
        assert sorted(os.listdir(scores)) == ['cycle-1', 'latest']
        assert os.readlink(os.path.join(scores, 'latest')) == 'cycle-1'
        assert 'the deterministic scores it wrote, cycle-2, are removed' in \
            capsys.readouterr().out

    def test_within_it_runs_and_the_rechecks_get_what_is_left(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _run_polish_loop
        high, done = self.H._make_diag(high=1), self.H._make_diag(high=0)
        project_dir, events, commits, _ = self._setup(
            tmp_path, monkeypatch, [high, done], 14, upstream=['s01'])
        _run_polish_loop(project_dir, 3, None)
        # while the brief fix runs, this iteration's pass, the 2 after it and
        # the full score are kept from its re-checks; during the pass, the 2
        # after it and the full score
        assert events == [('fix', ['s01'], 2 + 2 * 2 + 5.0), ('pass', 1, 2 * 2 + 5.0),
                          ('score',)]

    def test_a_source_drift_fix_alone_reserves_only_the_full_score(
            self, tmp_path, monkeypatch):
        """T-5/TD-2 (#510's review): with the craft converged the loop ends
        after the fix, so its re-checks keep only the full score back, and
        the reservation is put back after."""
        from storyforge import cmd_revise
        from storyforge.cmd_revise import _run_polish_loop
        done = self.H._make_diag(high=0)
        project_dir, events, _, _ = self._setup(
            tmp_path, monkeypatch, [done], 14, upstream=['s01'])
        monkeypatch.setattr(cmd_revise, '_source_drift_scenes',
                            lambda p, quiet=False: {'s01': ['outcome']})
        _run_polish_loop(project_dir, 3, None)
        assert events == [('fix', ['s01'], 5.0), ('score',)]
        assert cmd_revise._RUN_BUDGET.owed == 0.0

    def test_skip_final_score_leaves_the_score_out(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _run_polish_loop
        high, done = self.H._make_diag(high=1), self.H._make_diag(high=0)
        project_dir, events, _, _ = self._setup(
            tmp_path, monkeypatch, [high, done], 9, upstream=['s01'])
        _run_polish_loop(project_dir, 3, None, skip_final_score=True)
        assert [e[0] for e in events] == ['fix', 'pass']

    def test_it_stops_before_an_iteration_that_would_pass_the_threshold(
            self, tmp_path, monkeypatch, capsys):
        from storyforge.cmd_revise import _run_polish_loop
        diags = [self.H._make_diag(high=1, avg=3.0), self.H._make_diag(high=1, avg=3.5)]
        # forecast 5 x $2 + $5 = $15; the first pass costs $14
        project_dir, events, commits, _ = self._setup(
            tmp_path, monkeypatch, diags, 20, charge=14.0)
        with pytest.raises(SystemExit) as e:
            _run_polish_loop(project_dir, 5, None)
        assert e.value.code == 1
        assert [e[:2] for e in events] == [('pass', 1)]
        assert commits[-1] == 'Polish: stopped at the cost threshold'
        out = capsys.readouterr().out
        assert 'ERROR: iteration 2 (~$2.00) and the full score after the loop (~$5.00): ' \
            'spent so far ~$14.00 + forecast ~$7.00 = ~$21.00 is over the cost threshold ' \
            '($20). Stopping before iteration 2' in out
        assert 're-run `storyforge revise --polish --loop`' in out
        # SF-9: the draft PR says so, as a finished loop's would
        assert self.bodies[-1].rstrip().endswith(
            '- [ ] Stopped before iteration 2 at the cost threshold: spent so far ~$14.00 '
            '+ forecast ~$7.00 = ~$21.00 is over the cost threshold ($20)')
        assert self.comments and self.comments[-1].startswith(
            '**Stopped before iteration 2 at the cost threshold')

    def test_brief_fixes_a_later_iteration_finds_are_in_its_check(
            self, tmp_path, monkeypatch, capsys):
        """T-1/SF-10: iteration 2's check counts the fix it found ($3)."""
        from storyforge.cmd_revise import _run_polish_loop
        diags = [self.H._make_diag(high=1, avg=3.0), self.H._make_diag(high=1, avg=3.5)]
        # up front 3 x $2 + $5 = $11; the first pass costs $6; then
        # $6 + $3 + $2 + $5 = $16 is over $15 only with the fix
        project_dir, events, _, _ = self._setup(
            tmp_path, monkeypatch, diags, 15, charge=6.0,
            upstream=lambda n: [] if n == 1 else ['s01'])
        with pytest.raises(SystemExit):
            _run_polish_loop(project_dir, 3, None)
        assert [e[0] for e in events] == ['pass']
        assert 'iteration 2 (~$5.00)' in capsys.readouterr().out

    def test_the_pass_is_checked_after_its_brief_fixes(self, tmp_path, monkeypatch, capsys):
        """CR-M1: fixes that cost more than forecast could overshoot by a pass."""
        from storyforge.cmd_revise import _run_polish_loop
        high = self.H._make_diag(high=1)
        # up front 3 x $2 + $3 + $5 = $14; the fix costs $9: $9 + $2 + $5 > $15
        project_dir, events, commits, _ = self._setup(
            tmp_path, monkeypatch, [high], 15, upstream=['s01'], fix_charge=9.0)
        with pytest.raises(SystemExit) as e:
            _run_polish_loop(project_dir, 3, None)
        assert e.value.code == 1
        assert [e[0] for e in events] == ['fix']
        assert commits[-1] == 'Polish: stopped at the cost threshold'
        assert "Stopping before iteration 1's pass" in capsys.readouterr().out

    def test_the_full_score_is_checked_before_it_runs(self, tmp_path, monkeypatch, capsys):
        from storyforge.cmd_revise import _run_polish_loop
        high, done = self.H._make_diag(high=1), self.H._make_diag(high=0)
        project_dir, events, commits, _ = self._setup(
            tmp_path, monkeypatch, [high, done], 20, charge=16.0)
        with pytest.raises(SystemExit) as e:
            _run_polish_loop(project_dir, 3, None)
        assert e.value.code == 1
        assert ('score',) not in events
        assert 'Polish: deterministic phase complete' in commits
        out = capsys.readouterr().out
        assert 'the full score (~$5.00): spent so far ~$16.00 + forecast ~$5.00 = ~$21.00' in out
        assert 'run `storyforge score` for it' in out
