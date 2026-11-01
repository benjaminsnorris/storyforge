"""`write` gates each drafted scene (plan §3.2–3.3; Ben's decisions,
2026-10-30): sequential by default, fix once and re-check, and a scene that
still fails is kept, listed in working/gate-pending.csv, and stops the run.
The gate itself is mocked at `gate.gate_and_fix`; its own tests are
tests/test_gate.py and tests/commands/test_cmd_check.py."""

import os

import pytest

from storyforge import gate
from storyforge.checker import CheckResult, Finding
from storyforge.cmd_write import main

from .test_write_guard import GOOD, _direct_replies, _reply, _scene, setup  # noqa: F401

pytestmark = pytest.mark.real_gate

BAD = Finding(kind='contradiction', code='TIM', scene_quote='word', established_scene='x',
              established_quote='y', fact_id='', explanation='why')



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

def _result(sid, passed):
    r = gate.GateResult(sid, check=CheckResult(sid, findings=[] if passed else [BAD]))
    r.committed = passed
    return r


#: what the stubbed gate was given as each scene's prose before the command
BEFORES: dict = {}


def _gate(monkeypatch, verdicts, fixed_prose=None):
    """`verdicts[scene_id]` is True (passes) or False (fails after the fix)."""
    calls = []

    def fake(project_dir, scene_id, *, command, prose, log_dir, **k):
        calls.append((scene_id, command))
        BEFORES[scene_id] = k.get('before')
        passed = verdicts[scene_id]
        out_prose = fixed_prose if fixed_prose is not None else prose
        return gate.GatedScene(out_prose, _result(scene_id, passed), _result(scene_id, False),
                               fixed=out_prose != prose)
    monkeypatch.setattr(gate, 'gate_and_fix', fake)
    return calls


