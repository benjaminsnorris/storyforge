"""Bibles as facts, not essays (#657): the rows, the migration, the readers
(checker, drafting) and the two-writers gap list."""

import os

import pytest

from fixture_helpers import FIXTURE_DIR_FACTS
from storyforge import bibles, ledger

CONVERSION = os.path.join(str(FIXTURE_DIR_FACTS), 'conversion')


def _ref(project_dir, *parts):
    return os.path.join(project_dir, 'reference', *parts)


def _read(path):
    with open(path, encoding='utf-8', newline='') as f:
        return f.read()


def _gaps(project_dir):
    return bibles.plan_gaps(_ref(project_dir))


# ---------------------------------------------------------------------------
# The converted fixture
# ---------------------------------------------------------------------------

class TestConvertedFixture:
    def test_the_bible_is_rows_and_the_essay_is_retired(self, facts_project_dir):
        assert not os.path.exists(_ref(facts_project_dir, 'character-bible.md'))
        assert os.path.isfile(_ref(facts_project_dir, 'archive', 'character-bible.md'))
        assert bibles.essay_state(facts_project_dir, 'character-bible.md') == 'retired'
        rows = ledger.load(facts_project_dir)
        facts = [r for r in rows if bibles.is_bible_fact(r)]
        assert {r['type'] for r in facts} == {'trait', 'relationship', 'world'}
        assert all(r['origin'] == 'plan' and r['introduced_by'] == bibles.WRITER for r in facts)
        voices, problems = bibles.read_voices(facts_project_dir)
        assert set(voices) == {'dorren-hayle', 'tessa-merrin'} and not problems

    def test_the_migration_makes_the_fixture(self, project_dir, capsys):
        """`storyforge bibles import` + `retire` on test-project give exactly
        the overlay's files: the fixture is the migration's output."""
        from storyforge import cmd_bibles
        cwd = os.getcwd()
        os.chdir(project_dir)
        try:
            cmd_bibles.main(['import', os.path.join(CONVERSION, 'bible-facts.csv'),
                             '--voices', os.path.join(CONVERSION, 'character-voices.csv'),
                             '--notes', os.path.join(CONVERSION, 'bible-notes.md'),
                             '--no-commit'])
            cmd_bibles.main(['retire', 'character-bible.md', '--no-commit'])
        finally:
            os.chdir(cwd)
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
        added, notes = bibles.add_facts(project_dir, [
            {'type': 'trait', 'subject': 'pell', 'statement': 'Is a ferryman'},
            {'type': 'world', 'subject': '', 'statement': 'The river floods each spring'},
        ], command='test')
        assert added == ['pell-is-a-ferryman', 'the-river-floods-each-spring']
        assert notes == []
        rows = {r['id']: r for r in ledger.load(project_dir)}
        r = rows['pell-is-a-ferryman']
        assert (r['origin'], r['status'], r['mutable'], r['introduced_by'], r['scene_id']) == \
            ('plan', 'binding', 'fixed', 'bibles', '')

    def test_a_rerun_adds_nothing_and_says_so(self, project_dir):
        item = {'type': 'trait', 'subject': 'pell', 'statement': 'Is a ferryman'}
        bibles.add_facts(project_dir, [item], command='test')
        before = _read(ledger.ledger_path(project_dir))
        added, notes = bibles.add_facts(project_dir, [item], command='test')
        assert added == [] and 'already has this fact' in notes[0]
        assert _read(ledger.ledger_path(project_dir)) == before

    def test_an_unknown_subject_is_added_and_noted(self, project_dir):
        added, notes = bibles.add_facts(project_dir, [
            {'type': 'trait', 'subject': 'nobody-here', 'statement': 'Is tall',
             'known_by': 'ghost'}], command='test')
        assert added and any('nobody-here' in n for n in notes)
        assert any('ghost' in n for n in notes)

    @pytest.mark.parametrize('item, said', [
        ({'type': 'essay', 'subject': '', 'statement': 'x'}, 'is not one of'),
        ({'type': 'trait', 'subject': 'pell', 'statement': ''}, 'no statement'),
        ({'type': 'trait', 'subject': 'pell', 'statement': 'a | b'}, 'a `|`'),
        ({'type': 'trait', 'subject': 'pell', 'statement': 'x', 'id': 'village-vanished'},
         'already in the ledger'),
    ])
    def test_a_bad_item_writes_nothing(self, project_dir, item, said):
        before = _read(ledger.ledger_path(project_dir))
        good = {'type': 'trait', 'subject': 'pell', 'statement': 'Is a ferryman'}
        with pytest.raises(bibles.BiblesError, match=said):
            bibles.add_facts(project_dir, [good, item], command='test')
        assert _read(ledger.ledger_path(project_dir)) == before

    def test_an_import_file_needs_its_columns(self, tmp_path):
        path = tmp_path / 'facts.csv'
        path.write_text('kind|subject|statement\ntrait|pell|x\n')
        with pytest.raises(bibles.BiblesError, match='no type column'):
            bibles.read_import(str(path))

    def test_voices_and_notes(self, project_dir):
        notes = bibles.add_voices(project_dir, [('pell', '"Mind the rope."'),
                                                ('stranger', '"Who asks?"')])
        assert any('stranger' in n for n in notes)
        assert bibles.add_voices(project_dir, [('pell', '"Mind the rope."')])[0].endswith('skipped')
        voices, _ = bibles.read_voices(project_dir)
        assert voices == {'pell': ['"Mind the rope."'], 'stranger': ['"Who asks?"']}
        assert bibles.add_notes(project_dir, '- The ferry is older than the town.')
        assert not bibles.add_notes(project_dir, '  ')
        assert 'older than the town' in bibles.notes_text(project_dir)

    def test_a_voices_file_with_the_wrong_header_is_said(self, project_dir):
        with open(_ref(project_dir, bibles.VOICES_FILE), 'w') as f:
            f.write('who|said\npell|hi\n')
        voices, problems = bibles.read_voices(project_dir)
        assert voices == {} and 'header must be' in problems[0]


