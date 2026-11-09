"""#633: revise held a pass (and refused to start it) behind any earlier
scene waiting on the gate, even one the scenes it rewrites don't depend on.

On iliad-teen a pass rewrote 20 scenes and gated none, because an earlier
scene's re-check failed on two staging nitpicks. Now revise
(`cmd_write.GateBlockers` with `narrow`) holds a scene only behind an
earlier pending scene one of its facts depends on (`ledger.dependents`,
run from the pending scene's facts), names that fact in the log, and lets
a failed re-reading (`recheck-failed`, `advisor`) of prose unchanged since
its facts were read through. `write` keeps its rule: every earlier pending
scene holds a scene back."""

import os
import subprocess as sp

import pytest

from storyforge import cmd_revise, cmd_write, gate

from .test_revise_pass_gate import _gate_pass, _stub_gate

EARLIER, TARGET = 'act1-sc01', 'act2-sc01'


def _fact(fid, scene, subject, statement, resolves=''):
    return (f'{fid}|{scene}|physical|{subject}|{statement}||prose|binding|state|||||'
            f'draft|||{resolves}|')


def _ledger(project_dir, *rows):
    path = os.path.join(project_dir, 'reference', 'commitments.csv')
    with open(path, 'a', encoding='utf-8') as f:
        for row in rows:
            f.write(row + '\n')


#: the earlier scene's fact: about Kael Maren
KAEL = _fact('kael-lamp', EARLIER, 'kael-maren', 'Kael carries a brass lamp')
#: a later fact about someone else, naming no one in KAEL
PELL = _fact('pell-boots', TARGET, 'pell', 'Pell has new boots')
#: a later fact about Kael: it depends on KAEL
KAEL_LATER = _fact('kael-lamp-out', TARGET, 'kael-maren', 'The lamp has gone out')


@pytest.fixture
def git_book(project_dir):
    """The fixture project as a git work tree, so the prose a scene's facts
    were read from can be recorded (`gate.record_prose`)."""
    sp.run(['git', 'init', '-q', project_dir], check=True)
    return project_dir


def _record_earlier_prose(project_dir):
    with open(os.path.join(project_dir, 'scenes', f'{EARLIER}.md'), encoding='utf-8') as f:
        assert gate.record_prose(project_dir, EARLIER, f.read()) == ''


def _edit_earlier_prose(project_dir):
    with open(os.path.join(project_dir, 'scenes', f'{EARLIER}.md'), 'a',
              encoding='utf-8') as f:
        f.write('\nAn edit made after the facts were read.\n')


class TestTheRegressions:
    """The issue's acceptance tests."""

    def test_a_failed_recheck_of_unchanged_prose_does_not_hold_a_later_scene(
            self, git_book, monkeypatch):
        _ledger(git_book, KAEL, PELL)
        _record_earlier_prose(git_book)
        gate.mark_pending(git_book, EARLIER, gate.RECHECK_FAILED,
                          're-check did not pass: 2 problem(s): staging')
        gated, _ = _stub_gate(monkeypatch)
        assert _gate_pass(git_book, [TARGET]) == []
        assert gated == [(TARGET, 'revise')]
        assert set(gate.pending(git_book)) == {EARLIER}   # still the author's

    def test_a_later_scene_that_depends_on_it_is_held_and_the_fact_named(
            self, git_book, monkeypatch, capsys):
        _ledger(git_book, KAEL, KAEL_LATER)
        gate.mark_pending(git_book, EARLIER, 'redraft', 'a contradiction')
        gated, _ = _stub_gate(monkeypatch)
        out = _gate_pass(git_book, [TARGET])
        assert gated == []
        assert 'an earlier scene waits on the gate: act1-sc01' in out[0]
        log = capsys.readouterr().out
        assert (f'{TARGET} waits on it: fact kael-lamp-out ("The lamp has gone out") '
                f'depends on its fact kael-lamp ("Kael carries a brass lamp")') in log


