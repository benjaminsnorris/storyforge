"""A series' character sheets (`series.characters`): one appearance sheet per
character, read in place, sent only with the scenes the character is in."""

import os

import pytest

from storyforge import checker, series


def _yaml(project_dir, block):
    path = os.path.join(project_dir, 'storyforge.yaml')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.rstrip('\n') + '\n\n' + block)


def _sheet(cid, body):
    return f'---\ncanon_id: {cid}\ncanon_type: character\n---\n\n# {cid}\n\n{body}\n'


@pytest.fixture
def sheets(tmp_path):
    """A series' character sheets outside the project, like
    `homer/series-bible/characters`."""
    d = tmp_path / 'homer' / 'series-bible' / 'characters'
    d.mkdir(parents=True)
    (d / 'README.md').write_text('# How they look\n\nThe format.\n')
    (d / 'dorren-hayle.md').write_text(_sheet('dorren-hayle', 'Grey eyes; a burn scar on the left palm.'))
    (d / 'tessa-merrin.md').write_text(_sheet('tessa-merrin', 'Red hair cut short.'))
    (d / 'nobody-here.md').write_text(_sheet('nobody-here', 'Not in this book.'))
    return d


def _configure(project_dir, sheets):
    _yaml(project_dir, f'series:\n  characters: {os.path.relpath(sheets, project_dir)}\n')


class TestConfig:
    def test_no_block_is_no_sheets(self, project_dir):
        assert series.characters_path(project_dir) == ''
        assert series.character_sheets(project_dir) == {}
        assert series.cast_sheets(project_dir, {'pov': 'dorren-hayle'}) == []

    def test_characters_alone_is_a_block(self, project_dir, sheets):
        _configure(project_dir, sheets)
        assert series.canon_paths(project_dir) == []
        assert series.characters_path(project_dir) == os.path.relpath(sheets, project_dir)
        series.require_canon(project_dir)

    def test_beside_the_canon(self, project_dir, sheets):
        (sheets.parent / 'gods.md').write_text('# Gods\n')
        rel = os.path.relpath(sheets.parent, project_dir)
        _yaml(project_dir, f'series:\n  canon:\n    - {rel}/gods.md\n  characters: {rel}/characters\n')
        assert series.canon_paths(project_dir) == [f'{rel}/gods.md']
        assert series.characters_path(project_dir) == f'{rel}/characters'

    def test_a_list_is_refused(self, project_dir, sheets):
        _yaml(project_dir, f'series:\n  characters:\n    - {sheets}\n')
        with pytest.raises(series.SeriesError, match='not a list|same line'):
            series.characters_path(project_dir)

    def test_a_missing_directory_is_an_error(self, project_dir):
        _yaml(project_dir, 'series:\n  characters: ../nowhere\n')
        with pytest.raises(series.SeriesError, match='is not a directory'):
            series.character_sheets(project_dir)

    def test_a_directory_with_only_a_readme_is_an_error(self, project_dir, tmp_path):
        d = tmp_path / 'empty'
        d.mkdir()
        (d / 'README.md').write_text('notes\n')
        _yaml(project_dir, f'series:\n  characters: {d}\n')
        with pytest.raises(series.SeriesError, match='holds no character sheet'):
            series.character_sheets(project_dir)


class TestSheets:
    def test_readme_is_skipped(self, project_dir, sheets):
        _configure(project_dir, sheets)
        assert set(series.character_sheets(project_dir)) == {
            'dorren-hayle', 'tessa-merrin', 'nobody-here'}

    def test_text_drops_the_frontmatter(self, project_dir, sheets):
        _configure(project_dir, sheets)
        text = series.sheet_text(project_dir, 'dorren-hayle')
        assert text.startswith('# dorren-hayle') and 'canon_id' not in text
        assert series.sheet_text(project_dir, 'someone-else') == ''

    def test_canon_id_must_name_the_file(self, project_dir, sheets):
        (sheets / 'tessa-merrin.md').write_text(_sheet('tessa', 'x'))
        _configure(project_dir, sheets)
        with pytest.raises(series.SeriesError, match="canon_id: tessa-merrin.*'tessa'"):
            series.sheet_text(project_dir, 'tessa-merrin')
        with pytest.raises(series.SeriesError):
            series.require_canon(project_dir)

    def test_a_sheet_without_frontmatter_is_an_error(self, project_dir, sheets):
        (sheets / 'tessa-merrin.md').write_text('# Tessa\n\nRed hair.\n')
        _configure(project_dir, sheets)
        with pytest.raises(series.SeriesError, match='needs frontmatter'):
            series.sheet_text(project_dir, 'tessa-merrin')

    def test_the_sheets_are_never_written(self, project_dir, sheets):
        _configure(project_dir, sheets)
        before = {p.name: p.read_bytes() for p in sheets.iterdir()}
        series.require_canon(project_dir)
        series.cast_sheets(project_dir, {'pov': 'Dorren Hayle', 'on_stage': 'tessa-merrin'})
        assert {p.name: p.read_bytes() for p in sheets.iterdir()} == before


