"""#749: a claim a character makes in speech about the past, not shown on the
page, is that character's account, not narration.

Extraction marks it (`claimed_by`); it is recorded as a `claim` row, never
binding, that supersedes and ends nothing, and the gate says so in a NOTE.
The open checker and the question layer are told that two tellings of
off-page history are not a contradiction when either is speech, while a
spoken account of an event the book shows, and a wrong name, kinship, age or
time in speech, still are (report A section 4: the Laomedon wall, O41/O42,
not raised; O13, Apollo healed Hector at the ford remembered as by the
ships, still raised)."""

import json
from unittest.mock import patch

from storyforge import checker, extract, gate, ledger, questions
from storyforge.extract import (CLAIM, COMMITMENT_PROBLEMS, COMMITMENT_RUBRIC,
                                build_commitments_prompt, commitment_rows,
                                parse_commitments_response)

from test_gate import (SCENE, HERE, _commitment, _gate, _pure_prose_scenes,  # noqa: F401
                       _text, _with_persistence)

SAID = 'It was here last quarter'


def _claim(**over):
    return _commitment(**dict({'type': 'world', 'subject': 'tarrens-hollow',
                               'statement': "Tarren's Hollow was on the map last quarter",
                               'quote': SAID, 'mutable': 'fixed',
                               'claimed_by': 'Dorren Hayle'}, **over))


def _row(rid, scene='', status='binding', **over):
    r = {c: '' for c in ledger.COLUMNS}
    r.update(id=rid, scene_id=scene, type='world', subject='', statement=rid, quote='q',
             origin='prose', status=status, mutable='fixed', introduced_by='draft')
    r.update(over)
    return r


class TestExtraction:
    def test_the_prompt_asks_for_the_speaker_of_a_claim(self):
        prompt = build_commitments_prompt('sc1', 'x', {})
        assert '- claimed_by:' in prompt and 'A claim supersedes and ends nothing' in prompt
        assert "A character's account in speech is that character's claim" in COMMITMENT_RUBRIC
        for never in ('narration', "a character's thoughts and memories", 'the story\'s present',
                      'a promise, threat or plan', 'a kinship', 'an elapsed time'):
            assert never in COMMITMENT_RUBRIC.split('These are never claims:')[1].split('\n')[0]
        assert 'claimed_by' in extract.COMMITMENTS_SCHEMA['properties']['commitments'][
            'items']['required']

    def test_parse_reads_the_speaker(self):
        got = parse_commitments_response(json.dumps({'commitments': [
            {'type': 'trait', 'subject': 'poseidon', 'statement': 'Poseidon built the wall',
             'quote': 'I built his wall', 'mutable': 'fixed', 'supersedes': '', 'ends': [],
             'claimed_by': ' poseidon '}]}), 'sc1')
        assert got[0]['claimed_by'] == 'poseidon'

    def _rows(self, found, rows=(), known=(), subjects=None):
        problems = {k: [] for k in COMMITMENT_PROBLEMS}
        out = commitment_rows(found, 'b', 'I built his wall. You minded his cattle.',
                              list(rows), list(known), [], subjects or {}, 'draft', problems,
                              own_writers=ledger.COMMITMENT_WRITERS, registry_is_plan=True,
                              reserved=set(), order={'a': 0, 'b': 1})
        return out, problems

    def _found(self, **over):
        return [dict({'type': 'trait', 'subject': 'laomedon',
                      'statement': "Poseidon alone built Laomedon's wall",
                      'quote': 'I built his wall', 'mutable': 'fixed', 'supersedes': '',
                      'ends': [], 'claimed_by': 'Poseidon'}, **over)]

    def test_a_claim_is_a_claim_row_naming_its_speaker(self):
        out, problems = self._rows(self._found(), subjects={'poseidon': 'poseidon-god'})
        assert out[0]['status'] == ledger.CLAIM == CLAIM
        assert out[0]['known_by'] == 'poseidon-god'
        assert problems[CLAIM] == [
            'b: poseidon-god: "Poseidon alone built Laomedon\'s wall"']

    def test_a_claim_supersedes_and_ends_nothing_and_says_so(self):
        """The Laomedon case: Poseidon's telling named the other telling's
        fact as replaced. A registry fact would have been a dispute, a
        commitment superseded."""
        told = _row('a--poseidon-and-apollo-built-the-wall', 'a')
        plan = _row('apollo-and-poseidon-built-it', introduced_by='elaborate')
        state = _row('a--apollo-tends-cattle', 'a', mutable='state')
        out, problems = self._rows(
            self._found(supersedes=told['id'], ends=[state['id']]), [told, plan, state],
            [told, plan, state])
        assert out[0]['supersedes'] == '' and state['resolves'] == ''
        assert not problems['disagrees'] and not problems['supersedes'] \
            and not problems['ends']
        assert problems[CLAIM] == [
            f'b: Poseidon: "Poseidon alone built Laomedon\'s wall" '
            f'(supersedes {told["id"]}, ends {state["id"]}: not applied)']
        out, problems = self._rows(self._found(supersedes=plan['id']), [plan], [plan])
        assert not problems['disagrees']

    def test_narration_is_still_a_binding_fact(self):
        out, problems = self._rows(self._found(claimed_by=''))
        assert out[0]['status'] == 'binding' and out[0]['known_by'] == ''
        assert problems[CLAIM] == []

    def test_a_claims_quote_is_checked(self):
        _, problems = self._rows(self._found(quote='Apollo built it'))
        assert problems[extract.MISQUOTE]

    def test_a_claim_is_never_offered_as_a_fact_in_force(self):
        rows = [_row('a--said', 'a', status=ledger.CLAIM),
                _row('a--narrated', 'a')]
        assert [r['id'] for r in extract.facts_in_force(rows, 'b', {'a': 0, 'b': 1})] \
            == ['a--narrated']

    def test_a_claim_is_never_asked_about(self):
        rows = [_row('a--said', 'a', status=ledger.CLAIM, subject='troy'),
                _row('a--narrated', 'a', subject='troy')]
        got = questions.facts_to_ask(rows, 'b', {'a': 0, 'b': 1}, {'troy'})
        assert [r['id'] for r in got.facts] == ['a--narrated']

    def test_the_ledger_takes_a_claim_row(self):
        assert ledger.CLAIM in ledger.STATUSES
        assert not ledger.validate_ledger([_row('a--said', 'a', status=ledger.CLAIM,
                                                known_by='poseidon')])


