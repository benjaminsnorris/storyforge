"""Phase 4 PR 4: every prose pass `revise` runs goes through the gate
(`docs/plans/2026-10-31-phase4-safe-revision-design.md` §5).

Before this, only redraft-from-brief was gated (#456); a polish, craft or
naturalness pass wrote its scenes and committed them unchecked, so a
contradiction it wrote reached the book (E8's `revision-plan` family).
Now each scene a pass rewrote is gated in reading order (fix once,
re-check), then the later scenes depending on it are re-checked, and the
first scene the gate doesn't pass stops the session with it and the rest
listed in working/gate-pending.csv."""

import os

import pytest

from storyforge import cmd_revise, cmd_write, gate
from storyforge.cmd_revise import _read_csv_plan, main

from . import test_cmd_revise as revise_tests
from .test_cmd_revise import _run_pass_setup


def _stub_gate(monkeypatch, fails=()):
    """`_gate_drafted_scene` passes every scene but `fails` (which it lists
    pending, as the real one does). Returns the (scene, command) calls and
    the re-check skip sets."""
    gated, skips = [], []

    def fake(pd, sid, scene_file, command, log_dir):
        gated.append((sid, command))
        if sid in fails:
            return False, cmd_write._pend(pd, sid, command, 'a contradiction')
        return True, ''
    monkeypatch.setattr(cmd_write, '_gate_drafted_scene', fake)
    monkeypatch.setattr(cmd_write, 'run_recheck',
                        lambda pd, ld, skip=frozenset(), spent_before=0.0:
                        skips.append(set(skip)))
    return gated, skips


def _scenes(project_dir, *ids):
    for sid in ids:
        with open(os.path.join(project_dir, 'scenes', f'{sid}.md'), 'w') as f:
            f.write(f'Prose of {sid}.\n')


class TestGatePassScenes:

    def test_each_scene_is_gated_in_reading_order_as_revise(self, project_dir, monkeypatch):
        _scenes(project_dir, 'act1-sc01', 'act1-sc02', 'act2-sc01')
        gated, skips = _stub_gate(monkeypatch)
        out = cmd_revise._gate_pass_scenes(project_dir, ['act2-sc01', 'act1-sc01', 'act1-sc02'],
                                           'polish', str(project_dir))
        assert out == []
        assert gated == [('act1-sc01', 'revise'), ('act1-sc02', 'revise'),
                         ('act2-sc01', 'revise')]
        # each re-check leaves out the scenes this pass still has to gate
        assert skips == [{'act1-sc02', 'act2-sc01'}, {'act2-sc01'}, set()]

    def test_the_first_failure_stops_and_lists_the_rest_pending(self, project_dir, monkeypatch):
        _scenes(project_dir, 'act1-sc01', 'act1-sc02', 'act2-sc01')
        gated, _ = _stub_gate(monkeypatch, fails={'act1-sc02'})
        out = cmd_revise._gate_pass_scenes(project_dir, ['act1-sc01', 'act1-sc02', 'act2-sc01'],
                                           'polish', str(project_dir))
        assert [s for s, _ in gated] == ['act1-sc01', 'act1-sc02']
        assert out[0].startswith('act1-sc02 (the gate did not pass it')
        assert 'act2-sc01 (revised, not gated: the gate stopped at act1-sc02)' in out[1]
        waiting = gate.pending(project_dir)
        assert set(waiting) == {'act1-sc02', 'act2-sc01'}
        assert waiting['act2-sc01']['command'] == 'revise'
        assert 'revised by pass polish but not gated' in waiting['act2-sc01']['reason']

    def test_an_earlier_pending_scene_blocks_every_scene(self, project_dir, monkeypatch):
        """A re-check that failed mid-run lists a scene before the next one."""
        _scenes(project_dir, 'act1-sc02', 'act2-sc01')
        gated, _ = _stub_gate(monkeypatch)
        gate.mark_pending(project_dir, 'act1-sc01', gate.RECHECK_FAILED, 'a contradiction')
        out = cmd_revise._gate_pass_scenes(project_dir, ['act1-sc02', 'act2-sc01'],
                                           'polish', str(project_dir))
        assert gated == []
        assert 'an earlier scene waits on the gate: act1-sc01' in out[0]
        assert {'act1-sc02', 'act2-sc01'} <= set(gate.pending(project_dir))

    def test_nothing_rewritten_gates_nothing(self, project_dir, monkeypatch):
        gated, _ = _stub_gate(monkeypatch)
        assert cmd_revise._gate_pass_scenes(project_dir, [], 'polish', str(project_dir)) == []
        assert gated == []

    def test_a_marker_the_gates_fix_drops_is_restored(self, project_dir, monkeypatch):
        marker = '<!-- illustration: ill-1 -->'
        scene = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        with open(scene, 'w') as f:
            f.write(f'Revised prose.\n\n{marker}\n')

        def restore(pd, original, rewritten):
            if marker in original and marker not in rewritten:
                return {'text': rewritten + f'\n{marker}\n', 'restored': ['ill-1'], 'lost': []}
            return {'text': rewritten, 'restored': [], 'lost': []}
        monkeypatch.setattr('storyforge.illustrations.preserve_markers', restore)

        def fix_drops_marker(pd, sid, scene_file, command, log_dir):
            with open(scene_file) as f:
                text = f.read()
            with open(scene_file, 'w') as f:
                f.write(text.replace(marker, ''))
            return True, ''
        monkeypatch.setattr(cmd_write, '_gate_drafted_scene', fix_drops_marker)
        cmd_revise._gate_pass_scenes(project_dir, ['act1-sc01'], 'polish', str(project_dir))
        with open(scene) as f:
            assert marker in f.read()


