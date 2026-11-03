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

    def test_there_are_benign_edits(self):
        assert sum(1 for c in e2.load_cases('carol') if c.get('benign')) >= 5

    def test_the_ledger_is_present(self):
        # The frozen book predates the ledger; copy_book migrates each copy
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

    def test_an_edit_may_not_overwrite_its_own_established_quote(self, tmp_path):
        book = self._book(tmp_path, {'a': 'x', 'b': 'the old fact'})
        found = e2.validate_cases([_case(established=(('b', 'old fact'),))], book)
        assert found == ['x-001: the edit overwrites its own established quote in b']

    def test_a_benign_case_has_no_code_or_spans(self, tmp_path):
        book = self._book(tmp_path, {'b': 'old'})
        good = dict(_case(code=None), benign=True, established=[], contradicted=[])
        assert e2.validate_cases([good], book) == []
        assert e2.validate_cases([dict(good, code='TIM')], book) == [
            'x-001: a benign case has no code and no spans']

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


def _flag(scene, code='TIM', check='gap_mismatch', message=''):
    return {'scene_id': scene, 'code': code, 'check': check, 'message': message}


class TestScore:
    ORDER = ['a', 'b', 'c', 'd']

    def test_a_flag_on_the_case_scenes_with_its_code_is_a_detection(self):
        cases = [_case('x-001', 'TIM'), _case('x-002', 'KNO', scene='c')]
        flags = {'x-001': [_flag('b')], 'x-002': [_flag('d', message='other')]}
        result = e2.score(cases, flags, {}, self.ORDER)
        # The scene after the edited one counts for location
        assert result['by_code']['TIM'] == {'cases': 1, 'recall': 1.0, 'recall_code_match': 1.0,
                                            'precision': 0.5}
        # A TIM flag on a KNO case is located but not a detection, and is false
        assert result['by_code']['KNO'] == {'cases': 1, 'recall': 1.0, 'recall_code_match': 0.0}
        assert result['detected'] == {'x-001': True, 'x-002': False}
        assert result['metrics']['flags_true'] == 1
        assert result['metrics']['flags_false'] == 1

    def test_a_flag_the_control_also_raised_is_not_a_detection(self):
        flag = _flag('b', check='date_mismatch', message='x')
        result = e2.score([_case()], {'x-001': [dict(flag, message='y')]}, {'b': [flag]}, self.ORDER)
        assert result['detected'] == {'x-001': False}
        # The control's own flag is a false positive
        assert result['metrics']['flags_false'] == 1
        assert result['metrics']['precision'] == 0.0

    def test_a_control_flag_on_the_next_scene_is_still_subtracted(self):
        flag = _flag('c', check='gap_mismatch')
        result = e2.score([_case()], {'x-001': [flag]}, {'b': [flag]}, self.ORDER)
        assert result['detected'] == {'x-001': False}

    def test_a_flag_elsewhere_is_a_false_positive(self):
        # 'a', an established scene, would count; 'd' doesn't
        result = e2.score([_case(established=(('a', 'fact'),))], {'x-001': [_flag('d'), _flag('b')]},
                          {}, self.ORDER)
        assert result['metrics']['flags_true'] == 1
        assert result['metrics']['flags_false'] == 1
        assert result['metrics']['precision'] == 0.5

    def test_the_same_flag_from_two_cases_counts_once(self):
        cases = [_case('x-001'), _case('x-002')]
        flag = _flag('b', message='same')
        result = e2.score(cases, {'x-001': [flag], 'x-002': [dict(flag)]}, {}, self.ORDER)
        assert result['metrics']['flags_true'] == 1

    def test_any_flag_on_a_benign_edit_is_false(self):
        benign = dict(_case('b-01', code=None), benign=True, established=[], contradicted=[])
        result = e2.score([_case(), benign], {'x-001': [_flag('b')], 'b-01': [_flag('b', message='n')]},
                          {}, self.ORDER)
        assert result['metrics']['cases'] == 1
        assert result['metrics']['benign_flagged'] == 1
        assert result['metrics']['precision'] == 0.5

    def test_no_flags_scores_zero_not_an_error(self):
        result = e2.score([_case()], {'x-001': []}, {'b': []}, self.ORDER)
        assert result['metrics']['recall'] == 0.0
        assert result['metrics']['precision'] == 0.0
        assert 'precision' not in result['by_code']['TIM']

    def test_too_few_flags_fail_the_precision_gate(self):
        metrics = {'precision': 1.0, 'flags_true': 2, 'flags_false': 0}
        assert e2.precision_gate_value(metrics) == 0.0
        assert e2.precision_gate_value(dict(metrics, flags_true=e2.MIN_FLAGS_FOR_PRECISION)) == 1.0


