"""An adaptation's characters take their pronouns from the imported source
(#515): `source.character_pronouns` is the one resolver, and the drafting
prompt (`prompts._established_facts_block`), the gate's speaker check
(`gate._cast`) and validate (`elaborate._validate_pronouns`, plus the counts
line in `storyforge validate`) all read it. The project's own cell wins; then
the source row with the same id; then the one source character with that
name or alias. Nothing is written to the project's characters.csv, and a
project without a `source:` block reads exactly what it did before."""

import os

import pytest

from storyforge import common, gate, source
from storyforge.elaborate import validate_structure
from storyforge.prompts import _established_facts_block

from source_helpers import SOURCE_FILES, YAML, _write, import_source, make_adaptation

# The tiny source's registry with a pronouns column, and two homonyms the
# name map keeps apart (as the Homer map splits Xanthus)
SOURCE_CHARACTERS = (
    'id|name|role|aliases|pronouns\n'
    'jove|Jove|supporting|son of Saturn|he\n'
    'minerva|Minerva|supporting|Pallas Minerva;Pallas|she/her\n'
    'ulysses|Ulysses|protagonist||he\n'
    'telemachus|Telemachus|protagonist||he\n'
    'narrator|Narrator|minor||\n'
    'xanthus|Xanthus|minor||he\n'
    'xanthus-horse|Xanthus|minor||it\n'
    'eurycleia|Eurycleia|minor|the nurse|she\n'
)

NAME_MAP_EXTRA = (
    'xanthus|xanthus-son-of-phaenops|Xanthus|Xanthus\n'
    'xanthus-horse|xanthus-horse-of-achilles|Xanthus|Xanthus\n'
    'eurycleia|eurycleia|Eurycleia|Eurycleia\n'
)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    common.clear_shared_context_cache()
    monkeypatch.setattr(gate, '_WARNED', set())
    yield
    common.clear_shared_context_cache()


def _adaptation(tmp_path, characters, source_chars=SOURCE_CHARACTERS, mode='faithful'):
    """The tiny adaptation with `characters` as its characters.csv, its
    source's registry `source_chars`, imported."""
    proj = make_adaptation(tmp_path)
    _write(str(tmp_path / 'odyssey'), {'reference/characters.csv': source_chars})
    with open(os.path.join(proj, 'reference', 'names.csv'), 'a', encoding='utf-8') as f:
        f.write(NAME_MAP_EXTRA)
    _write(proj, {'storyforge.yaml': YAML.format(extra=f'  mode: {mode}'),
                  'reference/characters.csv': characters})
    import_source(proj)
    return proj


def _chars(*rows, header='id|name|role|aliases|pronouns'):
    return header + '\n' + ''.join(r + '\n' for r in rows)


CAST = _chars('zeus|Zeus|supporting||',
              'athena|Athena|supporting|Pallas Athena|',
              'odysseus|Odysseus|protagonist||they',
              'telemachus|Telemachus|protagonist||')


def _resolved(proj):
    return source.character_pronouns(proj).by_id


