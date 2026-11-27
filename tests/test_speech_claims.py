"""#749: a claim a character makes in speech about the past, not shown on the
page, is that character's account, not narration.

Extraction marks it (`claimed_by`); code keeps it binding unless it can be a
claim (`extract.claim_refusal`: never a time, a state, a name or age,
knowledge, a quote outside quotation marks, or a speaker who isn't one
character). A claim is recorded as a `claim` row, never binding, that ends
nothing; its `supersedes` is a dispute (a registry fact) or a NOTE naming the
fact (a commitment), never applied; the gate lists every claim. The open
checker and the question layer are told that two tellings of off-page
history are not a contradiction when either is speech, while a spoken
account of an event the book shows, and a wrong name, kinship, age or time in
speech, still are (report A section 4: the Laomedon wall, O41/O42, not
raised; O13, Apollo healed Hector at the ford remembered as by the ships,
still raised)."""

import json
import os
from unittest.mock import patch

import pytest

from storyforge import audit, checker, extract, gate, ledger, questions
from storyforge.extract import (CLAIM_DEPARTS, CLAIM_KEPT, COMMITMENT_PROBLEMS,
                                COMMITMENT_RUBRIC, SPEECH_CLAIM, Speakers,
                                build_commitments_prompt, commitment_rows, in_speech,
                                parse_commitments_response)

from test_gate import (SCENE, HERE, _commitment, _gate, _pure_prose_scenes,  # noqa: F401
                       _text, _with_persistence)
from test_gate_source import adaptation  # noqa: F401

