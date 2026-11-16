"""Bibles as facts, not essays (#657): the rows, the migration, the readers
(checker, drafting, scoring, illustrate) and the two-writers gap list.
Finding ids (CR-, T-, SF-, TD-, C-) are #697's review."""

import os
import shutil

import pytest

from fixture_helpers import FIXTURE_DIR_FACTS
from storyforge import bibles, ledger

CONVERSION = os.path.join(str(FIXTURE_DIR_FACTS), 'conversion')


def _ref(project_dir, *parts):
    return os.path.join(project_dir, 'reference', *parts)


def _read(path):
    with open(path, encoding='utf-8', newline='') as f:
        return f.read()


def _write(path, text, mode='w'):
    with open(path, mode, encoding='utf-8', newline='') as f:
        f.write(text)


def _gaps(project_dir):
    return bibles.plan_gaps(_ref(project_dir))


def _set_brief(project_dir, scene_id, column, value):
    path = _ref(project_dir, 'scene-briefs.csv')
    header, *lines = _read(path).splitlines()
    cols = header.split('|')
    out = []
    for line in lines:
        cells = line.split('|')
        if cells[0] == scene_id:
            i = cols.index(column)
            cells[i] = ';'.join(filter(None, [cells[i], value]))
        out.append('|'.join(cells))
    _write(path, '\n'.join([header] + out) + '\n')


def _set_scene_status(project_dir, scene_id, status):
    path = _ref(project_dir, 'scenes.csv')
    header, *lines = _read(path).splitlines()
    cols = header.split('|')
    if 'status' not in cols:
        cols.append('status')
        header = '|'.join(cols)
        lines = [l + '|' for l in lines]
    i = cols.index('status')
    out = []
    for line in lines:
        cells = line.split('|')
        if cells[0] == scene_id:
            cells[i] = status
        out.append('|'.join(cells))
    _write(path, '\n'.join([header] + out) + '\n')


def _add(project_dir, *items, **kw):
    return bibles.add_facts(project_dir, list(items), command='test', **kw)


# ---------------------------------------------------------------------------
# The converted fixture
# ---------------------------------------------------------------------------

class TestConvertedFixture:
    def test_the_bible_is_rows_and_the_essay_is_retired(self, facts_project_dir):
        assert not os.path.exists(_ref(facts_project_dir, 'character-bible.md'))
        assert bibles.essay_state(facts_project_dir, 'character-bible.md') == 'retired'
        rows = ledger.load(facts_project_dir)
        facts = [r for r in rows if bibles.is_bible_fact(r)]
        assert {r['type'] for r in facts} == {'trait', 'relationship', 'world'}
        assert all(r['origin'] == 'plan'
                   and r['introduced_by'] == bibles.essay_writer('character-bible.md')
                   for r in facts)
        voices, problems = bibles.read_voices(facts_project_dir)
        assert set(voices) == {'dorren-hayle', 'tessa-merrin'} and not problems

    def test_the_migration_makes_the_fixture(self, project_dir, monkeypatch):
        """`storyforge bibles import` + `retire` on test-project give exactly
        the overlay's files: the fixture is the migration's output."""
        from storyforge import cmd_bibles
        monkeypatch.chdir(project_dir)
        cmd_bibles.main(['import', os.path.join(CONVERSION, 'bible-facts.csv'),
                         '--essay', 'character-bible.md',
                         '--voices', os.path.join(CONVERSION, 'character-voices.csv'),
                         '--notes', os.path.join(CONVERSION, 'bible-notes.md'),
                         '--no-commit'])
        cmd_bibles.main(['retire', 'character-bible.md', '--no-commit'])
        overlay = os.path.join(str(FIXTURE_DIR_FACTS), 'reference')
        for rel in ('commitments.csv', 'character-voices.csv', 'bible-notes.md',
                    os.path.join('archive', 'character-bible.md')):
            assert _read(_ref(project_dir, rel)) == _read(os.path.join(overlay, rel)), rel
        assert not os.path.exists(_ref(project_dir, 'character-bible.md'))


# ---------------------------------------------------------------------------
# Writing facts
# ---------------------------------------------------------------------------

