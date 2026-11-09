"""Tests for storyforge.typed_state and storyforge.continuity (#648): typed
records, their extraction (API mocked at `api._api_request`) and file, and
each deterministic check on synthetic books; the `frame` column; the
world table's `speed`; the gate's use of the checks. Every scene, name and
place here is invented for the tests."""

import json
import os
from unittest.mock import patch

import pytest

from storyforge import continuity, gate, typed_state, world_table
from storyforge.checker import CALENDAR
from storyforge.continuity import Book, parse_elapsed
from storyforge.typed_state import Record
from storyforge.world_table import World


# ============================================================================
# Building synthetic books
# ============================================================================

CHARS = {'mara': 'mara', 'mara vell': 'mara', 'oren': 'oren', 'oren tal': 'oren',
         'lise': 'lise', 'jory': 'jory'}
PLACES = {'harbour': 'harbour', 'the harbour': 'harbour', 'mill': 'mill', 'the mill': 'mill',
          'tower': 'tower', 'the tower': 'tower'}


def R(type_, who='', item='', value='', detail='', quote=None, verified=True, origin='prose'):
    return Record(type_, who, item, value, detail,
                  quote if quote is not None else f'{type_} {who} {item} {value}'.strip(),
                  verified=verified, origin=origin)


def make_book(scene, recs, *, scenes=None, rows=None, briefs=None, deaths=None, world=None,
              frame_column=True, forbidden=None, known=None):
    """`scenes`: id → overrides of a row (`timeline_day`, `time_of_day`,
    `pov`, `frame`, `time_mode`, `location`); reading order is the dict's.
    `recs`: id → records, numbered in order."""
    scenes = scenes or {s: {} for s in recs}
    rows_ = {}
    for n, (sid, over) in enumerate(scenes.items()):
        rows_[sid] = {'id': sid, 'seq': str(n + 1), 'timeline_day': str(n + 1),
                      'time_of_day': 'morning', 'pov': 'Mara', 'location': '', **over}
    order = {sid: n for n, sid in enumerate(scenes)}
    book = Book(scene, order, rows_, deaths=list(deaths or []), chars=dict(CHARS),
                places=dict(PLACES), place_names={'harbour': 'Harbour', 'mill': 'Mill',
                                                  'tower': 'Tower'},
                world=world or World(), rows=list(rows or []), briefs=dict(briefs or {}),
                has_frame_column=frame_column, forbidden=dict(forbidden or {}),
                known_names=known)
    for sid, rs in recs.items():
        for n, r in enumerate(rs):
            r.scene_id, r.index = sid, n
        book.records[sid] = rs
    return book


def codes(findings):
    return [f.code for f in findings]


# ============================================================================
# Life and death
# ============================================================================

class TestLife:
    def test_a_dead_character_present_later(self):
        b = make_book('s3', {'s1': [R('alive', 'Oren', value='dead', quote='Oren fell')],
                             's2': [], 's3': [R('at', 'Oren Tal', 'harbour',
                                                quote='Oren waved')]})
        f, _ = continuity.check_life(b)
        assert codes(f) == ['PHY']
        assert f[0].scene_quote == 'Oren waved' and f[0].established_scene == 's1'
        assert f[0].established_quote == 'Oren fell'
        assert 'died s1 (day 1, morning)' in f[0].explanation
        assert f[0].explanation.startswith('(typed state, life)')

    def test_a_registry_death(self):
        b = make_book('s2', {'s1': [], 's2': [R('at', 'Oren', quote='Oren waved')]},
                      deaths=[Record('alive', 'oren', value='dead', scene_id='s1',
                                     quote='death_scene s1', origin='registry', index=10 ** 6)])
        f, _ = continuity.check_life(b)
        assert f[0].established_scene == 'characters.csv'
        assert 'death_scene s1' in f[0].explanation

    def test_present_in_the_scene_of_a_registry_death_is_fine(self):
        b = make_book('s1', {'s1': [R('at', 'Oren', quote='Oren waved')]},
                      deaths=[Record('alive', 'oren', value='dead', scene_id='s1',
                                     origin='registry', index=10 ** 6)])
        assert continuity.check_life(b) == ([], [])

    def test_a_flashback_keeps_its_earlier_day(self):
        b = make_book('s3', {'s1': [], 's2': [R('alive', 'Oren', value='dead')],
                             's3': [R('at', 'Oren')]},
                      scenes={'s1': {'timeline_day': '1'}, 's2': {'timeline_day': '5'},
                              's3': {'timeline_day': '2'}})
        assert continuity.check_life(b)[0] == []

    @pytest.mark.parametrize('over', [{'frame': 'dream'}, {'frame': 'Ghost '},
                                      {'time_mode': 'vision'}, {'frame': 'memory'}])
    def test_a_scene_off_the_present_is_exempt(self, over):
        b = make_book('s2', {'s1': [R('alive', 'Oren', value='dead')], 's2': [R('at', 'Oren')]},
                      scenes={'s1': {}, 's2': over})
        assert continuity.check_life(b)[0] == []

    def test_an_unknown_frame_value_is_the_present(self):
        b = make_book('s2', {'s1': [R('alive', 'Oren', value='dead')], 's2': [R('at', 'Oren')]},
                      scenes={'s1': {}, 's2': {'frame': 'flashback'}})
        assert codes(continuity.check_life(b)[0]) == ['PHY']

    def test_without_a_frame_column_it_is_reported_and_says_so(self):
        b = make_book('s2', {'s1': [R('alive', 'Oren', value='dead')], 's2': [R('at', 'Oren')]},
                      frame_column=False)
        f, _ = continuity.check_life(b)
        assert 'frame column (scenes.csv has none' in f[0].explanation

    def test_a_death_in_a_dream_is_not_a_death(self):
        b = make_book('s2', {'s1': [R('alive', 'Oren', value='dead')], 's2': [R('at', 'Oren')]},
                      scenes={'s1': {'frame': 'dream'}, 's2': {}})
        assert continuity.check_life(b)[0] == []

    def test_brought_back(self):
        b = make_book('s3', {'s1': [R('alive', 'Oren', value='dead')],
                             's2': [R('alive', 'Oren', value='alive')], 's3': [R('at', 'Oren')]})
        assert continuity.check_life(b)[0] == []

    def test_within_one_scene_order_counts(self):
        before = make_book('s1', {'s1': [R('at', 'Oren'), R('alive', 'Oren', value='dead')]})
        after = make_book('s1', {'s1': [R('alive', 'Oren', value='dead'),
                                        R('at', 'Oren', quote='Oren spoke again')]})
        assert continuity.check_life(before)[0] == []
        f, _ = continuity.check_life(after)
        assert 'earlier in this scene' in f[0].explanation

    def test_a_misquoted_record_makes_no_finding(self):
        b = make_book('s2', {'s1': [R('alive', 'Oren', value='dead')],
                             's2': [R('at', 'Oren', verified=False)]})
        assert continuity.check_life(b)[0] == []

    def test_one_finding_per_person(self):
        b = make_book('s2', {'s1': [R('alive', 'Oren', value='dead')],
                             's2': [R('at', 'Oren', 'harbour'), R('at', 'Oren', 'mill')]})
        assert len(continuity.check_life(b)[0]) == 1


