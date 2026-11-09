"""#641: a failing scene stops only itself.

On *Wrath Like Smoke* one failing scene held every later scene at
`pending`: `write` refused to draft and the author drafted outside the
tool. #633 narrowed revise's holds to the scenes a scene depends on
(`cmd_write.GateBlockers(narrow=True)`, the reverse `ledger.dependents`
rule). Now
- `write` uses that rule too: a scene that depends on an earlier one
  waiting on the gate isn't drafted, the others are (with a WARNING naming
  what they were drafted past), and a scene that fails in the run holds
  back only its dependents;
- the later brief is read first: `continuity_deps`, or a fact its `*_in`
  columns need that the earlier brief sets up (in its `*_out` and not its
  `*_in`: `*_out` is cumulative); a scene with no commitments in the
  ledger (not drafted yet, or its first gate failed) is then judged by
  those brief facts depending on each other by the same rule, less its
  type guess;
- `check` keeps going by default (`--stop-at-first` for the old stop;
  `--keep-going` is still taken) and labels provisional only the results
  that depend on an earlier failure;
- revise's pass gating and redrafts go on past a failure the same way.

The fixture's briefs: act1-sc02 lists act1-sc01 in continuity_deps and
sets up archive-key-dorren and exhaustion-tessa; new-x1 needs
archive-key-dorren; act2-sc01 and act2-sc02 have no brief."""

import os

import pytest

from storyforge import cmd_check, cmd_revise, cmd_write, gate, status

from .test_cmd_check import _fake_gate, _finding
from .test_cmd_check import project  # noqa: F401  (fixture)
from .test_write_gate import _gate
from .test_write_guard import (  # noqa: F401  (setup is a fixture)
    GOOD, _direct_replies, _pending, _reply, _scene, setup,
)

INDEPENDENT = 'act2-sc01'


def set_brief(project_dir: str, scene_id: str, **cols: str) -> None:
    """Set `cols` on `scene_id`'s row of reference/scene-briefs.csv (a new
    row when it has none)."""
    path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    header = lines[0].split('|')
    rows = [dict(zip(header, line.split('|'))) for line in lines[1:] if line.strip()]
    row = next((r for r in rows if r['id'] == scene_id), None)
    if row is None:
        row = {c: '' for c in header}
        row['id'] = scene_id
        rows.append(row)
    row.update(cols)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(['|'.join(header)] + ['|'.join(r.get(c, '') for c in header)
                                                 for r in rows]) + '\n')


def _independent(project_dir: str) -> None:
    """act2-sc01's brief needs only Kael's scar: nothing act1-sc01 or
    act1-sc02 sets up, nothing about their subjects."""
    set_brief(project_dir, INDEPENDENT, physical_state_in='scar-left-hand-kael')


def _of(project_dir, scene, **k):
    return cmd_write.GateBlockers(project_dir, narrow=True, **k).of(scene)


