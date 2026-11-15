"""Long writing sessions (#655): the writer's context, the lean plan, the
reply, the writer as the gate's fixer, the stage sheets, and the session
loop in `write --session`."""

import json
import os

import pytest

from storyforge import gate, session, voice_book
from storyforge.common import get_plugin_dir

SCENE = 'act1-sc01'


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def _reply(text):
    return {'content': [{'type': 'text', 'text': text}], 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 10, 'output_tokens': 10}}


STAGE = json.dumps([{'who': 'Dorren Hayle', 'field': 'posture', 'item': '', 'value': 'sitting',
                     'quote': 'She sat'}])


def scene_reply(prose='She sat at the desk. The village was gone from the map.'):
    return f'<scene>\n{prose}\n</scene>\n<stage>\n{STAGE}\n</stage>'


@pytest.fixture
def requests(monkeypatch):
    """Every Messages request, answered in turn by `requests.replies` (a
    function of the request body, or a list)."""
    from storyforge import api

    class Requests(list):
        replies = []

    seen = Requests()

    def fake(path, body=None, method='GET', timeout=600):
        seen.append(json.loads(json.dumps(body)))
        r = seen.replies
        return r(body) if callable(r) else r.pop(0)
    monkeypatch.setattr(api, '_api_request', fake)
    return seen


# --- the reply ---

def test_a_reply_gives_the_scene_and_the_stage():
    d = session.parse_reply('Some talk.\n' + scene_reply(), SCENE)
    assert d.prose.startswith('She sat at the desk.') and d.prose.endswith('\n')
    assert d.stage[0]['value'] == 'sitting' and d.stage_problem == ''


def test_a_reply_without_a_scene_stops_the_session():
    with pytest.raises(session.SessionError, match='no <scene>'):
        session.parse_reply('Here is the scene: She sat.', SCENE)


@pytest.mark.parametrize('stage, problem', [
    ('', 'no stage note'),
    ('<stage>\nnot json\n</stage>', 'not a JSON list'),
    ('<stage>\n[{"who": "D", "field": "wings", "value": "up"}]\n</stage>', 'wings'),
])
def test_a_stage_note_that_cant_be_used_is_said(stage, problem):
    d = session.parse_reply('<scene>\nShe sat.\n</scene>\n' + stage, SCENE)
    assert d.prose == 'She sat.\n' and problem in d.stage_problem


# --- the writer's context ---

def test_the_context_holds_the_voice_and_the_cast_never_the_checks(project_dir):
    text = '\n'.join(b['text'] for b in session.system_blocks(project_dir))
    assert 'The village was not there' in text            # the anchor
    assert 'Measures before it feels' in text              # book.md
    assert 'Her heart pounded' not in text                 # checks.md
    assert '## The cast' in text and '- Dorren Hayle' in text
    assert session.system_blocks(project_dir)[-1]['cache_control'] == {'type': 'ephemeral'}


def test_no_voice_no_session(project_dir):
    import shutil
    shutil.rmtree(os.path.join(project_dir, voice_book.VOICE_DIR))
    with pytest.raises(session.SessionError, match='writes toward the voice'):
        session.system_blocks(project_dir)


def test_the_story_so_far_is_word_for_word_then_summaries_past_the_cap(project_dir):
    from storyforge import ledger
    order = sorted(ledger.scene_order(project_dir), key=ledger.scene_order(project_dir).get)
    last = order[-1]
    text, notes = session.story_so_far(project_dir, last, cap_words=10**6)
    assert '# The story so far' in text and 'summary' not in ' '.join(notes)
    small, notes = session.story_so_far(project_dir, last, cap_words=50)
    assert '## Before that, in summary' in small
    assert any('as summaries only' in n for n in notes)
    assert session.story_so_far(project_dir, order[0], 10**6)[0] == ''


# --- the plan ---

def _brief(project_dir, **cells):
    from storyforge.elaborate import update_scene
    update_scene(SCENE, os.path.join(project_dir, 'reference'), cells)