# ============================================================================
# Possession
# ============================================================================

class TestPossession:
    def test_two_hands_at_once(self):
        b = make_book('s2', {'s1': [R('holds', 'Mara', 'the brass key', 'has', quote='Mara key')],
                             's2': [R('holds', 'Oren', 'brass key', 'has', quote='Oren key')]})
        f, _ = continuity.check_possession(b)
        assert codes(f) == ['PHY'] and f[0].established_scene == 's1'
        assert 'Mara holds brass key' in f[0].explanation

    def test_given_on_is_fine(self):
        b = make_book('s2', {'s1': [R('holds', 'Mara', 'brass key', 'gives', 'Oren')],
                             's2': [R('holds', 'Oren', 'brass key', 'has')]})
        assert continuity.check_possession(b)[0] == []

    def test_held_after_giving_it_away(self):
        b = make_book('s2', {'s1': [R('holds', 'Mara', 'brass key', 'gives', 'a stranger')],
                             's2': [R('holds', 'Mara', 'brass key', 'has')]})
        f, _ = continuity.check_possession(b)
        assert 'Mara gave away brass key s1' in f[0].explanation

    def test_used_after_it_was_destroyed(self):
        b = make_book('s2', {'s1': [R('holds', 'Mara', 'the letter', 'destroyed')],
                             's2': [R('holds', 'Mara', 'letter', 'has')]})
        assert 'destroyed' in continuity.check_possession(b)[0][0].explanation

    def test_a_later_fact_moves_it(self):
        b = make_book('s3', {'s1': [R('holds', 'Mara', 'brass key', 'loses')],
                             's2': [R('holds', 'Oren', 'brass key', 'gets')],
                             's3': [R('holds', 'Oren', 'brass key', 'has')]})
        assert continuity.check_possession(b)[0] == []

    def test_from_a_place_to_a_hand(self):
        b = make_book('s2', {'s1': [R('holds', 'the shelf', 'brass key', 'has')],
                             's2': [R('holds', 'Mara', 'brass key', 'has')]})
        assert continuity.check_possession(b)[0] == []

    def test_only_this_scene_is_judged(self):
        b = make_book('s3', {'s1': [R('holds', 'Mara', 'brass key', 'has')],
                             's2': [R('holds', 'Oren', 'brass key', 'has')], 's3': []})
        assert continuity.check_possession(b)[0] == []

    def test_a_stage_sheet_hand_counts(self):
        b = make_book('s2', {'s1': [R('holds', 'Mara', 'brass key', 'has')], 's2': []})
        sheet = [Record('holds', 'Oren', 'brass key', 'has', quote='Oren gripped the key',
                        scene_id='s2', origin='stage-sheet', index=0)]
        f, _ = continuity.check_possession(b, sheet)
        assert f[0].scene_quote == 'Oren gripped the key'


# ============================================================================
# Knowledge
# ============================================================================

def fact(fid, scene, known_by, statement='The mill is flooded', quote='the mill flooded'):
    return {'id': fid, 'type': 'knowledge', 'status': 'binding', 'scene_id': scene,
            'known_by': known_by, 'statement': statement, 'quote': quote}