class TestBriefsStandIn:
    """`GateBlockers` narrowed, for a scene with no commitments."""

    def test_continuity_deps_naming_the_earlier_scene_holds_it(self, project_dir):
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        [line] = _of(project_dir, 'act1-sc02')
        assert line == ('act1-sc01: two problems (act1-sc02 waits on it: its brief lists '
                        'act1-sc01 in continuity_deps)')

    def test_a_fact_it_needs_that_the_earlier_brief_sets_up_holds_it(self, project_dir):
        gate.mark_pending(project_dir, 'act1-sc02', 'draft', 'two problems')
        [line] = _of(project_dir, 'new-x1')
        assert ("new-x1 waits on it: its brief needs archive-key-dorren, which act1-sc02's "
                "brief sets up") in line

    def test_brief_facts_that_do_not_depend_on_each_other_let_it_through(self, project_dir):
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        _independent(project_dir)
        assert _of(project_dir, INDEPENDENT) == []

    def test_brief_facts_about_the_same_subject_hold_it(self, project_dir):
        """Tessa's ankle (act2-sc01's need) and Tessa's exhaustion (act1-sc02's
        set-up): the same subject, so `ledger.dependents` links them."""
        gate.mark_pending(project_dir, 'act1-sc02', 'draft', 'two problems')
        set_brief(project_dir, INDEPENDENT, physical_state_in='sprained-ankle-tessa')
        [line] = _of(project_dir, INDEPENDENT)
        assert ('brief fact sprained-ankle-tessa ("right ankle sprained during ridge '
                'collapse") depends on its brief fact exhaustion-tessa') in line

    def test_no_brief_and_no_facts_still_holds_it_and_says_why(self, project_dir):
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        [line] = _of(project_dir, 'act2-sc02')
        assert ('act2-sc02 has no binding facts in the ledger and it has no row in '
                'reference/scene-briefs.csv, to tell whether any depends on act1-sc01') in line

    def test_a_brief_that_needs_nothing_says_so(self, project_dir):
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        set_brief(project_dir, 'act2-sc02', goal='a goal')
        [line] = _of(project_dir, 'act2-sc02')
        assert 'act2-sc02 has no binding facts in the ledger and its brief names none it ' \
            'needs' in line

    def test_brief_ids_not_in_the_registry_are_named(self, project_dir):
        """#641's review, T-7: not "its brief names none"."""
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        set_brief(project_dir, INDEPENDENT, physical_state_in='no-such-fact')
        [line] = _of(project_dir, INDEPENDENT)
        assert "its brief's no-such-fact is not in reference/commitments.csv" in line

    def test_no_briefs_file_is_said(self, project_dir):
        """#641's review, SF-5: not "its brief sets up none"."""
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        os.remove(os.path.join(project_dir, 'reference', 'scene-briefs.csv'))
        [line] = _of(project_dir, INDEPENDENT)
        assert "act1-sc01's facts are not in the ledger and there is no " \
            "reference/scene-briefs.csv" in line

    def test_briefs_that_cannot_be_read_hold_it_and_warn(self, project_dir, capsys):
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        _independent(project_dir)
        with open(os.path.join(project_dir, 'reference', 'scene-briefs.csv'), 'ab') as f:
            f.write(b'\xff\xfe broken\n')
        [line] = _of(project_dir, INDEPENDENT)
        assert ("act1-sc01's facts are not in the ledger and reference/scene-briefs.csv "
                "could not be read") in line
        assert 'scene-briefs.csv could not be read' in capsys.readouterr().out

    def test_a_scene_held_in_the_run_holds_its_dependents(self, project_dir):
        [line] = _of(project_dir, 'act1-sc02', held={'act1-sc01': 'not drafted: x'})
        assert line.startswith('act1-sc01: not drafted: x (act1-sc02 waits on it')

    def test_passed_over_names_what_it_does_not_wait_on(self, project_dir):
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        _independent(project_dir)
        blockers = cmd_write.GateBlockers(project_dir, narrow=True)
        assert blockers.passed_over(INDEPENDENT) == ['act1-sc01: two problems']
        assert blockers.passed_over('act1-sc02') == []


def _registry_link(project_dir: str, fact: str, column: str, value: str) -> None:
    """Set `column` on registry fact `fact` in reference/commitments.csv."""
    path = os.path.join(project_dir, 'reference', 'commitments.csv')
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    header = lines[0].split('|')
    at = header.index(column)
    for n, line in enumerate(lines):
        cells = line.split('|')
        if cells[0] == fact:
            cells[at] = value
            lines[n] = '|'.join(cells)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


