"""Tests for the gate's `tandem` check method (#738): the open checker and
the question layer together on a scene's first gate run, the question layer
alone on the re-checks after a fix, with the open checker's first-run
findings carried where the fix left their words alone and asked again
(`questions.ask_resolved`) where it didn't; how the two rule on one dispute
or ending; the `--tandem` / `--open` / `--questions` flags and the
`check --pending` messages carrying them. The API is mocked at
`api._api_request`. Every scene, name and fact here is invented."""

import os
from unittest.mock import patch

import pytest

from storyforge import gate, questions
from storyforge.checker import CheckResult, Dispute, Finding

from test_questions import (SCENE, TESSA_KIND, _add_rows, _is_questions, _text,  # noqa: F401
                            ans)

LAMP = 'the lamp burned in the window of the tower'
PROSE = f'Tessa mocked Dorren until he left the study. Far away, {LAMP} all night long.'
# in act1-sc01 of the fixture book, so the open checker's finding verifies
EARLIER = 'Dorren Hayle pressed the brass calipers against the vellum'


def _lamp(quote=LAMP):
    return {'kind': 'contradiction', 'code': 'PHY', 'scene_quote': quote,
            'established_scene': 'act1-sc01', 'established_quote': EARLIER,
            'fact_id': '', 'explanation': 'The tower has no window.'}


def _f(kind='contradiction', code='PHY', quote=LAMP, fact='', source='act1-sc01',
       checker='', problem=''):
    return Finding(kind, code, quote, source, EARLIER, fact, 'why', problem=problem,
                   checker=checker)


class _Book:
    """A fake API for one scene's gate runs: the open checker finds the
    lamp (`open_findings`), the questions find "Tessa mocked Dorren" while
    the prose has it, and the resolved asking answers `resolved(n)`."""

    def __init__(self, open_findings=None, resolved=None):
        self.calls = []
        self.open_findings = [_lamp()] if open_findings is None else open_findings
        self.resolved = resolved or (lambda n: [ans(i, 'no') for i in range(1, n + 1)])
        self.resolved_prompts = []

    def __call__(self, path, body, **k):
        schema = (body.get('output_config') or {}).get('format', {}).get('schema', {})
        if 'tools' in body:
            self.calls.append('open')
            return _text({'findings': self.open_findings, 'kept': [], 'cleared': [],
                          'ended': []})
        if 'records' in schema.get('properties', {}):
            return _text({'records': [{'type': 'at', 'who': 'Tessa', 'item': 'the study',
                                       'value': '', 'detail': '', 'quote': 'Tessa'}]})
        if _is_questions(body):
            prompt = body['messages'][0]['content']
            n = prompt.count('   Question: ')
            if 'Problems found in the earlier draft' in prompt:
                self.calls.append('resolved')
                self.resolved_prompts.append(prompt)
                return _text({'answers': self.resolved(n)})
            if 'delivers what its brief planned' in prompt:
                self.calls.append('promises')
                return _text({'answers': [ans(i, 'yes', 'Tessa') for i in range(1, n + 1)]})
            self.calls.append('questions')
            mocked = 'Tessa mocked Dorren' in prompt
            return _text({'answers': [ans(i, 'yes', 'Tessa mocked Dorren', 'Cruel.')
                                      if mocked else ans(i, 'no') for i in range(1, n + 1)]})
        if 'verdicts' in schema.get('properties', {}):
            return _text({'verdicts': []})
        return _text({'commitments': []})


def _brief(project_dir):
    from storyforge.elaborate import _read_csv, _write_csv
    path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    briefs = _read_csv(path)
    for b in briefs:
        if b['id'] == SCENE:
            b.update({k: '' for k in ('outcome', 'key_actions', 'key_dialogue',
                                      'knowledge_out', 'physical_state_out')})
    _write_csv(path, briefs, list(briefs[0].keys()))


@pytest.fixture
def tandem(project_dir, monkeypatch):
    monkeypatch.setattr(gate, 'GATE_CHECK_METHOD', 'tandem')
    monkeypatch.setattr(gate, 'GATE_CONTINUITY', True)
    _add_rows(project_dir, TESSA_KIND)
    _brief(project_dir)
    with open(os.path.join(project_dir, 'scenes', f'{SCENE}.md'), 'w') as f:
        f.write(PROSE)
    return project_dir