class TestKnowledge:
    def test_acting_on_a_fact_before_learning_it(self):
        b = make_book('s2', {'s1': [], 's2': [R('knows', 'Mara', 'mill-flooded', 'uses',
                                                quote='Mara avoided the mill')], 's3': []},
                      rows=[fact('mill-flooded', 's3', 'mara')])
        f, _ = continuity.check_knowledge(b)
        assert codes(f) == ['KNO'] and f[0].fact_id == 'mill-flooded'
        assert f[0].established_scene == 's3' and f[0].established_quote == 'the mill flooded'
        assert 'before learning it' in f[0].explanation

    def test_learned_earlier_by_a_brief(self):
        b = make_book('s2', {'s1': [], 's2': [R('knows', 'Mara', 'mill-flooded', 'uses')],
                             's3': []},
                      rows=[fact('mill-flooded', 's3', 'mara')],
                      briefs={'s1': {'knowledge_out': 'mill-flooded'}})
        assert continuity.check_knowledge(b)[0] == []

    def test_a_brief_of_someone_else_s_pov_does_not_teach_her(self):
        b = make_book('s2', {'s1': [], 's2': [R('knows', 'Mara', 'mill-flooded', 'uses')],
                             's3': []},
                      scenes={'s1': {'pov': 'Oren'}, 's2': {}, 's3': {}},
                      rows=[fact('mill-flooded', 's3', 'mara')],
                      briefs={'s1': {'knowledge_out': 'mill-flooded'}})
        assert codes(continuity.check_knowledge(b)[0]) == ['KNO']

    def test_learned_earlier_in_the_scene(self):
        b = make_book('s2', {'s2': [R('knows', 'Mara', 'mill-flooded', 'learns'),
                                    R('knows', 'Mara', 'mill-flooded', 'uses')], 's3': []},
                      rows=[fact('mill-flooded', 's3', 'mara')])
        assert continuity.check_knowledge(b)[0] == []

    def test_backstory_is_always_known(self):
        b = make_book('s2', {'s2': [R('knows', 'Mara', 'mill-flooded', 'uses')]},
                      rows=[fact('mill-flooded', '', 'Mara Vell')])
        assert continuity.check_knowledge(b)[0] == []

    def test_never_learned(self):
        b = make_book('s2', {'s1': [], 's2': [R('knows', 'Mara', 'mill-flooded', 'uses')]},
                      rows=[fact('mill-flooded', 's1', 'oren')])
        f, _ = continuity.check_knowledge(b)
        assert 'which no scene, brief or ledger row has Mara learn' in f[0].explanation
        assert f[0].established_scene == 's1'

    def test_an_unknown_fact_id_is_a_note(self):
        b = make_book('s2', {'s2': [R('knows', 'Mara', 'no-such-fact', 'uses')]})
        f, notes = continuity.check_knowledge(b)
        assert f == [] and 'no-such-fact' in notes[0]

    def test_offered_facts(self):
        rows = [fact('later', 's3', 'mara'), fact('earlier', 's1', 'mara'),
                fact('others', 's1', 'oren'), fact('nobody', 's1', ''),
                fact('here', 's2', 'mara')]
        b = make_book('s2', {'s1': [], 's2': [], 's3': []}, rows=rows)
        offered, cut = continuity.offered_facts(b)
        assert [fid for fid, _ in offered] == ['later', 'others'] and cut == 0

    def test_no_facts_offered_for_a_narrator(self):
        b = make_book('s1', {'s1': []}, scenes={'s1': {'pov': 'narrator'}},
                      rows=[fact('x', 's1', 'oren')])
        assert continuity.offered_facts(b) == ([], 0)

    def test_offered_facts_are_capped(self, monkeypatch):
        monkeypatch.setattr(continuity, 'MAX_OFFERED_FACTS', 1)
        b = make_book('s1', {'s1': []}, rows=[fact('a', 's1', 'oren'), fact('b', 's1', 'jory')])
        offered, cut = continuity.offered_facts(b)
        assert len(offered) == 1 and cut == 1


# ============================================================================
# Place and travel
# ============================================================================

class TestPlace:
    def _two(self, here, there, time2='morning'):
        return make_book('s1', {'s1': [R('at', 'Mara', here, quote='Mara here')],
                                's2': [R('at', 'Mara', there, quote='Mara there')]},
                         scenes={'s1': {'timeline_day': '3'},
                                 's2': {'timeline_day': '3', 'time_of_day': time2}})

    def test_two_places_in_one_slot(self):
        f, _ = continuity.check_place(self._two('the harbour', 'Mill'))
        assert codes(f) == ['PHY'] and f[0].established_scene == 's2'
        assert 'at Harbour here and at Mill in s2, both day 3, morning' in f[0].explanation

    def test_the_same_place_is_fine(self):
        assert continuity.check_place(self._two('harbour', 'the harbour'))[0] == []

    def test_another_time_of_day_is_another_slot(self):
        f, _ = continuity.check_place(self._two('harbour', 'mill', 'evening'))
        assert [x for x in f if '(typed state, place)' in x.explanation] == []

    def test_a_place_no_registry_names_is_a_note(self):
        f, notes = continuity.check_place(self._two('the old quarry', 'mill'))
        assert f == [] and 'locations.csv doesn\'t name' in notes[0]

    def test_the_scene_s_one_location_stands_in(self):
        b = make_book('s1', {'s1': [R('at', 'Mara', '')], 's2': [R('at', 'Mara', 'mill')]},
                      scenes={'s1': {'location': 'Harbour'}, 's2': {'timeline_day': '1'}})
        assert codes(continuity.check_place(b)[0]) == ['PHY']

    def _travel(self, day2, world):
        return make_book('s2', {'s1': [R('at', 'Mara', 'harbour', quote='at the harbour')],
                                's2': [R('at', 'Mara', 'tower', quote='at the tower')]},
                         scenes={'s1': {'timeline_day': '1', 'time_of_day': 'evening'},
                                 's2': {'timeline_day': day2, 'time_of_day': 'morning'}},
                         world=world)

    def _world(self, speed=True):
        w = World(distances={frozenset(('harbour', 'tower')): 100000.0})
        if speed:
            w.speeds['on foot'] = 40000.0
        return w

    def test_travel_too_fast(self):
        f, _ = continuity.check_place(self._travel('2', self._world()))
        assert codes(f) == ['WLD'] and f[0].established_scene == 's1'
        assert '100000 m from Harbour' in f[0].explanation and '2.5 day(s)' in f[0].explanation

    def test_travel_with_time_enough(self):
        assert continuity.check_place(self._travel('5', self._world()))[0] == []

    def test_no_speed_is_a_note(self):
        f, notes = continuity.check_place(self._travel('2', self._world(speed=False)))
        assert f == [] and notes == ['travel: 1 move(s) between places not checked '
                                     '(world.csv gives no speed)']