class TestAddFacts:
    def test_rows_take_the_plan_columns(self, project_dir):
        added, notes = _add(project_dir,
                            {'type': 'trait', 'subject': 'pell', 'statement': 'Is a ferryman'},
                            {'type': 'world', 'subject': '', 'statement': 'The river floods each spring'})
        assert added == ['pell-is-a-ferryman', 'the-river-floods-each-spring']
        assert notes == []
        r = {r['id']: r for r in ledger.load(project_dir)}['pell-is-a-ferryman']
        assert (r['origin'], r['status'], r['mutable'], r['introduced_by'], r['scene_id']) == \
            ('plan', 'binding', 'fixed', 'bibles', '')

    def test_a_rerun_adds_nothing_and_says_so(self, project_dir):
        """TD-1: the ledger's own fact_key: case and end punctuation aside."""
        _add(project_dir, {'type': 'trait', 'subject': 'pell', 'statement': 'Is a ferryman.'})
        before = _read(ledger.ledger_path(project_dir))
        added, notes = _add(project_dir, {'type': 'trait', 'subject': 'Pell',
                                          'statement': 'is a FERRYMAN'})
        assert added == [] and 'already states this fact' in notes[0]
        assert _read(ledger.ledger_path(project_dir)) == before

    def test_a_fact_twice_in_one_batch(self, project_dir):
        added, notes = _add(project_dir,
                            {'type': 'trait', 'subject': 'pell', 'statement': 'Is old'},
                            {'type': 'trait', 'subject': 'pell', 'statement': 'Is old.'})
        assert len(added) == 1 and 'item 1 states this fact' in notes[0]

    def test_a_commitment_doesnt_count_as_the_plans(self, project_dir):
        rows = ledger.load(project_dir)
        row = {c: '' for c in ledger.COLUMNS}
        row.update(id='said', scene_id='act1-sc01', type='trait', subject='pell',
                   statement='Is a ferryman', origin='prose', status='binding',
                   mutable='fixed', introduced_by='draft')
        ledger.save(project_dir, rows + [row], command='test')
        added, _ = _add(project_dir, {'type': 'trait', 'subject': 'pell', 'statement': 'Is a ferryman'})
        assert added == ['pell-is-a-ferryman']

    def test_an_unknown_subject_is_added_and_noted(self, project_dir):
        added, notes = _add(project_dir, {'type': 'trait', 'subject': 'nobody-here',
                                          'statement': 'Is tall', 'known_by': 'ghost'})
        assert added and any('nobody-here' in n for n in notes)
        assert any('ghost' in n for n in notes)

    @pytest.mark.parametrize('item, said', [
        ({'type': 'essay', 'subject': '', 'statement': 'x'}, 'is not one of'),
        ({'type': 'trait', 'subject': 'pell', 'statement': ''}, 'no statement'),
        ({'type': 'trait', 'subject': 'pell', 'statement': 'a | b'}, 'a `|`'),
        ({'type': 'trait', 'subject': 'pell', 'statement': 'x', 'id': 'village-vanished'},
         'already in the ledger'),
        ({'type': 'trait', 'subject': 'pell', 'statement': 'x', 'id': 'two words'},
         'has a space'),
        ({'type': 'relationship', 'subject': 'pell', 'statement': 'Is Kael\'s son',
          'category': 'secret'}, 'a secret is a knowledge fact'),
    ])
    def test_a_bad_item_writes_nothing(self, project_dir, item, said):
        before = _read(ledger.ledger_path(project_dir))
        good = {'type': 'trait', 'subject': 'pell', 'statement': 'Is a ferryman'}
        with pytest.raises(bibles.BiblesError, match=said):
            _add(project_dir, good, item)
        assert _read(ledger.ledger_path(project_dir)) == before

    def test_two_items_sharing_an_id_are_named(self, project_dir):
        """SF-11."""
        with pytest.raises(bibles.BiblesError, match="id 'same' is also item 1's"):
            _add(project_dir, {'type': 'trait', 'subject': 'pell', 'statement': 'a', 'id': 'same'},
                 {'type': 'trait', 'subject': 'pell', 'statement': 'b', 'id': 'same'})

    def test_a_dry_run_says_what_it_would_add(self, project_dir):
        before = _read(ledger.ledger_path(project_dir))
        added, _ = _add(project_dir, {'type': 'trait', 'subject': 'pell', 'statement': 'x'},
                        dry_run=True)
        assert added == ['pell-x'] and _read(ledger.ledger_path(project_dir)) == before


class TestImportFiles:
    def test_the_header_needs_its_columns(self, tmp_path):
        path = tmp_path / 'facts.csv'
        path.write_text('kind|subject|statement\ntrait|pell|x\n')
        with pytest.raises(bibles.BiblesError, match='no type column'):
            bibles.read_import(str(path))

    def test_an_unknown_column_is_refused(self, tmp_path):
        """SF-10: a typo would lose that column on every row."""
        path = tmp_path / 'facts.csv'
        path.write_text('type|subject|statement|knownby\ntrait|pell|x|kael\n')
        with pytest.raises(bibles.BiblesError, match="columns it doesn't take: knownby"):
            bibles.read_import(str(path))

    @pytest.mark.parametrize('line', ['trait|dorren-hayle|Loves the sea | hates rivers|',
                                      'world||Magic costs blood|extra|cells|x'])
    def test_a_row_that_doesnt_fit_the_header_is_refused(self, tmp_path, line):
        """SF-3: a `|` in a cell would shift every later cell."""
        path = tmp_path / 'facts.csv'
        path.write_text('type|subject|statement|known_by\n' + line + '\n')
        with pytest.raises(bibles.BiblesError, match='line 2: .* cells where the header has 4'):
            bibles.read_import(str(path))

    def test_a_file_that_cant_be_read(self, tmp_path):
        """SF-9: a BiblesError naming it, never a traceback."""
        path = tmp_path / 'facts.csv'
        path.write_bytes(b'type|subject|statement\ntrait|pell|\xff\n')
        with pytest.raises(bibles.BiblesError, match="can't be read as UTF-8"):
            bibles.read_import(str(path))

    def test_a_voice_line_with_a_pipe(self, tmp_path):
        path = tmp_path / 'v.csv'
        path.write_text('character|line\ndorren-hayle|"Wait | no."\n')
        with pytest.raises(bibles.BiblesError, match='3 cells'):
            bibles.read_voice_import(str(path))