class TestGate:
    def _mine(self, project_dir):
        return [r for r in ledger.load(project_dir)
                if r['scene_id'] == SCENE and ledger.is_commitment(r)]

    def test_a_claim_is_recorded_as_a_claim_and_noted(self, project_dir, tmp_path):
        result = _gate(project_dir, tmp_path, [_commitment(), _claim()])
        assert result.passed and result.committed
        assert [r['statement'] for r in result.claims] == [
            "Tarren's Hollow was on the map last quarter"]
        assert [r['quote'] for r in result.proposed] == [HERE]
        by_status = {r['status']: r for r in self._mine(project_dir)}
        assert set(by_status) == {'binding', ledger.CLAIM}
        assert by_status[ledger.CLAIM]['known_by'] == 'dorren-hayle'
        lines = gate.report_lines(result)
        assert any(line.startswith(f'NOTE ({gate._REPORTED_LABEL[CLAIM]}): ')
                   and 'dorren-hayle' in line for line in lines), lines

    def test_a_claim_naming_a_plan_fact_raises_no_dispute(self, project_dir, tmp_path):
        """Narrated, the same supersedes is a dispute the checker must rule
        on; said, it is a claim and the checker is not asked."""
        seen = []

        def fake(path, body, **k):
            if 'tools' in body:
                seen.append(json.dumps(body['messages'][0]['content']))
                return _text({'findings': [], 'kept': [], 'cleared': []})
            return _text({'commitments': [_claim(supersedes='village-vanished')]})
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)):
            result = gate.gate_scene(project_dir, SCENE, command='draft',
                                     log_dir=str(tmp_path / 'logs'), extract_model='m',
                                     check_model='m')
        assert result.passed and not result.unruled
        assert not result.problems['disagrees']
        assert seen and not any('may change' in s for s in seen)
        row = next(r for r in ledger.load(project_dir) if r['id'] == 'village-vanished')
        assert row['status'] == 'binding'

    def test_a_redraft_replaces_the_claims_and_keeps_an_unchanged_claims_id(
            self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_claim()])
        first = [r['id'] for r in self._mine(project_dir)]
        _gate(project_dir, tmp_path, [_claim()], command='redraft')
        assert [r['id'] for r in self._mine(project_dir)] == first
        _gate(project_dir, tmp_path, [_commitment()], command='redraft')
        assert [r['status'] for r in self._mine(project_dir)] == ['binding']

    def test_a_fact_that_becomes_a_claim_is_a_change(self, project_dir, tmp_path):
        """No longer in force: what leaned on it is re-checked."""
        _gate(project_dir, tmp_path, [_claim(claimed_by='')])
        result = _gate(project_dir, tmp_path, [_claim()], command='redraft')
        assert len(result.changed) == 1


class TestCheckers:
    def test_the_open_checker_is_told(self):
        book = checker.Book({'s': 0}, {'s': {}}, {'s': 'x'}, [])
        _, rest = checker.prompt_parts(book, 's', '')
        rule = rest.split('- Not a contradiction either: ')[1].split('\n')[0]
        assert 'two tellings of something no scene of the book shows happening' in rule
        assert "a character's words in speech" in rule
        assert 'Still report a character\'s account of an event a scene of this book shows' \
            in rule
        assert 'a name, kinship, age, date or elapsed time said in speech' in rule

    def test_the_question_layer_is_told(self):
        assert ('Answer `no` too when the fact is about something the book never shows '
                'happening') in questions.PROMPT
        assert ('A wrong name, kinship, age, date or elapsed time in speech is still a '
                'contradiction, and so is a wrong account of an event a scene of the book '
                'shows happening.') in questions.PROMPT