# ============================================================================
# Time
# ============================================================================

class TestParseElapsed:
    @pytest.mark.parametrize('phrase,low,high,direction', [
        ('three days ago', 3, 3, 'past'),
        ('Three Days Ago', 3, 3, 'past'),
        ('ten days since', 9, 11, 'past'),
        ('nine nights later', 8, 10, 'past'),
        ('in two days', 2, 2, 'future'),
        ('a week ago', 6, 8, 'past'),
        ('a fortnight since', 13, 15, 'past'),
        ('the tenth day', 9, 9, 'past'),
        ('on the 3rd morning', 2, 2, 'past'),
        ('the second week', 7, 13, 'past'),
        ('twelve hours ago', 0, 1, 'past'),
        ('2 months later', 54, 66, 'past'),
        ('a year ago', 350, 380, 'past'),
    ])
    def test_spans(self, phrase, low, high, direction):
        span, why = parse_elapsed(phrase)
        assert why == '' and (span.low, span.high, span.direction) == (low, high, direction)

    @pytest.mark.parametrize('phrase,why', [
        ('a few days ago', 'vague'),
        ('for nine days', 'which way'),
        ('long ago', 'no number'),
        ('several weeks later', 'vague'),
    ])
    def test_what_it_cannot_read_it_says(self, phrase, why):
        span, reason = parse_elapsed(phrase)
        assert span is None and why in reason


class TestTime:
    def _book(self, phrase, anchor='s1', day1='1', day2='4'):
        return make_book('s2', {'s1': [], 's2': [R('elapsed', item=anchor, value=phrase,
                                                   quote=f'it was {phrase}')]},
                         scenes={'s1': {'timeline_day': day1}, 's2': {'timeline_day': day2}})

    def test_a_span_that_fits(self):
        assert continuity.check_time(self._book('three days ago')) == ([], [])

    def test_a_span_that_breaks_the_calendar(self):
        f, _ = continuity.check_time(self._book('three days ago', day2='9'))
        assert codes(f) == ['TIM'] and f[0].established_scene == CALENDAR
        assert f[0].established_quote == 's1: day 1, morning'
        assert 'this scene is day 9, 8 day(s) after it' in f[0].explanation

    def test_the_future(self):
        b = make_book('s1', {'s1': [R('elapsed', item='s2', value='in two days')], 's2': []},
                      scenes={'s1': {'timeline_day': '1'}, 's2': {'timeline_day': '5'}})
        assert codes(continuity.check_time(b)[0]) == ['TIM']

    def test_unread_unanchored_and_undated_are_notes(self):
        b = make_book('s2', {'s1': [], 's2': [
            R('elapsed', item='s1', value='a few days ago'),
            R('elapsed', item='', value='ten years ago'),
            R('elapsed', item='s1', value='two days ago')]},
            scenes={'s1': {'timeline_day': ''}, 's2': {'timeline_day': '4'}})
        f, notes = continuity.check_time(b)
        assert f == [] and len(notes) == 3
        assert 'a vague count' in notes[0] and 'no scene' in notes[1]
        assert 'without a timeline_day' in notes[2]


# ============================================================================
# Injury
# ============================================================================

class TestInjury:
    def _book(self, injury='serious', use='full', side_i='left', side_u='left', between=(),
              days=('1', '2')):
        return make_book('s3', {
            's1': [R('injury', 'Oren', 'arm', injury, side_i, quote='the blade cut his arm')],
            's2': list(between),
            's3': [R('uses', 'Oren', 'arm', use, side_u, quote='he heaved the beam up')]},
            scenes={'s1': {'timeline_day': days[0]}, 's2': {}, 's3': {'timeline_day': days[1]}})

    def test_full_use_of_an_injured_part(self):
        f, _ = continuity.check_injury(self._book())
        assert codes(f) == ['PHY'] and f[0].established_quote == 'the blade cut his arm'
        assert 'left arm at full strength, but it was seriously injured' in f[0].explanation

    @pytest.mark.parametrize('kw', [{'use': 'impaired'}, {'injury': 'minor'},
                                    {'side_u': 'right'},
                                    {'between': [R('injury', 'Oren', 'left arm', 'healed')]},
                                    {'days': ('1', '60')}])
    def test_not_a_finding(self, kw):
        assert continuity.check_injury(self._book(**kw))[0] == []

    def test_a_disabling_injury_lasts(self):
        assert len(continuity.check_injury(self._book(injury='disabling',
                                                      days=('1', '300')))[0]) == 1

    def test_the_side_can_be_in_the_part(self):
        b = make_book('s2', {'s1': [R('injury', 'Oren', 'right hand', 'serious')],
                             's2': [R('uses', 'Oren', 'his hands', 'full', 'right')]})
        assert len(continuity.check_injury(b)[0]) == 1

    def test_no_side_against_a_one_sided_injury_is_a_note(self):
        f, notes = continuity.check_injury(self._book(side_u=''))
        assert f == [] and 'no side given' in notes[0]

    def test_offered_injuries(self):
        b = self._book()
        b.scene_id = 's3'
        lines, cut = continuity.offered_injuries(b)
        assert lines == ['Oren: left arm, serious (since s1)'] and cut == 0