def test_the_plan_is_lean_and_leaves_notes_out_when_asked(project_dir):
    _brief(project_dir, key_actions='She finds the gap;She tells no one',
           motifs='counting the fires', key_dialogue='Dorren: "No."')
    lean = session.scene_plan(project_dir, SCENE, notes=False)
    assert '1. She finds the gap' in lean and '2. She tells no one' in lean
    assert 'counting the fires' not in lean and '"No."' not in lean
    full = session.scene_plan(project_dir, SCENE, notes=True)
    assert "## The author's notes" in full and 'counting the fires' in full


def test_the_plan_names_the_tense_the_anchor_and_the_carried_stage(project_dir):
    anchors = voice_book.read_folder(project_dir).anchors
    plan = session.scene_plan(project_dir, SCENE, notes=False, anchors=anchors,
                              carried='- Dorren: posture: sitting')
    assert '**Closest anchor:** dorren-at-the-survey' in plan
    assert '## The stage as the last scene left it' in plan


def test_closest_anchor_prefers_pov_then_tense():
    a = voice_book.Anchor('a/x.md', 'T.', pov='Hector', tense='past')
    b = voice_book.Anchor('a/y.md', 'T.', tense='present')
    assert session.closest_anchor([a, b], {'pov': 'hector', 'tense': 'present'}) == 'x'
    assert session.closest_anchor([a, b], {'pov': 'Zeus', 'tense': 'present'}) == 'y'
    assert session.closest_anchor([a, b], {'pov': 'Zeus'}) == ''


def test_brief_notes_setting(project_dir):
    assert session.brief_notes_wanted(project_dir)
    with open(os.path.join(project_dir, 'storyforge.yaml'), 'a') as f:
        f.write('\ndrafting:\n  brief_notes: exclude\n')
    assert not session.brief_notes_wanted(project_dir)


# --- the conversation ---

def test_settle_keeps_the_committed_scene_in_place_of_its_turns(project_dir, requests):
    s = session.Session(project_dir, 'claude-opus-5-5', [{'type': 'text', 'text': 'sys'}],
                        'STORY', str(project_dir))
    requests.replies = [_reply(scene_reply()), _reply(scene_reply('She stood.'))]
    s.write(SCENE, 'PLAN 1')
    s.rewrite(SCENE, 'tense')
    s.settle('PLAN 1', 'FINAL PROSE\n', [])
    roles = [m['role'] for m in s.messages]
    assert roles == ['user', 'assistant', 'user', 'assistant']
    assert 'FINAL PROSE' in s.messages[-1]['content'] and s.messages[-2]['content'] == 'PLAN 1'
    # each request carried the system context and asked for caching
    assert requests[0]['system'][0]['text'] == 'sys'
    assert requests[0]['cache_control'] == {'type': 'ephemeral'}


def test_a_cut_off_reply_is_an_error_and_leaves_no_turn(project_dir, requests):
    s = session.Session(project_dir, 'claude-opus-5-5', [], '', str(project_dir))
    cut = _reply('<scene>\nShe')
    cut['stop_reason'] = 'max_tokens'
    requests.replies = [cut]
    with pytest.raises(session.SessionError, match='token limit'):
        s.write(SCENE, 'PLAN')
    assert s.messages == []


def test_the_writer_fixes_the_gates_problems_with_edits(project_dir, requests):
    from storyforge.checker import CheckResult, Finding
    s = session.Session(project_dir, 'claude-opus-5-5', [], '', str(project_dir))
    f = Finding('contradiction', 'TIM', 'eight days', SCENE, 'five days', 'ledger', 'why')
    result = gate.GateResult(SCENE, check=CheckResult(SCENE, findings=[f]))
    edits = [{'problem': 1, 'find': 'eight days', 'replace': 'five days'}]
    requests.replies = [_reply(json.dumps({'edits': edits}))]
    out = []
    fixed = s.fixer(SCENE, 'It took eight days.', result, edits_out=out)
    assert fixed == 'It took five days.' and out == edits
    assert requests[0]['output_config']['format']['schema'] == gate.FIX_SCHEMA
    assert 'eight days' in requests[0]['messages'][-1]['content']


