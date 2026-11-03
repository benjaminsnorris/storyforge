"""characters.csv `pronouns`: the drafting prompt gives them even when the
ledger is empty, and `validate` checks them. Wrong gender is one of the
commonest errors the gate catches (E8: a dead girl turned into a boy, Sarel
Davan made a woman); every one of the author's books now has the column."""

import os

import pytest

from storyforge import ledger
from storyforge.elaborate import validate_structure
from storyforge.prompts import build_scene_prompt_from_briefs

from conftest import PLUGIN_DIR

SCENE = 'act1-sc01'   # POV Dorren Hayle


def _pronouns(project_dir, values, column=True):
    """Give characters.csv a pronouns column: id → value, others empty."""
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    with open(path) as f:
        lines = f.read().splitlines()
    if column:
        lines = [lines[0] + '|pronouns'] + [
            line + '|' + values.get(line.split('|')[0], '') for line in lines[1:]]
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def _empty_ledger(project_dir):
    with open(os.path.join(project_dir, 'reference', ledger.LEDGER_FILE), 'w') as f:
        f.write('|'.join(ledger.COLUMNS) + '\n')


def _prompt(project_dir):
    return build_scene_prompt_from_briefs(SCENE, project_dir, PLUGIN_DIR)


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

    def test_with_a_ledger_they_sit_beside_its_facts(self, project_dir):
        _pronouns(project_dir, {'dorren-hayle': 'she'})
        assert '### Dorren Hayle\nPronouns: she' in _prompt(project_dir)


def _registry(project_dir):
    return {c['check']: c for c in validate_structure(os.path.join(project_dir, 'reference'))
            ['checks'] if c['category'] == 'registry'}


class TestValidate:

    def test_no_column_is_advisory(self, project_dir):
        c = _registry(project_dir)['character-pronouns']
        assert not c['passed'] and c['severity'] == 'advisory'

    def test_every_value_valid_passes(self, project_dir):
        _pronouns(project_dir, {'dorren-hayle': 'she', 'tessa-merrin': 'She/her'})
        checks = _registry(project_dir)
        assert checks['character-pronouns-values']['passed']
        assert 'character-pronouns' not in checks

    def test_a_bad_value_blocks(self, project_dir):
        _pronouns(project_dir, {'dorren-hayle': 'female'})
        result = validate_structure(os.path.join(project_dir, 'reference'))
        c = next(x for x in result['checks'] if x['check'] == 'character-pronouns-values')
        assert not c['passed'] and c['severity'] == 'blocking'
        assert "dorren-hayle ('female')" in c['message']
        assert not result['passed']

    def test_a_character_with_none_is_advisory(self, project_dir):
        _pronouns(project_dir, {'dorren-hayle': 'she'})
        c = _registry(project_dir)['character-pronouns-missing']
        assert not c['passed'] and c['severity'] == 'advisory'
        assert 'tessa-merrin' in c['message'] and 'dorren-hayle' not in c['message']

    @pytest.mark.parametrize('value', ['he', 'she', 'they', 'it', 'he/him', 'they/them'])
    def test_the_accepted_forms(self, project_dir, value):
        _pronouns(project_dir, {'dorren-hayle': value})
        assert _registry(project_dir)['character-pronouns-values']['passed']
