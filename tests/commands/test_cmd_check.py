"""Tests for `storyforge check` (advisor mode) and the gate's fix pass.
The API is mocked at `api._api_request`: a request with tools is the
checker, one with the fix schema is the fix, any other is extraction."""

import json
import os
from unittest.mock import patch

import pytest

from storyforge import cmd_check, gate, ledger

SCENE = 'act1-sc02'
HERE = 'population four hundred and twelve at last census'
BAD = {'kind': 'contradiction', 'code': 'TIM', 'scene_quote': HERE,
       'established_scene': 'act1-sc01', 'fact_id': '', 'explanation': 'why',
       'established_quote': 'Dorren Hayle pressed the brass calipers against the vellum'}



@pytest.fixture(autouse=True)
def _pure_prose_scenes(request):
    """Scene files are pure prose (the gate refuses frontmatter); the shared
    fixture's older scenes still carry it."""
    if 'project_dir' not in request.fixturenames:
        return
    import glob
    import re as _re
    for path in glob.glob(os.path.join(request.getfixturevalue('project_dir'), 'scenes', '*.md')):
        with open(path, encoding='utf-8') as f:
            text = f.read()
        stripped = _re.sub(r'\A---\n.*?\n---\n\s*', '', text, flags=_re.S)
        if stripped != text:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(stripped)

def _text(payload):
    return {'stop_reason': 'end_turn', 'model': 'm', 'usage': {},
            'content': [{'type': 'text', 'text': json.dumps(payload)}]}


def _api(checks, edits=()):
    """A fake API: each check reply in turn (findings lists), the fix edits."""
    checks = list(checks)

    def fake(path, body, **k):
        if 'tools' in body:
            return _text({'findings': checks.pop(0), 'kept': []})
        if 'edits' in json.dumps(body.get('output_config', {})):
            return _text({'edits': list(edits)})
        return _text({'commitments': []})
    return patch('storyforge.api._api_request', side_effect=fake)


@pytest.fixture
def project(project_dir, monkeypatch):
    monkeypatch.setattr(cmd_check, 'detect_project_root', lambda: project_dir)
    monkeypatch.setattr('storyforge.git.create_branch', lambda *a: 'b')
    commits = []
    monkeypatch.setattr('storyforge.git.commit_and_push',
                        lambda d, msg, paths=None: commits.append((msg, paths)) or True)
    monkeypatch.setenv('STORYFORGE_MODEL', 'm')
    return project_dir, commits


