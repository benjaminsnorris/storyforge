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
    gates = {g.name: g.passed for g in out.gates}
    assert gates == {'unreviewed': False, 'missing_labels': True, 'duplicate_flags': True,
                     'noise': False}
    assert any('brand new' in n for n in out.notes)
    assert out.by_code == {'PHY': {'false-positive': 1, 'unreviewed': 1}, 'TIM': {'deliberate': 1}}


def test_a_real_find_is_not_noise(fixtures, tmp_path, monkeypatch):
    _book(fixtures, None, ['A|run1|validate:x|s1|PHY|a real one|real||real\n'])
    monkeypatch.setattr(e7, 'continuity_flags', lambda ref: [_flag('a real one')])
    monkeypatch.setattr(e7, 'NOISE_CEILING', 0)
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


@pytest.mark.parametrize('book', ['christmas-carol', 'plastic-age'])
def test_each_book_reproduces_every_labeled_validate_flag(book, tmp_path):
    labels = e7.load_labels(book)
    raised = set()
    for snap_book, run, ref in e7.book_snapshots():
        if snap_book == book:
            raised |= {(run, f.get('scene_id', ''), f['message'])
                       for f in e7.continuity_flags(
                           e7.migrated(ref, str(tmp_path), f'{book}/{run}'))}
    assert raised == set(labels)


def _two_labeled(fixtures):
    _book(fixtures, None, ['A|run1|validate:x|s1|PHY|a|false-positive||false-positive\n',
                           'A|run1|validate:x|s2|PHY|b|false-positive||false-positive\n'])


def test_noise_must_equal_the_ceiling_both_ways(fixtures, tmp_path, monkeypatch):
    """CR-2: a `<=` gate left slack after a fix that later new noise filled."""
    _two_labeled(fixtures)
    monkeypatch.setattr(e7, 'continuity_flags', lambda ref: [_flag('a'), _flag('b', 's2')])
    monkeypatch.setattr(e7, 'NOISE_CEILING', 1)
    out = e7.run(_ctx(tmp_path))
    assert {g.name: g.passed for g in out.gates}['noise'] is False
    assert 'new noise' in out.notes[0]
    monkeypatch.setattr(e7, 'NOISE_CEILING', 3)
    out = e7.run(_ctx(tmp_path / 'again'))
    assert {g.name: g.passed for g in out.gates}['noise'] is False
    assert out.notes[0] == 'noise 2, NOISE_CEILING 3: lower NOISE_CEILING to 2'
    monkeypatch.setattr(e7, 'NOISE_CEILING', 2)
    assert all(g.passed for g in e7.run(_ctx(tmp_path / 'third')).gates)


def test_flags_that_vanish_fail_rather_than_pass_as_less_noise(fixtures, tmp_path, monkeypatch):
    """SF-2a/2b: a check that stops raising (a renamed category, a lost
    snapshot) read as less noise, and its stale label could match later."""
    _two_labeled(fixtures)
    monkeypatch.setattr(e7, 'continuity_flags', lambda ref: [_flag('a')])
    monkeypatch.setattr(e7, 'NOISE_CEILING', 1)
    out = e7.run(_ctx(tmp_path))
    assert out.metrics['missing_labels'] == 1
    assert {g.name: g.passed for g in out.gates}['missing_labels'] is False
    assert any(n.startswith('labeled but not raised book/run1/s2: b') for n in out.notes)


def test_a_flag_raised_twice_fails(fixtures, tmp_path, monkeypatch):
    _two_labeled(fixtures)
    monkeypatch.setattr(e7, 'continuity_flags',
                        lambda ref: [_flag('a'), _flag('a'), _flag('b', 's2')])
    monkeypatch.setattr(e7, 'NOISE_CEILING', 3)
    out = e7.run(_ctx(tmp_path))
    assert out.metrics['duplicate_flags'] == 1
    assert {g.name: g.passed for g in out.gates}['duplicate_flags'] is False


def test_the_ceiling_never_rises_unseen():
    """T-4: lowering the ceiling is routine; raising it accepts new noise, so
    it takes this second edit too."""
    assert e7.NOISE_CEILING <= 105


def test_the_ceiling_is_the_replayed_count(tmp_path):
    """The gate holds noise to the count it has; a change that removes flags
    lowers the ceiling with it, so the gate never has slack to hide new noise."""
    out = e7.run(_ctx(tmp_path))
    assert out.metrics['noise'] == e7.NOISE_CEILING
    assert all(g.passed for g in out.gates)


def test_ci_runs_e7_with_its_notes():
    workflow = (PLUGIN_DIR / '.github' / 'workflows' / 'e7-classics.yml').read_text()
    assert 'evals/run.py --suite e7-classics --notes' in workflow
    assert 'pull_request' in workflow


def test_e7_replays_with_the_standard_library_only(tmp_path):
    """T-5: CI installs nothing; -I -S drops site-packages and the user's env,
    so a third-party import on the validator's path fails here, not in CI."""
    import os
    import subprocess
    env = {k: v for k, v in os.environ.items()
           if k not in ('ANTHROPIC_API_KEY', 'PYTHONPATH')}
    proc = subprocess.run(
        [sys.executable, '-I', '-S', 'evals/run.py', '--suite', 'e7-classics', '--notes',
         '--results-file', str(tmp_path / 'r.json'), '--baseline-file', str(tmp_path / 'none.json')],
        cwd=PLUGIN_DIR, env=env, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'note: christmas-carol/run1:' in proc.stdout
