"""The calendar in the drafting prompt.

Since #478 the checker sees every scene's `timeline_day` / `time_of_day`
and stops on an elapsed time that breaks them; the writer didn't, so it
broke it in its drafts (E4: 5 TIM contradictions before the gate). The
drafting prompt now carries the same calendar lines the checker reads
(`prompts.calendar_lines`, `prompts.scene_when`)."""

import os

import pytest

from storyforge import checker, cmd_write
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

    def test_the_lines_are_the_checkers_exactly(self, project_dir):
        # review T-2: the whole list, in order, with a cut scene, a time-only
        # scene and time modes (a one-way substring check missed drift)
        _set(project_dir, 'act1-sc01', time_mode='summary')
        _set(project_dir, 'new-x1', timeline_day='', time_mode='frame')
        _set(project_dir, 'act2-sc01', status='cut')
        cal = _calendar(_prompt(project_dir))
        lines = [l.removesuffix('  <- this scene') for l in cal.split('\n\n')[2].splitlines()]
        assert lines == checker.Book.load(project_dir, SCENE).calendar().splitlines()
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

    def test_a_time_only_scene_is_not_said_to_be_a_day(self, project_dir):
        # review H1: the checker's rule since #478 (test_checker.py)
        _set(project_dir, SCENE, timeline_day='')
        cal = _calendar(_prompt(project_dir))
        assert 'this scene has no day' in cal and 'this scene is evening' not in cal
        assert 'act1-sc02: evening  <- this scene' in cal

    def test_scenes_with_no_day_are_named(self, project_dir):
        # review I2: silence would read as "every scene is listed"
        _set(project_dir, 'new-x1', timeline_day='', time_of_day='')
        _set(project_dir, 'act2-sc01', timeline_day='')
        cal = _calendar(_prompt(project_dir))
        assert cal.rstrip().endswith('No day in scenes.csv (name no span counted from these): '
                            'new-x1, act2-sc01')

    def test_a_fully_dated_book_names_none(self, project_dir):
        # the eval books are fully dated: their prompts carry no such line
        assert 'No day in scenes.csv' not in _prompt(project_dir)

    def test_the_scene_itself_stays_when_cut(self, project_dir):
        # review T-3: both sides keep the scene being drafted or checked
        _set(project_dir, SCENE, status='cut')
        assert 'act1-sc02: day 1, evening  <- this scene' in _calendar(_prompt(project_dir))
        assert 'act1-sc02: day 1, evening' in checker.Book.load(project_dir, SCENE).calendar()

    def test_a_book_with_no_days_gets_no_calendar(self, project_dir):
        # times of day alone give no days to count (the checker's rule too)
        for sid in checker.Book.load(project_dir, SCENE).order:
            _set(project_dir, sid, timeline_day='')
        assert HEADING not in _prompt(project_dir)

    def test_it_sits_after_the_facts_and_before_the_task(self, project_dir):
        prompt = _prompt(project_dir)
        assert prompt.index('## Established Facts') < prompt.index(HEADING) \
            < prompt.index('## Task')

    def test_a_rewrite_gets_it_too(self, project_dir):
        assert HEADING in _prompt(project_dir, voice='Old prose.')

    @pytest.mark.parametrize('coaching', ['coach', 'strict'])
    def test_guides_get_it_too(self, project_dir, coaching):
        # review T-4: coach/strict (the only coaching `--batch` takes) carry it
        assert 'act1-sc02: day 1, evening  <- this scene' in \
            _calendar(_prompt(project_dir, coaching=coaching))

    @pytest.mark.parametrize('coaching', ['full', 'coach'])
    def test_write_and_revise_prompts_carry_it(self, project_dir, coaching):
        # review T-5: write, its batch mode and revise's redrafts all build
        # their prompt through _build_prompt with these arguments
        prompt = cmd_write._build_prompt(SCENE, project_dir, coaching, use_briefs=True,
                                         system_context=True, rewrite=True)
        assert 'act1-sc02: day 1, evening  <- this scene' in prompt

    def test_a_bad_seq_stops_the_prompt(self, project_dir):
        # review T-6: no calendar without an order; it raises, not drops it
        path = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(path) as f:
            text = f.read()
        with open(path, 'w') as f:
            f.write(text.replace('act2-sc03|6|', 'act2-sc03|x|'))
        with pytest.raises(ValueError, match='act2-sc03'):
            _prompt(project_dir)


