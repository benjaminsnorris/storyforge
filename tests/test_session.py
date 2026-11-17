"""Long writing sessions (#655): the writer's context, the lean plan, the
reply, the writer as the gate's fixer, the stage sheets, and the session
loop in `write --session`."""

import json
import os
import re

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
])
def test_a_stage_note_that_cant_be_used_is_said(stage, problem):
    d = session.parse_reply('<scene>\nShe sat.\n</scene>\n' + stage, SCENE)
    assert d.prose == 'She sat.\n' and problem in d.stage_problem and d.stage == []


def test_a_note_whose_only_entry_cant_be_read_carries_nothing_and_names_it():
    d = session.parse_reply('<scene>\nShe sat.\n</scene>\n<stage>\n'
                            '[{"who": "D", "field": "wings", "value": "up"}]\n</stage>', SCENE)
    assert d.stage == [] and d.stage_problem == ''
    assert len(d.stage_dropped) == 1 and 'wings' in d.stage_dropped[0]


@pytest.mark.parametrize('value', ['', None])
def test_a_blank_hand_is_not_read_as_empty_and_the_note_says_why(value):
    """The writer wrote '' for an empty hand (#700): blank can also mean "not
    known", so it isn't guessed to be empty. The note isn't used, the
    problem names the marker to write, and the writer's instructions name it.
    A null gets the same hint (SF-8)."""
    blank = {'who': 'D', 'field': 'hand_left', 'item': '', 'value': value, 'quote': ''}
    d = session.parse_reply('<scene>\nShe sat.\n</scene>\n<stage>\n'
                            + json.dumps([blank]) + '\n</stage>', SCENE)
    assert d.stage == [] and len(d.stage_dropped) == 1
    assert "value ''" in d.stage_dropped[0] and 'the word "empty"' in d.stage_dropped[0]
    assert 'or the word "empty" for an empty hand: never ""' in session.INSTRUCTIONS


def test_an_empty_hand_written_as_empty_is_carried():
    empty = {'who': 'D', 'field': 'hand_left', 'item': '', 'value': 'empty', 'quote': ''}
    d = session.parse_reply('<scene>\nShe sat.\n</scene>\n<stage>\n'
                            + json.dumps([empty]) + '\n</stage>', SCENE)
    assert d.stage_problem == '' and d.stage[0]['value'] == 'empty'
    assert session.carried_text(d.stage) == '- D: left hand: empty'


def test_the_writer_is_told_the_word_the_reader_takes_for_an_empty_hand():
    """TD-4: the instructions and the reader can't drift apart."""
    from storyforge import stage_sheet
    assert f'the word "{stage_sheet.EMPTY}" for an empty hand' in session.INSTRUCTIONS
    assert stage_sheet._hand_value(stage_sheet.EMPTY) == stage_sheet.EMPTY
    assert all(stage_sheet._hand_value(w) == stage_sheet.EMPTY
               for w in stage_sheet.EMPTY_HAND_WORDS)
    assert stage_sheet._hand_value('  ') == ''


def test_the_writers_scene_is_laid_out_a_sentence_per_line():
    """T-6: the review, the writer's sheet and the file hold the same prose."""
    d = session.parse_reply('<scene>\nShe sat. He stood.\n\n"Who?" she asks.\n</scene>\n', SCENE)
    assert d.prose == 'She sat.\nHe stood.\n\n"Who?" she asks.\n'


# the two door entries a real session wrote (#710): a place in `who`, and
# a value with more than the word
BAD_DOORS = [
    {'who': 'briseis-hut', 'field': 'door', 'item': "doorway of Briseis's hut",
     'value': 'open, empty', 'quote': 'a dark square in the sunlit wall, with nobody in it'},
    {'who': 'achilles-courtyard', 'field': 'door', 'item': 'gate in the fence',
     'value': 'shut', 'quote': 'The gate is shut.'}]
PEOPLE = [
    {'who': 'Briseis', 'field': 'posture', 'item': '', 'value': 'standing', 'quote': ''},
    {'who': 'Briseis', 'field': 'hand_right', 'item': '', 'value': 'empty', 'quote': ''},
    {'who': 'Briseis', 'field': 'worn', 'item': 'cloak', 'value': 'on', 'quote': ''},
    {'who': '', 'field': 'door', 'item': 'gate in the fence', 'value': 'shut',
     'quote': 'The gate is shut.'}]


def test_entries_that_cant_be_read_are_dropped_and_the_rest_kept():
    """#710: a `who` on a door cost the whole note. Now only those entries
    go, each named with its reason; the person entries (and a door written
    right) are kept as they were."""
    d = session.parse_reply('<scene>\nShe sat.\n</scene>\n<stage>\n'
                            + json.dumps(BAD_DOORS[:1] + PEOPLE + BAD_DOORS[1:])
                            + '\n</stage>', SCENE)
    assert d.stage_problem == ''
    assert [(e['who'], e['field']) for e in d.stage] == [(e['who'], e['field'])
                                                          for e in PEOPLE]
    assert len(d.stage_dropped) == 2
    assert 'names someone on door' in d.stage_dropped[0] and 'briseis-hut' in d.stage_dropped[0]
    assert 'names someone on door' in d.stage_dropped[1]
    assert 'achilles-courtyard' in d.stage_dropped[1]


def test_a_note_whose_entries_all_read_is_kept_unchanged():
    d = session.parse_reply('<scene>\nShe sat.\n</scene>\n<stage>\n'
                            + json.dumps(PEOPLE) + '\n</stage>', SCENE)
    assert d.stage == PEOPLE and d.stage_dropped == [] and d.stage_problem == ''


