"""Tests for storyforge.questions (#649, plan A3) and storyforge.yes_no, the
ask-twice machinery it shares with the stage sheet (#647): which ledger
facts are asked about, for whom; the questions code writes; the two-yeses-
and-a-verified-quote rule; disputes; the gate's `questions` method and
`check --questions`. The API is mocked at `api._api_request`. Every scene,
name and fact here is invented for the tests."""

import json
import os
from unittest.mock import patch

import pytest

from storyforge import gate, questions, yes_no
from storyforge.checker import Dispute
from storyforge.questions import Question, QuestionError, facts_to_ask, present_subjects
from storyforge.typed_state import Record

SCENE = 'act1-sc02'


def _text(payload, stop='end_turn'):
    return {'stop_reason': stop, 'model': 'claude-haiku-5-5',
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 1, 'output_tokens': 1}}


def row(rid, type_='trait', subject='mara', scene='s1', statement='', status='binding',
        mutable='fixed', **more):
    return {'id': rid, 'scene_id': scene, 'type': type_, 'subject': subject,
            'statement': statement or f'{rid} statement', 'quote': more.pop('quote', ''),
            'status': status, 'mutable': mutable, 'supersedes': more.pop('supersedes', ''),
            'resolves': more.pop('resolves', ''), 'category': more.pop('category', ''), **more}


ORDER = {'s1': 0, 's2': 1, 's3': 2, 's4': 3}


def _is_questions(body):
    schema = (body.get('output_config') or {}).get('format', {}).get('schema', {})
    item = schema.get('properties', {}).get('answers', {}).get('items', {})
    return 'quote' in item.get('properties', {})


def _answering(answers, asked=None):
    """A fake API: `answers(asking, count)` → the answers list."""
    asked = asked if asked is not None else []

    def fake(path, body, **k):
        assert _is_questions(body), 'only question calls expected'
        prompt = body['messages'][0]['content']
        asked.append(prompt)
        n = prompt.count('   Question: ')
        asking = 2 if 'independent asking 2' in prompt else 1
        return _text({'answers': answers(asking, n)})
    return fake


def ans(n, answer, quote='', why='because'):
    return {'n': n, 'answer': answer, 'quote': quote, 'why': why}


# ============================================================================
# yes_no: the shared machinery
# ============================================================================

class TestYesNo:
    def test_parse_answers_takes_the_fields_asked_for(self):
        text = json.dumps({'answers': [{'n': 1, 'answer': 'yes', 'quote': ' a b ', 'why': 'w'}]})
        assert yes_no.parse_answers(text, 1, ('quote', 'why')) == {
            1: {'answer': 'yes', 'quote': 'a b', 'why': 'w'}}
        with pytest.raises(ValueError, match='not the schema'):
            yes_no.parse_answers(json.dumps({'answers': [{'n': 1, 'answer': 'yes',
                                                          'why': 'w'}]}), 1, ('quote', 'why'))

    def test_answers_cover_every_question_once(self):
        with pytest.raises(ValueError, match='exactly'):
            yes_no.parse_answers(json.dumps({'answers': [{'n': 1, 'answer': 'no',
                                                          'why': ''}]}), 2)
        with pytest.raises(ValueError, match='answered twice'):
            yes_no.parse_answers(json.dumps({'answers': [
                {'n': 1, 'answer': 'no', 'why': ''}, {'n': 1, 'answer': 'no', 'why': ''}]}), 1)

    def test_agreed_and_split(self):
        a1 = {1: {'answer': 'yes'}, 2: {'answer': 'yes'}, 3: {'answer': 'no'}}
        a2 = {1: {'answer': 'yes'}, 2: {'answer': 'no'}, 3: {'answer': 'no'}}
        assert yes_no.agreed([a1, a2], 3, 'yes') == ([1], 1)
        assert yes_no.agreed([a1, a2], 3, 'no') == ([3], 1)

    def test_asking_log(self):
        assert yes_no.asking_log('/l/q.json', 1) == '/l/q.json'
        assert yes_no.asking_log('/l/q.json', 2) == '/l/q.a2.json'
        assert yes_no.asking_log('', 2) == ''

    def test_ask_raises_the_callers_error(self):
        class Mine(RuntimeError):
            pass

        def fake(path, body, **k):
            return _text({'nope': 1})
        with patch('storyforge.api._api_request', side_effect=fake):
            with pytest.raises(Mine, match='the things failed twice'):
                yes_no.ask(lambda n: 'p', 1, model='m', log_file='', tokens=100,
                           schema={}, label='l', what='the things', error=Mine)

    def test_no_questions_no_call(self):
        assert yes_no.ask(lambda n: pytest.fail('no prompt'), 0, model='m', log_file='',
                          tokens=1, schema={}, label='l', what='w', error=RuntimeError) == []

    def test_the_stage_sheet_uses_it(self):
        from storyforge import stage_sheet
        assert stage_sheet.ASKINGS == yes_no.ASKINGS == questions.ASKINGS == 2