class TestVoicesAndNotes:
    def test_voices(self, project_dir):
        added, notes = bibles.add_voices(project_dir, [('pell', '"Mind the rope."'),
                                                       ('stranger', '"Who asks?"'),
                                                       ('pell', '')])
        assert added == 2
        assert any('stranger' in n for n in notes) and any('no line' in n for n in notes)
        added, notes = bibles.add_voices(project_dir, [('pell', '"Mind the rope."')])
        assert added == 0 and notes[0].endswith('skipped')
        voices, _ = bibles.read_voices(project_dir)
        assert voices == {'pell': ['"Mind the rope."'], 'stranger': ['"Who asks?"']}

    def test_a_dry_run_counts_what_it_would_add(self, project_dir):
        """C-3/T-8."""
        added, _ = bibles.add_voices(project_dir, [('pell', '"Hi."')], dry_run=True)
        assert added == 1 and not os.path.exists(_ref(project_dir, bibles.VOICES_FILE))

    def test_a_bad_header_refuses_and_writes_nothing(self, project_dir):
        """TD-2/SF-4: lines appended under it would never be read."""
        _write(_ref(project_dir, bibles.VOICES_FILE), 'who|said\npell|hi\n')
        with pytest.raises(bibles.BiblesError, match='fix it first'):
            bibles.add_voices(project_dir, [('pell', '"New line."')])
        assert _read(_ref(project_dir, bibles.VOICES_FILE)) == 'who|said\npell|hi\n'

    def test_read_voices_reports_a_bad_header_and_a_bad_row(self, project_dir):
        _write(_ref(project_dir, bibles.VOICES_FILE), 'who|said\npell|hi\n')
        voices, problems = bibles.read_voices(project_dir)
        assert voices == {} and 'header must be' in problems[0]
        _write(_ref(project_dir, bibles.VOICES_FILE), 'character|line\npell|a|b\npell|ok\n')
        voices, problems = bibles.read_voices(project_dir)
        assert voices == {'pell': ['ok']} and 'line 2' in problems[0]

    def test_drafting_warns_what_it_leaves_out(self, facts_project_dir, capsys):
        _write(_ref(facts_project_dir, bibles.VOICES_FILE), 'character|line\npell|a|b\n',
               mode='a')
        bibles.drafting_sections(facts_project_dir)
        out = capsys.readouterr()
        assert 'WARNING' in out.out + out.err

    def test_notes_append_only_new_lines(self, project_dir):
        assert bibles.add_notes(project_dir, '# Notes\n\n- The ferry is old.') == 2
        assert bibles.add_notes(project_dir, '- The ferry is old.\n- The ford is new.') == 1
        assert bibles.add_notes(project_dir, '- The ferry is old.') == 0
        text = bibles.notes_text(project_dir)
        assert text.count('The ferry is old') == 1 and 'The ford is new' in text


# ---------------------------------------------------------------------------
# Importing: every input checked before anything is written
# ---------------------------------------------------------------------------

class TestImportCommand:
    def test_a_bad_voices_file_writes_no_facts(self, project_dir, monkeypatch, tmp_path):
        """CR-2/T-3: facts written, then voices failing, left them uncommitted
        and a re-run said 0 added."""
        from storyforge import cmd_bibles
        bad = tmp_path / 'v.csv'
        bad.write_text('character|line\npell|"a | b"\n')
        before = _read(ledger.ledger_path(project_dir))
        monkeypatch.chdir(project_dir)
        with pytest.raises(SystemExit):
            cmd_bibles.main(['import', os.path.join(CONVERSION, 'bible-facts.csv'),
                             '--voices', str(bad), '--no-commit'])
        assert _read(ledger.ledger_path(project_dir)) == before

    def test_a_missing_notes_file_writes_nothing(self, project_dir, monkeypatch):
        from storyforge import cmd_bibles
        before = _read(ledger.ledger_path(project_dir))
        monkeypatch.chdir(project_dir)
        with pytest.raises(SystemExit):
            cmd_bibles.main(['import', os.path.join(CONVERSION, 'bible-facts.csv'),
                             '--notes', 'nope.md', '--no-commit'])
        assert _read(ledger.ledger_path(project_dir)) == before

    def test_a_dry_run_reports_the_counts(self, project_dir, monkeypatch, capsys):
        from storyforge import cmd_bibles
        monkeypatch.chdir(project_dir)
        cmd_bibles.main(['import', os.path.join(CONVERSION, 'bible-facts.csv'),
                         '--voices', os.path.join(CONVERSION, 'character-voices.csv'),
                         '--dry-run'])
        out = capsys.readouterr()
        text = out.out + out.err
        assert 'Facts: 13 added' in text and 'Voices: 4 line(s) added' in text
        assert not os.path.exists(_ref(project_dir, bibles.VOICES_FILE))


