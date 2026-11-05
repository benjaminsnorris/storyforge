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


def test_a_contradiction_the_source_backs_this_scene_on_does_not_block(
        project_dir, tmp_path, adaptation):
    """B-031: the herald told it the poem's way and was the one blocked."""
    sent = []
    result = _run(project_dir, tmp_path, _two(), findings=[_contradiction()], sent=sent,
                  source={'facts': [], 'contradictions': [
                      {'n': 1, 'backs': 'this', 'why': 'the poem says so'}]})
    assert result.passed and result.committed
    assert 'SOURCE s1' in sent[0]   # the earlier scene's source was sent
    # the commitment stating it is held back; the earlier scene goes to the author
    mine = [r['statement'] for r in ledger.load(project_dir)
            if r['scene_id'] == SCENE and ledger.is_commitment(r)]
    assert mine == [SECOND]
    row = gate.pending(project_dir)[EARLIER]
    assert row['command'] == gate.SOURCE_FIX and SCENE in row['reason']
    assert any(line.startswith('SOURCE BACKS THIS SCENE') for line in gate.report_lines(result))
    assert gate.problems_to_fix(result) == []


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