# ---------------------------------------------------------------------------
# Retiring an essay
# ---------------------------------------------------------------------------

class TestRetire:
    def test_refused_until_its_facts_are_rows(self, project_dir):
        with pytest.raises(bibles.BiblesError, match='has no rows yet'):
            bibles.retire(project_dir, 'character-bible.md')
        assert os.path.isfile(_ref(project_dir, 'character-bible.md'))

    def test_force_and_dry_run(self, project_dir):
        assert bibles.retire(project_dir, 'character-bible.md', force=True, dry_run=True) \
            == os.path.join('reference', 'archive', 'character-bible.md')
        assert os.path.isfile(_ref(project_dir, 'character-bible.md'))
        bibles.retire(project_dir, 'character-bible.md', force=True)
        assert bibles.essay_state(project_dir, 'character-bible.md') == 'retired'

    @pytest.mark.parametrize('name, said', [('notes.md', 'not a bible essay'),
                                            ('world-bible.md', "doesn't exist")])
    def test_refusals(self, project_dir, name, said):
        with pytest.raises(bibles.BiblesError, match=said):
            bibles.retire(project_dir, name, force=True)

    def test_an_archived_copy_is_never_overwritten(self, facts_project_dir):
        with open(_ref(facts_project_dir, 'character-bible.md'), 'w') as f:
            f.write('# a new essay\n')
        with pytest.raises(bibles.BiblesError, match='already exists'):
            bibles.retire(facts_project_dir, 'character-bible.md')


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

    def test_a_template_essay_is_not_an_essay(self, project_dir, plugin_dir):
        import shutil
        shutil.copy(os.path.join(plugin_dir, 'templates', 'reference', 'character-bible.md'),
                    _ref(project_dir, 'character-bible.md'))
        assert _gaps(project_dir) == ([], [])

    def test_a_brief_that_reveals_it_settles_a_secret(self, facts_project_dir):
        path = _ref(facts_project_dir, 'scene-briefs.csv')
        text = _read(path)
        header, *lines = text.splitlines()
        cols = header.split('|')
        out = []
        for line in lines:
            cells = line.split('|')
            if cells[0] == 'act2-sc03':
                i = cols.index('knowledge_out')
                cells[i] = ';'.join(filter(None, [cells[i], 'kael-erased-records']))
            out.append('|'.join(cells))
        with open(path, 'w', newline='') as f:
            f.write('\n'.join([header] + out) + '\n')
        kinds = {g.ref for g in _gaps(facts_project_dir)[0]}
        assert 'kael-erased-records' not in kinds

    def test_a_secret_known_only_entering_is_still_unsettled(self, project_dir):
        bibles.add_facts(project_dir, [{'type': 'knowledge', 'subject': 'dorren-hayle',
                                        'statement': 'Dorren forged the survey',
                                        'category': 'secret', 'id': 'forged'}],
                         command='test')
        assert any(g.ref == 'forged' for g in _gaps(project_dir)[0])

    def test_a_known_fact_is_not_a_reveal(self, project_dir):
        bibles.add_facts(project_dir, [{'type': 'knowledge', 'subject': 'pell',
                                        'statement': 'Pell knows the river',
                                        'known_by': 'pell'}], command='test')
        assert _gaps(project_dir)[0] == []

    def test_a_relationship_naming_one_side(self, project_dir):
        bibles.add_facts(project_dir, [
            {'type': 'relationship', 'subject': 'pell', 'statement': 'Owes a debt',
             'id': 'one-side'},
            {'type': 'relationship', 'subject': 'pell', 'statement': 'Owes Kael a debt',
             'id': 'two-sides'}], command='test')
        refs = {g.ref for g in _gaps(project_dir)[0]}
        assert 'one-side' in refs and 'two-sides' not in refs

    def test_facts_the_prose_established_are_not_the_plans(self, project_dir):
        rows = ledger.load(project_dir)
        row = {c: '' for c in ledger.COLUMNS}
        row.update(id='hedged', type='world', statement='Maybe it rains?', origin='prose',
                   status='binding', mutable='fixed', introduced_by='extract')
        ledger.save(project_dir, rows + [row], command='test')
        assert all(g.ref != 'hedged' for g in _gaps(project_dir)[0])

    def test_a_ledger_that_cant_be_read_is_said(self, facts_project_dir):
        with open(ledger.ledger_path(facts_project_dir), 'a') as f:
            f.write('broken|row\n')
        gaps, notes = _gaps(facts_project_dir)
        assert gaps == [] and "can't be checked for gaps" in notes[-1]

    def test_validate_lists_them_as_advisory(self, facts_project_dir):
        from storyforge.elaborate import validate_structure
        result = validate_structure(_ref(facts_project_dir))
        gaps = [c for c in result['checks'] if c['category'] == 'plan-gaps']
        assert len(gaps) == 4 and all(c['severity'] == 'advisory' and not c['passed']
                                      for c in gaps)
        assert any('kael-erased-records' in c['message'] for c in gaps)

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


