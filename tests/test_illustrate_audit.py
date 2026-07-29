"""Tests for `storyforge illustrate --audit` — the contradiction pass (#278).

Two guarantees matter more than the rest and are asserted first: the audit never
edits the prose or the log, and it makes no LLM call when the pre-pass has
nothing for a model to look at.
"""

import json
import os

import pytest

from storyforge import cmd_illustrate
from storyforge import illustrations as ill
from storyforge import prompts_illustrate as pi
from storyforge import visual_state as vs

STATE_PATH = os.path.join('reference', 'visual-state.csv')
REPORT = os.path.join('working', 'illustration-contradictions.md')
PROVENANCE = os.path.join('working', 'illustration-audit-provenance.csv')


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Keep every test off the API path unless it opts in."""
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('STORYFORGE_COACHING', raising=False)


@pytest.fixture
def in_project(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    return project_dir


def _write_state(project_dir, rows):
    with open(os.path.join(project_dir, STATE_PATH), 'w',
              encoding='utf-8') as f:
        f.write('|'.join(vs.STATE_COLUMNS) + '\n')
        for row in rows:
            f.write('|'.join(row) + '\n')


def _read(project_dir, rel):
    with open(os.path.join(project_dir, rel), encoding='utf-8') as f:
        return f.read()


def _snapshot(project_dir):
    """Bytes of the log and every scene file."""
    snap = {}
    state = os.path.join(project_dir, STATE_PATH)
    if os.path.isfile(state):
        snap[STATE_PATH] = open(state, 'rb').read()
    scenes = os.path.join(project_dir, 'scenes')
    for name in sorted(os.listdir(scenes)):
        snap[f'scenes/{name}'] = open(os.path.join(scenes, name), 'rb').read()
    return snap


_ONE_CONTRADICTION = json.dumps({'contradictions': [{
    'scene_id': 'act1-sc02',
    'entity': 'dorren-clothing',
    'quote': 'Dorren sat at her desk',
    'log_says': 'office dress, brass calipers in hand',
    'prose_says': 'she is described in the travel coat she does not put on '
                  'until act2-sc01',
    'resolution': 'the log is missing a transition at act1-sc02',
}]})


# ============================================================================
# Cost discipline
# ============================================================================

def test_audit_makes_no_api_call_when_there_is_no_log(in_project, monkeypatch):
    """With no transitions there is nothing for the prose to contradict."""
    os.remove(os.path.join(in_project, STATE_PATH))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*a, **k):
        raise AssertionError('no log means no call')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)

    assert cmd_illustrate.main(['--audit']) == 0
    body = _read(in_project, REPORT)
    assert 'no visual-state log yet' in body
    assert 'No contradiction pass was run' in body


def test_audit_makes_no_api_call_when_the_prepass_is_empty(in_project, monkeypatch):
    """A clean log whose entity the prose never names: no findings, no
    candidates, nothing a model could add."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    _write_state(in_project, [
        ('nothing-in-the-prose', 'act1-sc01', 'x', 'held her breath'),
    ])

    def _boom(*a, **k):
        raise AssertionError('no candidates means no call')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)

    assert cmd_illustrate.main(['--audit']) == 0
    body = _read(in_project, REPORT)
    assert 'No model was called' in body
    assert 'no' in body.lower()


def test_a_skipped_pass_does_not_claim_contradictions_were_assessed(in_project, monkeypatch):
    os.remove(os.path.join(in_project, STATE_PATH))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    cmd_illustrate.main(['--audit'])
    body = _read(in_project, REPORT)
    assert 'Not assessed' in body
    assert 'None found' not in body


def test_no_provenance_is_written_when_nothing_was_read(in_project, monkeypatch):
    """Recording a scene the pass never read would make the next run report it
    as audited."""
    os.remove(os.path.join(in_project, STATE_PATH))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    assert cmd_illustrate.main(['--audit']) == 0
    assert not os.path.isfile(os.path.join(in_project, PROVENANCE))


# ============================================================================
# Read-only
# ============================================================================