class TestGatedWrite:
    def test_each_scene_is_gated_in_order(self, setup, monkeypatch):
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD), 'act1-sc02': _reply(GOOD)})
        calls = _gate(monkeypatch, {'act1-sc01': True, 'act1-sc02': True})
        main(['--scenes', 'act1-sc01,act1-sc02'])
        assert calls == [('act1-sc01', 'draft'), ('act1-sc02', 'draft')]
        assert gate.pending(setup) == {}

    def test_the_fixed_prose_is_what_is_saved(self, setup, monkeypatch):
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})
        fixed = GOOD.replace('word.', 'ending.')
        _gate(monkeypatch, {'act1-sc01': True}, fixed_prose=fixed)
        main(['--scenes', 'act1-sc01'])
        assert _scene(setup, 'act1-sc01') == fixed

    def test_a_scene_still_failing_is_kept_listed_and_stops_the_run(
            self, setup, monkeypatch, capsys):
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD), 'act1-sc02': _reply(GOOD)})
        calls = _gate(monkeypatch, {'act1-sc01': False, 'act1-sc02': True})
        with pytest.raises(SystemExit) as e:
            main(['--scenes', 'act1-sc01,act1-sc02'])
        assert e.value.code == 1
        assert calls == [('act1-sc01', 'draft')]
        assert _scene(setup, 'act1-sc01') is not None       # kept
        assert _scene(setup, 'act1-sc02') is None           # never drafted
        assert 'act1-sc01' in gate.pending(setup)
        out = capsys.readouterr().out
        assert 'did not pass the gate' in out and 'not attempted' in out

    def test_a_gate_error_is_a_stop_too(self, setup, monkeypatch):
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})

        def boom(*a, **k):
            raise gate.GateError('extraction failed: HTTP 500')
        monkeypatch.setattr(gate, 'gate_and_fix', boom)
        with pytest.raises(SystemExit):
            main(['--scenes', 'act1-sc01'])
        assert 'HTTP 500' in gate.pending(setup)['act1-sc01']['reason']

    def test_a_pending_earlier_scene_blocks_later_drafting(self, setup, monkeypatch, capsys):
        gate.mark_pending(setup, 'act1-sc01', 'draft', '2 problem(s)')
        _direct_replies(monkeypatch, {'act1-sc02': _reply(GOOD)})
        _gate(monkeypatch, {'act1-sc02': True})
        with pytest.raises(SystemExit) as e:
            main(['--scenes', 'act1-sc02'])
        assert e.value.code == 1
        assert 'did not pass the gate' in capsys.readouterr().out
        assert _scene(setup, 'act1-sc02') is None

    def test_the_pending_scene_itself_may_be_redrafted(self, setup, monkeypatch):
        gate.mark_pending(setup, 'act1-sc01', 'draft', '2 problem(s)')
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})
        calls = _gate(monkeypatch, {'act1-sc01': True})
        main(['--scenes', 'act1-sc01'])
        assert calls == [('act1-sc01', 'draft')]

    def test_batch_prose_is_refused_before_anything_is_spent(self, setup, monkeypatch, capsys):
        ran = []
        monkeypatch.setattr('storyforge.cmd_write._run_batch_mode',
                            lambda *a, **k: ran.append(1) or (0, 0, []))
        monkeypatch.setattr('storyforge.cmd_write.estimate_cost',
                            lambda *a, **k: ran.append('cost') or 0.0)
        with pytest.raises(SystemExit) as exc:
            main(['--batch', '--scenes', 'act1-sc01'])
        assert exc.value.code == 1 and ran == []
        assert '--batch is for coaching coach or strict' in capsys.readouterr().out

    @pytest.mark.parametrize('extra', [['--interactive'], ['--dry-run']])
    def test_batch_prose_is_refused_with_other_flags_too(self, setup, capsys, extra):
        with pytest.raises(SystemExit) as exc:
            main(['--batch', *extra, '--scenes', 'act1-sc01'])
        assert exc.value.code == 1
        assert '--batch is for coaching coach or strict' in capsys.readouterr().out

    def test_batch_prose_is_refused_when_the_level_comes_from_the_environment(
            self, setup, monkeypatch, capsys):
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')
        with pytest.raises(SystemExit):
            main(['--batch', '--scenes', 'act1-sc01'])
        assert '--batch is for coaching' in capsys.readouterr().out

    def test_batch_runs_for_coaching_briefs(self, setup, monkeypatch):
        ran = []
        monkeypatch.setattr('storyforge.cmd_write._run_batch_mode',
                            lambda *a, **k: ran.append(a[5]) or (0, 0, []))
        main(['--batch', '--coaching', 'coach', '--force', '--scenes', 'act1-sc01'])
        assert ran == ['coach']

    def test_coaching_replies_are_not_gated(self, setup, monkeypatch):
        _direct_replies(monkeypatch, {'act1-sc01': _reply('A brief. ' * 30)})
        calls = _gate(monkeypatch, {})
        main(['--force', '--coaching', 'coach', '--scenes', 'act1-sc01'])
        assert calls == []


class TestPendingFile:
    def test_round_trip_and_clear(self, project_dir):
        gate.mark_pending(project_dir, 's1', 'draft', 'a | b\nc')
        reason = gate.pending(project_dir)['s1']['reason']
        assert '|' not in reason and '\n' not in reason
        gate.clear_pending(project_dir, 's1')
        assert gate.pending(project_dir) == {}
        assert not os.path.exists(os.path.join(project_dir, gate.PENDING_PATH))

    def test_a_passing_gate_clears_its_scene(self, project_dir, tmp_path):
        import json
        from unittest.mock import patch

        def clean(path, body, **k):
            payload = {'findings': [], 'kept': []} if 'tools' in body else {'commitments': []}
            return {'stop_reason': 'end_turn', 'usage': {},
                    'content': [{'type': 'text', 'text': json.dumps(payload)}]}
        gate.mark_pending(project_dir, 'act1-sc02', 'draft', 'x')
        with patch('storyforge.api._api_request', side_effect=clean):
            assert gate.gate_scene(project_dir, 'act1-sc02', command='draft',
                                   log_dir=str(tmp_path), extract_model='m',
                                   check_model='m').committed
        assert gate.pending(project_dir) == {}


