"""Tests for storyforge.stage_sheet and storyforge.world_table (#647): the
stage sheet's code checks, extraction and the yes/no fallback (API mocked
at `api._api_request`), its file, and the gate's and `check`'s use of it.
Every scene here is invented for the tests."""

import json
import os
from unittest.mock import patch

import pytest

from storyforge import gate, stage_sheet, world_table
from storyforge.blocking import BLOCKING_CODE
from storyforge.stage_sheet import (Entry, Event, Question, StageSheetError, check_stage_sheet,
                                    replay)
from storyforge.world_table import World, WorldTableError

SCENE = 'act1-sc02'
PREV = 'act1-sc01'

# An invented scene with three slips: a free hand with both hands full, a
# second sitting down, and reading by a candle that went out
HARBOUR = ('Tom held the lamp in his right hand and the rope in his left. '
           'He waved with his free hand to the boat. '
           'Ann sat on the step. Later Ann sat down beside him. '
           'The candle had gone out, and in the candlelight he read the letter.')
CLEAN = ('Ann stood at the door and looked out at the rain. She put on her coat, '
         'took the lantern from its hook and went down the path to the gate.')


def E(quote, who, field, to, frm='', item='', verified=True):
    return Event(quote=quote, who=who, field=field, item=item, from_=frm, to=to,
                 verified=verified)


def _quotes(r):
    return [(s.event.quote, s.against.quote if s.against else None) for s in r.slips]


def _hands(entries, who='Ann'):
    """hand → (value, side_guessed) for `who`'s hands in `entries`."""
    return {e.field: (e.value, e.side_guessed) for e in entries
            if e.field in stage_sheet.HANDS and e.who == who}


# ============================================================================
# The world table
# ============================================================================

def _world_file(project_dir, text):
    path = os.path.join(project_dir, 'reference', 'world.csv')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


class TestWorldTable:
    def test_no_file_gives_the_defaults(self, tmp_path):
        os.makedirs(tmp_path / 'reference')
        w = world_table.load(str(tmp_path))
        assert w.sun('dawn') == 'east' and w.sun('night') == world_table.SUN_DOWN
        assert w.sight('face') == 30.0

    def test_rows_add_to_and_replace_the_defaults(self, project_dir):
        _world_file(project_dir, 'kind|name|value|note\n'
                                 'direction|Ida|E|seen from Troy\n'
                                 'sun|noon|north|southern hemisphere\n'
                                 'sight|face|20|\n'
                                 'distance|the wall > the ships|2000|\n')
        w = world_table.load(project_dir)
        assert w.direction('behind Ida') == 'east'
        assert w.direction('north-east') == 'northeast'
        assert w.sun('high noon') == 'north'
        assert w.sight('face') == 20.0
        assert w.distance('The ships', 'the wall') == 2000.0

    @pytest.mark.parametrize('row,expected', [
        ('river|Ida|east|', 'kind "river"'),
        ('direction|Ida|up|', 'not a compass direction'),
        ('sun|dawn|sideways|', 'not a compass direction or "none"'),
        ('sight|face|-3|', 'not a positive number'),
        ('distance|the wall|200|', 'not two places as "A > B"'),
        ('direction|Ida|east', 'has 3 cells'),
        ('direction||east|', 'no name'),
    ])
    def test_problems_name_the_row(self, project_dir, row, expected):
        path = _world_file(project_dir, f'kind|name|value|note\n{row}\n')
        found = world_table.problems(path)
        assert found and found[0].startswith('row 2') and expected in found[0]
        with pytest.raises(WorldTableError, match='reference/world.csv: row 2'):
            world_table.load(project_dir)

    def test_a_fact_given_twice(self, project_dir):
        path = _world_file(project_dir, 'kind|name|value|note\ndistance|a > b|1|\n'
                                        'distance|B > A|2|\n')
        assert world_table.problems(path) == ['row 3: distance "B > A" is already given on row 2']

    def test_wrong_header(self, project_dir):
        path = _world_file(project_dir, 'kind|name|value\n')
        assert world_table.problems(path)[0].startswith('header is')


# ============================================================================
# Code checks the events
# ============================================================================

class TestPosture:
    def test_standing_up_when_standing(self):
        r = replay([E('Apollo stood by the altar', 'Apollo', 'posture', 'standing'),
                    E('Apollo stood up', 'Apollo', 'posture', 'standing', frm='down')])
        assert _quotes(r) == [('Apollo stood up', 'Apollo stood by the altar')]
        assert 'is standing' in r.slips[0].why

    def test_standing_up_after_sitting_down_is_fine(self):
        r = replay([E('He sat', 'Apollo', 'posture', 'sitting', frm='standing'),
                    E('He stood up', 'Apollo', 'posture', 'standing', frm='down')])
        assert r.slips == []

    def test_sitting_then_standing_with_nothing_between(self):
        r = replay([E('Ann sat on the step', 'Ann', 'posture', 'sitting'),
                    E('Ann stood at the rail', 'Ann', 'posture', 'standing')])
        assert len(r.slips) == 1 and 'with nothing between' in r.slips[0].why

    def test_unknown_posture_is_never_a_slip(self):
        assert replay([E('He stood up', 'Apollo', 'posture', 'standing', frm='down')]).slips == []

    def test_synonyms_and_other(self):
        assert stage_sheet.posture('Seated in the car') == 'sitting'
        assert stage_sheet.posture('on horseback') == 'mounted'
        assert stage_sheet.posture('leaning') == 'other'
        r = replay([E('She leaned on the wall', 'Ann', 'posture', 'leaning'),
                    E('She sat', 'Ann', 'posture', 'sitting', frm='standing')])
        assert r.slips == []

    def test_names_are_matched_without_case(self):
        r = replay([E('Ann sat', 'Ann', 'posture', 'sitting'),
                    E('ANN sat down', 'ann ', 'posture', 'sitting', frm='standing')])
        assert len(r.slips) == 1


class TestHands:
    def test_free_hand_with_both_hands_full(self):
        r = replay([E('the lamp in his right hand', 'Tom', 'hand_right', 'lamp'),
                    E('the rope in his left', 'Tom', 'hand_left', 'rope'),
                    E('He waved with his free hand', 'Tom', 'hand_either', 'empty', frm='empty')])
        # set against the later of the two hands
        assert _quotes(r) == [('He waved with his free hand', 'the rope in his left')]

    def test_free_hand_after_letting_go(self):
        r = replay([E('the lamp in his right hand', 'Tom', 'hand_right', 'lamp'),
                    E('the rope in his left', 'Tom', 'hand_left', 'rope'),
                    E('He dropped the rope', 'Tom', 'hand_left', 'empty', frm='rope'),
                    E('He waved with his free hand', 'Tom', 'hand_either', 'empty', frm='empty')])
        assert r.slips == []

    def test_gripping_with_a_full_hand(self):
        r = replay([E('his right hand on the spear', 'Achilles', 'hand_right', 'the spear'),
                    E('his right hand closed on her wrist', 'Achilles', 'hand_right', 'her wrist',
                      frm='empty')])
        assert len(r.slips) == 1 and 'needs to be free' in r.slips[0].why

    def test_letting_go_of_what_the_hand_does_not_hold(self):
        r = replay([E('the axe in his right hand', 'Gawain', 'hand_right', 'the axe'),
                    E('he drove the spear into the ground', 'Gawain', 'hand_right', 'empty',
                      frm='spear')])
        assert len(r.slips) == 1 and 'lets go of spear' in r.slips[0].why

    def test_other_names_for_one_object(self):
        r = replay([E('holding the holly branch', 'Gawain', 'hand_left', 'the holly branch'),
                    E('he let the holly fall', 'Gawain', 'hand_left', 'empty', frm='holly')])
        assert r.slips == []

    def test_a_second_thing_in_a_full_hand(self):
        r = replay([E('the cup in her left hand', 'Ann', 'hand_left', 'cup'),
                    E('the letter in her left hand', 'Ann', 'hand_left', 'letter')])
        assert len(r.slips) == 1 and 'already holds cup' in r.slips[0].why

    def test_either_hand_takes_the_free_one(self):
        r = replay([E('the cup in her left hand', 'Ann', 'hand_left', 'cup'),
                    E('her right hand was empty', 'Ann', 'hand_right', 'empty'),
                    E('she picked up the letter', 'Ann', 'hand_either', 'letter', frm='empty'),
                    E('she waved with her free hand', 'Ann', 'hand_either', 'empty',
                      frm='empty')])
        assert len(r.slips) == 1
        assert r.slips[0].against.quote == 'she picked up the letter'

    def test_either_hand_letting_go_of_what_neither_holds(self):
        r = replay([E('cup in her left', 'Ann', 'hand_left', 'cup'),
                    E('pen in her right', 'Ann', 'hand_right', 'pen'),
                    E('she set the bowl down', 'Ann', 'hand_either', 'empty', frm='bowl')])
        assert len(r.slips) == 1 and 'lets go of bowl' in r.slips[0].why

    def test_a_guessed_side_moves_to_the_free_hand(self):
        """Either hand could have taken the cup: a later jug in the left
        means the cup is in the right."""
        r = replay([E('her hands were empty', 'Ann', 'hand_left', 'empty'),
                    E('her right was empty', 'Ann', 'hand_right', 'empty'),
                    E('she took the cup', 'Ann', 'hand_either', 'cup', frm='empty'),
                    E('she took the jug in her left', 'Ann', 'hand_left', 'jug', frm='empty')])
        assert r.slips == []
        assert _hands(r.end) == {'hand_left': ('jug', False), 'hand_right': ('cup', False)}