def _fixer(*proses):
    """A fixer returning each of `proses` in turn (the last one again after)."""
    left = list(proses)

    def fix(scene_id, prose, result, *, log_dir, model=None, protected=(), earlier=(),
            edits_out=None):
        fixed = left.pop(0) if len(left) > 1 else left[0]
        if edits_out is not None and fixed != prose:
            edits_out.append({'find': prose, 'replace': fixed})
        return fixed
    return fix


# ============================================================================
# The method
# ============================================================================

@pytest.mark.check_method_default
def test_tandem_is_the_default():
    assert gate.GATE_CHECK_METHOD == 'tandem'
    assert gate.CHECK_METHODS == ('open', 'questions', 'tandem')


def test_it_needs_the_typed_state(tandem, tmp_path, monkeypatch):
    monkeypatch.setattr(gate, 'GATE_CONTINUITY', False)
    with pytest.raises(gate.GateError, match='needs the continuity checks'):
        gate.gate_scene(tandem, SCENE, command='advisor', log_dir=str(tmp_path / 'logs'),
                        extract_model='m', check_model='m')


@pytest.mark.continuity
class TestFirstRun:
    def test_both_checkers_read_it_and_each_finding_says_which(self, tandem, tmp_path):
        book = _Book()
        with patch('storyforge.api._api_request', side_effect=book):
            result = gate.gate_scene(tandem, SCENE, command='advisor',
                                     log_dir=str(tmp_path / 'logs'), extract_model='m',
                                     check_model='m')
        assert book.calls.count('open') == gate.GATE_READINGS
        assert book.calls.count('questions') == 2 and 'resolved' not in book.calls
        assert {f.code: f.checker for f in result.findings} == {'PHY': gate.OPEN,
                                                                'TRT': gate.QUESTIONS}
        report = '\n'.join(gate.report_lines(result))
        assert 'CONTRADICTION [open checker]: PHY' in report
        assert 'CONTRADICTION [questions]: TRT' in report
        assert 'NOTE (tandem: which checkers read it' in report and 'first run' in report
        # the open checker read the book: the question layer's gap isn't claimed
        assert not set(gate.QUESTION_LAYER_GAPS) & set(result.question_notes)
        assert gate.TANDEM_RECHECK_GAP not in result.question_notes
        assert [f.code for f in result.open_findings] == ['PHY']

    def test_a_finding_both_make_is_one_tagged_both(self, tandem, tmp_path):
        book = _Book(open_findings=[{**_lamp('Tessa mocked Dorren'), 'code': 'TRT'}])
        with patch('storyforge.api._api_request', side_effect=book):
            result = gate.gate_scene(tandem, SCENE, command='advisor',
                                     log_dir=str(tmp_path / 'logs'), extract_model='m',
                                     check_model='m')
        assert [(f.code, f.checker) for f in result.findings] == [('TRT', gate.BOTH)]
        assert '[open checker and questions]' in '\n'.join(gate.report_lines(result))

    def test_the_open_and_questions_methods_tag_nothing(self, tandem, tmp_path, monkeypatch):
        monkeypatch.setattr(gate, 'GATE_CHECK_METHOD', 'open')
        book = _Book()
        with patch('storyforge.api._api_request', side_effect=book):
            result = gate.gate_scene(tandem, SCENE, command='advisor',
                                     log_dir=str(tmp_path / 'logs'), extract_model='m',
                                     check_model='m')
        assert 'questions' not in book.calls
        assert [f.checker for f in result.findings] == [''] and not result.check_notes
        assert result.open_findings is None