class TestReviewJudgement:
    """#641's review: what `GateBlockers` narrowed holds, by brief and ledger."""

    def test_a_fact_the_earlier_brief_only_carries_forward_does_not_hold_it(self, project_dir):
        """C3: `knowledge_out` is cumulative. act1-sc02 enters knowing
        map-anomaly-exists (act1-sc01 set it up) and lists it again on the way
        out; act2-sc01 needing it doesn't wait on act1-sc02."""
        gate.mark_pending(project_dir, 'act1-sc02', 'draft', 'two problems')
        set_brief(project_dir, 'act1-sc02',
                  knowledge_out='map-anomaly-exists;village-vanished;archive-erasure')
        set_brief(project_dir, INDEPENDENT, knowledge_in='map-anomaly-exists')
        assert _of(project_dir, INDEPENDENT) == []

    def test_a_fact_the_earlier_brief_adds_still_holds_it(self, project_dir):
        gate.mark_pending(project_dir, 'act1-sc02', 'draft', 'two problems')
        set_brief(project_dir, 'act1-sc02',
                  knowledge_out='map-anomaly-exists;village-vanished;archive-erasure')
        set_brief(project_dir, INDEPENDENT, knowledge_in='village-vanished')
        [line] = _of(project_dir, INDEPENDENT)
        assert "its brief needs village-vanished, which act1-sc02's brief sets up" in line

    def test_knowledge_facts_are_not_tied_by_type_alone(self, project_dir):
        """TD-2: knowledge registry facts have no subject; the type guess would
        tie any knowledge fact act2-sc01 needs to any act1-sc01 sets up."""
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        set_brief(project_dir, INDEPENDENT, knowledge_in='council-dismisses-evidence')
        assert _of(project_dir, INDEPENDENT) == []
        blockers = cmd_write.GateBlockers(project_dir, narrow=True)
        assert blockers.passed_over(INDEPENDENT) == ['act1-sc01: two problems']

    def test_a_registry_link_between_brief_facts_holds_it(self, project_dir):
        """TD-1: scar-left-hand-kael depends_on exhaustion-tessa (act1-sc02's
        set-up); the stand-ins' ids differ, the link is still seen."""
        gate.mark_pending(project_dir, 'act1-sc02', 'draft', 'two problems')
        _registry_link(project_dir, 'scar-left-hand-kael', 'depends_on', 'exhaustion-tessa')
        _independent(project_dir)
        [line] = _of(project_dir, INDEPENDENT)
        assert ('brief fact scar-left-hand-kael ("old scar across left palm from archive '
                'incident") links to its brief fact exhaustion-tessa') in line

    def test_continuity_deps_holds_it_when_both_have_ledger_facts(self, project_dir):
        """CR-1: the brief is read first, whatever the ledger holds."""
        from .test_revise_blockers import KAEL, PELL, _ledger
        _ledger(project_dir, KAEL, PELL)
        gate.mark_pending(project_dir, 'act1-sc01', 'redraft', 'a contradiction')
        assert _of(project_dir, INDEPENDENT) == []   # unrelated facts, no brief tie
        set_brief(project_dir, INDEPENDENT, continuity_deps='act1-sc01')
        [line] = _of(project_dir, INDEPENDENT)
        assert 'its brief lists act1-sc01 in continuity_deps' in line


class TestMixedStandIns:
    """T-2: one side's facts from the ledger, the other's from its brief."""

    def test_earlier_brief_later_ledger_dependent_is_held(self, project_dir):
        from .test_revise_blockers import _fact, _ledger
        _ledger(project_dir, _fact('tessa-limps', INDEPENDENT, 'tessa-merrin', 'Tessa limps'))
        gate.mark_pending(project_dir, 'act1-sc02', 'draft', 'two problems')
        [line] = _of(project_dir, INDEPENDENT)
        assert ('fact tessa-limps ("Tessa limps") depends on its brief fact '
                'exhaustion-tessa') in line

    def test_earlier_brief_later_ledger_independent_is_let_through(self, project_dir):
        from .test_revise_blockers import PELL, _ledger
        _ledger(project_dir, PELL)
        gate.mark_pending(project_dir, 'act1-sc02', 'draft', 'two problems')
        assert _of(project_dir, INDEPENDENT) == []

    def test_earlier_ledger_later_brief_dependent_is_held(self, project_dir):
        from .test_revise_blockers import KAEL, _ledger
        _ledger(project_dir, KAEL)
        gate.mark_pending(project_dir, 'act1-sc01', 'redraft', 'a contradiction')
        _independent(project_dir)   # needs Kael's scar: Kael is KAEL's subject
        [line] = _of(project_dir, INDEPENDENT)
        assert ('brief fact scar-left-hand-kael ("old scar across left palm from archive '
                'incident") depends on its fact kael-lamp') in line

    def test_earlier_ledger_later_brief_independent_is_let_through(self, project_dir):
        from .test_revise_blockers import KAEL, _ledger
        _ledger(project_dir, KAEL)
        gate.mark_pending(project_dir, 'act1-sc01', 'redraft', 'a contradiction')
        set_brief(project_dir, INDEPENDENT, physical_state_in='sprained-ankle-tessa')
        assert _of(project_dir, INDEPENDENT) == []