class TestWornPresentLightDoor:
    def test_taking_off_what_is_off(self):
        r = replay([E('He took off his helm', 'Gawain', 'worn', 'off', frm='on', item='helm'),
                    E('he unlaced the helmet', 'Gawain', 'worn', 'off', frm='on',
                      item='the helm')])
        assert len(r.slips) == 1 and 'helm' in r.slips[0].why

    def test_wearing_what_he_took_off(self):
        r = replay([E('He shrugged off the cloak', 'Tom', 'worn', 'off', frm='on', item='cloak'),
                    E('his cloak about his shoulders', 'Tom', 'worn', 'on', item='cloak')])
        assert len(r.slips) == 1

    def test_acting_after_leaving(self):
        r = replay([E('Hector went out', 'Hector', 'present', 'gone', frm='here'),
                    E('Hector sat down', 'Hector', 'posture', 'sitting', frm='standing')])
        assert len(r.slips) == 1 and 'after leaving' in r.slips[0].why

    def test_coming_back_in_is_fine(self):
        r = replay([E('Hector went out', 'Hector', 'present', 'gone', frm='here'),
                    E('Hector came back', 'Hector', 'present', 'here', frm='gone'),
                    E('Hector sat down', 'Hector', 'posture', 'sitting', frm='standing')])
        assert r.slips == []

    def test_arriving_when_already_here(self):
        r = replay([E('Hector came in', 'Hector', 'present', 'here', frm='gone'),
                    E('Hector entered', 'Hector', 'present', 'here', frm='gone')])
        assert len(r.slips) == 1

    def test_reading_by_a_candle_that_went_out(self):
        r = replay([E('The candle had gone out', '', 'light', 'out', frm='lit', item='candle'),
                    E('in the candlelight he read', '', 'light', 'lit', item='the candle')])
        assert _quotes(r) == [('in the candlelight he read', 'The candle had gone out')]

    def test_opening_a_door_that_is_open(self):
        r = replay([E('the door stood open', '', 'door', 'open', item='door'),
                    E('she opened the door', '', 'door', 'open', frm='shut', item='door')])
        assert len(r.slips) == 1

    def test_a_break_ends_states_but_what_is_worn(self):
        r = replay([E('Ann sat', 'Ann', 'posture', 'sitting'),
                    E('his helm off', 'Tom', 'worn', 'off', item='helm'),
                    E('* * *', '', 'break', ''),
                    E('Ann stood at the rail', 'Ann', 'posture', 'standing'),
                    E('he took off his helm', 'Tom', 'worn', 'off', frm='on', item='helm')])
        assert [s.event.quote for s in r.slips] == ['he took off his helm']
        assert r.beats[2].get('cleared') is True


class TestSky:
    def test_the_sun_against_the_time(self):
        w = World(directions={'ida': 'east'})
        r = replay([E('at dusk', '', 'time', 'dusk'),
                    E('the sun stood over Ida', '', 'sun', 'Ida')], world=w)
        assert _quotes(r) == [('the sun stood over Ida', 'at dusk')]
        assert r.slips[0].kind == 'impossible'

    def test_the_scene_time_from_scenes_csv(self):
        r = replay([E('the sun in the west', '', 'sun', 'west')], time_of_day='morning')
        assert len(r.slips) == 1 and r.slips[0].against is None

    def test_a_shadow_toward_the_sun(self):
        r = replay([E('the sun low in the west', '', 'sun', 'west'),
                    E('his shadow stretched west', '', 'shadow', 'west')])
        assert _quotes(r) == [('his shadow stretched west', 'the sun low in the west')]

    def test_a_shadow_away_from_the_sun(self):
        r = replay([E('at dawn', '', 'time', 'dawn'),
                    E('his shadow ran out west before him', '', 'shadow', 'west')])
        assert r.slips == []

    def test_an_unknown_landmark_is_not_checked_and_is_said(self):
        r = replay([E('at dusk', '', 'time', 'dusk'),
                    E('the sun over the hill', '', 'sun', 'the hill')])
        assert r.slips == [] and r.skipped == {stage_sheet.SKY_PLACE: 1}

    def test_a_face_seen_too_far_away(self):
        w = World(distances={frozenset(('the wall', 'the ships')): 2000.0})
        r = replay([Event('she saw his face', 'Helen', 'sees', 'face', 'the wall',
                          'the ships')], world=w)
        assert len(r.slips) == 1 and '2000 m' in r.slips[0].why


class TestWhatIsNotChecked:
    def test_a_carried_state_makes_no_finding(self):
        carried = [Entry('Ann', 'posture', '', 'standing', 'Ann stood', origin='carried')]
        r = replay([E('Ann stood up', 'Ann', 'posture', 'standing', frm='down'),
                    E('Ann stood up again', 'Ann', 'posture', 'standing', frm='down')],
                   opening=carried)
        assert [s.event.quote for s in r.slips] == ['Ann stood up again']
        # C2: the slip set against the carried state is counted, never silent
        assert r.carried == 1
        assert any('carried from the previous scene' in n for n in r.notes(2))

    def test_a_misquoted_state_is_not_applied_and_is_counted(self):
        bad = E('Ann sat on a chair', 'Ann', 'posture', 'sitting', verified=False)
        r = replay([bad, E('Ann sat down', 'Ann', 'posture', 'sitting', frm='standing')])
        assert r.slips == [] and r.unapplied == 1 and r.unchecked == 0
        assert r.beats[0]['set'] == []

    def test_a_slip_a_misquoted_event_makes_is_counted(self):
        r = replay([E('Ann sat', 'Ann', 'posture', 'sitting'),
                    E('Ann sat down', 'Ann', 'posture', 'sitting', frm='standing',
                      verified=False)])
        assert r.slips == [] and r.unchecked == 1
        assert any('made by a misquoted event' in n for n in r.notes(2))


# ============================================================================
# Extraction, the questions, the whole check
# ============================================================================

def _text(payload, stop='end_turn'):
    return {'stop_reason': stop, 'model': 'claude-haiku-5-5',
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 1, 'output_tokens': 1}}


def _kind(body):
    props = (body.get('output_config') or {}).get('format', {}).get('schema', {}) \
        .get('properties', {})
    return 'extract' if 'events' in props else 'ask' if 'answers' in props else 'other'


def ev(quote, who, field, to, frm='', item=''):
    return {'quote': quote, 'who': who, 'field': field, 'item': item, 'from': frm, 'to': to}


HARBOUR_EVENTS = [
    ev('Tom held the lamp in his right hand', 'Tom', 'hand_right', 'lamp'),
    ev('the rope in his left', 'Tom', 'hand_left', 'rope'),
    ev('He waved with his free hand', 'Tom', 'hand_either', 'empty', frm='empty'),
    ev('Ann sat on the step', 'Ann', 'posture', 'sitting'),
    ev('Later Ann sat down beside him', 'Ann', 'posture', 'sitting', frm='standing'),
    ev('The candle had gone out', '', 'light', 'out', frm='lit', item='candle'),
    ev('in the candlelight he read the letter', '', 'light', 'lit', item='candle'),
]


def _fake(extracts, answers=None, asked=None):
    """`extracts`: replies to the extraction in turn (the last repeats);
    `answers`: a function (asking number, questions count) → answers."""
    extracts = list(extracts)
    asked = asked if asked is not None else []

    def fake(path, body, **k):
        kind = _kind(body)
        prompt = body['messages'][0]['content']
        if kind == 'extract':
            reply = extracts.pop(0) if len(extracts) > 1 else extracts[0]
            return reply if 'content' in reply else _text(reply)
        if kind == 'ask':
            asked.append(prompt)
            n = prompt.count('   Question: ')
            asking = 2 if 'independent asking 2' in prompt else 1
            return _text({'answers': answers(asking, n)})
        raise AssertionError(f'unexpected call: {kind}')
    return fake


