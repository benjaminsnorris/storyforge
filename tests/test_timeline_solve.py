"""The calendar computed in code from the cues (#351): the model labels, code counts."""

import csv
import os

import pytest

from storyforge.timeline_solve import Link, anchor_for, link_for, run_solve, solve


def _items(*rows):
    """(id, relation, gap, anchor, date, span) rows as scene_items."""
    out = []
    for row in rows:
        sid, relation, gap, anchor, date, span = (list(row) + [''] * 6)[:6]
        out.append({'id': sid, 'duration': '', 'cues': {
            'relation': relation, 'gap': gap, 'anchor': anchor, 'date': date, 'span': span}})
    return out


class TestLinks:
    def test_continues_is_the_same_day(self):
        assert link_for('continues', '') == Link(0, 0, 0, True)

    def test_a_counted_gap_holds_with_a_little_slack(self):
        assert link_for('later', 'the next morning') == Link(1, 1, 1, True)
        three = link_for('later', 'three weeks')
        assert three.counted and three.pref == 21 and three.lo < 21 < three.hi <= 25

    def test_vague_gaps_are_ranges(self):
        weeks = link_for('later', 'some weeks later')
        assert not weeks.counted and weeks.lo < weeks.pref < weeks.hi
        # "the summer" is a season, not a year (Plastic Age)
        assert link_for('later', 'the summer').hi < 365

    def test_anchors(self):
        assert anchor_for({'date': 'XXXX-07-04'}).first == 184
        assert anchor_for({'anchor': 'early in May'}).words == 'early May'
        assert anchor_for({'anchor': 'a warm evening'}) is None
        assert anchor_for({'date': '1922-07-04'}).year_date.year == 1922


class TestSolve:
    def test_counted_gaps_count(self):
        s = solve(_items(('a', 'unclear'), ('b', 'later', 'the next morning'),
                         ('c', 'later', 'three days'), ('d', 'continues')))
        assert [s.days[x] for x in 'abcd'] == [1, 2, 5, 5]
        assert s.conflicts == []

    def test_a_month_anchor_stretches_the_vague_gap_not_the_counted_one(self):
        """F-071: the prom "early in May" landed in January. The vague gap
        before it takes up the distance; the stated "the next day" doesn't."""
        s = solve(_items(('opening', 'unclear', '', '', 'XXXX-09-20'),
                         ('later-on', 'later', 'some months later'),
                         ('prom', 'later', 'the next day', 'early in May')))
        assert s.days['prom'] - s.days['later-on'] == 1
        # September 20 + the days to early May
        assert 222 <= s.days['prom'] - 1 <= 232
        assert s.conflicts == []

    def test_an_anchor_no_gap_can_reach_is_a_conflict(self):
        s = solve(_items(('a', 'unclear', '', '', 'XXXX-03-01'),
                         ('b', 'later', 'the next day', '', 'XXXX-06-01')))
        assert s.days['b'] == 2
        assert [sid for sid, _m in s.conflicts] == ['b']

    def test_stated_years_fix_the_distance(self):
        s = solve(_items(('a', 'unclear', '', '', '1920-01-10'),
                         ('b', 'later', 'years later', '', '1922-01-10')))
        assert s.days['b'] - s.days['a'] == 731   # 1920 is a leap year

    def test_flashbacks_frames_and_visions(self):
        s = solve(_items(('frame', 'frame'), ('a', 'earlier'), ('b', 'later', 'a week'),
                         ('memory', 'earlier', 'five years'), ('memory2', 'continues'),
                         ('back', 'later', 'the next morning'), ('dream', 'vision')))
        # after a frame, "earlier" is the story starting, not a flashback
        assert s.days['a'] == 1 and s.modes['a'] == 'scene'
        assert s.days['b'] == 8
        assert s.days['memory'] == 8 - 5 * 365 and s.days['memory2'] == s.days['memory']
        assert s.days['back'] == 9
        assert s.days['dream'] == 9 and s.modes['dream'] == 'vision'
        assert s.modes['frame'] == 'frame' and s.days['frame'] > 9


def test_run_solve_writes_the_proposal_and_leaves_scenes_alone(project_dir):
    from storyforge.timeline import write_cues
    scenes = os.path.join(project_dir, 'reference', 'scenes.csv')
    with open(scenes) as f:
        before = f.read()
    ids = [r['id'] for r in csv.DictReader(open(scenes), delimiter='|')]
    write_cues(project_dir, {sid: {'id': sid, 'relation': 'later', 'gap': 'the next day'}
                             for sid in ids})
    result = run_solve(project_dir)
    assert result['solved'] >= 1
    with open(scenes) as f:
        assert f.read() == before
    with open(os.path.join(project_dir, 'working', 'timeline-solved.csv')) as f:
        assert f.readline().startswith('id|current_day|solved_day|mode|basis|conflict')


