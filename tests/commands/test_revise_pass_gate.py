"""Phase 4 PR 4: every prose pass `revise` runs goes through the gate
(`docs/plans/2026-10-31-phase4-safe-revision-design.md` §5).

Before this, only redraft-from-brief was gated (#456); a polish, craft or
naturalness pass wrote its scenes and committed them unchecked, so a
contradiction it wrote reached the book (E8's `revision-plan` family).
Now each scene a pass rewrote is listed pending and committed, then gated
in reading order (fix once, re-check), then the later scenes depending on
it are re-checked; the first scene the gate doesn't pass stops the session
with it and the rest listed in working/gate-pending.csv."""

import os
import subprocess as sp

import pytest

from storyforge import cmd_revise, cmd_write, gate
from storyforge.cmd_revise import _read_csv_plan, _write_csv_plan, main

from . import test_cmd_revise as revise_tests
from .test_cmd_revise import _run_pass_setup

PROSE = 'The rain kept on against the slate. ' * 60


@pytest.fixture(autouse=True)
def _no_git(monkeypatch):
    """The commit `_gate_pass_scenes` makes before gating."""
    commits = []
    monkeypatch.setattr('storyforge.git.commit_and_push',
                        lambda d, msg, paths=None: commits.append((msg, paths)) or True)
    return commits


#: what the stubbed gate was given as each scene's prose before the pass
BEFORES: dict = {}


def _stub_gate(monkeypatch, fails=(), recheck=None):
    """`_gate_drafted_scene` passes every scene but `fails` (which it lists
    pending, as the real one does). `recheck(project_dir, skip)` runs as the
    re-check and returns its `gate.Recheck` (default: nothing pending).
    Returns the (scene, command) calls and the re-check skip sets."""
    gated, skips = [], []
    BEFORES.clear()

    def fake(pd, sid, scene_file, command, log_dir, before=None):
        gated.append((sid, command))
        BEFORES[sid] = before
        if sid in fails:
            return False, cmd_write._pend(pd, sid, command, 'a contradiction')
        return True, ''

    def run_recheck(pd, ld, skip=frozenset(), spent_before=0.0):
        skips.append(set(skip))
        return recheck(pd, skip) if recheck else None
    monkeypatch.setattr(cmd_write, '_gate_drafted_scene', fake)
    monkeypatch.setattr(cmd_write, 'run_recheck', run_recheck)
    return gated, skips


def _scenes(project_dir, *ids):
    for sid in ids:
        with open(os.path.join(project_dir, 'scenes', f'{sid}.md'), 'w') as f:
            f.write(f'Prose of {sid}.\n')


def _gate_pass(project_dir, ids):
    return cmd_revise._gate_pass_scenes(project_dir, ids, 'polish', str(project_dir))


class TestOneBudget:
    """The threshold is one budget for the revise session (#499's review)."""

    def test_the_rechecks_reserve_the_gate_runs_the_pass_still_owes(
            self, project_dir, monkeypatch):
        _scenes(project_dir, 'act1-sc01', 'act1-sc02', 'act2-sc01')
        seen = []
        monkeypatch.setattr(cmd_write, '_gate_drafted_scene', lambda *a, **k: (True, ''))
        monkeypatch.setattr(cmd_write, 'run_recheck',
                            lambda pd, ld, skip=frozenset(), spent_before=0.0:
                            seen.append(spent_before))
        _gate_pass(project_dir, ['act1-sc01', 'act1-sc02', 'act2-sc01'])
        per = gate.RECHECK_COST_PER_SCENE
        assert seen == [pytest.approx(2 * per), pytest.approx(per), pytest.approx(0.0)]

    def test_the_session_is_metered(self, monkeypatch):
        """What the passes spent counts against the re-checks after them."""
        from storyforge import api
        seen = []

        def fake_main(argv=None):
            api._meter({'usage': {'input_tokens': 0, 'output_tokens': 40_000}},
                       'claude-opus-4-6')
            seen.append(cmd_revise._run_budget().committed())
            return 0
        monkeypatch.setattr(cmd_revise, '_main', fake_main)
        assert main([]) == 0
        assert seen and seen[0] > 0.5
        assert cmd_revise._RUN_BUDGET is None   # gone with the session
        assert cmd_revise._run_budget().committed() == 0.0


class TestReservationsReachTheRechecks:
    """T-2 (#510's review): what the run reserves (`RunBudget.owed`) must
    reach the re-checks after a pass's gated scenes and after a redraft;
    either could take a fresh budget and lose it."""

    @pytest.fixture
    def budget(self, monkeypatch):
        from storyforge.costs import RunBudget
        b = RunBudget()
        monkeypatch.setattr(cmd_revise, '_RUN_BUDGET', b)
        return b

    def _rechecks(self, monkeypatch):
        seen = []
        monkeypatch.setattr(cmd_write, 'run_recheck',
                            lambda pd, ld, skip=frozenset(), spent_before=0.0:
                            seen.append(spent_before))
        return seen

    def test_in_a_passs_gated_scenes(self, project_dir, monkeypatch, budget):
        _scenes(project_dir, 'act1-sc01', 'act1-sc02')
        monkeypatch.setattr(cmd_write, '_gate_drafted_scene', lambda *a, **k: (True, ''))
        seen = self._rechecks(monkeypatch)
        with budget.reserving(4.0):
            _gate_pass(project_dir, ['act1-sc01', 'act1-sc02'])
        per = gate.RECHECK_COST_PER_SCENE
        assert seen == [pytest.approx(4.0 + per), pytest.approx(4.0)]

    def test_after_a_redraft(self, project_dir, monkeypatch, budget):
        from unittest.mock import patch
        long = 'The rain fell on the cobblestones. ' * 40
        with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md'), 'w') as f:
            f.write(long)
        monkeypatch.setattr(cmd_revise, '_gate_redraft', lambda *a, **k: '')
        monkeypatch.setattr(cmd_revise, '_restore_gate_markers', lambda *a, **k: None)
        seen = self._rechecks(monkeypatch)
        with patch('storyforge.cmd_revise.invoke_api', return_value=long + ' New end.'), \
             patch('storyforge.cmd_revise.select_model', return_value='claude-sonnet-5-5'), \
             patch('storyforge.cmd_write._build_prompt', return_value='fake prompt'), \
             patch('storyforge.common.get_coaching_level', return_value='full'), \
             budget.reserving(4.0):
            cmd_revise._redraft_scenes(project_dir, ['act1-sc01'])
        assert seen == [pytest.approx(4.0)]

    def test_the_polish_loop_is_one_budget_outside_main(self, monkeypatch):
        """TD-3: outside `main` each `_run_budget()` was a new budget."""
        seen = []
        monkeypatch.setattr(cmd_revise, '_polish_loop',
                            lambda *a, **k: seen.extend([cmd_revise._run_budget(),
                                                         cmd_revise._run_budget()]))
        cmd_revise._run_polish_loop('/p', 1, None)
        assert seen[0] is seen[1]
        assert cmd_revise._RUN_BUDGET is None   # gone with the run