def _write_scene(project_dir, scene, prose):
    with open(os.path.join(project_dir, 'scenes', f'{scene}.md'), 'w', encoding='utf-8') as f:
        f.write(prose)


class TestCheckStageSheet:
    def test_the_slips_are_blk_findings_against_the_scene(self, project_dir):
        fake = _fake([{'cast': ['Tom', 'Ann'], 'events': HARBOUR_EVENTS, 'questions': []}])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=HARBOUR, model='m', carry=False)
        assert [f.scene_quote for f in r.findings] == [
            'He waved with his free hand', 'Later Ann sat down beside him',
            'in the candlelight he read the letter']
        for f in r.findings:
            assert f.code == BLOCKING_CODE and f.kind == 'contradiction'
            assert f.established_scene == SCENE and not f.problem
            assert '(contradiction, stage sheet)' in f.explanation
        assert r.findings[0].established_quote == 'the rope in his left'
        assert r.notes == [] and r.events == 7

    def test_a_clean_scene_has_nothing(self, project_dir):
        fake = _fake([{'cast': ['Ann'], 'events': [
            ev('Ann stood at the door', 'Ann', 'posture', 'standing'),
            ev('She put on her coat', 'Ann', 'worn', 'on', frm='off', item='coat'),
            ev('took the lantern from its hook', 'Ann', 'hand_either', 'lantern', frm='empty'),
        ], 'questions': []}])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=CLEAN, model='m', carry=False)
        assert r.findings == [] and r.notes == []

    def test_misquotes_are_noted_never_silent(self, project_dir):
        events = HARBOUR_EVENTS[:3] + [ev('Ann sat on a bench', 'Ann', 'posture', 'sitting')]
        fake = _fake([{'cast': [], 'events': events,
                       'questions': [{'quote': 'a line not there', 'question': 'Can he?'}]}])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=HARBOUR, model='m', carry=False)
        assert any('1 of 4 event(s) quote words not in the scene' in n for n in r.notes)
        assert any('1 question(s) quote words not in the scene: not asked' in n
                   for n in r.notes)

    def test_a_bad_reply_twice_raises(self, project_dir):
        fake = _fake([{'nope': 1}])
        with patch('storyforge.api._api_request', side_effect=fake):
            with pytest.raises(StageSheetError, match='extraction failed twice'):
                check_stage_sheet(project_dir, SCENE, prose=HARBOUR, model='m', carry=False)

    def test_a_cut_off_reply_is_retried(self, project_dir):
        good = {'cast': [], 'events': [], 'questions': []}
        fake = _fake([_text(good, stop='max_tokens'), good])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=HARBOUR, model='m', carry=False)
        assert r.findings == []

    def test_an_event_off_the_schema_is_unusable(self):
        with pytest.raises(ValueError, match='an event is not the schema'):
            stage_sheet.parse(json.dumps({'cast': [], 'questions': [],
                                          'events': [{'quote': 'x', 'field': 'mood'}]}))

    def test_no_prose(self, project_dir):
        with pytest.raises(StageSheetError, match='no prose'):
            check_stage_sheet(project_dir, SCENE, prose='  ', model='m')

    def test_the_model_is_configurable(self, project_dir, monkeypatch):
        models = []

        def fake(path, body, **k):
            models.append(body['model'])
            return _text({'cast': [], 'events': [], 'questions': []})
        monkeypatch.setenv(stage_sheet.MODEL_ENV, 'claude-sonnet-5-5')
        with patch('storyforge.api._api_request', side_effect=fake):
            check_stage_sheet(project_dir, SCENE, prose=HARBOUR, carry=False)
        monkeypatch.delenv(stage_sheet.MODEL_ENV)
        with patch('storyforge.api._api_request', side_effect=fake):
            check_stage_sheet(project_dir, SCENE, prose=HARBOUR, carry=False)
        assert models == ['claude-sonnet-5-5', 'claude-haiku-5-5']

    def test_a_malformed_world_table_stops_the_check(self, project_dir):
        _world_file(project_dir, 'kind|name|value|note\nsun|dawn|up|\n')
        with pytest.raises(WorldTableError):
            check_stage_sheet(project_dir, SCENE, prose=HARBOUR, model='m')

    def test_scenes_csv_time_of_day_reaches_the_sky_check(self, project_dir):
        # act1-sc02 is an evening scene in the fixture
        prose = 'The sun rose over the eastern hills.'
        fake = _fake([{'cast': [], 'events': [ev('The sun rose over the eastern hills', '',
                                                'sun', 'east')], 'questions': []}])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=prose, model='m', carry=False)
        assert len(r.findings) == 1 and '(impossible, stage sheet)' in r.findings[0].explanation


class TestQuestions:
    PROSE = ('Ann sat at the rail behind the cart. She reached back and lifted the basket '
             'from the cart bed.')
    EVENTS = [ev('Ann sat at the rail behind the cart', 'Ann', 'posture', 'sitting')]
    Q = {'quote': 'lifted the basket from the cart bed',
         'question': 'Can Ann, seated at the rail behind the cart, lift the basket from the '
                     'cart ahead of her?'}

    def _run(self, project_dir, answers):
        asked = []
        fake = _fake([{'cast': ['Ann'], 'events': self.EVENTS, 'questions': [self.Q]}],
                     answers=answers, asked=asked)
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=self.PROSE, model='m',
                                  carry=False)
        return r, asked

    def test_two_noes_make_a_finding(self, project_dir):
        r, asked = self._run(project_dir, lambda a, n: [
            {'n': 1, 'answer': 'no', 'why': 'The cart is ahead and she sits behind it.'}])
        assert len(asked) == stage_sheet.ASKINGS == 2
        assert len(r.findings) == 1 and r.asked == 1
        f = r.findings[0]
        assert f.scene_quote == self.Q['quote'] and f.code == BLOCKING_CODE
        assert 'asked 2 times' in f.explanation and 'cart is ahead' in f.explanation

    def test_split_answers_are_noted_not_found(self, project_dir):
        r, _ = self._run(project_dir, lambda a, n: [
            {'n': 1, 'answer': 'no' if a == 1 else 'yes', 'why': 'x'}])
        assert r.findings == []
        assert r.notes == ['1 question(s) got split answers: not findings']

    def test_yes_twice_is_nothing(self, project_dir):
        r, _ = self._run(project_dir, lambda a, n: [{'n': 1, 'answer': 'yes', 'why': 'x'}])
        assert r.findings == [] and r.notes == []

    def test_the_question_carries_the_stage_at_its_beat(self, project_dir):
        _, asked = self._run(project_dir, lambda a, n: [{'n': 1, 'answer': 'yes', 'why': 'x'}])
        assert '- Ann: posture: sitting' in asked[0]
        assert 'independent asking 2' in asked[1] and 'independent asking' not in asked[0]

    def test_a_question_on_a_slip_the_code_found_is_not_a_second_finding(self, project_dir):
        events = HARBOUR_EVENTS[:3]
        q = {'quote': 'He waved with his free hand', 'question': 'Can Tom wave with a free hand?'}
        fake = _fake([{'cast': [], 'events': events, 'questions': [q]}],
                     answers=lambda a, n: [{'n': 1, 'answer': 'no', 'why': 'hands full'}])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=HARBOUR, model='m', carry=False)
        assert [f.scene_quote for f in r.findings] == ['He waved with his free hand']
        assert '(contradiction, stage sheet)' in r.findings[0].explanation

    def test_answers_must_cover_every_question_once(self):
        with pytest.raises(ValueError, match='exactly'):
            stage_sheet.parse_answers(json.dumps({'answers': [
                {'n': 1, 'answer': 'yes', 'why': ''}]}), 2)
        with pytest.raises(ValueError, match='answered twice'):
            stage_sheet.parse_answers(json.dumps({'answers': [
                {'n': 1, 'answer': 'yes', 'why': ''}, {'n': 1, 'answer': 'no', 'why': ''}]}), 1)

    def test_the_second_asking_reverses_the_order(self):
        qs = [Question('a', 'First?'), Question('b', 'Second?')]
        one = stage_sheet.build_ask_prompt(SCENE, 'a b', qs, 1)
        two = stage_sheet.build_ask_prompt(SCENE, 'a b', qs, 2)
        assert one.index('First?') < one.index('Second?')
        assert two.index('Second?') < two.index('First?')
        assert '2. At: "b"' in two

    def test_questions_past_the_cap_are_noted(self, project_dir, monkeypatch):
        monkeypatch.setattr(stage_sheet, 'MAX_QUESTIONS', 1)
        q2 = {'quote': 'She reached back', 'question': 'Can she reach back?'}
        fake = _fake([{'cast': [], 'events': [], 'questions': [self.Q, q2]}],
                     answers=lambda a, n: [{'n': i, 'answer': 'yes', 'why': ''}
                                           for i in range(1, n + 1)])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=self.PROSE, model='m',
                                  carry=False)
        assert r.asked == 1
        assert any('1 question(s) past the 1 a scene gets' in n for n in r.notes)


