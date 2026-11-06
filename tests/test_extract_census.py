"""Extraction's census of named people (#546, storyforge-evals B-007)."""

import json
import os

import pytest

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
                     'aliases': 'Edgetheow', 'pronouns': ''}]


def test_parse_keeps_readable_pronouns_only():
    """#513: a person's pronouns as the passages use them; a value
    `pronoun_key` can't read is left empty for validate to name."""
    cands = [Candidate('Wealhtheow', 9, ['a']), Candidate('Unferth', 7, ['a'])]
    rows = parse_census(_reply([
        {'word': 'Wealhtheow', 'person': True, 'id': 'wealhtheow', 'name': 'Wealhtheow',
         'aliases': [], 'pronouns': 'she/her'},
        {'word': 'Unferth', 'person': True, 'id': 'unferth', 'name': 'Unferth',
         'aliases': [], 'pronouns': 'unclear'},
    ]), cands, registry_ids=set())
    assert [(r['id'], r['pronouns']) for r in rows] == [('wealhtheow', 'she/her'),
                                                        ('unferth', '')]


def test_prompt_lists_words_passages_and_registry():
    prompt = build_census_prompt([Candidate('Atreus', 135, ['a'], ['a: the son of Atreus'])],
                                 [{'id': 'agamemnon', 'name': 'Agamemnon'}])
    assert 'Atreus (135 mentions)' in prompt and 'a: the son of Atreus' in prompt
    assert 'agamemnon — Agamemnon' in prompt
    assert 'Judge from the passages only' in prompt
    assert "`pronouns`, he, she, they or it as the passages use them" in prompt


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


# ---------------------------------------------------------------------------
# Review of #591
# ---------------------------------------------------------------------------

def test_non_ascii_and_inner_capital_names_count():
    found = {c.word for c in count_names(
        {'s': 'Then came Hæreth with Zoë and Élise, and McTavish, and old Hæreth again; '
              'and McTavish laughed. THE END came.'}, known=set())}
    assert {'Hæreth', 'Zoë', 'Élise', 'McTavish'} <= found
    assert 'Tavish' not in found and 'THE' not in found and 'END' not in found


def test_a_location_hides_only_its_head_noun(tmp_path):
    from storyforge.extract_census import _registry_words
    with open(tmp_path / 'locations.csv', 'w') as f:
        f.write("id|name\nlaertes-farm|Laertes' Farm\nhouse-of-hades|House of Hades\n"
                "nestors-palace|Nestor's Palace\n")
    words = _registry_words(str(tmp_path))
    assert {'farm', 'house', 'palace'} <= words
    assert not {'laertes', 'hades', 'nestor', 'nestors'} & words


def test_the_threshold_rises_for_a_long_book():
    from storyforge.extract_census import threshold
    cands = [Candidate(f'W{i}', 2, ['s']) for i in range(500)] + \
            [Candidate(f'X{i}', 3, ['s']) for i in range(100)]
    assert threshold(cands, 2, 300) == 3
    assert threshold(cands[:10], 2, 300) == 2


def _setup(project_dir):
    scenes = os.path.join(project_dir, 'scenes')
    first = sorted(f for f in os.listdir(scenes) if f.endswith('.md'))[0]
    with open(os.path.join(scenes, first), 'a') as f:
        f.write('\n\nShe thought of old Quillon, and of Quillon\'s debts, and of the Graces '
                'and the Graces again.\n')


