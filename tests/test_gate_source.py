"""The gate's source check (#557, B-031, B-027): in a faithful adaptation the
source, not the first telling, decides a contradiction between scenes, and
a fact the source contradicts isn't committed. The API is mocked as in
tests/test_gate.py; the source call is the one whose schema asks for
`contradictions`."""

import json
from unittest.mock import patch

import pytest

from storyforge import gate, gate_source, ledger

from test_gate import (SCENE, _commitment, _contradiction, _is_persistence,
                        _persistence_reply, _pure_prose_scenes, _text)  # noqa: F401

EARLIER = 'act1-sc01'
SECOND = "The hollow's well ran dry"
SECOND_QUOTE = 'She tapped the empty space on the map'


def _is_source(body):
    schema = (body.get('output_config') or {}).get('format', {}).get('schema', {})
    return 'contradictions' in schema.get('properties', {})


@pytest.fixture
def adaptation(monkeypatch):
    """Every scene mapped to a source scene; the source text is fixed."""
    ctx = gate_source.Setup({SCENE: [('src', 's2')], EARLIER: [('src', 's1')]},
                            'Rule: keep the poem\'s history.', {SCENE: {'treatment': 'adapt'}})
    monkeypatch.setattr(gate_source, 'setup', lambda project_dir: ctx)
    monkeypatch.setattr(gate_source, '_source_text',
                        lambda project_dir, refs: f'SOURCE {refs[0][1]}')
    monkeypatch.setattr(gate_source, 'has_source_prose', lambda project_dir, refs: True)
    gate_source._MEMO.clear()
    return ctx


def _run(project_dir, tmp_path, commitments, findings=(), source=None, sent=None):
    def fake(path, body, **k):
        if _is_persistence(body):
            return _persistence_reply(body)
        if _is_source(body):
            if sent is not None:
                sent.append(body['messages'][0]['content'])
            if isinstance(source, Exception):
                raise source
            return _text(source or {'facts': [], 'contradictions': []})
        if 'tools' in body:
            return _text({'findings': list(findings), 'kept': []})
        return _text({'commitments': list(commitments)})
    with patch('storyforge.api._api_request', side_effect=fake):
        return gate.gate_scene(project_dir, SCENE, command='draft',
                               log_dir=str(tmp_path / 'logs'), extract_model='m',
                               check_model='m')


def _two():
    return [_commitment(), _commitment(statement=SECOND, quote=SECOND_QUOTE)]


def test_a_fact_the_source_contradicts_is_not_committed(project_dir, tmp_path, adaptation):
    """B-027: facts misread from the prose bound every later scene."""
    sent = []
    result = _run(project_dir, tmp_path, _two(), sent=sent, source={
        'facts': [{'n': 2, 'verdict': 'contradicts', 'why': 'the source: the well is full'},
                  {'n': 1, 'verdict': 'agrees', 'why': 'w'}],
        'contradictions': []})
    assert result.committed
    mine = [r['statement'] for r in ledger.load(project_dir)
            if r['scene_id'] == SCENE and ledger.is_commitment(r)]
    assert mine == ["Tarren's Hollow had 412 people"]
    assert result.source_dropped == [(SECOND, 'the source: the well is full')]
    assert any(line.startswith('NOTE (not recorded: the source contradicts it)')
               for line in gate.report_lines(result))
    assert 'SOURCE s2' in sent[0] and 'keep the poem' in sent[0]


def _earlier_fact(project_dir, quote='Dorren Hayle pressed the brass calipers against the vellum'):
    rows = ledger.load(project_dir)
    base = dict(rows[0], **{k: '' for k in rows[0]})
    base.update(id='early-wrong', scene_id=EARLIER, type='world', subject='tarrens-hollow',
                statement='The Hollow had 300 people', quote=quote, status='binding',
                origin='prose', mutable='fixed', introduced_by='draft')
    ledger.save(project_dir, rows + [base], command='test')