# ============================================================================
# The sheet's file, and carrying it over
# ============================================================================

class TestSheetFile:
    def _check(self, project_dir, scene, prose, events, carry=True):
        fake = _fake([{'cast': ['Ann'], 'events': events, 'questions': []}])
        with patch('storyforge.api._api_request', side_effect=fake):
            return check_stage_sheet(project_dir, scene, prose=prose, model='m', carry=carry,
                                     save=True)

    def test_written_loaded_and_replayed(self, project_dir):
        self._check(project_dir, SCENE, HARBOUR, HARBOUR_EVENTS, carry=False)
        path = stage_sheet.sheet_path(project_dir, SCENE)
        sheet = stage_sheet.load_sheet(path)
        assert sheet['format'] == stage_sheet.FORMAT and sheet['source'] == 'extracted'
        assert sheet['prose_sha256'] == stage_sheet.prose_hash(HARBOUR)
        assert len(sheet['beats']) == len(HARBOUR_EVENTS)
        assert sheet['beats'][0]['set'][0]['value'] == 'lamp'
        steps = stage_sheet.states(sheet)
        assert len(steps) == len(HARBOUR_EVENTS) + 1 and steps[0] == []
        end = {(e.who, e.field, e.item): e.value for e in steps[-1]}
        assert end[('Ann', 'posture', '')] == 'sitting'
        assert end[('', 'light', 'candle')] == 'lit'
        with open(path, 'rb') as f:
            assert b'\r\n' not in f.read()

    def test_a_bad_file_names_itself(self, tmp_path):
        path = tmp_path / 's.json'
        path.write_text(json.dumps({'format': 99, 'scene_id': 'x'}))
        with pytest.raises(ValueError, match='s.json: format is not 1'):
            stage_sheet.load_sheet(str(path))

    def test_the_next_scene_opens_with_the_last_ones_end(self, project_dir):
        prev = 'Ann sat on the step.'
        _write_scene(project_dir, PREV, prev)
        self._check(project_dir, PREV, prev, [ev('Ann sat on the step', 'Ann', 'posture',
                                                 'sitting')], carry=False)
        r = self._check(project_dir, SCENE, 'Ann stood up.',
                        [ev('Ann stood up', 'Ann', 'posture', 'standing', frm='down')])
        assert r.notes == [] and r.findings == []
        opening = r.sheet['opening']
        assert opening == [{'who': 'Ann', 'field': 'posture', 'item': '', 'value': 'sitting',
                            'quote': 'Ann sat on the step', 'origin': 'carried'}]

    def test_a_carried_state_is_never_a_finding(self, project_dir):
        prev = 'Ann stood at the rail.'
        _write_scene(project_dir, PREV, prev)
        self._check(project_dir, PREV, prev, [ev('Ann stood at the rail', 'Ann', 'posture',
                                                 'standing')], carry=False)
        r = self._check(project_dir, SCENE, 'Ann stood up.',
                        [ev('Ann stood up', 'Ann', 'posture', 'standing', frm='down')])
        assert r.findings == []
        assert r.notes == ['1 possible slip(s) set against a state carried from the previous '
                           'scene: not findings (a scene break allows any change)']

    def test_a_sheet_of_earlier_prose_is_not_carried(self, project_dir):
        _write_scene(project_dir, PREV, 'Ann sat on the step.')
        self._check(project_dir, PREV, 'Ann sat on the step.', [], carry=False)
        _write_scene(project_dir, PREV, 'Ann stood on the step.')
        r = self._check(project_dir, SCENE, 'Ann stood up.', [])
        assert r.notes == [f'no state carried over: {PREV}\'s stage sheet is of earlier prose']

    def test_no_sheet_for_the_previous_scene_is_said(self, project_dir):
        r = self._check(project_dir, SCENE, 'Ann stood up.', [])
        assert r.notes == [f'no state carried over: {PREV} has no stage sheet yet']

    def test_the_first_scene_carries_nothing_and_says_nothing(self, project_dir):
        r = self._check(project_dir, PREV, 'Ann stood up.', [])
        assert r.notes == []


# ============================================================================
# The gate and `check`
# ============================================================================

@pytest.mark.blocking_read
class TestGateUsesTheStageSheet:
    def _run(self, project_dir, tmp_path, monkeypatch, extracts, method='stage-sheet'):
        monkeypatch.setattr(gate, 'GATE_BLOCKING_METHOD', method)
        calls = []

        def fake(path, body, **k):
            schema = (body.get('output_config') or {}).get('format', {}).get('schema', {})
            if 'tools' in body:
                return _text({'findings': [], 'kept': []})
            if 'verdicts' in schema.get('properties', {}):
                return _text({'verdicts': []})
            kind = _kind(body)
            calls.append(kind)
            if kind == 'extract':
                return _text(extracts)
            if 'other_quote' in json.dumps(schema):
                calls[-1] = 'read'
                return _text({'findings': []})
            return _text({'commitments': []})

        _write_scene(project_dir, SCENE, HARBOUR)
        with patch('storyforge.api._api_request', side_effect=fake):
            result = gate.gate_scene(project_dir, SCENE, command='draft',
                                     log_dir=str(tmp_path / 'logs'), extract_model='m',
                                     check_model='m')
        return result, calls

    def test_a_slip_stops_the_scene(self, project_dir, tmp_path, monkeypatch):
        result, calls = self._run(project_dir, tmp_path, monkeypatch,
                                  {'cast': [], 'events': HARBOUR_EVENTS, 'questions': []})
        assert 'extract' in calls and 'read' not in calls
        assert not result.passed and not result.committed
        assert [f.code for f in result.findings] == ['BLK'] * 3
        assert os.path.isfile(tmp_path / 'logs' / f'gate-stage-{SCENE}.json')
        assert os.path.isfile(stage_sheet.sheet_path(project_dir, SCENE))
        lines = gate.problems_to_fix(result)
        assert any('BLK blocking' in line and 'free hand' in line for line in lines)

    def test_a_clean_sheet_passes_and_notes_are_reported(self, project_dir, tmp_path,
                                                         monkeypatch):
        events = [ev('Ann sat on a bench', 'Ann', 'posture', 'sitting')]
        result, _ = self._run(project_dir, tmp_path, monkeypatch,
                              {'cast': [], 'events': events, 'questions': []})
        assert result.passed
        report = '\n'.join(gate.report_lines(result))
        assert 'NOTE (stage sheet, not checked):' in report
        assert 'quote words not in the scene' in report

    def test_a_failed_extraction_is_a_gate_error(self, project_dir, tmp_path, monkeypatch):
        with pytest.raises(gate.GateError, match='stage sheet extraction failed twice'):
            self._run(project_dir, tmp_path, monkeypatch, {'nope': 1})

    def test_the_read_is_still_the_default(self, project_dir, tmp_path, monkeypatch):
        assert gate.GATE_BLOCKING_METHOD == 'read'
        _, calls = self._run(project_dir, tmp_path, monkeypatch, {}, method='read')
        assert 'read' in calls and 'extract' not in calls

    def test_an_unknown_method_is_refused(self, project_dir, tmp_path, monkeypatch):
        with pytest.raises(gate.GateError, match='GATE_BLOCKING_METHOD'):
            self._run(project_dir, tmp_path, monkeypatch, {}, method='guess')


