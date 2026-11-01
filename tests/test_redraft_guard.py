"""Regression tests for thornwall 19530d5: a scene file overwritten with the
model's raw reply. ``_redraft_scenes`` wrote whatever came back; an
interactive revise session writes scene files directly. Both now go through
``parsing.unsafe_scene_reason``."""

import os
from unittest.mock import patch

import pytest

LONG = ' '.join(['The rain fell on the cobblestones.'] * 40)


def _scene(project_dir, sid, text):
    scenes_dir = os.path.join(project_dir, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    path = os.path.join(scenes_dir, f'{sid}.md')
    with open(path, 'w') as f:
        f.write(text)
    return path


def _redraft(project_dir, ids, reply):
    from storyforge.cmd_revise import _redraft_scenes
    with patch('storyforge.cmd_revise.invoke_api', return_value=reply), \
         patch('storyforge.cmd_revise.select_model', return_value='claude-sonnet-5-5'), \
         patch('storyforge.cmd_write._build_prompt', return_value='fake prompt'), \
         patch('storyforge.common.get_coaching_level', return_value='full'):
        return _redraft_scenes(project_dir, ids)


@pytest.mark.parametrize('reply', [
    'Here is the revised scene. I tightened the opening and',  # truncated
    'Too short now.',                                          # collapsed
])
def test_an_unsafe_redraft_is_not_written_and_raises(project_dir, reply):
    from storyforge.cmd_revise import RedraftError
    path = _scene(project_dir, 'kept', LONG)
    with pytest.raises(RedraftError, match='kept'):
        _redraft(project_dir, ['kept'], reply)
    with open(path) as f:
        assert f.read() == LONG


def test_safe_scenes_are_written_before_the_error(project_dir):
    from storyforge.cmd_revise import RedraftError
    _scene(project_dir, 'a', LONG)
    responses = iter([LONG + ' New ending.', 'cut off mid'])
    from storyforge.cmd_revise import _redraft_scenes
    with patch('storyforge.cmd_revise.invoke_api', side_effect=lambda *a, **k: next(responses)), \
         patch('storyforge.cmd_revise.select_model', return_value='claude-sonnet-5-5'), \
         patch('storyforge.cmd_write._build_prompt', return_value='fake prompt'), \
         patch('storyforge.common.get_coaching_level', return_value='full'):
        _scene(project_dir, 'b', LONG)
        with pytest.raises(RedraftError, match='1 scene'):
            _redraft_scenes(project_dir, ['a', 'b'])
    with open(os.path.join(project_dir, 'scenes', 'a.md')) as f:
        assert f.read().endswith('New ending.')


def test_redraft_or_halt_exits(project_dir):
    from storyforge.cmd_revise import _redraft_or_halt
    _scene(project_dir, 'kept', LONG)
    with patch('storyforge.cmd_revise.invoke_api', return_value='cut off'), \
         patch('storyforge.cmd_revise.select_model', return_value='claude-sonnet-5-5'), \
         patch('storyforge.cmd_write._build_prompt', return_value='fake prompt'), \
         patch('storyforge.common.get_coaching_level', return_value='full'), \
         pytest.raises(SystemExit):
        _redraft_or_halt(project_dir, ['kept'])


def test_interactive_writes_are_checked(project_dir):
    from storyforge.cmd_revise import _scene_texts, _unsafe_scene_writes
    _scene(project_dir, 'same', LONG)
    _scene(project_dir, 'good', LONG)
    _scene(project_dir, 'bad', LONG)
    before = _scene_texts(project_dir)
    _scene(project_dir, 'good', LONG + ' Then she left.')
    _scene(project_dir, 'bad', "I'll revise this scene now. First,")
    problems = _unsafe_scene_writes(project_dir, before)
    assert len(problems) == 1 and 'bad' in problems[0]


def test_unsafe_scene_reason():
    from storyforge.parsing import unsafe_scene_reason
    assert unsafe_scene_reason(LONG, LONG) == ''
    assert unsafe_scene_reason(LONG) == ''
    assert 'empty' in unsafe_scene_reason('  ')
    assert 'mid-sentence' in unsafe_scene_reason('and then')
    assert 'collapsed' in unsafe_scene_reason('Short.', LONG)


@pytest.mark.parametrize('ending', [
    'She left…', '*I am home.*', '_Run._', 'The end.\n\n---', 'The end.\n\n* * *',
])
def test_finished_prose_with_a_literary_ending_is_safe(ending):
    """An ellipsis, closing emphasis or a trailing scene break ends finished
    prose; rejecting it threw away paid, complete drafts (PR #364 review)."""
    from storyforge.parsing import unsafe_scene_reason
    assert unsafe_scene_reason(ending) == ''


@pytest.mark.parametrize('cut_off', ['and then she', 'word*', '---'])
def test_markup_does_not_hide_a_cut_off(cut_off):
    from storyforge.parsing import unsafe_scene_reason
    assert 'mid-sentence' in unsafe_scene_reason(cut_off)


def test_a_redraft_opts_into_the_refusal_fallback(project_dir):
    from storyforge.cmd_revise import _redraft_scenes
    _scene(project_dir, 'a', LONG)
    with patch('storyforge.cmd_revise.invoke_api', return_value=LONG + ' New.') as api, \
         patch('storyforge.cmd_revise.select_model', return_value='claude-sonnet-5-5'), \
         patch('storyforge.cmd_write._build_prompt', return_value='fake prompt'), \
         patch('storyforge.common.get_coaching_level', return_value='full'):
        _redraft_scenes(project_dir, ['a'])
    assert api.call_args.kwargs['fallback'] is True
