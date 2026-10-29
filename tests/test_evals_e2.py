"""E2 detection benchmark: the Carol injection fixtures, the scorer, and the
suite's plumbing with a stand-in detector (no API calls)."""

import json
import os
import sys
from collections import Counter

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import e2  # noqa: E402
import harness  # noqa: E402

BOOK_DIR = os.path.join(e2.fixture_dir('carol'), 'book')


def _case(cid='x-001', code='TIM', scene='b', find='old', replace='new text', quote='new',
          established=(('a', 'fact'),)):
    return {'id': cid, 'code': code, 'summary': '',
            'established': [{'scene': s, 'quote': q} for s, q in established],
            'contradicted': [{'scene': scene, 'quote': quote}],
            'injection': {'scene': scene, 'find': find, 'replace': replace}}


class TestCarolFixtures:
    def test_cases_are_sound_against_the_text(self):
        assert e2.validate_cases(e2.load_cases('carol'), BOOK_DIR) == []

    def test_every_gated_code_has_cases(self):
        counts = Counter(c['code'] for c in e2.load_cases('carol'))
        for code in e2.GATED_CODES:
            assert counts[code] >= 5, code

    def test_the_ledger_is_present(self):
        for name in ('scenes.csv', 'knowledge.csv', 'physical-states.csv'):
            assert os.path.isfile(os.path.join(BOOK_DIR, 'reference', name))
        assert os.path.isfile(os.path.join(BOOK_DIR, 'working', 'timeline-cues.csv'))
        assert len(e2.reading_order(BOOK_DIR)) == 40


class TestValidate:
    def _book(self, tmp_path, scenes):
        os.makedirs(tmp_path / 'scenes')
        for sid, text in scenes.items():
            (tmp_path / 'scenes' / f'{sid}.md').write_text(text)
        return str(tmp_path)

    def test_a_find_that_is_not_unique_is_a_problem(self, tmp_path):
        book = self._book(tmp_path, {'a': 'fact', 'b': 'old and old'})
        assert e2.validate_cases([_case()], book) == ['x-001: "find" occurs 2 times in b']

    def test_an_established_quote_must_be_verbatim(self, tmp_path):
        book = self._book(tmp_path, {'a': 'a different fact', 'b': 'old'})
        found = e2.validate_cases([_case(established=(('a', 'the fact'),))], book)
        assert found == ['x-001: established quote not found in a']

    def test_the_contradicted_quote_must_be_injected(self, tmp_path):
        book = self._book(tmp_path, {'a': 'fact', 'b': 'old'})
        found = e2.validate_cases([_case(quote='elsewhere')], book)
        assert found == ['x-001: contradicted quote is not in the injected text']


def test_copy_book_applies_one_edit(tmp_path):
    src = tmp_path / 'src'
    os.makedirs(src / 'scenes')
    (src / 'scenes' / 'a.md').write_text('fact')
    (src / 'scenes' / 'b.md').write_text('the old door')
    dest = e2.copy_book(str(src), str(tmp_path / 'dest'), _case())
    assert open(os.path.join(dest, 'scenes', 'b.md')).read() == 'the new text door'
    assert open(os.path.join(dest, 'scenes', 'a.md')).read() == 'fact'
    assert open(src / 'scenes' / 'b.md').read() == 'the old door'


class TestScore:
    ORDER = ['a', 'b', 'c', 'd']

    def test_a_flag_on_the_case_scenes_is_a_detection(self):
        cases = [_case('x-001', 'TIM'), _case('x-002', 'KNO', scene='c')]
        flags = {'x-001': [{'scene_id': 'b', 'code': 'TIM', 'check': 'gap_mismatch'}],
                 'x-002': [{'scene_id': 'd', 'code': 'TIM', 'check': 'gap_mismatch'}]}
        result = e2.score(cases, flags, {}, self.ORDER)
        # The scene after the edited one counts; the code needn't match
        assert result['detected'] == {'x-001': True, 'x-002': True}
        assert result['by_code']['TIM']['recall_code_match'] == 1.0
        assert result['by_code']['KNO'] == {'cases': 1, 'recall': 1.0, 'recall_code_match': 0.0}
        assert result['metrics']['precision'] == 1.0

    def test_a_flag_the_control_also_raised_is_not_a_detection(self):
        flag = {'scene_id': 'b', 'code': 'TIM', 'check': 'date_mismatch', 'message': 'x'}
        result = e2.score([_case()], {'x-001': [dict(flag, message='y')]}, {'b': [flag]}, self.ORDER)
        assert result['detected'] == {'x-001': False}
        # The control's own flag is a false positive, counted once
        assert result['metrics']['flags_false'] == 1
        assert result['metrics']['precision'] == 0.0

    def test_a_flag_elsewhere_is_a_false_positive(self):
        flags = {'x-001': [{'scene_id': 'd', 'code': 'TIM', 'check': 'gap_mismatch'},
                           {'scene_id': 'b', 'code': 'TIM', 'check': 'gap_mismatch'}]}
        result = e2.score([_case()], flags, {}, self.ORDER)
        assert result['metrics']['flags_true'] == 1
        assert result['metrics']['flags_false'] == 1
        assert result['metrics']['precision'] == 0.5

    def test_no_flags_scores_zero_not_an_error(self):
        result = e2.score([_case()], {'x-001': []}, {'b': []}, self.ORDER)
        assert result['metrics']['recall'] == 0.0
        assert result['metrics']['precision'] == 0.0
        assert 'precision' not in result['by_code']['TIM']


def test_suite_runs_with_a_stand_in_detector(tmp_path, monkeypatch):
    """The suite's plumbing, end to end, with a detector that flags exactly
    the edited scene when its text changed."""
    clean = {}

    def detector(project_dir, scenes, log_dir):
        flags = []
        for scene in scenes:
            text = open(os.path.join(project_dir, 'scenes', f'{scene}.md')).read()
            clean.setdefault(scene, text)
            if text != clean[scene]:
                flags.append({'scene_id': scene, 'code': 'TIM', 'check': 'stand_in', 'message': ''})
        return flags

    monkeypatch.setitem(e2.DETECTORS, 'drift-check', detector)
    suite = next(s for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites')) if s.name == 'e2-carol')
    ctx = harness.SuiteContext(name='e2-carol', mode='replay', cassette_dir=str(tmp_path / 'c'),
                               work_dir=str(tmp_path / 'w'))
    out = suite.run(ctx)
    assert out.metrics['recall'] == 1.0
    assert out.metrics['precision'] == 1.0
    assert out.by_code['TIM']['recall_code_match'] == 1.0
    assert out.by_code['KNO']['recall_code_match'] == 0.0
    assert {g.name for g in out.gates} == {'recall_PHY', 'recall_TIM', 'recall_KNO',
                                           'recall_REL', 'recall_TRT', 'precision'}
    assert all(g.passed for g in out.gates)