def _backs(project_dir, tmp_path, sent=None):
    return _run(project_dir, tmp_path, _two(), findings=[_contradiction()], sent=sent,
                source={'facts': [], 'contradictions': [
                    {'n': 1, 'backs': 'this', 'why': 'the poem says so'}]})


def test_a_contradiction_the_source_backs_this_scene_on_does_not_block(
        project_dir, tmp_path, adaptation):
    """B-031: the herald told it the poem's way and was the one blocked.
    #557's review: the earlier scene's wrong fact is no longer binding and
    this scene's is committed, so later scenes follow the source."""
    _earlier_fact(project_dir)
    sent = []
    result = _backs(project_dir, tmp_path, sent)
    assert result.passed and result.committed
    assert 'SOURCE s1' in sent[0]   # the earlier scene's source was sent
    rows = {r['id']: r for r in ledger.load(project_dir)}
    assert rows['early-wrong']['status'] == 'superseded'
    mine = sorted(r['statement'] for r in rows.values()
                  if r['scene_id'] == SCENE and ledger.is_commitment(r))
    assert mine == sorted([SECOND, "Tarren's Hollow had 412 people"])
    assert result.source_superseded == ['early-wrong']
    row = gate.pending(project_dir)[EARLIER]
    assert row['command'] == gate.SOURCE_FIX and SCENE in row['reason']
    lines = gate.report_lines(result)
    assert any(line.startswith('SOURCE BACKS THIS SCENE') for line in lines)
    assert any('no longer binding' in line and 'early-wrong' in line for line in lines)
    assert gate.problems_to_fix(result) == []


def test_with_no_earlier_fact_found_its_commitments_are_held_back(
        project_dir, tmp_path, adaptation):
    result = _backs(project_dir, tmp_path)
    assert result.passed and result.source_unmatched
    mine = [r['statement'] for r in ledger.load(project_dir)
            if r['scene_id'] == SCENE and ledger.is_commitment(r)]
    assert mine == [SECOND]