# ============================================================================
# Which facts, about whom
# ============================================================================

class TestPresent:
    CHARS = {'mara': 'mara', 'mara vell': 'mara', 'oren': 'oren-tal', 'oren tal': 'oren-tal'}
    PLACES = {'mill': 'the-mill', 'the old mill': 'the-mill', 'harbour': 'harbour'}

    def test_at_records_through_the_registry_and_places(self):
        recs = [Record('at', 'Mara Vell', 'the mill'), Record('at', 'Oren', ''),
                Record('named', 'Lise', value='Lise'), Record('at', 'a stranger', 'the moon')]
        got = present_subjects(recs, self.CHARS, self.PLACES, location='Harbour')
        assert got == {'mara', 'oren tal', 'the mill', 'harbour', 'a stranger'}

    def test_a_name_only_mentioned_is_not_present(self):
        assert present_subjects([Record('named', 'Mara', value='Mara')], self.CHARS,
                                self.PLACES) == set()


class TestFactsToAsk:
    def ask(self, rows, scene='s3', present=('mara',)):
        got, no_subject = facts_to_ask(rows, scene, ORDER, set(present))
        return [r['id'] for r in got], no_subject

    def test_only_the_types_no_typed_check_compares(self):
        rows = [row('t', 'trait'), row('r', 'relationship'), row('w', 'world'),
                row('p', 'physical', category='appearance'), row('k', 'knowledge'),
                row('tl', 'timeline'), row('pr', 'promise'),
                row('inj', 'physical', category='injury'),
                row('eq', 'physical', category='Equipment')]
        assert self.ask(rows)[0] == ['t', 'r', 'p', 'w']

    def test_only_subjects_present(self):
        rows = [row('a', subject='mara'), row('b', subject='oren-tal'),
                row('c', subject='Mara')]
        assert self.ask(rows)[0] == ['a', 'c']
        assert self.ask(rows, present=('mara', 'oren tal'))[0] == ['a', 'b', 'c']

    def test_no_subject_is_counted_not_asked(self):
        assert self.ask([row('a', subject=''), row('b')]) == (['b'], 1)

    def test_fixed_facts_from_any_other_scene_but_the_scenes_own(self):
        rows = [row('early', scene='s1'), row('later', scene='s4'), row('own', scene='s3'),
                row('backstory', scene=''), row('gone', scene='cut-scene')]
        assert sorted(self.ask(rows)[0]) == ['backstory', 'early', 'gone', 'later']

    def test_state_facts_only_while_in_force(self):
        rows = [row('now', mutable='state', scene='s1'),
                row('ended', mutable='state', scene='s1', resolves='s2'),
                row('ends-here', mutable='state', scene='s1', resolves='s3'),
                row('not-yet', mutable='state', scene='s4')]
        assert self.ask(rows)[0] == ['ends-here', 'now']   # one scene: by id

    def test_not_binding_or_superseded(self):
        rows = [row('planned', status='planned'), row('pending', status='pending'),
                row('old'), row('new', supersedes='old'),
                row('rej', status='rejected')]
        assert self.ask(rows)[0] == ['new']

    def test_type_order_then_reading_order(self):
        rows = [row('w1', 'world', scene='s1'), row('t4', scene='s4'), row('t1', scene='s1'),
                row('r2', 'relationship', scene='s2')]
        assert self.ask(rows)[0] == ['t1', 't4', 'r2', 'w1']


class TestQuestionFor:
    def test_written_by_code_from_type_subject_and_statement(self):
        q = questions.question_for(row('f', 'relationship', scene='s1',
                                       statement='Mara  is Oren\'s sister',
                                       quote='my sister'), 'Mara Vell', ORDER)
        assert q.statement == "Mara is Oren's sister" and q.code == 'REL'
        assert q.established_scene == 's1' and q.established_quote == 'my sister'
        assert 'Mara Vell' in q.text and q.text.endswith('rules out?')

    def test_a_fact_with_no_scene_of_the_book_is_the_ledgers(self):
        q = questions.question_for(row('f', scene='cut-scene', quote='q'), 'Mara', ORDER)
        assert q.established_scene == '' and q.established_quote == 'f statement'

    def test_each_type_has_its_own_question(self):
        texts = {questions.question_for(row('f', t), 'Mara').text
                 for t in questions.QUESTION_TYPES}
        assert len(texts) == len(questions.QUESTION_TYPES)