class TestCheckCommand:
    def _main(self, project_dir, monkeypatch, argv, fake):
        from storyforge import cmd_check
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '100')
        monkeypatch.setattr(cmd_check, 'detect_project_root', lambda: project_dir)
        with patch('storyforge.api._api_request', side_effect=fake):
            with pytest.raises(SystemExit) as e:
                cmd_check.main(argv)
        return e.value.code

    def test_blocking_with_the_stage_sheet_reports(self, project_dir, monkeypatch):
        _write_scene(project_dir, SCENE, HARBOUR)
        fake = _fake([{'cast': [], 'events': HARBOUR_EVENTS, 'questions': []}])
        code = self._main(project_dir, monkeypatch,
                          ['--blocking', '--stage-sheet', SCENE], fake)
        assert code == 1
        with open(os.path.join(project_dir, 'working', 'blocking-report.md')) as f:
            report = f.read()
        assert report.startswith('# Blocking (stage sheet)')
        assert 'He waved with his free hand' in report and 'stage sheet' in report
        assert os.path.isfile(stage_sheet.sheet_path(project_dir, SCENE))

    def test_notes_alone_are_listed_and_exit_0(self, project_dir, monkeypatch):
        _write_scene(project_dir, SCENE, HARBOUR)
        fake = _fake([{'cast': [], 'events': [ev('not in it', 'Ann', 'posture', 'sitting')],
                       'questions': []}])
        code = self._main(project_dir, monkeypatch,
                          ['--blocking', '--stage-sheet', SCENE], fake)
        assert code == 0
        with open(os.path.join(project_dir, 'working', 'blocking-report.md')) as f:
            report = f.read()
        assert '- NOT CHECKED: 1 of 1 event(s)' in report
        assert 'some of it was not checked' in report

    def test_stage_sheet_chooses_the_gate_method(self, project_dir, monkeypatch):
        from storyforge import cmd_check
        seen = []
        monkeypatch.setattr(cmd_check, '_check_scenes',
                            lambda *a, **k: seen.append(gate.GATE_BLOCKING_METHOD)
                            or (_ for _ in ()).throw(SystemExit(7)))
        monkeypatch.setattr(cmd_check, 'create_branch', lambda *a: True, raising=False)
        monkeypatch.setattr('storyforge.git.create_branch', lambda *a, **k: True)
        monkeypatch.setattr(gate, 'GATE_BLOCKING_METHOD', 'read')
        _write_scene(project_dir, SCENE, HARBOUR)
        code = self._main(project_dir, monkeypatch, ['--stage-sheet', SCENE],
                          lambda *a, **k: pytest.fail('no call expected'))
        assert code == 7 and seen == ['stage-sheet']

    def test_the_method_is_this_runs_only(self, project_dir, monkeypatch):
        """CR-9: an in-process caller after `check --stage-sheet` keeps the read."""
        from storyforge import cmd_check
        monkeypatch.setattr(cmd_check, '_check_scenes',
                            lambda *a, **k: (_ for _ in ()).throw(SystemExit(7)))
        monkeypatch.setattr('storyforge.git.create_branch', lambda *a, **k: True)
        _write_scene(project_dir, SCENE, HARBOUR)
        before = gate.GATE_BLOCKING_METHOD
        assert self._main(project_dir, monkeypatch, ['--stage-sheet', SCENE],
                          lambda *a, **k: pytest.fail('no call expected')) == 7
        assert gate.GATE_BLOCKING_METHOD == before == 'read'

    def test_notes_are_listed_exactly_and_nothing_is_carried(self, project_dir, monkeypatch):
        """T5: --blocking runs each scene alone: no carried state, no carry note."""
        r = replay([E('Ann sat', 'Ann', 'posture', 'sitting')])
        _write_scene(project_dir, PREV, 'x')
        stage_sheet.write_sheet(project_dir, stage_sheet.build_sheet(PREV, 'x', r))
        _write_scene(project_dir, SCENE, HARBOUR)
        fake = _fake([{'cast': [], 'events': [ev('not in it', 'Ann', 'posture', 'sitting')],
                       'questions': []}])
        assert self._main(project_dir, monkeypatch, ['--blocking', '--stage-sheet', SCENE],
                          fake) == 0
        with open(os.path.join(project_dir, 'working', 'blocking-report.md')) as f:
            report = f.read()
        assert [line for line in report.splitlines() if line.startswith('- ')] == [
            '- NOT CHECKED: 1 of 1 event(s) quote words not in the scene: their states were '
            'not applied, so what they touched is unknown from there']
        sheet = stage_sheet.load_sheet(stage_sheet.sheet_path(project_dir, SCENE))
        assert sheet['opening'] == []

    @pytest.mark.parametrize('broken', ['reply', 'world'])
    def test_a_scene_the_sheet_cannot_read_is_not_read(self, project_dir, monkeypatch, broken):
        _write_scene(project_dir, SCENE, HARBOUR)
        if broken == 'world':
            _world_file(project_dir, 'kind|name|value|note\nsun|dawn|up|\n')
        fake = _fake([{'nope': 1}])
        assert self._main(project_dir, monkeypatch, ['--blocking', '--stage-sheet', SCENE],
                          fake) == 1
        with open(os.path.join(project_dir, 'working', 'blocking-report.md')) as f:
            report = f.read()
        assert '- NOT READ: ' in report
        assert ('world.csv' if broken == 'world' else 'failed twice') in report

    def test_accept_takes_no_stage_sheet(self, project_dir, monkeypatch):
        code = self._main(project_dir, monkeypatch, ['--accept', SCENE, '--stage-sheet'],
                          lambda *a, **k: pytest.fail('no call expected'))
        assert code == 1


# ============================================================================
# cleanup
# ============================================================================

class TestCleanup:
    def test_bad_world_rows_are_reported_never_repaired(self, project_dir):
        from storyforge.cmd_cleanup import build_cleanup_report
        text = 'kind|name|value|note\ndirection|Ida|up|\n'
        _world_file(project_dir, text)
        found = [f for f in build_cleanup_report(project_dir)['findings']
                 if f['type'] == 'world_table_row']
        assert len(found) == 1 and found[0]['severity'] == 'error'
        assert 'row 2: direction "up"' in found[0]['detail']
        with open(os.path.join(project_dir, 'reference', 'world.csv')) as f:
            assert f.read() == text

    def test_a_bad_header_is_the_schema_check_alone(self, project_dir):
        from storyforge.cmd_cleanup import build_cleanup_report
        _world_file(project_dir, 'kind|name|value\n')
        findings = build_cleanup_report(project_dir)['findings']
        assert not [f for f in findings if f['type'] == 'world_table_row']
        assert any(f['file'] == 'reference/world.csv' for f in findings)

    def test_no_world_table_is_no_finding(self, project_dir):
        from storyforge.cmd_cleanup import build_cleanup_report
        findings = build_cleanup_report(project_dir)['findings']
        assert not [f for f in findings if 'world.csv' in f.get('file', '')]

    def test_stage_sheets_are_an_expected_working_dir(self, project_dir):
        from storyforge.cmd_cleanup import report_unexpected_files
        os.makedirs(os.path.join(project_dir, 'working', 'stage-sheets'))
        assert 'UNEXPECTED_DIR:working/stage-sheets' not in report_unexpected_files(project_dir)


# ============================================================================
# Review fixes (#671): hands as two slots, misquotes, carried states, what
# isn't checked, the file's entries, the prose's order
# ============================================================================

class TestUnnamedHands:
    """CR-1, SF5: an unnamed hand on unknown hands takes a slot; a known
    state is never forgotten."""

    def test_an_unnamed_hand_on_an_empty_sheet_is_recorded(self):
        r = replay([E('she took the cup', 'Ann', 'hand_either', 'cup', frm='empty')])
        assert _hands(r.end) == {'hand_left': ('cup', True)}
        assert r.beats[0]['set'][0]['side_guessed'] is True

    def test_two_unnamed_hands_then_a_free_hand_is_a_slip(self):
        """The review's case: cup, then bowl, then a free hand gripping rope."""
        r = replay([E('she took the cup', 'Ann', 'hand_either', 'cup'),
                    E('she took the bowl', 'Ann', 'hand_either', 'bowl'),
                    E('with a free hand she gripped the rope', 'Ann', 'hand_either', 'rope',
                      frm='empty')])
        assert len(r.slips) == 1 and 'free hand' in r.slips[0].why
        assert all(b['set'] for b in r.beats)

    def test_an_unnamed_hand_keeps_the_named_ones(self):
        r = replay([E('the spear in her left hand', 'Ann', 'hand_left', 'spear'),
                    E('she took the cup', 'Ann', 'hand_either', 'cup', frm='empty'),
                    E('she gripped the rope', 'Ann', 'hand_either', 'rope', frm='empty')])
        # the cup went to the only hand not known; the rope finds none free
        assert _hands(r.end)['hand_left'][0] != 'empty'
        assert len(r.slips) == 1 and 'spear' in r.slips[0].why

    def test_letting_go_with_an_unnamed_hand_takes_the_hand_holding_it(self):
        r = replay([E('the cup in her right hand', 'Ann', 'hand_right', 'cup'),
                    E('she set the cup down', 'Ann', 'hand_either', 'empty', frm='cup')])
        assert r.slips == [] and _hands(r.end) == {'hand_right': ('empty', False)}

    def test_a_guessed_side_follows_its_object(self):
        """She took the cup (a hand untold); then her right hand sets the
        cup down: the cup was in the right, and no slip."""
        r = replay([E('she took the cup', 'Ann', 'hand_either', 'cup', frm='empty'),
                    E('her right hand set the cup down', 'Ann', 'hand_right', 'empty',
                      frm='cup')])
        assert r.slips == []
        assert _hands(r.end) == {'hand_right': ('empty', False)}

    def test_naming_one_hand_settles_the_other(self):
        r = replay([E('she took the cup', 'Ann', 'hand_either', 'cup', frm='empty'),
                    E('she took the bowl', 'Ann', 'hand_either', 'bowl', frm='empty'),
                    E('the bowl in her right hand', 'Ann', 'hand_right', 'bowl')])
        assert r.slips == []
        assert _hands(r.end) == {'hand_left': ('cup', False), 'hand_right': ('bowl', False)}

    def test_a_named_hand_still_slips_when_neither_side_fits(self):
        r = replay([E('she took the cup', 'Ann', 'hand_either', 'cup', frm='empty'),
                    E('she took the bowl', 'Ann', 'hand_either', 'bowl', frm='empty'),
                    E('her left hand let go of the spear', 'Ann', 'hand_left', 'empty',
                      frm='spear')])
        assert len(r.slips) == 1 and 'lets go of spear' in r.slips[0].why

    def test_a_guessed_side_is_shown_to_the_asker(self):
        r = replay([E('she took the cup', 'Ann', 'hand_either', 'cup', frm='empty'),
                    E('Ann sat', 'Ann', 'posture', 'sitting')])
        assert 'left hand (or the other): cup' in r.stage_at[1]