def test_a_fix_the_writer_cant_make_is_a_gate_error(project_dir, requests):
    from storyforge.checker import CheckResult, Finding
    s = session.Session(project_dir, 'claude-opus-5-5', [], '', str(project_dir))
    f = Finding('contradiction', 'TIM', 'eight days', SCENE, 'five days', 'ledger', 'why')
    result = gate.GateResult(SCENE, check=CheckResult(SCENE, findings=[f]))
    requests.replies = [_reply('not json')]
    with pytest.raises(gate.GateError, match='could not be read'):
        s.fixer(SCENE, 'It took eight days.', result, edits_out=[])


def test_gate_and_fix_uses_the_fixer_it_is_given(monkeypatch, tmp_path):
    from storyforge.checker import CheckResult, Finding
    f = Finding('contradiction', 'TIM', 'q', SCENE, 'e', '', 'why')
    runs = iter([gate.GateResult(SCENE, check=CheckResult(SCENE, findings=[f])),
                 gate.GateResult(SCENE, check=CheckResult(SCENE, findings=[]))])
    monkeypatch.setattr(gate, 'gate_scene', lambda *a, **k: next(runs))
    monkeypatch.setattr(gate, 'fix_scene', lambda *a, **k: pytest.fail('the gate\'s own fix'))
    used = []

    def fixer(scene, prose, result, **k):
        used.append(prose)
        k['edits_out'].append({'find': 'x', 'replace': 'y', 'problem': 1})
        return 'y'
    out = gate.gate_and_fix('p', SCENE, command='draft', prose='x', log_dir=str(tmp_path),
                            fixer=fixer)
    assert used == ['x'] and out.prose == 'y' and out.fixed


# --- the writer's stage sheet ---

def test_the_writers_sheet_is_compared_with_the_extracted_one(project_dir):
    from storyforge import stage_sheet
    prose = 'She sat. Then she stood.\n'
    session.save_writer_sheet(project_dir, SCENE, prose, json.loads(STAGE), 'm')
    mism, note = session.compare_sheets(project_dir, SCENE, prose)
    assert mism == [] and 'no extracted stage sheet' in note
    sheet = {'format': stage_sheet.FORMAT, 'scene_id': SCENE, 'source': 'extracted',
             'model': 'm', 'prose_sha256': stage_sheet.prose_hash(prose), 'cast': [],
             'opening': [], 'beats': [],
             'end': [{'who': 'Dorren Hayle', 'field': 'posture', 'item': '',
                      'value': 'standing', 'quote': 'she stood'}]}
    stage_sheet.write_sheet(project_dir, sheet)
    mism, note = session.compare_sheets(project_dir, SCENE, prose)
    assert note == '' and len(mism) == 1
    assert 'the writer says "sitting", the prose says "standing"' in mism[0]
    mism, note = session.compare_sheets(project_dir, SCENE, 'Other prose.\n')
    assert mism == [] and 'of other prose' in note


# --- the forecast ---

def test_the_forecast_grows_with_the_story_and_counts_the_review(project_dir):
    small = session.forecast(project_dir, ['a'], 'claude-opus-5-5', 2000, 0, 5000, False)
    big = session.forecast(project_dir, ['a'], 'claude-opus-5-5', 2000, 100_000, 5000, False)
    rev = session.forecast(project_dir, ['a'], 'claude-opus-5-5', 2000, 0, 5000, True)
    assert big[0] > small[0] and rev[0] > small[0]
    assert small[1] == gate.WRITE_GATE_COST_PER_SCENE
    assert 'voice review' in rev[2]


# --- the loop (write --session) ---

@pytest.fixture
def loop(project_dir, monkeypatch, requests):
    """`_run_session_mode` with the gate and the commits replaced."""
    from storyforge import cmd_write
    from storyforge.costs import RunBudget
    state = {'gate': lambda sid: (True, ''), 'commits': []}
    monkeypatch.setattr(cmd_write, 'select_model', lambda task: 'claude-opus-5-5')
    monkeypatch.setattr(cmd_write, '_gate_drafted_scene',
                        lambda pd, sid, f, c, ld, **k: state['gate'](sid))
    monkeypatch.setattr(cmd_write, '_verify_and_commit_scene',
                        lambda sid, *a, **k: (len(open(os.path.join(project_dir, 'scenes',
                                                                     f'{sid}.md')).read()
                                                   .split()), True))
    monkeypatch.setattr(cmd_write, '_commit', lambda pd, msg, paths:
                        state['commits'].append(msg))
    monkeypatch.setattr(gate, 'snapshot', lambda pd: None)
    monkeypatch.setattr(gate, 'recheck_queue', lambda pd, skip=frozenset(): [])

    def run(ids, stop_after=0):
        return cmd_write._run_session_mode(
            ids, project_dir, os.path.join(project_dir, 'scenes'),
            os.path.join(project_dir, 'working', 'logs'),
            os.path.join(project_dir, 'reference', 'scenes.csv'),
            dry_run=False, budget=RunBudget(), stop_after=stop_after)
    state['run'] = run
    return state