def test_the_writer_is_told_which_fields_take_a_who_and_their_words():
    """#710: the instructions name every field the note can hold, as a
    person's or the scene's (no `who`), with each closed field's words, so
    they and `Entry.from_json` can't drift apart."""
    from storyforge import stage_sheet
    text = session.INSTRUCTIONS
    person = text[text.index('Fields of a person'):text.index('Fields of the scene')]
    scene = text[text.index('Fields of the scene'):text.index('Where a field lists')]
    assert '"who" always ""' in scene
    for f in stage_sheet.STATE_FIELDS:
        where = person if f in stage_sheet.PERSON_FIELDS else scene
        assert re.search(rf'\b{f}\b', where), f
    for f, words in stage_sheet.VALUES.items():
        where = person if f in stage_sheet.PERSON_FIELDS else scene
        line = where[where.index(f):]
        assert all(w in line[:line.index(')')] for w in words), f
    assert all(p in person for p in stage_sheet.POSTURES if p != 'other')


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
    assert out.failed[0].startswith('act1-sc01 (did not pass the gate')
    assert out.failed[1] == 'act1-sc02 (not attempted: act1-sc01 did not pass the gate)'
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


def test_the_story_cap_without_a_key_is_the_fallback_window(monkeypatch, capsys):
    from storyforge import api
    monkeypatch.setattr(api, 'max_input_tokens',
                        lambda m: (_ for _ in ()).throw(RuntimeError('ANTHROPIC_API_KEY not set')))
    cap = session.story_cap_words('claude-opus-5-5')
    assert cap == int(session.FALLBACK_WINDOW * session.STORY_SHARE / session.TOKENS_PER_WORD)
    assert 'taken as 200,000 tokens' in capsys.readouterr().out


def test_must_lines_are_required_in_the_plan_whatever_the_notes(project_dir):
    # iliad-adult: a must: speech showed only among "notes, not requirements",
    # and not at all with notes excluded, while the gate stops a scene without it
    _brief(project_dir, key_actions='She finds the gap;must: She burns the map',
           key_dialogue='must: Dorren: "Not one line of it.";Kell: "Why?"')
    for notes in (False, True):
        plan = session.scene_plan(project_dir, SCENE, notes=notes)
        assert '2. She burns the map (must happen)' in plan and 'must:' not in plan
        assert '## Must be said' in plan and '- Dorren: "Not one line of it."' in plan
        assert plan.count('Not one line of it') == 1
    assert 'Kell: "Why?"' not in session.scene_plan(project_dir, SCENE, notes=False)
    assert '- key_dialogue: Kell: "Why?"' in session.scene_plan(project_dir, SCENE, notes=True)


def test_a_labelled_must_line_brings_the_label_reading(project_dir):
    from storyforge.speaker_labels import LABEL_READING
    _brief(project_dir, key_actions='She finds the gap', key_dialogue='must: Dorren: "No."')
    assert LABEL_READING in session.scene_plan(project_dir, SCENE, notes=False)
    # a label only on a line the plan leaves out brings no reading
    _brief(project_dir, key_dialogue='must: She refuses;Kell: "Why?"')
    assert LABEL_READING not in session.scene_plan(project_dir, SCENE, notes=False)


def test_bare_variant_and_misplaced_must_markers(project_dir):
    _brief(project_dir, key_actions='must:;MUST : She burns the map',
           key_dialogue='must:;Dorren: must: "No."', decision='must: She refuses the crown')
    said = []
    plan = session.scene_plan(project_dir, SCENE, notes=False, said=said)
    assert '1. She burns the map (must happen)' in plan and '2.' not in plan
    assert '## Must be said' not in plan and '- \n' not in plan
    assert 'must' not in plan.lower().replace('must happen', '')
    assert any(s.startswith('key_dialogue: "Dorren: must:') for s in said)
    assert any(s.startswith('decision: "must: She refuses') for s in said)


def test_the_gate_names_a_must_marker_in_a_note_column():
    from storyforge.gate import _misplaced_must
    assert _misplaced_must({'decision': 'must: She refuses', 'goal': 'escape'}) == [
        'decision: must: She refuses']


def test_a_craft_label_outcome_is_left_out_of_the_plan(project_dir):
    _brief(project_dir, outcome='yes-but')
    assert '## How it ends' not in session.scene_plan(project_dir, SCENE, notes=False)
    _brief(project_dir, outcome='She keeps the map and tells no one.')
    assert 'She keeps the map' in session.scene_plan(project_dir, SCENE, notes=False)



# --- the review's fixes (#685) ---

def test_a_session_error_midway_stops_cleanly(project_dir, loop, requests, capsys):
    answers = iter([_reply(scene_reply(LONG)), _reply('no scene here')])
    requests.replies = lambda body: (_route(body) if body.get('output_config')
                                     else next(answers))
    out = loop['run'](['act1-sc01', 'act1-sc02', 'act2-sc01'])
    assert out.drafted == 1
    assert out.failed[0].startswith('act1-sc02 (') and 'not attempted' in out.failed[1]
    assert 'resume from act1-sc02' in capsys.readouterr().out
    assert not os.path.isfile(os.path.join(project_dir, 'scenes', 'act1-sc02.md')) or \
        'no scene here' not in open(os.path.join(project_dir, 'scenes', 'act1-sc02.md')).read()


def test_a_provisional_scene_lets_the_session_go_on(project_dir, loop, requests, monkeypatch):
    from storyforge import cmd_write
    requests.replies = _route
    loop['gate'] = lambda sid: (False, 'a finding') if sid == 'act1-sc01' else (True, '')
    monkeypatch.setattr(cmd_write, 'is_provisional', lambda pd, sid: sid == 'act1-sc01')
    out = loop['run'](['act1-sc01', 'act1-sc02'])
    assert out.drafted == 2 and out.provisional == ['act1-sc01 (a finding)']


