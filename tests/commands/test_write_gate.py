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


def _gate(monkeypatch, verdicts, fixed_prose=None):
    """`verdicts[scene_id]` is True (passes) or False (fails after the fix)."""
    calls = []

    def fake(project_dir, scene_id, *, command, prose, log_dir, **k):
        calls.append((scene_id, command))
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

    def test_batch_warns_that_it_is_not_gated(self, setup, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_write._run_batch_mode',
                            lambda *a, **k: (0, 0, []))
        main(['--batch', '--scenes', 'act1-sc01'])
        assert 'no scene is gated' in capsys.readouterr().out

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

    def test_a_redraft_later_facts_lean_on_is_refused_before_spending(
            self, setup, monkeypatch, capsys):
        monkeypatch.setattr(gate, 'leaning_on',
                            lambda p, sid: ['later-fact → x'] if sid == 'act1-sc01' else [])
        calls = _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})
        with pytest.raises(SystemExit):
            main(['--force', '--scenes', 'act1-sc01'])
        assert calls == []
        assert 'later facts lean on its commitments' in capsys.readouterr().out
        assert gate.pending(setup) == {}

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

    def test_batch_lists_every_scene_it_writes_as_pending(self, setup, monkeypatch):
        from storyforge.cmd_write import _pend
        _pend(setup, 'act1-sc01', 'draft', 'drafted with --batch, not gated')
        assert 'batch' in gate.pending(setup)['act1-sc01']['reason']

    def test_revise_redrafts_are_listed_pending(self, project_dir):
        from storyforge.cmd_revise import _mark_ungated
        _mark_ungated(project_dir, 'act1-sc01')
        assert gate.pending(project_dir)['act1-sc01']['command'] == 'redraft'