class TestGatePassScenes:

    def test_every_scene_gets_the_passs_one_baseline(self, project_dir, monkeypatch):
        _scenes(project_dir, 'act1-sc01', 'act1-sc02')
        _stub_gate(monkeypatch)
        snap = gate.Snapshot(scenes={'act1-sc01': 'old one'})
        cmd_revise._gate_pass_scenes(project_dir, ['act1-sc01', 'act1-sc02'], 'polish',
                                     str(project_dir), before=snap)
        assert set(BEFORES) == {'act1-sc01', 'act1-sc02'}
        assert all(b is snap for b in BEFORES.values())

    def test_each_scene_is_gated_in_reading_order_as_revise(self, project_dir, monkeypatch):
        _scenes(project_dir, 'act1-sc01', 'act1-sc02', 'act2-sc01')
        gated, skips = _stub_gate(monkeypatch)
        assert _gate_pass(project_dir, ['act2-sc01', 'act1-sc01', 'act1-sc02']) == []
        assert gated == [('act1-sc01', 'revise'), ('act1-sc02', 'revise'),
                         ('act2-sc01', 'revise')]
        # each re-check leaves out the scenes this pass still has to gate
        assert skips == [{'act1-sc02', 'act2-sc01'}, {'act2-sc01'}, set()]
        assert gate.pending(project_dir) == {}   # each came off the list as it passed

    def test_every_scene_is_listed_and_committed_before_the_gate(
            self, project_dir, monkeypatch, _no_git):
        """An interrupted run leaves each ungated scene listed (design §3)."""
        _scenes(project_dir, 'act1-sc01', 'act1-sc02')
        seen = []

        def fake(pd, sid, *a, **k):
            seen.append(sorted(gate.pending(pd)))
            raise KeyboardInterrupt
        monkeypatch.setattr(cmd_write, '_gate_drafted_scene', fake)
        with pytest.raises(KeyboardInterrupt):
            _gate_pass(project_dir, ['act1-sc01', 'act1-sc02'])
        assert seen == [['act1-sc01', 'act1-sc02']]
        assert 'not gated yet' in gate.pending(project_dir)['act1-sc02']['reason']
        assert _no_git == [('Revision: polish, before the gate',
                            ['scenes/', 'reference/', 'working/'])]

    def test_a_failure_holds_the_scenes_depending_on_it_pending(self, project_dir, monkeypatch):
        """act2-sc01 has no brief and no facts, so it waits on act1-sc02 (#641)."""
        _scenes(project_dir, 'act1-sc01', 'act1-sc02', 'act2-sc01')
        gated, _ = _stub_gate(monkeypatch, fails={'act1-sc02'})
        out = _gate_pass(project_dir, ['act1-sc01', 'act1-sc02', 'act2-sc01'])
        assert [s for s, _ in gated] == ['act1-sc01', 'act1-sc02']
        assert out[0].startswith('act1-sc02 (the gate did not pass it')
        assert ('act2-sc01 (revised, not gated: an earlier scene waits on the gate: '
                'act1-sc02)') in out[1]
        waiting = gate.pending(project_dir)
        assert set(waiting) == {'act1-sc02', 'act2-sc01'}
        assert waiting['act1-sc02']['reason'] == 'a contradiction'
        assert waiting['act2-sc01']['command'] == 'revise'
        assert 'revised by pass polish but not gated: an earlier' in \
            waiting['act2-sc01']['reason']

    def test_an_earlier_pending_scene_blocks_every_scene(self, project_dir, monkeypatch):
        _scenes(project_dir, 'act1-sc02', 'act2-sc01')
        gated, _ = _stub_gate(monkeypatch)
        gate.mark_pending(project_dir, 'act1-sc01', gate.RECHECK_FAILED, 'a contradiction')
        out = _gate_pass(project_dir, ['act1-sc02', 'act2-sc01'])
        assert gated == []
        assert 'an earlier scene waits on the gate: act1-sc01' in out[0]
        assert {'act1-sc02', 'act2-sc01'} <= set(gate.pending(project_dir))

    def test_a_recheck_that_fails_mid_pass_blocks_the_scenes_after_it(
            self, project_dir, monkeypatch):
        """The pass rewrote act1-sc01 and act2-sc01; the re-check after the
        first fails act1-sc02, between them, so act2-sc01 isn't gated."""
        _scenes(project_dir, 'act1-sc01', 'act2-sc01')

        def recheck(pd, skip):
            gate.mark_pending(pd, 'act1-sc02', gate.RECHECK_FAILED, 'a contradiction')
            return gate.Recheck(failed='act1-sc02', why='a contradiction')
        gated, _ = _stub_gate(monkeypatch, recheck=recheck)
        out = _gate_pass(project_dir, ['act1-sc01', 'act2-sc01'])
        assert gated == [('act1-sc01', 'revise')]
        assert 'an earlier scene waits on the gate: act1-sc02' in out[0]
        assert 'revised by pass polish but not gated' in \
            gate.pending(project_dir)['act2-sc01']['reason']

    def test_a_recheck_that_fails_after_the_last_scene_is_reported(
            self, project_dir, monkeypatch):
        """...so the session stops before the next pass."""
        _scenes(project_dir, 'act1-sc01')
        gated, _ = _stub_gate(monkeypatch, recheck=lambda pd, skip: gate.Recheck(
            failed='act2-sc03', why='a contradiction'))
        out = _gate_pass(project_dir, ['act1-sc01'])
        assert gated == [('act1-sc01', 'revise')]
        assert out == [f'act2-sc03 (re-checked after act1-sc01 and did not pass: a '
                       f'contradiction; listed in {gate.PENDING_PATH})']

    def test_a_recheck_over_the_threshold_is_reported(self, project_dir, monkeypatch):
        _scenes(project_dir, 'act1-sc01')
        _stub_gate(monkeypatch, recheck=lambda pd, skip: gate.Recheck(
            over_budget=True, left=['act2-sc03']))
        assert 'over the cost threshold' in _gate_pass(project_dir, ['act1-sc01'])[0]

    def test_an_unreadable_pending_file_stops_and_names_every_scene(
            self, project_dir, monkeypatch, capsys):
        _scenes(project_dir, 'act1-sc01', 'act1-sc02')
        gated, _ = _stub_gate(monkeypatch)

        def bad(pd, sid, **kw):
            raise gate.GateError('bad header')
        monkeypatch.setattr(cmd_write, '_gate_blockers', bad)
        out = _gate_pass(project_dir, ['act1-sc01', 'act1-sc02'])
        assert gated == []
        assert out == ['act1-sc01, act1-sc02 (revised, not gated: bad header)']
        assert 'ERROR: bad header' in capsys.readouterr().out

    def test_nothing_rewritten_gates_nothing(self, project_dir, monkeypatch, _no_git):
        gated, _ = _stub_gate(monkeypatch)
        assert _gate_pass(project_dir, []) == []
        assert gated == [] and _no_git == []