def test_a_drafted_scene_between_two_to_draft_reaches_the_writer(project_dir, loop, requests):
    requests.replies = _route
    with open(os.path.join(project_dir, 'scenes', 'act1-sc02.md'), 'w') as f:
        f.write('THE MIDDLE SCENE, ALREADY WRITTEN.\n')
    loop['run'](['act1-sc01', 'act2-sc01'])
    writes = [r for r in requests if not r.get('output_config')]
    assert 'THE MIDDLE SCENE' in json.dumps(writes[-1]['messages'])
    roles = [m['role'] for m in writes[-1]['messages']]
    assert all(a != b for a, b in zip(roles, roles[1:]))


def _set_status(project_dir, sid, status):
    path = os.path.join(project_dir, 'reference', 'scenes.csv')
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')
    header = lines[0].split('|')
    col = header.index('status')
    for n, line in enumerate(lines):
        cells = line.split('|')
        if cells[0] == sid:
            cells[col] = status
            lines[n] = '|'.join(cells)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def test_a_merged_scene_with_no_file_between_two_to_draft_is_passed_over(
        project_dir, loop, requests, capsys):
    requests.replies = _route
    _set_status(project_dir, 'act1-sc02', 'merged')
    os.remove(os.path.join(project_dir, 'scenes', 'act1-sc02.md'))
    out = loop['run'](['act1-sc01', 'act2-sc01'])
    assert out.drafted == 2 and out.failed == []
    said = capsys.readouterr().out.splitlines()
    assert not [line for line in said if 'writes past' in line and 'act1-sc02' in line]


def test_an_undrafted_scene_with_no_file_between_two_to_draft_is_a_gap(
        project_dir, loop, requests, capsys):
    requests.replies = _route
    os.remove(os.path.join(project_dir, 'scenes', 'act1-sc02.md'))
    out = loop['run'](['act1-sc01', 'act2-sc01'])
    assert out.drafted == 2 and out.failed == []
    said = capsys.readouterr().out
    assert 'WARNING: the session writes past' in said and 'act1-sc02' in said


def test_a_scene_that_fails_verification_stops_the_session(project_dir, loop, requests,
                                                           monkeypatch):
    from storyforge import cmd_write
    requests.replies = _route
    monkeypatch.setattr(cmd_write, '_verify_and_commit_scene', lambda *a, **k: (0, False))
    out = loop['run'](['act1-sc01', 'act1-sc02'])
    assert out.drafted == 0 and 'failed verification' in out.failed[0]
    assert 'not attempted' in out.failed[1]


def test_the_cost_threshold_stops_before_the_next_scene(project_dir, loop, requests,
                                                       monkeypatch, capsys):
    from storyforge import costs
    requests.replies = _route
    answers = iter([True, False])
    monkeypatch.setattr(costs, 'check_threshold', lambda *a, **k: next(answers))
    out = loop['run'](['act1-sc01', 'act1-sc02'])
    assert out.drafted == 1 and out.failed == ['act1-sc02 (not attempted: the cost threshold)']
    assert 'stopped at the cost threshold' in capsys.readouterr().out


def test_a_failed_voice_review_is_recorded_and_said(project_dir, loop, requests, capsys):
    def route(body):
        if body.get('output_config'):
            cut = _reply('{"flags": [')
            cut['stop_reason'] = 'max_tokens'
            return cut
        return _reply(scene_reply(LONG))
    requests.replies = route
    out = loop['run'](['act1-sc01'])
    assert out.drafted == 1
    with open(os.path.join(project_dir, 'working', 'voice-reviews', 'act1-sc01.md')) as f:
        assert "didn't finish" in f.read()
    assert 'without a finished voice review' in capsys.readouterr().out


def test_the_stage_is_carried_only_when_it_is_of_the_committed_prose(project_dir, loop,
                                                                     requests):
    def route(body):   # no review flag: the committed prose is the draft
        if body.get('output_config'):
            return _reply(json.dumps({'flags': []}))
        return _reply(scene_reply(LONG))
    requests.replies = route
    loop['run'](['act1-sc01', 'act1-sc02'])
    writes = [r for r in requests if not r.get('output_config')]
    assert '## The stage as the last scene left it' in writes[1]['messages'][-1]['content']
    requests.clear()
    requests.replies = _route   # the reviser changes the scene: nothing carried
    loop['run'](['act2-sc01', 'act2-sc02'])
    writes = [r for r in requests if not r.get('output_config')]
    assert '## The stage as the last scene left it' not in writes[1]['messages'][-1]['content']


def test_a_note_with_bad_door_entries_carries_its_person_entries(project_dir, loop,
                                                                 requests, capsys):
    """#710, in the loop: the two door entries are named as dropped, and the
    person entries reach the next scene's plan."""
    note = json.dumps(BAD_DOORS[:1] + PEOPLE[:3] + BAD_DOORS[1:])

    def route(body):   # no review flag: the committed prose is the draft
        if body.get('output_config'):
            return _reply(json.dumps({'flags': []}))
        return _reply(f'<scene>\n{LONG}\n</scene>\n<stage>\n{note}\n</stage>')
    requests.replies = route
    loop['run'](['act1-sc01', 'act1-sc02'])
    out = capsys.readouterr().out
    dropped = [ln for ln in out.splitlines()
               if 'act1-sc01: dropped from the writer\'s stage note' in ln]
    assert len(dropped) == 2
    assert 'briseis-hut' in dropped[0] and 'achilles-courtyard' in dropped[1]
    assert '3 entry(ies) of the writer\'s stage note kept, 2 dropped' in out
    assert "can't be used" not in out
    plan = [r for r in requests if not r.get('output_config')][1]['messages'][-1]['content']
    assert '## The stage as the last scene left it' in plan and 'cloak' in plan