# ---------------------------------------------------------------------------
# Retiring an essay
# ---------------------------------------------------------------------------

class TestRetire:
    def test_refused_until_it_is_converted(self, project_dir):
        with pytest.raises(bibles.BiblesError, match='no fact was converted from it'):
            bibles.retire(project_dir, 'character-bible.md')
        assert os.path.isfile(_ref(project_dir, 'character-bible.md'))

    def test_facts_from_a_stage_or_plain_import_dont_count(self, project_dir):
        """SF-6/C-2: elaborate writes such facts into every prose book."""
        _add(project_dir, {'type': 'trait', 'subject': 'dorren-hayle', 'statement': 'Is tall'},
             writer=bibles.STAGE_WRITER)
        _add(project_dir, {'type': 'trait', 'subject': 'tessa-merrin', 'statement': 'Is short'})
        with pytest.raises(bibles.BiblesError, match='no fact was converted'):
            bibles.retire(project_dir, 'character-bible.md')

    def test_each_character_the_essay_names_needs_a_fact(self, project_dir):
        _add(project_dir, {'type': 'trait', 'subject': 'dorren-hayle', 'statement': 'Is 42'},
             writer=bibles.essay_writer('character-bible.md'))
        with pytest.raises(bibles.BiblesError, match='no fact as a row: tessa-merrin'):
            bibles.retire(project_dir, 'character-bible.md')

    def test_another_essays_conversion_doesnt_count(self, project_dir):
        _write(_ref(project_dir, 'systems-bible.md'), '# Systems\n\nPressure maps.\n')
        _add(project_dir, {'type': 'world', 'subject': '', 'statement': 'Maps are drawn by hand'},
             writer=bibles.essay_writer('world-bible.md'))
        with pytest.raises(bibles.BiblesError, match='no fact was converted'):
            bibles.retire(project_dir, 'systems-bible.md')

    def test_a_converted_essay_retires_and_its_artifact_is_gone(self, project_dir):
        _add(project_dir,
             {'type': 'trait', 'subject': 'dorren-hayle', 'statement': 'Is 42'},
             {'type': 'trait', 'subject': 'tessa-merrin', 'statement': 'Is 28'},
             writer=bibles.essay_writer('character-bible.md'))
        with open(os.path.join(project_dir, 'storyforge.yaml'), 'a') as f:
            f.write('artifacts:\n  character_bible:\n    exists: true\n'
                    '    path: reference/character-bible.md\n')
        dest, notes = bibles.retire(project_dir, 'character-bible.md')
        assert dest == os.path.join('reference', 'archive', 'character-bible.md')
        assert 'dorren-hayle 1, tessa-merrin 1' in notes[0]
        from storyforge.common import read_artifact_field
        assert read_artifact_field(project_dir, 'character_bible', 'exists') == 'false'

    def test_force_and_dry_run(self, project_dir):
        dest, notes = bibles.retire(project_dir, 'character-bible.md', force=True, dry_run=True)
        assert os.path.isfile(_ref(project_dir, 'character-bible.md'))
        assert any('--force' in n for n in notes)
        bibles.retire(project_dir, 'character-bible.md', force=True)
        assert bibles.essay_state(project_dir, 'character-bible.md') == 'retired'

    @pytest.mark.parametrize('name, said', [('notes.md', 'not a bible essay'),
                                            ('world-bible.md', "doesn't exist")])
    def test_refusals(self, project_dir, name, said):
        with pytest.raises(bibles.BiblesError, match=said):
            bibles.retire(project_dir, name, force=True)

    def test_an_archived_copy_is_never_overwritten(self, facts_project_dir):
        _write(_ref(facts_project_dir, 'character-bible.md'), '# a new essay\n')
        with pytest.raises(bibles.BiblesError, match='already exists'):
            bibles.retire(facts_project_dir, 'character-bible.md')

    def test_extract_doesnt_write_a_retired_essay_again(self, facts_project_dir):
        from storyforge.extract_describe import decide
        verdict = decide(facts_project_dir, 'reference/character-bible.md', True, {})
        assert not verdict.write and 'retired' in verdict.report()


# ---------------------------------------------------------------------------
# The two-writers test
# ---------------------------------------------------------------------------

