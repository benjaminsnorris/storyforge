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


def E(quote, who, field, to, frm='', item=''):
    return Event(quote=quote, who=who, field=field, item=item, from_=frm, to=to)


def _quotes(r):
    return [(s.event.quote, s.against.quote if s.against else None) for s in r.slips]


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

    def test_an_untold_hand_forgets_both(self):
        """When which hand can't be told, neither is known after."""
        r = replay([E('her hands were empty', 'Ann', 'hand_left', 'empty'),
                    E('her right was empty', 'Ann', 'hand_right', 'empty'),
                    E('she took the cup', 'Ann', 'hand_either', 'cup', frm='empty'),
                    E('she took the jug in her left', 'Ann', 'hand_left', 'jug', frm='empty')])
        assert r.slips == []


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

    def test_an_unknown_landmark_is_not_checked(self):
        r = replay([E('at dusk', '', 'time', 'dusk'),
                    E('the sun over the hill', '', 'sun', 'the hill')])
        assert r.slips == []

    def test_a_face_seen_too_far_away(self):
        w = World(distances={frozenset(('the wall', 'the ships')): 2000.0})
        r = replay([Event('she saw his face', 'Helen', 'sees', 'face', 'the wall',
                          'the ships')], world=w)
        assert len(r.slips) == 1 and '2000 m' in r.slips[0].why


class TestWhatIsNotChecked:
    def test_a_carried_state_makes_no_finding(self):
        carried = [Entry('Ann', 'posture', '', 'sitting', 'Ann sat', origin='carried')]
        r = replay([E('Ann stood up', 'Ann', 'posture', 'standing', frm='down'),
                    E('Ann stood up again', 'Ann', 'posture', 'standing', frm='down')],
                   opening=carried)
        assert [s.event.quote for s in r.slips] == ['Ann stood up again']

    def test_a_misquoted_event_makes_no_finding_and_is_counted(self):
        bad = E('Ann sat on a chair', 'Ann', 'posture', 'sitting')
        bad.verified = False
        r = replay([bad, E('Ann sat down', 'Ann', 'posture', 'sitting', frm='standing')])
        assert r.slips == [] and r.unchecked == 1


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
    PROSE = ('Priam sat in the car behind the wagon. He reached back and lifted the box '
             'from the wagon bed.')
    EVENTS = [ev('Priam sat in the car behind the wagon', 'Priam', 'posture', 'sitting')]
    Q = {'quote': 'lifted the box from the wagon bed',
         'question': 'Can Priam, seated in the car behind the wagon, lift the box from the '
                     'wagon ahead of him?'}

    def _run(self, project_dir, answers):
        asked = []
        fake = _fake([{'cast': ['Priam'], 'events': self.EVENTS, 'questions': [self.Q]}],
                     answers=answers, asked=asked)
        with patch('storyforge.api._api_request', side_effect=fake):
            r = check_stage_sheet(project_dir, SCENE, prose=self.PROSE, model='m',
                                  carry=False)
        return r, asked

    def test_two_noes_make_a_finding(self, project_dir):
        r, asked = self._run(project_dir, lambda a, n: [
            {'n': 1, 'answer': 'no', 'why': 'The wagon is ahead and he sits behind it.'}])
        assert len(asked) == stage_sheet.ASKINGS == 2
        assert len(r.findings) == 1 and r.asked == 1
        f = r.findings[0]
        assert f.scene_quote == self.Q['quote'] and f.code == BLOCKING_CODE
        assert 'asked 2 times' in f.explanation and 'wagon is ahead' in f.explanation

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
        assert '- Priam: posture: sitting' in asked[0]
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
        q2 = {'quote': 'He reached back', 'question': 'Can he reach back?'}
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