class TestCheck:
    def test_a_clean_scene_passes_and_commits_its_facts(self, project):
        project_dir, commits = project
        with _api([[]]):
            cmd_check.main([SCENE])
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert f'## {SCENE}: passed' in report
        assert commits and 'reference/commitments.csv' in commits[0][1]

    def test_a_finding_is_reported_never_fixed_and_exits_1(self, project):
        project_dir, _ = project
        path = os.path.join(project_dir, 'scenes', f'{SCENE}.md')
        before_prose, before_ledger = open(path).read(), ledger.load(project_dir)
        with _api([[BAD]]), pytest.raises(SystemExit) as e:
            cmd_check.main([SCENE])
        assert e.value.code == 1
        assert open(path).read() == before_prose
        assert ledger.load(project_dir) == before_ledger
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert f'## {SCENE}: did not pass' in report and 'CONTRADICTION: TIM' in report

    def test_the_first_failure_stops_the_run_and_lists_the_rest(self, project):
        """Review of #441 (H1): later scenes would be checked, and committed,
        against a ledger without the failing scene's facts."""
        project_dir, _ = project
        with _api([[BAD], []]) as api, pytest.raises(SystemExit) as e:
            cmd_check.main(['--scenes', f'{SCENE},act2-sc01'])
        assert e.value.code == 1
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert 'Not checked: act2-sc01' in report
        assert sum('tools' in c.args[1] for c in api.call_args_list) == 1
        assert SCENE in gate.pending(project_dir)

    def test_a_gate_error_stops_the_run_too(self, project, monkeypatch):
        project_dir, _ = project

        def boom(*a, **k):
            raise gate.GateError('extraction failed:\nHTTP 500')
        monkeypatch.setattr(gate, 'gate_scene', boom)
        with pytest.raises(SystemExit):
            cmd_check.main(['--scenes', f'{SCENE},act2-sc01'])
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert f'## {SCENE}: not checked' in report and 'failed: HTTP 500' in report
        assert 'Not checked: act2-sc01' in report

    def test_scenes_are_checked_in_reading_order(self, project, monkeypatch):
        seen = []

        def record(project_dir, scene_id, **k):
            seen.append(scene_id)
            return gate.GateResult(scene_id, check=None)
        monkeypatch.setattr(gate, 'gate_scene', record)
        cmd_check.main(['--scenes', f'act2-sc01,{SCENE}'])
        assert seen == [SCENE, 'act2-sc01']

    def test_an_unknown_scene_is_an_error(self, project):
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--scenes', f'{SCENE},nope-sc99'])
        assert e.value.code == 1

    def test_a_failed_commit_exits_1(self, project, monkeypatch):
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **k: False)
        with _api([[]]), pytest.raises(SystemExit) as e:
            cmd_check.main([SCENE])
        assert e.value.code == 1

    def test_no_scenes_named_is_an_error(self, project):
        with pytest.raises(SystemExit) as e:
            cmd_check.main([])
        assert e.value.code == 1

    def test_a_non_numeric_cost_threshold_stops_before_anything(
            self, project, monkeypatch, capsys):
        """It crashed with a ValueError at the first threshold check."""
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', 'twenty')
        monkeypatch.setattr(gate, 'gate_scene', lambda *a, **k: pytest.fail('checked'))
        for argv in ([SCENE], ['--pending']):
            with pytest.raises(SystemExit) as e:
                cmd_check.main(argv)
            assert e.value.code == 1
            assert "ERROR: STORYFORGE_COST_THRESHOLD is 'twenty'" in capsys.readouterr().out


