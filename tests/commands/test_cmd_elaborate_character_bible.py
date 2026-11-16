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
    assert (row['type'], row['origin'], row['introduced_by']) == ('trait', 'plan', 'elaborate')


# ---------------------------------------------------------------------------
# #697's review: a bible block that can't be written holds the phase (SF-5);
# a graphic novel ignores rows; the prompts (T-10)
# ---------------------------------------------------------------------------

def _report(proj):
    import glob
    paths = sorted(glob.glob(os.path.join(proj, 'working', 'validation', 'validate-*.md')))
    with open(paths[-1]) as f:
        return f.read()


def test_a_bad_facts_block_is_a_blocking_failure(prose, mock_api, capsys):
    """SF-5: it was one ERROR line, then the stage committed and advanced.
    Now the stage's report has it as blocking, so the phase holds (the
    fixture's own blocking failures hold it too, so the report is what's
    checked)."""
    from storyforge import ledger
    before_rows = len(ledger.load(prose))
    _run(mock_api, 'architecture', ARCH_REPLY + (
        '```bible-facts-csv\n'
        'type|subject|statement\n'
        'Trait|arthur|Is the king\n'
        '```\n'))
    out = capsys.readouterr()
    text = out.out + out.err
    assert "bible-facts-csv block wasn't written" in text and 'elaborate-architecture.log' in text
    assert len(ledger.load(prose)) == before_rows
    report = _report(prose)
    assert '**Passed:** False' in report and "bible-facts-csv block wasn't written" in report


def test_a_good_facts_block_is_no_failure(prose, mock_api):
    _run(mock_api, 'architecture', ROWS_REPLY)
    assert "block wasn't written" not in _report(prose)


def test_a_row_with_a_stray_pipe_is_refused(prose, mock_api, capsys):
    """SF-3: it would shift every later cell."""
    from storyforge import ledger
    before_rows = len(ledger.load(prose))
    _run(mock_api, 'architecture', ARCH_REPLY + (
        '```bible-facts-csv\n'
        'type|subject|statement|known_by|category\n'
        'trait|arthur|Loves the sea | hates rivers||role\n'
        '```\n'))
    out = capsys.readouterr()
    assert 'cells where the header has 5' in out.out + out.err
    assert len(ledger.load(prose)) == before_rows


def test_a_graphic_novel_reply_with_rows_writes_none(novel, mock_api, capsys):
    from storyforge import ledger
    before_rows = len(ledger.load(novel))
    _run(mock_api, 'architecture', ROWS_REPLY)
    out = capsys.readouterr()
    assert "left out the reply's bible-facts-csv block" in out.out + out.err
    assert len(ledger.load(novel)) == before_rows
    assert '## Arthur: supporting' in _bible(novel)


def test_a_prose_spine_writes_facts_and_notes_but_no_voices(prose, mock_api, capsys):
    """#702: a stage's voice lines would be a model's; the block is left
    out with a NOTE, and character-voices.csv holds the author's lines."""
    from storyforge import bibles, ledger
    _run(mock_api, 'spine', ARCH_REPLY.replace('|architecture\n', '|spine\n') + (
        '```bible-facts-csv\n'
        'type|subject|statement|known_by|category\n'
        'trait|gawain|Wants to keep his word||want\n'
        '```\n'
        '```character-voices-csv\n'
        'character|line\n'
        'gawain|"I gave my word."\n'
        '```\n'
        '```bible-notes\n'
        '- Courtly, cold, Christmas.\n'
        '```\n'))
    row = next(r for r in ledger.load(prose) if r['statement'] == 'Wants to keep his word')
    assert row['introduced_by'] == bibles.STAGE_WRITER
    assert bibles.read_voices(prose)[0] == {}
    out = capsys.readouterr()
    assert "left out the reply's character-voices-csv block" in out.out + out.err
    assert 'Courtly, cold' in bibles.notes_text(prose)
    assert _bible(prose) == SPINE_BIBLE   # the essay is read-only


def test_prose_stage_prompts_ask_for_rows(project_dir, plugin_dir):
    from storyforge import prompts_elaborate as pe
    for prompt in (pe.build_spine_prompt(project_dir, plugin_dir, 'seed'),
                   pe.build_architecture_prompt(project_dir, plugin_dir)):
        assert '```bible-facts-csv' in prompt and '```character-voices-csv' not in prompt
        assert '```character-bible' not in prompt and '```world-bible' not in prompt


def test_graphic_novel_stage_prompts_keep_the_essays(project_dir_gn, plugin_dir):
    from storyforge import prompts_elaborate as pe
    spine = pe.build_spine_prompt(project_dir_gn, plugin_dir, 'seed')
    arch = pe.build_architecture_prompt(project_dir_gn, plugin_dir)
    assert '```character-bible' in spine and 'bible-facts-csv' not in spine
    assert '```world-bible' in arch and 'bible-facts-csv' not in arch
