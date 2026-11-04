"""A later stage's character-bible block adds entries to the bible.

The architecture prompt asks for "additional character entries", and the
stage wrote the block over the whole file, so the spine's protagonist and
antagonist entries were lost (found on the Gawain novel, G-016)."""

import os

import pytest

from storyforge.cmd_elaborate import main

ARCH_REPLY = (
    '```scenes-csv\n'
    'id|seq|title|summary|act|pov|spine_event|status\n'
    'knight-offers-game|1|The Game|A knight offers a game.|1|gawain|knight-offers-game|architecture\n'
    '```\n'
    '```intent-csv\n'
    'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point\n'
    'knight-offers-game|Challenge|action|ease to awe|honor|+/-|action\n'
    '```\n'
    '```character-bible\n'
    '## Arthur: supporting\n\nThe king.\n'
    '```\n'
)

SPINE_BIBLE = '# Character Bible\n\n## Gawain: protagonist\n\nThe knight.\n'


@pytest.fixture
def novel(project_dir, monkeypatch, mock_git, mock_costs):
    with open(os.path.join(project_dir, 'reference', 'character-bible.md'), 'w') as f:
        f.write(SPINE_BIBLE)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root', lambda: project_dir)
    return project_dir


def _bible(proj):
    with open(os.path.join(proj, 'reference', 'character-bible.md')) as f:
        return f.read()


def _run(mock_api, stage, reply):
    mock_api.set_response(reply)
    try:
        main(['--stage', stage])
    except SystemExit:
        pass


def test_architecture_entries_are_added_to_the_bible(novel, mock_api):
    _run(mock_api, 'architecture', ARCH_REPLY)
    bible = _bible(novel)
    assert '## Gawain: protagonist' in bible
    assert '## Arthur: supporting' in bible
    assert bible.index('Gawain') < bible.index('Arthur')


def test_spine_writes_the_bible_whole(novel, mock_api):
    _run(mock_api, 'spine', ARCH_REPLY.replace('|architecture\n', '|spine\n'))
    bible = _bible(novel)
    assert '## Arthur: supporting' in bible
    assert 'Gawain: protagonist' not in bible