def test_the_source_fix_row_stays_until_the_earlier_prose_changes(
        project_dir, tmp_path, adaptation, monkeypatch):
    import os
    _earlier_fact(project_dir)
    _backs(project_dir, tmp_path)
    assert gate.source_fix_waits(project_dir, EARLIER)
    # a pass of the unchanged earlier scene doesn't clear it
    from storyforge import cmd_check
    monkeypatch.setattr(cmd_check, 'detect_project_root', lambda: project_dir)
    monkeypatch.setattr('storyforge.git.create_branch', lambda *a: 'b')
    monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **k: True)
    cmd_check.main(['--pending'])   # nothing else waits: it is skipped, said
    assert gate.pending(project_dir)[EARLIER]['command'] == gate.SOURCE_FIX
    path = os.path.join(project_dir, 'scenes', f'{EARLIER}.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace('Dorren', 'Dorren', 1) + '\n\nA new line toward the source.\n')
    assert not gate.source_fix_waits(project_dir, EARLIER)


def test_a_scene_already_waiting_gets_the_source_fix_added(project_dir, adaptation):
    gate.mark_pending(project_dir, EARLIER, 'draft', '2 problem(s)')
    gate.mark_source_fix(project_dir, EARLIER, 'the source tells it otherwise')
    row = gate.pending(project_dir)[EARLIER]
    assert row['command'] == 'draft'
    assert '2 problem(s)' in row['reason'] and 'the source tells it otherwise' in row['reason']


def test_a_dropped_fact_lists_the_scene_for_the_author(project_dir, tmp_path, adaptation):
    _run(project_dir, tmp_path, _two(), source={
        'facts': [{'n': 2, 'verdict': 'contradicts', 'why': 'w'}], 'contradictions': []})
    row = gate.pending(project_dir)[SCENE]
    assert row['command'] == gate.SOURCE_FIX and 'contradicts 1 fact' in row['reason']


def test_an_unchanged_recheck_makes_no_call_and_a_repeat_reuses_the_ruling(
        project_dir, tmp_path, adaptation):
    sent = []
    _run(project_dir, tmp_path, _two(), sent=sent)
    assert len(sent) == 1
    # the same facts again: none is new to the scene, nothing to rule on
    gate.clear_pending(project_dir, SCENE)
    _run(project_dir, tmp_path, _two(), sent=sent)
    assert len(sent) == 1
    # a fix round with the same facts and contradiction: the memo answers
    gate_source._MEMO.clear()
    _run(project_dir, tmp_path, [_commitment(statement='A new fact', quote=SECOND_QUOTE)],
         findings=[_contradiction()], sent=sent)
    _run(project_dir, tmp_path, [_commitment(statement='A new fact', quote=SECOND_QUOTE)],
         findings=[_contradiction()], sent=sent)
    assert len(sent) == 2


def test_the_write_forecast_counts_the_source_check(project_dir, adaptation):
    from storyforge import cmd_write
    assert cmd_write._source_check_cost(project_dir) == gate_source.COST_PER_SCENE


def test_no_source_prose_is_a_note(project_dir, tmp_path, adaptation, monkeypatch):
    monkeypatch.setattr(gate_source, 'has_source_prose', lambda project_dir, refs: False)
    sent = []
    result = _run(project_dir, tmp_path, _two(), sent=sent)
    assert sent == [] and any('no prose' in n for n in result.source_notes)


def test_a_contradiction_the_source_backs_the_earlier_scene_on_still_blocks(
        project_dir, tmp_path, adaptation):
    result = _run(project_dir, tmp_path, _two(), findings=[_contradiction()], source={
        'facts': [], 'contradictions': [{'n': 1, 'backs': 'earlier', 'why': 'w'}]})
    assert not result.passed and result.source_backed == []
    assert EARLIER not in gate.pending(project_dir)


def test_a_failed_source_call_is_a_note_not_a_stop(project_dir, tmp_path, adaptation):
    result = _run(project_dir, tmp_path, _two(), source=RuntimeError('HTTP 500'))
    assert result.passed and result.committed
    assert any('not checked against the source' in n and 'HTTP 500' in n
               for n in result.source_notes)


def test_a_project_without_a_source_makes_no_call(project_dir, tmp_path):
    sent = []
    result = _run(project_dir, tmp_path, _two(), sent=sent)
    assert result.passed and sent == [] and result.source_notes == []


def test_free_mode_and_unmapped_scenes_say_why(project_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(gate_source, 'setup', lambda p: gate_source.Setup(
        {}, '', {}, skip='source.mode is free: fidelity isn\'t checked'))
    result = _run(project_dir, tmp_path, _two())
    assert result.source_notes == ['not checked against the source: source.mode is free: '
                                   'fidelity isn\'t checked']
    monkeypatch.setattr(gate_source, 'setup', lambda p: gate_source.Setup({}, '', {}))
    result = _run(project_dir, tmp_path, _two())
    assert 'invented or not mapped' in result.source_notes[0]


def test_source_fix_rows_do_not_stop_drafting(project_dir):
    from storyforge import cmd_write
    gate.mark_pending(project_dir, EARLIER, gate.SOURCE_FIX, 'source: later scene')
    assert cmd_write._gate_blockers(project_dir, 'act2-sc01') == []


def test_setup_reads_a_real_adaptation(tmp_path):
    from source_helpers import SNAPSHOT_FILES, _write, import_source, make_adaptation
    project = make_adaptation(tmp_path)
    import_source(project)
    assert gate_source.setup(project).skip == 'reference/source-map.csv is missing or empty'
    _write(project, SNAPSHOT_FILES)
    ctx = gate_source.setup(project)
    assert ctx.skip == ''
    assert ctx.refs == {'olympus-council-meets': [('odyssey', 'gods-debate')],
                        'athena-at-the-door': [('odyssey', 'minerva-visits'),
                                               ('odyssey', 'assembly-called')]}
    text = gate_source._source_text(project, ctx.refs['athena-at-the-door'])
    assert 'Then Pallas Minerva went down.' in text   # the source prose itself