class TestNarrowed:
    """`GateBlockers(narrow=True)`, revise's rule."""

    def _of(self, project_dir, scene=TARGET, narrow=True):
        return cmd_write.GateBlockers(project_dir, narrow=narrow).of(scene)

    def test_a_pending_scene_it_does_not_depend_on_lets_it_through(self, project_dir):
        _ledger(project_dir, KAEL, PELL)
        gate.mark_pending(project_dir, EARLIER, 'redraft', 'a contradiction')
        assert self._of(project_dir) == []

    def test_write_still_waits_on_every_earlier_pending_scene(self, project_dir):
        _ledger(project_dir, KAEL, PELL)
        gate.mark_pending(project_dir, EARLIER, 'redraft', 'a contradiction')
        assert self._of(project_dir, narrow=False) == [f'{EARLIER}: a contradiction']
        assert cmd_write._gate_blockers(project_dir, TARGET) == [f'{EARLIER}: a contradiction']

    def test_a_failed_recheck_of_unchanged_prose_lets_even_a_dependent_through(
            self, git_book):
        _ledger(git_book, KAEL, KAEL_LATER)
        _record_earlier_prose(git_book)
        for command in (gate.RECHECK_FAILED, 'advisor'):
            gate.mark_pending(git_book, EARLIER, command, 'staging')
            assert self._of(git_book) == [], command

    def test_one_whose_prose_changed_since_still_holds_a_dependent(self, git_book):
        _ledger(git_book, KAEL, KAEL_LATER)
        _record_earlier_prose(git_book)
        _edit_earlier_prose(git_book)
        gate.mark_pending(git_book, EARLIER, gate.RECHECK_FAILED, 'staging')
        [line] = self._of(git_book)
        assert line.startswith(f'{EARLIER}: staging ({TARGET} waits on it: fact kael-lamp-out')

    def test_one_whose_facts_are_not_in_the_ledger_holds_every_later_scene(self, git_book):
        """Nothing to tell what depends on it; its prose's facts are unknown,
        and its brief sets up none (#641: with one, the brief's stand in)."""
        from .test_gate_no_lock import set_brief
        set_brief(git_book, EARLIER, knowledge_out='')
        _ledger(git_book, PELL)
        _record_earlier_prose(git_book)
        gate.mark_pending(git_book, EARLIER, gate.RECHECK_FAILED, 'staging')
        [line] = self._of(git_book)
        assert "act1-sc01's facts are not in the ledger" in line

    def test_a_target_without_facts_waits_as_write_does(self, project_dir):
        """A scene not yet gated (or drafted) has no facts to tell from."""
        _ledger(project_dir, KAEL)
        gate.mark_pending(project_dir, EARLIER, 'redraft', 'a contradiction')
        [line] = self._of(project_dir)
        assert f'{TARGET} has no binding facts in the ledger' in line

    def test_a_scene_its_fact_ends_in_waits_on_it(self, project_dir):
        _ledger(project_dir, _fact('kael-lamp', EARLIER, 'kael-maren', 'Kael carries a brass lamp',
                                    resolves=TARGET), PELL)
        gate.mark_pending(project_dir, EARLIER, 'redraft', 'a contradiction')
        [line] = self._of(project_dir)
        assert f'its fact kael-lamp ("Kael carries a brass lamp") ends in {TARGET}' in line

    def test_a_ledger_that_cannot_be_read_narrows_nothing(self, project_dir, capsys):
        _ledger(project_dir, 'a|broken|row')
        gate.mark_pending(project_dir, EARLIER, 'redraft', 'a contradiction')
        assert self._of(project_dir) == [f'{EARLIER}: a contradiction']
        assert 'whatever they depend on' in capsys.readouterr().out


class TestPassStart:
    """`_exit_if_pass_blocked`: a pass starts when nothing it rewrites waits."""

    def test_a_pending_scene_no_target_depends_on_does_not_stop_it(self, project_dir):
        _ledger(project_dir, KAEL, PELL)
        gate.mark_pending(project_dir, EARLIER, 'redraft', 'a contradiction')
        cmd_revise._exit_if_pass_blocked(project_dir, TARGET)

    def test_one_a_target_depends_on_stops_it_and_names_the_fact(self, project_dir, capsys):
        _ledger(project_dir, KAEL, KAEL_LATER)
        gate.mark_pending(project_dir, EARLIER, 'redraft', 'a contradiction')
        with pytest.raises(SystemExit) as e:
            cmd_revise._exit_if_pass_blocked(project_dir, TARGET)
        assert e.value.code == 1
        assert 'fact kael-lamp-out' in capsys.readouterr().out

    def test_a_later_target_that_depends_on_it_stops_it(self, project_dir):
        """Not only the first target counts."""
        _ledger(project_dir, KAEL, KAEL_LATER,
                _fact('pell-hat', 'act1-sc02', 'pell', 'Pell wears a hat'))
        gate.mark_pending(project_dir, EARLIER, 'redraft', 'a contradiction')
        with pytest.raises(SystemExit):
            cmd_revise._exit_if_pass_blocked(project_dir, f'act1-sc02;{TARGET}')

    def test_one_between_the_targets_no_later_target_depends_on_does_not(self, project_dir):
        between = _fact('x1-lamp', 'new-x1', 'kael-maren', 'Kael lights a lamp')
        _ledger(project_dir, between, PELL,
                _fact('pell-hat', 'act1-sc02', 'pell', 'Pell wears a hat'))
        gate.mark_pending(project_dir, 'new-x1', 'redraft', 'a contradiction')
        cmd_revise._exit_if_pass_blocked(project_dir, f'act1-sc02;{TARGET}')


class TestRedraft:
    def test_a_redraft_is_not_held_by_a_scene_it_does_not_depend_on(self, project_dir):
        _ledger(project_dir, KAEL, PELL)
        gate.mark_pending(project_dir, EARLIER, 'redraft', 'a contradiction')
        assert cmd_revise._leaning(project_dir, TARGET) == ''

    def test_one_it_depends_on_holds_it(self, project_dir):
        _ledger(project_dir, KAEL, KAEL_LATER)
        gate.mark_pending(project_dir, EARLIER, 'redraft', 'a contradiction')
        assert 'earlier scene(s) that did not pass the gate or were not redrafted: ' \
            'act1-sc01' in cmd_revise._leaning(project_dir, TARGET)