class TestPendingAndRecheck:
    """Phase 4: `--pending`, a re-check row keeps its prose's writer, and a
    scene that passes re-checks what it listed."""

    def test_pending_checks_every_waiting_scene_in_reading_order(self, project, monkeypatch):
        project_dir, _ = project
        gate.mark_pending(project_dir, 'act2-sc01', 'recheck', 'x')
        gate.mark_pending(project_dir, SCENE, 'draft', 'y')
        gate.mark_pending(project_dir, 'deleted-scene', 'draft', 'z')
        seen = []

        def record(project_dir, scene_id, *, command, introduced_by=None, **k):
            seen.append((scene_id, command, introduced_by))
            gate.clear_pending(project_dir, scene_id)
            r = gate.GateResult(scene_id, check=None)
            r.committed = True
            return r
        monkeypatch.setattr(gate, 'gate_scene', record)
        monkeypatch.setattr(gate, '_writer', lambda pd, sid: 'draft')
        cmd_check.main(['--pending'])
        assert seen == [(SCENE, 'advisor', None), ('act2-sc01', 'recheck', 'draft')]

    def test_pending_with_scenes_named_is_an_error(self, project):
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--pending', SCENE])
        assert e.value.code == 1

    def test_pending_over_the_cost_threshold_checks_nothing(self, project, monkeypatch):
        project_dir, _ = project
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '0.1')
        gate.mark_pending(project_dir, SCENE, 'draft', 'y')
        monkeypatch.setattr(gate, 'gate_scene', lambda *a, **k: pytest.fail('checked'))
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--pending'])
        assert e.value.code == 1

    def test_nothing_pending_is_said(self, project, capsys):
        cmd_check.main(['--pending'])
        assert 'Nothing is waiting on the gate' in capsys.readouterr().out

    def test_a_failed_recheck_before_the_next_scene_stops_the_run(self, project, monkeypatch):
        project_dir, _ = project
        seen = []

        def record(project_dir, scene_id, **k):
            seen.append(scene_id)
            r = gate.GateResult(scene_id, check=None)
            r.committed = True
            return r
        monkeypatch.setattr(gate, 'gate_scene', record)
        monkeypatch.setattr(gate, 'recheck_queue', lambda pd, skip=frozenset(): ['new-x1'])
        monkeypatch.setattr(gate, 'recheck_pending', lambda pd, **k: gate.Recheck(
            failed='new-x1', why='a contradiction', left=['new-x1']))
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--scenes', f'{SCENE},act2-sc01'])
        assert e.value.code == 1 and seen == [SCENE]
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert 're-check of new-x1 did not pass' in report and 'Not checked: act2-sc01' in report


    def _passing(self, monkeypatch, seen):
        def record(project_dir, scene_id, **k):
            seen.append((scene_id, k.get('command')))
            r = gate.GateResult(scene_id, check=None)
            r.committed = True
            return r
        monkeypatch.setattr(gate, 'gate_scene', record)

    def test_a_failed_recheck_after_the_last_scene_exits_1(self, project, monkeypatch):
        project_dir, _ = project
        self._passing(monkeypatch, [])
        monkeypatch.setattr(gate, 'recheck_queue', lambda pd, skip=frozenset(): ['act2-sc01'])
        monkeypatch.setattr(gate, 'recheck_pending', lambda pd, **k: gate.Recheck(
            failed='act2-sc01', why='a contradiction'))
        with pytest.raises(SystemExit) as e:
            cmd_check.main([SCENE])
        assert e.value.code == 1

    def test_a_failed_recheck_after_the_next_scene_does_not_stop_the_run(
            self, project, monkeypatch):
        project_dir, _ = project
        seen = []
        self._passing(monkeypatch, seen)
        calls = []

        def queue(pd, skip=frozenset()):
            return [] if calls else ['act2-sc01']

        def recheck(pd, **k):
            calls.append(1)
            return gate.Recheck(failed='act2-sc01', why='x')
        monkeypatch.setattr(gate, 'recheck_queue', queue)
        monkeypatch.setattr(gate, 'recheck_pending', recheck)
        with pytest.raises(SystemExit):
            cmd_check.main(['--scenes', f'act1-sc01,{SCENE}'])
        assert [s for s, _ in seen] == ['act1-sc01', SCENE]   # SCENE is before act2-sc01

    def test_over_budget_is_said_as_not_run(self, project, monkeypatch, capsys):
        project_dir, _ = project
        self._passing(monkeypatch, [])
        monkeypatch.setattr(gate, 'recheck_queue', lambda pd, skip=frozenset(): ['new-x1'])
        monkeypatch.setattr(gate, 'recheck_pending', lambda pd, **k: gate.Recheck(
            over_budget=True, left=['new-x1'], forecast=200.0))
        with pytest.raises(SystemExit):
            cmd_check.main(['--scenes', f'{SCENE},act2-sc01'])
        out = capsys.readouterr().out
        assert 'stopped at new-x1, which was not re-checked (over the cost threshold)' in out

    def test_a_failing_recheck_scene_stays_listed_as_a_recheck(self, project, monkeypatch):
        project_dir, _ = project
        gate.mark_pending(project_dir, 'act2-sc01', gate.RECHECK_FAILED, 'x')
        monkeypatch.setattr(gate, '_writer', lambda pd, sid: 'draft')
        with _api([[BAD]]), pytest.raises(SystemExit):
            cmd_check.main(['--pending'])
        assert gate.pending(project_dir)['act2-sc01']['command'] == gate.RECHECK_FAILED


def _finding(kind='contradiction'):
    from storyforge.checker import Finding
    return Finding(kind=kind, code='TIM', scene_quote=HERE, established_scene='act1-sc01',
                   established_quote='y', fact_id='', explanation='why')


