"""Regression tests for governor d7e98f3: Elias's burns were given to Tessa,
then propagated to 80 scenes. A state's character must be present where the
state is acquired before hone spreads it, and hone's mapping prompt shows who
is present."""

import os

from storyforge.elaborate import _read_csv_as_map, present_in_scene, state_owner_absent


def _ref(tmp_path, states):
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'scenes.csv').write_text('id|seq|pov\nfire|1|tessa\nafter|2|tessa\nlater|3|elias\n')
    (ref / 'scene-intent.csv').write_text(
        'id|characters|on_stage\nfire|tessa;elias|tessa;elias\nafter|tessa|tessa\nlater|elias;tessa|elias;tessa\n')
    (ref / 'scene-briefs.csv').write_text(
        'id|physical_state_in|physical_state_out\nfire||\nafter||\nlater||\n')
    (ref / 'characters.csv').write_text('id|name|role|aliases\ntessa|Tessa|lead|\nelias|Elias|lead|\n')
    (ref / 'physical-states.csv').write_text(
        'id|character|description|category|acquired|resolves|action_gating\n' + states)
    return str(ref)


def test_present_in_scene():
    assert present_in_scene({'pov': 'Tessa'}, {'on_stage': 'Elias; Pell'}) == {'tessa', 'elias', 'pell'}
    assert present_in_scene({'pov': ''}, {'on_stage': '', 'characters': 'a'}) == {'a'}
    assert present_in_scene({}, {}) == set()


def test_owner_absent_only_when_presence_is_known():
    scenes = {'s': {'pov': 'tessa'}, 'u': {'pov': ''}}
    intent = {'s': {'on_stage': 'tessa'}}
    assert state_owner_absent({'character': 'elias', 'acquired': 's'}, scenes, intent)
    assert not state_owner_absent({'character': 'Tessa', 'acquired': 's'}, scenes, intent)
    assert not state_owner_absent({'character': 'elias', 'acquired': 'u'}, scenes, intent)
    assert not state_owner_absent({'character': 'elias', 'acquired': 'gone'}, scenes, intent)


def test_propagation_refuses_a_state_whose_owner_is_absent(tmp_path):
    from storyforge.hone import propagate_physical_states
    ref = _ref(tmp_path, 'burns-elias|elias|burned hands|injury|after|never|true\n'
                         'burns-tessa|tessa|burned arm|injury|fire|never|true\n')
    result = propagate_physical_states(ref)
    assert result['refused'] == ['burns-elias']
    briefs = _read_csv_as_map(os.path.join(ref, 'scene-briefs.csv'))
    assert 'burns-elias' not in ';'.join(b['physical_state_out'] + b['physical_state_in']
                                         for b in briefs.values())
    assert 'burns-tessa' in briefs['later']['physical_state_in']


def test_mapping_prompt_lists_who_is_present(tmp_path):
    from storyforge.hone import build_mapping_prompt
    ref = _ref(tmp_path, '')
    batch = [{'key': 'k', 'text': 'burned hands', 'type': '', 'scenes': ['fire']}]
    prompt = build_mapping_prompt('physical-states', ref, batch)
    assert '[present in fire: elias, tessa]' in prompt