def test_a_resumed_session_carries_the_writers_note(project_dir, loop, requests, capsys):
    """#707: with the default gate there's no extracted sheet; a session
    that resumes after a stop opens with the writer's note of the scene
    before, when that is of the prose as committed."""
    def route(body):
        if body.get('output_config'):
            return _reply(json.dumps({'flags': []}))
        return _reply(scene_reply(LONG))
    requests.replies = route
    loop['run'](['act1-sc01'])
    capsys.readouterr()
    requests.clear()
    loop['run'](['act1-sc02'])
    assert ('the stage act1-sc01 left is carried from its writer\'s stage note (1 state(s))'
            in capsys.readouterr().out)
    plan = [r for r in requests if not r.get('output_config')][0]['messages'][-1]['content']
    assert '## The stage as the last scene left it' in plan and 'Dorren Hayle' in plan


def test_a_resumed_session_says_why_an_edited_scenes_note_isnt_carried(project_dir, loop,
                                                                        requests, capsys):
    """#707: the reviser changed the scene after the writer's note, so the
    note is of other prose: not carried, and the log says why. (The
    extraction at the resume, #720, gets a scene for its reply here, so it
    fails and carries nothing.)"""
    requests.replies = _route
    loop['run'](['act1-sc01'])
    capsys.readouterr()
    requests.clear()
    loop['run'](['act1-sc02'])
    out = capsys.readouterr().out
    assert ("no state carried over: act1-sc01's writer's stage note is of its draft, which "
            "was changed after the writer wrote it" in out)
    plan = [r for r in requests if not r.get('output_config')][0]['messages'][-1]['content']
    assert '## The stage as the last scene left it' not in plan


# --- the stage extracted at a resume (#720) ---

def _extraction(body):
    return 'events' in ((body.get('output_config') or {}).get('format', {})
                        .get('schema', {}).get('properties', {}))


def _resume_route(extract):
    """Answer the stage extraction with `extract(body)`, the review with
    no flags, and the writer with a scene."""
    def route(body):
        if _extraction(body):
            return extract(body)
        if body.get('output_config'):
            return _reply(json.dumps({'flags': []}))
        return _reply(scene_reply(LONG))
    return route


#: what the fixture's act1-sc01 is read to leave: Dorren standing, the map
#: in her hand
SC01_EVENTS = {'cast': ['Dorren Hayle'], 'questions': [], 'events': [
    {'quote': '', 'who': 'Dorren Hayle', 'field': 'posture', 'item': '', 'from': '',
     'to': 'standing'},
]}


@pytest.fixture
def resume(project_dir, monkeypatch):
    """act1-sc01 (prose in the fixture, no sheet) is the scene before
    act1-sc02's session; each extraction reply quotes its own first words."""
    monkeypatch.setenv('STORYFORGE_STAGE_SHEET_MODEL', 'claude-haiku-5-5')
    from storyforge.illustrations import read_scene_raw
    prose = read_scene_raw(project_dir, 'act1-sc01')
    quote = ' '.join(prose.split()[:4])
    events = json.loads(json.dumps(SC01_EVENTS))
    events['events'][0]['quote'] = quote
    return {'events': events, 'quote': quote}


def test_a_resume_with_no_sheet_extracts_the_scene_before(project_dir, loop, requests,
                                                           resume, capsys):
    from storyforge import stage_sheet
    from storyforge.costs import ledger_rows
    requests.replies = _resume_route(lambda body: _reply(json.dumps(resume['events'])))
    out = loop['run'](['act1-sc02'])
    assert out.drafted == 1
    assert len([r for r in requests if _extraction(r)]) == 1
    log = capsys.readouterr().out
    assert 'no state carried over: act1-sc01 has no stage sheet yet' in log
    assert "extracting act1-sc01's stage sheet from its prose as it stands" in log
    assert ('the stage act1-sc01 left is carried from its stage sheet extracted at this '
            'resume (1 state(s))') in log
    saved = stage_sheet.load_sheet(stage_sheet.sheet_path(project_dir, 'act1-sc01'))
    assert saved['source'] == 'extracted' and saved['end'][0]['value'] == 'standing'
    plan = [r for r in requests if not r.get('output_config')][0]['messages'][-1]['content']
    assert '## The stage as the last scene left it' in plan and 'standing' in plan
    rows = ledger_rows(project_dir, ('stage-resume',))
    assert len(rows) == 1 and rows[0]['target'] == 'act1-sc01'


def test_a_resume_with_a_usable_sheet_extracts_nothing(project_dir, loop, requests, resume,
                                                       capsys):
    from storyforge import stage_sheet
    from storyforge.costs import ledger_rows
    from storyforge.illustrations import read_scene_raw
    r = stage_sheet.replay([stage_sheet.Event(resume['quote'], 'Dorren Hayle', 'posture', '',
                                              '', 'kneeling')])
    stage_sheet.write_sheet(project_dir, stage_sheet.build_sheet(
        'act1-sc01', read_scene_raw(project_dir, 'act1-sc01'), r))
    requests.replies = _resume_route(lambda body: pytest.fail('extracted again'))
    loop['run'](['act1-sc02'])
    assert 'carried from its stage sheet (1 state(s))' in capsys.readouterr().out
    assert ledger_rows(project_dir, ('stage-resume',)) == []