class TestPlanGaps:
    def test_the_fixture_lists_one_gap_of_each_kind(self, facts_project_dir):
        gaps, notes = _gaps(facts_project_dir)
        assert {(g.kind, g.ref) for g in gaps} == {
            ('ambiguous-relationship', 'kael-knew-mentor'),
            ('unsettled-reveal', 'kael-erased-records'),
            ('open-world-rule', 'readings-faked-at-instrument'),
            ('open-question', 'bible-notes.md line 5'),
        }
        assert notes == []

    def test_an_essay_not_converted_is_said(self, project_dir):
        gaps, notes = _gaps(project_dir)
        assert gaps == []
        assert len(notes) == 1 and 'character-bible.md is still an essay' in notes[0]

    def test_the_mixed_state_is_said(self, project_dir):
        """T-2: an essay and rows of its kind are both read."""
        _add(project_dir, {'type': 'trait', 'subject': 'pell', 'statement': 'Is old'})
        notes = _gaps(project_dir)[1]
        assert 'read it beside 1 plan fact(s) of its kind' in notes[0]

    def test_a_retired_essay_with_no_rows_is_said(self, project_dir):
        """SF-12."""
        bibles.retire(project_dir, 'character-bible.md', force=True)
        notes = _gaps(project_dir)[1]
        assert len(notes) == 1 and 'nothing stands in for it' in notes[0]

    def test_a_graphic_novel_keeps_its_essays_unnoted(self, project_dir_gn):
        assert not any('still an essay' in n for n in _gaps(project_dir_gn)[1])

    def test_a_template_essay_is_not_an_essay(self, project_dir, plugin_dir):
        shutil.copy(os.path.join(plugin_dir, 'templates', 'reference', 'character-bible.md'),
                    _ref(project_dir, 'character-bible.md'))
        assert _gaps(project_dir) == ([], [])

    # -- reveals (T-5) --

    def _secret(self, project_dir, **extra):
        item = {'type': 'knowledge', 'subject': 'dorren-hayle', 'id': 'forged',
                'statement': 'Dorren forged the survey', 'category': 'secret'}
        item.update(extra)
        _add(project_dir, item)

    def _reveal_gaps(self, project_dir):
        return {g.ref for g in _gaps(project_dir)[0] if g.kind == 'unsettled-reveal'}

    def test_a_brief_that_reveals_it_settles_a_secret(self, project_dir):
        self._secret(project_dir)
        assert 'forged' in self._reveal_gaps(project_dir)
        _set_brief(project_dir, 'act2-sc03', 'knowledge_out', 'forged')
        assert 'forged' not in self._reveal_gaps(project_dir)

    def test_knowledge_in_settles_a_fact_but_not_a_secret(self, project_dir):
        self._secret(project_dir)
        _add(project_dir, {'type': 'knowledge', 'subject': 'pell', 'id': 'ford',
                           'statement': 'The ford is shallow'})
        _set_brief(project_dir, 'act2-sc03', 'knowledge_in', 'forged;ford')
        refs = self._reveal_gaps(project_dir)
        assert 'forged' in refs and 'ford' not in refs

    def test_a_live_scene_id_settles_it_and_a_cut_one_doesnt(self, project_dir):
        self._secret(project_dir, scene_id='act2-sc03')
        assert 'forged' not in self._reveal_gaps(project_dir)
        _set_scene_status(project_dir, 'act2-sc03', 'cut')
        assert 'forged' in self._reveal_gaps(project_dir)

    def test_a_cut_scenes_brief_reveals_nothing(self, project_dir):
        self._secret(project_dir)
        _set_brief(project_dir, 'act2-sc03', 'knowledge_out', 'forged')
        _set_scene_status(project_dir, 'act2-sc03', 'cut')
        assert 'forged' in self._reveal_gaps(project_dir)

    def test_a_known_fact_is_not_a_reveal(self, project_dir):
        _add(project_dir, {'type': 'knowledge', 'subject': 'pell',
                           'statement': 'Pell knows the river', 'known_by': 'pell'})
        assert _gaps(project_dir)[0] == []

    # -- relationships, rules, questions --

    def test_a_relationship_naming_one_side(self, project_dir):
        _add(project_dir,
             {'type': 'relationship', 'subject': 'pell', 'statement': 'Owes a debt', 'id': 'one-side'},
             {'type': 'relationship', 'subject': 'pell', 'statement': 'Owes Kael a debt',
              'id': 'two-sides'})
        refs = {g.ref for g in _gaps(project_dir)[0]}
        assert 'one-side' in refs and 'two-sides' not in refs

    @pytest.mark.parametrize('statement', [
        'Anyone may be summoned before the council',
        'Magic is uncertain near running water',
        'A reading might be faked only at the instrument, never in the archive',
        'Kael trusts either Dorren or no one',
        'The Uncharted Reaches are unknown territory',
    ])
    def test_a_settled_statement_is_not_hedged(self, project_dir, statement):
        """T-4."""
        _add(project_dir, {'type': 'world', 'subject': '', 'statement': statement},
             {'type': 'relationship', 'subject': 'kael-maren',
              'statement': statement + ' (Kael and Dorren Hayle)'})
        assert _gaps(project_dir)[0] == []

    @pytest.mark.parametrize('statement', ['Perhaps magic needs blood', 'Can maps lie?',
                                           'Undecided: who drew the first map',
                                           'Kael may have lied'])
    def test_a_hedged_rule_is_open(self, project_dir, statement):
        _add(project_dir, {'type': 'world', 'subject': '', 'statement': statement, 'id': 'r'})
        assert [g.kind for g in _gaps(project_dir)[0]] == ['open-world-rule']

    def test_a_trait_question_is_open(self, project_dir):
        """C-1: the stage prompt says any row ending in `?`."""
        _add(project_dir, {'type': 'trait', 'subject': 'pell', 'statement': 'How old is Pell?',
                           'id': 'q'})
        assert [(g.kind, g.ref) for g in _gaps(project_dir)[0]] == [('open-question', 'q')]

    def test_facts_the_prose_established_are_not_the_plans(self, project_dir):
        rows = ledger.load(project_dir)
        row = {c: '' for c in ledger.COLUMNS}
        row.update(id='hedged', type='world', statement='Maybe it rains?', origin='prose',
                   status='binding', mutable='fixed', introduced_by='extract')
        ledger.save(project_dir, rows + [row], command='test')
        assert all(g.ref != 'hedged' for g in _gaps(project_dir)[0])

    def test_a_ledger_that_cant_be_read_is_said(self, facts_project_dir):
        _write(ledger.ledger_path(facts_project_dir), 'broken|row\n', mode='a')
        gaps, notes = _gaps(facts_project_dir)
        assert gaps == [] and "can't be checked for gaps" in notes[-1]

    def test_an_unreadable_registry_is_said_not_raised(self, facts_project_dir):
        with open(_ref(facts_project_dir, 'characters.csv'), 'wb') as f:
            f.write(b'id|name\n\xff\xfe|x\n')
        gaps, notes = _gaps(facts_project_dir)
        assert any("can't be read" in n for n in notes)
        assert any(g.kind == 'unsettled-reveal' for g in gaps)

    def test_a_gap_kind_is_checked(self):
        with pytest.raises(AssertionError):
            bibles.Gap('typo', 'x', '', '')

    # -- validate and the command --

    def test_validate_lists_them_as_advisory(self, facts_project_dir):
        from storyforge.elaborate import validate_structure
        result = validate_structure(_ref(facts_project_dir))
        gaps = [c for c in result['checks'] if c['category'] == 'plan-gaps']
        assert len(gaps) == 4 and all(c['severity'] == 'advisory' and not c['passed']
                                      for c in gaps)
        assert any(c['check'] == 'plan-gap-open-question-bible-notes-md-line-5' for c in gaps)

    def test_validate_says_an_essay_couldnt_be_checked(self, project_dir):
        from storyforge.elaborate import validate_structure
        checks = [c for c in validate_structure(_ref(project_dir))['checks']
                  if c['category'] == 'plan-gaps']
        assert len(checks) == 1 and not checks[0]['passed']
        assert 'still an essay' in checks[0]['message']

    def test_validate_passes_a_clean_plan(self, project_dir):
        from storyforge.elaborate import validate_structure
        os.remove(_ref(project_dir, 'character-bible.md'))
        checks = [c for c in validate_structure(_ref(project_dir))['checks']
                  if c['category'] == 'plan-gaps']
        assert [c['passed'] for c in checks] == [True]

    def test_the_command_lists_them(self, facts_project_dir, capsys, monkeypatch):
        from storyforge import cmd_bibles
        monkeypatch.chdir(facts_project_dir)
        cmd_bibles.main([])
        out = capsys.readouterr().out
        assert 'character-bible.md: retired' in out
        assert 'The two-writers test: 4 gap(s)' in out
        assert 'unsettled-reveal: kael-erased-records' in out

    def test_the_command_reports_an_unreadable_voices_file(self, facts_project_dir, capsys,
                                                           monkeypatch):
        from storyforge import cmd_bibles
        with open(_ref(facts_project_dir, bibles.VOICES_FILE), 'wb') as f:
            f.write(b'character|line\npell|\xff\n')
        monkeypatch.chdir(facts_project_dir)
        with pytest.raises(SystemExit):
            cmd_bibles.main([])
        assert 'ERROR' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Readers: drafting, secrets, the mixed state