# ============================================================================
# Asking
# ============================================================================

PROSE = 'Mara slammed the door on her brother. Oren laughed at the mill wheel.'


def Q(fid, type_='trait', claim=''):
    return Question(fid, type_, 'Mara', f'{fid} holds', 's1', f'{fid} words',
                    'Does this scene rule it out?', claim=claim)


class TestAskQuestions:
    def _ask(self, qs, answers, **kw):
        asked = []
        with patch('storyforge.api._api_request', side_effect=_answering(answers, asked)):
            r = questions.ask_questions(SCENE, PROSE, qs, model='m', **kw)
        return r, asked

    def test_two_yeses_and_a_verified_quote_make_a_finding(self):
        r, asked = self._ask([Q('gentle'), Q('kin', 'relationship')], lambda a, n: [
            ans(1, 'yes', 'slammed the door on her brother', 'She is rough.'),
            ans(2, 'no')])
        assert len(asked) == 2 and r.asked == 2
        assert len(r.findings) == 1
        f = r.findings[0]
        assert (f.code, f.kind, f.fact_id, f.scene_quote) == (
            'TRT', 'contradiction', 'gentle', 'slammed the door on her brother')
        assert f.established_scene == 's1' and f.established_quote == 'gentle words'
        assert '(question, asked 2 times)' in f.explanation and 'She is rough.' in f.explanation
        assert r.notes == []

    def test_one_yes_is_split_not_a_finding(self):
        r, _ = self._ask([Q('gentle')], lambda a, n: [
            ans(1, 'yes' if a == 1 else 'no', 'slammed the door')])
        assert r.findings == []
        assert r.notes == ['1 question(s) got split answers: not findings']

    def test_two_yeses_with_no_quote_in_the_scene_are_noted(self):
        r, _ = self._ask([Q('gentle')], lambda a, n: [ans(1, 'yes', 'she struck him')])
        assert r.findings == []
        assert r.notes == ['1 question(s) answered yes twice with no quote in the scene: not '
                           'findings']

    def test_the_second_askings_quote_when_the_first_isnt_in_the_scene(self):
        r, _ = self._ask([Q('gentle')], lambda a, n: [
            ans(1, 'yes', 'not there' if a == 1 else 'Oren laughed')])
        assert [f.scene_quote for f in r.findings] == ['Oren laughed']

    def test_the_second_asking_reverses_and_says_so(self):
        _, asked = self._ask([Q('first'), Q('second')],
                             lambda a, n: [ans(i, 'no') for i in range(1, n + 1)])
        one, two = asked
        assert one.index('first holds') < one.index('second holds')
        assert two.index('second holds') < two.index('first holds')
        assert 'independent asking 2' in two and 'independent asking' not in one
        assert 'Established in s1: "first holds"' in one
        assert 'Its words there: "first words"' in one

    def test_past_the_cap_is_noted(self, monkeypatch):
        monkeypatch.setattr(questions, 'MAX_QUESTIONS', 1)
        r, asked = self._ask([Q('a'), Q('b'), Q('c')], lambda a, n: [ans(1, 'no')])
        assert r.asked == 1 and asked[0].count('   Question: ') == 1
        assert r.notes == ['2 question(s) past the 1 a scene gets: not asked']

    def test_a_bad_reply_twice_is_a_question_error(self):
        def fake(path, body, **k):
            return _text({'answers': []})
        with patch('storyforge.api._api_request', side_effect=fake):
            with pytest.raises(QuestionError, match='the questions failed twice'):
                questions.ask_questions(SCENE, PROSE, [Q('a')], model='m')

    def test_a_later_asking_logs_beside_the_first(self, tmp_path):
        log = str(tmp_path / 'q.json')
        self._ask([Q('a')], lambda a, n: [ans(1, 'no')], log_file=log)
        assert os.path.isfile(log) and os.path.isfile(str(tmp_path / 'q.a2.json'))