@pytest.mark.continuity
class TestFixLoop:
    def _run(self, tandem, tmp_path, book, *fixed):
        with patch('storyforge.api._api_request', side_effect=book):
            return gate.gate_and_fix(tandem, SCENE, command='draft', prose=PROSE,
                                     log_dir=str(tmp_path / 'logs'), extract_model='m',
                                     check_model='m', fixer=_fixer(*fixed))

    def test_a_recheck_makes_no_open_reading_and_carries_untouched_words(self, tandem,
                                                                         tmp_path):
        # the fix takes out the questions' finding; the lamp's words are
        # more than four words from the change, so its finding stands
        # without a call
        book = _Book()
        out = self._run(tandem, tmp_path, book, PROSE.replace('mocked', 'thanked'))
        assert book.calls.count('open') == gate.GATE_READINGS   # the first run's only
        assert 'resolved' not in book.calls
        result = out.result
        assert not result.passed and out.fixed
        [lamp] = result.findings
        assert (lamp.code, lamp.checker, lamp.carried) == ('PHY', gate.OPEN, gate.UNTOUCHED)
        assert lamp.scene_quote == LAMP
        report = '\n'.join(gate.report_lines(result))
        assert '[open checker] [from the first run; its words untouched by the fix]' in report
        assert '1 stand (their words untouched)' in report
        assert gate.TANDEM_RECHECK_GAP in result.question_notes

    def test_a_finding_in_edited_words_is_asked_again_and_resolved(self, tandem, tmp_path):
        book = _Book()
        fixed = PROSE.replace('mocked', 'thanked').replace(
            'the lamp burned in the window', 'the lamp burned on the stair')
        out = self._run(tandem, tmp_path, book, fixed)
        assert book.calls.count('open') == gate.GATE_READINGS
        assert book.calls.count('resolved') == 2   # asked twice
        assert out.result.passed and out.prose == fixed
        assert 'the earlier draft said "the lamp burned in the window of the tower"' in (
            book.resolved_prompts[0])
        notes = '; '.join(out.result.check_notes)
        assert '1 asked again in this prose: 0 still there, 1 resolved (PHY vs act1-sc01)' in (
            notes)
        assert os.path.isfile(os.path.join(out.log_dir, 'recheck',
                                           f'gate-resolved-{SCENE}.json'))

    def test_one_still_there_stands_on_the_words_the_asking_gave(self, tandem, tmp_path):
        new = 'the lamp burned on the sill of the tower'
        book = _Book(resolved=lambda n: [ans(1, 'yes', new, 'Still a window.')])
        fixed = PROSE.replace('mocked', 'thanked').replace(LAMP, new)
        out = self._run(tandem, tmp_path, book, fixed, fixed)
        [lamp] = out.result.findings
        assert (lamp.carried, lamp.scene_quote, lamp.problem) == (gate.STILL_THERE, new, '')
        assert '[from the first run; still there after the fix]' in '\n'.join(
            gate.report_lines(out.result))

    def test_a_split_answer_stands(self, tandem, tmp_path):
        book = _Book(resolved=lambda n: [ans(1, 'no')] if not book.resolved_prompts[1:]
                     else [ans(1, 'yes', 'nowhere in it')])
        fixed = PROSE.replace('mocked', 'thanked').replace(LAMP, 'the lamp burned on the sill')
        out = self._run(tandem, tmp_path, book, fixed, fixed)
        # the yes gave no words of the prose: unverified, still blocking
        assert not out.result.passed
        [lamp] = out.result.unverified
        assert lamp.problem == gate.CARRIED_UNPLACED and lamp.carried == gate.STILL_THERE
        assert any('split' in n for n in out.result.check_notes)


# ============================================================================
# The pieces
# ============================================================================