class TestReview443:
    """Fixes from #443's review."""

    def test_a_pending_scene_between_scenes_to_draft_stops_the_run_there(
            self, setup, monkeypatch, capsys):
        from storyforge import ledger
        order = ledger.scene_order(setup)
        middle = sorted(order, key=order.get)[1]
        assert middle == 'act1-sc02'
        gate.mark_pending(setup, middle, 'draft', 'two problems')
        later = sorted(order, key=order.get)[2]
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD), later: _reply(GOOD)})
        calls = _gate(monkeypatch, {'act1-sc01': True, later: True})
        with pytest.raises(SystemExit):
            main(['--scenes', f'act1-sc01,{later}'])
        assert calls == [('act1-sc01', 'draft')]
        assert f'{later} (not attempted: an earlier scene did not pass the gate)' \
            in capsys.readouterr().out

    def test_a_redraft_is_not_refused_and_its_dependents_are_rechecked(
            self, setup, monkeypatch, capsys, mock_git):
        """Phase 4: what leans on the scene is re-checked after it passes,
        not a reason to refuse it; scenes the run redrafts anyway are skipped."""
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD), 'act1-sc02': _reply(GOOD)})
        _gate(monkeypatch, {'act1-sc01': True, 'act1-sc02': True})
        runs = []

        def recheck(pd, *, log_dir, skip=frozenset(), **k):
            runs.append(set(skip))
            gate.clear_pending(pd, 'new-x1')
            return gate.Recheck(passed=['new-x1'])
        monkeypatch.setattr(gate, 'recheck_pending', recheck)
        gate.mark_pending(setup, 'new-x1', 'recheck', 're-check: x')
        main(['--force', '--scenes', 'act1-sc01,act1-sc02'])
        assert runs == [{'act1-sc02'}]   # after act1-sc01; act1-sc02 is redrafted next
        assert 'Re-check passed: new-x1' in capsys.readouterr().out
        commits = [c[1] for c in mock_git.calls if c[0] == 'commit_and_push']
        # the scene is committed before the re-check runs, then the re-check
        assert commits.index('Draft scene act1-sc01') < commits.index(
            'Re-check after act1-sc01: 1 passed')

    def test_a_failed_recheck_blocks_drafting_past_it(self, setup, monkeypatch, capsys):
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})
        _gate(monkeypatch, {'act1-sc01': True})

        def recheck(pd, *, log_dir, skip=frozenset(), **k):
            gate.mark_pending(pd, 'act1-sc02', 'recheck', 're-check did not pass: x')
            return gate.Recheck(failed='act1-sc02', why='x', left=['act1-sc02'])
        monkeypatch.setattr(gate, 'recheck_pending', recheck)
        gate.mark_pending(setup, 'act1-sc02', 'recheck', 're-check: x')
        main(['--force', '--scenes', 'act1-sc01'])
        out = capsys.readouterr().out
        assert 'the re-check of act1-sc02 did not pass' in out
        assert gate.pending(setup)['act1-sc02']['command'] == 'recheck'

    def test_a_pending_id_that_is_no_longer_a_scene_warns_and_does_not_block(
            self, setup, monkeypatch, capsys):
        gate.mark_pending(setup, 'cut-long-ago', 'draft', 'x')
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})
        _gate(monkeypatch, {'act1-sc01': True})
        main(['--scenes', 'act1-sc01'])
        assert 'no longer scenes: cut-long-ago' in capsys.readouterr().out

    def test_existing_prose_makes_it_a_redraft(self, setup, monkeypatch):
        path = os.path.join(setup, 'scenes', 'act1-sc01.md')
        with open(path, 'w') as f:
            f.write('A few words of an old version.')
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})
        calls = _gate(monkeypatch, {'act1-sc01': True})
        main(['--force', '--scenes', 'act1-sc01'])
        assert calls == [('act1-sc01', 'redraft')]
        # 2026-11-01: what was already there doesn't stop the redraft
        assert BEFORES['act1-sc01'].scenes['act1-sc01'] == 'A few words of an old version.'

    def test_a_new_scene_has_nothing_before(self, setup, monkeypatch):
        path = os.path.join(setup, 'scenes', 'act1-sc01.md')
        if os.path.exists(path):
            os.remove(path)
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})
        _gate(monkeypatch, {'act1-sc01': True})
        main(['--scenes', 'act1-sc01'])
        assert 'act1-sc01' not in BEFORES['act1-sc01'].scenes

    def test_a_scene_the_gate_failed_is_no_baseline_for_its_retry(self, setup, monkeypatch):
        """#480's review (CR-1): the failed prose is on disk and listed
        pending; redrafting it must not pass its errors as inherited."""
        path = os.path.join(setup, 'scenes', 'act1-sc01.md')
        with open(path, 'w') as f:
            f.write('The failed draft.')
        gate.mark_pending(setup, 'act1-sc01', 'draft', '1 problem(s) after one fix: x')
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})
        _gate(monkeypatch, {'act1-sc01': True})
        main(['--force', '--scenes', 'act1-sc01'])
        assert 'act1-sc01' not in BEFORES['act1-sc01'].scenes
        assert 'waiting on the gate' in BEFORES['act1-sc01'].left_out['act1-sc01']

    def test_a_gate_failure_is_in_the_commit_message_and_the_task_stays_open(
            self, setup, monkeypatch, mock_git):
        ticked = []
        monkeypatch.setattr('storyforge.cmd_write.update_pr_task',
                            lambda task, p: ticked.append(task))
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})
        _gate(monkeypatch, {'act1-sc01': False})
        with pytest.raises(SystemExit):
            main(['--scenes', 'act1-sc01'])
        assert ticked == []
        commits = [c for c in mock_git.calls if c[0] == 'commit_and_push']
        assert any('did not pass the gate' in c[1] for c in commits)
        assert any(gate.PENDING_PATH in (c[2] or []) for c in commits)

    def test_the_first_runs_findings_are_logged_when_the_fix_fails(
            self, setup, monkeypatch, capsys):
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})

        def boom(*a, **k):
            e = gate.GateError('the fix failed: bad find')
            e.first = _result('act1-sc01', False)
            raise e
        monkeypatch.setattr(gate, 'gate_and_fix', boom)
        with pytest.raises(SystemExit):
            main(['--scenes', 'act1-sc01'])
        out = capsys.readouterr().out
        assert '(first check) CONTRADICTION: TIM' in out
        assert 'act1-sc01' in gate.pending(setup)

    def test_an_unexpected_gate_failure_is_pending_not_a_traceback(self, setup, monkeypatch):
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})

        def boom(*a, **k):
            raise KeyError('bug')
        monkeypatch.setattr(gate, 'gate_and_fix', boom)
        with pytest.raises(SystemExit) as e:
            main(['--scenes', 'act1-sc01'])
        assert e.value.code == 1
        assert 'KeyError' in gate.pending(setup)['act1-sc01']['reason']

    def test_a_redraft_failing_says_its_old_facts_are_stale(self, setup, monkeypatch):
        path = os.path.join(setup, 'scenes', 'act1-sc01.md')
        with open(path, 'w') as f:
            f.write('Old prose.')
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})
        _gate(monkeypatch, {'act1-sc01': False})
        with pytest.raises(SystemExit):
            main(['--force', '--scenes', 'act1-sc01'])
        reason = gate.pending(setup)['act1-sc01']['reason']
        assert 'earlier version' in reason and 'CONTRADICTION' in reason

    @pytest.mark.parametrize('written, why', [
        (None, 'wrote no scene file'),
        ('same', 'left the scene file unchanged'),
        ('too few words', 'only 3 words'),
    ])
    def test_interactive_output_is_checked_before_the_gate(self, written, why):
        import tempfile
        from storyforge.cmd_write import _interactive_problem
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 's.md')
            if written is not None:
                with open(path, 'w') as f:
                    f.write(written)
            assert why in _interactive_problem(path, 'same')