# ---------------------------------------------------------------------------
# Readers: drafting and the checker
# ---------------------------------------------------------------------------

class TestDrafting:
    def test_sections_carry_facts_voices_and_notes_never_a_secret(self, facts_project_dir):
        sections = dict(bibles.drafting_sections(facts_project_dir))
        assert list(sections) == ['Settled Facts', 'How They Speak', 'Notes']
        facts = sections['Settled Facts']
        assert '### Dorren Hayle\n- Is 42' in facts
        assert '### The world' in facts and facts.index('### The world') > facts.index('Tessa')
        assert 'erased' not in facts         # a knowledge secret would give the reveal away
        assert '[dorren-age]' not in facts   # ids are the checker's
        assert "Tessa Merrin:\n> \"I walked it." in sections['How They Speak']
        assert 'What did the council gain' in sections['Notes']

    def test_a_fact_true_from_a_scene_is_not_standing(self, facts_project_dir):
        bibles.add_facts(facts_project_dir, [{'type': 'world', 'subject': '',
                                              'statement': 'The ridge has collapsed',
                                              'scene_id': 'act2-sc02'}], command='test')
        assert 'ridge has collapsed' not in bibles.drafting_text(facts_project_dir)

    def test_a_book_without_rows_gets_nothing(self, project_dir):
        assert bibles.drafting_sections(project_dir) == []

    def test_shared_context_carries_them(self, facts_project_dir):
        from storyforge.common import build_shared_context
        text = '\n'.join(b['text'] for b in build_shared_context(facts_project_dir,
                                                                 'claude-opus-5-5'))
        assert '=== Settled Facts ===' in text and '=== How They Speak ===' in text
        assert 'Character Bible' not in text

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


