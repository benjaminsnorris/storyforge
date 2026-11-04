"""characters.csv `pronouns`: the drafting prompt gives them even when the
ledger is empty, and `validate` checks them the same way
(`schema.pronoun_key`). Wrong gender is one of the commonest errors the
gate catches (E8: a dead girl turned into a boy, Sarel Davan made a woman)."""

import os

import pytest

from storyforge import ledger
from storyforge.elaborate import validate_structure
from storyforge.prompts import _established_facts_block, build_scene_prompt_from_briefs
from storyforge.schema import pronoun_key

from conftest import PLUGIN_DIR

SCENE = 'act1-sc01'   # POV Dorren Hayle, alone


def _chars_path(project_dir):
    return os.path.join(project_dir, 'reference', 'characters.csv')


def _pronouns(project_dir, values):
    """Give characters.csv a pronouns column: id → value, others empty."""
    path = _chars_path(project_dir)
    with open(path, encoding='utf-8', newline='') as f:
        lines = f.read().splitlines()
    lines = [lines[0] + '|pronouns'] + [
        line + '|' + values.get(line.split('|')[0], '') for line in lines[1:]]
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(lines) + '\n')


def _rewrite(project_dir, fn):
    path = _chars_path(project_dir)
    with open(path, encoding='utf-8', newline='') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(fn(text))


def _empty_ledger(project_dir):
    with open(os.path.join(project_dir, 'reference', ledger.LEDGER_FILE), 'w') as f:
        f.write('|'.join(ledger.COLUMNS) + '\n')


def _prompt(project_dir):
    return build_scene_prompt_from_briefs(SCENE, project_dir, PLUGIN_DIR)


def _block(project_dir, pov='Dorren Hayle', on_stage=''):
    return _established_facts_block(SCENE, {'pov': pov, 'on_stage': on_stage},
                                    project_dir, set())


class TestPronounKey:

    @pytest.mark.parametrize('value, key', [
        ('he', 'he'), ('she', 'she'), ('they', 'they'), ('it', 'it'),
        ('she/her', 'she'), ('he/him/his', 'he'), ('they/them/theirs', 'they'),
        (' She / Her ', 'she'), ('', ''), ('  ', ''),
        ('she/him', None), ('he/xyz', None), ('/him', None), ('he or she', None),
        ('female', None), ('xe', None), ('he/she', None),
    ])
    def test_forms(self, value, key):
        assert pronoun_key(value) == key