SAID = 'It was here last quarter'
WALL = 'Poseidon said, "I built his wall. You minded his cattle." The sea was loud.'
SPEAKERS = Speakers.from_rows([
    {'id': 'poseidon', 'name': 'Poseidon', 'aliases': 'Earth-shaker'},
    {'id': 'pisander-1', 'name': 'Pisander', 'aliases': ''},
    {'id': 'pisander-2', 'name': 'Pisander', 'aliases': ''}])


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
        assert '- claimed_by:' in prompt
        assert "A character's account in speech is that character's claim" in COMMITMENT_RUBRIC
        never = COMMITMENT_RUBRIC.split('These are never claims:')[1].split('\n')[0]
        for words in ('narration', "a character's thoughts and memories",
                      'the story\'s present and how things are now',
                      'a stated rule of the world',
                      'who learns or knows what in this scene',   # CR-5
                      'a promise, threat or plan', 'a kinship', 'an elapsed time'):
            assert words in never
        assert 'claimed_by' in extract.COMMITMENTS_SCHEMA['properties']['commitments'][
            'items']['required']

    def test_parse_reads_the_speaker(self):
        got = parse_commitments_response(json.dumps({'commitments': [
            {'type': 'trait', 'subject': 'poseidon', 'statement': 'Poseidon built the wall',
             'quote': 'I built his wall', 'mutable': 'fixed', 'supersedes': '', 'ends': [],
             'claimed_by': ' poseidon '}]}), 'sc1')
        assert got[0]['claimed_by'] == 'poseidon'

    def _rows(self, found, rows=(), known=(), text=WALL, registry_is_plan=True,
              speakers=SPEAKERS):
        problems = {k: [] for k in COMMITMENT_PROBLEMS}
        out = commitment_rows(found, 'b', text, list(rows), list(known), [],
                              {'poseidon': 'poseidon-place'}, 'draft', problems,
                              own_writers=ledger.COMMITMENT_WRITERS,
                              registry_is_plan=registry_is_plan,
                              reserved=set(), order={'a': 0, 'b': 1}, speakers=speakers)
        return out, problems

    def _found(self, **over):
        return [dict({'type': 'trait', 'subject': 'laomedon',
                      'statement': "Poseidon alone built Laomedon's wall",
                      'quote': 'I built his wall', 'mutable': 'fixed', 'supersedes': '',
                      'ends': [], 'claimed_by': 'Earth-shaker'}, **over)]

    def test_a_claim_is_a_claim_row_naming_its_character(self):
        """TD-1: the speaker is bound through characters.csv alone; a place
        of the same name in `subjects` is never it."""
        out, problems = self._rows(self._found())
        assert out[0]['status'] == ledger.CLAIM
        assert ledger.speaker(out[0]) == out[0]['known_by'] == 'poseidon'
        assert problems[SPEECH_CLAIM] == [
            'b: poseidon: "Poseidon alone built Laomedon\'s wall"']
        assert problems[CLAIM_KEPT] == []

    @pytest.mark.parametrize('over, why', [
        ({'type': 'timeline', 'statement': 'Ves wrote the journal'}, 'it is a timeline fact'),
        ({'type': 'knowledge'}, 'it is a knowledge fact'),
        ({'type': 'relationship'}, 'it is a relationship fact'),
        ({'type': 'promise'}, 'it is a promise fact'),
        ({'mutable': 'state'}, 'it is a state, which can change'),
        ({'statement': 'The rescue got them out two hours ago'},
         'it states an elapsed time, an age or a name'),
        ({'statement': 'The wall-builder was named Poseidon'},
         'it states an elapsed time, an age or a name'),
        ({'quote': 'The sea was loud'}, 'its quote is not inside quotation marks'),
        ({'claimed_by': 'Pisander'},
         'its speaker is a name several characters share (pisander-1, pisander-2)'),
        ({'claimed_by': 'crew-chief-unnamed'},
         'its speaker is not a character in characters.csv'),
        ({'claimed_by': 'Poseidon; Apollo'}, 'it names more than one speaker'),
    ])
    def test_code_keeps_what_cannot_be_a_claim_binding(self, over, why):
        """SF-2, CR-3: the E3 recordings marked elapsed times ("two hours
        ago", "sixteen years ago"), states and knowledge as claims, and a
        claim escapes every check."""
        out, problems = self._rows(self._found(**over))
        assert out[0]['status'] == 'binding' and out[0]['known_by'] == ''
        assert problems[SPEECH_CLAIM] == []
        assert len(problems[CLAIM_KEPT]) == 1 and f'but {why}; kept binding' \
            in problems[CLAIM_KEPT][0]

    def test_with_no_characters_read_nothing_is_a_claim(self):
        out, problems = self._rows(self._found(), speakers=None)
        assert out[0]['status'] == 'binding'
        assert 'no characters registry was read' in problems[CLAIM_KEPT][0]

    def test_a_kept_claims_links_are_applied_as_narrations(self):
        told = _row('a--the-wall', 'a')
        out, _ = self._rows(self._found(mutable='state', supersedes=told['id']), [told],
                            [told])
        assert out[0]['supersedes'] == told['id']

    def test_a_pipe_in_the_speaker_or_statement_never_breaks_the_report(self):
        """T-3, T-4."""
        _, problems = self._rows(self._found(claimed_by='Earth|shaker'))
        assert '|' not in problems[CLAIM_KEPT][0]
        _, problems = self._rows(self._found(statement='Poseidon | Apollo built it'))
        assert '|' not in problems[SPEECH_CLAIM][0]

    def test_a_claim_naming_a_registry_fact_is_a_dispute(self):
        """SF-3: as narration's would be; the link is not applied."""
        plan = _row('apollo-and-poseidon-built-it', introduced_by='elaborate')
        out, problems = self._rows(self._found(supersedes=plan['id']), [plan], [plan])
        assert out[0]['supersedes'] == ''
        assert problems['disagrees'] == [f'b: {plan["id"]} (prose: {out[0]["id"]})']
        assert 'a dispute for the check' in problems[SPEECH_CLAIM][0]

    def test_a_claim_naming_a_commitment_names_it_and_ends_nothing(self):
        """The Laomedon case: Poseidon's telling named the other telling's
        fact as replaced; it stands, and the report names it."""
        told = _row('a--poseidon-and-apollo-built-the-wall', 'a',
                    statement='Poseidon and Apollo built the wall together')
        state = _row('a--apollo-tends-cattle', 'a', mutable='state')
        out, problems = self._rows(
            self._found(supersedes=told['id'], ends=[state['id']]), [told, state],
            [told, state])
        assert out[0]['supersedes'] == '' and state['resolves'] == ''
        assert not problems['disagrees'] and not problems['supersedes'] \
            and not problems['ends']
        assert problems[CLAIM_DEPARTS] == [
            f'b: {out[0]["id"]} tells otherwise than {told["id"]} '
            f'("Poseidon and Apollo built the wall together")']
        assert problems[SPEECH_CLAIM] == [
            f'b: poseidon: "Poseidon alone built Laomedon\'s wall" '
            f'(ends {state["id"]}, supersedes {told["id"]}: not applied)']

    def test_phase_4_names_a_commitment_and_does_not_dispute(self):
        told = _row('a--the-wall', 'a')
        plan = _row('the-plan-wall', introduced_by='elaborate')
        _, problems = self._rows(self._found(supersedes=plan['id']), [plan], [plan],
                                 registry_is_plan=False)
        assert not problems['disagrees'] and problems[CLAIM_DEPARTS]
        _, problems = self._rows(self._found(supersedes=told['id']), [told], [told],
                                 registry_is_plan=False)
        assert problems[CLAIM_DEPARTS]

    def test_narration_is_still_a_binding_fact(self):
        out, problems = self._rows(self._found(claimed_by=''))
        assert out[0]['status'] == 'binding' and out[0]['known_by'] == ''
        assert problems[SPEECH_CLAIM] == [] and problems[CLAIM_KEPT] == []

    def test_a_claims_quote_is_checked(self):
        _, problems = self._rows(self._found(quote='"I built his wall. You minded'),
                                 text='Poseidon said, "I built his wall. You minded nothing."')
        assert not problems[extract.MISQUOTE]
        _, problems = self._rows(self._found(quote='Apollo built it'),
                                 text='"Apollo built it" ... no')
        assert not problems[extract.MISQUOTE]
        _, problems = self._rows(self._found(quote='"Apollo built it"'))
        assert problems[extract.MISQUOTE]

    def test_in_speech(self):
        assert in_speech(WALL, 'I built his wall ... You minded his cattle')
        assert not in_speech(WALL, 'Poseidon said')
        assert not in_speech(WALL, 'I built his wall ... The sea was loud')
        assert in_speech('“I built it,” he said.', 'I built it')
        assert not in_speech('No speech here at all.', 'speech')

    def test_a_claim_is_never_offered_as_a_fact_in_force(self):
        rows = [_row('a--said', 'a', status=ledger.CLAIM), _row('a--narrated', 'a')]
        assert [r['id'] for r in extract.facts_in_force(rows, 'b', {'a': 0, 'b': 1})] \
            == ['a--narrated']

    def test_a_claim_is_never_asked_about(self):
        rows = [_row('a--said', 'a', status=ledger.CLAIM, subject='troy'),
                _row('a--narrated', 'a', subject='troy')]
        got = questions.facts_to_ask(rows, 'b', {'a': 0, 'b': 1}, {'troy'})
        assert [r['id'] for r in got.facts] == ['a--narrated']