# ---------------------------------------------------------------------------
# Elaborate writes rows
# ---------------------------------------------------------------------------

class TestElaborate:
    def test_prose_stage_prompts_ask_for_rows(self, project_dir, plugin_dir):
        from storyforge import prompts_elaborate as pe
        for prompt in (pe.build_spine_prompt(project_dir, plugin_dir, 'seed'),
                       pe.build_architecture_prompt(project_dir, plugin_dir)):
            assert '```bible-facts-csv' in prompt and '```character-voices-csv' in prompt
            assert '```character-bible' not in prompt and '```world-bible' not in prompt

    def test_a_graphic_novel_keeps_its_essays(self, project_dir_gn, plugin_dir):
        from storyforge import prompts_elaborate as pe
        prompt = pe.build_spine_prompt(project_dir_gn, plugin_dir, 'seed')
        assert '```character-bible' in prompt and 'bible-facts-csv' not in prompt

    def test_the_writer_adds_each_block(self, project_dir):
        from storyforge.cmd_elaborate import _apply_bible_block
        written = []
        _apply_bible_block(project_dir, 'bible-facts-csv',
                           'type|subject|statement|known_by|category\n'
                           'trait|pell|Is a ferryman||role\n', written)
        _apply_bible_block(project_dir, 'character-voices-csv',
                           'character|line\npell|"Mind the rope."\n', written)
        _apply_bible_block(project_dir, 'bible-notes', '- The ferry is old.', written)
        assert written == ['commitments.csv (1 plan facts)', 'character-voices.csv (1 lines)',
                           'bible-notes.md (notes added)']
        assert any(r['id'] == 'pell-is-a-ferryman' for r in ledger.load(project_dir))

    def test_a_bad_block_is_an_error_and_writes_nothing(self, project_dir, capsys):
        from storyforge.cmd_elaborate import _apply_bible_block
        before = _read(ledger.ledger_path(project_dir))
        written = []
        _apply_bible_block(project_dir, 'bible-facts-csv',
                           'type|subject|statement\nessay|pell|x\n', written)
        assert written == [] and _read(ledger.ledger_path(project_dir)) == before
        captured = capsys.readouterr()
        assert "bible-facts-csv block wasn't written" in captured.out + captured.err


class TestBibleText:
    def test_the_essay_while_it_is_there(self, project_dir):
        assert bibles.bible_text(project_dir, 'character-bible.md').startswith('# Character Bible')

    def test_the_rows_once_retired(self, facts_project_dir):
        text = bibles.bible_text(facts_project_dir, 'character-bible.md')
        assert 'Believes the maps are objective' in text and 'How they speak' in text
        assert 'answers to the council' not in text
        world = bibles.bible_text(facts_project_dir, 'world-bible.md')
        assert 'answers to the council' in world and 'brass instruments' in world

    def test_nothing_for_a_book_with_neither(self, project_dir):
        assert bibles.bible_text(project_dir, 'world-bible.md') == ''

    def test_hone_reads_the_rows(self, facts_project_dir, monkeypatch):
        """The registry pass's character context, once the essay is retired."""
        from storyforge import cmd_hone, hone
        seen = {}
        monkeypatch.setattr(hone, 'reconcile_domain',
                            lambda domain, ref_dir, model, log_dir, context='': seen.update(
                                context=context) or {})
        cmd_hone._run_registry_domain('characters', _ref(facts_project_dir), facts_project_dir,
                                      '', 'm', _ref(facts_project_dir, 'character-bible.md'),
                                      False)
        assert 'Believes the maps are objective' in seen['context']


def test_an_unreadable_registry_is_said_not_raised(facts_project_dir):
    with open(_ref(facts_project_dir, 'characters.csv'), 'wb') as f:
        f.write(b'id|name\n\xff\xfe|x\n')
    gaps, notes = _gaps(facts_project_dir)
    assert any("characters.csv can't be read" in n for n in notes)
    assert any(g.kind == 'unsettled-reveal' for g in gaps)
