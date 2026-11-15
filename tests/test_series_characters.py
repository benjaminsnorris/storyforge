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


class TestSession:
    """The long-session writer keeps one conversation: a character's sheet
    comes once a session, with their first scene."""

    def test_a_sheet_comes_once_a_session(self, project_dir, sheets):
        from storyforge import session
        _configure(project_dir, sheets)
        sent = set()
        first = session.scene_plan(project_dir, 'act1-sc01', notes=False, sheets_sent=sent)
        assert '## How the characters new to this session look' in first
        assert 'burn scar on the left palm' in first and 'Not in this book' not in first
        assert sent == {'series-character-dorren-hayle.md', 'series-character-tessa-merrin.md'}
        again = session.scene_plan(project_dir, 'act1-sc02', notes=False, sheets_sent=sent)
        assert 'burn scar on the left palm' not in again

    def test_without_a_record_the_plan_is_as_it_was(self, project_dir, sheets):
        from storyforge import session
        _configure(project_dir, sheets)
        assert 'characters new to this session' not in session.scene_plan(
            project_dir, 'act1-sc01', notes=False)


def _measured(rows):
    table = '\n'.join(f'| {a} | {b} | {c} |' for a, b, c in rows)
    return ('# x\n\n## Body\n\nTall.\n\n## Measurements\n\n'
            '| Measurement | Metric | Imperial |\n| --- | --- | --- |\n' + table + '\n\n## Next\n')


ACHILLES = [('Height', '188 cm', '74 in'), ('Weight', '86 kg', '190 lb'),
            ('Chest', '104 cm', '41 in'), ('Waist', '80 cm', '31.5 in'),
            ('Hips', '96 cm', '38 in'), ('Inseam', '89 cm', '35 in'),
            ('Shoulder width', '46 cm', '18 in'), ('Sleeve', '91 cm', '36 in'),
            ('Neck', '40 cm', '15.5 in'), ('Head', '58 cm', '23 in'),
            ('Calf', '39 cm', '15.5 in'), ('Foot', '28.5 cm', '11.25 in')]


class TestMeasurements:
    def test_a_full_set_reads_and_fits(self):
        m, problems = series.sheet_measurements(_measured(ACHILLES))
        assert problems == [] and m['inseam'] == 89 and m['weight'] == 86
        assert series.implausible(m) == []

    def test_no_section_is_nothing(self):
        assert series.sheet_measurements('# x\n\nNo table.\n') == ({}, [])

    def test_rows_that_cant_be_used(self):
        rows = ACHILLES[:2] + [('Cup size', 'C', ''), ('Chest', '104 in', ''),
                               ('Waist', '80 cm', '40 in'), ('Waist', '81 cm', '')]
        m, problems = series.sheet_measurements(_measured(rows), 'achilles.md')
        assert any("'Cup size' is not one of" in p for p in problems)
        assert any("chest: '104 in' is not a number in cm" in p for p in problems)
        assert any('waist: 40 in is 101.6 cm, not 80 cm' in p for p in problems)
        assert any('waist is given twice' in p for p in problems)
        assert all(p.startswith('achilles.md: ') for p in problems)

    def test_a_body_that_doesnt_fit(self):
        m = dict(height=188, weight=40, inseam=110, bust=90, underbust=95,
                 waist=120, chest=100, hips=100)
        why = ' '.join(series.implausible(m))
        assert 'inseam 110 cm is 0.59 of the height' in why
        assert 'body-mass index of 11' in why
        assert 'underbust 95 cm is not under the bust' in why
        assert 'waist 120 cm is over both chest/bust and hips' in why

    def test_a_god_or_giant_keeps_human_proportions(self):
        scale = 600 / 175
        giant = {'height': 600, 'weight': round(78 * scale ** 3), 'inseam': 270, 'head': 190}
        assert series.implausible(giant) == []

    def test_validate_blocks_a_bad_row_and_advises_on_a_bad_body(self, project_dir, sheets):
        (sheets / 'dorren-hayle.md').write_text(
            _sheet('dorren-hayle', _measured([('Height', '170 cm', ''), ('Shoe', '40', '')])))
        (sheets / 'tessa-merrin.md').write_text(
            _sheet('tessa-merrin', _measured([('Height', '170 cm', ''), ('Inseam', '100 cm', '')])))
        _configure(project_dir, sheets)
        found = series.measurement_findings(project_dir)
        assert ('blocking', "series.characters: "
                + os.path.join(os.path.relpath(sheets, project_dir), 'dorren-hayle.md')
                + ": measurement 'Shoe' is not one of " + ', '.join(series.MEASUREMENTS)) in found
        assert any(sev == 'advisory' and 'tessa-merrin.md: inseam 100 cm' in msg
                   for sev, msg in found)


class TestValidateCommand:
    def test_a_bad_measurement_row_blocks_validate(self, project_dir, sheets, monkeypatch, capsys):
        from test_series_canon import TestValidate
        (sheets / 'dorren-hayle.md').write_text(
            _sheet('dorren-hayle', _measured([('Height', '170 cm', ''), ('Shoe', '40', '')])))
        _configure(project_dir, sheets)
        code, out = TestValidate()._run(project_dir, monkeypatch, capsys)
        assert code == 1
        assert "measurement 'Shoe' is not one of" in out
        assert 'Series character sheets: 3 in' in out