class TestCast:
    def test_scene_cast_order_and_names(self):
        aliases = {'dorren hayle': 'dorren-hayle', 'tessa': 'tessa-merrin'}
        scene = {'pov': 'Dorren Hayle', 'characters': 'Tessa;dorren-hayle',
                 'on_stage': 'tessa-merrin; Kell'}
        assert series.scene_cast(scene, aliases) == ['dorren-hayle', 'tessa-merrin', 'Kell']

    def test_only_the_scenes_cast_gets_sheets(self, project_dir, sheets):
        _configure(project_dir, sheets)
        got = series.cast_sheets(project_dir, {'pov': 'Dorren Hayle'})
        assert [name for name, _ in got] == ['series-character-dorren-hayle.md']
        block = series.cast_sheets_block(project_dir, {'pov': 'Dorren Hayle'})
        assert 'burn scar on the left palm' in block and 'Red hair' not in block
        assert 'Not in this book' not in block
        assert series.cast_sheets_block(project_dir, {'pov': 'Kell'}) == ''


class TestDrafting:
    def test_briefs_prompt_carries_the_casts_sheets(self, project_dir, sheets):
        from storyforge.prompts import build_scene_prompt_from_briefs
        _configure(project_dir, sheets)
        plugin = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for system_context in (False, True):
            prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin,
                                                    system_context=system_context)
            assert "## How this scene's characters look" in prompt
            assert 'burn scar on the left palm' in prompt
            assert 'Not in this book' not in prompt

    def test_older_prompt_carries_them_too(self, project_dir, sheets):
        from storyforge.prompts import build_scene_prompt
        _configure(project_dir, sheets)
        for system_context in (False, True):
            prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=True,
                                        system_context=system_context)
            assert 'burn scar on the left palm' in prompt

    def test_no_sheets_leaves_the_prompt_as_it_was(self, project_dir):
        from storyforge.prompts import build_scene_prompt_from_briefs
        plugin = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin)
        assert "characters look" not in prompt


class TestChecker:
    def test_the_check_gets_the_casts_sheets(self, project_dir, sheets):
        _configure(project_dir, sheets)
        book = checker.Book.load(project_dir, 'act1-sc01')
        # the scene's pov and the others in it; no one outside the scene
        assert list(book.sheets) == ['series-character-dorren-hayle.md',
                                     'series-character-tessa-merrin.md']
        assert 'Not in this book' not in checker.build_prompt(book, 'act1-sc01', '')
        prompt = checker.build_prompt(book, 'act1-sc01', '')
        assert 'burn scar on the left palm' in prompt
        assert 'series-character-dorren-hayle.md' in prompt
        # the system prompt is the same for every scene: no sheet in it
        assert 'burn scar' not in str(checker._system(book))

    def test_a_finding_may_cite_a_sheet(self, project_dir, sheets):
        _configure(project_dir, sheets)
        book = checker.Book.load(project_dir, 'act1-sc01')
        quote = book.prose['act1-sc01'].split('.')[0]
        good = checker.Finding('contradiction', 'TRT', quote, 'series-character-dorren-hayle.md',
                               'burn scar on the left palm', '', 'why')
        assert checker._verify(good, book, 'act1-sc01', checker.Brief()) == ''
        bad = checker.Finding('contradiction', 'TRT', quote, 'series-character-dorren-hayle.md',
                              'blue eyes', '', 'why')
        assert 'not in series-character-dorren-hayle.md' in checker._verify(
            bad, book, 'act1-sc01', checker.Brief())

    def test_a_bad_sheet_stops_the_check(self, project_dir, sheets):
        (sheets / 'dorren-hayle.md').write_text('no frontmatter\n')
        _configure(project_dir, sheets)
        with pytest.raises(checker.CheckError, match='character sheets'):
            checker.Book.load(project_dir, 'act1-sc01')


def test_validate_summary_names_the_sheets(project_dir, sheets):
    _configure(project_dir, sheets)
    lines = series.summary_lines(project_dir)
    assert any(l.startswith('Series character sheets: 3 in ') for l in lines)
