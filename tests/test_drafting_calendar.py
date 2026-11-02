"""The calendar in the drafting prompt.

Since #478 the checker sees every scene's `timeline_day` / `time_of_day`
and stops on an elapsed time that breaks them; the writer didn't, so it
guessed spans the gate then caught ("ten days" from day 5 to day 19,
"eight days" made "five" and still off). The drafting prompt now carries
the same calendar lines the checker reads (`prompts.scene_when`)."""

import os

from storyforge import checker
from storyforge.elaborate import update_scene
from storyforge.prompts import build_scene_prompt_from_briefs, scene_when

from conftest import PLUGIN_DIR

SCENE = 'act1-sc02'
HEADING = '## The Calendar'


def _prompt(project_dir, scene=SCENE, coaching='full', voice=''):
    return build_scene_prompt_from_briefs(scene, project_dir, PLUGIN_DIR, coaching,
                                          voice_reference=voice)


def _set(project_dir, sid, **cols):
    update_scene(sid, os.path.join(project_dir, 'reference'), cols)


def _calendar(prompt):
    start = prompt.index(HEADING)
    end = prompt.index('\n## ', start + 1)
    return prompt[start:end]


class TestTheCalendar:

    def test_every_dated_scene_in_reading_order_with_this_one_marked(self, project_dir):
        cal = _calendar(_prompt(project_dir))
        assert 'this scene is day 1, evening' in cal
        lines = [l for l in cal.splitlines() if ': day ' in l]
        assert lines == ['act1-sc01: day 1, morning',
                         'act1-sc02: day 1, evening  <- this scene',
                         'new-x1: day 2, afternoon',
                         'act2-sc01: day 3, morning',
                         'act2-sc02: day 3, afternoon',
                         'act2-sc03: day 4, evening']
        assert 'must fit these days' in cal and "don't name one" in cal

    def test_later_scenes_are_in_it_too(self, project_dir):
        # a scene can promise a span forward ("in three days the ship sails")
        assert 'act2-sc03: day 4, evening' in _calendar(_prompt(project_dir, 'act1-sc01'))

    def test_the_lines_match_the_checkers_word_for_word(self, project_dir):
        _set(project_dir, 'act1-sc01', time_mode='summary')
        _set(project_dir, 'new-x1', timeline_day='', time_mode='frame')
        cal = _calendar(_prompt(project_dir))
        book = checker.Book.load(project_dir, SCENE)
        for line in book.calendar().splitlines():
            assert line in cal
        assert 'act1-sc01: day 1, morning, a summary: covers a stretch from that day' in cal
        assert "new-x1: afternoon, frame narration: not the story's present" in cal

    def test_cut_and_merged_scenes_are_left_out(self, project_dir):
        _set(project_dir, 'new-x1', status='cut')
        _set(project_dir, 'act2-sc01', status='merged')
        cal = _calendar(_prompt(project_dir))
        assert 'new-x1' not in cal and 'act2-sc01' not in cal
        assert 'act2-sc02: day 3, afternoon' in cal

    def test_an_undated_scene_says_so(self, project_dir):
        _set(project_dir, SCENE, timeline_day='', time_of_day='')
        cal = _calendar(_prompt(project_dir))
        assert 'this scene has no day' in cal and '<- this scene' not in cal

    def test_a_book_with_no_days_gets_no_calendar(self, project_dir):
        # times of day alone give no days to count (the checker's rule too)
        for sid in checker.Book.load(project_dir, SCENE).order:
            _set(project_dir, sid, timeline_day='')
        assert HEADING not in _prompt(project_dir)

    def test_it_sits_after_the_facts_and_before_the_task(self, project_dir):
        prompt = _prompt(project_dir)
        assert prompt.index('## Scene Brief') < prompt.index(HEADING) < prompt.index('## Task')

    def test_a_rewrite_gets_it_too(self, project_dir):
        assert HEADING in _prompt(project_dir, voice='Old prose.')


def test_scene_when():
    assert scene_when({}) == ''
    assert scene_when({'timeline_day': '19', 'time_of_day': 'evening'}) == 'day 19, evening'
    assert scene_when({'timeline_day': '3', 'time_mode': 'vision'}) == \
        "day 3, a vision: not the story's present"