# ---------------------------------------------------------------------------

class TestDrafting:
    def test_sections_carry_facts_voices_and_notes_never_a_secret(self, facts_project_dir):
        sections = dict(bibles.drafting_sections(facts_project_dir))
        assert list(sections) == ['Settled Facts', 'How They Speak', 'Notes']
        facts = sections['Settled Facts']
        assert '### Dorren Hayle\n- Is 42' in facts
        assert '### The world' in facts and facts.index('### The world') > facts.index('Tessa')
        assert 'erased' not in facts
        assert '[dorren-age]' not in facts   # ids are the checker's
        assert "Tessa Merrin:\n> \"I walked it." in sections['How They Speak']
        assert 'What did the council gain' in sections['Notes']

    def test_a_hand_written_secret_on_another_type_is_withheld(self, facts_project_dir):
        """CR-1(a)."""
        rows = ledger.load(facts_project_dir)
        row = {c: '' for c in ledger.COLUMNS}
        row.update(id='hidden-kin', type='relationship', subject='kael-maren',
                   statement='Kael is Dorren Hayle\'s brother', origin='author',
                   status='binding', mutable='fixed', introduced_by='bibles', category='secret')
        ledger.save(facts_project_dir, rows + [row], command='test')
        assert 'brother' not in bibles.drafting_text(facts_project_dir)
        assert 'brother' not in bibles.checker_doc(facts_project_dir)

    def test_a_secret_waits_for_the_scene_that_reveals_it(self, project_dir, plugin_dir):
        """CR-1(b): a backstory knowledge fact was in force from scene 1."""
        from storyforge.prompts import build_scene_prompt_from_briefs
        _add(project_dir, {'type': 'knowledge', 'subject': 'dorren-hayle', 'id': 'forged',
                           'statement': 'Dorren forged the survey', 'category': 'secret'})
        _add(project_dir, {'type': 'knowledge', 'subject': 'dorren-hayle', 'id': 'ford',
                           'statement': 'Dorren knows the ford is shallow'})

        def prompt(sid):
            return build_scene_prompt_from_briefs(sid, project_dir, plugin_dir, 'full',
                                                  system_context=True)
        assert 'Dorren forged the survey' not in prompt('act1-sc01')
        assert 'the ford is shallow' in prompt('act1-sc01')
        _set_brief(project_dir, 'act1-sc02', 'knowledge_out', 'forged')
        assert 'Dorren forged the survey' not in prompt('act1-sc01')
        assert 'Dorren forged the survey' in prompt('act2-sc03')

    def test_unrevealed_secrets(self, project_dir):
        _add(project_dir, {'type': 'knowledge', 'subject': 'pell', 'id': 's1',
                           'statement': 'a', 'category': 'secret'},
             {'type': 'knowledge', 'subject': 'pell', 'id': 's2', 'statement': 'b',
              'category': 'reveal', 'scene_id': 'act1-sc02'})
        rows, order = ledger.load(project_dir), ledger.scene_order(project_dir)
        ref = _ref(project_dir)
        assert bibles.unrevealed_secrets(ref, rows, 'act1-sc01', order) == {'s1', 's2'}
        assert bibles.unrevealed_secrets(ref, rows, 'act1-sc02', order) == {'s1'}

    def test_a_fact_true_from_a_scene_is_not_standing(self, facts_project_dir):
        _add(facts_project_dir, {'type': 'world', 'subject': '',
                                 'statement': 'The ridge has collapsed', 'scene_id': 'act2-sc02'})
        assert 'ridge has collapsed' not in bibles.drafting_text(facts_project_dir)

    def test_a_book_without_rows_gets_nothing(self, project_dir):
        assert bibles.drafting_sections(project_dir) == []

    def test_shared_context_carries_them(self, facts_project_dir):
        from storyforge.common import build_shared_context
        text = '\n'.join(b['text'] for b in build_shared_context(facts_project_dir,
                                                                 'claude-opus-5-5'))
        assert '=== Settled Facts ===' in text and '=== How They Speak ===' in text
        assert 'Character Bible' not in text

    def test_shared_context_in_the_mixed_state_carries_both(self, project_dir):
        """T-2."""
        from storyforge.common import build_shared_context
        _add(project_dir, {'type': 'trait', 'subject': 'pell', 'statement': 'Is a ferryman'})
        text = '\n'.join(b['text'] for b in build_shared_context(project_dir, 'claude-opus-5-5'))
        assert '=== Character Bible ===' in text and 'Is a ferryman' in text

    def test_shared_context_survives_a_bad_ledger(self, project_dir, capsys):
        """CR-3: evaluate and scenes-setup crashed on it."""
        from storyforge import common
        common._shared_context_cache.clear()
        _write(ledger.ledger_path(project_dir), 'broken|row\n', mode='a')
        blocks = common.build_shared_context(project_dir, 'claude-opus-5-5')
        assert blocks
        out = capsys.readouterr()
        assert 'bible rows are left out' in out.out + out.err

    def test_the_scene_prompt_carries_them_without_shared_context(self, facts_project_dir,
                                                                   plugin_dir):
        from storyforge.prompts import build_scene_prompt_from_briefs
        prompt = build_scene_prompt_from_briefs('act1-sc02', facts_project_dir, plugin_dir,
                                                'full', system_context=False)
        assert '## Settled Facts' in prompt and 'Believes the maps are objective' in prompt
        assert '## Character Bible' not in prompt

    def test_a_session_carries_them(self, facts_project_dir):
        from storyforge import session
        text = '\n'.join(b['text'] for b in session.system_blocks(facts_project_dir))
        assert '## Settled Facts' in text and '## How They Speak' in text

    def test_elaborate_stages_see_them(self, facts_project_dir):
        from storyforge.prompts_elaborate import _existing_refs
        assert '### Settled Facts' in _existing_refs(facts_project_dir)
        assert '### Settled Facts' not in _existing_refs(facts_project_dir, shared=True)