class TestHeldState:
    """TD-3, TD-4, SF-4: the run's holds, kept by `GateBlockers`."""

    def test_hold_narrows_a_set_read_with_nothing_pending(self, project_dir):
        blockers = cmd_write.GateBlockers(project_dir, narrow=True)
        assert blockers.of('act1-sc02') == []
        blockers.hold('act1-sc01', 'not drafted: x')
        [line] = blockers.of('act1-sc02')
        assert line.scene_id == 'act1-sc01'
        assert line.endswith('(act1-sc02 waits on it: its brief lists act1-sc01 in '
                             'continuity_deps)')

    def test_a_scene_failed_this_run_is_named_as_passed_over(self, project_dir):
        _independent(project_dir)
        failed = cmd_write.GateBlockers(project_dir, narrow=True,
                                        failed={'act1-sc01': 'not drafted: cut off'})
        assert failed.passed_over(INDEPENDENT) == ['act1-sc01: not drafted: cut off']
        held = cmd_write.GateBlockers(project_dir, narrow=True,
                                      held={'act1-sc01': 'not drafted: it waits on x'})
        assert held.passed_over(INDEPENDENT) == []

    def test_a_pending_row_is_kept_over_a_hold(self, project_dir):
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        blockers = cmd_write.GateBlockers(project_dir, narrow=True,
                                          failed={'act1-sc01': 'did not pass'})
        assert blockers.waiting['act1-sc01']['command'] == 'draft'

    def test_held_scenes_reads_the_book_once(self, project_dir, monkeypatch):
        """TD-5: one ledger read however many scenes are asked about."""
        from storyforge import ledger
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        loads = []
        real = ledger.load
        monkeypatch.setattr(ledger, 'load', lambda *a, **k: loads.append(1) or real(*a, **k))
        held = cmd_write.held_scenes(project_dir, ['act1-sc02', 'new-x1', 'act2-sc03'])
        assert len(loads) == 1
        assert set(held) == {'act1-sc02', 'new-x1', 'act2-sc03'}
        assert held['act2-sc03'][0].scene_id == 'act1-sc02'   # behind a held scene


def _left_to_draft(project_dir: str, *scenes: str) -> None:
    """Mark every scene drafted in scenes.csv but `scenes`."""
    path = os.path.join(project_dir, 'reference', 'scenes.csv')
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    at = lines[0].split('|').index('status')
    for n, line in enumerate(lines[1:], 1):
        cells = line.split('|')
        cells[at] = 'briefed' if cells[0] in scenes else 'drafted'
        lines[n] = '|'.join(cells)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


class TestStatus:
    """CR-2, SF-3, T-1, C5: status routes to the check when write would
    draft nothing, instead of looping on write."""

    @pytest.fixture(autouse=True)
    def _solid(self, monkeypatch):
        monkeypatch.setattr(status, 'ladder_states', lambda pd, medium='novel': [
            {'level': lvl, 'name': name, 'state': 'solid', 'detail': ''}
            for lvl, name in status.LEVEL_NAMES.items()])

    def test_every_scene_left_to_draft_held_puts_the_check_first(self, project_dir):
        _left_to_draft(project_dir, 'act1-sc02')
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        v = status.build_status(project_dir)
        assert (v['next']['stage'], v['next']['command']) == ('check', status.CHECK_COMMAND)
        assert 'every one of the 1 scene(s) left to draft waits on one of them' \
            in v['next']['reason']
        assert v['then']['stage'] == 'draft'

    def test_a_scene_free_to_draft_keeps_drafting_next(self, project_dir):
        _left_to_draft(project_dir, 'act1-sc02', INDEPENDENT)
        _independent(project_dir)
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        v = status.build_status(project_dir)
        assert (v['next']['stage'], v['next']['command']) == ('draft', status.WRITE_COMMAND)
        assert '(1 of 2 left to draft can be drafted now)' in v['next']['reason']
        assert v['then']['stage'] == 'check'

    def test_what_it_reads_is_not_printed(self, project_dir, capsys):
        """`status --json` prints the verdict alone: GateBlockers' WARNINGs
        become blockers."""
        _left_to_draft(project_dir, 'act1-sc02')
        gate.mark_pending(project_dir, 'act1-sc01', 'draft', 'two problems')
        gate.mark_pending(project_dir, 'gone-scene', 'draft', 'old')
        v = status.build_status(project_dir)
        assert capsys.readouterr().out == ''
        assert any('no longer scenes: gone-scene' in b['detail'] for b in v['blockers'])


