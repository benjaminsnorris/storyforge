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
    assert (fact['type'], fact['scene_id'], fact['status']) == ('knowledge', 'new-x1', 'planned')
    assert (state['type'], state['scene_id']) == ('physical', 'new-x1')
    for row in (fact, state):
        assert (row['introduced_by'], row['origin']) == ('briefs', 'plan')
        assert row['status'] == 'planned'
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


def test_a_rerun_moves_a_fact_to_the_scene_that_now_sets_it_up(novel, mock_api):
    _run(mock_api, _briefs(_row('new-x1', 'archivist-knows-village')))
    assert _rows(novel)['archivist-knows-village']['scene_id'] == 'new-x1'
    _run(mock_api, _briefs(_row('new-x1', 'archivist-fears-council'),
                           _row('act2-sc01', 'archivist-knows-village')))
    assert _rows(novel)['archivist-knows-village']['scene_id'] == 'act2-sc01'


def test_a_row_the_author_edited_is_left_alone(novel, mock_api):
    _run(mock_api, _briefs(_row('new-x1', 'archivist-knows-village')))
    ref = os.path.join(novel, 'reference')
    rows = ledger.load_from(ref)
    for r in rows:
        if r['id'] == 'archivist-knows-village':
            r['statement'] = 'The archivist knows where the village went'
    ledger.save_to(ref, rows, command='test')
    _run(mock_api, _briefs(_row('new-x1', 'archivist-fears-council')))
    rows = _rows(novel)
    assert rows['archivist-knows-village']['statement'] == \
        'The archivist knows where the village went'
    assert 'archivist-fears-council' in rows


def test_the_gate_makes_a_planned_fact_binding_when_the_prose_establishes_it():
    rows = [dict({c: '' for c in ledger.COLUMNS}, id='f', type='knowledge',
                 statement='The archivist knows', status='planned', origin='plan',
                 mutable='state', introduced_by='briefs')]
    assert ledger.fill_quote(rows, 'f', 'the archivist knew where it went')
    assert rows[0]['status'] == 'binding'
    assert rows[0]['quote'] == 'the archivist knew where it went'


def test_a_rerun_keeps_the_authors_must_beats(novel, mock_api, capsys):
    """#642: regenerating a brief never drops or rewords a `must` beat."""
    from storyforge.elaborate import _read_csv_as_map
    _run(mock_api, _briefs(_row('new-x1', 'archivist-knows-village')))
    from storyforge.enrich import update_csv_field
    path = os.path.join(novel, 'reference', 'scene-briefs.csv')
    update_csv_field(path, 'new-x1', 'key_actions', 'Asks;must: Kael burns the ledger')
    update_csv_field(path, 'new-x1', 'key_dialogue', 'must: Kael: "Ask me again"')
    _run(mock_api, _briefs(_row('new-x1', 'archivist-knows-village')))
    row = _read_csv_as_map(path)['new-x1']
    assert row['key_actions'] == 'Asks; must: Kael burns the ledger; Listens'
    # #644: the reply's own key_dialogue is never written; the author's stays whole
    assert row['key_dialogue'] == 'must: Kael: "Ask me again"'
    assert 'put back the author\'s must item(s)' in capsys.readouterr().out