class TestLedger:
    def test_the_ledger_takes_a_claim_row(self):
        assert ledger.CLAIM in ledger.STATUSES
        assert not ledger.validate_ledger([_row('a--said', 'a', status=ledger.CLAIM,
                                                known_by='poseidon')])

    def test_validate_holds_a_claims_shape(self):
        """TD-3."""
        bad = [_row('r1', status=ledger.CLAIM, known_by='p', introduced_by='bibles'),
               _row('r2', 'a', status=ledger.CLAIM),
               _row('r3', 'a', status=ledger.CLAIM, known_by='p;q'),
               _row('r4', 'a', status=ledger.CLAIM, known_by='p', supersedes='r1'),
               _row('r5', 'a', status=ledger.CLAIM, known_by='p', resolves='a')]
        problems = ' '.join(ledger.validate_ledger(bad))
        assert 'r1): a claim, but not a commitment' in problems
        assert 'r2): a claim names 0 speakers' in problems
        assert 'r3): a claim names 2 speakers' in problems
        assert "r4): a claim with supersedes 'r1'" in problems
        assert "r5): a claim with resolves 'a'" in problems

    def test_speaker_is_only_a_claims(self):
        assert ledger.speaker(_row('k', known_by='p')) == ''
        assert ledger.speaker(_row('c', status=ledger.CLAIM, known_by='p')) == 'p'

    def test_audit_never_lists_a_claim_as_known_by_its_speaker(self, project_dir):
        """TD-2."""
        rows = ledger.load(project_dir) + [
            _row('act1-sc02--said', SCENE, status=ledger.CLAIM, known_by='dorren-hayle'),
            _row('act1-sc02--known', SCENE, type='knowledge', known_by='dorren-hayle')]
        got = audit.select(rows, project_dir,
                           audit.Scope(character='dorren-hayle', include_reviewed=True),
                           ledger.scene_order(project_dir))
        ids = {r['id'] for r in got.facts}
        assert 'act1-sc02--known' in ids and 'act1-sc02--said' not in ids


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
        label = f'NOTE ({gate._REPORTED_LABEL[SPEECH_CLAIM]}): '
        assert any(line.startswith(label) and 'dorren-hayle' in line
                   for line in gate.report_lines(result))
        # SF-1: a passing re-check's report lists it too
        assert any(line.startswith(label) for line in gate.applied_lines(result))

    def test_every_claim_is_listed(self, project_dir, tmp_path):
        """SF-5: never cut at 20."""
        result = _gate(project_dir, tmp_path, [_commitment()])
        result.problems[SPEECH_CLAIM] = [f'{SCENE}: p: "claim {i}"' for i in range(25)]
        line = next(line for line in gate.report_lines(result)
                    if line.startswith(f'NOTE ({gate._REPORTED_LABEL[SPEECH_CLAIM]})'))
        assert 'claim 24' in line and not line.endswith('...')

    def test_a_kept_claim_is_noted_and_binding(self, project_dir, tmp_path):
        result = _gate(project_dir, tmp_path, [_claim(type='timeline')])
        assert [r['status'] for r in self._mine(project_dir)] == ['binding']
        assert any(line.startswith(f'NOTE ({gate._REPORTED_LABEL[CLAIM_KEPT]})')
                   for line in gate.report_lines(result))

    def test_a_claim_naming_a_plan_fact_is_a_dispute_the_check_rules_on(
            self, project_dir, tmp_path):
        """SF-3: cleared, the plan's fact stands and the claim is recorded."""
        seen = []

        def fake(path, body, **k):
            if 'tools' in body:
                prompt = json.dumps(body['messages'][0]['content'])
                seen.append(prompt)
                return _text({'findings': [], 'kept': [], 'cleared': ['village-vanished']})
            return _text({'commitments': [_claim(supersedes='village-vanished')]})
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)):
            result = gate.gate_scene(project_dir, SCENE, command='draft',
                                     log_dir=str(tmp_path / 'logs'), extract_model='m',
                                     check_model='m')
        assert result.problems['disagrees']
        assert any('may change' in s and 'village-vanished' in s and SAID in s for s in seen)
        assert result.passed and result.committed
        row = next(r for r in ledger.load(project_dir) if r['id'] == 'village-vanished')
        assert row['status'] == 'binding'
        assert [r['status'] for r in self._mine(project_dir)] == [ledger.CLAIM]

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

    def test_a_kept_fact_of_unchanged_prose_read_as_a_claim_is_not_kept(
            self, project_dir, tmp_path):
        """CR-1: on an already-gated book the binding fact stayed (its
        paragraph unchanged) beside the new claim row, and nothing was
        re-checked. Now it goes, counted as changed, and one row is left."""
        import subprocess
        subprocess.run(['git', 'init', '-q', project_dir], check=True)
        _gate(project_dir, tmp_path, [_commitment(), _claim(claimed_by='')])
        old = next(r for r in self._mine(project_dir) if r['quote'] == SAID)
        path = os.path.join(project_dir, 'scenes', f'{SCENE}.md')
        with open(path, encoding='utf-8') as f:
            text = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text.replace('She returned to the new map.', 'She went back to the new map.'))
        result = _gate(project_dir, tmp_path, [_commitment(), _claim()], command='redraft')
        assert result.committed
        assert old["id"] not in result.steady and old["id"] in result.changed
        assert result.unkept_as_claims == [(old['id'], old['statement'])]
        mine = [r for r in self._mine(project_dir) if r['quote'] == SAID]
        assert [r['status'] for r in mine] == [ledger.CLAIM]
        assert any('now read as a claim in speech' in line
                   for line in gate.report_lines(result))
        again = _gate(project_dir, tmp_path, [_commitment(), _claim()], command='recheck')
        assert [r['status'] for r in self._mine(project_dir) if r['quote'] == SAID] \
            == [ledger.CLAIM]
        assert again.committed


