"""#788: a scene whose plan calls for changing a fixed fact (Wrath Like
Smoke: armour read as a fixed trait, traded away in
`glaucus-and-diomedes-trade-armour`) halted, was sent to the fix as a prose
problem no edit could repair, and the author had no command to clear it.

Now the halt is marked as one the plan calls for: reported as a likely
mis-typing, never sent to the fix, and `audit.unfix` (`check --unfix`)
makes the fact a state fact in the ledger, the snapshot and the log."""

import os

import pytest

from storyforge import audit, gate, ledger
from storyforge.audit import Halt

from test_gate import SCENE, _commitment, _gate, _pure_prose_scenes  # noqa: F401 (autouse)

ARMOUR_QUOTE = 'population four hundred and twelve at last census'


def _add(project_dir, **row):
    rows = ledger.load(project_dir)
    rows.append(dict({c: '' for c in ledger.COLUMNS}, status='binding', **row))
    ledger.save(project_dir, rows, command='test')


def _fixed_armour(project_dir):
    _add(project_dir, id='tessa-gold-armour', scene_id='act1-sc01', type='trait',
         subject='tessa-merrin', statement='Tessa wears gold armour', origin='prose',
         mutable='fixed', introduced_by='draft')


def _trade(**over):
    return _commitment(type='physical', subject='tessa-merrin',
                       statement='Tessa wears bronze armour', quote=ARMOUR_QUOTE,
                       mutable='state', supersedes='tessa-gold-armour', **over)


def _set_brief(project_dir, **cols):
    path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    header = lines[0].split('|')
    for n, line in enumerate(lines[1:], start=1):
        cells = line.split('|')
        if cells[0] == SCENE:
            for col, value in cols.items():
                cells[header.index(col)] = value
            lines[n] = '|'.join(cells)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


class TestAHaltThePlanCallsFor:

    def test_a_plan_fact_set_here_marks_the_halt(self, project_dir, tmp_path):
        _fixed_armour(project_dir)
        _add(project_dir, id='tessa-armour-traded', scene_id=SCENE, type='physical',
             subject='tessa-merrin', statement='Tessa traded her gold armour for bronze',
             origin='plan', mutable='state', introduced_by='briefs')
        result = _gate(project_dir, tmp_path, [_trade()])
        assert [h.kind for h in result.halts] == ['supersedes-fixed']
        h = result.halts[0]
        assert h.fixed_id == 'tessa-gold-armour' and 'tessa-armour-traded' in h.planned
        assert not result.passed and not result.committed
        # reported to the author as a mis-typing, with the command to clear it
        lines = gate.report_lines(result)
        halt = next(x for x in lines if x.startswith('HALT'))
        assert 'likely mis-typed fixed' in halt
        assert '`storyforge check --unfix tessa-gold-armour`' in halt
        assert halt in gate.blocking_lines(lines)
        # never sent to the fix
        assert gate.problems_to_fix(result) == []
        assert 'check --unfix tessa-gold-armour' in gate.can_commit_provisionally(result)

    def test_a_must_beat_naming_the_change_marks_the_halt(self, project_dir, tmp_path):
        _fixed_armour(project_dir)
        _set_brief(project_dir, key_actions=f'must: {ARMOUR_QUOTE};Finds nothing')
        result = _gate(project_dir, tmp_path, [_trade()])
        assert result.halts and 'must: beat in key_actions' in result.halts[0].planned
        assert gate.problems_to_fix(result) == []

    def test_a_change_the_plan_does_not_call_for_still_goes_to_the_fix(
            self, project_dir, tmp_path):
        _fixed_armour(project_dir)
        # a plan fact here about someone else
        _add(project_dir, id='dorren-tired', scene_id=SCENE, type='physical',
             subject='dorren-hayle', statement='Dorren is tired', origin='plan',
             mutable='state', introduced_by='briefs')
        result = _gate(project_dir, tmp_path, [_trade()])
        assert [h.planned for h in result.halts] == ['']
        fix = gate.problems_to_fix(result)
        assert len(fix) == 1 and fix[0].startswith('The scene changes something the book fixed')
        assert gate.can_commit_provisionally(result) == 'it changes a fixed fact (a halt)'

    def test_gate_and_fix_spends_no_fix_or_regate_on_it(self, monkeypatch, tmp_path):
        r = gate.GateResult(SCENE)
        r.halts = [Halt('supersedes-fixed', 'f', 'supersedes the fixed fact g',
                        fixed_id='g', planned='the plan sets p in this scene')]
        calls = []
        monkeypatch.setattr(gate, 'gate_scene', lambda *a, **k: calls.append(1) or r)
        monkeypatch.setattr(gate, 'fix_scene', lambda *a, **k: pytest.fail('fixed'))
        out = gate.gate_and_fix('p', SCENE, command='draft', prose='x',
                                log_dir=str(tmp_path))
        assert out.result is r and not out.fixed and calls == [1]


class TestUnfix:

    def test_unfix_changes_ledger_snapshot_and_log_and_the_scene_clears(
            self, project_dir, tmp_path):
        _fixed_armour(project_dir)
        assert _gate(project_dir, tmp_path, [_trade()]).halts
        rows = audit.unfix(project_dir, ['tessa-gold-armour'])
        assert [r['mutable'] for r in rows] == ['state']
        assert next(r for r in ledger.load(project_dir)
                    if r['id'] == 'tessa-gold-armour')['mutable'] == 'state'
        assert next(r for r in audit.read_snapshot(project_dir)
                    if r['id'] == 'tessa-gold-armour')['mutable'] == 'state'
        entry = audit.read_log(project_dir)[-1]
        assert (entry['fact_id'], entry['change'], entry['command'], entry['columns']) == (
            'tessa-gold-armour', 'changed', audit.UNFIX, 'mutable')
        # the re-gate no longer halts, and commits
        result = _gate(project_dir, tmp_path, [_trade()])
        assert result.halts == [] and result.passed and result.committed

    @pytest.mark.parametrize('ids, said', [
        (['no-such-fact'], 'no-such-fact is not in'),
        ([''], 'no fact ids given'),
    ])
    def test_a_fact_it_cannot_unfix_changes_nothing(self, project_dir, ids, said):
        _fixed_armour(project_dir)
        before = ledger.load(project_dir)
        with pytest.raises(audit.UnfixError, match=said):
            audit.unfix(project_dir, ['tessa-gold-armour'] + ids if ids != [''] else ids)
        assert ledger.load(project_dir) == before

    def test_a_state_fact_is_refused(self, project_dir):
        _add(project_dir, id='a-state', scene_id='act1-sc01', type='physical',
             statement='x', origin='prose', mutable='state')
        with pytest.raises(audit.UnfixError, match='a-state is not fixed'):
            audit.unfix(project_dir, ['a-state'])