def test_a_failed_extraction_carries_nothing_and_the_session_goes_on(project_dir, loop,
                                                                      requests, resume, capsys):
    from storyforge import stage_sheet
    from storyforge.costs import ledger_rows
    requests.replies = _resume_route(lambda body: _reply('not the schema'))
    out = loop['run'](['act1-sc02'])
    assert out.drafted == 1 and out.failed == []
    log = capsys.readouterr().out
    assert ("WARNING: act1-sc01's stage sheet could not be extracted (act1-sc01: the stage "
            "sheet extraction failed twice") in log
    assert 'no state carried over, and the session goes on without it' in log
    assert 'carried from its stage sheet' not in log
    assert not os.path.exists(stage_sheet.sheet_path(project_dir, 'act1-sc01'))
    plan = [r for r in requests if not r.get('output_config')][0]['messages'][-1]['content']
    assert '## The stage as the last scene left it' not in plan
    assert len(ledger_rows(project_dir, ('stage-resume',))) == 1   # the spend still logged


def test_an_extraction_with_no_event_carries_nothing(project_dir, loop, requests, resume,
                                                     capsys):
    from storyforge import stage_sheet
    empty = {'cast': ['Dorren Hayle'], 'events': [], 'questions': []}
    requests.replies = _resume_route(lambda body: _reply(json.dumps(empty)))
    out = loop['run'](['act1-sc02'])
    assert out.drafted == 1
    log = capsys.readouterr().out
    assert ("can't give its end state (the extraction recorded no physical event" in log
            and 'no state carried over, and the sheet is not saved' in log)
    assert not os.path.exists(stage_sheet.sheet_path(project_dir, 'act1-sc01'))
    plan = [r for r in requests if not r.get('output_config')][0]['messages'][-1]['content']
    assert '## The stage as the last scene left it' not in plan


def test_a_dry_run_says_it_would_extract_and_calls_nothing(project_dir, monkeypatch, resume,
                                                           capsys):
    from storyforge import api, cmd_write
    monkeypatch.setattr(cmd_write, 'detect_project_root', lambda: project_dir)
    monkeypatch.setattr(cmd_write, 'select_model', lambda t: 'claude-opus-5-5')
    monkeypatch.setattr(api, '_api_request', lambda *a, **k: pytest.fail('spent'))
    monkeypatch.setattr(api, 'max_input_tokens', lambda m: 200_000)
    try:
        cmd_write.main(['--session', '--coaching', 'full', '--dry-run', '--force',
                        'act1-sc02'])
    except SystemExit as e:
        assert not e.code
    out = capsys.readouterr().out
    assert re.search(r"Cost forecast: .*~\$\d+\.\d\d to extract act1-sc01's stage at the "
                     r"resume", out)
    assert re.search(r"would extract act1-sc01's stage sheet from its prose as it stands "
                     r"\(one call on claude-haiku-5-5, ~\$\d+\.\d\d\)", out)


def test_the_forecast_counts_the_extraction_only_when_it_will_run(project_dir, monkeypatch,
                                                                  resume):
    from storyforge import cmd_write, stage_sheet
    from storyforge.illustrations import read_scene_raw
    monkeypatch.setattr(cmd_write, 'select_model', lambda t: 'claude-opus-5-5')
    monkeypatch.setattr(session, 'forecast', lambda *a, **k: (1.0, 0.0, 'base'))
    csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    f = cmd_write._session_forecast(project_dir, ['act1-sc02'], csv)
    cost = stage_sheet.extraction_cost(read_scene_raw(project_dir, 'act1-sc01'),
                                       'claude-haiku-5-5')
    assert f.draft == pytest.approx(1.0 + cost) and 'to extract act1-sc01' in f.basis
    # the first scene has none before it; a usable sheet needs no extraction
    assert cmd_write._session_forecast(project_dir, ['act1-sc01'], csv).draft == 1.0
    r = stage_sheet.replay([stage_sheet.Event(resume['quote'], 'Dorren Hayle', 'posture', '',
                                              '', 'kneeling')])
    stage_sheet.write_sheet(project_dir, stage_sheet.build_sheet(
        'act1-sc01', read_scene_raw(project_dir, 'act1-sc01'), r))
    assert cmd_write._session_forecast(project_dir, ['act1-sc02'], csv).draft == 1.0


def test_the_spend_reaches_the_cost_ledger(project_dir, loop, requests):
    from storyforge.costs import ledger_rows
    requests.replies = _route
    loop['run'](['act1-sc01'])
    ops = {r['operation'] for r in ledger_rows(project_dir, ('draft', 'voice-review'))}
    assert ops == {'draft', 'voice-review'}


@pytest.mark.parametrize('argv, why', [
    (['--session', '--coaching', 'coach'], 'full coaching'),
    (['--session', '--coaching', 'full', '--batch'], 'full coaching'),
    (['--session', '--coaching', 'full', '-i'], 'full coaching'),
    (['--coaching', 'full', '--stop-after', '2'], '--stop-after'),
    (['--session', '--coaching', 'full', '--stop-after', '-1'], '--stop-after'),
])
def test_the_session_flags_are_checked_first(project_dir, monkeypatch, capsys, argv, why):
    from storyforge import cmd_write
    monkeypatch.setattr(cmd_write, 'detect_project_root', lambda: project_dir)
    with pytest.raises(SystemExit) as e:
        cmd_write.main(argv + ['--dry-run'])
    assert e.value.code == 1 and why in capsys.readouterr().out


def test_stop_after_defaults(project_dir, tmp_path):
    from storyforge import cmd_write
    assert cmd_write._stop_after(project_dir, None) == 0          # the fixture has prose
    assert cmd_write._stop_after(project_dir, 5) == 5
    empty = tmp_path / 'b'
    (empty / 'scenes').mkdir(parents=True)
    assert cmd_write._stop_after(str(empty), None) == 3