@pytest.mark.real_gate
class TestWrite:
    """The issue's acceptance test: a book with one failing early scene can
    draft every later scene that doesn't depend on it."""

    def test_a_pending_early_scene_holds_only_the_scenes_depending_on_it(
            self, setup, monkeypatch, capsys):
        _pending(setup, INDEPENDENT)
        _independent(setup)
        gate.mark_pending(setup, 'act1-sc01', 'draft', 'two problems')
        _direct_replies(monkeypatch, {INDEPENDENT: _reply(GOOD)})
        calls = _gate(monkeypatch, {INDEPENDENT: True})
        with pytest.raises(SystemExit) as e:
            cmd_write.main(['--scenes', f'act1-sc02,{INDEPENDENT}'])
        assert e.value.code == 1                       # a scene was held: not a finished run
        assert calls == [(INDEPENDENT, 'draft')]
        assert _scene(setup, INDEPENDENT) is not None
        assert _scene(setup, 'act1-sc02') is None
        out = capsys.readouterr().out
        assert 'WARNING: not drafting act1-sc02: it waits on 1 earlier scene(s)' in out
        assert f'WARNING: drafting {INDEPENDENT} past 1 earlier scene(s) waiting on the gate' \
            in out
        assert '  act1-sc01: two problems' in out
        assert 'act1-sc02 (not drafted: it waits on act1-sc01; draft it once that passes' in out
        # SF-6: counted against every scene asked for, the held one too
        assert 'Scenes drafted: 1/2 (1 held back before drafting)' in out

    def test_a_scene_failing_in_the_run_stops_only_itself(self, setup, monkeypatch, capsys):
        _pending(setup, INDEPENDENT)
        _independent(setup)
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD), INDEPENDENT: _reply(GOOD)})
        calls = _gate(monkeypatch, {'act1-sc01': False, INDEPENDENT: True})
        with pytest.raises(SystemExit) as e:
            cmd_write.main(['--scenes', f'act1-sc01,{INDEPENDENT}'])
        assert e.value.code == 1
        assert calls == [('act1-sc01', 'draft'), (INDEPENDENT, 'draft')]
        assert set(gate.pending(setup)) == {'act1-sc01'}
        assert 'Going on: the later scenes that depend on it are held back.' in \
            capsys.readouterr().out

    def test_a_held_scene_holds_the_scenes_depending_on_it(self, setup, monkeypatch, capsys):
        """act2-sc03's brief lists act1-sc02, held behind act1-sc01."""
        _pending(setup, INDEPENDENT, 'act2-sc03')
        _independent(setup)
        gate.mark_pending(setup, 'act1-sc01', 'draft', 'two problems')
        _direct_replies(monkeypatch, {INDEPENDENT: _reply(GOOD)})
        calls = _gate(monkeypatch, {INDEPENDENT: True})
        with pytest.raises(SystemExit):
            cmd_write.main(['--scenes', f'act1-sc02,{INDEPENDENT},act2-sc03'])
        assert calls == [(INDEPENDENT, 'draft')]
        out = capsys.readouterr().out
        held = [line for line in out.splitlines() if 'act2-sc03 (not drafted' in line]
        assert held and 'act1-sc02' in held[0]

    def test_every_scene_held_spends_nothing(self, setup, monkeypatch, capsys):
        gate.mark_pending(setup, 'act1-sc01', 'draft', 'two problems')
        monkeypatch.setattr(cmd_write, '_forecast', lambda *a, **k: pytest.fail('forecast'))
        with pytest.raises(SystemExit) as e:
            cmd_write.main(['--scenes', 'act1-sc02'])
        assert e.value.code == 1
        out = capsys.readouterr().out
        assert 'ERROR: not drafting act1-sc02' in out and 'Nothing to draft' in out
        assert 'run `storyforge check --pending`' in out   # C5: what clears it


class TestCheck:
    def test_a_failing_scene_s_pending_row_carries_its_findings(self, project, monkeypatch):
        """SF-2: write names them when it drafts past the scene; the next
        check overwrites the report."""
        project_dir, _ = project
        _fake_gate(monkeypatch, {'act1-sc01': _finding()})
        with pytest.raises(SystemExit):
            cmd_check.main(['act1-sc01'])
        reason = gate.pending(project_dir)['act1-sc01']['reason']
        assert reason.startswith('1 problem(s): ')
        assert 'why' in reason and reason.endswith('; see working/check-report.md')

    def test_named_scenes_are_all_checked_by_default(self, project, monkeypatch, capsys):
        seen = _fake_gate(monkeypatch, {'act1-sc01': _finding()})
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--scenes', f'act1-sc01,{INDEPENDENT}'])
        assert e.value.code == 1
        assert seen == ['act1-sc01', INDEPENDENT]
        assert '1 of 2 scene(s) checked passed.' in capsys.readouterr().out

    def test_keep_going_is_still_taken_and_changes_nothing(self, project, monkeypatch):
        seen = _fake_gate(monkeypatch, {'act1-sc01': _finding()})
        with pytest.raises(SystemExit):
            cmd_check.main(['--keep-going', '--scenes', f'act1-sc01,{INDEPENDENT}'])
        assert seen == ['act1-sc01', INDEPENDENT]

    def test_stop_at_first_stops_there(self, project, monkeypatch):
        project_dir, _ = project
        seen = _fake_gate(monkeypatch, {'act1-sc01': _finding()})
        with pytest.raises(SystemExit):
            cmd_check.main(['--stop-at-first', '--scenes', f'act1-sc01,{INDEPENDENT}'])
        assert seen == ['act1-sc01']
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert f'Not checked: {INDEPENDENT}' in report

    def test_only_a_result_depending_on_the_failure_is_provisional(
            self, project, monkeypatch, capsys):
        project_dir, _ = project
        _independent(project_dir)
        for sid in ('act1-sc01', 'act1-sc02', INDEPENDENT):
            gate.mark_pending(project_dir, sid, 'draft', 'stale')
        _fake_gate(monkeypatch, {'act1-sc01': _finding()})
        with pytest.raises(SystemExit):
            cmd_check.main(['--pending'])
        out = capsys.readouterr().out
        assert 'act1-sc02: passed (provisional: act1-sc01, earlier, has not passed)' in out
        assert f'{INDEPENDENT}: passed\n' in out
        assert 'Provisional: act1-sc02 were checked' in out


