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


class TestGatePassScenes:

    def test_each_scene_gets_its_own_prose_before_the_pass(self, project_dir, monkeypatch):
        _scenes(project_dir, 'act1-sc01', 'act1-sc02')
        _stub_gate(monkeypatch)
        cmd_revise._gate_pass_scenes(project_dir, ['act1-sc01', 'act1-sc02'], 'polish',
                                     str(project_dir), before={'act1-sc01': 'old one'})
        assert BEFORES == {'act1-sc01': 'old one', 'act1-sc02': None}

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

    def test_the_first_failure_stops_and_lists_the_rest_pending(self, project_dir, monkeypatch):
        _scenes(project_dir, 'act1-sc01', 'act1-sc02', 'act2-sc01')
        gated, _ = _stub_gate(monkeypatch, fails={'act1-sc02'})
        out = _gate_pass(project_dir, ['act1-sc01', 'act1-sc02', 'act2-sc01'])
        assert [s for s, _ in gated] == ['act1-sc01', 'act1-sc02']
        assert out[0].startswith('act1-sc02 (the gate did not pass it')
        assert 'act2-sc01 (revised, not gated: the gate stopped at act1-sc02)' in out[1]
        waiting = gate.pending(project_dir)
        assert set(waiting) == {'act1-sc02', 'act2-sc01'}
        assert waiting['act1-sc02']['reason'] == 'a contradiction'
        assert waiting['act2-sc01']['command'] == 'revise'
        assert 'revised by pass polish but not gated: the gate' in waiting['act2-sc01']['reason']

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

        def bad(pd, sid):
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
        assert BEFORES == old

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
        assert len(committed) == 2
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
        monkeypatch.setattr(cmd_revise, 'commit_and_push',
                            lambda d, msg, paths=None: commits.append((msg, paths)))
        main(['--interactive'])
        return gated, commits

    def test_the_scenes_the_session_rewrote_are_gated(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        gated, _ = self._run(project_dir, monkeypatch, ['act1-sc02'])
        assert gated == [('act1-sc02', 'revise')]

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
        assert BEFORES == {'act1-sc01': old} and 'The rain kept on.' not in old

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