class TestDisputes:
    D = Dispute('reg-fact', 'Mara is gentle', 'Mara slammed the door')

    def _ask(self, answers):
        q = questions.dispute_question(self.D, row('reg-fact', 'trait', quote='kind words'),
                                       'Mara')
        with patch('storyforge.api._api_request', side_effect=_answering(answers)):
            return questions.ask_questions(SCENE, PROSE, [q], model='m',
                                           disputes={self.D.fact_id: self.D})

    def test_the_question_names_the_claim(self):
        q = questions.dispute_question(self.D, None)
        assert '"Mara slammed the door"' in q.text and q.claim

    def test_two_yeses_are_a_contradiction(self):
        r = self._ask(lambda a, n: [ans(1, 'yes', 'Mara slammed the door')])
        assert [f.fact_id for f in r.findings] == ['reg-fact']
        assert r.cleared == [] and r.unruled == []

    def test_two_noes_clear_it(self):
        r = self._ask(lambda a, n: [ans(1, 'no')])
        assert r.cleared == [self.D] and r.unruled == [] and r.findings == []

    @pytest.mark.parametrize('answers', [
        lambda a, n: [ans(1, 'yes' if a == 1 else 'no', 'Mara slammed the door')],
        lambda a, n: [ans(1, 'yes', 'not in the scene')]])
    def test_anything_else_leaves_it_unruled(self, answers):
        r = self._ask(answers)
        assert r.unruled == [self.D] and r.cleared == [] and r.findings == []

    def test_a_dispute_past_the_cap_is_unruled(self, monkeypatch):
        monkeypatch.setattr(questions, 'MAX_QUESTIONS', 1)
        q = questions.dispute_question(self.D, None)
        with patch('storyforge.api._api_request',
                   side_effect=_answering(lambda a, n: [ans(1, 'no')])):
            r = questions.ask_questions(SCENE, PROSE, [Q('a'), q], model='m',
                                        disputes={self.D.fact_id: self.D})
        assert r.unruled == [self.D]


# ============================================================================
# The check on a project
# ============================================================================

def _add_rows(project_dir, *rows):
    from storyforge import ledger
    have = ledger.load(project_dir)
    for r in rows:
        have.append({**{c: '' for c in ledger.COLUMNS}, 'origin': 'prose', **r})
    ledger.write_ledger(ledger.ledger_path(project_dir), have)
    return have


TESSA_KIND = {'id': 'tessa-kind', 'scene_id': 'act1-sc01', 'type': 'trait',
              'subject': 'tessa-merrin', 'statement': 'Tessa is never cruel to Dorren',
              'status': 'binding', 'mutable': 'fixed'}
KAEL_SHY = {'id': 'kael-shy', 'scene_id': 'act1-sc01', 'type': 'trait',
            'subject': 'kael-maren', 'statement': 'Kael avoids crowds', 'status': 'binding',
            'mutable': 'fixed'}
STUDY_DARK = {'id': 'study-dark', 'scene_id': 'act1-sc01', 'type': 'world',
              'subject': 'private-study', 'statement': 'The study has no window',
              'status': 'binding', 'mutable': 'fixed'}
TESSA_PROSE = 'Tessa mocked Dorren until he left the study.'


class TestCheckQuestions:
    def test_asks_about_who_is_there_and_the_place(self, project_dir):
        rows = _add_rows(project_dir, TESSA_KIND, KAEL_SHY, STUDY_DARK)
        asked = []
        with patch('storyforge.api._api_request', side_effect=_answering(
                lambda a, n: [ans(1, 'yes', 'Tessa mocked Dorren', 'Cruel.')]
                + [ans(i, 'no') for i in range(2, n + 1)], asked)):
            r = questions.check_questions(project_dir, SCENE, prose=TESSA_PROSE, rows=rows,
                                          records=[Record('at', 'Tessa', 'the study')],
                                          model='m')
        assert 'Tessa Merrin' in asked[0] and 'Kael' not in asked[0]
        assert 'The study has no window' in asked[0]
        assert r.asked == 2 and [f.fact_id for f in r.findings] == ['tessa-kind']
        assert r.present == ['private study', 'tessa merrin']

    def test_nobody_present_is_said_and_costs_nothing(self, project_dir):
        rows = _add_rows(project_dir, KAEL_SHY)
        with open(os.path.join(project_dir, 'reference', 'scenes.csv')) as f:
            text = f.read()
        with open(os.path.join(project_dir, 'reference', 'scenes.csv'), 'w') as f:
            f.write(text.replace("|Dorren's private study|", '||'))
        with patch('storyforge.api._api_request', side_effect=lambda *a, **k: pytest.fail()):
            r = questions.check_questions(project_dir, SCENE, prose=TESSA_PROSE, rows=rows,
                                          records=[], model='m')
        assert r.asked == 0 and r.findings == []
        assert any('no one present' in n for n in r.notes)

    def test_facts_with_no_subject_are_said(self, project_dir):
        rows = _add_rows(project_dir, {**TESSA_KIND, 'id': 'nobody', 'subject': ''})
        with patch('storyforge.api._api_request',
                   side_effect=_answering(lambda a, n: [ans(i, 'no')
                                                        for i in range(1, n + 1)])):
            r = questions.check_questions(project_dir, SCENE, prose=TESSA_PROSE, rows=rows,
                                          records=[Record('at', 'Tessa', '')], model='m')
        assert any('1 fact(s) of the asked types have no subject' in n for n in r.notes)

    def test_the_model_is_configurable(self, monkeypatch):
        monkeypatch.setenv(questions.MODEL_ENV, 'claude-sonnet-5-5')
        assert questions.resolve_model() == 'claude-sonnet-5-5'
        assert questions.resolve_model('given') == 'given'
        monkeypatch.delenv(questions.MODEL_ENV)
        assert questions.resolve_model() == 'claude-haiku-5-5'