class TestTheResolver:

    def test_the_own_value_wins_and_the_source_value_is_kept(self, tmp_path):
        p = _resolved(_adaptation(tmp_path, CAST))['odysseus']
        assert (p.value, p.origin, p.slug, p.match, p.source_values) == (
            'they', source.OWN, 'odyssey', 'id', (('odyssey', 'he'),))

    def test_an_empty_cell_takes_the_source_row_with_the_same_id(self, tmp_path):
        r = _resolved(_adaptation(tmp_path, CAST))
        assert (r['zeus'].value, r['zeus'].origin, r['zeus'].match) == (
            'he', source.FROM_SOURCE, 'id')
        # as written in the source
        assert r['athena'].value == 'she/her' and r['athena'].slug == 'odyssey'

    @pytest.mark.parametrize('row', ['nurse|Old Nurse|minor|the nurse|',   # by alias
                                     'nurse|Eurycleia|minor||',             # by name
                                     'nurse|EURYCLEIA|minor|  The   Nurse |'])  # case, spacing
    def test_a_unique_name_or_alias_matches(self, tmp_path, row):
        r = _resolved(_adaptation(tmp_path, _chars(row)))
        assert (r['nurse'].value, r['nurse'].origin, r['nurse'].match) == (
            'she', source.FROM_SOURCE, 'name')

    def test_two_project_characters_claiming_one_source_character_get_neither(self, tmp_path):
        r = _resolved(_adaptation(tmp_path, _chars('nurse|Old Nurse|minor|the nurse|',
                                                   'eury|Eurycleia|minor||')))
        for cid in ('nurse', 'eury'):
            assert r[cid].origin == source.NO_PRONOUNS
            assert 'source character eurycleia matches 2 characters by name' in r[cid].note

    def test_names_matching_two_different_source_characters_give_none(self, tmp_path):
        r = _resolved(_adaptation(tmp_path, _chars('x|Eurycleia|minor|Telemachus|')))
        assert r['x'].origin == source.NO_PRONOUNS
        assert 'its names match 2 source characters (eurycleia, telemachus)' in r['x'].note

    def test_a_name_two_source_characters_share_matches_neither(self, tmp_path):
        # both Xanthuses are "he"-or-"it"; even so a name match never guesses
        r = _resolved(_adaptation(tmp_path, _chars('xanthus|Xanthus|minor||')))
        assert (r['xanthus'].value, r['xanthus'].origin) == ('', source.NO_PRONOUNS)
        assert "'xanthus' is the name of 2 source characters" in r['xanthus'].note
        assert 'xanthus-horse-of-achilles, xanthus-son-of-phaenops' in r['xanthus'].note

    def test_homonyms_that_agree_still_match_neither(self, tmp_path):
        chars = SOURCE_CHARACTERS.replace('xanthus-horse|Xanthus|minor||it',
                                          'xanthus-horse|Xanthus|minor||he')
        r = _resolved(_adaptation(tmp_path, _chars('xanthus|Xanthus|minor||'), chars))
        assert r['xanthus'].origin == source.NO_PRONOUNS
        assert "'xanthus' is the name of 2 source characters" in r['xanthus'].note

    def test_a_homonym_with_its_own_id_matches_by_id(self, tmp_path):
        r = _resolved(_adaptation(tmp_path, _chars(
            'xanthus-horse-of-achilles|Xanthus|minor||')))
        assert r['xanthus-horse-of-achilles'].value == 'it'

    def test_a_unique_alias_beats_a_shared_name(self, tmp_path):
        chars = SOURCE_CHARACTERS.replace('xanthus|Xanthus|minor||he',
                                          'xanthus|Xanthus|minor|son of Phaenops|he')
        r = _resolved(_adaptation(tmp_path, _chars(
            'x|Xanthus|minor|son of Phaenops|'), chars))
        assert (r['x'].value, r['x'].match) == ('he', 'name')

    def test_a_name_another_project_character_holds_by_id_is_not_taken(self, tmp_path):
        # Mentes is Athena in disguise here: Athena is already the project's
        r = _resolved(_adaptation(tmp_path, _chars('athena|Athena|supporting||',
                                                   'mentes|Mentes|minor|Athena|')))
        assert r['athena'].value == 'she/her'
        assert r['mentes'].origin == source.NO_PRONOUNS
        assert 'another character in characters.csv' in r['mentes'].note

    def test_a_character_not_in_the_source_has_none_and_no_note(self, tmp_path):
        r = _resolved(_adaptation(tmp_path, _chars('noemon|Noemon|minor||')))
        assert (r['noemon'].origin, r['noemon'].note) == (source.NO_PRONOUNS, '')

    def test_an_unreadable_source_value_is_reported_not_used(self, tmp_path):
        chars = SOURCE_CHARACTERS.replace('jove|Jove|supporting|son of Saturn|he',
                                          'jove|Jove|supporting|son of Saturn|he/her')
        p = _resolved(_adaptation(tmp_path, CAST, chars))['zeus']
        assert (p.value, p.origin) == ('', source.NO_PRONOUNS)
        assert "source odyssey gives 'he/her', which is not a pronoun" in p.problem

    def test_a_source_with_no_pronouns_column_is_a_note(self, tmp_path):
        proj = _adaptation(tmp_path, CAST, SOURCE_FILES['reference/characters.csv'])
        res = source.character_pronouns(proj)
        assert res.notes == ('reference/source/odyssey/characters.csv has no pronouns '
                             'column, so no pronouns are read from it',)
        assert res.by_id['zeus'].origin == source.NO_PRONOUNS

    def test_a_source_not_imported_is_a_note(self, tmp_path):
        proj = _adaptation(tmp_path, CAST)
        import shutil
        shutil.rmtree(source.source_dir(proj, 'odyssey'))
        res = source.character_pronouns(proj)
        assert 'source odyssey is not imported' in res.notes[0]
        assert res.by_id['zeus'].origin == source.NO_PRONOUNS

    def test_nothing_is_written(self, tmp_path):
        proj = _adaptation(tmp_path, CAST)
        path = os.path.join(proj, 'reference', 'characters.csv')
        with open(path, 'rb') as f:
            before = f.read()
        source.character_pronouns(proj)
        validate_structure(os.path.join(proj, 'reference'))
        with open(path, 'rb') as f:
            assert f.read() == before

    def test_the_counts_line(self, tmp_path):
        proj = _adaptation(tmp_path, CAST + 'noemon|Noemon|minor||\n')
        assert source.character_pronouns(proj).counts_line() == (
            'Pronouns: 1 own, 3 from source odyssey, 1 none (noemon)')