class TestChecker:
    def test_the_checker_reads_rows_not_the_retired_essay(self, facts_project_dir):
        from storyforge import checker
        docs = checker.reference_docs(facts_project_dir)
        assert list(docs) == ['bible-notes.md', bibles.FACTS_DOC]
        assert '- [dorren-lie] Believes the maps are objective' in docs[bibles.FACTS_DOC]

    def test_a_book_without_rows_reads_as_before(self, project_dir):
        from storyforge import checker
        assert list(checker.reference_docs(project_dir)) == ['character-bible.md']

    def test_notes_alone_are_reference(self, project_dir):
        """T-9: bible-notes.md joined REFERENCE_DOCS."""
        from storyforge import checker
        bibles.add_notes(project_dir, '- The office never closes.')
        assert checker.reference_docs(project_dir)['bible-notes.md'].startswith('- The office')

    def test_an_unreadable_ledger_is_a_check_error(self, facts_project_dir):
        """T-9."""
        from storyforge import checker
        _write(ledger.ledger_path(facts_project_dir), 'broken|row\n', mode='a')
        with pytest.raises(checker.CheckError, match="plan's facts can't be read"):
            checker.reference_docs(facts_project_dir)


class TestBibleText:
    def test_the_essay_while_it_is_there(self, project_dir):
        assert bibles.bible_text(project_dir, 'character-bible.md').startswith('# Character Bible')

    def test_both_in_the_mixed_state(self, project_dir):
        """T-2: hone and novel-level score dropped the rows."""
        _add(project_dir, {'type': 'trait', 'subject': 'pell', 'statement': 'Is a ferryman'})
        text = bibles.bible_text(project_dir, 'character-bible.md')
        assert text.startswith('# Character Bible') and 'Facts as rows' in text
        assert 'Is a ferryman' in text

    def test_the_rows_once_retired(self, facts_project_dir):
        text = bibles.bible_text(facts_project_dir, 'character-bible.md')
        assert 'Believes the maps are objective' in text and 'How they speak' in text
        assert 'answers to the council' not in text
        world = bibles.bible_text(facts_project_dir, 'world-bible.md')
        assert 'answers to the council' in world and 'brass instruments' in world

    def test_nothing_for_a_book_with_neither(self, project_dir):
        assert bibles.bible_text(project_dir, 'world-bible.md') == ''

    def test_hone_reads_the_rows(self, facts_project_dir, monkeypatch):
        from storyforge import cmd_hone, hone
        seen = {}
        monkeypatch.setattr(hone, 'reconcile_domain',
                            lambda domain, ref_dir, model, log_dir, context='': seen.update(
                                context=context) or {})
        cmd_hone._run_registry_domain('characters', _ref(facts_project_dir), facts_project_dir,
                                      '', 'm', _ref(facts_project_dir, 'character-bible.md'),
                                      False)
        assert 'Believes the maps are objective' in seen['context']