# ============================================================================
# The gate
# ============================================================================

@pytest.mark.continuity
class TestGate:
    def _gate(self, project_dir, tmp_path, monkeypatch, answers, method='questions',
              records=None):
        monkeypatch.setattr(gate, 'GATE_CHECK_METHOD', method)
        _add_rows(project_dir, TESSA_KIND)
        calls = []
        records = records if records is not None else [
            {'type': 'at', 'who': 'Tessa', 'item': 'the study', 'value': '', 'detail': '',
             'quote': 'Tessa mocked Dorren'}]

        def fake(path, body, **k):
            schema = (body.get('output_config') or {}).get('format', {}).get('schema', {})
            if 'tools' in body:
                calls.append('open')
                return _text({'findings': [], 'kept': []})
            if 'records' in schema.get('properties', {}):
                return _text({'records': records})
            if _is_questions(body):
                calls.append('questions')
                prompt = body['messages'][0]['content']
                return _text({'answers': answers(prompt.count('   Question: '))})
            if 'verdicts' in schema.get('properties', {}):
                return _text({'verdicts': []})
            return _text({'commitments': []})
        with open(os.path.join(project_dir, 'scenes', f'{SCENE}.md'), 'w') as f:
            f.write(TESSA_PROSE)
        with patch('storyforge.api._api_request', side_effect=fake):
            result = gate.gate_scene(project_dir, SCENE, command='advisor',
                                     log_dir=str(tmp_path / 'logs'), extract_model='m',
                                     check_model='m')
        return result, calls

    def test_the_questions_replace_the_open_checker(self, project_dir, tmp_path, monkeypatch):
        result, calls = self._gate(project_dir, tmp_path, monkeypatch,
                                   lambda n: [ans(1, 'yes', 'Tessa mocked Dorren', 'Cruel.')])
        assert calls == ['questions', 'questions']
        assert not result.passed and [f.code for f in result.findings] == ['TRT']
        report = '\n'.join(gate.report_lines(result))
        assert 'CONTRADICTION: TRT contradicts act1-sc01 [tessa-kind]' in report
        assert 'NOTE (questions, not checked): ' in report and 'brief promises' in report
        assert os.path.isfile(tmp_path / 'logs' / f'gate-questions-{SCENE}.json')
        assert os.path.isfile(tmp_path / 'logs' / f'gate-questions-{SCENE}.a2.json')
        assert any('BREAKS' in line or 'TRT' in line for line in gate.problems_to_fix(result))

    def test_a_clean_scene_passes_and_says_what_wasnt_checked(self, project_dir, tmp_path,
                                                              monkeypatch):
        result, _ = self._gate(project_dir, tmp_path, monkeypatch, lambda n: [ans(1, 'no')])
        assert result.passed and result.committed
        assert result.question_notes == list(gate.QUESTION_LAYER_GAPS)

    def test_the_open_checker_is_the_default(self, project_dir, tmp_path, monkeypatch):
        assert gate.GATE_CHECK_METHOD == 'open'
        result, calls = self._gate(project_dir, tmp_path, monkeypatch,
                                   lambda n: pytest.fail('no questions'), method='open')
        assert calls == ['open'] and result.passed and result.question_notes == []

    def test_an_unknown_method_is_refused(self, project_dir, tmp_path, monkeypatch):
        with pytest.raises(gate.GateError, match='GATE_CHECK_METHOD'):
            self._gate(project_dir, tmp_path, monkeypatch, lambda n: [], method='guess')

    def test_it_needs_the_typed_state(self, project_dir, tmp_path, monkeypatch):
        monkeypatch.setattr(gate, 'GATE_CONTINUITY', False)
        with pytest.raises(gate.GateError, match='needs the continuity checks'):
            self._gate(project_dir, tmp_path, monkeypatch, lambda n: [])

    def test_a_failed_asking_is_a_gate_error(self, project_dir, tmp_path, monkeypatch):
        with pytest.raises(gate.GateError, match='the questions failed twice'):
            self._gate(project_dir, tmp_path, monkeypatch, lambda n: [])