TWO_SOURCES = """project:
  title: "Telemachus"
source:
  projects:
    - slug: odyssey
      path: ../odyssey
    - slug: iliad
      path: ../iliad
  name_map: reference/names.csv
  mode: free
"""


def _two(tmp_path, characters, iliad_chars):
    proj = _adaptation(tmp_path, characters)
    _write(str(tmp_path / 'iliad'), {**SOURCE_FILES, 'reference/characters.csv': iliad_chars})
    _write(proj, {'storyforge.yaml': TWO_SOURCES})
    cfg = source.read_config(proj)
    source.import_source(proj, cfg, 'iliad')
    return proj


class TestTwoSources:

    def test_one_person_in_both_is_matched_once(self, tmp_path):
        r = _resolved(_two(tmp_path, CAST, SOURCE_CHARACTERS))
        assert (r['zeus'].value, r['zeus'].slug) == ('he', 'odyssey')

    def test_the_first_with_a_value_gives_it(self, tmp_path):
        r = _resolved(_two(tmp_path, CAST, SOURCE_CHARACTERS.replace(
            'telemachus|Telemachus|protagonist||he', 'telemachus|Telemachus|protagonist||')
            .replace('narrator|Narrator|minor||', 'narrator|Narrator|minor||she')))
        assert (r['telemachus'].value, r['telemachus'].slug) == ('he', 'odyssey')
        proj = tmp_path / 'p2'
        proj.mkdir()
        r = _resolved(_two(proj, _chars('narrator|Narrator|minor||'), SOURCE_CHARACTERS
                           .replace('narrator|Narrator|minor||', 'narrator|Narrator|minor||she')))
        assert (r['narrator'].value, r['narrator'].slug) == ('she', 'iliad')

    def test_sources_that_disagree_give_none(self, tmp_path):
        r = _resolved(_two(tmp_path, CAST, SOURCE_CHARACTERS.replace(
            'jove|Jove|supporting|son of Saturn|he', 'jove|Jove|supporting|son of Saturn|she')))
        assert r['zeus'].origin == source.NO_PRONOUNS
        assert "the sources disagree (odyssey: 'he', iliad: 'she')" in r['zeus'].problem

    def test_a_name_unique_in_each_source_but_two_people_across_them(self, tmp_path):
        # each source has one Eurycleia, but they are different people (ids)
        iliad = SOURCE_CHARACTERS.replace('eurycleia|Eurycleia|minor|the nurse|she',
                                          'eurycleia-of-troy|Eurycleia|minor||she')
        iliad_map = 'eurycleia-of-troy|eurycleia-of-troy|Eurycleia|Eurycleia\n'
        proj = _adaptation(tmp_path, _chars('eury|Eurycleia|minor||'))
        with open(os.path.join(proj, 'reference', 'names.csv'), 'a', encoding='utf-8') as f:
            f.write(iliad_map)
        _write(str(tmp_path / 'iliad'), {**SOURCE_FILES, 'reference/characters.csv': iliad})
        _write(proj, {'storyforge.yaml': TWO_SOURCES})
        source.import_source(proj, source.read_config(proj), 'iliad')
        r = _resolved(proj)
        assert r['eury'].origin == source.NO_PRONOUNS
        assert 'eurycleia, eurycleia-of-troy' in r['eury'].note