class TestReviseRedraftsAreGated:
    """revise's redraft-from-brief goes through write's gate, in reading
    order, and stops where write would."""

    def _redraft(self, project_dir, monkeypatch, ids, gate_fails=()):
        from storyforge import cmd_revise, cmd_write
        drafted, gated, skips = [], [], []
        self.skips = skips

        def invoke(prompt, model, log_file, **k):
            drafted.append(os.path.basename(log_file)[len('redraft-'):-len('.json')])
        monkeypatch.setattr('storyforge.cmd_write._build_prompt', lambda sid, *a, **k: sid)
        monkeypatch.setattr('storyforge.api.invoke_to_file', invoke)
        def extract(log_file, scene_file):   # the reply is written, as the real one does
            with open(scene_file, 'w') as f:
                f.write('A new redraft.')
            return ''
        monkeypatch.setattr(cmd_write, '_extract_scene_from_response', extract)
        monkeypatch.setattr(cmd_revise, 'commit_and_push', lambda *a, **k: True)
        self.befores = {}

        def fake_gate(pd, sid, scene_file, command, log_dir, before=None):
            gated.append((sid, command))
            self.befores[sid] = before
            return (False, 'a contradiction') if sid in gate_fails else (True, '')
        monkeypatch.setattr(cmd_write, 'run_recheck', lambda pd, ld, skip=frozenset(),
                            spent_before=0.0: skips.append(set(skip)))
        monkeypatch.setattr(cmd_write, '_gate_drafted_scene', fake_gate)
        error = None
        try:
            cmd_revise._redraft_from_briefs(project_dir, ids, 'm', str(project_dir),
                                            system=[{'type': 'text', 'text': 's'}])
        except cmd_revise.RedraftError as e:
            error = str(e)
        return drafted, gated, error

    def test_each_redraft_is_gated_in_reading_order(self, project_dir, monkeypatch):
        old = {}
        for sid in ('act1-sc01', 'act1-sc02', 'act2-sc01'):
            with open(os.path.join(project_dir, 'scenes', f'{sid}.md')) as f:
                old[sid] = f.read()
        drafted, gated, error = self._redraft(project_dir, monkeypatch,
                                              ['act2-sc01', 'act1-sc02', 'act1-sc01'])
        assert drafted == ['act1-sc01', 'act1-sc02', 'act2-sc01']
        assert gated == [(s, 'redraft') for s in drafted]
        assert error is None
        # #480's review: the baseline is the book before the run, not the new prose
        assert all(self.befores[sid].scenes[sid] == old[sid] != 'A new redraft.'
                   for sid in drafted)

    def test_a_scene_the_gate_does_not_pass_stops_the_run(self, project_dir, monkeypatch):
        drafted, _, error = self._redraft(project_dir, monkeypatch,
                                          ['act1-sc01', 'act1-sc02', 'act2-sc01'],
                                          gate_fails={'act1-sc02'})
        assert drafted == ['act1-sc01', 'act1-sc02']
        assert 'act1-sc02 (redrafted, but the gate did not pass it' in error
        assert 'act2-sc01 (not redrafted: redrafting stops' in error

    def test_each_redraft_skips_the_rest_of_the_run_in_its_recheck(
            self, project_dir, monkeypatch):
        self._redraft(project_dir, monkeypatch, ['act1-sc01', 'act1-sc02', 'act2-sc01'])
        assert self.skips == [{'act1-sc02', 'act2-sc01'}, {'act2-sc01'}, set()]

    def test_the_hone_fix_redraft_is_gated_and_stops_too(self, project_dir, monkeypatch):
        from storyforge import cmd_revise, cmd_write
        gated = []
        monkeypatch.setattr('storyforge.cmd_write._build_prompt', lambda sid, *a, **k: sid)
        monkeypatch.setattr('storyforge.common.build_shared_context', lambda *a, **k: [])
        monkeypatch.setattr(cmd_revise, 'invoke_api', lambda *a, **k: 'New prose. ' * 300)
        monkeypatch.setattr('storyforge.parsing.unsafe_scene_reason', lambda *a: '')
        befores = {}
        with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md')) as f:
            old = f.read()

        def fake_gate(pd, sid, scene_file, command, log_dir, before=None):
            gated.append(sid)
            befores[sid] = before
            return (False, 'a contradiction') if sid == 'act1-sc01' else (True, '')
        monkeypatch.setattr(cmd_write, '_gate_drafted_scene', fake_gate)
        with pytest.raises(cmd_revise.RedraftError, match='act1-sc02 \\(not redrafted'):
            cmd_revise._redraft_scenes(project_dir, ['act1-sc02', 'act1-sc01'])
        assert gated == ['act1-sc01']
        assert befores['act1-sc01'].scenes['act1-sc01'] == old   # the scene before the redraft

    def test_the_hone_fix_redraft_skips_the_rest_of_its_run_in_the_recheck(
            self, project_dir, monkeypatch):
        from storyforge import cmd_revise, cmd_write
        monkeypatch.setattr('storyforge.cmd_write._build_prompt', lambda sid, *a, **k: sid)
        monkeypatch.setattr('storyforge.common.build_shared_context', lambda *a, **k: [])
        monkeypatch.setattr(cmd_revise, 'invoke_api', lambda *a, **k: 'New prose. ' * 300)
        monkeypatch.setattr('storyforge.parsing.unsafe_scene_reason', lambda *a: '')
        monkeypatch.setattr(cmd_write, '_gate_drafted_scene', lambda *a, **k: (True, ''))
        skips = []
        monkeypatch.setattr(cmd_write, 'run_recheck', lambda pd, ld, skip=frozenset(),
                            spent_before=0.0: skips.append(set(skip)))
        cmd_revise._redraft_scenes(project_dir, ['act1-sc02', 'act1-sc01'])
        assert skips == [{'act1-sc02'}, set()]