class TestWhatTheCalendarCantRead:
    """Review H2/I3: author data the calendar can't read as meant is logged
    as a WARNING, never passed silently."""

    def _warnings(self, project_dir, capsys):
        cal = _calendar(_prompt(project_dir))
        return cal, [l for l in capsys.readouterr().out.splitlines()
                     if 'drafting calendar' in l]

    def test_a_non_numeric_day_is_reported(self, project_dir, capsys):
        _set(project_dir, 'act2-sc01', timeline_day='Day 3')
        cal, warnings = self._warnings(project_dir, capsys)
        assert "act2-sc01: timeline_day 'Day 3' is not a whole number" in warnings[0]
        assert 'WARNING: act1-sc02 (drafting calendar): scenes.csv:' in warnings[0]
        assert 'act2-sc01: day Day 3, morning' in cal  # shown as written

    def test_a_negative_day_is_a_day(self, project_dir, capsys):
        # backstory days before the story's day 1 (shared-dark has day -2)
        _set(project_dir, 'act1-sc01', timeline_day='-2')
        cal, warnings = self._warnings(project_dir, capsys)
        assert warnings == [] and 'act1-sc01: day -2, morning' in cal

    def test_an_unknown_time_mode_is_reported(self, project_dir, capsys):
        _set(project_dir, 'new-x1', time_mode='flashback')
        cal, warnings = self._warnings(project_dir, capsys)
        assert "new-x1: time_mode 'flashback' is not one of" in warnings[0]
        assert 'shown as an ordinary scene' in warnings[0]

    def test_a_clean_book_logs_nothing(self, project_dir, capsys):
        _set(project_dir, 'new-x1', time_mode='Scene')
        assert self._warnings(project_dir, capsys)[1] == []

    def test_an_id_with_spaces_around_it_is_reported(self, project_dir, capsys):
        path = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(path) as f:
            text = f.read()
        with open(path, 'w') as f:
            f.write(text.replace('\nact2-sc03|', '\nact2-sc03 |'))
        cal, warnings = self._warnings(project_dir, capsys)
        assert any('act2-sc03: no scenes.csv row under that exact id' in w for w in warnings)
        assert 'act2-sc03' not in cal


def test_scene_when():
    assert scene_when({}) == ''
    assert scene_when({'time_mode': 'summary'}) == ''
    assert scene_when({'timeline_day': '  ', 'time_of_day': ' '}) == ''
    assert scene_when({'time_of_day': 'dusk', 'time_mode': ' Frame '}) == \
        "dusk, frame narration: not the story's present"
    assert scene_when({'timeline_day': '19', 'time_of_day': 'evening'}) == 'day 19, evening'
    assert scene_when({'timeline_day': '3', 'time_mode': 'vision'}) == \
        "day 3, a vision: not the story's present"


