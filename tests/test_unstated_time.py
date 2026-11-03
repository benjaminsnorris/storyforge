"""#488: `time_of_day = unstated` is a valid value that reads as no time."""

from storyforge.schema import VALID_TIMES, stated_time
from storyforge.prompts import scene_when
from storyforge.extract_describe import _scene_line


def test_unstated_is_a_valid_time():
    assert 'unstated' in VALID_TIMES


def test_stated_time():
    assert stated_time(' night ') == 'night'
    assert stated_time('unstated') == ''
    assert stated_time('Unstated') == ''
    assert stated_time(None) == ''


def test_scene_when_shows_unstated_as_no_time():
    assert scene_when({'timeline_day': '3', 'time_of_day': 'unstated'}) == 'day 3'
    assert scene_when({'time_of_day': 'unstated'}) == ''


def test_timeline_description_shows_unstated_as_no_time():
    line = _scene_line({'seq': '1', 'id': 'a', 'time_of_day': 'unstated',
                        'timeline_date': '', 'summary': 'S.'})
    assert line == '- 1 `a`: S.'