class TestMarkers:
    MARKER = '<!-- illustration: ill-1 -->'

    def _run(self, project_dir, monkeypatch, restore):
        scene = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        with open(scene, 'w') as f:
            f.write(f'Revised prose.\n\n{self.MARKER}\n')
        monkeypatch.setattr('storyforge.illustrations.preserve_markers', restore)

        def fix_drops_marker(pd, sid, scene_file, command, log_dir, before=None):
            with open(scene_file) as f:
                text = f.read()
            with open(scene_file, 'w') as f:
                f.write(text.replace(self.MARKER, ''))
            return True, ''
        monkeypatch.setattr(cmd_write, '_gate_drafted_scene', fix_drops_marker)
        _gate_pass(project_dir, ['act1-sc01'])
        with open(scene) as f:
            return f.read()

    def test_a_marker_the_gates_fix_drops_is_restored(self, project_dir, monkeypatch):
        marker = self.MARKER

        def restore(pd, original, rewritten):
            if marker in original and marker not in rewritten:
                return {'text': rewritten + f'\n{marker}\n', 'restored': ['ill-1'], 'lost': []}
            return {'text': rewritten, 'restored': [], 'lost': []}
        assert marker in self._run(project_dir, monkeypatch, restore)

    def test_one_it_cannot_restore_is_warned(self, project_dir, monkeypatch, capsys):
        self._run(project_dir, monkeypatch,
                  lambda pd, o, r: {'text': r, 'restored': [], 'lost': ['ill-1']})
        out = capsys.readouterr().out
        assert "WARNING: illustration marker 'ill-1'" in out
        assert 'storyforge illustrate --embed' in out

    def test_one_already_reported_lost_is_not_warned_twice(self, project_dir, monkeypatch,
                                                           capsys):
        scene = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        monkeypatch.setattr('storyforge.illustrations.preserve_markers',
                            lambda pd, o, r: {'text': r, 'restored': [], 'lost': ['ill-1']})
        cmd_revise._restore_gate_markers(project_dir, 'act1-sc01', scene, 'x', ['ill-1'])
        assert 'WARNING' not in capsys.readouterr().out


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
    out = _gate_pass(project_dir, ['act1-sc01'])
    assert out and out[0].startswith('act1-sc01')
    row = gate.pending(project_dir)['act1-sc01']
    assert row['command'] == 'revise'
    assert 'facts are still in the ledger and may no longer match' in row['reason']


class TestPassBlocked:
    """A prose pass doesn't start (or spend) when the gate couldn't get
    through what it writes."""

    def test_a_pending_scene_before_the_targets_stops_it(self, project_dir):
        gate.mark_pending(project_dir, 'act1-sc01', 'redraft', 'a contradiction')
        with pytest.raises(SystemExit) as e:
            cmd_revise._exit_if_pass_blocked(project_dir, 'act2-sc01;act1-sc02')
        assert e.value.code == 1

    def test_a_pending_scene_between_the_targets_stops_it(self, project_dir, capsys):
        gate.mark_pending(project_dir, 'new-x1', 'redraft', 'a contradiction')
        with pytest.raises(SystemExit):
            cmd_revise._exit_if_pass_blocked(project_dir, 'act1-sc02;act2-sc01')
        assert 'nothing spent' in capsys.readouterr().out

    def test_a_scene_listed_only_for_a_recheck_between_them_does_not(self, project_dir):
        gate.mark_pending(project_dir, 'new-x1', gate.RECHECK, 're-check: x changed')
        cmd_revise._exit_if_pass_blocked(project_dir, 'act1-sc02;act2-sc01')

    def test_a_pending_scene_the_pass_rewrites_does_not(self, project_dir):
        gate.mark_pending(project_dir, 'act1-sc02', 'redraft', 'a contradiction')
        cmd_revise._exit_if_pass_blocked(project_dir, 'act1-sc02;act2-sc01')
        cmd_revise._exit_if_pass_blocked(project_dir, '')  # full scope: every scene

    def test_targets_that_are_not_scenes_mean_every_scene(self, project_dir):
        from storyforge import ledger
        assert cmd_revise._pass_scene_ids(project_dir, 'Dorren Hayle;NEW:bridge') == \
            list(ledger.scene_order(project_dir))