class TestMisquotesAreNotApplied:
    """SF1: a misquoted event's state can't cancel a real slip unseen."""

    def test_a_misquoted_posture_makes_the_posture_unknown(self):
        r = replay([E('Ann stood', 'Ann', 'posture', 'standing'),
                    E('Ann sat down', 'Ann', 'posture', 'sitting', frm='standing',
                      verified=False),
                    E('Ann stood up', 'Ann', 'posture', 'standing', frm='down')])
        assert r.slips == [] and r.unapplied == 1
        assert r.beats[1]['set'] == []
        assert r.beats[1]['unknown'] == [{'who': 'Ann', 'field': 'posture', 'item': ''}]
        assert any('not applied' in n for n in r.notes(3))

    def test_a_misquoted_drop_makes_the_hand_unknown(self):
        r = replay([E('the spear in his right hand', 'Tom', 'hand_right', 'spear'),
                    E('he dropped it', 'Tom', 'hand_right', 'empty', frm='spear',
                      verified=False),
                    E('his right hand gripped the cup', 'Tom', 'hand_right', 'cup',
                      frm='empty')])
        assert r.unapplied == 1
        assert r.beats[1]['unknown'] == [{'who': 'Tom', 'field': 'hand_right', 'item': ''}]

    def test_a_misquoted_break_clears_nothing_it_does_not_say(self):
        r = replay([E('Ann sat', 'Ann', 'posture', 'sitting'),
                    E('* * *', '', 'break', '', verified=False)])
        assert 'cleared' not in r.beats[1] and r.unapplied == 1
        assert r.end == []

    def test_the_file_replays_to_the_same_end(self, project_dir):
        events = [E('Ann stood', 'Ann', 'posture', 'standing'),
                  E('Ann sat down', 'Ann', 'posture', 'sitting', frm='standing',
                    verified=False),
                  E('she took the cup', 'Ann', 'hand_either', 'cup', frm='empty'),
                  E('the jug in her left hand', 'Ann', 'hand_left', 'jug', frm='empty')]
        r = replay(events)
        sheet = stage_sheet.build_sheet(SCENE, 'x', r)
        path = stage_sheet.write_sheet(project_dir, sheet)
        last = stage_sheet.states(stage_sheet.load_sheet(path))[-1]
        assert sorted(e.to_json().items().__repr__() for e in last) == \
            sorted(e.to_json().items().__repr__() for e in r.end)


class TestCarriedStates:
    """CR-3, C2, T1, T4: a carried state is shown, counted, never a finding."""

    def _carried(self, field, value, who='', item=''):
        return [Entry(who, field, item, value, 'before', origin='carried')]

    def test_a_carried_time_never_overrides_the_scene_time(self):
        r = replay([E('the sun sank in the west', '', 'sun', 'west')],
                   opening=self._carried('time', 'morning'), time_of_day='evening')
        assert r.slips == [] and r.carried == 0

    def test_a_carried_time_alone_makes_no_finding_and_is_counted(self):
        r = replay([E('the sun sank in the west', '', 'sun', 'west')],
                   opening=self._carried('time', 'morning'))
        assert r.slips == [] and r.carried == 1

    def test_a_carried_sun_makes_no_shadow_finding(self):
        r = replay([E('his shadow ran east', '', 'shadow', 'east')],
                   opening=self._carried('sun', 'east'))
        assert r.slips == [] and r.carried == 1

    def test_the_scenes_own_time_still_binds(self):
        r = replay([E('at dusk', '', 'time', 'dusk'),
                    E('the sun climbed in the east', '', 'sun', 'east')],
                   opening=self._carried('time', 'morning'))
        assert len(r.slips) == 1

    @pytest.mark.parametrize('opening,event', [
        (('hand_right', 'spear', 'Tom'),
         E('his right hand closed on the rope', 'Tom', 'hand_right', 'rope', frm='empty')),
        (('worn', 'off', 'Tom', 'cloak'),
         E('he took off his cloak', 'Tom', 'worn', 'off', frm='on', item='cloak')),
        (('light', 'out', '', 'candle'),
         E('she blew out the candle', '', 'light', 'out', frm='lit', item='candle')),
        (('present', 'here', 'Tom'),
         E('Tom came in', 'Tom', 'present', 'here', frm='gone')),
    ])
    def test_carried_hands_worn_light_and_presence_make_no_finding(self, opening, event):
        r = replay([event], opening=self._carried(*opening))
        assert r.slips == [] and r.carried == 1

    def test_someone_who_left_last_scene_is_counted_once(self):
        r = replay([E('Tom sat', 'Tom', 'posture', 'sitting'),
                    E('Tom stood', 'Tom', 'posture', 'standing', frm='down'),
                    E('Tom waved', 'Tom', 'hand_right', 'empty')],
                   opening=self._carried('present', 'gone', 'Tom'))
        assert r.slips == [] and r.carried == 1


class TestWhatIsSaid:
    """SF3, SF4, CR-6, T6: every event the code can't read or check is counted."""

    def test_a_sun_with_no_time(self):
        r = replay([E('the sun in the west', '', 'sun', 'west')])
        assert r.slips == [] and r.skipped == {stage_sheet.SKY_NO_TIME: 1}

    def test_a_sun_at_night(self):
        r = replay([E('the sun in the west', '', 'sun', 'west')], time_of_day='night')
        assert r.slips == [] and r.skipped == {stage_sheet.SKY_NIGHT: 1}

    def test_a_time_the_table_does_not_know(self):
        r = replay([E('in the third watch', '', 'time', 'the third watch'),
                    E('the sun in the west', '', 'sun', 'west')])
        assert r.skipped == {stage_sheet.SKY_ODD_TIME: 1}

    def test_a_shadow_from_the_time_alone(self):
        r = replay([E('at dawn', '', 'time', 'dawn'),
                    E('his shadow ran east before him', '', 'shadow', 'east')])
        assert len(r.slips) == 1 and 'with the sun in the east' in r.slips[0].why

    def test_a_sighting_within_range(self):
        w = World(distances={frozenset(('the gate', 'the well')): 20.0})
        r = replay([Event('she saw his face', 'Ann', 'sees', 'face', 'the gate', 'the well')],
                   world=w)
        assert r.slips == [] and r.skipped == {}

    def test_a_figure_too_far_away(self):
        w = World(distances={frozenset(('the wall', 'the ships')): 2000.0})
        r = replay([Event('she knew him', 'Ann', 'sees', 'figure', 'the wall', 'the ships')],
                   world=w)
        assert len(r.slips) == 1 and 'figure' in r.slips[0].why

    def test_a_sighting_with_no_distance(self):
        r = replay([Event('she saw his face', 'Ann', 'sees', 'face', 'the gate', 'the well')])
        assert r.skipped == {stage_sheet.SIGHT_FAR: 1}

    def test_a_detail_with_no_range(self):
        r = replay([Event('she saw his limp', 'Ann', 'sees', 'gait', 'the gate', 'the well')])
        assert r.skipped == {stage_sheet.SIGHT_DETAIL: 1}

    def test_places_are_matched_inside_longer_phrases(self):
        w = World(distances={frozenset(('the wall', 'the ships')): 2000.0})
        assert w.distance('on the wall', 'down by the ships') == 2000.0
        assert w.distance('the ships', 'the wall') == 2000.0
        assert w.distance('the tower', 'the ships') is None
        r = replay([Event('she saw his face', 'Ann', 'sees', 'face', 'up on the wall',
                          'among the ships')], world=w)
        assert len(r.slips) == 1

    def test_synonyms_for_closed_values(self):
        r = replay([E('the door was closed', '', 'door', 'closed', item='door'),
                    E('she opened the door', '', 'door', 'opened', frm='closed', item='door'),
                    E('she opened the door again', '', 'door', 'open', frm='closed',
                      item='door')])
        assert len(r.slips) == 1
        r = replay([E('Tom left', 'Tom', 'present', 'left', frm='here'),
                    E('Tom sat', 'Tom', 'posture', 'sitting')])
        assert len(r.slips) == 1 and 'after leaving' in r.slips[0].why

    def test_a_value_the_sheet_cannot_read(self):
        r = replay([E('the door hung crooked', '', 'door', 'crooked', item='door')])
        assert r.skipped == {stage_sheet.UNREADABLE: 1} and r.end == []

    def test_no_one_and_no_item(self):
        r = replay([E('someone sat', '', 'posture', 'sitting'),
                    E('he took it off', 'Tom', 'worn', 'off', frm='on')])
        assert r.skipped == {stage_sheet.NO_ONE: 1, stage_sheet.NO_ITEM: 1}

    def test_position_and_facing_reach_the_asker(self):
        r = replay([E('Ann stood at the rail', 'Ann', 'position', 'at the rail'),
                    E('she faced the sea', 'Ann', 'facing', 'the sea'),
                    E('Ann sat', 'Ann', 'posture', 'sitting')])
        assert 'position: at the rail' in r.stage_at[2] and 'facing: the sea' in r.stage_at[2]


