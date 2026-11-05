"""The briefs stage registers its new fact and state ids in the ledger.

The briefs prompt has the model coin knowledge and physical-state ids, but
the stage wrote only scene-briefs.csv: validate counted "0 facts across 42
scenes" on Gawain (G-023) and the knowledge chain scored 0 on Beowulf
(B-020). The stage now runs hone's reconciliation for both domains (#547),
and keeps its own rows in step with the briefs: a re-run's dropped facts
and facts only cut scenes name leave the ledger (#568 review). These run
the real reconciliation, with the model mocked per prompt."""

import os
import re

import pytest

from storyforge import ledger
from storyforge.cmd_elaborate import main

HEADER = ('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|'
          'key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|'
          'physical_state_in|physical_state_out')


def _briefs(*rows):
    return '```briefs-csv\n' + HEADER + '\n' + ''.join(r + '\n' for r in rows) + '```\n'


def _row(sid, kout='', psout=''):
    return (f'{sid}|Learn the truth|The archivist lies|yes-but|Trust or not|Trusts|'
            f'|{kout}|Asks;Listens|"Ask me again"|fear;hope||||false||{psout}')


def _hone_reply(prompt):
    """Declare every numbered reference a NEW fact or state, its id the text."""
    refs = re.findall(r'^(\d+)\. (\S+)', prompt, re.M)
    if 'NEW | id | character | description' in prompt:
        return ''.join(f'{n} | NEW | {t} | Kael Maren | {t} | injury | false\n'
                       for n, t in refs)
    return ''.join(f'{n} | NEW | {t} | {t.replace("-", " ")} | secret\n' for n, t in refs)


@pytest.fixture
def novel(project_dir, monkeypatch, mock_git, mock_costs):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root', lambda: project_dir)
    monkeypatch.setattr('storyforge.cmd_elaborate.select_model', lambda tier: 'test-model')
    return project_dir


def _run(mock_api, reply, stage='briefs'):
    mock_api.set_response_fn(lambda prompt: _hone_reply(prompt)
                             if 'match no registry id' in prompt else reply)
    try:
        main(['--stage', stage])
    except SystemExit:
        pass


def _rows(proj):
    return {r['id']: r for r in ledger.load_from(os.path.join(proj, 'reference'))}


def _set_status(proj, sid, status):
    path = os.path.join(proj, 'reference', 'scenes.csv')
    lines = open(path).read().splitlines()
    i = lines[0].split('|').index('status')
    out = [lines[0]]
    for line in lines[1:]:
        cells = line.split('|')
        if cells[0] == sid:
            cells[i] = status
        out.append('|'.join(cells))
    open(path, 'w').write('\n'.join(out) + '\n')


def test_the_new_ids_land_in_the_ledger_as_planned_rows(novel, mock_api):
    _run(mock_api, _briefs(_row('new-x1', 'archivist-knows-village', 'torn-sleeve-kael')))
    rows = _rows(novel)
    fact, state = rows['archivist-knows-village'], rows['torn-sleeve-kael']
    assert (fact['type'], fact['scene_id'], fact['status']) == ('knowledge', 'new-x1', 'binding')
    assert (state['type'], state['scene_id']) == ('physical', 'new-x1')
    for row in (fact, state):
        assert (row['introduced_by'], row['origin']) == ('briefs', 'plan')
        assert not ledger.is_commitment(row)   # the gate reads it as plan
    # rows other writers made are untouched
    assert rows['map-anomaly-exists']['introduced_by'] == 'migration'


def test_a_rerun_replaces_its_own_earlier_rows(novel, mock_api):
    _run(mock_api, _briefs(_row('new-x1', 'archivist-knows-village')))
    assert 'archivist-knows-village' in _rows(novel)
    _run(mock_api, _briefs(_row('new-x1', 'archivist-fears-council')))
    rows = _rows(novel)
    assert 'archivist-fears-council' in rows
    assert 'archivist-knows-village' not in rows


def test_a_fact_only_a_cut_scene_names_leaves_the_ledger(novel, mock_api):
    _run(mock_api, _briefs(_row('new-x1', 'archivist-knows-village'),
                           _row('act2-sc01', 'reaches-are-unmapped')))
    assert {'archivist-knows-village', 'reaches-are-unmapped'} <= set(_rows(novel))
    _set_status(novel, 'new-x1', 'cut')
    _run(mock_api, _briefs(_row('act2-sc01', 'reaches-are-unmapped')))
    rows = _rows(novel)
    assert 'archivist-knows-village' not in rows
    assert rows['reaches-are-unmapped']['scene_id'] == 'act2-sc01'


def test_ids_left_unregistered_are_reported(novel, mock_api, capsys):
    mock_api.set_response_fn(lambda prompt: '' if 'match no registry id' in prompt
                             else _briefs(_row('new-x1', 'archivist-knows-village')))
    try:
        main(['--stage', 'briefs'])
    except SystemExit:
        pass
    out = capsys.readouterr()
    assert ("the briefs' knowledge ids are not all in the ledger; run storyforge hone "
            "--domain knowledge,physical-states") in out.out + out.err


def test_the_architecture_stage_does_not_touch_the_ledger(novel, mock_api):
    before = _rows(novel)
    _run(mock_api, _briefs(_row('new-x1', 'x')).replace('briefs-csv', 'intent-csv'),
         stage='architecture')
    assert _rows(novel) == before