class TestSource:
    def test_a_claim_the_source_tells_otherwise_is_listed_never_blocking(
            self, project_dir, tmp_path, adaptation):
        """CR-2: conflicting accounts in speech are kept; the departure goes
        to the author list and a note."""
        from test_gate_source import _run
        sent = []
        result = _run(project_dir, tmp_path, [_commitment(), _claim()], sent=sent, source={
            'facts': [{'n': 1, 'verdict': 'agrees', 'why': 'w'},
                      {'n': 2, 'verdict': 'contradicts', 'why': 'the source: never mapped'}],
            'contradictions': [], 'findings': []})
        assert SAID in sent[0]
        assert result.committed and result.source_departs == []
        assert result.claim_departs == [("Tarren's Hollow was on the map last quarter",
                                         'the source: never mapped')]
        notes = gate.source_notes(project_dir)
        assert len(notes) == 1 and 'a claim in speech the source tells otherwise' \
            in notes[0]['finding']
        assert any(line.startswith('NOTE (a claim in speech tells otherwise than the source')
                   for line in gate.report_lines(result))


class TestPhase4:
    def test_phase_4_records_and_lists_its_claims(self, project_dir, monkeypatch, capsys):
        """T-2."""
        from test_extract_commitments import TestPhase4 as Phase4, _reply
        Phase4._run(Phase4(), project_dir, monkeypatch, {SCENE: _reply(
            {'statement': "Tarren's Hollow was on the map last quarter", 'type': 'world',
             'subject': 'tarrens-hollow', 'quote': SAID, 'mutable': 'fixed',
             'claimed_by': 'Dorren', 'ends': []},
            {'statement': 'The census was taken two years ago', 'type': 'world',
             'quote': SAID, 'mutable': 'fixed', 'claimed_by': 'Dorren', 'ends': []})},
            only=[SCENE])
        mine = [r for r in ledger.load(project_dir)
                if r['introduced_by'] == ledger.COMMITMENTS_PASS]
        assert [(r['status'], r['known_by']) for r in mine] == [
            (ledger.CLAIM, 'dorren-hayle'), ('binding', '')]
        out = capsys.readouterr().out
        assert "NOTE: 1 character account(s) in speech" in out and 'dorren-hayle' in out
        assert 'NOTE: 1 account(s) marked as a claim in speech that are kept binding' in out


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
        """T-1, CR-6: only a fact from no scene, and only speech."""
        sentence = questions.PROMPT.split('Answer `no` too when ')[1].split('. ')[0]
        assert sentence.startswith('the fact is established before the story or in the '
                                   'ledger (not in a scene)')
        assert 'something the book never shows happening' in sentence
        assert sentence.endswith("are a character's speech")
        assert ('A wrong name, kinship, age, date or elapsed time in speech is still a '
                'contradiction, and so is a wrong account of an event a scene of the book '
                'shows happening.') in questions.PROMPT