# ============================================================================
# Names
# ============================================================================

class TestNames:
    def test_a_forbidden_name(self):
        prose = 'The old priest prayed to Jupiter for rain. Mara laughed.'
        b = make_book('s1', {'s1': []}, forbidden={'Jupiter': 'storyforge.yaml'})
        f, _ = continuity.check_names(b, prose)
        assert codes(f) == ['WLD'] and f[0].scene_quote == 'The old priest prayed to Jupiter for rain'
        assert f[0].established_scene == 'storyforge.yaml'

    def test_counts_and_whole_words(self):
        prose = 'Jupiter, Jupiter! The Jupiterian moons.'
        b = make_book('s1', {'s1': []}, forbidden={'Jupiter': 'name-map.csv'})
        f, _ = continuity.check_names(b, prose)
        assert '(2 times in the scene)' in f[0].explanation

    def test_a_sentence_start_that_is_also_a_word(self):
        prose = 'Will you come? He said he will.'
        b = make_book('s1', {'s1': []}, forbidden={'Will': 'name-map.csv'})
        assert continuity.check_names(b, prose)[0] == []

    def test_a_forbidden_name_the_registry_allows_is_a_note(self):
        b = make_book('s1', {'s1': []}, forbidden={'Oren': 'storyforge.yaml'},
                      known={'oren'})
        f, notes = continuity.check_names(b, 'Oren ran.')
        assert f == [] and 'also a name the character registry gives' in notes[0]

    def test_unknown_names_are_advisory(self):
        b = make_book('s1', {'s1': [R('named', 'Mara', value='Mara Vell'),
                                    R('named', 'stranger', value='Tobin Rusk',
                                      quote='Tobin Rusk bowed')]},
                      known={'mara', 'vell', 'mara vell'})
        f, notes = continuity.check_names(b, '')
        assert f == [] and notes == ['advisory: names no registry, ledger subject or name map '
                                     'knows: Tobin Rusk ("Tobin Rusk bowed")']

    def test_no_registry_is_a_note(self):
        b = make_book('s1', {'s1': [R('named', 'Mara', value='Mara')]})
        assert 'characters.csv is missing' in continuity.check_names(b, '')[1][0]

    def test_forbidden_names_from_yaml_and_a_name_map(self, project_dir, monkeypatch):
        from storyforge import source
        with open(os.path.join(project_dir, 'storyforge.yaml'), 'a') as f:
            f.write('\ncontinuity:\n  forbidden_names: "Jupiter; Juno"\n')
        path = os.path.join(project_dir, 'reference', 'name-map.csv')
        with open(path, 'w') as f:
            f.write('|'.join(source.NAME_MAP_COLUMNS) + '\n'
                    'ulix|odys|Ulix|Odys\nhekt|hekt|Hekt|Hekt\n')
        cfg = source.SourceConfig(projects=(source.SourceProject('src', '../src'),),
                                  name_map='reference/name-map.csv')
        monkeypatch.setattr(source, 'read_config', lambda d: cfg)
        found, notes = continuity.forbidden_names(project_dir)
        assert found == {'Ulix': 'name-map.csv', 'Jupiter': 'storyforge.yaml',
                         'Juno': 'storyforge.yaml'} and notes == []


# ============================================================================
# Geography and sky
# ============================================================================

class TestSky:
    def _book(self):
        return make_book('s1', {'s1': []}, world=World(directions={'kesh': 'east',
                                                                    'the sea': 'west'}))

    def test_the_sun_setting_behind_an_eastern_landmark(self):
        prose = 'At evening the sun went down behind Kesh, red as a coal.'
        f, _ = continuity.check_sky(self._book(), prose)
        assert codes(f) == ['WLD'] and f[0].scene_quote == 'the sun went down behind Kesh'
        assert f[0].established_scene == 'world.csv'

    def test_rising_over_it_is_fine(self):
        assert continuity.check_sky(self._book(), 'The sun rose over Kesh.') == ([], [])

    def test_a_compass_word(self):
        f, _ = continuity.check_sky(self._book(), 'That day the sun rose in the west.')
        assert len(f) == 1

    def test_an_unknown_landmark_is_a_note_a_common_noun_nothing(self):
        f, notes = continuity.check_sky(self._book(),
                                        'The sun set behind Varn. The sun set behind the hills.')
        assert f == [] and notes == ['sky: 1 phrase(s) about the sun at a place world.csv '
                                     'doesn\'t give a direction for, not checked: "The sun set '
                                     'behind Varn" (Varn is not in world.csv)']

    def test_a_dream_is_not_checked(self):
        b = make_book('s1', {'s1': []}, scenes={'s1': {'frame': 'dream'}},
                      world=World(directions={'kesh': 'east'}))
        assert continuity.check_sky(b, 'the sun went down behind Kesh') == ([], [])


# ============================================================================
# All checks together
# ============================================================================