EVALS = os.path.expanduser('~/Developer/evals/projects')
BOOKS = ['age-of-innocence', 'around-the-world', 'brimming-cup', 'five-weeks-in-a-balloon',
         'gatsby', 'iliad', 'middlemarch', 'odyssey', 'plastic-age', 'pride-and-prejudice',
         'self-control']


@pytest.mark.skipif(not os.path.isdir(EVALS), reason='needs the storyforge-evals projects')
@pytest.mark.parametrize('slug', BOOKS)
def test_every_evals_book_is_placed_from_its_recorded_cues(slug):
    """The recorded cues of each evals book give a day for every scene, and
    the present never steps back."""
    from storyforge.timeline import read_cues, scene_items
    proj = os.path.join(EVALS, slug)
    if not os.path.isfile(os.path.join(proj, 'working', 'timeline-cues.csv')):
        pytest.skip('no recorded cues')
    items = scene_items(proj, read_cues(proj))
    s = solve(items)
    assert set(s.days) == {it['id'] for it in items}
    present = [s.days[it['id']] for it in items if s.basis.get(it['id']) == 'from cues']
    assert present == sorted(present)


class TestLinks351:
    """#351 step 2: the cue read names the scene a stated distance counts
    from, and code counts it (the Iliad's "upon the tenth day")."""

    def test_the_cue_prompt_lists_earlier_scenes_and_asks_for_links(self):
        from storyforge.timeline import build_cue_prompt
        prompt = build_cue_prompt('s3', 'Text.', 'tail', earlier=[('s1', 'Plague'), ('s2', 'Quarrel')])
        assert '## Earlier Scenes (id | title)' in prompt and 's1 | Plague' in prompt
        assert 'TIME_LINK:' in prompt and 'TIME_BOUND:' in prompt
        assert 'nine days after' in prompt      # ordinal days counted as distances

    def test_link_and_bound_parse(self):
        from storyforge.timeline import parse_cues
        from storyforge.timeline_solve import bound_for, link_ref
        cues = parse_cues('TIME_RELATION: later\nTIME_LINK: plague | nine days after\n'
                          'TIME_BOUND: before XXXX-09-29\n')
        assert link_ref(cues) == ('plague', 9)
        assert link_ref({'link': 'x | three days before'}) == ('x', -3)
        assert link_ref({'link': 'x | some time after'}) is None
        b = bound_for(cues)
        assert b.last == 270 and b.first == 211

    def test_a_link_sets_the_day_over_vague_gaps(self):
        """Iliad I: the assembly is "upon the tenth day" of the plague; the
        gaps in between are vague."""
        s = solve(_items(('plague', 'unclear'), ('prayer', 'continues'),
                         ('assembly', 'later')))
        assert s.days['assembly'] == 3        # "later", no gap: a couple of days
        items = _items(('plague', 'unclear'), ('prayer', 'continues'), ('assembly', 'later'))
        items[2]['cues']['link'] = 'plague | nine days after'
        s = solve(items)
        assert s.days['assembly'] == 10 and s.conflicts == []

    def test_a_link_to_a_scene_inside_the_open_stretch(self):
        items = _items(('a', 'unclear'), ('b', 'later', 'some days'), ('c', 'later'),
                       ('d', 'later', 'some weeks', 'early in May'))
        items[2]['cues']['link'] = 'b | twelve days after'
        s = solve(items)
        assert s.days['c'] - s.days['b'] == 12

    def test_a_link_back_past_the_present_is_a_conflict(self):
        items = _items(('a', 'unclear'), ('b', 'later', 'three weeks'), ('c', 'later'))
        items[2]['cues']['link'] = 'a | two days after'
        s = solve(items)
        assert [sid for sid, _m in s.conflicts] == ['c']
        assert s.days['c'] >= s.days['b']


def test_a_told_tale_keeps_its_own_time():
    """#548: a tale told inside a scene (told_by) is placed like a
    flashback, and the story's present goes on from its telling."""
    items = _items(('feast', 'unclear'), ('finnsburh', 'earlier', 'many years'),
                   ('next-day', 'later', 'the next day'))
    items[1]['told_by'] = 'feast'
    items[1]['cues']['relation'] = 'continues'     # read as continuing, but told
    s = solve(items)
    assert s.days['finnsburh'] < s.days['feast']
    assert s.days['next-day'] == s.days['feast'] + 1