class TestWithoutASource:

    def test_every_value_is_the_own_cell(self, project_dir):
        path = os.path.join(project_dir, 'reference', 'characters.csv')
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join([lines[0] + '|pronouns', lines[1] + '|she']
                              + [line + '|' for line in lines[2:]]) + '\n')
        res = source.character_pronouns(project_dir)
        assert res.mode == '' and res.notes == ()
        first = lines[1].split('|')[0]
        assert (res.by_id[first].value, res.by_id[first].origin) == ('she', source.OWN)
        assert all(p.origin == source.NO_PRONOUNS and not p.note
                   for cid, p in res.by_id.items() if cid != first)

    def test_validate_has_no_source_checks(self, project_dir):
        checks = validate_structure(os.path.join(project_dir, 'reference'))['checks']
        assert not [c for c in checks if c['check'].startswith('character-pronouns-source')]


def _checks(proj, name):
    return [c for c in validate_structure(os.path.join(proj, 'reference'))['checks']
            if c['check'] == name]


class TestValidate:

    def test_source_pronouns_are_not_missing(self, tmp_path):
        proj = _adaptation(tmp_path, CAST + 'noemon|Noemon|minor||\n')
        [missing] = _checks(proj, 'character-pronouns-missing')
        assert missing['message'] == 'Characters with no pronouns (the writer guesses): noemon'

    def test_no_pronouns_column_is_fine_when_the_source_has_them(self, tmp_path):
        proj = _adaptation(tmp_path, _chars('zeus|Zeus|supporting|', header='id|name|role|aliases'))
        assert not _checks(proj, 'character-pronouns-column')
        [missing] = _checks(proj, 'character-pronouns-missing')
        assert missing['passed']

    @pytest.mark.parametrize('mode, severity', [('faithful', 'blocking'), ('free', 'advisory')])
    def test_an_own_value_differing_from_the_source(self, tmp_path, mode, severity):
        proj = _adaptation(tmp_path, CAST, mode=mode)
        [c] = _checks(proj, 'character-pronouns-source-mismatch')
        assert not c['passed'] and c['severity'] == severity
        assert "odysseus ('they' in characters.csv, 'he' in source odyssey)" in c['message']
        report = validate_structure(os.path.join(proj, 'reference'))
        assert c in report['failures'] and report['passed'] is (mode == 'free')

    def test_the_same_pronoun_in_another_form_is_no_mismatch(self, tmp_path):
        proj = _adaptation(tmp_path, CAST.replace('odysseus|Odysseus|protagonist||they',
                                                  'odysseus|Odysseus|protagonist||He/him'))
        [c] = _checks(proj, 'character-pronouns-source-mismatch')
        assert c['passed']

    def test_what_the_source_could_not_give_is_advisory(self, tmp_path):
        proj = _adaptation(tmp_path, _chars('xanthus|Xanthus|minor||'))
        [c] = _checks(proj, 'character-pronouns-source')
        assert not c['passed'] and c['severity'] == 'advisory'
        assert c['message'].startswith('Pronouns not read from the source: xanthus: ')

    def test_a_source_that_cannot_be_read_blocks(self, tmp_path):
        proj = _adaptation(tmp_path, CAST)
        with open(os.path.join(source.source_dir(proj, 'odyssey'), 'characters.csv'), 'a') as f:
            f.write('broken|row\n')
        [c] = _checks(proj, 'character-pronouns-source')
        assert not c['passed'] and c['severity'] == 'blocking'
        assert c['message'].startswith("The source's pronouns can't be read (source odyssey:")
        # the rest falls back to the project's own cells
        [missing] = _checks(proj, 'character-pronouns-missing')
        assert missing['message'].endswith('athena, telemachus, zeus')

    def test_the_command_prints_the_counts(self, tmp_path, capsys, monkeypatch):
        from storyforge import cmd_validate
        proj = _adaptation(tmp_path, CAST + 'noemon|Noemon|minor||\n')
        monkeypatch.setattr(cmd_validate, 'detect_project_root', lambda: proj)
        with pytest.raises(SystemExit) as exit_:
            cmd_validate.main(['--no-schema'])
        assert exit_.value.code == 1   # odysseus' faithful mismatch blocks
        out = capsys.readouterr().out
        assert '  Pronouns: 1 own, 3 from source odyssey, 1 none (noemon)' in out