def test_a_dry_run_without_a_key_names_the_model_once(monkeypatch, capsys):
    from storyforge import cmd_write
    monkeypatch.setattr(cmd_write, 'select_model',
                        lambda t: (_ for _ in ()).throw(RuntimeError('ANTHROPIC_API_KEY not set')))
    monkeypatch.setattr(cmd_write._session_model, 'said', False, raising=False)
    a, b = cmd_write._session_model(True), cmd_write._session_model(True)
    assert a == b and capsys.readouterr().out.count('the dry run takes the writer') == 1
    with pytest.raises(RuntimeError):
        cmd_write._session_model(False)


def test_a_session_dry_run_spends_nothing(project_dir, monkeypatch, capsys):
    from storyforge import api, cmd_write
    monkeypatch.setattr(cmd_write, 'detect_project_root', lambda: project_dir)
    monkeypatch.setattr(cmd_write, 'select_model', lambda t: 'claude-opus-5-5')
    monkeypatch.setattr(api, '_api_request', lambda *a, **k: pytest.fail('spent'))
    monkeypatch.setattr(api, 'max_input_tokens', lambda m: 200_000)
    try:
        cmd_write.main(['--session', '--coaching', 'full', '--dry-run', '--force',
                        'act1-sc01'])
    except SystemExit as e:
        assert not e.code
    out = capsys.readouterr().out
    assert 'Cost forecast:' in out and "the writer's standing context is" in out
    assert '# Next: The Finest Cartographer (act1-sc01)' in out


# --- end-of-run bookkeeping (#699) ---

def _git(cwd, *args):
    import subprocess
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