def _fake_gate(monkeypatch, outcomes, spend=0):
    """`gate.gate_scene` passing every scene but those in `outcomes`: a
    Finding fails with it (recorded for --accept as the real gate does), a
    string raises a GateError. `spend` output tokens of Opus 4.6 are metered
    per scene. Returns the scenes gated, in order."""
    from storyforge import api
    from storyforge.checker import CheckResult
    seen = []

    def fake(project_dir, scene_id, *, command, introduced_by=None, **k):
        seen.append(scene_id)
        if spend:
            api._meter({'usage': {'input_tokens': 0, 'output_tokens': spend}},
                       'claude-opus-4-6')
        outcome = outcomes.get(scene_id)
        if isinstance(outcome, str):
            raise gate.GateError(outcome)
        if outcome is not None:
            r = gate.GateResult(scene_id, check=CheckResult(scene_id, findings=[outcome]))
            gate._note_blocked(project_dir, scene_id, command, r)
            return r
        gate.clear_pending(project_dir, scene_id)
        r = gate.GateResult(scene_id, check=None)
        r.committed = True
        return r
    monkeypatch.setattr(gate, 'gate_scene', fake)
    monkeypatch.setattr(gate, '_writer', lambda pd, sid: 'draft')
    return seen


class TestKeepGoing:
    """`check --pending --keep-going`: one decision per run, not per paid
    stop. Every pending scene is checked in reading order; each failure
    stays pending (and acceptable); a summary names them all with the
    exact --accept command; exit 1 if any failed."""

    def _pend(self, project_dir, *ids):
        for sid in ids:
            gate.mark_pending(project_dir, sid, 'draft', 'stale')

    def test_every_scene_is_checked_and_each_failure_stays_pending(
            self, project, monkeypatch, capsys):
        project_dir, commits = project
        self._pend(project_dir, 'act2-sc01', 'act1-sc01', SCENE)
        seen = _fake_gate(monkeypatch, {'act1-sc01': _finding(), 'act2-sc01': _finding()})
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--pending', '--keep-going'])
        assert e.value.code == 1
        assert seen == ['act1-sc01', SCENE, 'act2-sc01']       # reading order, all of them
        waiting = gate.pending(project_dir)
        assert set(waiting) == {'act1-sc01', 'act2-sc01'}       # SCENE passed and came off
        assert set(gate.blocked(project_dir)) == {'act1-sc01', 'act2-sc01'}
        out = capsys.readouterr().out
        assert '1 of 3 scene(s) checked passed.' in out
        assert 'CONTRADICTION: TIM' in out
        assert '`storyforge check --accept act1-sc01,act2-sc01`' in out
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert '## Summary' in report and 'check --accept act1-sc01,act2-sc01' in report
        assert 'Not checked' not in report
        assert commits and commits[-1][0] == 'Check: 1 of 3 scene(s) passed'

    def test_results_after_a_failure_are_provisional(self, project, monkeypatch, capsys):
        project_dir, _ = project
        self._pend(project_dir, 'act1-sc01', SCENE, 'act2-sc01')
        _fake_gate(monkeypatch, {'act1-sc01': _finding(), 'act2-sc01': _finding()})
        with pytest.raises(SystemExit):
            cmd_check.main(['--pending', '--keep-going'])
        out = capsys.readouterr().out
        assert f'{SCENE}: passed (provisional: act1-sc01, earlier, has not passed)' in out
        assert 'Provisional: act1-sc02, act2-sc01 were checked after a scene earlier in the ' \
            'book that had not passed' in out
        assert f'{SCENE} passed and committed their facts meanwhile' in out
        assert 'act2-sc01: (provisional: checked while act1-sc01 had not passed)' in out

    def test_a_scene_with_nothing_to_accept_is_named_apart(self, project, monkeypatch, capsys):
        """--accept errors on a scene with nothing recorded (and accepts
        nothing), so the command lists only scenes it would work on."""
        project_dir, _ = project
        self._pend(project_dir, 'act1-sc01', SCENE, 'act2-sc01')
        _fake_gate(monkeypatch, {'act1-sc01': 'extraction failed: HTTP 500',
                                 SCENE: _finding('broken-promise'),
                                 'act2-sc01': _finding()})
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--pending', '--keep-going'])
        assert e.value.code == 1
        out = capsys.readouterr().out
        assert 'could not be checked: extraction failed: HTTP 500' in out
        assert '`storyforge check --accept act2-sc01`' in out
        assert f'Nothing to accept for act1-sc01, {SCENE}' in out
        assert set(gate.pending(project_dir)) == {'act1-sc01', SCENE, 'act2-sc01'}

    def test_accept_then_keep_going_again_passes(self, project, monkeypatch, capsys):
        project_dir, _ = project
        self._pend(project_dir, 'act1-sc01', 'act2-sc01')
        _fake_gate(monkeypatch, {'act1-sc01': _finding(), 'act2-sc01': _finding()})
        with pytest.raises(SystemExit):
            cmd_check.main(['--pending', '--keep-going'])
        cmd_check.main(['--accept', 'act1-sc01,act2-sc01'])
        assert gate.blocked(project_dir) == {}
        _fake_gate(monkeypatch, {})
        cmd_check.main(['--pending', '--keep-going'])           # all pass: exit 0
        assert gate.pending(project_dir) == {}
        assert '2 of 2 scene(s) checked passed.' in capsys.readouterr().out

    def test_a_failed_recheck_does_not_stop_the_run(self, project, monkeypatch, capsys):
        project_dir, _ = project
        self._pend(project_dir, 'act1-sc01', 'act2-sc01')
        seen = _fake_gate(monkeypatch, {})
        calls = []

        def queue(pd, skip=frozenset()):
            return [] if calls else ['new-x1']

        def recheck(pd, **k):
            calls.append(1)
            gate.mark_pending(pd, 'new-x1', gate.RECHECK_FAILED, 'x')
            return gate.Recheck(failed='new-x1', why='a contradiction')
        monkeypatch.setattr(gate, 'recheck_queue', queue)
        monkeypatch.setattr(gate, 'recheck_pending', recheck)
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--pending', '--keep-going'])
        assert e.value.code == 1
        assert seen == ['act1-sc01', 'act2-sc01']    # the stop-at-first run stops here
        out = capsys.readouterr().out
        assert 'new-x1 (re-checked after act1-sc01 passed): a contradiction' in out

    def test_keep_going_needs_pending(self, project):
        for argv in (['--keep-going', SCENE], ['--keep-going']):
            with pytest.raises(SystemExit) as e:
                cmd_check.main(argv)
            assert e.value.code == 1

    def test_over_the_threshold_up_front_checks_nothing(self, project, monkeypatch):
        project_dir, _ = project
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '1')
        self._pend(project_dir, 'act1-sc01', SCENE)
        seen = _fake_gate(monkeypatch, {})
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--pending', '--keep-going'])
        assert e.value.code == 1 and seen == []

    def test_the_run_stops_when_its_spend_reaches_the_threshold(
            self, project, monkeypatch, capsys):
        """One budget across the run: the forecast was within it, but the
        first scene actually cost more, so the rest would go over."""
        project_dir, _ = project
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '3')
        self._pend(project_dir, 'act1-sc01', SCENE, 'act2-sc01')
        assert 3 * gate.RECHECK_COST_PER_SCENE <= 3
        seen = _fake_gate(monkeypatch, {}, spend=80_000)   # $2.00 a scene
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--pending', '--keep-going'])
        assert e.value.code == 1
        assert seen == ['act1-sc01']
        assert set(gate.pending(project_dir)) == {SCENE, 'act2-sc01'}
        out = capsys.readouterr().out
        assert f'checking {SCENE} and the 1 scene(s) after it would bring this run to about ' \
            in out and 'over the cost threshold ($3): stopped' in out
        assert f'not checked, still pending: {SCENE}, act2-sc01' in out