@pytest.mark.real_gate
class TestReviseRedraftsRealGate:
    """The real `_gate_drafted_scene` (only `gate_and_fix` mocked)."""

    def _setup(self, project_dir, monkeypatch, fails=()):
        from storyforge import cmd_revise, cmd_write
        from storyforge.checker import CheckResult
        monkeypatch.setattr('storyforge.cmd_write._build_prompt', lambda sid, *a, **k: sid)
        monkeypatch.setattr('storyforge.api.invoke_to_file', lambda *a, **k: None)
        monkeypatch.setattr(cmd_write, '_extract_scene_from_response', lambda *a: '')
        monkeypatch.setattr(cmd_revise, 'commit_and_push', lambda *a, **k: True)
        bad = Finding('contradiction', 'TIM', 'x', 'y', 'z', '', 'why')
        gated = []

        def gate_and_fix(pd, sid, *, command, prose, log_dir, **k):
            gated.append(sid)
            result = gate.GateResult(sid, check=CheckResult(
                sid, findings=[bad] if sid in fails else []))
            return gate.GatedScene(prose, result, result)
        monkeypatch.setattr(gate, 'gate_and_fix', gate_and_fix)
        return gated

    def _run(self, project_dir, ids):
        from storyforge import cmd_revise
        with pytest.raises(cmd_revise.RedraftError) as e:
            cmd_revise._redraft_from_briefs(project_dir, ids, 'm', str(project_dir),
                                            system=[{'type': 'text', 'text': 's'}])
        return str(e.value)

    def test_a_redraft_the_gate_fails_is_listed_pending(self, project_dir, monkeypatch):
        self._setup(project_dir, monkeypatch, fails={'act1-sc01'})
        error = self._run(project_dir, ['act1-sc01', 'act1-sc02'])
        assert gate.pending(project_dir)['act1-sc01']['command'] == 'redraft'
        assert 'act1-sc02 (not redrafted' in error

    def test_a_later_run_does_not_redraft_past_a_pending_scene(self, project_dir, monkeypatch):
        gated = self._setup(project_dir, monkeypatch)
        gate.mark_pending(project_dir, 'act1-sc01', 'redraft', 'a contradiction')
        error = self._run(project_dir, ['act1-sc02'])
        assert gated == []
        assert 'earlier scene(s) wait on the gate: act1-sc01' in error

    def test_the_advice_names_check_for_a_scene_the_gate_failed(self, capsys):
        from storyforge import cmd_revise
        cmd_revise._report_redraft_error(cmd_revise.RedraftError('x'))
        out = capsys.readouterr().out
        assert '`storyforge check <id>`' in out and 'gate-pending.csv' in out