class TestDriftCheck:
    def _project(self, tmp_path):
        os.makedirs(tmp_path / 'working')
        (tmp_path / 'working' / 'timeline-cues.csv').write_text(
            'id|relation|gap|anchor|refers|span|date\nb|continues|||||\nc|later|||||\n')
        return str(tmp_path)

    def test_a_scene_left_without_cues_is_an_error(self, tmp_path, monkeypatch):
        """Review of #341: a failed cue read left the old cues in place and
        scored as a confident miss."""
        import storyforge.timeline as timeline
        monkeypatch.setattr(timeline, 'check_scenes', lambda *a, **k: [])
        with pytest.raises(RuntimeError, match='no time cues read for b'):
            e2.drift_check(self._project(tmp_path), ['b'], str(tmp_path / 'logs'))

    def test_findings_become_tim_flags(self, tmp_path, monkeypatch):
        import storyforge.timeline as timeline

        def fake(project_dir, scenes, model, log_dir):
            timeline.write_cues(project_dir, {'b': {'relation': 'later'}})
            return [{'scene_id': 'b', 'check': 'gap_mismatch', 'message': 'm'}]

        monkeypatch.setattr(timeline, 'check_scenes', fake)
        project = self._project(tmp_path)
        assert e2.drift_check(project, ['b'], str(tmp_path / 'logs')) == [
            {'scene_id': 'b', 'code': 'TIM', 'check': 'gap_mismatch', 'message': 'm'}]
        # The other scenes' cues are kept
        assert timeline.read_cues(project)['c']['relation'] == 'later'


def _run_suite(tmp_path):
    suite = next(s for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites')) if s.name == 'e2-carol')
    ctx = harness.SuiteContext(name='e2-carol', mode='replay', cassette_dir=str(tmp_path / 'c'),
                               work_dir=str(tmp_path / 'w'))
    return suite.run(ctx)


def _change_detector(code_of=lambda scene: 'TIM'):
    """A stand-in that flags exactly the scenes whose text changed."""
    clean = {}

    def detector(project_dir, scenes, log_dir):
        flags = []
        for scene in scenes:
            text = open(os.path.join(project_dir, 'scenes', f'{scene}.md')).read()
            clean.setdefault(scene, text)
            if text != clean[scene]:
                flags.append({'scene_id': scene, 'code': code_of(scene), 'check': 'changed',
                              'message': project_dir.rsplit(os.sep, 1)[-1]})
        return flags
    return detector


def test_noticing_the_edited_scene_does_not_reach_the_precision_target(tmp_path, monkeypatch):
    """Review of #341: a detector that flags whichever scene changed scored
    recall and precision 1.0. Code matching and the benign edits stop it."""
    monkeypatch.setitem(e2.DETECTORS, 'drift-check', _change_detector())
    out = _run_suite(tmp_path)
    assert out.metrics['recall'] == 1.0
    assert out.by_code['TIM']['recall_code_match'] == 1.0
    assert out.by_code['KNO']['recall_code_match'] == 0.0
    assert out.metrics['benign_flagged'] == out.metrics['benign_cases']
    assert {g.name for g in out.gates} == {'recall_PHY', 'recall_TIM', 'recall_KNO',
                                           'recall_REL', 'recall_TRT', 'precision', 'flags'}
    actual = {g.name: g.actual for g in out.gates}
    assert actual['recall_TIM'] == 1.0 and actual['recall_KNO'] == 0.0
    assert actual['precision'] < e2.PRECISION_TARGET


def test_a_perfect_detector_fails_until_its_floors_are_raised(tmp_path, monkeypatch):
    by_dir = {c['id']: c for c in e2.load_cases('carol')}

    def detector(project_dir, scenes, log_dir):
        case = by_dir.get(project_dir.rsplit(os.sep, 1)[-1])
        if not case or case.get('benign'):
            return []
        return [{'scene_id': case['injection']['scene'], 'code': case['code'],
                 'check': 'perfect', 'message': case['id']}]

    monkeypatch.setitem(e2.DETECTORS, 'drift-check', detector)
    out = _run_suite(tmp_path)
    assert out.metrics['recall_code_match'] == 1.0
    assert out.metrics['precision'] == 1.0
    # #488: a gain over the recorded floors fails until they are raised
    assert not any(g.passed for g in out.gates)
    assert all('raise its floor to 1.0' in n for n in out.notes[:6])
    monkeypatch.setitem(e2.FLOORS, 'e2-carol', {g.name: g.actual for g in out.gates})
    out = _run_suite(tmp_path / 'again')
    assert all(g.passed for g in out.gates)
    assert not any('below the plan target' in n for n in out.notes)


class TestLedgerMigration:
    def test_a_copy_of_the_book_has_its_registries_in_the_ledger(self, tmp_path):
        from storyforge import ledger
        dest = e2.copy_book(BOOK_DIR, str(tmp_path / 'book'))
        ref = os.path.join(dest, 'reference')
        assert ledger.legacy_files(ref) == []
        rows = ledger.load_from(ref)
        assert {r['type'] for r in rows} == {'knowledge', 'physical'}
        # The frozen fixture itself is untouched
        assert ledger.legacy_files(os.path.join(BOOK_DIR, 'reference')) == list(ledger.LEGACY_FILES)

    def test_a_tree_that_cannot_migrate_is_named_in_the_notes(self, tmp_path):
        import harness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'knowledge.csv').write_text('id|name|aliases|category|origin\n'
                                           'a|One||\na|Two||\n')
        harness._MIGRATION_NOTES.clear()
        harness.migrate_tree(str(tmp_path), 'book@abc')
        assert len(harness._MIGRATION_NOTES) == 1
        assert harness._MIGRATION_NOTES[0].startswith('ledger migration stopped for book@abc')
        assert "id 'a' is on two rows that differ" in harness._MIGRATION_NOTES[0]
        assert (ref / 'knowledge.csv').exists()
        harness._MIGRATION_NOTES.clear()