class TestUnstatedTime:
    def test_unstated_in_scenes_csv_is_no_time(self, project_dir):
        path = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(path, encoding='utf-8') as f:
            text = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text.replace('|1|evening|1 hour|', '|1|unstated|1 hour|', 1))
        fake = _fake([{'cast': [], 'events': [ev('The sun rose over the eastern hills', '',
                                                'sun', 'east')], 'questions': []}])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose='The sun rose over the eastern hills.',
                                  model='m', carry=False)
        assert r.findings == [] and r.notes == [f'1 {stage_sheet.SKY_NO_TIME}']


class TestEntryFromJson:
    """TD-3: a sheet file holds only states a replay could have written."""

    def test_values_are_normalized(self):
        e = Entry.from_json({'who': 'Ann', 'field': 'posture', 'value': 'seated'})
        assert e.value == 'sitting'
        e = Entry.from_json({'field': 'door', 'item': 'gate', 'value': 'closed'})
        assert e.value == 'shut'

    @pytest.mark.parametrize('it,why', [
        ({'who': 'Ann', 'field': 'worn', 'item': 'cloak', 'value': 'yes'}, 'value'),
        ({'who': 'Ann', 'field': 'hand_left', 'item': 'cup', 'value': 'cup'}, 'names an item'),
        ({'who': 'Ann', 'field': 'hand_either', 'value': 'cup'}, 'not one of'),
        ({'who': 'Ann', 'field': 'sees', 'value': 'x'}, 'not one of'),
        ({'who': 'Ann', 'field': 'posture', 'value': 'sitting', 'origin': 'x'}, 'origin'),
        ({'field': 'posture', 'value': 'sitting'}, 'names no one'),
        ({'who': 'Ann', 'field': 'light', 'item': 'lamp', 'value': 'lit'}, 'names someone'),
        ({'field': 'door', 'value': 'open'}, 'names no item'),
        ({'who': 'Ann', 'field': 'posture', 'value': 'sitting', 'side_guessed': True},
         'side_guessed'),
    ])
    def test_what_a_replay_cannot_write_is_refused(self, it, why):
        with pytest.raises(ValueError, match=why):
            Entry.from_json(it)

    def test_a_sheet_with_another_source_is_refused(self, tmp_path):
        path = tmp_path / 's.json'
        path.write_text(json.dumps({'format': 1, 'scene_id': SCENE, 'source': 'guess'}))
        with pytest.raises(ValueError, match='source'):
            stage_sheet.load_sheet(str(path))


class TestSources:
    """TD-4: a writer's sheet and the extractor's never overwrite each other."""

    def test_each_source_has_its_own_file(self, project_dir):
        r = replay([E('Ann sat', 'Ann', 'posture', 'sitting')])
        a = stage_sheet.write_sheet(project_dir, stage_sheet.build_sheet(SCENE, 'x', r))
        b = stage_sheet.write_sheet(project_dir, stage_sheet.build_sheet(SCENE, 'x', r,
                                                                         source='writer'))
        assert a != b and a.endswith(f'{SCENE}.json') and b.endswith(f'{SCENE}.writer.json')
        assert os.path.isfile(a) and os.path.isfile(b)
        with pytest.raises(ValueError):
            stage_sheet.sheet_path(project_dir, SCENE, 'other')


class TestProseOrder:
    """CR-7, CR-5, SF6: events replay in the prose's order, and a question
    sees the stage where its words are, not the scene's end."""

    PROSE = ('Ann sat on the step. She leaned over and lifted the basket from the cart. '
             'At last Ann stood up and went in.')

    def test_events_are_sorted_by_their_quotes(self):
        events = [E('Ann stood up', 'Ann', 'posture', 'standing', frm='down'),
                  E('Ann sat on the step', 'Ann', 'posture', 'sitting')]
        ordered, pos = stage_sheet.in_prose_order(self.PROSE, events)
        assert [e.quote for e in ordered] == ['Ann sat on the step', 'Ann stood up']
        assert pos == sorted(pos)
        assert replay(ordered).slips == []

    def test_a_misquoted_event_stays_after_the_one_before_it(self):
        events = [E('Ann sat on the step', 'Ann', 'posture', 'sitting'),
                  E('not in it', 'Ann', 'facing', 'the cart', verified=False),
                  E('lifted the basket', 'Ann', 'hand_either', 'basket')]
        ordered, _ = stage_sheet.in_prose_order(self.PROSE, events)
        assert [e.quote for e in ordered] == [e.quote for e in events]

    def test_a_question_sees_the_stage_at_its_words(self, project_dir):
        events = [ev('At last Ann stood up', 'Ann', 'posture', 'standing', frm='down'),
                  ev('Ann sat on the step', 'Ann', 'posture', 'sitting')]
        q = {'quote': 'lifted the basket from the cart', 'question': 'Can Ann reach the cart?'}
        asked = []
        fake = _fake([{'cast': ['Ann'], 'events': events, 'questions': [q]}],
                     answers=lambda a, n: [{'n': 1, 'answer': 'yes', 'why': ''}], asked=asked)
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=self.PROSE, model='m', carry=False)
        assert r.findings == []
        assert '- Ann: posture: sitting' in asked[0] and 'standing' not in asked[0]


class TestExtractionGaps:
    """SF2, SF9, SF10: an empty reply, an empty question and a name not in
    the cast are said."""

    LONG = ' '.join(['Ann walked along the harbour wall and watched the boats.'] * 10)

    def test_an_empty_reply_on_a_long_scene_is_asked_again(self, project_dir):
        replies = [{'cast': [], 'events': [], 'questions': []},
                   {'cast': ['Ann'], 'events': [ev('Ann walked along the harbour wall', 'Ann',
                                                   'position', 'the harbour wall')],
                    'questions': []}]
        prompts = []

        def fake(path, body, **k):
            prompts.append(body['messages'][0]['content'])
            return _text(replies[len(prompts) - 1])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=self.LONG, model='m', carry=False)
        assert len(prompts) == 2 and 'recorded no events' in prompts[1]
        assert r.events == 1 and r.notes == []

    def test_two_empty_replies_are_noted(self, project_dir):
        fake = _fake([{'cast': [], 'events': [], 'questions': []}])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=self.LONG, model='m', carry=False)
        assert r.notes == ['the extraction recorded no physical event in 100 words (asked '
                           'twice): nothing was checked']

    def test_a_short_scene_is_not_asked_again(self, project_dir):
        calls = []

        def fake(path, body, **k):
            calls.append(1)
            return _text({'cast': [], 'events': [], 'questions': []})
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose='Ann waited.', model='m',
                                  carry=False)
        assert calls == [1] and r.notes == []

    def test_empty_and_misquoted_questions_are_counted_apart(self, project_dir):
        qs = [{'quote': 'He waved with his free hand', 'question': ' '},
              {'quote': 'not in the scene', 'question': 'Can he?'}]
        fake = _fake([{'cast': [], 'events': [], 'questions': qs}])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=HARBOUR, model='m', carry=False)
        assert '1 question(s) with no question: not asked' in r.notes
        assert '1 question(s) quote words not in the scene: not asked' in r.notes

    def test_a_name_not_in_the_cast_is_noted(self, project_dir):
        events = [ev('Ann sat on the step', 'Ann', 'posture', 'sitting'),
                  ev('Later Ann sat down beside him', 'the girl', 'posture', 'sitting')]
        fake = _fake([{'cast': ['Ann', 'Tom'], 'events': events, 'questions': []}])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=HARBOUR, model='m', carry=False)
        assert any(n.startswith('1 name(s) in the events not in the cast (the girl)')
                   for n in r.notes)


