import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402,F401
import e5  # noqa: E402


def test_parse_mismatches():
    text = 'ok {"mismatches": [{"code": "TIM", "fact": "f", "original": "a", "redraft": "b"}]}'
    assert e5.parse_mismatches(text)[0]['code'] == 'TIM'
    assert e5.parse_mismatches('{"mismatches": []}') == []


@pytest.mark.parametrize('text', ['none', '{"items": []}', '{"mismatches": [{"code": "VOI"}]}'])
def test_unreadable_answers_raise(text):
    with pytest.raises(ValueError):
        e5.parse_mismatches(text)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_sample_takes_act_one_scenes_with_prose_and_a_brief_in_reading_order(tmp_path):
    _write(tmp_path / 'reference' / 'scenes.csv',
           'id|seq|part\nc|3|1\na|1|1\nb|2|1\nd|4|2\ne|5|1\n')
    _write(tmp_path / 'reference' / 'scene-briefs.csv', 'id|goal\na|g\nb|\nc|g\nd|g\ne|g\n')
    for sid in 'abcd':
        _write(tmp_path / 'scenes' / f'{sid}.md', 'prose')
    _write(tmp_path / 'scenes' / 'e.md', '')
    # b has no brief, d is part 2, e has no prose
    assert e5.sample(str(tmp_path), n=5) == ['a', 'c']
    assert e5.sample(str(tmp_path), n=1) == ['a']


def test_act_wins_over_part(tmp_path):
    _write(tmp_path / 'reference' / 'scenes.csv', 'id|seq|act|part\na|1|2|1\nb|2|1|2\n')
    _write(tmp_path / 'reference' / 'scene-briefs.csv', 'id|goal\na|g\nb|g\n')
    for sid in 'ab':
        _write(tmp_path / 'scenes' / f'{sid}.md', 'prose')
    assert e5.sample(str(tmp_path)) == ['b']


def test_the_e5_suite_loads():
    names = {s.name for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites'))}
    assert 'e5-roundtrip' in names