class TestMainPassLoopIsGated:
    """`revise`'s main pass loop."""

    def _run(self, project_dir, monkeypatch, fails=(), coaching=None, committed=None):
        if coaching:
            monkeypatch.setenv('STORYFORGE_COACHING', coaching)
        gated, _ = _stub_gate(monkeypatch, fails)
        revise_tests.TestOwedScenes()._run(project_dir, monkeypatch, ['act1-sc02', 'act1-sc01'],
                                           [], [], committed if committed is not None else [])
        return gated

    def test_the_scenes_a_pass_wrote_are_gated(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        plan_file = _run_pass_setup(project_dir, monkeypatch, 'craft')
        mock_api.set_response('=== SCENE: act1-sc01 === ...')
        gated = self._run(project_dir, monkeypatch)
        assert gated == [('act1-sc01', 'revise'), ('act1-sc02', 'revise')]
        assert _read_csv_plan(plan_file)[0]['status'] == 'completed'

    def test_the_gate_gets_each_scene_as_it_was_before_the_pass(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        """2026-11-01: a contradiction already in the scene doesn't stop a pass."""
        _run_pass_setup(project_dir, monkeypatch, 'craft')
        old = {}
        for sid in ('act1-sc01', 'act1-sc02'):
            with open(os.path.join(project_dir, 'scenes', f'{sid}.md')) as f:
                old[sid] = f.read()
        mock_api.set_response('=== SCENE: act1-sc01 === ...')
        self._run(project_dir, monkeypatch)
        assert set(BEFORES) == set(old)
        snaps = list(BEFORES.values())
        assert snaps[0] is snaps[1]   # one baseline, taken before the pass
        assert {sid: snaps[0].scenes[sid] for sid in old} == old

    def test_a_scene_the_gate_fails_stops_the_session_after_committing(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        plan_file = _run_pass_setup(project_dir, monkeypatch, 'craft')
        mock_api.set_response('=== SCENE: act1-sc01 === ...')
        committed = []
        with pytest.raises(SystemExit) as e:
            self._run(project_dir, monkeypatch, fails={'act1-sc01'}, committed=committed)
        assert e.value.code == 1
        out = capsys.readouterr().out
        assert 'not everything it changed passed the gate' in out
        assert 'act1-sc02 (revised, not gated' in out
        assert '`storyforge check --pending`' in out
        assert "re-run `storyforge revise` for the plan's passes left" in out
        # the pass's scenes and its completed status are committed before the stop
        assert len(committed) == 3   # the pass, before the gate, the stop
        assert _read_csv_plan(plan_file)[0]['status'] == 'completed'
        assert set(gate.pending(project_dir)) == {'act1-sc01', 'act1-sc02'}

    def test_a_pending_scene_stops_the_pass_before_it_spends(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        plan_file = _run_pass_setup(project_dir, monkeypatch, 'craft')
        mock_api.set_response('=== SCENE: act1-sc01 === ...')
        rows = _read_csv_plan(plan_file)
        rows[0]['targets'] = 'act2-sc01'
        _write_csv_plan(plan_file, rows)
        gate.mark_pending(project_dir, 'act1-sc01', 'redraft', 'a contradiction')
        with pytest.raises(SystemExit):
            main([])
        assert not mock_api.calls

    def test_prose_a_coach_level_pass_writes_is_still_gated(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        _run_pass_setup(project_dir, monkeypatch, 'craft')
        mock_api.set_response('=== SCENE: act1-sc01 === ...')
        gated = self._run(project_dir, monkeypatch, coaching='coach')
        assert [s for s, _ in gated] == ['act1-sc01', 'act1-sc02']

    def test_a_structural_pass_runs_behind_a_pending_scene_ungated(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        plan_file = _run_pass_setup(project_dir, monkeypatch, 'structural')
        gated, _ = _stub_gate(monkeypatch)
        gate.mark_pending(project_dir, 'act1-sc01', 'redraft', 'a contradiction')
        mock_api.set_response('```briefs-csv\nid|goal\nact1-sc01|A sharper goal\n```')
        main([])
        assert _read_csv_plan(plan_file)[0]['status'] == 'completed'
        assert gated == []

    def test_a_skipped_scene_and_a_gate_failure_both_reported(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        _run_pass_setup(project_dir, monkeypatch, 'craft')
        mock_api.set_response('=== SCENE: act1-sc01 === ...')
        _stub_gate(monkeypatch, fails={'act1-sc01'})
        with pytest.raises(SystemExit):
            revise_tests.TestOwedScenes()._run(project_dir, monkeypatch, ['act1-sc01'],
                                               ['act1-sc02'], [], [])
        out = capsys.readouterr().out
        assert 'the gate did not pass everything this pass changed' in out
        assert 'act1-sc02: appears to end mid-sentence' in out

    def test_scenes_awaiting_the_deferred_redraft_are_named(self, capsys):
        with pytest.raises(SystemExit):
            cmd_revise._fail_gated_pass('craft', ['x (the gate did not pass it)'],
                                        cmd_revise.PLAN_RESUME, {'act2-sc01', 'act1-sc02'})
        out = capsys.readouterr().out
        assert 'still have their old prose: act1-sc02, act2-sc01' in out


class TestInteractivePass:
    """The CLI session writes scene files itself."""

    def _run(self, project_dir, monkeypatch, rewrite, heads=('a', 'a')):
        _run_pass_setup(project_dir, monkeypatch, 'craft')
        gated, _ = _stub_gate(monkeypatch)
        real_run = sp.run

        def run(cmd, **kwargs):
            if cmd and cmd[0] == 'claude':
                for sid in rewrite:
                    with open(os.path.join(project_dir, 'scenes', f'{sid}.md'), 'w') as f:
                        f.write(PROSE)
                return sp.CompletedProcess(cmd, 0, stdout='', stderr='')
            if 'build-prompt' in ' '.join(str(c) for c in cmd):
                return sp.CompletedProcess(cmd, 0, stdout='Revision prompt.', stderr='')
            return sp.CompletedProcess(cmd, 0, stdout='', stderr='')
        monkeypatch.setattr('subprocess.run', run)
        head = iter(heads)

        def git(pd, *args, check=True):
            out = next(head, heads[-1]) if args[:2] == ('rev-parse', 'HEAD') else ''
            return sp.CompletedProcess(args, 0, stdout=out, stderr='')
        monkeypatch.setattr(cmd_revise, '_git', git)
        commits = []
        monkeypatch.setattr('storyforge.git.commit_and_push',
                            lambda d, msg, paths=None: commits.append((msg, paths)) or True)
        main(['--interactive'])
        return gated, commits

    def test_the_scenes_the_session_rewrote_are_gated(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        with open(os.path.join(project_dir, 'scenes', 'act1-sc02.md')) as f:
            old = f.read()
        gated, _ = self._run(project_dir, monkeypatch, ['act1-sc02'])
        assert gated == [('act1-sc02', 'revise')]
        # #480's review: the baseline is the scene before the session wrote it
        with open(os.path.join(project_dir, 'scenes', 'act1-sc02.md')) as f:
            assert f.read() != old
        assert BEFORES['act1-sc02'].scenes['act1-sc02'] == old

    def test_when_the_session_committed_the_gates_work_gets_its_own_commit(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        _, commits = self._run(project_dir, monkeypatch, ['act1-sc02'], heads=('a', 'b'))
        assert ('Revision: gate the scenes of the-pass',
                ['scenes/', 'reference/', 'working/']) in commits


class TestPolishLoopPassIsGated:
    """The polish loop's pass (`_execute_single_pass`)."""

    REPLY = ('=== SCENE: act1-sc01 ===\n' + 'The rain kept on. ' * 50
             + '\n=== END SCENE: act1-sc01 ===')

    def _run(self, project_dir, monkeypatch, reply=None):
        return revise_tests.TestPolishLoopPass()._run(project_dir, monkeypatch,
                                                      reply or self.REPLY)

    def test_the_scene_it_wrote_is_gated(self, project_dir, monkeypatch):
        gated, _ = _stub_gate(monkeypatch)
        rows, _, _ = self._run(project_dir, monkeypatch)
        assert gated == [('act1-sc01', 'revise')]
        assert rows[0]['status'] == 'completed'

    def test_the_gate_gets_the_scene_as_it_was_before_the_pass(self, project_dir, monkeypatch):
        with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md')) as f:
            old = f.read()
        _stub_gate(monkeypatch)
        self._run(project_dir, monkeypatch)
        assert BEFORES['act1-sc01'].scenes['act1-sc01'] == old
        assert 'The rain kept on.' not in old

    def test_a_scene_the_gate_fails_stops_the_loop_after_committing(
            self, project_dir, monkeypatch, capsys):
        _stub_gate(monkeypatch, fails={'act1-sc01'})
        with pytest.raises(SystemExit) as e:
            self._run(project_dir, monkeypatch)
        assert e.value.code == 1
        out = capsys.readouterr().out
        assert 'not everything it changed passed the gate' in out
        assert 're-run `storyforge revise --polish --loop`' in out
        assert 'act1-sc01' in gate.pending(project_dir)
        rows = _read_csv_plan(os.path.join(project_dir, 'working', 'plans',
                                           'revision-plan.csv'))
        assert rows[0]['status'] == 'completed'   # written before the commit, so in it

    def test_it_is_built_at_the_loops_coaching_level(self, project_dir, monkeypatch):
        """Built without `--coaching`, the prompt asked for prose at every level."""
        monkeypatch.setenv('STORYFORGE_COACHING', 'coach')
        built = []

        def run(cmd, **kwargs):
            built.append([str(c) for c in cmd])
            raise SystemExit('stop after the build')
        monkeypatch.setattr('subprocess.run', run)
        monkeypatch.setattr('storyforge.common.build_shared_context', lambda *a, **k: [])
        rows = revise_tests._make_plan_rows()
        plan_file = revise_tests._write_plan(project_dir, rows)
        with pytest.raises(SystemExit):
            cmd_revise._execute_single_pass(project_dir, plan_file, rows, 1)
        assert 'build-prompt' in built[0]
        assert built[0][built[0].index('--coaching') + 1] == 'coach'

    def test_behind_a_pending_scene_it_spends_nothing(self, project_dir, monkeypatch):
        _stub_gate(monkeypatch)
        gate.mark_pending(project_dir, 'act1-sc01', 'redraft', 'a contradiction')
        calls = []
        monkeypatch.setattr('storyforge.api.invoke_to_file',
                            lambda *a, **k: calls.append(a) or pytest.fail('spent'))
        rows = revise_tests._make_plan_rows()
        rows[0]['targets'] = 'act2-sc01'
        plan_file = revise_tests._write_plan(project_dir, rows)
        monkeypatch.setattr('storyforge.common.build_shared_context', lambda *a, **k: [])
        monkeypatch.setattr('subprocess.run', lambda cmd, **k: sp.CompletedProcess(
            cmd, 0, stdout='Prompt text', stderr=''))
        with pytest.raises(SystemExit):
            cmd_revise._execute_single_pass(project_dir, plan_file, rows, 1)
        assert calls == []


class TestAFailedCommitStopsRevise:
    """SF-3 (#503's review): revise ignored every `commit_and_push` result,
    so a failed commit was silent and the session went on (and paid)."""

    def test_the_gate_is_not_run_after_a_failed_commit(self, project_dir, monkeypatch,
                                                       capsys):
        _scenes(project_dir, 'act1-sc01')
        gated, _ = _stub_gate(monkeypatch)
        import storyforge.git as sfgit

        def fail(*a, **k):
            sfgit.last_commit_error = 'error: unable to create index.lock'
            return False
        monkeypatch.setattr('storyforge.git.commit_and_push', fail)
        with pytest.raises(SystemExit) as e:
            _gate_pass(project_dir, ['act1-sc01'])
        assert e.value.code == 1 and gated == []
        out = capsys.readouterr().out
        assert 'ERROR: the commit "Revision: polish, before the gate" failed: error: unable ' \
            'to create index.lock' in out

    def test_nothing_to_commit_carries_on(self, project_dir, monkeypatch):
        _scenes(project_dir, 'act1-sc01')
        gated, _ = _stub_gate(monkeypatch)
        import storyforge.git as sfgit

        def nothing(*a, **k):
            sfgit.last_commit_error = sfgit.NOTHING_TO_COMMIT
            return False
        monkeypatch.setattr('storyforge.git.commit_and_push', nothing)
        _gate_pass(project_dir, ['act1-sc01'])
        assert gated == [('act1-sc01', 'revise')]


class TestReviseForecast:
    """CR-1: the passes had no up-front threshold check, yet their spend
    came out of the re-checks' budget."""

    def test_passes_over_the_threshold_spend_nothing(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        revise_tests._run_pass_setup(project_dir, monkeypatch, 'craft')
        mock_costs.threshold_ok = False
        with pytest.raises(SystemExit) as e:
            main([])
        assert e.value.code == 1
        assert mock_api.call_count == 0 and not mock_git.calls_for('commit_and_push')
        assert 'is over the cost threshold' in capsys.readouterr().out

    def test_the_redraft_recheck_reserves_the_scenes_still_to_gate(self, monkeypatch):
        """T-8: `_recheck_after` (revise's redrafts) reserves the gate runs
        the scenes still to redraft owe, and the passes still to run."""
        from storyforge.costs import RunBudget
        seen = []
        monkeypatch.setattr(cmd_write, 'run_recheck',
                            lambda pd, ld, skip=frozenset(), spent_before=0.0:
                            seen.append(spent_before))
        budget = RunBudget()
        budget.owed = 4.0
        cmd_revise._recheck_after('/p', '/l', {'a', 'b'}, budget)
        assert seen == [pytest.approx(4.0 + 2 * gate.RECHECK_COST_PER_SCENE)]


class TestNaturalnessForecast:
    """#503 left `--naturalness` with no up-front forecast before its brief
    fixes and redrafts: they spent unchecked, and their spend came out of
    the re-checks' budget. Costs here: a scene's fix and redraft $3, a pass
    $10; naturalness has 3 passes."""

    def _setup(self, project_dir, monkeypatch, mock_git, threshold, charge=0.0, fixed=(),
               gate_runs=None):
        revise_tests._run_pass_setup(project_dir, monkeypatch, 'craft')
        # the gate's foreseen runs are #619's (TestDeferRechecksToLaterPasses)
        monkeypatch.setattr(cmd_revise, '_foreseen_gate_runs',
                            lambda *a: gate_runs or cmd_revise.GateForecast(0, 0, 0))
        monkeypatch.setattr(cmd_revise, '_detect_upstream_scenes',
                            lambda p, rows: ['act1-sc01'])
        monkeypatch.setattr(cmd_revise, '_upstream_fix_cost', lambda p, ids: 3.0 * len(ids))
        monkeypatch.setattr(cmd_revise, '_pass_cost', lambda p, m: 10.0)
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', str(threshold))
        seen = []

        def fake_fix(p, ids):
            budget = cmd_revise._run_budget()
            seen.append((budget.owed, len(mock_git.calls_for('create_branch'))))
            budget.charge(charge)   # what the fixes cost
            return list(fixed), {} if fixed else {'act1-sc01': 'no reply'}
        monkeypatch.setattr(cmd_revise, '_fix_and_redraft', fake_fix)
        return seen

    def _plan_target(self, project_dir):
        return os.readlink(os.path.join(project_dir, 'working', 'plans',
                                        'revision-plan.csv'))

    def _link_plan(self, project_dir):
        """revision-plan.csv as a link to a numbered plan, as revise leaves it."""
        plans = os.path.join(project_dir, 'working', 'plans')
        os.replace(os.path.join(plans, 'revision-plan.csv'),
                   os.path.join(plans, 'revision-plan-7.csv'))
        os.symlink('revision-plan-7.csv', os.path.join(plans, 'revision-plan.csv'))

    def test_over_the_threshold_nothing_is_spent_written_or_branched(
            self, mock_api, mock_git, project_dir, monkeypatch, capsys):
        """SF-3, SF-4, T-6 (#510's review): the refused run had already
        pointed revision-plan.csv at the naturalness plan."""
        seen = self._setup(project_dir, monkeypatch, mock_git, 32)
        self._link_plan(project_dir)
        with pytest.raises(SystemExit) as e:
            main(['--naturalness'])
        assert e.value.code == 1
        assert seen == [] and mock_api.call_count == 0
        assert mock_git.calls == []   # no branch, no PR, no commit
        assert self._plan_target(project_dir) == 'revision-plan-7.csv'
        out = capsys.readouterr().out
        assert 'Upstream issues in 1 scene(s): act1-sc01' in out
        assert 'Cost forecast: ~$33.00: brief fixes and redrafts for 1 scene(s) ~$3.00' in out
        assert 'the forecast (~$33.00) is over the cost threshold ($32): nothing revised. ' \
            'Raise STORYFORGE_COST_THRESHOLD, or fix the briefs of act1-sc01 first ' \
            '(`storyforge hone`), or start from a later pass (`storyforge revise N`)' in out

    def test_the_foreseen_gate_runs_count_against_the_threshold(
            self, mock_api, mock_git, project_dir, monkeypatch, capsys):
        """#619: a "~$4.51" plan cost ~$80: the forecast left out the gate on
        each rewritten scene; now the gate on each planned rewrite counts
        against the threshold, and what it can't count is named."""
        seen = self._setup(project_dir, monkeypatch, mock_git, 34,
                           gate_runs=cmd_revise.GateForecast(4, 6, 9, ('pass 2: x',)))
        with pytest.raises(SystemExit) as e:
            main(['--naturalness'])
        assert e.value.code == 1 and seen == [] and mock_api.call_count == 0
        out = capsys.readouterr().out
        gate_cost = 4 * gate.RECHECK_COST_PER_SCENE
        assert f'Cost forecast: ~${33 + gate_cost:.2f}' in out
        assert f'the gate on the 4 scene rewrite(s) they name ~${gate_cost:.2f}' in out
        assert 'what the full-scope passes rewrite, up to 6 scene(s)' in out
        assert 're-checks of the 9 scene(s) after them that no pass rewrites' in out
        assert 'WARNING: pass 2: x' in out

    def test_a_later_start_forecasts_only_the_passes_it_runs(
            self, mock_api, mock_git, project_dir, monkeypatch, capsys):
        """CR-L1: `revise 3 --naturalness` forecast all 3 passes."""
        self._setup(project_dir, monkeypatch, mock_git, 12)
        with pytest.raises(SystemExit):
            main(['--naturalness', '3'])
        out = capsys.readouterr().out
        assert 'Cost forecast: ~$13.00' in out and '1 passes @ ~$10.00' in out

    def test_a_dry_run_forecasts_the_fixes_and_spends_nothing(
            self, mock_api, mock_git, project_dir, monkeypatch, capsys):
        """SF-1/T-3: a dry run paid for the fixes and committed them, on
        whatever branch was checked out."""
        seen = self._setup(project_dir, monkeypatch, mock_git, 1, fixed=['act1-sc01'])
        main(['--naturalness', '--dry-run'])
        assert seen == [] and mock_api.call_count == 0
        assert not mock_git.calls_for('commit_and_push')
        out = capsys.readouterr().out
        assert 'Upstream issues in 1 scene(s): act1-sc01' in out
        assert 'DRY RUN: their brief fixes and redrafts (~$3.00) are skipped' in out

    @pytest.mark.parametrize('fixed, done', [
        ([], 'no pass run; the brief fixes changed nothing'),
        (['act1-sc01'], 'no pass run; the brief fixes and redrafts of act1-sc01 are '
                        'committed'),
    ])
    def test_the_passes_are_reserved_then_checked_with_what_the_fixes_spent(
            self, mock_api, mock_git, project_dir, monkeypatch, capsys, fixed, done):
        """SF-4, SF-7, C-1: the fixes run on the run's branch; the stop says
        what they did and names the spend apart from the forecast."""
        seen = self._setup(project_dir, monkeypatch, mock_git, 50, charge=30.0, fixed=fixed)
        with pytest.raises(SystemExit) as e:
            main(['--naturalness'])
        assert e.value.code == 1
        assert seen == [(30.0, 1)]   # the 3 passes kept back; on the branch
        assert mock_api.call_count == 0   # no pass run
        commits = [c[1] for c in mock_git.calls_for('commit_and_push')]
        assert commits == (['Naturalness: upstream brief fixes for 1 scenes'] if fixed else [])
        out = capsys.readouterr().out
        assert 'spent so far ~$30.00 + forecast ~$30.00 = ~$60.00 is over the cost ' \
            f'threshold ($50): {done}' in out


class TestDeferRechecksToLaterPasses:
    """#619 (Telemachy, 2026-11-07): a one-scene pass at the book's start
    re-checked the 27 scenes after it (~$26) that the act passes then
    rewrote and gated again. A re-check of a scene a later pass of the plan
    rewrites waits for that pass's gate, and doesn't block the scenes gated
    before it; what's left is re-checked once, after the last pass."""

    def _plan(self, *passes):
        return [dict({'name': f'p{i}', 'status': 'pending', 'fix_location': 'craft',
                      'scope': 'full', 'targets': '', 'owed': ''}, **p)
                for i, p in enumerate(passes, 1)]

    def test_the_scenes_later_passes_rewrite(self, project_dir):
        plan = self._plan({'scope': 'act1-sc01'},
                          {'scope': 'targeted', 'targets': 'act1-sc02;new-x1'},
                          {'scope': 'act2-sc01', 'status': 'completed'},
                          {'scope': 'act2-sc01', 'fix_location': 'structural'})
        assert cmd_revise._later_pass_scenes(project_dir, plan, 1, 4) == {'act1-sc02', 'new-x1'}
        assert cmd_revise._later_pass_scenes(project_dir, plan, 2, 4) == frozenset()

    def test_owed_scenes_are_what_a_pass_rewrites(self, project_dir):
        plan = self._plan({}, {'scope': 'full', 'owed': 'act2-sc01'})
        assert cmd_revise._later_pass_scenes(project_dir, plan, 1, 2) == {'act2-sc01'}

    def test_a_scope_that_cannot_be_resolved_defers_nothing(self, project_dir):
        plan = self._plan({}, {'scope': 'no-such-scene'})
        assert cmd_revise._later_pass_scenes(project_dir, plan, 1, 2) == frozenset()

    def test_the_foreseen_gate_runs(self, project_dir):
        """Two rewrites; of the scenes with prose after act1-sc02, act2-sc01
        is rewritten too, so new-x1 is the one scene a re-check can reach."""
        plan = self._plan({'scope': 'act1-sc02'}, {'scope': 'act2-sc01'},
                          {'scope': 'act1-sc01', 'status': 'completed'})
        f = cmd_revise._foreseen_gate_runs(project_dir, plan, 1, 3)
        assert (f.rewrites, f.full_upto, f.recheck_scenes, f.notes) == (2, 0, 1, ())

    def test_a_scene_two_passes_rewrite_counts_twice_and_a_start_skips_earlier(
            self, project_dir):
        plan = self._plan({'scope': 'act1-sc01'}, {'scope': 'act1-sc02'},
                          {'scope': 'act1-sc02'})
        assert cmd_revise._foreseen_gate_runs(project_dir, plan, 2, 3).rewrites == 2

    def test_a_full_pass_is_named_not_counted(self, project_dir):
        """A full pass may rewrite any scene: its gate runs are named in the
        forecast, never counted against the threshold."""
        f = cmd_revise._foreseen_gate_runs(project_dir, self._plan({}), 1, 1)
        assert f.rewrites == 0 and f.full_upto == 4 and f.recheck_scenes == 0

    def test_hone_and_structural_passes_foresee_nothing(self, project_dir):
        plan = self._plan({'fix_location': 'brief'}, {'fix_location': 'structural'})
        assert cmd_revise._foreseen_gate_runs(project_dir, plan, 1, 2) == (0, 0, 0, ())

    def test_what_cannot_be_foreseen_says_so(self, project_dir, monkeypatch):
        plan = self._plan({'scope': 'no-such-scene'}, {'scope': 'act1-sc02'})
        f = cmd_revise._foreseen_gate_runs(project_dir, plan, 1, 2)
        assert f.rewrites == 1 and f.notes[0].startswith("pass 1: scope 'no-such-scene'")
        from storyforge import ledger

        def bad(pd):
            raise ValueError('scene x has no seq')
        monkeypatch.setattr(ledger, 'scene_order', bad)
        f = cmd_revise._foreseen_gate_runs(project_dir, plan, 2, 2)
        assert f.recheck_scenes is None and 'no seq' in f.notes[-1]

    def test_a_pass_that_left_a_planned_scene_alone_rechecks_it_first(
            self, project_dir, monkeypatch, tmp_path):
        """#622's review (CR-1): pass 1's re-check of act1-sc02 waited for
        pass 2, whose reply rewrote only act2-sc01; act1-sc02 then blocked
        pass 2's gating and the session stopped."""
        gate.mark_pending(project_dir, 'act1-sc02', gate.RECHECK, 'x')
        calls = []

        def recheck(pd, ld, skip, budget, reserved=0.0):
            calls.append(set(skip))
            gate.clear_pending(pd, 'act1-sc02')
        monkeypatch.setattr(cmd_revise, '_commit', lambda *a, **k: None)
        monkeypatch.setattr(cmd_write, '_gate_drafted_scene', lambda *a, **k: (True, ''))
        monkeypatch.setattr(cmd_write, 'budgeted_recheck', recheck)
        out = cmd_revise._gate_pass_scenes(project_dir, ['act2-sc01'], 'p', str(tmp_path))
        assert out == [] and calls[0] == {'act2-sc01'}

    def test_a_deferred_recheck_does_not_block(self, project_dir, monkeypatch):
        gate.mark_pending(project_dir, 'act1-sc02', gate.RECHECK, 'x')
        gate.mark_pending(project_dir, 'new-x1', gate.RECHECK_FAILED, 'y')
        lines = ['act1-sc02: x', 'new-x1: y']
        assert cmd_revise._not_deferred(project_dir, lines, frozenset()) == lines
        # a failed re-check still blocks: the author acts on it
        assert cmd_revise._not_deferred(project_dir, lines,
                                        frozenset({'act1-sc02', 'new-x1'})) == ['new-x1: y']

    def test_a_deferred_recheck_does_not_stop_a_pass_before_it_starts(self, project_dir):
        """#622's review: the pass-start check (`_exit_if_pass_blocked`) still
        exited on a re-check deferred to a later pass."""
        gate.mark_pending(project_dir, 'act1-sc02', gate.RECHECK, 'x')
        cmd_revise._exit_if_pass_blocked(project_dir, 'act2-sc01', frozenset({'act1-sc02'}))
        with pytest.raises(SystemExit):
            cmd_revise._exit_if_pass_blocked(project_dir, 'act2-sc01')
        gate.mark_pending(project_dir, 'act1-sc02', gate.RECHECK_FAILED, 'x')
        with pytest.raises(SystemExit):
            cmd_revise._exit_if_pass_blocked(project_dir, 'act2-sc01',
                                             frozenset({'act1-sc02'}))

    def test_the_gated_scenes_rechecks_skip_later_passes_scenes(
            self, project_dir, monkeypatch, tmp_path):
        skips = []
        monkeypatch.setattr(cmd_revise, '_commit', lambda *a, **k: None)
        monkeypatch.setattr(cmd_write, '_gate_drafted_scene', lambda *a, **k: (True, ''))
        monkeypatch.setattr(cmd_write, 'budgeted_recheck',
                            lambda pd, ld, skip, budget, reserved=0.0: skips.append(set(skip)))
        cmd_revise._gate_pass_scenes(project_dir, ['act1-sc01', 'act1-sc02'], 'p',
                                     str(tmp_path), deferred=frozenset({'act2-sc01'}))
        assert skips == [{'act1-sc02', 'act2-sc01'}, {'act2-sc01'}]

    def test_after_the_last_pass_what_is_left_is_rechecked_once(self, monkeypatch):
        from storyforge.gate import Recheck
        calls = []

        def fake(pd, ld, skip, budget, reserved=0.0):
            calls.append(set(skip))
            return Recheck(failed='act2-sc01', why='a contradiction')
        monkeypatch.setattr(cmd_write, 'budgeted_recheck', fake)
        why = cmd_revise._final_rechecks('/p', '/l')
        assert calls == [set()] and why.startswith('act2-sc01 (re-checked after the last pass')
        monkeypatch.setattr(cmd_write, 'budgeted_recheck', lambda *a, **k: None)
        assert cmd_revise._final_rechecks('/p', '/l') == ''


class TestDeferralThroughMain:
    """#622's review (T-3): the pass loop hands each pass the scenes later
    passes may rewrite, and what is left after the last pass is re-checked
    once; one that fails there exits 1, after the summary."""

    def _run(self, project_dir, monkeypatch, mock_git, final, argv=()):
        import subprocess as sp
        from storyforge import costs
        _run_pass_setup(project_dir, monkeypatch, 'craft')
        rows = revise_tests._make_plan_rows(('a', 'b'))
        rows[0]['scope'], rows[1]['scope'] = 'act1-sc01', 'act2-sc01'
        revise_tests._write_plan(project_dir, rows)
        n = [0]

        def run(cmd, **kwargs):
            joined = ' '.join(str(c) for c in cmd)
            if 'build-prompt' in joined:
                return sp.CompletedProcess(cmd, 0, stdout='Revision prompt.', stderr='')
            if 'extract-scenes' in joined:
                n[0] += 1
                with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md'), 'w') as f:
                    f.write(f'Revised prose {n[0]}.\n')
                return sp.CompletedProcess(cmd, 0, stdout='Wrote: act1-sc01\n', stderr='')
            return sp.CompletedProcess(cmd, 0, stdout='', stderr='')
        monkeypatch.setattr('subprocess.run', run)
        monkeypatch.setattr(cmd_revise.time, 'sleep', lambda s: None)
        seen, finals = [], []

        def gate_pass(pd, ids, name, ld, before=None, deferred=frozenset()):
            seen.append(deferred)
            return []
        monkeypatch.setattr(cmd_revise, '_gate_pass_scenes', gate_pass)

        def budgeted(pd, ld, skip, budget, reserved=0.0):
            finals.append(set(skip))
            return final
        monkeypatch.setattr(cmd_write, 'budgeted_recheck', budgeted)
        monkeypatch.setattr(costs, 'log_operation', lambda *a, **k: None)
        return seen, finals

    def test_each_pass_gets_the_later_passes_scenes(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        mock_api.set_response('=== SCENE: act1-sc01 === ...')
        deferred, finals = self._run(project_dir, monkeypatch, mock_git, None)
        main([])
        assert deferred == [frozenset({'act2-sc01'}), frozenset()]
        assert finals == [set()]   # the final re-check, nothing skipped

    def test_a_final_recheck_that_fails_exits_1(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        mock_api.set_response('=== SCENE: act1-sc01 === ...')
        self._run(project_dir, monkeypatch, mock_git,
                  gate.Recheck(failed='new-x1', why='a contradiction'))
        with pytest.raises(SystemExit) as e:
            main([])
        assert e.value.code == 1
        out = capsys.readouterr().out
        assert 'a re-check they owed did not finish: new-x1 (re-checked after the last' in out
        assert 'All revision passes are done' not in out