class TestJoin:
    """`gate._ask_questions(tandem=)` on its own."""

    def _join(self, monkeypatch, tmp_path, existing, got, disputes=(), endings=(),
              tandem=gate.READ, cleared=(), unruled=(), ended=()):
        monkeypatch.setattr(questions, 'check_questions', lambda *a, **k: got)
        result = gate.GateResult('s1')
        result.check = CheckResult('s1', findings=list(existing), cleared=list(cleared),
                                   unruled=list(unruled), ended=list(ended))
        gate._ask_questions(str(tmp_path), 's1', 'p', [], [], list(disputes), str(tmp_path),
                            result, endings=list(endings), tandem=tandem)
        return result

    def test_a_shared_layers_slip_is_not_made_twice(self, monkeypatch, tmp_path):
        blk = _f(code='TRT', quote='Tessa mocked Dorren')        # a shared layer's
        mine = _f(code='TRT', quote='mocked Dorren', fact='f')
        got = questions.QuestionResult('s1', findings=[mine])
        result = self._join(monkeypatch, tmp_path, [blk], got)
        assert result.check.findings == [blk] and blk.checker == ''

    def test_the_same_broken_promise_is_one(self, monkeypatch, tmp_path):
        theirs = _f('broken-promise', 'PRM', '', 'outcome', '', gate.OPEN)
        theirs.established_quote = 'Tessa apologizes'
        mine = _f('broken-promise', 'PRM', '', 'outcome', '')
        mine.established_quote = 'Tessa apologizes'
        got = questions.QuestionResult('s1', findings=[mine])
        result = self._join(monkeypatch, tmp_path, [theirs], got)
        assert result.check.findings == [theirs] and theirs.checker == gate.BOTH

    def test_a_contradiction_from_either_stands_and_the_other_ruling_is_said(
            self, monkeypatch, tmp_path):
        d = Dispute('tessa-kind', 'Tessa is never cruel', 'mocked')
        theirs = _f(code='TRT', fact='tessa-kind', source='', checker=gate.OPEN)
        got = questions.QuestionResult('s1', cleared=[d])
        result = self._join(monkeypatch, tmp_path, [theirs], got, disputes=[d])
        assert result.check.findings == [theirs]
        assert result.check.cleared == [] and result.check.unruled == []
        assert result.check_notes == ['dispute on tessa-kind: the open checker found it '
                                      'contradicted, the questions cleared it; the finding '
                                      'stands']
        mine = _f(code='TRT', fact='tessa-kind', source='')
        got = questions.QuestionResult('s1', findings=[mine])
        result = self._join(monkeypatch, tmp_path, [], got, disputes=[d], cleared=[d])
        assert result.check.findings == [mine] and mine.checker == gate.QUESTIONS
        assert result.check.cleared == []
        assert 'the questions found it contradicted, the open checker cleared it' in (
            result.check_notes[0])

    def test_cleared_by_one_and_unruled_by_the_other_is_cleared_and_said(
            self, monkeypatch, tmp_path):
        d, e = Dispute('a', 's', 'c'), Dispute('b', 's', 'c')
        got = questions.QuestionResult('s1', unruled=[d, e])
        result = self._join(monkeypatch, tmp_path, [], got, disputes=[d, e], cleared=[d],
                            unruled=[e])
        assert result.check.cleared == [d] and result.check.unruled == [e]
        assert result.check_notes == ['dispute on a: the open checker cleared it, the '
                                      'questions gave no ruling; cleared']

    def test_an_ending_needs_both(self, monkeypatch, tmp_path):
        a, b, c = (Dispute(x, 's', 'c') for x in 'abc')
        got = questions.QuestionResult('s1', ended=[a, c])
        result = self._join(monkeypatch, tmp_path, [], got, endings=[a, b, c], ended=[a, b])
        assert result.check.ended == [a]
        assert result.check_notes == [
            'ending of b: the open checker found the scene shows it ending, the questions '
            'did not; not recorded',
            'ending of c: the questions found the scene shows it ending, the open checker '
            'did not; not recorded']

    def test_on_a_recheck_the_questions_rule_beside_what_was_carried(
            self, monkeypatch, tmp_path):
        d, e, end = Dispute('a', 's', 'c'), Dispute('b', 's', 'c'), Dispute('x', 's', 'c')
        carried = _f(code='TRT', fact='a', source='', checker=gate.OPEN)
        got = questions.QuestionResult('s1', cleared=[d, e], ended=[end])
        result = self._join(monkeypatch, tmp_path, [carried], got, disputes=[d, e],
                            endings=[end], tandem=gate.CARRIED)
        assert result.check.cleared == [e] and result.check.ended == [end]
        assert 'the open checker found it contradicted, the questions cleared it' in (
            result.check_notes[0])
        assert result.question_notes[-1] == gate.TANDEM_RECHECK_GAP