class TestTheReaders:

    def _scene(self, proj):
        _write(proj, {'reference/scenes.csv': 'id|seq|title|pov\nat-the-door|1|Door|telemachus\n'})

    def test_the_drafting_prompt_gets_source_pronouns(self, tmp_path):
        proj = _adaptation(tmp_path, CAST)
        self._scene(proj)
        block = _established_facts_block(
            'at-the-door', {'pov': 'Telemachus', 'on_stage': 'Athena;Odysseus'}, proj, set())
        assert '### Telemachus\nPronouns: he' in block
        assert '### Athena\nPronouns: she/her' in block
        assert '### Odysseus\nPronouns: they' in block   # its own wins

    def test_the_prompt_warns_for_what_the_source_could_not_give(self, tmp_path, capsys):
        proj = _adaptation(tmp_path, CAST + 'xanthus|Xanthus|minor||\n')
        self._scene(proj)
        _established_facts_block('at-the-door', {'pov': 'Telemachus', 'on_stage': 'Xanthus'},
                                 proj, set())
        out = capsys.readouterr().out
        assert ("no pronouns for Xanthus in characters.csv, and none from the source: "
                "'xanthus' is the name of 2 source characters") in out
        # said once, not again in the general list
        assert 'no pronouns in characters.csv or the source for' not in out

    def test_the_gate_cast_gets_source_pronouns(self, tmp_path):
        cast = gate._cast(_adaptation(tmp_path, CAST))
        assert cast.pronouns == {'zeus': 'he', 'athena': 'she', 'odysseus': 'they',
                                 'telemachus': 'he'}
        assert cast.warnings == ()

    def test_the_gate_warns_for_what_the_source_could_not_give(self, tmp_path):
        proj = _adaptation(tmp_path, CAST + 'xanthus|Xanthus|minor||\n')
        cast = gate._cast(proj)
        assert 'xanthus' not in cast.pronouns
        assert any(w.startswith("Xanthus: no pronouns in characters.csv or from the source "
                                "('xanthus' is the name of 2") for w in cast.warnings)

    def test_the_gate_warns_for_a_source_it_cannot_read(self, tmp_path):
        proj = _adaptation(tmp_path, CAST)
        with open(os.path.join(source.source_dir(proj, 'odyssey'), 'characters.csv'), 'a') as f:
            f.write('broken|row\n')
        cast = gate._cast(proj)
        assert cast.pronouns == {'odysseus': 'they'}
        assert "the source's pronouns can't be read" in cast.warnings[0]


# ----------------------------------------------------------------------------
# The 5-agent review's findings (PR #518)
# ----------------------------------------------------------------------------

def _two_sources(tmp_path, characters, iliad_chars, iliad_map=''):
    proj = _adaptation(tmp_path, characters)
    if iliad_map:
        with open(os.path.join(proj, 'reference', 'names.csv'), 'a', encoding='utf-8') as f:
            f.write(iliad_map)
    _write(str(tmp_path / 'iliad'), {**SOURCE_FILES, 'reference/characters.csv': iliad_chars})
    _write(proj, {'storyforge.yaml': TWO_SOURCES})
    source.import_source(proj, source.read_config(proj), 'iliad')
    return proj


def _one_scene(proj):
    _write(proj, {'reference/scenes.csv': 'id|seq|title|pov\nat-the-door|1|Door|telemachus\n'})