class TestFloors:
    """#488: E2's gates are its replayed values (`FLOORS`), the plan's
    targets notes, as E7's noise ceiling is."""

    SUITES = ('e2-carol', 'e2-carol-checker', 'e2-corpus-drift', 'e2-corpus-validate')
    ALL = {f'recall_{c}': 0.5 for c in e2.GATED_CODES} | {'precision': 0.5, 'flags': 10}

    def _result(self, recall=None, precision=0.5, flags=10, cases=3):
        recall = {c: 0.5 for c in e2.GATED_CODES} if recall is None else recall
        return {'by_code': {c: {'recall_code_match': v, 'cases': cases}
                            for c, v in recall.items()},
                'metrics': {'precision': precision, 'flags_true': flags, 'flags_false': 0}}

    def _gates(self, monkeypatch, floors, result):
        monkeypatch.setitem(e2.FLOORS, 'test', floors)
        gates, notes = e2.floor_gates('test', result)
        return {g.name: g for g in gates}, notes

    def test_floors_are_the_registered_e2_suites(self):
        """TD-9: every E2 suite has floors, and only E2 suites do."""
        names = {s.name for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites'))
                 if s.name.startswith('e2-')}
        assert set(e2.FLOORS) == names == set(self.SUITES)

    def test_every_suite_gates_precision_flags_and_its_codes(self):
        for suite in self.SUITES:
            keys = set(e2.FLOORS[suite])
            assert {'precision', 'flags'} <= keys, suite
            assert keys - {'precision', 'flags'} <= {f'recall_{c}' for c in e2.GATED_CODES}

    def test_floors_never_drop_below_the_recorded_values(self):
        """Lowering a floor accepts a regression: it takes an edit here too.
        Each non-zero floor is pinned as a minimum (a 0 can't be lowered)."""
        lowest = {
            'e2-carol': {'flags': 1},
            'e2-carol-checker': {'recall_PHY': 0.6667, 'recall_TIM': 0.8, 'recall_KNO': 1.0,
                                 'recall_REL': 0.8, 'recall_TRT': 0.5, 'precision': 0.7742,
                                 'flags': 31},
            'e2-corpus-drift': {'recall_TIM': 0.1667, 'precision': 0.4, 'flags': 5},
            'e2-corpus-validate': {'recall_PHY': 0.4286, 'precision': 0.0305, 'flags': 753},
        }
        for suite, floors in lowest.items():
            for name, value in floors.items():
                assert e2.FLOORS[suite][name] >= value, (suite, name)
        for suite in self.SUITES:
            for name, value in e2.FLOORS[suite].items():
                if value:
                    assert name in lowest[suite], (suite, name)

    def test_equal_to_the_floor_passes(self, monkeypatch):
        gates, notes = self._gates(monkeypatch, self.ALL, self._result())
        assert all(g.passed for g in gates.values())
        assert not any('FLOORS' in n for n in notes)
        assert any('below the plan target' in n for n in notes)

    def test_a_gain_fails_until_the_floor_is_raised(self, monkeypatch):
        """No slack: an unrecorded gain would hide a later loss (E7's CR-2)."""
        gates, notes = self._gates(monkeypatch, self.ALL, self._result(
            {c: (0.75 if c == 'PHY' else 0.5) for c in e2.GATED_CODES}))
        assert [n for n, g in gates.items() if not g.passed] == ['recall_PHY']
        assert 'raise its floor to 0.75' in notes[0]

    def test_a_loss_fails(self, monkeypatch):
        gates, notes = self._gates(monkeypatch, self.ALL, self._result(precision=0.4))
        assert [n for n, g in gates.items() if not g.passed] == ['precision']
        assert 'a regression' in notes[0]

    def test_a_silent_detector_fails_even_on_zero_floors(self, monkeypatch):
        """SF-3: with every recall and precision floor 0, losing the flags
        still fails."""
        floors = {k: 0.0 for k in self.ALL} | {'flags': 1}
        result = self._result({c: 0.0 for c in e2.GATED_CODES}, precision=0.0, flags=0)
        gates, notes = self._gates(monkeypatch, floors, result)
        assert [n for n, g in gates.items() if not g.passed] == ['flags']
        assert any('only its flag count can regress' in n for n in notes)

    def test_a_code_with_no_cases_is_not_gated(self, monkeypatch):
        """SF-2: no REL case is no measurement, not a recall of 0."""
        floors = {k: v for k, v in self.ALL.items() if k != 'recall_REL'}
        recall = {c: 0.5 for c in e2.GATED_CODES if c != 'REL'}
        gates, notes = self._gates(monkeypatch, floors, self._result(recall))
        assert 'recall_REL' not in gates and all(g.passed for g in gates.values())
        assert 'recall_REL: no REL case, not gated' in notes

    def test_a_floored_code_whose_cases_vanish_fails(self, monkeypatch):
        recall = {c: 0.5 for c in e2.GATED_CODES if c != 'REL'}
        gates, notes = self._gates(monkeypatch, self.ALL, self._result(recall))
        assert gates['recall_REL'].passed is False
        assert any('no case of its code was scored' in n for n in notes)

    def test_a_code_with_cases_and_no_floor_fails(self, monkeypatch):
        floors = {k: v for k, v in self.ALL.items() if k != 'recall_REL'}
        gates, notes = self._gates(monkeypatch, floors, self._result())
        assert gates['recall_REL'].passed is False
        assert any('no floor recorded' in n for n in notes)

    def test_too_few_flags_count_precision_as_zero(self, monkeypatch):
        floors = {k: 0.0 for k in self.ALL} | {'flags': 2}
        gates, notes = self._gates(monkeypatch, floors, self._result(
            {c: 0.0 for c in e2.GATED_CODES}, precision=1.0, flags=2))
        assert gates['precision'].actual == 0.0
        assert all(g.passed for g in gates.values())


def test_corpus_suite_output_gates_on_the_named_suites_floors():
    """T-6: suite_output reads FLOORS[suite], and names too few flags."""
    from e2 import corpus
    out = corpus.suite_output('e2-corpus-drift', 'x', [], {}, {}, {})
    gates = {g.name: g for g in out.gates}
    floors = e2.FLOORS['e2-corpus-drift']
    assert {n: g.threshold for n, g in gates.items() if n in floors} == {
        n: v for n, v in floors.items() if n in gates}
    assert gates['flags'].passed is False      # nothing flagged
    assert any('fewer than' in n for n in out.notes)
