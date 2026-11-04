"""The spine and architecture stages write their tier files.

The status ladder, the level floor checks (`score --level 3|4`) and the
boundary diffs read `reference/spine.csv` and `reference/architecture.csv`.
Only extraction wrote them, so a novel built with `storyforge elaborate`
showed the spine as not started after its spine stage, and status sent the
author back to run it again (found on the Gawain novel, G-015)."""

import os

import pytest

from storyforge.cmd_elaborate import main
from storyforge.elaborate import _read_csv
from storyforge.status import ladder_states

SPINE_REPLY = (
    '```scenes-csv\n'
    'id|seq|title|summary|act|status\n'
    'knight-offers-game|1|The Game|A green knight offers a blow for a blow.|1|spine\n'
    'gawain-strikes-blow|2|The Blow|Gawain strikes off the head.|1|spine\n'
    'gawain-rides-out|3|Rides Out|Gawain arms and rides north.|1|spine\n'
    'gawain-keeps-girdle|4|The Girdle|Gawain keeps the girdle back.|2|spine\n'
    'knight-nicks-neck|5|Three Blows|The third blow nicks his neck.|3|spine\n'
    '```\n'
    '```intent-csv\n'
    'id|function\n'
    'knight-offers-game|The challenge puts the court on trial\n'
    'gawain-strikes-blow|Gawain binds himself to die in a year\n'
    'gawain-rides-out|He leaves the court for the wilderness\n'
    'gawain-keeps-girdle|His one breach of faith\n'
    'knight-nicks-neck|The covenant is kept and judged\n'
    '```\n'
)

ARCH_REPLY = (
    '```scenes-csv\n'
    'id|seq|title|summary|act|pov|spine_event|status\n'
    'knight-offers-game|1|The Game|A green knight offers a blow.|1|gawain|knight-offers-game|architecture\n'
    'arthur-takes-the-axe|2|The Axe|Arthur takes the axe in anger.|1|gawain|knight-offers-game|architecture\n'
    'gawain-strikes-blow|3|The Blow|Gawain strikes.|1|gawain||architecture\n'
    '```\n'
    '```intent-csv\n'
    'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point\n'
    'knight-offers-game|Challenge|action|ease to awe|honor|+/-|action\n'
    'arthur-takes-the-axe|Shame|action|awe to anger|honor|-/+|action\n'
    'gawain-strikes-blow|Oath|action|dread to resolve|honor|+/-|action\n'
    '```\n'
)


@pytest.fixture
def novel(project_dir, monkeypatch, mock_git, mock_costs):
    ref = os.path.join(project_dir, 'reference')
    for name in ('scenes.csv', 'scene-intent.csv', 'scene-briefs.csv', 'spine.csv',
                 'architecture.csv'):
        path = os.path.join(ref, name)
        if os.path.exists(path):
            os.remove(path)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root', lambda: project_dir)
    return project_dir


def _run(mock_api, stage, reply):
    mock_api.set_response(reply)
    try:
        main(['--stage', stage])
    except SystemExit as e:
        return e.code
    return 0


def test_spine_stage_writes_spine_csv(novel, mock_api):
    _run(mock_api, 'spine', SPINE_REPLY)
    rows = _read_csv(os.path.join(novel, 'reference', 'spine.csv'))
    assert [r['id'] for r in rows] == ['knight-offers-game', 'gawain-strikes-blow',
                                       'gawain-rides-out', 'gawain-keeps-girdle',
                                       'knight-nicks-neck']
    assert rows[0]['summary'] == 'A green knight offers a blow for a blow.'
    assert rows[0]['function'] == 'The challenge puts the court on trial'
    assert [r['act'] for r in rows] == ['1', '1', '1', '2', '3']


def test_spine_rung_is_solid_after_the_spine_stage(novel, mock_api):
    _run(mock_api, 'spine', SPINE_REPLY)
    spine = [r for r in ladder_states(novel) if r['name'] == 'spine'][0]
    assert spine['state'] == 'solid', spine


def test_architecture_stage_writes_architecture_csv(novel, mock_api):
    _run(mock_api, 'spine', SPINE_REPLY)
    _run(mock_api, 'architecture', ARCH_REPLY)
    rows = {r['id']: r for r in _read_csv(os.path.join(novel, 'reference', 'architecture.csv'))}
    assert list(rows) == ['knight-offers-game', 'arthur-takes-the-axe', 'gawain-strikes-blow']
    assert rows['arthur-takes-the-axe']['spine_event'] == 'knight-offers-game'
    # A spine scene left blank serves itself
    assert rows['gawain-strikes-blow']['spine_event'] == 'gawain-strikes-blow'
    assert rows['arthur-takes-the-axe']['value_shift'] == '-/+'
    assert rows['arthur-takes-the-axe']['pov'] == 'gawain'
    scenes = {r['id']: r for r in _read_csv(os.path.join(novel, 'reference', 'scenes.csv'))}
    assert scenes['arthur-takes-the-axe']['architecture_scene'] == 'arthur-takes-the-axe'
    assert scenes['gawain-rides-out']['architecture_scene'] == ''


def test_prompts_ask_for_the_tier_columns(novel):
    from storyforge import prompts_elaborate as pe
    plugin = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert 'id|seq|title|summary|act|status' in pe.build_spine_prompt(novel, plugin, 'seed')
    assert ('id|seq|title|summary|act|pov|spine_event|status'
            in pe.build_architecture_prompt(novel, plugin))