def _fake(answers, calls):
    def fake(prompt, model, log_file, max_tokens=4096, **kw):
        calls.append(prompt)
        reply = {'content': [{'type': 'text', 'text': _reply(answers)}],
                 'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 1}}
        with open(log_file, 'w') as f:
            json.dump(reply, f)
        return reply
    return fake


ANSWERS = [{'word': 'Quillon', 'person': True, 'id': 'quillon', 'name': 'Quillon', 'aliases': []},
           {'word': 'Graces', 'person': True, 'id': 'graces', 'name': 'Graces', 'aliases': []}]


def test_a_rerun_asks_nothing_again_and_keeps_deleted_rows_deleted(project_dir, monkeypatch):
    _setup(project_dir)
    calls = []
    monkeypatch.setattr(api, 'invoke_to_file', _fake(ANSWERS, calls))
    logs = os.path.join(project_dir, 'working', 'logs')
    first = run_census(project_dir, 'm', logs)
    assert {r['id'] for r in first.added} == {'quillon', 'graces'}
    # The author deletes "graces"
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    with open(path) as f:
        lines = [l for l in f if not l.startswith('graces|')]
    with open(path, 'w') as f:
        f.writelines(lines)
    calls.clear()
    second = run_census(project_dir, 'm', logs)
    assert second.added == [] and second.remembered >= 1
    assert all('Graces' not in p and 'Quillon' not in p for p in calls)
    with open(path) as f:
        assert 'graces|' not in f.read()


def test_a_failed_batch_adds_nothing_and_is_asked_again(project_dir, monkeypatch):
    _setup(project_dir)

    def boom(*a, **k):
        raise RuntimeError('API down')
    monkeypatch.setattr(api, 'invoke_to_file', boom)
    logs = os.path.join(project_dir, 'working', 'logs')
    result = run_census(project_dir, 'm', logs)
    assert result.added == [] and 'Quillon' in result.failed
    with open(os.path.join(project_dir, 'working', 'census.csv')) as f:
        assert 'Quillon|2|1|not checked' in f.read()
    calls = []
    monkeypatch.setattr(api, 'invoke_to_file', _fake(ANSWERS, calls))
    assert {r['id'] for r in run_census(project_dir, 'm', logs).added} == {'quillon', 'graces'}


class TestCommand:
    def _patch(self, project_dir, monkeypatch, calls):
        from storyforge import cmd_extract, ledger
        os.makedirs(os.path.join(project_dir, 'working', 'logs'), exist_ok=True)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test')
        monkeypatch.setattr(cmd_extract, 'detect_project_root', lambda: project_dir)
        monkeypatch.setattr(ledger, 'exit_if_not_migrated', lambda d: None)
        for name in ('create_branch', 'ensure_branch_pushed', 'create_draft_pr',
                     'print_summary', 'build_shared_context', 'update_pr_task',
                     'run_review_phase', '_cleanup_intermediates'):
            monkeypatch.setattr(cmd_extract, name, lambda *a, **k: None)
        commits = []
        monkeypatch.setattr(cmd_extract, 'commit_and_push',
                            lambda d, msg, paths: commits.append(msg))
        monkeypatch.setattr(cmd_extract, '_log_api_usage', lambda *a: None)
        monkeypatch.setattr(api, 'invoke_to_file', _fake(ANSWERS, calls))
        return cmd_extract, commits

    def test_extract_census_adds_and_commits(self, project_dir, monkeypatch):
        _setup(project_dir)
        calls = []
        cmd_extract, commits = self._patch(project_dir, monkeypatch, calls)
        monkeypatch.setattr(cmd_extract, '_run_phase_0',
                            lambda *a, **k: pytest.fail('--census ran phase 0'))
        cmd_extract.main(['--census'])
        assert commits == ['Extract: census of named people (characters.csv)']
        with open(os.path.join(project_dir, 'reference', 'characters.csv')) as f:
            assert 'quillon|' in f.read()

    def test_dry_run_sends_nothing(self, project_dir, monkeypatch):
        calls = []
        cmd_extract, commits = self._patch(project_dir, monkeypatch, calls)
        cmd_extract.main(['--census', '--dry-run'])
        assert calls == [] and commits == []

    def test_casts_only_refuses_census(self):
        from storyforge.cmd_extract import parse_args
        with pytest.raises(SystemExit):
            parse_args(['--phase', '2', '--casts-only', '--census'])

    def test_phase_2_runs_the_census_after_its_registry_pass(self, project_dir, monkeypatch):
        calls = []
        cmd_extract, commits = self._patch(project_dir, monkeypatch, calls)
        order = []
        monkeypatch.setattr(cmd_extract, '_run_phase_2', lambda *a, **k: order.append('phase2'))
        monkeypatch.setattr(cmd_extract, '_run_hone',
                            lambda *a, **k: order.append(f'hone{k.get("phase")}'))
        monkeypatch.setattr(cmd_extract, '_run_census', lambda *a: order.append('census'))
        cmd_extract.main(['--phase', '2'])
        assert order == ['phase2', 'hone2', 'census']
        assert 'Extract: census of named people (characters.csv)' in commits