class TestTheDraftingPrompt:

    def test_an_empty_ledger_still_gives_the_pronouns(self, project_dir):
        _empty_ledger(project_dir)
        _pronouns(project_dir, {'dorren-hayle': 'she'})
        prompt = _prompt(project_dir)
        assert '## Established Facts' in prompt
        assert '### Dorren Hayle\nPronouns: she' in prompt

    def test_an_empty_ledger_and_no_pronouns_give_no_block(self, project_dir):
        _empty_ledger(project_dir)
        assert '## Established Facts' not in _prompt(project_dir)
        _pronouns(project_dir, {})   # the column, every cell empty
        assert '## Established Facts' not in _prompt(project_dir)

    def test_pronouns_only_off_stage_give_no_block(self, project_dir):
        _empty_ledger(project_dir)
        _pronouns(project_dir, {'tessa-merrin': 'she'})
        assert _block(project_dir) == ''

    def test_on_stage_characters_and_an_alias_pov_get_theirs(self, project_dir):
        _empty_ledger(project_dir)
        _pronouns(project_dir, {'dorren-hayle': 'she', 'tessa-merrin': 'She/her'})
        block = _block(project_dir, pov='Dorren', on_stage='Dorren;Tessa')
        assert block.count('### Dorren Hayle') == 1
        assert '### Dorren Hayle\nPronouns: she' in block
        assert '### Tessa Merrin\nPronouns: She/her' in block   # as written

    def test_with_a_ledger_they_sit_beside_its_facts(self, project_dir):
        _pronouns(project_dir, {'dorren-hayle': 'she'})
        # the line under the heading, before any of the ledger's facts
        assert '### Dorren Hayle\nPronouns: she\n' in _block(project_dir)

    def test_an_invalid_value_is_warned_and_never_shown(self, project_dir, capsys):
        _empty_ledger(project_dir)
        _pronouns(project_dir, {'dorren-hayle': 'she/him', 'tessa-merrin': 'she'})
        block = _block(project_dir, on_stage='Tessa Merrin')
        assert 'she/him' not in block and '### Tessa Merrin\nPronouns: she' in block
        out = capsys.readouterr().out
        assert "Dorren Hayle's pronouns in characters.csv ('she/him')" in out

    def test_a_character_with_none_is_warned(self, project_dir, capsys):
        _empty_ledger(project_dir)
        _pronouns(project_dir, {'dorren-hayle': 'she'})
        _block(project_dir, on_stage='Tessa Merrin')
        assert 'no pronouns in characters.csv for Tessa Merrin' in capsys.readouterr().out

    def test_no_column_warns_nothing_about_pronouns(self, project_dir, capsys):
        _block(project_dir, on_stage='Tessa Merrin')
        assert 'no pronouns in characters.csv' not in capsys.readouterr().out

    def test_an_unknown_name_says_its_pronouns_are_lost(self, project_dir, capsys):
        _empty_ledger(project_dir)
        _pronouns(project_dir, {'dorren-hayle': 'she'})
        _block(project_dir, on_stage='Nobody Atall')
        out = capsys.readouterr().out
        assert 'no pronouns or ledger facts for them: Nobody Atall' in out

    def test_a_location_never_gets_pronouns(self, project_dir):
        path = os.path.join(project_dir, 'reference', 'locations.csv')
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join([lines[0] + '|pronouns'] + [l + '|it' for l in lines[1:]]) + '\n')
        _pronouns(project_dir, {'dorren-hayle': 'she'})
        loc = lines[1].split('|')[1]
        block = _established_facts_block(SCENE, {'pov': 'Dorren Hayle', 'location': loc},
                                         project_dir, set())
        assert '(location)\nPronouns' not in block

    def test_a_bom_still_gives_them(self, project_dir):
        _empty_ledger(project_dir)
        _pronouns(project_dir, {'dorren-hayle': 'she'})
        _rewrite(project_dir, lambda t: '﻿' + t)
        assert '### Dorren Hayle\nPronouns: she' in _prompt(project_dir)

    def test_crlf_still_gives_them(self, project_dir):
        _empty_ledger(project_dir)
        _pronouns(project_dir, {'dorren-hayle': 'she'})
        _rewrite(project_dir, lambda t: t.replace('\n', '\r\n'))
        assert '### Dorren Hayle\nPronouns: she' in _prompt(project_dir)

    def test_an_empty_ledger_with_pronouns_needs_the_order(self, project_dir):
        _empty_ledger(project_dir)
        _pronouns(project_dir, {'dorren-hayle': 'she'})
        path = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(path) as f:
            text = f.read()
        with open(path, 'w') as f:
            f.write(text.replace('act2-sc03|6|', 'act2-sc03|x|'))
        with pytest.raises(ValueError, match='act2-sc03'):
            _block(project_dir)


def _checks(project_dir):
    return {c['check']: c for c in validate_structure(os.path.join(project_dir, 'reference'))
            ['checks'] if c['category'] == 'characters'}


