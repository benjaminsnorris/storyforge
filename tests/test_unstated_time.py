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


# --- #488 review: every writer of time_of_day knows `unstated`; the frame
# exemption is shared by L5 and validate (CR-1, CR-2, TD-1..TD-6) ---

from storyforge.schema import TIMES_OF_DAY, UNSTATED_TIME


def test_valid_times_are_the_real_times_and_unstated():
    assert UNSTATED_TIME not in TIMES_OF_DAY
    assert VALID_TIMES == TIMES_OF_DAY | {UNSTATED_TIME}


def test_enrich_keeps_unstated_and_offers_it():
    from storyforge import enrich
    assert enrich.validate_time_of_day('Unstated') == 'unstated'
    assert enrich.validate_time_of_day('night') == 'night'
    assert enrich.validate_time_of_day('teatime') == ''
    assert not hasattr(enrich, 'VALID_TIMES')   # one list, the schema's
    import inspect
    assert 'or unstated when the text gives none' in inspect.getsource(enrich)


def test_gap_fill_offers_unstated():
    from storyforge import prompts_elaborate
    import inspect
    assert 'or unstated when' in inspect.getsource(prompts_elaborate)


def test_force_keyword_inference_keeps_unstated(tmp_path):
    from storyforge.cmd_enrich import _infer_times_of_day
    csv_path = tmp_path / 'scenes.csv'
    csv_path.write_text('id|location|time_of_day\n'
                        'a|night market|unstated\n'
                        'b|night market|\n'
                        'c|night market|morning\n')
    written, kept = _infer_times_of_day(str(csv_path), str(tmp_path), ['a', 'b', 'c'], True)
    rows = {line.split('|')[0]: line.split('|')[2] for line in csv_path.read_text().splitlines()[1:]}
    assert rows['a'] == 'unstated' and kept == ['a']
    assert rows['b'] == 'night' and rows['c'] == 'night' and written == 2
    written, kept = _infer_times_of_day(str(csv_path), str(tmp_path), ['a'], False)
    assert (written, kept) == (0, [])


def test_time_mode_is_normalized():
    from storyforge.elaborate import time_mode
    assert time_mode({'time_mode': ' Frame '}) == 'frame'
    assert time_mode({'time_mode': ''}) == 'scene'
    assert time_mode({'time_mode': None}) == 'scene'
    assert time_mode({}) == 'scene'


def _validate_project(tmp_path, mode, tod):
    ref = tmp_path / 'reference'
    ref.mkdir(parents=True)
    (ref / 'scenes.csv').write_text(
        'id|seq|title|act|pov|location|timeline_day|time_of_day|duration|status|time_mode\n'
        f'a|1|T|1|narrator|loc|1|{tod}||mapped|{mode}\n')
    (ref / 'scene-intent.csv').write_text(
        'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|'
        'turning_point|characters|on_stage\n'
        'a|f|action|arc|v|+/-|revelation|hero|hero\n')
    from storyforge.elaborate import validate_structure
    report = validate_structure(str(ref))
    return next(c for c in report['checks'] if c['check'] == 'required-columns-a')


def test_validate_exempts_a_frame_scene_from_time_of_day(tmp_path):
    """CR-1: L5 and validate agree, so gap-fill never invents a time for
    frame narration; an ordinary or vision scene still needs one."""
    assert _validate_project(tmp_path / 'f', 'Frame', '')['passed'] is True
    for mode in ('scene', 'vision'):
        check = _validate_project(tmp_path / mode, mode, '')
        assert check['passed'] is False and 'time_of_day' in check['fields'], mode
    assert _validate_project(tmp_path / 'u', 'scene', 'unstated')['passed'] is True


def test_timeline_assignment_prompt_shows_unstated_as_unknown():
    """T-1: the cue prompt says '?' (no time), never 'unstated' as a time."""
    from storyforge.timeline import build_assignment_prompt
    prompt = build_assignment_prompt(
        [{'id': 's', 'time_of_day': 'unstated', 'cues': {}, 'provisional': None},
         {'id': 't', 'time_of_day': 'night', 'cues': {}, 'provisional': None}], 1, 1, [])
    assert 'time of day: ?' in prompt and 'time of day: night' in prompt
    assert 'unstated' not in prompt


def test_story_power_scene_map_reads_unstated_as_no_time(tmp_path):
    """T-2: the scorer sees no time, not 'unstated', for such a scene."""
    from storyforge.scoring_story_power import parse_scene_map
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'scenes.csv').write_text('id|seq|summary|time_of_day\n'
                                    'a|1|S.|unstated\nb|2|S.|Night \n')
    scenes = {s.id: s for s in parse_scene_map(str(tmp_path))}
    assert scenes['a'].time_of_day == '' and scenes['b'].time_of_day == 'Night'