class TestQuestionAgreement:
    """T3: answers are matched by number, whatever order an asking lists them."""

    def test_three_questions(self, project_dir):
        prose = 'Ann reached the lamp. Ann passed the cup. Ann saw the boat.'
        qs = [{'quote': 'Ann reached the lamp', 'question': 'Can Ann reach the lamp?'},
              {'quote': 'Ann passed the cup', 'question': 'Can Ann pass the cup?'},
              {'quote': 'Ann saw the boat', 'question': 'Can Ann see the boat?'}]
        said = {1: ('yes', 'yes'), 2: ('no', 'no'), 3: ('no', 'yes')}
        fake = _fake([{'cast': ['Ann'], 'events': [], 'questions': qs}],
                     answers=lambda a, n: [{'n': i, 'answer': said[i][a - 1], 'why': f'q{i}'}
                                           for i in (range(n, 0, -1) if a == 2
                                                     else range(1, n + 1))])
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=prose, model='m', carry=False)
        assert [f.scene_quote for f in r.findings] == ['Ann passed the cup']
        assert 'No: q2' in r.findings[0].explanation
        assert '1 question(s) got split answers: not findings' in r.notes


class TestCarryNotes:
    """T4, SF8: each way carrying can fail is said; a bug isn't swallowed."""

    def test_an_unreadable_order_is_said(self, project_dir, monkeypatch):
        from storyforge import ledger
        monkeypatch.setattr(ledger, 'scene_order',
                            lambda p: (_ for _ in ()).throw(ValueError('no seq')))
        assert stage_sheet.carried_opening(project_dir, SCENE) == (
            [], 'no state carried over (the reading order could not be read: no seq)')

    def test_a_bug_in_the_order_is_not_swallowed(self, project_dir, monkeypatch):
        from storyforge import ledger
        monkeypatch.setattr(ledger, 'scene_order',
                            lambda p: (_ for _ in ()).throw(KeyError('bug')))
        with pytest.raises(KeyError):
            stage_sheet.carried_opening(project_dir, SCENE)

    def test_a_malformed_previous_sheet_is_said(self, project_dir):
        path = stage_sheet.sheet_path(project_dir, PREV)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write('{"format": 1, "scene_id": "x", "end": [{"field": "sees"}]}')
        opening, note = stage_sheet.carried_opening(project_dir, SCENE)
        assert opening == [] and 'stage sheet could not be used' in note

    def test_a_previous_scene_with_no_prose_is_said(self, project_dir):
        r = replay([E('Ann sat', 'Ann', 'posture', 'sitting')])
        stage_sheet.write_sheet(project_dir, stage_sheet.build_sheet(PREV, 'x', r))
        os.remove(os.path.join(project_dir, 'scenes', f'{PREV}.md'))
        assert stage_sheet.carried_opening(project_dir, SCENE) == (
            [], f'no state carried over: {PREV} has no prose')


@pytest.mark.blocking_read
class TestGateRecordsTheMethod:
    """CR-2, T2: gate-prose.csv records how the blocking was checked, and a
    re-check skips only when it was checked the same way."""

    _run = TestGateUsesTheStageSheet._run

    def _gated(self, project_dir, tmp_path, monkeypatch, method):
        import subprocess
        subprocess.run(['git', 'init', '-q', project_dir], check=True)
        events = [ev('Ann sat on the step', 'Ann', 'posture', 'sitting')]
        result, calls = self._run(project_dir, tmp_path, monkeypatch,
                                  {'cast': [], 'events': events, 'questions': []}, method=method)
        assert result.committed
        return calls

    def _recheck(self, project_dir, tmp_path, monkeypatch, method):
        monkeypatch.setattr(gate, 'GATE_BLOCKING_METHOD', method)
        calls = []

        def fake(path, body, **k):
            schema = (body.get('output_config') or {}).get('format', {}).get('schema', {})
            if 'tools' in body:
                return _text({'findings': [], 'kept': []})
            if 'verdicts' in schema.get('properties', {}):
                return _text({'verdicts': []})
            kind = _kind(body)
            calls.append(kind)
            if kind == 'extract':
                return _text({'cast': [], 'events': [], 'questions': []})
            if 'other_quote' in json.dumps(schema):
                calls[-1] = 'read'
                return _text({'findings': []})
            return _text({'commitments': []})
        with patch('storyforge.api._api_request', side_effect=fake):
            result = gate.gate_scene(project_dir, SCENE, command='recheck',
                                     log_dir=str(tmp_path / 'logs2'), extract_model='m',
                                     check_model='m')
        return result, calls

    def test_the_stage_sheet_is_recorded_as_such(self, project_dir, tmp_path, monkeypatch):
        self._gated(project_dir, tmp_path, monkeypatch, 'stage-sheet')
        assert gate._prose_table(project_dir)[SCENE]['blocking'] == 'stage-sheet'

    def test_a_sheet_gated_scene_still_gets_the_read(self, project_dir, tmp_path, monkeypatch):
        self._gated(project_dir, tmp_path, monkeypatch, 'stage-sheet')
        result, calls = self._recheck(project_dir, tmp_path, monkeypatch, 'read')
        assert 'read' in calls and not result.blocking_skipped
        assert result.blocking_note == ('blocking read run: its last gate checked its blocking '
                                        'by stage-sheet, not read')

    def test_a_read_gated_scene_still_gets_the_sheet(self, project_dir, tmp_path, monkeypatch):
        self._gated(project_dir, tmp_path, monkeypatch, 'read')
        assert gate._prose_table(project_dir)[SCENE]['blocking'] == 'read'
        result, calls = self._recheck(project_dir, tmp_path, monkeypatch, 'stage-sheet')
        assert 'extract' in calls and not result.blocking_skipped
        assert os.path.isfile(stage_sheet.sheet_path(project_dir, SCENE))

    def test_the_same_method_is_skipped(self, project_dir, tmp_path, monkeypatch):
        self._gated(project_dir, tmp_path, monkeypatch, 'stage-sheet')
        result, calls = self._recheck(project_dir, tmp_path, monkeypatch, 'stage-sheet')
        assert 'extract' not in calls and result.blocking_skipped
        assert result.blocking_note.startswith('stage sheet skipped')

    def test_record_prose_takes_a_method(self, project_dir):
        with pytest.raises(ValueError, match='blocking must be one of'):
            gate.record_prose(project_dir, SCENE, 'x', blocking='yes')

    def test_an_ask_failure_is_a_gate_error(self, project_dir, tmp_path, monkeypatch):
        """T7: the questions failing loses the scene's check, loudly."""
        q = {'quote': 'He waved with his free hand', 'question': 'Can he wave?'}
        with pytest.raises(gate.GateError, match='stage sheet questions failed twice'):
            self._run(project_dir, tmp_path, monkeypatch,
                      {'cast': [], 'events': [], 'questions': [q]})


class TestAcceptedSheetFindings:
    """T8: an accepted stage-sheet finding covers a new wording of it on the
    same unchanged paragraphs, as the read's do."""

    def _row(self, f, prose):
        keys = gate._quote_paragraphs(f.scene_quote, prose) | gate._quote_paragraphs(
            f.established_quote, prose)
        return {'command': gate.ACCEPTED, 'paragraphs': ';'.join(sorted(keys)),
                'source': SCENE, 'finding': f'{BLOCKING_CODE} x'}

    def test_a_one_sided_finding(self):
        r = replay([E('the sun in the west', '', 'sun', 'west')], time_of_day='morning')
        f = stage_sheet.to_finding(SCENE, r.slips[0])
        prose = 'Morning.\n\nThe sun in the west lit the rail.'
        assert f.established_quote == f.scene_quote
        assert gate._accepted_blocking_covers(self._row(f, prose), f, SCENE, prose)

    def test_a_yes_no_finding(self):
        from storyforge.checker import Finding
        prose = 'Ann sat.\n\nShe lifted the basket from the cart.'
        f = Finding(kind='contradiction', code=BLOCKING_CODE,
                    scene_quote='lifted the basket from the cart', established_scene=SCENE,
                    established_quote='lifted the basket from the cart', fact_id='',
                    explanation='(impossible, stage sheet: asked 2 times) x')
        row = self._row(f, prose)
        again = Finding(kind='contradiction', code=BLOCKING_CODE,
                        scene_quote='She lifted the basket', established_scene=SCENE,
                        established_quote='She lifted the basket', fact_id='',
                        explanation='(impossible, stage sheet: asked 2 times) other words')
        assert gate._accepted_blocking_covers(row, again, SCENE, prose)
        moved = prose.replace('She lifted', 'Then she lifted')
        assert not gate._accepted_blocking_covers(row, f, SCENE, moved)
