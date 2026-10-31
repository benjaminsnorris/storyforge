"""Prior prose in the drafting request (rethink plan decision 4)."""

import os

import pytest

from storyforge import prompts


def test_window_is_the_preceding_scene_and_each_threads_latest(project_dir):
    # act2-sc03 carries archive-erasure (new-x1) and map-anomaly (act1-sc01);
    # act2-sc02 has no prose, so the preceding scene with prose is act2-sc01
    assert prompts.prior_scenes('act2-sc03', project_dir, 'window') == [
        'act1-sc01', 'new-x1', 'act2-sc01']


def test_full_is_every_earlier_scene_with_prose(project_dir):
    assert prompts.prior_scenes('act2-sc03', project_dir, 'full') == [
        'act1-sc01', 'act1-sc02', 'new-x1', 'act2-sc01']


@pytest.mark.parametrize('mode', ['window', 'full', 'none'])
def test_the_first_scene_and_none_get_nothing(project_dir, mode):
    assert prompts.prior_scenes('act1-sc01', project_dir, mode) == []
    assert prompts.prior_prose_blocks('act1-sc01', project_dir, mode) == []
    assert prompts.prior_scenes('act2-sc03', project_dir, 'none') == []


def test_blocks_hold_each_scene_and_end_on_a_cache_breakpoint(project_dir):
    blocks = prompts.prior_prose_blocks('new-x1', project_dir, 'full')
    assert 'THE STORY SO FAR' in blocks[0]['text']
    assert [b['text'].split('"')[1] for b in blocks[1:]] == ['act1-sc01', 'act1-sc02']
    assert 'cache_control' in blocks[-1] and all('cache_control' not in b for b in blocks[:-1])
    with open(os.path.join(project_dir, 'scenes', 'act1-sc02.md')) as f:
        assert f.read().strip() in blocks[-1]['text']


def test_full_requests_extend_each_other(project_dir):
    """What makes the manuscript so far a cache read: each scene's blocks
    start with the previous scene's."""
    a = prompts.prior_prose_blocks('act2-sc01', project_dir, 'full')
    b = prompts.prior_prose_blocks('act2-sc02', project_dir, 'full')
    strip = [{k: v for k, v in x.items() if k != 'cache_control'} for x in a]
    assert [{k: v for k, v in x.items() if k != 'cache_control'}
            for x in b[:len(a)]] == strip


def test_mode_comes_from_the_override_then_the_yaml(project_dir):
    assert prompts.prior_prose_mode(project_dir) == 'window'
    assert prompts.prior_prose_mode(project_dir, 'full') == 'full'
    path = os.path.join(project_dir, 'storyforge.yaml')
    with open(path, 'a') as f:
        f.write('\ndrafting:\n  prior_prose: none\n')
    assert prompts.prior_prose_mode(project_dir) == 'none'
    with pytest.raises(ValueError, match='prior_prose'):
        prompts.prior_prose_mode(project_dir, 'everything')



def test_a_cut_or_merged_scene_is_never_earlier_prose(project_dir):
    from storyforge.csv_cli import update_field
    update_field(os.path.join(project_dir, 'reference', 'scenes.csv'), 'act2-sc01',
                 'status', 'cut')
    assert prompts.prior_scenes('act2-sc03', project_dir, 'window') == ['act1-sc01', 'new-x1']
    assert 'act2-sc01' not in prompts.prior_scenes('act2-sc03', project_dir, 'full')


def test_full_past_the_cap_falls_back_to_the_window_and_says_so(
        project_dir, monkeypatch, capsys):
    monkeypatch.setattr(prompts, 'FULL_MAX_WORDS', 10)
    assert prompts.prior_scenes('act2-sc03', project_dir, 'full') == \
        prompts.prior_scenes('act2-sc03', project_dir, 'window')
    assert 'WARNING: act2-sc03' in capsys.readouterr().out


def test_thread_signs_are_ignored(project_dir):
    # act2-sc02 closes uncharted-reaches (-), which act2-sc01 opened (+)
    assert 'act2-sc01' in prompts.prior_scenes('act2-sc02', project_dir, 'window')