@pytest.mark.real_gate
def test_a_revision_the_gate_fails_is_listed_as_revise_with_stale_facts(
        project_dir, monkeypatch):
    """The real `_gate_drafted_scene` (only `gate_and_fix` mocked)."""
    from storyforge.checker import CheckResult, Finding
    _scenes(project_dir, 'act1-sc01')
    bad = Finding('contradiction', 'TIM', 'x', 'y', 'z', '', 'why')

    def gate_and_fix(pd, sid, *, command, prose, log_dir, **k):
        result = gate.GateResult(sid, check=CheckResult(sid, findings=[bad]))
        return gate.GatedScene(prose, result, result)
    monkeypatch.setattr(gate, 'gate_and_fix', gate_and_fix)
    out = cmd_revise._gate_pass_scenes(project_dir, ['act1-sc01'], 'polish', str(project_dir))
    assert out and out[0].startswith('act1-sc01')
    row = gate.pending(project_dir)['act1-sc01']
    assert row['command'] == 'revise'
    assert 'earlier version\'s facts are still in the ledger' in row['reason']


class TestPassBlocked:
    """A prose pass doesn't start (or spend) behind a scene waiting on the gate."""

    def test_a_pending_scene_before_the_targets_stops_it(self, project_dir):
        gate.mark_pending(project_dir, 'act1-sc01', 'redraft', 'a contradiction')
        with pytest.raises(SystemExit) as e:
            cmd_revise._exit_if_pass_blocked(project_dir, 'act2-sc01;act1-sc02')
        assert e.value.code == 1

    def test_a_pending_scene_the_pass_rewrites_does_not(self, project_dir):
        gate.mark_pending(project_dir, 'act1-sc02', 'redraft', 'a contradiction')
        cmd_revise._exit_if_pass_blocked(project_dir, 'act1-sc02;act2-sc01')
        cmd_revise._exit_if_pass_blocked(project_dir, '')  # full scope: every scene

    def test_targets_that_are_not_scenes_mean_every_scene(self, project_dir):
        assert cmd_revise._pass_scene_ids(project_dir, 'Dorren Hayle;NEW:bridge')[0] == \
            'act1-sc01'


