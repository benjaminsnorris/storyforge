"""#552: the map and architecture stages write enum cells with descriptions
("action: Arthur, stung by the laughter, rises"), which validate rejects
(Gawain G-021, 67 cells); the scene count in key-decisions wins (Beowulf
B-016); split scenes keep their architecture_scene (Beowulf B-022)."""

import os

import pytest

from storyforge.cmd_elaborate import main, split_enum_descriptions
from storyforge.elaborate import _read_csv_as_map


def test_a_described_turning_point_keeps_its_type_and_moves_the_text():
    row = {'id': 'a', 'turning_point': 'action: Arthur, stung by the laughter, rises',
           'function': 'Challenge'}
    assert split_enum_descriptions(row, 'scene-intent.csv')
    assert row['turning_point'] == 'action'
    assert row['function'] == 'Challenge (turning_point: Arthur, stung by the laughter, rises)'


@pytest.mark.parametrize('cell', ['revelation — the host is the knight',
                                  'Revelation - the host is the knight'])
def test_other_separators(cell):
    row = {'id': 'a', 'turning_point': cell, 'function': ''}
    split_enum_descriptions(row, 'scene-intent.csv')
    assert row['turning_point'] == 'revelation'
    assert row['function'] == 'the host is the knight'


@pytest.mark.parametrize('row', [
    {'id': 'a', 'turning_point': 'twist: the host'},        # not a valid value
    {'id': 'a', 'time_of_day': 'midday'},                     # validate's to report
    {'id': 'a', 'turning_point': 'action'},                   # already clean
])
def test_cells_it_cannot_split_are_left(row):
    before = dict(row)
    assert split_enum_descriptions(row, 'scene-intent.csv' if 'turning_point' in row
                                   else 'scenes.csv') == []
    assert row == before


def test_a_row_without_function_does_not_get_one():
    row = {'id': 'a', 'turning_point': 'action: she strikes'}
    split_enum_descriptions(row, 'scene-intent.csv')
    assert row == {'id': 'a', 'turning_point': 'action'}


ARCH_REPLY = (
    '```scenes-csv\n'
    'id|seq|title|summary|act|pov|spine_event|status\n'
    'act1-sc01|1|The Game|A knight offers a game.|1|Dorren Hayle|act1-sc01|architecture\n'
    '```\n'
    '```intent-csv\n'
    'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point\n'
    'act1-sc01|Challenge|action|ease to awe|honor|+/-|action: the knight rides in\n'
    '```\n'
)


def test_the_architecture_stage_writes_the_type(project_dir, monkeypatch, mock_git,
                                                mock_costs, mock_api):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root', lambda: project_dir)
    mock_api.set_response(ARCH_REPLY)
    try:
        main(['--stage', 'architecture'])
    except SystemExit:
        pass
    row = _read_csv_as_map(os.path.join(project_dir, 'reference', 'scene-intent.csv'))['act1-sc01']
    assert row['turning_point'] == 'action'
    assert 'the knight rides in' in row['function']


def test_the_map_prompt_asks_for_the_cells(project_dir):
    from storyforge.prompts_elaborate import build_map_prompt
    plugin = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    p = build_map_prompt(project_dir, plugin)
    assert '|status|architecture_scene|told_by\n' in p
    assert 'for a scene split off one' in p
    assert 'exactly one of morning, afternoon, evening, night, dawn, dusk' in p
    assert 'Key Decisions records a scene count' in p
    assert 'An enum cell holds only its value' in p
