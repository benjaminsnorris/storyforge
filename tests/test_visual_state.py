"""Tests for the visual-state transition log (#278 phase 2).

The fixture project's reading order comes from its chapter map:
`act1-sc01` -> `act1-sc02` -> `act2-sc01`. The rows below use those ids and
evidence quotes that really appear in those scene files, because the pre-pass
checks the evidence against the prose.
"""

import os

import pytest

from storyforge import visual_state as vs

ROWS = [
    # entity, from_scene, state, evidence
    ('dorren-clothing', 'act1-sc01', 'office dress, brass calipers in hand',
     'held her breath'),
    ('dorren-clothing', 'act2-sc01', 'travel coat, boots, compass on a cord',
     'She checked her compass'),
    ('master-survey', 'act1-sc02', 'blank where the village should be',
     'Blank parchment'),
]


def _write_state(project_dir, rows=ROWS):
    path = os.path.join(project_dir, 'reference', 'visual-state.csv')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('|'.join(vs.STATE_COLUMNS) + '\n')
        for row in rows:
            f.write('|'.join(row) + '\n')
    return path


# ============================================================================
# Resolution
# ============================================================================

def test_state_at_walks_forward_from_the_last_transition(project_dir):
    _write_state(project_dir)
    # act1-sc02 is after act1-sc01 and before act2-sc01
    at = vs.state_at(project_dir, 'act1-sc02')
    assert at['dorren-clothing'] == 'office dress, brass calipers in hand'
    assert at['master-survey'] == 'blank where the village should be'


def test_state_at_the_transition_scene_uses_the_new_state(project_dir):
    """The boundary: a transition takes effect AT its own scene, not after it."""
    _write_state(project_dir)
    at = vs.state_at(project_dir, 'act2-sc01')
    assert at['dorren-clothing'] == 'travel coat, boots, compass on a cord'


def test_an_entity_with_no_transition_yet_is_absent(project_dir):
    _write_state(project_dir)
    at = vs.state_at(project_dir, 'act1-sc01')
    assert 'master-survey' not in at, 'master-survey first changes at act1-sc02'


def test_the_later_row_wins_when_two_transitions_share_a_scene(project_dir):
    _write_state(project_dir, [
        ('great-lamp', 'act1-sc01', 'first row', 'held her breath'),
        ('great-lamp', 'act1-sc01', 'second row', 'held her breath'),
    ])
    assert vs.state_at(project_dir, 'act1-sc01')['great-lamp'] == 'second row'


def test_a_scene_with_no_reading_position_resolves_empty(project_dir, capsys):
    """new-x1 exists in scenes.csv but not in the chapter map, which wins."""
    _write_state(project_dir)
    assert vs.state_at(project_dir, 'new-x1') == {}
    assert 'no reading position' in capsys.readouterr().out


def test_entities_lists_every_distinct_entity_sorted(project_dir):
    _write_state(project_dir)
    assert vs.entities(project_dir) == ['dorren-clothing', 'master-survey']


def test_a_row_with_no_entity_is_skipped_loudly(project_dir, capsys):
    _write_state(project_dir, [('', 'act1-sc01', 'orphaned state', '')])
    assert vs.read_transitions(project_dir) == []
    assert 'no entity' in capsys.readouterr().out


def test_no_state_file_is_empty_not_an_error(project_dir):
    os.remove(os.path.join(project_dir, 'reference', 'visual-state.csv'))
    assert vs.read_transitions(project_dir) == []
    assert vs.state_at(project_dir, 'act1-sc01') == {}
    assert vs.entities(project_dir) == []


def test_write_transitions_emits_lf_only(project_dir):
    vs.write_transitions(project_dir, [
        {'entity': 'x', 'from_scene': 'act1-sc01', 'state': 'y',
         'evidence': 'z'},
    ])
    with open(os.path.join(project_dir, 'reference', 'visual-state.csv'),
              'rb') as f:
        assert b'\r' not in f.read()


def test_write_transitions_round_trips(project_dir):
    rows = [{'entity': e, 'from_scene': s, 'state': st, 'evidence': ev}
            for e, s, st, ev in ROWS]
    vs.write_transitions(project_dir, rows)
    assert vs.read_transitions(project_dir) == rows
