import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402,F401
import e4  # noqa: E402


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_parse_judgment():
    text = ('ok {"contradictions": [{"code": "TIM", "fact": "f", "quote": "a", "against": "b"}], '
            '"broken_promises": [{"field": "outcome", "promise": "p", "why": "w"}]}')
    judged = e4.parse_judgment(text)
    assert judged['contradictions'][0]['code'] == 'TIM'
    assert judged['broken_promises'][0]['field'] == 'outcome'
    assert e4.parse_judgment('{"contradictions": [], "broken_promises": []}') == {
        'contradictions': [], 'broken_promises': []}


@pytest.mark.parametrize('text', [
    'none',
    '{"contradictions": []}',
    '{"contradictions": [{"code": "VOI"}], "broken_promises": []}',
    '{"contradictions": [], "broken_promises": [{"field": "emotions"}]}',
])
def test_unreadable_answers_raise(text):
    with pytest.raises(ValueError):
        e4.parse_judgment(text)


def test_act_scenes_in_reading_order_and_act_wins_over_part(tmp_path):
    _write(tmp_path / 'reference' / 'scenes.csv',
           'id|seq|act|part\nc|3||1\na|1||1\nb|2|2|1\nd|4||2\n')
    assert [r['id'] for r in e4.act_scenes(str(tmp_path))] == ['a', 'c']


def test_clear_prose_removes_the_files_and_keeps_the_text(tmp_path):
    _write(tmp_path / 'scenes' / 'a.md', 'author prose')
    assert e4.clear_prose(str(tmp_path), ['a', 'missing']) == {'a': 'author prose'}
    assert not (tmp_path / 'scenes' / 'a.md').exists()


def test_brief_block_lists_promise_fields_only(tmp_path):
    _write(tmp_path / 'reference' / 'scene-briefs.csv',
           'id|goal|outcome|emotions|key_dialogue\na|find it|no-and|dread|"Your turn"\n')
    block = e4.brief_block(str(tmp_path), 'a')
    assert 'goal: find it' in block and 'Your turn' in block
    assert 'dread' not in block


def test_judge_prompt_marks_the_first_scene():
    assert '(none: this is the first scene)' in e4.judge_prompt([], 'goal: g', 'a', 'prose')
    assert '<scene id="a">' in e4.judge_prompt([('a', 'earlier')], 'goal: g', 'b', 'prose')


def test_length_drift_and_rate():
    rows = [{'id': 'a', 'target_words': '100'}, {'id': 'b', 'target_words': '200'},
            {'id': 'c', 'target_words': ''}]
    drafts = {'a': 'w ' * 150, 'b': 'w ' * 100, 'c': 'w ' * 10}
    assert e4.length_drift(rows, drafts) == 0.5
    assert e4.per_10k(3, 20000) == 1.5
    assert e4.per_10k(3, 0) == 0.0


def test_the_e4_suite_loads():
    names = {s.name for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites'))}
    assert 'e4-generation' in names