class TestOtherReaders:
    """SF-1/SF-2/T-6: readers that went blind after an essay was retired."""

    def test_bible_consistency_reads_the_rows(self, facts_project_dir):
        from storyforge.scoring_bible import _load_bibles
        loaded = _load_bibles(facts_project_dir)
        label = 'character-bible.md (rows in commitments.csv)'
        assert label in loaded and 'Believes the maps are objective' in loaded[label]

    def test_bible_consistency_warns_a_retired_essay_with_no_rows(self, project_dir, capsys):
        from storyforge.scoring_bible import _load_bibles
        bibles.retire(project_dir, 'character-bible.md', force=True)
        _load_bibles(project_dir)
        out = capsys.readouterr()
        assert 'retired and the ledger has no facts' in out.out + out.err

    def test_illustrate_reads_the_rows(self, facts_project_dir):
        from storyforge.cmd_illustrate import _canon_context
        text = _canon_context(facts_project_dir)
        assert 'Believes the maps are objective' in text and 'answers to the council' in text

    def test_a_row_edit_marks_novel_scores_stale(self, facts_project_dir, project_dir):
        from storyforge.cmd_score import _current_input_hashes
        before = _current_input_hashes(facts_project_dir)['character-bible.md']
        _add(facts_project_dir, {'type': 'trait', 'subject': 'pell', 'statement': 'Is a ferryman'})
        assert _current_input_hashes(facts_project_dir)['character-bible.md'] != before
        # a book without rows hashes its essay as before
        from storyforge.cmd_score import _hash_text
        with open(_ref(project_dir, 'character-bible.md'), encoding='utf-8') as f:
            assert _current_input_hashes(project_dir)['character-bible.md'] == _hash_text(f.read())


def test_migrate_medium_says_a_retired_essay_got_no_note(facts_project_dir, capsys):
    from storyforge.cmd_migrate_medium import step8_add_bible_visual_notes
    assert step8_add_bible_visual_notes(facts_project_dir, dry_run=True) == []
    out = capsys.readouterr()
    assert 'character-bible.md is retired' in out.out + out.err
