"""Extraction's census of named people (#546, storyforge-evals B-007)."""

import json
import os

from storyforge import api
from storyforge.extract_census import (
    Candidate, build_census_prompt, count_names, parse_census, run_census,
)

BEOWULF = {
    'hrothgar-speaks': "Then Hrothgar spake, the son of Healfdene:\\\n"
                       "I knew him of yore, the bairn of Ecgtheow. Ecgtheow fought the Wylfings.\n"
                       "To Healfdene's hall came Wealhtheow. Then the Geats rode home.",
    'ohthere': "The sons of Ohtere fled. Ohtere's kin were outlaws. The Geats grieved. Healfdene slept.",
}


def test_count_finds_names_by_lineage_and_skips_the_registry():
    found = {c.word: c for c in count_names(BEOWULF, known={'hrothgar', 'wealhtheow'})}
    assert found['Healfdene'].mentions == 3
    assert found['Ecgtheow'].mentions == 2
    assert found['Ohtere'].mentions == 2          # "Ohtere's" counts as Ohtere
    assert 'Hrothgar' not in found and 'Wealhtheow' not in found
    assert 'Then' not in found and 'The' not in found
    assert found['Healfdene'].passages and found['Healfdene'].passages[0].startswith('hrothgar-speaks:')


def test_a_word_only_at_sentence_starts_is_not_a_name():
    found = {c.word for c in count_names({'s': 'Fearing nothing, he went. Fearing all, she stayed.'},
                                         known=set())}
    assert 'Fearing' not in found


def test_registry_aliases_count_only_whole():
    """"ohtere-sons" on Eadgils hid Ohthere himself (B-007)."""
    import tempfile
    with tempfile.TemporaryDirectory() as ref:
        with open(os.path.join(ref, 'characters.csv'), 'w') as f:
            f.write('id|name|role|aliases\neadgils|Eadgils|minor|ohtere-sons;Eadgils the Swede\n')
        from storyforge.extract_census import _registry_words
        words = _registry_words(ref)
        assert 'eadgils' in words and 'ohtere' not in words


def _reply(names):
    return json.dumps({'names': names})


def test_parse_keeps_people_and_drops_groups():
    cands = [Candidate('Ecgtheow', 16, ['a']), Candidate('Geats', 29, ['a']),
             Candidate('Ohtere', 5, ['a'])]
    rows = parse_census(_reply([
        {'word': 'Ecgtheow', 'person': True, 'id': 'ecgtheow', 'name': 'Ecgtheow',
         'aliases': ['Edgetheow', 'the sons of Ecgtheow']},
        {'word': 'Geats', 'person': False, 'id': '', 'name': '', 'aliases': []},
        {'word': 'Ohtere', 'person': True, 'id': 'hrothgar', 'name': 'Ohtere', 'aliases': []},
        {'word': 'Unasked', 'person': True, 'id': 'x', 'name': 'X', 'aliases': []},
    ]), cands, registry_ids={'hrothgar'})
    assert rows == [{'id': 'ecgtheow', 'name': 'Ecgtheow', 'role': 'referenced',
                     'aliases': 'Edgetheow'}]


def test_prompt_lists_words_passages_and_registry():
    prompt = build_census_prompt([Candidate('Atreus', 135, ['a'], ['a: the son of Atreus'])],
                                 [{'id': 'agamemnon', 'name': 'Agamemnon'}])
    assert 'Atreus (135 mentions)' in prompt and 'a: the son of Atreus' in prompt
    assert 'agamemnon — Agamemnon' in prompt
    assert 'Judge from the passages only' in prompt


def test_run_census_appends_rows_and_writes_the_list(project_dir, monkeypatch):
    scenes = os.path.join(project_dir, 'scenes')
    ids = sorted(f[:-3] for f in os.listdir(scenes) if f.endswith('.md'))
    with open(os.path.join(scenes, f'{ids[0]}.md'), 'a') as f:
        f.write('\n\nShe thought of old Quillon, and of Quillon\'s debts, and of Varrow.\n')
    with open(os.path.join(project_dir, 'reference', 'characters.csv')) as f:
        before = f.read()

    def fake(prompt, model, log_file, max_tokens=4096, **kw):
        assert 'Quillon' in prompt
        reply = {'content': [{'type': 'text', 'text': _reply([
            {'word': 'Quillon', 'person': True, 'id': 'quillon', 'name': 'Quillon',
             'aliases': []}])}],
                 'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 1}}
        with open(log_file, 'w') as f:
            json.dump(reply, f)
        return reply
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    result = run_census(project_dir, 'm', os.path.join(project_dir, 'working', 'logs'))
    assert [r['id'] for r in result.added] == ['quillon']
    with open(os.path.join(project_dir, 'reference', 'characters.csv')) as f:
        after = f.read()
    assert 'quillon|Quillon|referenced|' in after
    for line in before.strip().split('\n')[1:]:
        assert line.split('|')[0] in after
    with open(os.path.join(project_dir, 'working', 'census.csv')) as f:
        census = f.read()
    assert census.startswith('word|mentions|scenes|answer')
    assert 'Quillon|2|' in census and '|person' in census