class TestOneBudget:
    def test_rechecks_get_what_the_checks_spent_and_the_rest_leave(
            self, project, monkeypatch):
        """check's re-checks were told the run had spent only their own
        forecast: the scenes it checked didn't count."""
        from storyforge import api
        seen = []
        _fake_gate(monkeypatch, {}, spend=40_000)          # $1.00 a scene
        monkeypatch.setattr(gate, 'recheck_queue', lambda pd, skip=frozenset(): ['new-x1'])

        def recheck(pd, *, spent_before=0.0, **k):
            seen.append(spent_before)
            return gate.Recheck(spent=spent_before, spent_before=spent_before)
        monkeypatch.setattr(gate, 'recheck_pending', recheck)
        cmd_check.main(['--scenes', f'act1-sc01,{SCENE}'])
        one = api.calculate_cost_from_usage({'input_tokens': 0, 'output_tokens': 40_000},
                                            'claude-opus-4-6')
        per = gate.RECHECK_COST_PER_SCENE
        assert seen == [pytest.approx(one + per), pytest.approx(2 * one)]


class TestFix:
    def test_apply_edits(self):
        assert gate.apply_edits('a b c', [{'find': 'b', 'replace': 'B'},
                                          {'find': 'c', 'replace': 'C'}]) == 'a B C'

    @pytest.mark.parametrize('edits, why', [
        ([{'find': 'x', 'replace': 'y'}], 'occurs 0 times'),
        ([{'find': 'a', 'replace': 'y'}], 'occurs 2 times'),
        ([{'find': 'a b', 'replace': ''}, {'find': 'b c', 'replace': ''}], 'overlap'),
    ])
    def test_apply_edits_refuses(self, edits, why):
        with pytest.raises(gate.GateError, match=why):
            gate.apply_edits('a b c a', edits)

    def test_a_failing_scene_is_fixed_once_and_rechecked(self, project_dir, tmp_path):
        prose = open(os.path.join(project_dir, 'scenes', f'{SCENE}.md')).read()
        edit = {'problem': 1, 'find': HERE, 'replace': 'population four hundred at last census'}
        with _api([[BAD], []], [edit]):
            out = gate.gate_and_fix(project_dir, SCENE, command='draft', prose=prose,
                                    log_dir=str(tmp_path), extract_model='m',
                                    check_model='m', fix_model='m')
        assert out.fixed and out.result.passed and out.result.committed
        assert not out.first.passed
        assert 'four hundred at last census' in out.prose

    def test_still_failing_after_the_fix_commits_nothing(self, project_dir, tmp_path):
        prose = open(os.path.join(project_dir, 'scenes', f'{SCENE}.md')).read()
        before = ledger.load(project_dir)
        with _api([[BAD], [BAD]], []):
            out = gate.gate_and_fix(project_dir, SCENE, command='draft', prose=prose,
                                    log_dir=str(tmp_path), extract_model='m',
                                    check_model='m', fix_model='m')
        assert not out.result.passed and not out.fixed
        assert ledger.load(project_dir) == before

    def test_a_fix_with_no_edits_is_not_regated(self, project_dir, tmp_path):
        """Review of #441 (M2): re-checking identical prose is a paid re-roll
        that could commit what the first check rejected."""
        prose = open(os.path.join(project_dir, 'scenes', f'{SCENE}.md')).read()
        with _api([[BAD], []], []) as api:
            out = gate.gate_and_fix(project_dir, SCENE, command='draft', prose=prose,
                                    log_dir=str(tmp_path), extract_model='m',
                                    check_model='m', fix_model='m')
        assert out.result is out.first and not out.result.passed
        assert sum('tools' in c.args[1] for c in api.call_args_list) == 1

    def test_a_failing_fix_keeps_the_first_runs_findings(self, project_dir, tmp_path):
        prose = open(os.path.join(project_dir, 'scenes', f'{SCENE}.md')).read()
        with _api([[BAD]], [{'problem': 1, 'find': 'not in the scene', 'replace': 'x'}]), \
                pytest.raises(gate.GateError) as e:
            gate.gate_and_fix(project_dir, SCENE, command='draft', prose=prose,
                              log_dir=str(tmp_path), extract_model='m',
                              check_model='m', fix_model='m')
        assert e.value.first.findings[0].code == 'TIM'

    def test_two_rounds_through_the_real_fix(self, tmp_path):
        """T-2 (#482): the second fix's prompt carries the first's edits, and the
        edits reach the rounds, through the real fix_scene and prompt."""
        from storyforge.checker import CheckResult, Finding
        bad = lambda q: gate.GateResult(SCENE, check=CheckResult(SCENE, findings=[
            Finding('contradiction', 'TIM', q, 'act1-sc01', 'e', '', 'why')]))
        runs = iter([bad('eight days'), bad('five days'), gate.GateResult(SCENE)])
        replies = iter([[{'problem': 1, 'find': 'eight days', 'replace': 'five days'}],
                        [{'problem': 1, 'find': 'five days', 'replace': 'three days'}]])
        prompts = []

        def fake(path, body, **k):
            prompts.append(body['messages'][0]['content'] if isinstance(
                body['messages'][0]['content'], str)
                else body['messages'][0]['content'][0]['text'])
            return _text({'edits': next(replies)})
        with patch.object(gate, 'gate_scene', lambda *a, **k: next(runs)), \
                patch.object(gate, '_brief_phrases', lambda *a: []), \
                patch('storyforge.api._api_request', side_effect=fake):
            out = gate.gate_and_fix('p', SCENE, command='draft', prose='It took eight days.',
                                    log_dir=str(tmp_path), fix_model='m')
        assert out.result.passed and out.prose == 'It took three days.'
        assert '## Earlier fixes' not in prompts[0]
        assert '- "eight days" became "five days"' in prompts[1]
        assert out.rounds[0].edits == [{'problem': 1, 'find': 'eight days',
                                        'replace': 'five days'}]

    def test_a_fix_that_cannot_apply_records_no_edits(self, tmp_path):
        from storyforge.checker import CheckResult, Finding
        result = gate.GateResult(SCENE, check=CheckResult(SCENE, findings=[Finding(**BAD)]))
        edits = []
        with patch('storyforge.api._api_request', return_value=_text(
                {'edits': [{'problem': 1, 'find': 'not there', 'replace': 'x'}]})), \
                pytest.raises(gate.GateError, match='occurs 0 times'):
            gate.fix_scene(SCENE, 'prose', result, log_dir=str(tmp_path), model='m',
                           edits_out=edits)
        assert edits == []

    @pytest.mark.parametrize('reply', [
        {'stop_reason': 'max_tokens', 'content': [{'type': 'text', 'text': '{}'}], 'usage': {}},
        _text('not json'),
        {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': '{"x": 1}'}], 'usage': {}},
    ])
    def test_a_bad_fix_reply_is_a_gate_error(self, tmp_path, reply):
        from storyforge.checker import CheckResult, Finding
        result = gate.GateResult(SCENE, check=CheckResult(SCENE, findings=[Finding(**BAD)]))
        with patch('storyforge.api._api_request', return_value=reply), \
                pytest.raises(gate.GateError, match='the fix failed'):
            gate.fix_scene(SCENE, 'prose', result, log_dir=str(tmp_path), model='m')

    def test_unverified_and_halts_are_told_apart_in_the_fix_prompt(self):
        from storyforge import audit
        from storyforge.checker import CheckResult, Finding
        result = gate.GateResult(SCENE, check=CheckResult(
            SCENE, unverified=[Finding(**BAD, problem='its established quote is not in x')]))
        result.proposed = [{'id': 'p1', 'statement': 'S', 'quote': 'the words'}]
        result.halts = [audit.Halt('supersedes-fixed', 'p1',
                                   "the prose supersedes the registry fact r1 ('R')")]
        lines = gate.problems_to_fix(result)
        assert 'The scene says: "the words"' in lines[0] and "'R'" in lines[0]
        assert lines[1].startswith('UNVERIFIED (the check\'s quotes did not hold up: '
                                   'its established quote is not in x')

    def test_apply_edits_on_crlf_prose(self):
        assert gate.apply_edits('a\r\nb c', [{'find': 'a\nb', 'replace': 'X'}]) == 'X c'

    def test_frontmatter_is_refused(self, project_dir, tmp_path):
        with pytest.raises(gate.GateError, match='frontmatter'):
            gate.gate_scene(project_dir, SCENE, command='draft', prose='---\nid: x\n---\nText',
                            log_dir=str(tmp_path))

    def test_the_fix_prompt_lists_each_problem(self, project_dir, tmp_path):
        result = gate.GateResult(SCENE)
        from storyforge.checker import CheckResult, Finding
        result.check = CheckResult(SCENE, findings=[Finding(**BAD)])
        problems = gate.problems_to_fix(result)
        assert len(problems) == 1 and HERE in problems[0]
        assert '1. TIM contradiction' in gate.build_fix_prompt(SCENE, 'prose', problems)


class TestAccept:
    """`check --accept` (Ben, 2026-11-02): the author accepts the
    contradictions that stopped a scene, and `--pending` then passes it."""

    def test_accept_then_pending_passes(self, project, capsys):
        project_dir, commits = project
        with _api([[BAD]]), pytest.raises(SystemExit):
            cmd_check.main([SCENE])
        assert f'storyforge check --accept {SCENE}' in capsys.readouterr().out
        commits.clear()
        cmd_check.main(['--accept', SCENE])
        msg, paths = commits[-1]
        assert msg == f'Check: accept 1 contradiction(s) in {SCENE}'
        assert set(paths) == {gate.REPORTED_PATH, gate.BLOCKED_PATH, gate.PENDING_PATH}
        assert gate.reported(project_dir)[SCENE][0]['command'] == gate.ACCEPTED
        with _api([[BAD]]):
            cmd_check.main(['--pending'])
        assert SCENE not in gate.pending(project_dir)
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert f'## {SCENE}: passed' in report and 'ALREADY IN THE SCENE' in report

    def test_nothing_recorded_is_an_error_and_accepts_nothing(self, project):
        project_dir, commits = project
        with _api([[BAD]]), pytest.raises(SystemExit):
            cmd_check.main([SCENE])
        commits.clear()
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--accept', f'{SCENE},act2-sc01'])
        assert e.value.code == 1 and commits == []
        assert gate.reported(project_dir) == {} and SCENE in gate.blocked(project_dir)

    def test_it_takes_no_other_selection(self, project):
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--accept', SCENE, '--pending'])
        assert e.value.code == 1

    def test_a_failed_commit_exits_1(self, project, monkeypatch):
        with _api([[BAD]]), pytest.raises(SystemExit):
            cmd_check.main([SCENE])
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **k: False)
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--accept', SCENE])
        assert e.value.code == 1