class TestRunChecks:
    def test_an_off_present_scene_says_only_names_were_checked(self):
        b = make_book('s2', {'s1': [R('alive', 'Oren', value='dead')],
                             's2': [R('at', 'Oren', quote='Oren')]},
                      scenes={'s1': {}, 's2': {'frame': 'ghost'}},
                      forbidden={'Juno': 'storyforge.yaml'})
        f, notes = continuity.run_checks(b, 'Oren came. Juno wept.')
        assert codes(f) == ['WLD'] and 'marked ghost' in notes[0]

    def test_a_finding_whose_quote_is_not_in_the_prose_is_dropped(self):
        b = make_book('s2', {'s1': [R('alive', 'Oren', value='dead')],
                             's2': [R('at', 'Oren', quote='Oren waved')]})
        f, notes = continuity.run_checks(b, 'Something else entirely.')
        assert f == [] and 'dropped' in notes[-1]


# ============================================================================
# The records' file, extraction, and the whole check on a project
# ============================================================================

SCENE, PREV = 'act1-sc02', 'act1-sc01'
PROSE_1 = 'Pell slipped on the ice and lay dead at the foot of the stair.'
PROSE_2 = 'Dorren walked to the study. Pell met him there and spoke of the map.'


def _text(payload, stop='end_turn'):
    return {'stop_reason': stop, 'model': 'claude-haiku-5-5',
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 1, 'output_tokens': 1}}


def rec(type_, who='', item='', value='', detail='', quote=''):
    return {'type': type_, 'who': who, 'item': item, 'value': value, 'detail': detail,
            'quote': quote}


def _write(project_dir, scene, prose):
    with open(os.path.join(project_dir, 'scenes', f'{scene}.md'), 'w', encoding='utf-8') as f:
        f.write(prose)


def _is_state(body):
    props = (body.get('output_config') or {}).get('format', {}).get('schema', {}) \
        .get('properties', {})
    return 'records' in props


class TestFile:
    def test_round_trip_and_current(self, project_dir):
        recs = [Record('at', 'Pell', 'study', quote='Pell met him')]
        typed_state.write_state(project_dir, SCENE, PROSE_2, recs, model='m')
        _write(project_dir, SCENE, PROSE_2)
        got, why = typed_state.current(project_dir, SCENE)
        assert why == '' and [(r.type, r.who, r.item) for r in got] == [('at', 'Pell', 'study')]
        _write(project_dir, SCENE, PROSE_2 + ' More.')
        got, why = typed_state.current(project_dir, SCENE)
        assert got is None and why == 'its typed state is of earlier prose'

    def test_a_bad_file_says_why(self, project_dir):
        path = typed_state.state_path(project_dir, SCENE)
        os.makedirs(os.path.dirname(path))
        with open(path, 'w') as f:
            f.write('{"format": 9}')
        _write(project_dir, SCENE, PROSE_2)
        got, why = typed_state.current(project_dir, SCENE)
        assert got is None and 'format is not 1' in why

    def test_registry_deaths(self, project_dir):
        path = os.path.join(project_dir, 'reference', 'characters.csv')
        with open(path) as f:
            text = f.read()
        with open(path, 'w') as f:
            f.write(text.replace('pell|Pell||minor|', f'pell|Pell||minor|{PREV}'))
        deaths = typed_state.registry_deaths(project_dir)
        assert [(d.who, d.scene_id, d.origin) for d in deaths] == [('pell', PREV, 'registry')]

    def test_sheet_holdings_read_a_current_sheet(self, project_dir):
        from storyforge import stage_sheet
        prose = 'Pell took the brass key in his right hand.'
        _write(project_dir, SCENE, prose)
        stage_sheet.write_sheet(project_dir, {
            'format': 1, 'scene_id': SCENE, 'prose_sha256': stage_sheet.prose_hash(prose),
            'opening': [], 'end': [], 'beats': [{'quote': 'Pell took the brass key', 'set': [
                {'who': 'Pell', 'field': 'hand_right', 'item': '', 'value': 'the brass key',
                 'quote': 'Pell took the brass key'}]}]})
        got, why = typed_state.sheet_holdings(project_dir, SCENE, {'brass key'})
        assert why == '' and [(r.who, r.value, r.origin) for r in got] == [
            ('Pell', 'has', 'stage-sheet')]
        assert typed_state.sheet_holdings(project_dir, SCENE, {'letter'})[0] == []


