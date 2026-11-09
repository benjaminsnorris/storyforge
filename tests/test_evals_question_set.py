"""The question set (#649): the fixture is sound against the Carol book, its
validation and scoring, and the suite end to end with the API faked at
`api._live_request` (so the cassette path is the real one)."""

import copy
import json
import os
import re
import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import e2  # noqa: E402
import harness  # noqa: E402

SUITES = PLUGIN_DIR / 'evals' / 'suites'


def _suite():
    return next(s for s in harness.discover(str(SUITES)) if s.name == 'question-set')


def _module():
    return _suite().run.__globals__


BOOK = os.path.join(e2.fixture_dir('carol'), 'book')
INJECTIONS = {c['id']: c for c in e2.load_cases('carol')}


class TestFixture:
    def test_the_set_is_sound(self):
        m = _module()
        assert m['validate'](m['load_cases'](), BOOK, INJECTIONS) == []

    def test_its_shape(self):
        data = _module()['load_cases']()
        kinds = [v['kind'] for v in data['variants']]
        assert (kinds.count('error'), kinds.count('control'), kinds.count('benign')) == (17, 13, 8)
        assert {f['type'] for f in data['facts'].values()} == {
            'trait', 'relationship', 'physical', 'world'}

    @pytest.mark.parametrize('break_it,problem', [
        (lambda d: d['facts']['ebenezer'].update(quote='Nathaniel'), 'its quote is not in'),
        (lambda d: d['scenes']['marley-ghost-arrives'].append('nobody'), 'unknown fact nobody'),
        (lambda d: d['scenes']['scrooge-dismisses-clerk'].__init__(['bob-coat'])
         if 'scrooge-dismisses-clerk' in d['scenes']
         else d['scenes'].update({'scrooge-dismisses-clerk': ['bob-coat']}), 'which it establishes'),
        (lambda d: d['variants'][0].update(yes=['camden']), 'is not asked in'),
        (lambda d: d['variants'][0].update(injection='e2-carol-b01'), 'does not apply once'),
        (lambda d: d['variants'][-1].update(yes=['partner']), 'a benign variant'),
        (lambda d: d['facts']['ebenezer'].update(type='knowledge'), 'not one the layer asks'),
    ])
    def test_validation_names_the_problem(self, break_it, problem):
        m = _module()
        data = copy.deepcopy(m['load_cases']())
        break_it(data)
        assert any(problem in p for p in m['validate'](data, BOOK, INJECTIONS))


class TestScore:
    DATA = {'facts': {'a': {'type': 'trait'}, 'b': {'type': 'world'}},
            'scenes': {'s': ['a', 'b']},
            'variants': [{'id': 'v1', 'kind': 'error', 'scene': 's', 'injection': 'i1',
                          'yes': ['a']},
                         {'id': 'v2', 'kind': 'error', 'scene': 's', 'injection': 'i2',
                          'yes': ['b']},
                         {'id': 'c', 'kind': 'control', 'scene': 's', 'injection': None,
                          'yes': []}]}
    INJ = {'i1': {'contradicted': [{'quote': 'the red door'}]},
           'i2': {'contradicted': [{'quote': 'a blue sky'}]}}

    def test_caught_at_the_place_anywhere_and_false_alarms(self):
        outcomes = {'v1': {'findings': {'a': 'past the red door'}, 'split': 1, 'misquoted': 0},
                    'v2': {'findings': {'b': 'somewhere else', 'a': 'x'}, 'split': 0,
                           'misquoted': 2},
                    'c': {'findings': {'b': 'y'}, 'split': 0, 'misquoted': 0}}
        got = _module()['score'](self.DATA, outcomes, self.INJ)
        m = got['metrics']
        assert (m['recall'], m['recall_any'], m['false_alarms']) == (0.5, 1.0, 2)
        assert (m['false_alarms_control'], m['false_alarms_other_facts']) == (1, 1)
        assert (m['split'], m['misquoted'], m['questions'], m['yes_questions']) == (1, 2, 6, 2)
        assert got['by_code'] == {'TRT': {'cases': 1, 'recall': 1.0},
                                  'WLD': {'cases': 1, 'recall': 0.0}}
        assert got['missed'] == ['v2'] and got['alarms'] == ['v2:a', 'c:b']


def _reply(answers):
    return {'id': 'msg', 'type': 'message', 'role': 'assistant', 'model': 'claude-haiku-5-5',
            'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': json.dumps({'answers': answers})}],
            'usage': {'input_tokens': 1000, 'output_tokens': 100}}


def _fake_api(calls):
    """Yes to the first-name question when the gravestone says Nathaniel, no
    to everything else."""
    def live(path, body, method, timeout):
        prompt = body['messages'][0]['content']
        calls.append(prompt)
        out = []
        for m in re.finditer(r'^(\d+)\. Established [^\n]*"(.*)"', prompt, re.M):
            n, statement = int(m.group(1)), m.group(2)
            if 'Ebenezer' in statement and 'NATHANIEL SCROOGE' in prompt:
                out.append({'n': n, 'answer': 'yes', 'quote': 'his own name, NATHANIEL SCROOGE',
                            'why': 'The stone names him Nathaniel.'})
            else:
                out.append({'n': n, 'answer': 'no', 'quote': '', 'why': 'Nothing rules it out.'})
        return _reply(out)
    return live


class TestSuite:
    def test_records_then_replays_free(self, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.delenv('STORYFORGE_CASSETTE', raising=False)
        calls = []
        monkeypatch.setattr(api, '_live_request', _fake_api(calls))
        suite = _suite()
        result = harness.run_suite(suite, 'record', str(tmp_path / 'c'))
        assert result['error'] is None, result['error']
        assert len(calls) == 76                      # 38 variants, two askings each
        m = result['metrics']
        assert (m['variants'], m['questions'], m['yes_questions']) == (38, 96, 17)
        assert m['recall'] == m['recall_any'] == round(1 / 17, 4) and m['false_alarms'] == 0
        assert result['by_code']['TRT'] == {'cases': 4, 'recall': 0.25}
        assert [g['name'] for g in result['gates']] == list(_module()['FLOORS'])

        monkeypatch.setattr(api, '_live_request', lambda *a: pytest.fail('went live'))
        replayed = harness.run_suite(suite, 'replay', str(tmp_path / 'c'))
        assert replayed['metrics'] == result['metrics']
        assert replayed['cost']['usd_spent'] == 0 and replayed['cost']['replayed_calls'] == 76

    def test_no_floor_fails_and_says_what_to_write(self, monkeypatch):
        gates, notes = _module()['floor_gates']({'recall': 0.5}, {'recall': None})
        assert not gates[0].passed and "set FLOORS['recall'] = 0.5" in notes[0]
        gates, notes = _module()['floor_gates']({'recall': 0.5}, {'recall': 0.5})
        assert gates[0].passed and notes == []