def test_audit_never_edits_the_log_or_the_prose(in_project, monkeypatch):
    """The important test. An audit that edits prose is a far worse bug than one
    that misses a contradiction."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: _ONE_CONTRADICTION)
    before = _snapshot(in_project)
    assert cmd_illustrate.main(['--audit']) == 0
    assert _snapshot(in_project) == before


def test_audit_dry_run_writes_nothing_at_all(in_project, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*a, **k):
        raise AssertionError('--dry-run must not call the API')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)
    assert cmd_illustrate.main(['--audit', '--dry-run']) == 0
    assert '[dry-run]' in capsys.readouterr().out
    assert not os.path.isfile(os.path.join(in_project, REPORT))
    assert not os.path.isfile(os.path.join(in_project, PROVENANCE))


# ============================================================================
# The load-bearing case
# ============================================================================

def test_audit_reports_a_prose_assertion_that_contradicts_the_log(in_project, monkeypatch):
    """Two transitions do not disagree with each other; a scene between them
    asserts a state the span cannot support."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    # Neither row disagrees with the other — a change of clothes between act 1
    # and act 2 is a story. act1-sc02 sits between them and names Dorren, so it
    # is the one scene that could assert a state the span cannot support.
    _write_state(in_project, [
        ('dorren-clothing', 'act1-sc01', 'office dress, brass calipers in hand',
         'held her breath'),
        ('dorren-clothing', 'act2-sc01', 'travel coat, boots',
         'She checked her compass'),
    ])
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: _ONE_CONTRADICTION)
    assert cmd_illustrate.main(['--audit']) == 0
    body = _read(in_project, REPORT)
    assert 'act1-sc02' in body
    assert 'dorren-clothing' in body
    assert 'Dorren sat at her desk' in body
    assert 'the log is missing a transition' in body
    # The pre-pass found nothing wrong with the log itself — the contradiction
    # is only visible by reading the prose against it.
    assert 'None. The log resolves cleanly' in body


def test_the_report_explains_why_the_llm_pass_is_necessary(in_project, monkeypatch):
    """An author reading a clean report must understand what it can see."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '{"contradictions": []}')
    cmd_illustrate.main(['--audit'])
    body = _read(in_project, REPORT)
    assert 'never disagree with each other' in body
    assert 'because things are allowed to change' in body
    assert 'a scene *between* them' in body


def test_an_empty_contradictions_list_is_a_clean_pass_not_a_failure(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '{"contradictions": []}')
    assert cmd_illustrate.main(['--audit']) == 0
    body = _read(in_project, REPORT)
    assert 'None found' in body
    assert 'No contradiction pass was run' not in body


def test_deterministic_findings_reach_the_report(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    _write_state(in_project, [('lamp', 'scene-that-was-cut', 'dark', '')])
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '{"contradictions": []}')
    assert cmd_illustrate.main(['--audit']) == 0
    body = _read(in_project, REPORT)
    assert 'state_unknown_scene' in body


# ============================================================================
# Provenance
# ============================================================================

def test_audit_records_a_digest_per_scene_it_read(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '{"contradictions": []}')
    assert cmd_illustrate.main(['--audit']) == 0
    rows = vs.read_provenance(in_project)
    assert rows, 'the fixture log yields at least one candidate scene'
    for row in rows:
        assert row['digest'] == ill.scene_prose_digest(in_project,
                                                       row['scene_id'])
        assert row['audited_at']
    # One row per scene read, no more.
    report = _read(in_project, REPORT)
    for row in rows:
        assert f'`{row["scene_id"]}`' in report


def test_provenance_is_lf_only(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '{"contradictions": []}')
    cmd_illustrate.main(['--audit'])
    with open(os.path.join(in_project, PROVENANCE), 'rb') as f:
        assert b'\r' not in f.read()


def test_a_whitespace_only_edit_does_not_read_as_staleness(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '{"contradictions": []}')
    cmd_illustrate.main(['--audit'])
    scene = os.path.join(in_project, 'scenes', 'act1-sc02.md')
    with open(scene, encoding='utf-8') as f:
        text = f.read()
    with open(scene, 'w', encoding='utf-8') as f:
        f.write(text.replace('\n\n', '\n\n\n') + '   \n')
    kinds = {f['kind'] for f in vs.digest_drift(in_project)}
    assert 'audit_stale' not in kinds


def test_a_real_revision_reads_as_staleness(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '{"contradictions": []}')
    cmd_illustrate.main(['--audit'])
    audited = vs.read_provenance(in_project)[0]['scene_id']
    scene = os.path.join(in_project, 'scenes', f'{audited}.md')
    with open(scene, 'a', encoding='utf-8') as f:
        f.write('\nA sentence that was not there when the audit ran.\n')
    findings = [f for f in vs.digest_drift(in_project)
                if f['kind'] == 'audit_stale']
    assert len(findings) == 1
    assert findings[0]['scene_id'] == audited


def test_embedding_a_marker_does_not_read_as_staleness(in_project, monkeypatch):
    """A marker is not prose, so embedding one must not invalidate an audit."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '{"contradictions": []}')
    cmd_illustrate.main(['--audit'])
    audited = vs.read_provenance(in_project)[0]['scene_id']
    scene = os.path.join(in_project, 'scenes', f'{audited}.md')
    with open(scene, 'a', encoding='utf-8') as f:
        f.write('\n' + ill.marker_for('lantern-vigil') + '\n')
    kinds = {f['kind'] for f in vs.digest_drift(in_project)}
    assert 'audit_stale' not in kinds