LONG = ' '.join(['She walked to the map.'] * 20) + ' Then she looked at it again.'


def _route(body):
    """Answer by what the request is: a review, a revision, or a scene."""
    if body.get('output_config'):
        schema = body['output_config']['format']['schema']
        if 'flags' in schema['properties']:
            return _reply(json.dumps({'flags': [{'quote': 'looked at it again', 'check': '2',
                                                 'why': 'a tail'}]}))
        if 'kept' in schema['properties']:
            return _reply(json.dumps({'edits': [{'flag': 1, 'find': 'looked at it again',
                                                 'replace': 'read it'}], 'kept': []}))
    return _reply(scene_reply(LONG))


def test_a_session_drafts_reviews_and_commits_each_scene(project_dir, loop, requests):
    requests.replies = _route
    out = loop['run'](['act1-sc01', 'act1-sc02'])
    assert out.drafted == 2 and out.failed == []
    with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md')) as f:
        assert 'read it' in f.read()                       # the reviser's edit
    assert os.path.isfile(os.path.join(project_dir, 'working', 'voice-reviews',
                                       'act1-sc01.md'))
    assert loop['commits'] == ['Session notes for act1-sc01', 'Session notes for act1-sc02']
    writes = [r for r in requests if not r.get('output_config')]
    # the second scene's request holds the first as committed, not as drafted
    history = json.dumps(writes[1]['messages'])
    assert 'read it' in history and 'looked at it again' not in history


def test_a_session_stops_for_a_read(project_dir, loop, requests, capsys):
    requests.replies = _route
    out = loop['run'](['act1-sc01', 'act1-sc02'], stop_after=1)
    assert out.drafted == 1
    assert 'stopped after 1 scene(s) for a read' in capsys.readouterr().out


def test_a_scene_the_gate_stops_on_stops_the_session(project_dir, loop, requests, capsys):
    requests.replies = _route
    loop['gate'] = lambda sid: (False, 'a contradiction')
    out = loop['run'](['act1-sc01', 'act1-sc02'])
    assert out.failed == [('act1-sc01', 'a contradiction')]
    assert 'The session stops' in capsys.readouterr().out


def test_a_tense_mismatch_goes_back_to_the_writer_once(project_dir, loop, requests):
    from storyforge.csv_cli import update_field
    csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    with open(csv) as f:
        lines = f.read().splitlines()
    with open(csv, 'w') as f:
        f.write('\n'.join([lines[0] + '|tense'] + [ln + '|' for ln in lines[1:]]) + '\n')
    update_field(csv, 'act1-sc01', 'tense', 'past')
    present = ' '.join(['She walks to the map. She looks at it. She is tired.'] * 6)
    answers = iter([_reply(scene_reply(present)), _reply(scene_reply(LONG))])
    requests.replies = lambda body: (_route(body) if body.get('output_config')
                                     else next(answers))
    out = loop['run'](['act1-sc01'])
    assert out.drafted == 1
    rewrites = [r for r in requests if 'Write the whole scene again'
                in json.dumps(r['messages'][-1])]
    assert len(rewrites) == 1


def test_no_checks_md_no_review_and_said(project_dir, loop, requests, capsys):
    os.remove(os.path.join(project_dir, voice_book.CHECKS_FILE))
    requests.replies = _route
    loop['run'](['act1-sc01'])
    assert 'has no checks yet, so no scene gets a voice review' in capsys.readouterr().out
    assert not [r for r in requests if r.get('output_config')]