class TestTheRevisionCalendar:
    """Revise's prose passes (`revision.build_revision_prompt`) get the
    calendar too: #478's thornwall-020, "ten days" from day 5 to day 19, came
    from a `revision-plan` pass that had the days only as raw scenes.csv."""

    SCOPE = 'act1-sc02,act2-sc01'

    def _prompt(self, project_dir, scope=SCOPE, coaching='full'):
        from storyforge.revision import build_revision_prompt
        return build_revision_prompt('continuity', 'Fix continuity', scope, project_dir,
                                     coaching_level=coaching, api_mode=True)

    def test_every_scene_with_the_passs_scenes_marked(self, project_dir):
        cal = _calendar(self._prompt(project_dir))
        assert 'the scenes this pass revises are marked' in cal
        assert 'Add or change a span only where the pass needs to' in cal
        lines = [l for l in cal.splitlines() if ': day ' in l]
        assert lines == ['act1-sc01: day 1, morning',
                         'act1-sc02: day 1, evening  <- in this pass',
                         'new-x1: day 2, afternoon',
                         'act2-sc01: day 3, morning  <- in this pass',
                         'act2-sc02: day 3, afternoon',
                         'act2-sc03: day 4, evening']

    def test_the_lines_are_the_checkers(self, project_dir):
        _set(project_dir, 'act1-sc01', time_mode='summary')
        _set(project_dir, 'new-x1', status='cut')
        cal = _calendar(self._prompt(project_dir))
        lines = [l.removesuffix('  <- in this pass') for l in cal.split('\n\n')[2].splitlines()]
        assert lines == checker.Book.load(project_dir, SCENE).calendar().splitlines()

    def test_a_cut_scene_in_the_pass_stays(self, project_dir):
        _set(project_dir, 'act2-sc01', status='cut')
        assert 'act2-sc01: day 3, morning  <- in this pass' in _calendar(self._prompt(project_dir))

    def test_it_sits_after_the_intent_beats_and_before_the_scenes(self, project_dir):
        prompt = self._prompt(project_dir)
        assert prompt.index('## Intent-Beat Protection') < prompt.index(HEADING) \
            < prompt.index('## Scene Content')

    @pytest.mark.parametrize('coaching', ['coach', 'strict'])
    def test_guides_get_it_too(self, project_dir, coaching):
        assert HEADING in self._prompt(project_dir, coaching=coaching)

    def test_scenes_with_no_day_are_named(self, project_dir):
        _set(project_dir, 'new-x1', timeline_day='', time_of_day='')
        assert _calendar(self._prompt(project_dir)).rstrip().endswith(
            'No day in scenes.csv (name no span counted from these): new-x1')

    def test_no_days_or_no_known_scene_gets_none(self, project_dir):
        from storyforge.prompts import revision_calendar_block
        assert revision_calendar_block(['not-a-scene'], project_dir, 'p') == ''
        for sid in checker.Book.load(project_dir, SCENE).order:
            _set(project_dir, sid, timeline_day='')
        assert HEADING not in self._prompt(project_dir)

    def test_warnings_go_to_stderr_never_into_the_prompt(self, project_dir, capsys):
        # build-prompt's stdout is the prompt; a WARNING there would be sent
        _set(project_dir, 'act2-sc02', timeline_day='Day 3')
        prompt = self._prompt(project_dir)
        out, err = capsys.readouterr()
        assert 'WARNING' not in prompt and 'WARNING' not in out
        assert ("WARNING: continuity (revision calendar): scenes.csv: act2-sc02: "
                "timeline_day 'Day 3' is not a whole number") in err

    def test_the_build_prompt_subprocess_keeps_them_apart(self, project_dir):
        import subprocess
        import sys
        from conftest import PLUGIN_DIR as plugin
        _set(project_dir, 'act2-sc02', time_mode='flashback')
        result = subprocess.run(
            [sys.executable, '-m', 'storyforge.revision', 'build-prompt', 'continuity',
             'Fix continuity', self.SCOPE, project_dir, '--api-mode'],
            capture_output=True, text=True, check=True,
            env={**os.environ, 'PYTHONPATH': os.path.join(plugin, 'scripts', 'lib', 'python')})
        assert HEADING in result.stdout and 'WARNING' not in result.stdout
        assert "time_mode 'flashback'" in result.stderr

    def test_revise_logs_what_comes_back(self, capsys):
        from storyforge.cmd_revise import _log_prompt_warnings
        _log_prompt_warnings('WARNING: p (revision calendar): x\nnoise\n')
        out = capsys.readouterr().out
        assert 'WARNING: p (revision calendar): x' in out and 'noise' not in out


class TestTheHeaderSaysWhatIsListed:
    """The calendar lists every scene with a day or a time of day, so its
    header doesn't say "each dated scene's day" (rethink status, the
    calendar's 5-agent review): the drafting, revision and checker
    calendars all name time-only scenes too."""

    WORDS = "The story's calendar (scenes.csv): each scene with a day or a time of day"

    def test_drafting(self, project_dir):
        _set(project_dir, 'new-x1', timeline_day='')
        cal = _calendar(_prompt(project_dir))
        assert self.WORDS in cal and 'new-x1: afternoon' in cal
        assert 'dated scene' not in cal

    def test_revision(self, project_dir):
        from storyforge.revision import build_revision_prompt
        cal = _calendar(build_revision_prompt('continuity', 'Fix continuity', SCENE,
                                              project_dir, api_mode=True))
        assert self.WORDS in cal and 'dated scene' not in cal

    def test_the_checker(self, project_dir):
        book = checker.Book.load(project_dir, SCENE)
        note = checker._calendar_note(book, SCENE)
        assert "gives each scene's day and time of day" in note
        assert 'where it has them' in note and 'dated scene' not in note