class TestCheckContinuity:
    def _run(self, project_dir, records, prose=PROSE_2, calls=None, **kw):
        calls = calls if calls is not None else []

        def fake(path, body, **k):
            assert _is_state(body)
            calls.append(body['messages'][0]['content'])
            return _text({'records': records}) if not isinstance(records, str) \
                else _text({'nope': 1})
        _write(project_dir, SCENE, prose)
        with patch('storyforge.api._api_request', side_effect=fake):
            return continuity.check_continuity(project_dir, SCENE, model='m', **kw)

    def test_a_dead_man_speaks(self, project_dir):
        _write(project_dir, PREV, PROSE_1)
        typed_state.write_state(project_dir, PREV, PROSE_1, [
            Record('alive', 'Pell', value='dead', quote='lay dead at the foot of the stair')])
        r = self._run(project_dir, [rec('at', 'Pell', 'the study', quote='Pell met him there')])
        assert r.extracted and codes(r.findings) == ['PHY']
        assert r.findings[0].established_scene == PREV
        assert os.path.isfile(typed_state.state_path(project_dir, SCENE))

    def test_unchanged_prose_reads_its_file_again(self, project_dir):
        self._run(project_dir, [rec('at', 'Pell', 'the study', quote='Pell met him there')])
        calls = []
        r = self._run(project_dir, [], calls=calls)
        assert calls == [] and not r.extracted and len(r.records) == 1

    def test_misquotes_and_off_schema_records_are_noted(self, project_dir):
        r = self._run(project_dir, [rec('at', 'Pell', 'study', quote='not in the scene'),
                                    rec('holds', 'Pell', 'map', value='maybe', quote='map')])
        assert any('off the schema' in n and 'maybe' in n for n in r.notes)
        assert any('1 of 1 record(s) quote words not in the scene' in n for n in r.notes)

    def test_an_earlier_scene_without_state_is_said(self, project_dir):
        _write(project_dir, PREV, PROSE_1)
        r = self._run(project_dir, [])
        assert any('earlier scene(s) with prose have no typed state' in n and PREV in n
                   for n in r.notes)

    def test_the_prompt_offers_facts_calendar_and_cast(self, project_dir):
        from storyforge import ledger
        rows = ledger.load(project_dir)
        rows.append({**{c: '' for c in ledger.COLUMNS}, 'id': 'map-is-forged',
                     'type': 'knowledge', 'status': 'binding', 'scene_id': 'act2-sc01',
                     'known_by': 'dorren-hayle', 'statement': 'The map was forged',
                     'origin': 'prose', 'mutable': 'state'})
        ledger.write_ledger(ledger.ledger_path(project_dir), rows)
        calls = []
        self._run(project_dir, [], calls=calls)
        prompt = calls[0]
        assert '- map-is-forged: The map was forged' in prompt
        assert 'act1-sc02: day 1, evening  <- this scene' in prompt
        assert '- Dorren Hayle' in prompt and 'Point of view: Dorren Hayle' in prompt

    def test_a_bad_reply_twice_raises(self, project_dir):
        with pytest.raises(continuity.ContinuityError, match='failed twice'):
            self._run(project_dir, 'bad')

    def test_the_model_is_configurable(self, project_dir, monkeypatch):
        monkeypatch.setenv(typed_state.MODEL_ENV, 'claude-tiny')
        assert typed_state.resolve_model() == 'claude-tiny'
        assert typed_state.resolve_model('given') == 'given'


# ============================================================================
# The gate
# ============================================================================

@pytest.mark.continuity
class TestGate:
    def _gate(self, project_dir, tmp_path, records):
        def fake(path, body, **k):
            if 'tools' in body:
                return _text({'findings': [], 'kept': []})
            if _is_state(body):
                return _text({'records': records})
            schema = (body.get('output_config') or {}).get('format', {}).get('schema', {})
            if 'verdicts' in schema.get('properties', {}):
                return _text({'verdicts': []})
            return _text({'commitments': []})
        _write(project_dir, PREV, PROSE_1)
        typed_state.write_state(project_dir, PREV, PROSE_1, [
            Record('alive', 'Pell', value='dead', quote='lay dead at the foot of the stair')])
        _write(project_dir, SCENE, PROSE_2)
        with patch('storyforge.api._api_request', side_effect=fake):
            return gate.gate_scene(project_dir, SCENE, command='advisor',
                                   log_dir=str(tmp_path / 'logs'), extract_model='m',
                                   check_model='m')

    def test_a_continuity_error_stops_the_scene(self, project_dir, tmp_path):
        result = self._gate(project_dir, tmp_path,
                            [rec('at', 'Pell', 'the study', quote='Pell met him there')])
        assert not result.passed and codes(result.findings) == ['PHY']
        assert any('(typed state, life)' in line for line in gate.report_lines(result))
        assert os.path.isfile(tmp_path / 'logs' / f'gate-state-{SCENE}.json')

    def test_notes_are_reported_and_never_block(self, project_dir, tmp_path):
        result = self._gate(project_dir, tmp_path,
                            [rec('named', 'Pell', value='Pellinor', quote='Pell met him')])
        assert result.passed
        report = '\n'.join(gate.report_lines(result))
        assert 'NOTE (continuity, not checked or advisory): advisory: names' in report

    def test_off_by_default_in_tests_on_by_default_in_the_gate(self):
        assert gate.GATE_CONTINUITY is True


def test_the_conftest_turns_the_checks_off():
    assert gate.GATE_CONTINUITY is False


# ============================================================================
# scenes.csv's frame column, world.csv's speed
# ============================================================================