class TestCheckBudget:
    def test_a_check_by_name_is_forecast_too(self, project, monkeypatch, capsys):
        """It skipped the threshold silently."""
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '1')
        seen = _fake_gate(monkeypatch, {})
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--scenes', f'act1-sc01,{SCENE}'])
        assert e.value.code == 1 and seen == []
        assert 'over the cost threshold ($1): nothing checked' in capsys.readouterr().out

    def test_pending_stopped_mid_run_by_the_budget(self, project, monkeypatch, capsys):
        """T-1: without --keep-going too: exit 1, the rest still pending, no
        --accept advice, and the report says what wasn't checked."""
        project_dir, _ = project
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '3')
        for sid in ('act1-sc01', SCENE, 'act2-sc01'):
            gate.mark_pending(project_dir, sid, 'draft', 'stale')
        seen = _fake_gate(monkeypatch, {}, spend=80_000)   # $2.00 a scene
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--pending'])
        assert e.value.code == 1 and seen == ['act1-sc01']
        assert set(gate.pending(project_dir)) == {SCENE, 'act2-sc01'}
        out = capsys.readouterr().out
        assert f'ERROR: stopped before {SCENE}: the run reached the cost threshold' in out
        assert '--accept' not in out
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert '## Not checked' in report and f'Not checked: {SCENE}, act2-sc01' in report
