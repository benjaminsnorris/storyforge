"""A later stage's character-bible block adds entries to the bible.

The architecture prompt asks for "additional character entries", and the
stage wrote the block over the whole file, so the spine's protagonist and
antagonist entries were lost (found on the Gawain novel, G-016). Since #657
only a graphic novel's stages write the essay; a prose book's write rows,
and its essay is left as it is."""

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


def _setup(proj, monkeypatch):
    with open(os.path.join(proj, 'reference', 'character-bible.md'), 'w') as f:
        f.write(SPINE_BIBLE)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root', lambda: proj)
    return proj


@pytest.fixture
def novel(project_dir_gn, monkeypatch, mock_git, mock_costs):
    """A graphic novel: its stages still write the essay."""
    return _setup(project_dir_gn, monkeypatch)


@pytest.fixture
def prose(project_dir, monkeypatch, mock_git, mock_costs):
    return _setup(project_dir, monkeypatch)


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


ROWS_REPLY = ARCH_REPLY + (
    '```bible-facts-csv\n'
    'type|subject|statement|known_by|category\n'
    'trait|arthur|Is the king||role\n'
    '```\n'
)


def test_a_prose_book_writes_rows_and_leaves_the_essay(prose, mock_api, capsys):
    """#657: the essay is read-only reference until converted; the reply's
    essay block is left out with a NOTE and its facts block becomes rows."""
    from storyforge import ledger
    _run(mock_api, 'architecture', ROWS_REPLY)
    assert _bible(prose) == SPINE_BIBLE
    out = capsys.readouterr()
    assert 'left out the reply\'s character-bible block' in out.out + out.err
    row = next(r for r in ledger.load(prose) if r['statement'] == 'Is the king')
    assert (row['type'], row['origin'], row['introduced_by']) == ('trait', 'plan', 'bibles')