def test_a_marker_the_gates_fix_drops_is_restored(project_dir, monkeypatch):
    from storyforge import cmd_revise, cmd_write
    marker = '<!-- illustration: ill-1 -->'
    scene = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
    with open(scene, 'w') as f:
        f.write(f'Old prose.\n\n{marker}\n')
    monkeypatch.setattr('storyforge.cmd_write._build_prompt', lambda sid, *a, **k: sid)
    monkeypatch.setattr('storyforge.common.build_shared_context', lambda *a, **k: [])
    monkeypatch.setattr(cmd_revise, 'invoke_api', lambda *a, **k: 'New prose. ' * 300)
    monkeypatch.setattr('storyforge.parsing.unsafe_scene_reason', lambda *a: '')

    def restore(pd, original, rewritten):
        if marker in original and marker not in rewritten:
            return {'text': rewritten + f'\n{marker}\n', 'restored': ['ill-1'], 'lost': []}
        return {'text': rewritten, 'restored': [], 'lost': []}
    monkeypatch.setattr('storyforge.illustrations.preserve_markers', restore)

    def fix_drops_marker(pd, sid, scene_file, command, log_dir, before=None):
        with open(scene_file) as f:
            text = f.read()
        assert marker in text           # restored before the gate
        with open(scene_file, 'w') as f:
            f.write(text.replace(marker, ''))
        return True, ''
    monkeypatch.setattr(cmd_write, '_gate_drafted_scene', fix_drops_marker)
    assert cmd_revise._redraft_scenes(project_dir, ['act1-sc01']) == 1
    with open(scene) as f:
        assert marker in f.read()