class TestReviewFindings:

    def test_sf1_a_source_without_the_column_still_counts_for_the_name_match(self, tmp_path):
        # the iliad's Eurycleia is another person, in a registry with no
        # pronouns column: the odyssey's must not be guessed for her
        iliad = SOURCE_FILES['reference/characters.csv'] + 'other-eury|Eurycleia|minor|\n'
        proj = _two_sources(tmp_path, _chars('x|Eurycleia|minor||'), iliad,
                            'other-eury|other-eury|Eurycleia|Eurycleia\n')
        res = source.character_pronouns(proj)
        assert res.by_id['x'].origin == source.NO_PRONOUNS
        assert "'eurycleia' is the name of 2 source characters" in res.by_id['x'].note
        assert any('iliad/characters.csv has no pronouns column' in n for n in res.notes)

    def test_sf1_an_id_only_in_a_columnless_source_gives_none(self, tmp_path):
        iliad = SOURCE_FILES['reference/characters.csv'] + 'other-eury|Eurycleia|minor|\n'
        proj = _two_sources(tmp_path, _chars('other-eury|Eurycleia|minor||'), iliad,
                            'other-eury|other-eury|Eurycleia|Eurycleia\n')
        p = source.character_pronouns(proj).by_id['other-eury']
        assert (p.origin, p.match) == (source.NO_PRONOUNS, 'id')

    def test_cr1_an_own_value_against_an_unreadable_source_value_is_reported(self, tmp_path):
        chars = SOURCE_CHARACTERS.replace('ulysses|Ulysses|protagonist||he',
                                          'ulysses|Ulysses|protagonist||xe')
        proj = _adaptation(tmp_path, CAST, chars)
        [c] = _checks(proj, 'character-pronouns-source')
        assert not c['passed']
        assert "odysseus: source odyssey gives 'xe', which is not a pronoun" in c['message']

    def test_sf2_an_own_value_is_compared_with_sources_that_disagree(self, tmp_path):
        proj = _two_sources(tmp_path, CAST, SOURCE_CHARACTERS.replace(
            'ulysses|Ulysses|protagonist||he', 'ulysses|Ulysses|protagonist||she'))
        [c] = _checks(proj, 'character-pronouns-source-mismatch')
        assert not c['passed'] and c['severity'] == 'advisory'   # free
        assert ("odysseus ('they' in characters.csv, 'he' in source odyssey, "
                "'she' in source iliad)") in c['message']
        [u] = _checks(proj, 'character-pronouns-source')
        assert 'odysseus: the sources disagree' in u['message']

    def test_sf_m1_an_unreadable_value_beside_a_readable_one_is_not_a_disagreement(
            self, tmp_path):
        proj = _two_sources(tmp_path, CAST, SOURCE_CHARACTERS.replace(
            'jove|Jove|supporting|son of Saturn|he', 'jove|Jove|supporting|son of Saturn|xyz'))
        p = source.character_pronouns(proj).by_id['zeus']
        assert (p.value, p.origin, p.slug) == ('he', source.FROM_SOURCE, 'odyssey')
        assert p.problem == ("source iliad gives 'xyz', which is not a pronoun storyforge "
                             "knows, so it is not used")

    def test_t4_sources_agreeing_in_another_form_agree(self, tmp_path):
        proj = _two_sources(tmp_path, CAST, SOURCE_CHARACTERS.replace(
            'jove|Jove|supporting|son of Saturn|he', 'jove|Jove|supporting|son of Saturn|He/him'))
        p = source.character_pronouns(proj).by_id['zeus']
        assert (p.value, p.problem) == ('he', '')

    def test_t1_an_empty_ledger_and_source_pronouns_only(self, tmp_path):
        proj = _adaptation(tmp_path, _chars('telemachus|Telemachus|protagonist||'))
        _one_scene(proj)
        block = _established_facts_block('at-the-door', {'pov': 'Telemachus'}, proj, set())
        assert '### Telemachus\nPronouns: he' in block

    def test_t2_an_adaptation_with_no_column_warns_about_a_character_with_none(
            self, tmp_path, capsys):
        proj = _adaptation(tmp_path, _chars('telemachus|Telemachus|protagonist|',
                                            'noemon|Noemon|minor|', header='id|name|role|aliases'))
        _one_scene(proj)
        block = _established_facts_block('at-the-door',
                                         {'pov': 'Telemachus', 'on_stage': 'Noemon'}, proj, set())
        assert '### Telemachus\nPronouns: he' in block
        assert 'no pronouns in characters.csv or the source for Noemon' in capsys.readouterr().out

    def test_sf_m2_an_empty_ledger_still_says_what_the_source_could_not_give(
            self, tmp_path, capsys):
        chars = SOURCE_CHARACTERS.replace('telemachus|Telemachus|protagonist||he',
                                          'telemachus|Telemachus|protagonist||xyz')
        proj = _adaptation(tmp_path, _chars('telemachus|Telemachus|protagonist||'), chars)
        _one_scene(proj)
        assert _established_facts_block('at-the-door', {'pov': 'Telemachus'}, proj, set()) == ''
        assert "source odyssey gives 'xyz'" in capsys.readouterr().out

    def test_sf_m3_the_prompt_logs_a_source_wide_note_once(self, tmp_path, capsys, monkeypatch):
        from storyforge import prompts
        monkeypatch.setattr(prompts, '_SOURCE_NOTES_LOGGED', set())
        proj = _adaptation(tmp_path, CAST, SOURCE_FILES['reference/characters.csv'])
        _one_scene(proj)
        for _ in range(2):
            _established_facts_block('at-the-door', {'pov': 'Telemachus'}, proj, set())
        out = capsys.readouterr().out
        assert out.count('odyssey/characters.csv has no pronouns column') == 1

    def test_t3_validate_reports_a_source_wide_note(self, tmp_path):
        proj = _adaptation(tmp_path, CAST, SOURCE_FILES['reference/characters.csv'])
        [c] = _checks(proj, 'character-pronouns-source')
        assert not c['passed'] and 'has no pronouns column' in c['message']

    def test_t5_the_gate_says_a_source_wide_note(self, tmp_path):
        proj = _adaptation(tmp_path, CAST, SOURCE_FILES['reference/characters.csv'])
        assert any('has no pronouns column' in w for w in gate._cast(proj).warnings)

    def test_t6_validate_says_when_the_source_cannot_be_read(self, tmp_path, capsys,
                                                             monkeypatch):
        from storyforge import cmd_validate
        proj = _adaptation(tmp_path, CAST)
        with open(os.path.join(source.source_dir(proj, 'odyssey'), 'characters.csv'), 'a') as f:
            f.write('broken|row\n')
        monkeypatch.setattr(cmd_validate, 'detect_project_root', lambda: proj)
        with pytest.raises(SystemExit) as exit_:
            cmd_validate.main(['--no-schema'])
        assert exit_.value.code == 1
        assert "  Pronouns: the source's can't be read (source odyssey:" in capsys.readouterr().out

    def test_t8_an_empty_source_registry_and_rows_without_ids_are_notes(self, tmp_path):
        proj = _adaptation(tmp_path, CAST, SOURCE_CHARACTERS + '|Nobody|minor||he\n')
        assert any('has 1 row(s) with no id' in n for n in source.character_pronouns(proj).notes)
        os.remove(os.path.join(source.source_dir(proj, 'odyssey'), 'characters.csv'))
        assert any('characters.csv is missing or empty' in n
                   for n in source.character_pronouns(proj).notes)

    def test_t8_a_project_row_with_no_id_is_keyed_by_its_name(self, tmp_path):
        proj = _adaptation(tmp_path, _chars('|Eurycleia|minor||'))
        r = _resolved(proj)
        assert (r['Eurycleia'].value, r['Eurycleia'].match) == ('she', 'name')
        assert gate._cast(proj).pronouns == {'Eurycleia': 'she'}

    def test_t9_counts_with_two_sources_none_and_many(self, tmp_path):
        many = ''.join(f'p{n}|P{n}|minor||\n' for n in range(12))
        proj = _two_sources(tmp_path, _chars('zeus|Zeus|supporting||', 'mentor|Mentor|minor||')
                            + many, SOURCE_CHARACTERS + 'mentor|Mentor|minor||he\n',
                            'mentor|mentor|Mentor|Mentor\n')
        assert source.character_pronouns(proj).counts_line() == (
            'Pronouns: 0 own, 1 from source odyssey, 1 from source iliad, 12 none '
            '(p0, p1, p2, p3, p4, p5, p6, p7, p8, p9 and 2 more)')
        other = tmp_path / 'other'
        other.mkdir()
        proj = _adaptation(other, _chars('zeus|Zeus|supporting||'))
        assert source.character_pronouns(proj).counts_line() == (
            'Pronouns: 0 own, 1 from source odyssey, 0 none')

    @pytest.mark.parametrize('args', [
        ('he', source.NO_PRONOUNS), ('', source.OWN), ('', source.FROM_SOURCE),
        ('xe', source.FROM_SOURCE, 'odyssey', 'id'), ('he', source.FROM_SOURCE),
        ('he', 'borrowed'),
    ])
    def test_td_a_pronoun_that_breaks_its_invariants_is_refused(self, args):
        with pytest.raises(ValueError):
            source.Pronoun(*args)