class TestMainPassLoopIsGated:
    """`revise`'s main pass loop."""

    def _run(self, project_dir, monkeypatch, fails=(), coaching=None):
        if coaching:
            monkeypatch.setenv('STORYFORGE_COACHING', coaching)
        gated, _ = _stub_gate(monkeypatch, fails)
        revise_tests.TestOwedScenes()._run(project_dir, monkeypatch, ['act1-sc02', 'act1-sc01'], [], [], [])
        return gated

    def test_the_scenes_a_pass_wrote_are_gated(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        plan_file = _run_pass_setup(project_dir, monkeypatch, 'craft')
        mock_api.set_response('=== SCENE: act1-sc01 === ...')
        gated = self._run(project_dir, monkeypatch)
        assert gated == [('act1-sc01', 'revise'), ('act1-sc02', 'revise')]
        assert _read_csv_plan(plan_file)[0]['status'] == 'completed'

    def test_a_scene_the_gate_fails_stops_the_session(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        plan_file = _run_pass_setup(project_dir, monkeypatch, 'craft')
        mock_api.set_response('=== SCENE: act1-sc01 === ...')
        with pytest.raises(SystemExit) as e:
            self._run(project_dir, monkeypatch, fails={'act1-sc01'})
        assert e.value.code == 1
        out = capsys.readouterr().out
        assert 'the gate did not pass all of its revised scenes' in out
        assert 'act1-sc02 (revised, not gated' in out
        assert '`storyforge check --pending`' in out
        # the pass did its job and is committed; the gate stops what follows
        assert _read_csv_plan(plan_file)[0]['status'] == 'completed'
        assert set(gate.pending(project_dir)) == {'act1-sc01', 'act1-sc02'}

    def test_a_pending_scene_stops_the_pass_before_it_spends(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        plan_file = _run_pass_setup(project_dir, monkeypatch, 'craft')
        mock_api.set_response('=== SCENE: act1-sc01 === ...')
        rows = _read_csv_plan(plan_file)
        rows[0]['targets'] = 'act2-sc01'
        from storyforge.cmd_revise import _write_csv_plan
        _write_csv_plan(plan_file, rows)
        gate.mark_pending(project_dir, 'act1-sc01', 'redraft', 'a contradiction')
        with pytest.raises(SystemExit):
            main([])
        assert not mock_api.calls

    def test_coach_level_passes_are_not_gated(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        _run_pass_setup(project_dir, monkeypatch, 'craft')
        mock_api.set_response('=== SCENE: act1-sc01 === ...')
        assert self._run(project_dir, monkeypatch, coaching='coach') == []


class TestPolishLoopPassIsGated:
    """The polish loop's pass (`_execute_single_pass`)."""

    REPLY = ('=== SCENE: act1-sc01 ===\n' + 'The rain kept on. ' * 50
             + '\n=== END SCENE: act1-sc01 ===')

    def _run(self, project_dir, monkeypatch, reply):
        return revise_tests.TestPolishLoopPass()._run(project_dir, monkeypatch, reply)

    def test_the_scene_it_wrote_is_gated(self, project_dir, monkeypatch):
        gated, _ = _stub_gate(monkeypatch)
        rows, _, _ = self._run(project_dir, monkeypatch, self.REPLY)
        assert gated == [('act1-sc01', 'revise')]
        assert rows[0]['status'] == 'completed'

    def test_a_scene_the_gate_fails_stops_the_loop(self, project_dir, monkeypatch, capsys):
        _stub_gate(monkeypatch, fails={'act1-sc01'})
        with pytest.raises(SystemExit) as e:
            self._run(project_dir, monkeypatch, self.REPLY)
        assert e.value.code == 1
        assert 'the gate did not pass all of its revised scenes' in capsys.readouterr().out
        assert 'act1-sc01' in gate.pending(project_dir)
