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
        # the same fact (#738's review CR-3: the same words alone are not enough)
        book = _Book(open_findings=[{**_lamp('Tessa mocked Dorren'), 'code': 'TRT',
                                     'fact_id': 'tessa-kind'}])
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
              tandem=gate.READ, cleared=(), unruled=(), ended=(), view=None):
        monkeypatch.setattr(questions, 'check_questions', lambda *a, **k: got)
        result = gate.GateResult('s1')
        result.check = CheckResult('s1', findings=list(existing), cleared=list(cleared),
                                   unruled=list(unruled), ended=list(ended))
        if view is not None:
            result.open_rulings = view
        elif tandem == gate.READ:
            result.open_rulings = gate.OpenRulings.of(result.check, list(disputes),
                                                      list(endings))
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
        assert result.check_notes == ['dispute on a: the open checker on the first run found '
                                      'it contradicted, the questions cleared it; the finding '
                                      'stands',
                                      'ending of x: recorded on the questions\' answer alone; '
                                      'the open checker\'s view was not read again on this '
                                      're-check']
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


# ============================================================================
# #738's review (PR #767)
# ============================================================================

class TestSameCheck:
    """T-1 / CR-3: `_same_check` keeps two problems two."""

    def test_the_same_fact_on_the_same_words_is_one(self):
        a = _f(code='TRT', quote='Tessa mocked Dorren', fact='tessa-kind', checker=gate.OPEN)
        b = _f(code='TRT', quote='mocked Dorren', fact='tessa-kind')
        assert gate._same_check(a, b)

    @pytest.mark.parametrize('b', [
        _f(code='REL', quote='mocked Dorren', fact='tessa-kind'),        # another code
        _f(code='TRT', quote='until he left', fact='tessa-kind'),        # other words
        _f(code='TRT', quote='mocked Dorren', fact='kael-shy',           # another fact
           source='act1-sc03'),
        _f('broken-promise', 'TRT', 'Tessa mocked Dorren', 'outcome', ''),  # a promise
    ])
    def test_two_stay_two(self, b):
        a = _f(code='TRT', quote='Tessa mocked Dorren', fact='tessa-kind', checker=gate.OPEN)
        assert not gate._same_check(a, b)

    def test_two_facts_in_one_sentence_stay_two(self):
        # the same source scene, other established words, no shared fact id
        a = _f(code='PHY', quote='Tessa mocked Dorren', fact='', checker=gate.OPEN)
        b = _f(code='PHY', quote='mocked Dorren', fact='tessa-kind')
        b.established_quote = 'Tessa is never cruel to Dorren'
        assert not gate._same_check(a, b)

    def test_two_different_promises_stay_two(self):
        a = _f('broken-promise', 'PRM', '', 'outcome', '', gate.OPEN)
        a.established_quote = 'Tessa apologizes'
        b = _f('broken-promise', 'PRM', '', 'outcome', '')
        b.established_quote = 'Dorren forgives her'
        assert not gate._same_check(a, b)