class TestCarryOpen:
    def _carry(self, monkeypatch, tmp_path, findings, before, after, answer=None,
               disputes=(), run_disputes=()):
        asked = []

        def resolved(scene_id, prose, again, *, model, log_file=''):
            asked.extend(again)
            return answer(again) if answer else questions.Resolved(
                resolved=list(again))
        monkeypatch.setattr(questions, 'ask_resolved', resolved)
        run = gate.GateResult('s1', problems={'disagrees': [
            f's1: {rid} (prose: s1-x)' for rid in run_disputes]})
        run.open_findings, run.open_prose = findings, before
        result = gate.GateResult('s1')
        result.check = CheckResult('s1')
        gate._carry_open('s1', after, run, list(disputes), str(tmp_path), result)
        return result, asked

    def test_the_same_prose_carries_all_with_no_call(self, monkeypatch, tmp_path):
        f = _f(checker=gate.BOTH)
        result, asked = self._carry(monkeypatch, tmp_path, [f], PROSE, PROSE)
        assert asked == [] and [g.carried for g in result.check.findings] == [gate.UNTOUCHED]
        # the questions' half is asked again on this run, so it is the open checker's
        assert result.check.findings[0].checker == gate.OPEN
        assert f.carried == ''   # a copy: the run before's finding is unchanged

    def test_a_promise_with_no_words_is_asked_and_a_resolved_one_dropped(
            self, monkeypatch, tmp_path):
        promise = _f('broken-promise', 'PRM', '', 'outcome', '', gate.OPEN)
        result, asked = self._carry(monkeypatch, tmp_path, [promise], PROSE,
                                    PROSE.replace('mocked', 'thanked'))
        assert asked == [promise] and result.check.findings == []
        assert result.open_findings == []
        assert 'resolved (PRM vs outcome)' in result.check_notes[0]

    def test_a_still_broken_promise_stands_as_it_was(self, monkeypatch, tmp_path):
        promise = _f('broken-promise', 'PRM', 'nearest', 'outcome', '', gate.OPEN)
        result, _ = self._carry(
            monkeypatch, tmp_path, [promise], PROSE, PROSE.replace('mocked', 'thanked'),
            answer=lambda again: questions.Resolved(standing=[(again[0], '')]))
        [g] = result.check.findings
        assert (g.carried, g.scene_quote, g.problem) == (gate.STILL_THERE, '', '')

    def test_a_ruling_on_a_dispute_no_longer_raised_is_dropped(self, monkeypatch, tmp_path):
        ruling = _f(code='TRT', fact='tessa-kind', source='', checker=gate.OPEN)
        result, asked = self._carry(monkeypatch, tmp_path, [ruling], PROSE, PROSE,
                                    run_disputes=['tessa-kind'])
        assert asked == [] and result.check.findings == []
        assert 'dropped: rulings on disputes this run\'s extraction no longer raises' in (
            result.check_notes[0])
        result, _ = self._carry(monkeypatch, tmp_path, [ruling], PROSE, PROSE,
                                run_disputes=['tessa-kind'],
                                disputes=[Dispute('tessa-kind', 's', 'c')])
        assert len(result.check.findings) == 1

    def test_nothing_found_before_is_said(self, monkeypatch, tmp_path):
        result, _ = self._carry(monkeypatch, tmp_path, [], PROSE, PROSE)
        assert result.check_notes == ['re-check: no open reading; the open checker found '
                                      'nothing on the prose before']
        assert result.open_findings == []

    def test_a_failed_asking_is_a_gate_error(self, monkeypatch, tmp_path):
        def boom(again):
            raise questions.QuestionError('s1: refused')
        with pytest.raises(gate.GateError, match='refused'):
            self._carry(monkeypatch, tmp_path, [_f(quote='not there')], PROSE,
                        PROSE.replace('mocked', 'thanked'), answer=boom)


class TestAskResolved:
    def test_two_noes_resolve_anything_else_stands(self):
        a, b, c = _f(quote='one'), _f(quote='two'), _f(quote='three')
        said = {1: [ans(1, 'no'), ans(2, 'yes', 'Tessa mocked Dorren'), ans(3, 'no')],
                2: [ans(1, 'no'), ans(2, 'yes', 'not in it'), ans(3, 'yes', 'nowhere')]}
        prompts = []

        def fake(path, body, **k):
            prompt = body['messages'][0]['content']
            prompts.append(prompt)
            asking = 2 if 'independent asking 2' in prompt else 1
            if asking == 2:   # listed in reverse, numbered as the first
                return _text({'answers': said[2]})
            return _text({'answers': said[1]})
        with patch('storyforge.api._api_request', side_effect=fake):
            got = questions.ask_resolved(SCENE, PROSE, [a, b, c], model='m')
        assert got.resolved == [a]
        assert got.standing == [(b, 'Tessa mocked Dorren'), (c, '')]
        assert got.notes == ['1 split answer(s): they stand (only two noes clear one)']
        assert len(prompts) == 2 and all(PROSE in p for p in prompts)

    def test_no_findings_no_call(self):
        with patch('storyforge.api._api_request', side_effect=AssertionError('no call')):
            assert questions.ask_resolved(SCENE, PROSE, [], model='m') == questions.Resolved()

    def test_the_prompt_names_each_problem(self):
        promise = _f('broken-promise', 'PRM', '', 'outcome', '')
        promise.established_quote = 'Tessa apologizes'
        text = questions.build_resolved_prompt(SCENE, PROSE, [_f(), promise])
        assert (f'1. A contradiction (PHY): the earlier draft said "{LAMP}", but act1-sc01 '
                f'has "{EARLIER}". Why: why') in text
        assert '2. A broken promise (outcome): the brief promises "Tessa apologizes".' in text
        assert 'Does the scene still fail to deliver it?' in text


# ============================================================================
# The flags, the forecast, the messages
# ============================================================================