class TestPendingReason480:
    """#480's review: what the pending reason counts and says."""

    def _gated(self, project_dir, monkeypatch, first):
        from storyforge import cmd_write
        path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        monkeypatch.setattr(gate, 'gate_and_fix',
                            lambda *a, **k: gate.GatedScene('prose', first, first))
        passed, why = cmd_write._gate_drafted_scene(project_dir, 'act1-sc01', path, 'revise',
                                                    str(project_dir))
        return passed, why

    def test_an_inherited_finding_is_not_counted_as_a_problem(self, project_dir, monkeypatch):
        old = Finding('contradiction', 'TIM', 'old words here', 'act1-sc02', 'e', '', 'why')
        r = gate.GateResult('act1-sc01', check=CheckResult('act1-sc01', findings=[BAD, old]))
        r.inherited = [old]
        passed, why = self._gated(project_dir, monkeypatch, r)
        assert not passed and why.startswith('1 problem(s) after one fix')

    def test_plan_conflicts_alone_are_not_fixed_and_say_so(self, project_dir, monkeypatch):
        r = gate.GateResult('act1-sc01', check=CheckResult('act1-sc01', findings=[BAD]))
        r.plan_conflicts = [BAD]
        passed, why = self._gated(project_dir, monkeypatch, r)
        assert not passed and why.startswith('1 problem(s) not fixed (plan conflicts')
        assert 'PLAN CONFLICT' in why