class TestReviewJoin(TestJoin):
    def test_a_question_contradiction_left_out_as_a_repeat_still_rules(
            self, monkeypatch, tmp_path):
        # SF-1: the questions found the dispute contradicted on a shared
        # layer's words; the open checker cleared it: a contradiction, not
        # cleared, and said
        d = Dispute('tessa-kind', 's', 'c')
        blk = _f(code='TRT', quote='Tessa mocked Dorren', fact='')
        mine = _f(code='TRT', quote='mocked Dorren', fact='tessa-kind', source='')
        got = questions.QuestionResult('s1', findings=[mine])
        result = self._join(monkeypatch, tmp_path, [blk], got, disputes=[d], cleared=[d])
        assert result.check.findings == [blk] and result.check.cleared == []
        assert result.check.unruled == []
        assert result.check_notes == ['dispute on tessa-kind: the questions found it '
                                      'contradicted, the open checker cleared it; the '
                                      'finding stands']

    def test_cleared_by_the_questions_alone_is_said(self, monkeypatch, tmp_path):
        # T-3: the whole list, both directions
        d = Dispute('a', 's', 'c')
        got = questions.QuestionResult('s1', cleared=[d])
        result = self._join(monkeypatch, tmp_path, [], got, disputes=[d], unruled=[d])
        assert result.check.cleared == [d]
        assert result.check_notes == ['dispute on a: the questions cleared it, the open '
                                      'checker gave no ruling; cleared']

    def test_a_recheck_keeps_the_first_runs_clearing_and_ending(self, monkeypatch, tmp_path):
        # CR-1/CR-2: carried rulings; the questions split now
        d, end, new = Dispute('a', 's', 'c'), Dispute('x', 's', 'c'), Dispute('y', 's', 'c')
        view = gate.OpenRulings({'a': 'c'}, {'a'}, {'x': 'c'}, set())
        got = questions.QuestionResult('s1', unruled=[d], ended=[end, new])
        result = self._join(monkeypatch, tmp_path, [], got, disputes=[d],
                            endings=[end, new], tandem=gate.CARRIED, view=view)
        assert result.check.cleared == [d] and result.check.unruled == []
        # x: the open checker said not ending, on words the fix left alone
        assert result.check.ended == [new]
        assert result.check_notes == [
            'dispute on a: the open checker on the first run cleared it, the questions gave '
            'no ruling; cleared',
            'ending of x: the questions found the scene shows it ending, the open checker '
            'on the first run did not; not recorded',
            'ending of y: recorded on the questions\' answer alone; the open checker\'s view '
            'was not read again on this re-check']

    def test_the_brief_reports_join_without_repeats(self, monkeypatch, tmp_path):
        # T-7
        got = questions.QuestionResult(
            's1', kept=[('k1', 'q'), ('k2', 'q2')], kept_unverified=[('k1', 'q', 'short'),
                                                                   ('k3', 'q', 'short')],
            plan_departures=[_f('broken-promise', 'PRM', '', 'p1', ''),
                             _f('broken-promise', 'PRM', '', 'p2', '')],
            unknown_brief_items=['a', 'b'], asked_fact_ids=['f1', 'f2', 'f1'])
        monkeypatch.setattr(questions, 'check_questions', lambda *a, **k: got)
        result = gate.GateResult('s1', asked_fact_ids=['f2'])
        result.check = CheckResult('s1', kept=[('k1', 'open')],
                                   kept_unverified=[('k2', 'q2', 'short')],
                                   plan_departures=[_f('broken-promise', 'PRM', '', 'p1', '')],
                                   unknown_brief_items=['a'])
        result.open_rulings = gate.OpenRulings()
        gate._ask_questions(str(tmp_path), 's1', 'p', [], [], [], str(tmp_path), result,
                            tandem=gate.READ)
        assert result.check.kept == [('k1', 'open'), ('k2', 'q2')]
        assert result.check.kept_unverified == [('k3', 'q', 'short')]
        assert [f.fact_id for f in result.check.plan_departures] == ['p1', 'p2']
        assert result.check.unknown_brief_items == ['a', 'b']
        assert result.asked_fact_ids == ['f2', 'f1']


class TestReviewCarry(TestCarryOpen):
    def test_a_verified_quote_clears_the_old_problem(self, monkeypatch, tmp_path):
        # SF-4
        f = _f(quote='not there', checker=gate.OPEN, problem='the quote is not in the scene')
        result, _ = self._carry(
            monkeypatch, tmp_path, [f], PROSE, PROSE.replace('mocked', 'thanked'),
            answer=lambda again: questions.Resolved(standing=[(again[0], 'Tessa thanked')]))
        [g] = result.check.findings
        assert (g.scene_quote, g.problem) == ('Tessa thanked', '')

    def test_words_changed_where_they_stood_are_asked_though_found_elsewhere(
            self, monkeypatch, tmp_path):
        # T-8: the quote twice before the fix; the fix changes the first
        twice = f'{LAMP} at dusk. Tessa mocked Dorren once more. Later {LAMP} at dawn.'
        after = twice.replace(f'{LAMP} at dusk', 'a candle guttered at dusk', 1)
        f = _f(checker=gate.OPEN)
        _, asked = self._carry(monkeypatch, tmp_path, [f], twice, after)
        assert asked == [f]

    def test_rulings_carry_only_on_untouched_words(self, monkeypatch, tmp_path):
        # CR-1/CR-2: the claim's words decide
        before = ('Tessa mocked Dorren until he left the study and walked far into the '
                  'night. Kael healed by morning.')
        after = before.replace('mocked', 'thanked')
        run_view = gate.OpenRulings({'a': 'Tessa mocked Dorren', 'b': 'healed by morning'},
                                    {'a', 'b'}, {'e': 'Kael healed by morning'}, {'e'})
        run = gate.GateResult('s1')
        run.open_findings, run.open_prose, run.open_rulings = [], before, run_view
        result = gate.GateResult('s1')
        result.check = CheckResult('s1')
        ds = [Dispute('a', 's', 'Tessa mocked Dorren'), Dispute('b', 's', 'healed by morning')]
        gate._carry_open('s1', after, run, ds, str(tmp_path), result,
                         endings=[Dispute('e', 's', 'Kael healed by morning')])
        assert result.open_rulings == gate.OpenRulings(
            {'b': 'healed by morning'}, {'b'}, {'e': 'Kael healed by morning'}, {'e'})
        assert result.check_notes[-1] == (
            'the open checker\'s first-run ruling on 1 item(s) not carried, the fix changed '
            'the words it ruled on (the questions alone rule them): dispute on a')