def _append(project_dir, rel, line):
    path = os.path.join(project_dir, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


@pytest.fixture
def book(project_dir, monkeypatch):
    """`project_dir` as a git repo with the book's own .gitignore (as init
    writes it: working/logs/ ignored, so the closing summary's log lines,
    written after the commit, don't dirty the tree), and `write`'s branch,
    PR, forecast and closing steps stubbed. `book.mode(fake)` replaces the
    drafting mode; `book.run(argv)` runs `main` and returns its exit code."""
    import shutil
    from storyforge import cmd_write
    from storyforge.costs import WriteForecast
    shutil.copy(os.path.join(get_plugin_dir(), 'templates', 'gitignore'),
                os.path.join(project_dir, '.gitignore'))
    _git(project_dir, 'init', '-q', '-b', 'storyforge/write-test')
    _git(project_dir, 'config', 'user.email', 't@example.com')
    _git(project_dir, 'config', 'user.name', 'T')
    _git(project_dir, 'add', '-A')
    _git(project_dir, 'commit', '-q', '-m', 'start')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    # --coaching sets STORYFORGE_COACHING for the process: undone after
    monkeypatch.setenv('STORYFORGE_COACHING', 'full')
    monkeypatch.setattr(cmd_write, 'detect_project_root', lambda: project_dir)
    monkeypatch.setattr(cmd_write, 'create_branch', lambda *a, **k: None)
    monkeypatch.setattr(cmd_write, 'ensure_branch_pushed', lambda *a, **k: None)
    monkeypatch.setattr(cmd_write, 'create_draft_pr', lambda *a, **k: None)
    monkeypatch.setattr(cmd_write, '_held_up_front', lambda *a, **k: {})
    forecast = lambda *a, **k: WriteForecast(draft=1.0, gate=0.0, basis='test')
    monkeypatch.setattr(cmd_write, '_session_forecast', forecast)
    monkeypatch.setattr(cmd_write, '_forecast', forecast)
    monkeypatch.setattr(cmd_write, 'check_threshold', lambda *a, **k: True)
    monkeypatch.setattr(cmd_write, 'print_summary', lambda *a, **k: None)
    monkeypatch.setattr('storyforge.timeline.drift_check',
                        lambda pd, ids: _append(pd, 'working/timeline-cues.csv',
                                                'act1-sc01|day 1'))

    def review(kind, pd, pr=''):
        _append(pd, 'working/pipeline.csv', '3|2026-11-15|complete||||||')
        _append(pd, 'working/recommendations.md', '# Next steps')
    monkeypatch.setattr(cmd_write, 'run_review_phase', review)

    class Book:
        dir = project_dir

        def mode(self, name, fake):
            monkeypatch.setattr(cmd_write, name, fake)

        def run(self, argv):
            try:
                cmd_write.main(argv)
            except SystemExit as e:
                return e.code or 0
            return 0

        def status(self):
            return _git(project_dir, 'status', '--porcelain', '-uall')

        def dirty(self):
            return {line[3:] for line in self.status().splitlines()}

        def last(self):
            return _git(project_dir, 'log', '-1', '--format=%s').strip()
    return Book()


def _leaves_files(failed=(), drafted=1, seen=None):
    """A drafting mode that leaves what a real one leaves past its scenes'
    commits: a ledger row and a regenerated scenes-review.md."""
    from storyforge import cmd_write

    def mode(*a, **k):
        if seen is not None:
            seen.update(k)
        _append(a[1], 'working/costs/ledger.csv', 'x|draft|1.00')
        _append(a[1], 'reference/scenes-review.md', '- act1-sc01: drafted, 210 words')
        return cmd_write.DraftOutcome(drafted=drafted, words=210 * drafted,
                                      failed=list(failed))
    return mode


SESSION = ['--session', '--coaching', 'full', '--force', 'act1-sc01']


def test_a_stopped_session_leaves_its_bookkeeping_committed(book):
    """The real bug (#699): a session stopped for a read left the ledger,
    the pipeline row, the cues and scenes-review.md uncommitted."""
    seen = {}
    book.mode('_run_session_mode', _leaves_files(seen=seen))
    assert book.run(SESSION + ['--stop-after', '1']) == 0
    assert seen['stop_after'] == 1
    assert book.status() == ''
    assert book.last() == 'Write: run bookkeeping (costs, pipeline, reviews)'
    committed = _git(book.dir, 'show', '--name-only', '--format=', 'HEAD').split()
    assert set(committed) == {'working/costs/ledger.csv', 'reference/scenes-review.md',
                              'working/timeline-cues.csv', 'working/pipeline.csv',
                              'working/recommendations.md'}


@pytest.mark.parametrize('mode, argv', [
    ('_run_session_mode', SESSION),
    ('_run_direct_mode', ['--coaching', 'full', '--force', 'act1-sc01']),
    ('_run_batch_mode', ['--coaching', 'coach', '--batch', '--force', 'act1-sc01']),
])
def test_every_mode_commits_its_bookkeeping(book, mode, argv):
    book.mode(mode, _leaves_files())
    assert book.run(argv) == 0
    assert book.status() == '' and book.last().startswith('Write: run bookkeeping')


def test_a_run_with_failed_scenes_or_none_drafted_still_commits_it(book):
    """A failed scene's API call is in the ledger with no scene commit to
    take it (T-3)."""
    book.mode('_run_session_mode', _leaves_files(failed=['act1-sc01 (bad reply)'], drafted=0))
    assert book.run(SESSION) == 1
    assert book.status() == '' and book.last().startswith('Write: run bookkeeping')


def test_a_mode_that_stops_part_way_still_commits_it(book):
    """A prompt direct mode can't build is a sys.exit mid-run (SF-5)."""
    def mode(*a, **k):
        _append(a[1], 'working/costs/ledger.csv', 'x|draft|1.00')
        raise SystemExit(1)
    book.mode('_run_direct_mode', mode)
    assert book.run(['--coaching', 'full', '--force', 'act1-sc01']) == 1
    assert book.status() == '' and book.last().startswith('Write: run bookkeeping')


def test_an_interrupt_does_not_commit_it(book, monkeypatch):
    from storyforge import common

    def mode(*a, **k):
        _append(a[1], 'working/costs/ledger.csv', 'x|draft|1.00')
        monkeypatch.setattr(common, '_shutting_down', True)
        raise SystemExit(130)
    book.mode('_run_direct_mode', mode)
    assert book.run(['--coaching', 'full', '--force', 'act1-sc01']) == 130
    assert book.last() == 'start' and 'working/costs/ledger.csv' in book.dirty()


def test_the_authors_own_changes_stay_out_and_are_named(book, capsys):
    """Edits made before the run are the author's (CR-1, SF-1): a file the
    run didn't touch is left as it was, one it also wrote to is named."""
    _append(book.dir, 'reference/scene-briefs.csv', 'my edit')
    _append(book.dir, 'reference/scenes-review.md', 'my note')
    book.mode('_run_session_mode', _leaves_files())
    assert book.run(SESSION) == 0
    committed = _git(book.dir, 'show', '--name-only', '--format=', 'HEAD').split()
    assert 'reference/scene-briefs.csv' not in committed
    assert 'reference/scenes-review.md' not in committed
    assert 'working/costs/ledger.csv' in committed
    out = capsys.readouterr().out
    assert 'were already changed before it' in out and 'reference/scenes-review.md' in out
    assert 'reference/scene-briefs.csv' not in out.split('already changed')[1].split('\n')[0]
    assert book.dirty() == {'reference/scene-briefs.csv', 'reference/scenes-review.md'}


def test_what_the_run_leaves_outside_the_bookkeeping_is_named(book, capsys):
    def mode(*a, **k):
        _append(a[1], 'notes.md', 'stray')
        return _leaves_files()(*a, **k)
    book.mode('_run_session_mode', mode)
    assert book.run(SESSION) == 0
    assert 'WARNING: the run left 1 file(s) uncommitted: notes.md' in capsys.readouterr().out


def test_a_failed_bookkeeping_commit_fails_the_run(book, monkeypatch, capsys):
    """T-1: an otherwise clean run exits 1, and says so."""
    from storyforge import cmd_write
    real = cmd_write._commit

    def commit(pd, msg, paths):
        if msg.startswith('Write: run bookkeeping'):
            raise cmd_write.CommitError('the commit failed: index.lock')
        return real(pd, msg, paths)
    monkeypatch.setattr(cmd_write, '_commit', commit)
    book.mode('_run_session_mode', _leaves_files())
    assert book.run(SESSION) == 1
    assert "ERROR: the run's bookkeeping is not committed" in capsys.readouterr().out
    assert 'working/costs/ledger.csv' in book.dirty()


def test_no_bookkeeping_commit_after_a_failed_commit(book, monkeypatch, capsys):
    """Its paths would sweep the uncommitted scene's files in under the
    wrong message: left for the hand commit, said, and the run fails."""
    from storyforge import cmd_write

    def mode(*a, **k):
        _leaves_files()(*a, **k)
        return cmd_write.DraftOutcome(drafted=0, words=0, failed=[],
                                      uncommitted=['act1-sc01 (git failed)'])
    book.mode('_run_session_mode', mode)
    monkeypatch.setattr(cmd_write, '_commit_bookkeeping',
                        lambda *a: pytest.fail('committed'))
    assert book.run(SESSION) == 1
    assert 'bookkeeping (at least the cost ledger) is not committed' in capsys.readouterr().out


def test_the_real_review_phase_leaves_nothing_behind(book, monkeypatch):
    """T-2: the review phase writes the pipeline row after its own commits,
    and its calls add ledger rows after them too."""
    from storyforge import api, cmd_write, git
    monkeypatch.setattr(cmd_write, 'run_review_phase', git.run_review_phase)
    monkeypatch.setattr(api, 'invoke_api', lambda *a, **k: '# Review\n\nFine.')
    monkeypatch.setattr(git, '_push', lambda pd: True)
    book.mode('_run_session_mode', _leaves_files())
    assert book.run(SESSION) == 0
    assert book.status() == ''


def test_a_dry_run_commits_nothing(book, monkeypatch):
    from storyforge import cmd_write
    monkeypatch.setattr(cmd_write, '_commit', lambda *a: pytest.fail('committed'))
    book.mode('_run_session_mode', _leaves_files())
    assert book.run(SESSION + ['--dry-run']) == 0
    assert book.last() == 'start'


# --- the forecast covers the scenes a stopping session drafts (#708) ---

@pytest.fixture
def priced(book, monkeypatch):
    """`book` with the session forecast at $10 a scene and a $35 threshold:
    the whole fixture book is over it, three scenes are under it."""
    from storyforge import cmd_write
    from storyforge.costs import WriteForecast
    seen = {}

    def forecast(pd, ids, csv, count=None):
        n = len(ids) if count is None else count
        seen.update(pending=len(ids), count=n)
        return WriteForecast(draft=10.0 * n, gate=0.0, basis='test')
    monkeypatch.setattr(cmd_write, '_session_forecast', forecast)
    monkeypatch.setattr(cmd_write, 'check_threshold', lambda total: total <= 35)
    monkeypatch.setattr(cmd_write, 'cost_threshold', lambda: 35.0)
    book.seen = seen
    return book


ALL = ['--session', '--coaching', 'full', '--force']


def test_a_session_that_stops_after_3_is_forecast_for_3(priced, capsys):
    """The real bug (#708): --stop-after 3 refused to start because the
    whole book was over the threshold."""
    run = {}
    priced.mode('_run_session_mode', _leaves_files(seen=run))
    assert priced.run(ALL + ['--stop-after', '3']) == 0
    pending = priced.seen['pending']
    assert pending > 3 and priced.seen['count'] == 3
    out = capsys.readouterr().out
    assert (f'Cost forecast: ~$30.00 for 3 of {pending} scenes, stopping after 3 for a read'
            in out)
    assert run['stop_after'] == 3
    assert run['scene_forecast'] == pytest.approx(10.0)   # per scene, not per book


def test_a_stopping_dry_run_has_no_over_threshold_note(priced, capsys):
    priced.mode('_run_session_mode', _leaves_files())
    assert priced.run(ALL + ['--stop-after', '3', '--dry-run']) == 0
    out = capsys.readouterr().out
    assert 'for 3 of' in out and 'over the cost threshold' not in out


def test_a_session_with_no_stop_still_checks_the_whole_book(priced, capsys):
    priced.mode('_run_session_mode', lambda *a, **k: pytest.fail('drafted'))
    assert priced.run(ALL + ['--stop-after', '0']) == 1
    pending = priced.seen['pending']
    assert priced.seen['count'] == pending
    out = capsys.readouterr().out
    assert f'for {pending} scenes (mode session' in out and 'nothing written' in out


def test_the_default_stop_on_a_book_with_no_prose_forecasts_three(priced, capsys):
    import glob
    for path in glob.glob(os.path.join(priced.dir, 'scenes', '*.md')):
        open(path, 'w').close()
    run = {}
    priced.mode('_run_session_mode', _leaves_files(seen=run))
    assert priced.run(ALL) == 0
    assert priced.seen['count'] == 3 and run['stop_after'] == 3
    assert 'stopping after 3 for a read' in capsys.readouterr().out


def test_a_stop_past_the_pending_scenes_forecasts_them_all(priced, capsys):
    priced.mode('_run_session_mode', _leaves_files())
    priced.run(ALL + ['--stop-after', '50', '--dry-run'])
    pending = priced.seen['pending']
    assert priced.seen['count'] == pending
    assert f'for {pending} scenes (mode session' in capsys.readouterr().out


def test_the_session_forecast_prices_the_first_scenes_in_reading_order(project_dir,
                                                                       monkeypatch):
    from storyforge import cmd_write, ledger
    seen = {}
    monkeypatch.setattr(cmd_write, 'select_model', lambda t: 'claude-opus-5-5')
    monkeypatch.setattr(session, 'forecast',
                        lambda pd, ids, *a, **k: seen.setdefault('ids', ids) and (1.0, 0.0, ''))
    order = ledger.scene_order(project_dir)
    ids = sorted(order, key=order.get)
    csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    cmd_write._session_forecast(project_dir, list(reversed(ids)), csv, count=2)
    assert seen['ids'] == ids[:2]
    seen.clear()
    cmd_write._session_forecast(project_dir, ids, csv)
    assert seen['ids'] == ids


def test_is_bookkeeping():
    from storyforge.cmd_write import _is_bookkeeping
    assert _is_bookkeeping('working/costs/ledger.csv')
    assert _is_bookkeeping('working/recommendations-3.md')
    assert _is_bookkeeping('reference/scenes-review.md')
    assert _is_bookkeeping('working/stage-sheets/act1-sc01.json')   # saved at a resume (#720)
    assert not _is_bookkeeping('working/recommendations/x.md')
    assert not _is_bookkeeping('working/pipeline.csv.bak')
    assert not _is_bookkeeping('scenes/act1-sc01.md')