class TestFrameColumn:
    def test_schema_and_helpers(self):
        from storyforge.elaborate import FRAMES, _FILE_MAP, frame, off_present
        from storyforge.schema import COLUMN_SCHEMA, VALID_FRAMES
        assert 'frame' in _FILE_MAP['scenes.csv'] and VALID_FRAMES == set(FRAMES)
        assert COLUMN_SCHEMA['frame']['type'] == 'enum'
        assert frame({'frame': ' Dream '}) == 'dream' and frame({}) == ''
        assert off_present({'frame': 'memory'}) and off_present({'time_mode': 'frame'})
        assert not off_present({'frame': 'nap'}) and not off_present({})

    def test_validate_reports_a_bad_value(self, project_dir):
        from storyforge.schema import validate_schema
        path = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(path) as f:
            lines = f.read().splitlines()
        lines[0] += '|frame'
        lines[1] += '|flashback'
        lines[2] += '|dream'
        lines[3:] = [l + '|' for l in lines[3:]]
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        result = validate_schema(os.path.join(project_dir, 'reference'), project_dir)
        bad = [e for e in result.get('errors', []) if e.get('column') == 'frame']
        assert [e.get('value') for e in bad] == ['flashback']

    def test_cleanup_reports_a_bad_value_and_not_a_missing_column(self, project_dir):
        from storyforge.cmd_cleanup import _check_scene_frames, OPTIONAL_CSV_COLUMNS
        assert 'frame' in OPTIONAL_CSV_COLUMNS['reference/scenes.csv']
        assert _check_scene_frames(project_dir) == []
        path = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(path) as f:
            lines = f.read().splitlines()
        lines = [lines[0] + '|frame', lines[1] + '|nap'] + [l + '|' for l in lines[2:]]
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        found = _check_scene_frames(project_dir)
        assert len(found) == 1 and found[0]['severity'] == 'error'
        assert 'act1-sc01: frame "nap" is not one of memory, dream, vision, ghost' \
            in found[0]['detail']

    def test_the_map_stage_asks_for_it(self):
        from storyforge import prompts_elaborate
        import inspect
        src = inspect.getsource(prompts_elaborate)
        assert '|architecture_scene|told_by|frame\n(all scenes' in src
        assert '- frame: memory (a past relived), dream' in src

    def test_extraction_reads_it(self):
        from storyforge import extract
        assert extract.SKELETON_SCHEMA['properties']['frame']['enum'] == [
            '', 'memory', 'dream', 'vision', 'ghost']
        prompt = extract.build_skeleton_prompt('s1', 'Text.', {})
        assert '- frame: "memory"' in prompt
        base = {k: '' for k in extract.SKELETON_SCHEMA['properties']}
        base.update({'told': False, 'time_relation': 'unclear', 'location': [],
                     'title': 'T', 'frame': 'dream'})
        assert extract.parse_skeleton_response(json.dumps(base), 's1')['frame'] == 'dream'
        base['frame'] = ''
        assert 'frame' not in extract.parse_skeleton_response(json.dumps(base), 's1')


class TestWorldSpeed:
    def test_speed_rows(self, project_dir):
        with open(os.path.join(project_dir, 'reference', 'world.csv'), 'w') as f:
            f.write('kind|name|value|note\nspeed|on foot|40000|\nspeed|horse|80000|\n')
        w = world_table.load(project_dir)
        assert w.fastest() == 80000.0 and World().fastest() is None

    def test_a_bad_speed_is_a_problem(self, project_dir):
        path = os.path.join(project_dir, 'reference', 'world.csv')
        with open(path, 'w') as f:
            f.write('kind|name|value|note\nspeed|ship|fast|\n')
        assert world_table.problems(path) == [
            'row 2: speed "fast" is not a positive number of metres a day']


class TestGateJoin:
    """`gate._check_continuity` on its own: what joins the check's findings."""
    def _result(self, existing):
        from storyforge.checker import CheckResult
        result = gate.GateResult('s1')
        result.check = CheckResult('s1', findings=list(existing))
        return result

    def _join(self, monkeypatch, tmp_path, existing, found, notes=()):
        got = continuity.ContinuityResult('s1', findings=list(found), notes=list(notes))
        monkeypatch.setattr(continuity, 'check_continuity', lambda *a, **k: got)
        result = self._result(existing)
        gate._check_continuity(str(tmp_path), 's1', 'prose', [], str(tmp_path), result)
        return result

    def test_one_slip_is_not_two(self, monkeypatch, tmp_path):
        from storyforge.checker import Finding
        mine = continuity._finding('life', 'Oren waved at them', 's0', 'x', 'dead')
        theirs = Finding('contradiction', 'PHY', 'Oren waved', 's0', 'x', '', 'model')
        other = continuity._finding('time', 'three days ago', CALENDAR, 'x', 'calendar')
        result = self._join(monkeypatch, tmp_path, [theirs], [mine, other])
        assert result.check.findings == [theirs, other]

    def test_a_stage_sheet_sun_is_the_sky_slip(self, monkeypatch, tmp_path):
        from storyforge.checker import Finding
        blk = Finding('contradiction', 'BLK', 'the sun went down behind Kesh', 's1', 'x', '',
                      'sheet')
        sky = continuity._finding('sky', 'the sun went down behind Kesh', 'world.csv', 'x', 's')
        life = continuity._finding('life', 'the sun went down behind Kesh', 's0', 'x', 'odd')
        result = self._join(monkeypatch, tmp_path, [blk], [sky, life])
        assert result.check.findings == [blk, life]

    def test_notes_go_to_state_notes(self, monkeypatch, tmp_path):
        result = self._join(monkeypatch, tmp_path, [], [], ['travel: 1 move(s) not checked'])
        assert result.state_notes == ['travel: 1 move(s) not checked'] and result.passed

    def test_an_error_is_a_gate_error(self, monkeypatch, tmp_path):
        def boom(*a, **k):
            raise continuity.ContinuityError('s1: the typed state extraction failed twice')
        monkeypatch.setattr(continuity, 'check_continuity', boom)
        with pytest.raises(gate.GateError, match='failed twice'):
            gate._check_continuity(str(tmp_path), 's1', 'p', [], str(tmp_path),
                                   self._result([]))


def test_cleanup_expects_the_typed_state_dir(project_dir):
    from storyforge.cmd_cleanup import report_unexpected_files
    os.makedirs(os.path.join(project_dir, 'working', 'typed-state'))
    assert 'UNEXPECTED_DIR:working/typed-state' not in report_unexpected_files(project_dir)