class TestReviewWiring:
    """T-2: the runs that make no open reading are handed the one before."""

    def _capture(self, monkeypatch):
        seen = []

        def fake(*a, **k):
            seen.append(k)
            r = gate.GateResult('s1')
            r.check = CheckResult('s1')
            return r
        monkeypatch.setattr(gate, 'gate_scene', fake)
        return seen

    def test_reextract_hands_on_the_run(self, monkeypatch, tmp_path):
        seen = self._capture(monkeypatch)
        run = gate.GateResult('s1')
        run.check = CheckResult('s1')
        gate._reextract(str(tmp_path), 's1', 'draft', 'p', run, str(tmp_path),
                        extract_model='m', check_model='m', before=None,
                        fallback_dir=str(tmp_path))
        assert seen[0]['open_from'] is run

    def test_partial_fix_hands_on_the_run_before(self, monkeypatch, tmp_path):
        seen = self._capture(monkeypatch)
        before = gate.GateResult('s1')
        monkeypatch.setattr(gate, '_introduced', lambda *a: [_f()])
        monkeypatch.setattr(gate, '_bad_edits', lambda *a: [0])
        monkeypatch.setattr(gate, 'apply_edits', lambda prose, edits: 'kept')
        gate._partial_fix(str(tmp_path), 's1', 'draft', 'p', before, gate.GateResult('s1'),
                          None, [{'find': 'a'}, {'find': 'b'}], log_dir=str(tmp_path),
                          extract_model='m', check_model='m', before=None)
        assert seen[0]['open_from'] is before and seen[0]['carry'] is before


@pytest.mark.continuity
class TestTandemEndToEnd:
    """T-4: tandem runs through the callers."""

    def test_a_recheck_of_unchanged_prose_is_a_first_run(self, tandem, tmp_path):
        book = _Book()
        with patch('storyforge.api._api_request', side_effect=book):
            result, _ = gate.gate_unchanged(tandem, SCENE, command='recheck',
                                            log_dir=str(tmp_path / 'logs'),
                                            extract_model='m', check_model='m')
        assert book.calls.count('open') == gate.GATE_READINGS
        assert 'questions' in book.calls and result.check_notes[0].startswith('first run')

    def test_a_carried_finding_and_a_continuity_slip_on_its_words_are_one(
            self, tandem, tmp_path, monkeypatch):
        # CR-4: the carry comes before the shared layers' findings
        slip = _f(code='PHY', quote=LAMP)
        real = gate._read_continuity

        def read(*a, **k):
            got = real(*a, **k)
            got.findings.append(slip)
            return got
        monkeypatch.setattr(gate, '_read_continuity', read)
        book = _Book()
        with patch('storyforge.api._api_request', side_effect=book):
            out = gate.gate_and_fix(tandem, SCENE, command='draft', prose=PROSE,
                                    log_dir=str(tmp_path / 'logs'), extract_model='m',
                                    check_model='m',
                                    fixer=_fixer(PROSE.replace('mocked', 'thanked')))
        assert [(f.code, f.carried) for f in out.result.findings] == [('PHY', gate.UNTOUCHED)]

    def test_a_reextraction_after_the_fix_makes_no_open_reading(self, tandem, tmp_path,
                                                                monkeypatch):
        book = _Book()
        slips = iter([['m1: "x" is not in the scene']])
        monkeypatch.setattr(gate, '_slips_beside_findings', lambda r: next(slips, []))
        with patch('storyforge.api._api_request', side_effect=book):
            out = gate.gate_and_fix(tandem, SCENE, command='draft', prose=PROSE,
                                    log_dir=str(tmp_path / 'logs'), extract_model='m',
                                    check_model='m',
                                    fixer=_fixer(PROSE.replace('mocked', 'thanked')))
        assert out.reextraction is not None
        assert book.calls.count('open') == gate.GATE_READINGS
        assert [f.carried for f in out.result.findings] == [gate.UNTOUCHED]


class TestReviewCommands:
    def test_write_refuses_the_default_without_continuity(self, project_dir, monkeypatch,
                                                         capsys):
        # T-5: the default tandem needs the typed state; --open doesn't
        from storyforge import cmd_write
        monkeypatch.setattr(gate, 'GATE_CHECK_METHOD', 'tandem')
        monkeypatch.setattr(gate, 'GATE_CONTINUITY', False)
        monkeypatch.chdir(project_dir)
        monkeypatch.setattr(cmd_write, 'detect_project_root', lambda: project_dir)
        with pytest.raises(SystemExit) as e:
            cmd_write.main(['--coaching', 'full', '--scenes', SCENE])
        assert e.value.code == 1
        assert ('the gate (its default check, both checkers) needs the gate\'s continuity'
                in capsys.readouterr().out)
        # --open runs without the typed state: a dry run goes through
        cmd_write.main(['--open', '--dry-run', '--coaching', 'full', '--scenes', SCENE])
        assert 'continuity checks' not in capsys.readouterr().out

    def test_recheck_over_the_threshold_names_the_runs_flag(self, project_dir, tmp_path,
                                                            monkeypatch, capsys):
        # T-6
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '0.1')
        gate.mark_pending(project_dir, 'act2-sc01', 'recheck', 're-check: x')
        with gate.forced_check_method('open'), \
                patch('storyforge.api._api_request', side_effect=AssertionError('spent')):
            run = gate.recheck_pending(project_dir, log_dir=str(tmp_path))
        assert run.over_budget
        assert '`storyforge check --pending --open`' in capsys.readouterr().out
