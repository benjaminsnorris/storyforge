import copy
import os
import shutil
import subprocess
import sys

import pytest

from conftest import FIXTURE_DIR, PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402,F401
from e2 import corpus  # noqa: E402
from test_evals_e1 import CASE  # noqa: E402


def test_to_e2_uses_the_in_tree_scene_and_drops_non_prose_spans():
    case = copy.deepcopy(CASE)
    case['established'].append({**CASE['established'][0], 'source': 'reference', 'path': 'reference/bible.md'})
    shaped = corpus.to_e2(case)
    assert [s['scene'] for s in shaped['contradicted']] == ['90']   # scenes/90.md, not the HEAD slug
    assert [s['scene'] for s in shaped['established']] == ['44']
    assert shaped['target'] == '90' and shaped['injection'] == {'scene': CASE['id']}


def test_to_e2_without_a_prose_contradiction_is_none():
    case = copy.deepcopy(CASE)
    case['contradicted'] = [{**CASE['contradicted'][0], 'source': 'csv'}]
    assert corpus.to_e2(case) is None


@pytest.fixture
def book(tmp_path):
    repo = tmp_path / 'corpus' / 'book'
    shutil.copytree(FIXTURE_DIR / 'reference', repo / 'reference')
    scene = sorted(os.listdir(FIXTURE_DIR / 'scenes'))[0]
    (repo / 'scenes').mkdir()
    shutil.copy(FIXTURE_DIR / 'scenes' / scene, repo / 'scenes' / scene)
    git = ['git', '-C', str(repo), '-c', 'user.email=t@t', '-c', 'user.name=t']
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(git + ['add', '-A'], check=True)
    subprocess.run(git + ['commit', '-qm', 'error present'], check=True)
    (repo / 'scenes' / scene).write_text('fixed\n')
    subprocess.run(git + ['commit', '-qam', 'fix'], check=True)
    shas = subprocess.run(git + ['rev-list', 'HEAD'], capture_output=True, text=True).stdout.split()
    return tmp_path / 'corpus', scene[:-3], shas[1], shas[0]


def test_run_gives_each_call_its_own_copy_and_prepares_each_tree_once(book, tmp_path):
    root, scene, tree, fix = book
    cases = [{'id': f'book-00{i}', 'repo': 'book', 'tree': tree, 'control': fix, 'target': scene}
             for i in (1, 2)] + [{'id': 'book-003', 'repo': 'book', 'tree': tree, 'control': None,
                                  'target': scene}]
    prepared, seen = [], []

    def detector(project, scenes, log_dir):
        seen.append(project)
        with open(os.path.join(project, 'scenes', f'{scene}.md')) as f:
            return [{'scene_id': scene, 'code': 'PHY', 'check': 'c', 'message': f.read()[:5]}]

    case_flags, control_flags = corpus.run(cases, detector, str(tmp_path / 'w'),
                                           prepare_tree=prepared.append, root=str(root))
    assert len(prepared) == 2                       # the error tree and the fix tree, once each
    assert len(set(seen)) == len(seen) == 5         # 3 cases + 2 controls, no shared copies
    assert set(control_flags) == {'book-001', 'book-002'}   # unfixed case has no control
    assert control_flags['book-001'][0]['message'] == 'fixed'
    assert case_flags['book-001'][0]['message'] != 'fixed'


def test_validate_detector_maps_categories_to_codes():
    flags = corpus.validate_detector(str(FIXTURE_DIR), [], '')
    assert all(f['code'] in ('PHY', 'TIM', 'KNO') for f in flags)


def test_bootstrap_refuses_a_partial_calendar(monkeypatch, tmp_path):
    from storyforge import timeline
    monkeypatch.setattr(timeline, 'reading_order', lambda p: ['a', 'b'])
    monkeypatch.setattr(timeline, 'cue_prompts', lambda p, ids: {'a': 'x', 'b': 'y'})
    monkeypatch.setattr(timeline, 'extract_cues', lambda p, ids, m, d: {'a': {}})
    with pytest.raises(RuntimeError, match='time cues failed for 1'):
        corpus.bootstrap_cues(str(tmp_path))


def test_suites_load():
    import harness as h
    names = {s.name for s in h.discover(str(PLUGIN_DIR / 'evals' / 'suites'))}
    assert {'e2-corpus-validate', 'e2-corpus-drift'} <= names


def _timeline_book(root, days):
    """A reference dir whose scenes run in the given order with the given days."""
    ref = root / 'reference'
    ref.mkdir(parents=True)
    head = 'id|seq|title|act|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
    (ref / 'scenes.csv').write_text(head + ''.join(
        f'{sid}|{i}|T|1|{pov}|Town|{day}|morning|1 hour|action|briefed|1000|2000\n'
        for i, (sid, day, pov) in enumerate(days, 1)))
    (ref / 'scene-intent.csv').write_text(
        'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads\n'
        + ''.join(f'{sid}|f|action|flat|truth|+/-|revelation|a|{pov}|{pov}|\n' for sid, _, pov in days))
    (ref / 'scene-briefs.csv').write_text(
        'id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n'
        + ''.join(f'{sid}|g|c|o|cr|d|k|k|a|d|e|m||false\n' for sid, _, _ in days))
    return str(root)


def test_a_scene_an_edit_moves_into_a_timeline_run_is_still_found(tmp_path):
    """F-122 review: validate groups a run of scenes set before the present
    into one finding keyed by its first scene. The control book has the run
    a-b; the edit sets x before the present too, extending it to a-b-x. Keyed
    only by its first scene, the case's finding matched the control's and was
    dropped as a baseline flag, so recall fell with no error."""
    from e2 import score
    control = _timeline_book(tmp_path / 'control', [('p', 30, 'dee'), ('a', 10, 'fred'),
                                                   ('b', 11, 'fred'), ('x', 31, 'dee')])
    edited = _timeline_book(tmp_path / 'edited', [('p', 30, 'dee'), ('a', 10, 'fred'),
                                                  ('b', 11, 'fred'), ('x', 12, 'fred')])
    control_flags = corpus.validate_detector(control, [], '')
    case_flags = corpus.validate_detector(edited, [], '')
    tim = [f for f in case_flags if f['check'] == 'timeline-order']
    assert sorted(f['scene_id'] for f in tim) == ['a', 'b', 'x']   # one flag per scene in the run
    case = {'id': 'c1', 'code': 'TIM', 'injection': {'scene': 'x'},
            'contradicted': [{'scene': 'x'}], 'established': []}
    result = score([case], {'c1': case_flags}, {'x': control_flags}, ['p', 'a', 'b', 'x'])
    assert result['metrics']['recall_code_match'] == 1.0