class TestFlags:
    def test_forced_method_sets_the_flag_and_puts_both_back(self, monkeypatch):
        monkeypatch.setattr(gate, 'GATE_CHECK_METHOD', 'tandem')
        assert gate.pending_command() == 'storyforge check --pending'
        with gate.forced_check_method('open'):
            assert gate.GATE_CHECK_METHOD == 'open'
            assert gate.pending_command() == 'storyforge check --pending --open'
        with pytest.raises(RuntimeError):
            with gate.forced_check_method('questions'):
                assert gate.pending_command() == 'storyforge check --pending --questions'
                raise RuntimeError('boom')
        assert gate.GATE_CHECK_METHOD == 'tandem'
        assert gate.pending_command() == 'storyforge check --pending'
        with pytest.raises(ValueError):
            with gate.forced_check_method('guess'):
                pass

    def test_the_forecast_prices_tandem(self, monkeypatch):
        monkeypatch.setattr(gate, 'GATE_CHECK_METHOD', 'tandem')
        assert gate.recheck_cost_per_scene() == gate.TANDEM_GATE_COST_PER_SCENE
        assert gate.TANDEM_GATE_COST_PER_SCENE > gate.RECHECK_COST_PER_SCENE
        assert gate.write_gate_cost_per_scene() == pytest.approx(
            gate.TANDEM_GATE_COST_PER_SCENE * gate.WRITE_GATE_FIX_SHARE)

    @pytest.mark.parametrize('cmd', ['check', 'write'])
    def test_one_method_flag_at_most(self, cmd, capsys):
        from storyforge import cmd_check, cmd_write
        parse = cmd_check.parse_args if cmd == 'check' else cmd_write.parse_args
        with pytest.raises(SystemExit):
            parse(['--open', '--questions', SCENE])
        from storyforge.cli import check_method
        assert check_method(parse(['--open', SCENE])) == 'open'
        assert check_method(parse(['--tandem', SCENE])) == 'tandem'
        assert check_method(parse([SCENE])) is None

    @pytest.mark.parametrize('flag,method', [('--open', 'open'), ('--tandem', 'tandem'),
                                             ('--questions', 'questions')])
    def test_check_runs_under_the_flags_method(self, project_dir, monkeypatch, flag, method):
        from storyforge import cmd_check
        seen = []
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '100')
        monkeypatch.setattr(cmd_check, 'detect_project_root', lambda: project_dir)
        monkeypatch.setattr(cmd_check, '_check_scenes',
                            lambda *a, **k: seen.append((gate.GATE_CHECK_METHOD,
                                                         gate.pending_command()))
                            or (_ for _ in ()).throw(SystemExit(7)))
        monkeypatch.setattr('storyforge.git.create_branch', lambda *a, **k: True)
        monkeypatch.setattr(gate, 'GATE_CHECK_METHOD', 'tandem')
        with pytest.raises(SystemExit) as e:
            cmd_check.main([flag, SCENE])
        assert e.value.code == 7
        assert seen == [(method, f'storyforge check --pending {flag}')]
        assert gate.GATE_CHECK_METHOD == 'tandem' and gate.pending_command() == (
            'storyforge check --pending')

    @pytest.mark.parametrize('flag', ['--open', '--tandem'])
    def test_accept_and_blocking_take_no_method(self, project_dir, monkeypatch, capsys, flag):
        from storyforge import cmd_check
        monkeypatch.chdir(project_dir)
        monkeypatch.setattr(cmd_check, 'detect_project_root', lambda: project_dir)
        for argv in (['--accept', SCENE, flag], ['--blocking', flag]):
            with pytest.raises(SystemExit) as e:
                cmd_check.main(argv)
            assert e.value.code == 1
        out = capsys.readouterr().out
        assert '--accept takes its own scene list' in out
        assert f'{flag} checks a scene against the book' in out

    def test_write_open_runs_under_the_open_checker(self, monkeypatch):
        from storyforge import cmd_write
        seen = []
        monkeypatch.setattr(gate, 'GATE_CHECK_METHOD', 'tandem')
        monkeypatch.setattr(cmd_write, '_main', lambda args: seen.append(
            (gate.GATE_CHECK_METHOD, cmd_write.gate_pending_command())))
        cmd_write.main(['--open', SCENE])
        cmd_write.main([SCENE])
        assert seen == [('open', 'storyforge check --pending --open'),
                        ('tandem', 'storyforge check --pending')]
        assert gate.GATE_CHECK_METHOD == 'tandem'