class TestRevise:
    def test_a_pass_gates_the_scenes_after_a_failure_that_do_not_depend_on_it(
            self, project_dir, monkeypatch, capsys):
        from .test_revise_pass_gate import _gate_pass, _scenes, _stub_gate
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **k: True)
        _scenes(project_dir, 'act1-sc01', 'act1-sc02', INDEPENDENT)
        set_brief(project_dir, INDEPENDENT, physical_state_in='scar-left-hand-kael')
        gated, _ = _stub_gate(monkeypatch, fails={'act1-sc02'})
        out = _gate_pass(project_dir, ['act1-sc01', 'act1-sc02', INDEPENDENT])
        assert [s for s, _ in gated] == ['act1-sc01', 'act1-sc02', INDEPENDENT]
        assert out == ['act1-sc02 (the gate did not pass it: a contradiction)']
        assert set(gate.pending(project_dir)) == {'act1-sc02'}
        # SF-1: named, as write names what it drafts past
        assert f'WARNING: gating {INDEPENDENT} past 1 earlier scene(s) waiting on the gate' \
            in capsys.readouterr().out

    def test_redrafts_go_on_past_a_failure_to_the_scenes_not_depending_on_it(
            self, project_dir, monkeypatch, capsys):
        from .test_write_gate import TestReviseRedraftsAreGated
        _independent(project_dir)
        helper = TestReviseRedraftsAreGated()
        drafted, _, error = helper._redraft(project_dir, monkeypatch,
                                            ['act1-sc01', 'act1-sc02', INDEPENDENT],
                                            gate_fails={'act1-sc01'})
        # act1-sc02 lists act1-sc01 in continuity_deps; act2-sc01 doesn't depend on it
        assert drafted == ['act1-sc01', INDEPENDENT]
        assert 'act1-sc01 (redrafted, but the gate did not pass it' in error
        assert 'act1-sc02 (not redrafted: it waits on earlier scene(s)' in error
        assert INDEPENDENT not in error
        out = capsys.readouterr().out   # SF-1
        assert f'WARNING: redrafting {INDEPENDENT} past 1 earlier scene(s) waiting on the gate' \
            in out

    def test_the_hone_fix_redraft_goes_on_too(self, project_dir, monkeypatch):
        _independent(project_dir)
        gated = []
        monkeypatch.setattr('storyforge.cmd_write._build_prompt', lambda sid, *a, **k: sid)
        monkeypatch.setattr('storyforge.common.build_shared_context', lambda *a, **k: [])
        monkeypatch.setattr(cmd_revise, 'invoke_api', lambda *a, **k: 'New prose. ' * 300)
        monkeypatch.setattr('storyforge.parsing.unsafe_scene_reason', lambda *a: '')
        monkeypatch.setattr(cmd_write, 'run_recheck', lambda *a, **k: None)
        monkeypatch.setattr(cmd_write, '_gate_drafted_scene',
                            lambda pd, sid, *a, **k: gated.append(sid) or (
                                (False, 'a contradiction') if sid == 'act1-sc01' else (True, '')))
        with pytest.raises(cmd_revise.RedraftError) as e:
            cmd_revise._redraft_scenes(project_dir, ['act1-sc01', 'act1-sc02', INDEPENDENT])
        assert gated == ['act1-sc01', INDEPENDENT]
        assert 'act1-sc02 (not redrafted' in str(e.value)
