import importlib.util
import shutil
import sys

import pytest

from conftest import FIXTURE_DIR, PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    'e7_suite', PLUGIN_DIR / 'evals' / 'suites' / 'e7_classics.py')
e7 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e7)

HEADER = 'group|run|source|scene_id|code|flag|verdict|cause|ben_verdict\n'


@pytest.fixture
def fixtures(tmp_path, monkeypatch):
    monkeypatch.setattr(e7, 'FIXTURES', str(tmp_path))
    return tmp_path


def _book(root, flags, labels):
    """A one-snapshot book whose validator raises ``flags``."""
    shutil.copytree(FIXTURE_DIR / 'reference', root / 'book' / 'run1' / 'reference')
    (root / 'book' / 'flags.csv').write_text(HEADER + ''.join(labels))
    return flags


def _ctx(tmp_path):
    return harness.SuiteContext('e7-classics', 'replay', str(tmp_path / 'c'), str(tmp_path))


def _flag(msg, scene='s1', category='physical_state'):
    return {'passed': False, 'category': category, 'check': 'x', 'message': msg, 'scene_id': scene}


def test_flags_are_matched_to_verdicts_and_unlabeled_ones_are_unreviewed(fixtures, tmp_path, monkeypatch):
    flags = _book(fixtures, None, [
        'A|run1|validate:x|s1|PHY|state gone|false-positive||false-positive\n',
        'B|run1|validate:x|s2|TIM|flashback|deliberate||deliberate\n',
    ])
    monkeypatch.setattr(e7, 'continuity_flags', lambda ref: [
        _flag('state gone'), _flag('flashback', 's2', 'timeline'), _flag('brand new', 's3')])
    out = e7.run(_ctx(tmp_path))
    assert out.metrics['false_positive'] == 1 and out.metrics['deliberate'] == 1
    assert out.metrics['unreviewed'] == 1 and out.metrics['noise'] == 3
    assert {g.name: g.passed for g in out.gates} == {'unreviewed': False, 'noise': False}
    assert any('brand new' in n for n in out.notes)
    assert out.by_code == {'PHY': {'false-positive': 1, 'unreviewed': 1}, 'TIM': {'deliberate': 1}}


def test_a_real_find_is_not_noise(fixtures, tmp_path, monkeypatch):
    _book(fixtures, None, ['A|run1|validate:x|s1|PHY|a real one|real||real\n'])
    monkeypatch.setattr(e7, 'continuity_flags', lambda ref: [_flag('a real one')])
    out = e7.run(_ctx(tmp_path))
    assert out.metrics['real'] == 1 and out.metrics['noise'] == 0
    assert all(g.passed for g in out.gates)


def test_a_flag_without_a_verdict_is_refused(fixtures, tmp_path):
    _book(fixtures, None, ['A|run1|validate:x|s1|PHY|f|false-positive||\n'])
    with pytest.raises(ValueError, match='no valid ben_verdict'):
        e7.run(_ctx(tmp_path))


def test_no_snapshots_is_an_error(fixtures, tmp_path):
    with pytest.raises(RuntimeError, match='no snapshots'):
        e7.run(_ctx(tmp_path))


def test_the_carol_snapshots_reproduce_every_labeled_validate_flag():
    labels = e7.load_labels('christmas-carol')
    raised = set()
    for book, run, ref in e7.book_snapshots():
        raised |= {(run, f.get('scene_id', ''), f['message']) for f in e7.continuity_flags(ref)}
    assert raised == set(labels)