def test_a_provenance_row_for_a_deleted_scene_is_logged_not_flagged(
        in_project, monkeypatch, capsys):
    vs.write_provenance(in_project, [
        {'scene_id': 'gone', 'digest': 'abc', 'audited_at': '2026-07-28'},
    ])
    kinds = {f['kind'] for f in vs.digest_drift(in_project)}
    assert 'audit_stale' not in kinds
    assert 'has no file in scenes/' in capsys.readouterr().out


def test_a_provenance_row_with_no_scene_id_is_skipped_loudly(in_project, capsys):
    path = os.path.join(in_project, PROVENANCE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('scene_id|digest|audited_at\n|abc|2026-07-28\n')
    assert vs.read_provenance(in_project) == []
    assert 'no scene_id' in capsys.readouterr().out


def test_read_provenance_missing_file_is_empty(in_project):
    assert vs.read_provenance(in_project) == []


# ============================================================================
# prose_changed — an illustration rendered from prose that has since moved
# ============================================================================

def test_ingest_records_the_scene_digest(in_project):
    from illustration_helpers import make_png, plan_row
    row = plan_row(scene_id='act1-sc01', placement='scene_open', anchor='')
    ill.write_plan(in_project, [row])
    src = make_png(os.path.join(in_project, 'lantern-vigil.png'), 40, 60)
    assert cmd_illustrate.run_ingest(in_project, src, dry_run=False) == 0
    stored = ill.read_plan_as_map(in_project)['lantern-vigil']['scene_digest']
    assert stored == ill.scene_prose_digest(in_project, 'act1-sc01')


def test_prose_revised_under_a_render_is_reported(in_project):
    from illustration_helpers import make_png, plan_row
    row = plan_row(scene_id='act1-sc01', placement='scene_open', anchor='')
    ill.write_plan(in_project, [row])
    src = make_png(os.path.join(in_project, 'lantern-vigil.png'), 40, 60)
    cmd_illustrate.run_ingest(in_project, src, dry_run=False)

    scene = os.path.join(in_project, 'scenes', 'act1-sc01.md')
    with open(scene, 'a', encoding='utf-8') as f:
        f.write('\nA paragraph added after the art was made.\n')

    findings = [f for f in vs.digest_drift(in_project)
                if f['kind'] == 'prose_changed']
    assert len(findings) == 1
    assert findings[0]['id'] == 'lantern-vigil'
    assert ill.severity_of('prose_changed') == 'warning'


def test_a_row_with_no_recorded_digest_is_not_reported(in_project):
    """Every row on a plan that predates the column is in this state."""
    from illustration_helpers import plan_row
    ill.write_plan(in_project, [plan_row(scene_id='act1-sc01',
                                         status='ingested', scene_digest='')])
    kinds = {f['kind'] for f in vs.digest_drift(in_project)}
    assert 'prose_changed' not in kinds


# ============================================================================
# Parsing
# ============================================================================

def test_parse_audit_response_distinguishes_empty_from_unparseable():
    assert pi.parse_audit_response('{"contradictions": []}')[1] == 'empty'
    assert pi.parse_audit_response('not json')[1] == 'no_json'
    assert pi.parse_audit_response('{"other": 1}')[1] == 'no_json'
    assert pi.parse_audit_response('[1,2]')[1] == 'no_json'


def test_parse_audit_response_drops_rows_with_no_quote():
    rows, status = pi.parse_audit_response(json.dumps({'contradictions': [
        {'scene_id': 's1', 'entity': 'e', 'quote': 'q'},
        {'scene_id': 's1', 'entity': 'e'},
        'a string',
    ]}))
    assert status == 'ok'
    assert len(rows) == 1


def test_an_unparseable_audit_response_writes_no_report(in_project, monkeypatch, capsys):
    """An empty report would read as a clean audit."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: 'garbage')
    assert cmd_illustrate.main(['--audit']) == 1
    assert not os.path.isfile(os.path.join(in_project, REPORT))
    assert 'would read as a clean audit' in capsys.readouterr().out


def test_an_empty_api_response_writes_no_report(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: '')
    assert cmd_illustrate.main(['--audit']) == 1
    assert not os.path.isfile(os.path.join(in_project, REPORT))


def test_audit_without_a_key_is_an_error(in_project, capsys):
    assert cmd_illustrate.main(['--audit']) == 1
    assert 'ANTHROPIC_API_KEY is not set' in capsys.readouterr().out


def test_the_prompt_hands_over_the_resolved_walk_not_the_raw_log(in_project, monkeypatch):
    """The model must not re-derive resolution — it gets the `<=` boundary wrong."""
    captured = {}
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _capture(project_dir, prompt, operation, **kwargs):
        captured['prompt'] = prompt
        return '{"contradictions": []}'
    monkeypatch.setattr(cmd_illustrate, '_invoke', _capture)
    cmd_illustrate.main(['--audit'])
    assert 'State in effect at each scene you are reading' in captured['prompt']
    assert 'do not re-derive them' in captured['prompt']


def test_audit_uses_an_analytical_model_not_a_creative_one(in_project, monkeypatch):
    captured = {}
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _capture(project_dir, prompt, operation, *, task_type, **kwargs):
        captured['task_type'] = task_type
        return '{"contradictions": []}'
    monkeypatch.setattr(cmd_illustrate, '_invoke', _capture)
    cmd_illustrate.main(['--audit'])
    assert captured['task_type'] == 'evaluator'


def test_audit_skips_a_candidate_whose_file_disappeared(in_project, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*a, **k):
        raise AssertionError('nothing readable means no call')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)
    monkeypatch.setattr(cmd_illustrate.vs, 'prepass', lambda _p: {
        'findings': [], 'candidate_scenes': ['vanished'], 'scene_count': 3,
        'tracked_entities': ['x'], 'undrafted_scenes': [],
    })
    monkeypatch.setattr(cmd_illustrate.vs, 'read_transitions', lambda _p: [
        {'entity': 'x', 'from_scene': 'act1-sc01', 'state': 'y',
         'evidence': 'z'},
    ])
    assert cmd_illustrate.main(['--audit']) == 0
    assert 'no prose to read' in _read(in_project, REPORT)
    assert 'not read' in capsys.readouterr().out


# ============================================================================
# Renderer edges
# ============================================================================

def test_render_state_matrix_says_so_when_empty():
    assert 'No transitions recorded' in pi.render_state_matrix([])


def test_the_report_names_scenes_it_could_not_read():
    body = pi.render_audit_report(
        title='T', transitions=[], findings=[], contradictions=[],
        scenes_read=[], scene_count=4, tracked_entities=[],
        undrafted_scenes=['act9-sc01'], llm_skipped_reason='because')
    assert 'act9-sc01' in body
    assert 'no file in `scenes/`' in body


def test_the_report_renders_a_contradiction_with_fields_missing():
    body = pi.render_audit_report(
        title='T', transitions=[], findings=[],
        contradictions=[{'scene_id': 's1', 'entity': 'e', 'quote': 'q'}],
        scenes_read=['s1'], scene_count=1, tracked_entities=['e'],
        undrafted_scenes=[], llm_skipped_reason='')
    assert '(not stated)' in body
    assert '(none proposed)' in body


def test_the_audit_prompt_handles_a_scene_with_nothing_established():
    prompt = pi.build_audit_request(
        story_context='', transitions=[], resolved_by_scene=[('s1', {})],
        scene_prose='')
    assert 'nothing tracked is established yet' in prompt


def test_the_audit_prompt_handles_no_candidates():
    prompt = pi.build_audit_request(
        story_context='', transitions=[], resolved_by_scene=[],
        scene_prose='')
    assert '(no candidate scenes)' in prompt


def test_an_ingested_row_whose_scene_vanished_is_not_reported_as_drift(in_project):
    """No prose to compare against is not the same as prose that moved."""
    from illustration_helpers import plan_row
    ill.write_plan(in_project, [plan_row(scene_id='gone', status='ingested',
                                         scene_digest='abc123')])
    kinds = {f['kind'] for f in vs.digest_drift(in_project)}
    assert 'prose_changed' not in kinds


def test_the_audit_log_names_the_scenes_it_could_not_read(in_project, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '{"contradictions": []}')
    os.remove(os.path.join(in_project, 'scenes', 'act2-sc01.md'))
    cmd_illustrate.main(['--audit'])
    out = capsys.readouterr().out
    assert 'scene(s) have no file in scenes/ and were not read: act2-sc01' in out


# ============================================================================
# --diagnose reports the state and audit rungs
# ============================================================================

def test_diagnose_reports_no_state_log(in_project, capsys):
    os.remove(os.path.join(in_project, STATE_PATH))
    assert cmd_illustrate.main(['--diagnose']) == 0
    out = capsys.readouterr().out
    assert 'no transition log' in out
    assert '--state' in out


def test_diagnose_reports_the_state_rung_with_no_plan(in_project, capsys):
    """The log is about the book, not the illustrations — worth building first."""
    assert not ill.read_plan(in_project)
    assert cmd_illustrate.main(['--diagnose']) == 0
    out = capsys.readouterr().out
    assert 'No illustration plan yet' in out
    assert 'dorren-clothing' in out


def test_diagnose_counts_entities_and_transitions(in_project, capsys):
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert '2 transition(s) across 2 entity(ies)' in out


def test_diagnose_reports_an_unrun_audit(in_project, capsys):
    cmd_illustrate.main(['--diagnose'])
    assert 'audit: never run' in capsys.readouterr().out


def test_diagnose_reports_a_current_audit(in_project, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '{"contradictions": []}')
    cmd_illustrate.main(['--audit'])
    capsys.readouterr()
    monkeypatch.delenv('ANTHROPIC_API_KEY')
    cmd_illustrate.main(['--diagnose'])
    assert 'audit: current' in capsys.readouterr().out


def test_diagnose_reports_a_stale_audit(in_project, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '{"contradictions": []}')
    cmd_illustrate.main(['--audit'])
    audited = vs.read_provenance(in_project)[0]['scene_id']
    with open(os.path.join(in_project, 'scenes', f'{audited}.md'), 'a',
              encoding='utf-8') as f:
        f.write('\nRevised after the audit ran.\n')
    capsys.readouterr()
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'audit: stale' in out
    assert audited in out


def test_diagnose_reports_the_state_rung_alongside_a_plan(in_project, capsys):
    from illustration_helpers import plan_row
    ill.write_plan(in_project, [plan_row(scene_id='act1-sc01',
                                         placement='scene_open', anchor='')])
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'Illustration plan: 1 rows' in out
    assert 'Visual state:' in out