class TestGateJoin:
    """`gate._ask_questions` on its own: what joins the check."""
    def _join(self, monkeypatch, tmp_path, existing, got):
        from storyforge.checker import CheckResult
        monkeypatch.setattr(questions, 'check_questions', lambda *a, **k: got)
        result = gate.GateResult('s1')
        result.check = CheckResult('s1', findings=list(existing))
        gate._ask_questions(str(tmp_path), 's1', 'p', [], [], [], str(tmp_path), result)
        return result

    def test_one_slip_is_not_two_and_disputes_are_ruled(self, monkeypatch, tmp_path):
        from storyforge.checker import Finding
        theirs = Finding('contradiction', 'TRT', 'Tessa mocked Dorren', 's0', 'x', '', 'state')
        mine = Finding('contradiction', 'TRT', 'mocked Dorren', 's0', 'y', 'f', 'question')
        other = Finding('contradiction', 'REL', 'mocked Dorren', 's0', 'y', 'g', 'question')
        d1, d2 = Dispute('a', 's', 'c'), Dispute('b', 's', 'c')
        got = questions.QuestionResult('s1', findings=[mine, other], cleared=[d1],
                                       unruled=[d2], notes=['1 split'])
        result = self._join(monkeypatch, tmp_path, [theirs], got)
        assert result.check.findings == [theirs, other]
        assert result.check.cleared == [d1] and result.unruled == [d2]
        assert result.question_notes[0] == '1 split' and not result.passed

    def test_an_error_is_a_gate_error(self, monkeypatch, tmp_path):
        from storyforge.checker import CheckResult

        def boom(*a, **k):
            raise QuestionError('s1: the questions failed: refused')
        monkeypatch.setattr(questions, 'check_questions', boom)
        result = gate.GateResult('s1')
        result.check = CheckResult('s1')
        with pytest.raises(gate.GateError, match='refused'):
            gate._ask_questions(str(tmp_path), 's1', 'p', [], [], [], str(tmp_path), result)


# ============================================================================
# storyforge check --questions
# ============================================================================

class TestCheckCommand:
    def _main(self, project_dir, monkeypatch, argv):
        from storyforge import cmd_check
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '100')
        monkeypatch.setattr(cmd_check, 'detect_project_root', lambda: project_dir)
        with patch('storyforge.api._api_request',
                   side_effect=lambda *a, **k: pytest.fail('no call expected')):
            with pytest.raises(SystemExit) as e:
                cmd_check.main(argv)
        return e.value.code

    def test_questions_chooses_the_gate_method(self, project_dir, monkeypatch):
        from storyforge import cmd_check
        seen = []
        monkeypatch.setattr(cmd_check, '_check_scenes',
                            lambda *a, **k: seen.append(gate.GATE_CHECK_METHOD)
                            or (_ for _ in ()).throw(SystemExit(7)))
        monkeypatch.setattr('storyforge.git.create_branch', lambda *a, **k: True)
        monkeypatch.setattr(gate, 'GATE_CHECK_METHOD', 'open')
        assert self._main(project_dir, monkeypatch, ['--questions', SCENE]) == 7
        assert seen == ['questions']

    @pytest.mark.parametrize('argv', [['--accept', SCENE, '--questions'],
                                      ['--blocking', '--questions', SCENE]])
    def test_refused_with(self, project_dir, monkeypatch, argv):
        assert self._main(project_dir, monkeypatch, argv) == 1

    def test_the_help_names_it(self):
        from storyforge import cmd_check
        assert cmd_check.parse_args(['--questions', 'x']).questions is True
        assert '--questions' in cmd_check.__doc__