class TestValidate:

    def test_no_column_is_advisory_and_says_what_to_add(self, project_dir):
        c = _checks(project_dir)['character-pronouns-column']
        assert not c['passed'] and c['severity'] == 'advisory'
        assert 'he, it, she, they' in c['message']

    def test_every_value_valid_passes(self, project_dir):
        _pronouns(project_dir, {'dorren-hayle': 'she', 'tessa-merrin': 'She/her'})
        checks = _checks(project_dir)
        assert checks['character-pronouns-values']['passed']
        assert 'character-pronouns-column' not in checks

    @pytest.mark.parametrize('value', ['female', 'she/him', 'he/xyz', 'xe'])
    def test_a_bad_value_blocks(self, project_dir, value):
        _pronouns(project_dir, {'dorren-hayle': value})
        result = validate_structure(os.path.join(project_dir, 'reference'))
        c = next(x for x in result['checks'] if x['check'] == 'character-pronouns-values')
        assert not c['passed'] and c['severity'] == 'blocking'
        assert f'dorren-hayle ({value!r})' in c['message']
        assert not result['passed']

    def test_a_character_with_none_is_advisory(self, project_dir):
        _pronouns(project_dir, {'dorren-hayle': 'she', 'tessa-merrin': '   '})
        c = _checks(project_dir)['character-pronouns-missing']
        assert not c['passed'] and c['severity'] == 'advisory'
        assert 'tessa-merrin' in c['message'] and 'dorren-hayle' not in c['message']

    def test_a_bom_does_not_hide_a_bad_value(self, project_dir):
        _pronouns(project_dir, {'dorren-hayle': 'female'})
        _rewrite(project_dir, lambda t: '﻿' + t)
        assert not _checks(project_dir)['character-pronouns-values']['passed']

    def test_crlf_does_not_hide_a_bad_value(self, project_dir):
        _pronouns(project_dir, {'dorren-hayle': 'female'})
        _rewrite(project_dir, lambda t: t.replace('\n', '\r\n'))
        assert not _checks(project_dir)['character-pronouns-values']['passed']

    def test_an_unreadable_file_blocks_rather_than_crashing(self, project_dir):
        with open(_chars_path(project_dir), 'wb') as f:
            f.write(b'id|name|pronouns\nann|Ren\xe9e|she\n')
        c = _checks(project_dir)['character-pronouns-column']
        assert not c['passed'] and c['severity'] == 'blocking'
        assert "can't be read" in c['message']

    def test_no_rows_with_an_id_is_not_clean(self, project_dir):
        with open(_chars_path(project_dir), 'w') as f:
            f.write('id|name|pronouns\n|Nobody|xe\n')
        c = _checks(project_dir)['character-pronouns-values']
        assert not c['passed'] and 'not checked' in c['message']

    def test_no_characters_file_is_said(self, project_dir):
        os.remove(_chars_path(project_dir))
        c = _checks(project_dir)['character-pronouns-column']
        assert not c['passed'] and c['severity'] == 'advisory'


def test_the_new_book_template_has_the_column():
    with open(os.path.join(PLUGIN_DIR, 'templates', 'reference', 'characters.csv')) as f:
        assert f.readline().rstrip('\n').split('|')[-1] == 'pronouns'


class TestLocationList:
    """`location` is an ordered list of places (`a;b`): each place is read,
    not the whole cell as one unknown name (gawain G-026)."""

    def _places(self, project_dir):
        path = os.path.join(project_dir, 'reference', 'locations.csv')
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
        return [l.split('|')[1] for l in lines[1:3]]

    def test_each_place_in_the_list_is_known(self, project_dir, capsys):
        _pronouns(project_dir, {'dorren-hayle': 'she'})
        first, second = self._places(project_dir)
        path = os.path.join(project_dir, 'reference', ledger.LEDGER_FILE)
        with open(path, 'a', encoding='utf-8') as f:
            for pid, fact in (('cartography-office', 'the office floods each spring'),
                              ('private-study', 'the study has no window')):
                row = dict.fromkeys(ledger.COLUMNS, '')
                row.update(id=f'{pid}-fact', type='physical', subject=pid,
                           statement=fact, status='binding', mutable='state')
                f.write('|'.join(row[c] for c in ledger.COLUMNS) + '\n')
        block = _established_facts_block(
            SCENE, {'pov': 'Dorren Hayle', 'location': f'{first};{second}'},
            project_dir, set())
        out = capsys.readouterr().out
        assert 'not in characters.csv or locations.csv' not in out
        assert 'the office floods each spring' in block
        assert 'the study has no window' in block
        assert block.count('(location)') == 2

    def test_an_unknown_place_in_the_list_is_named_alone(self, project_dir, capsys):
        _pronouns(project_dir, {'dorren-hayle': 'she'})
        first, _ = self._places(project_dir)
        _established_facts_block(
            SCENE, {'pov': 'Dorren Hayle', 'location': f'{first};Nowhere Atall'},
            project_dir, set())
        out = capsys.readouterr().out
        assert 'no pronouns or ledger facts for them: Nowhere Atall' in out
