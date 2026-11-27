"""The gate's source check (#557, B-031, B-027): in a faithful adaptation the
source, not the first telling, decides a contradiction between scenes, and
a fact the source contradicts is reported, never dropped (#742). The API is mocked as in
tests/test_gate.py; the source call is the one whose schema asks for
`contradictions`."""

import json
from unittest.mock import patch

import pytest

from storyforge import gate, gate_source, ledger

from test_gate import (SCENE, _commitment, _contradiction, _is_persistence,
                        _persistence_reply, _pure_prose_scenes, _text)  # noqa: F401

EARLIER = 'act1-sc01'
#: each source scene's text (the fixture's `_source_text`)
TOLD = {'s1': 'the herald counted three hundred souls in the hollow',
        's2': 'the herald counted four hundred and twelve souls, and the sword broke in '
              'his hand'}
#: each source scene's summary (ours, not the source's words: never a quote)
BRIEF = {'s1': 'the herald takes a census of the whole hollow',
         's2': 'the herald recounts the hollow and his weapon fails him'}
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
                        lambda project_dir, refs: f'SOURCE {refs[0][1]}: {BRIEF[refs[0][1]]}\n'
                                                  f'<source-prose scene="{refs[0][1]}">\n'
                                                  f'{TOLD[refs[0][1]]}\n</source-prose>')
    monkeypatch.setattr(gate_source, 'has_source_prose', lambda project_dir, refs: True)
    gate_source._MEMO.clear()
    return ctx


def _run(project_dir, tmp_path, commitments, findings=(), source=None, sent=None,
         scene=SCENE):
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
        return gate.gate_scene(project_dir, scene, command='draft',
                               log_dir=str(tmp_path / 'logs'), extract_model='m',
                               check_model='m')


def _two():
    return [_commitment(), _commitment(statement=SECOND, quote=SECOND_QUOTE)]


def _mine(project_dir):
    return sorted(r['statement'] for r in ledger.load(project_dir)
                  if r['scene_id'] == SCENE and ledger.is_commitment(r))


def test_a_fact_the_source_contradicts_is_reported_and_still_committed(
        project_dir, tmp_path, adaptation):
    """B-027 dropped a fact the source contradicts; #742: 11 of 18 such
    verdicts were wrong (the check misread, or the translation slipped
    against the original), and each dropped a true fact. The ledger records
    what the book says; the departure goes to the author."""
    sent = []
    result = _run(project_dir, tmp_path, _two(), sent=sent, source={
        'facts': [{'n': 2, 'verdict': 'contradicts', 'why': 'the source: the well is full'},
                  {'n': 1, 'verdict': 'agrees', 'why': 'w'}],
        'contradictions': [], 'findings': []})
    assert result.committed
    assert _mine(project_dir) == sorted([SECOND, "Tarren's Hollow had 412 people"])
    assert result.source_departs == [(SECOND, 'the source: the well is full')]
    assert any(line.startswith('NOTE (recorded, but the source contradicts it')
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
                source={'facts': [], 'findings': [], 'contradictions': [
                    {'n': 1, 'backs': 'this', 'why': 'the poem says so',
                     'source_quote': 'counted four hundred and twelve souls'}]})


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
    assert EARLIER not in gate.pending(project_dir)   # its own file, not a gate stop
    row = gate.source_fixes(project_dir)[EARLIER]
    assert SCENE in row['reason'] and gate.source_fix_waits(project_dir, EARLIER)
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


def _cmd_check(project_dir, monkeypatch):
    from storyforge import cmd_check
    monkeypatch.setattr(cmd_check, 'detect_project_root', lambda: project_dir)
    monkeypatch.setattr('storyforge.git.create_branch', lambda *a: 'b')
    monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **k: True)
    return cmd_check


WRONG = _commitment(statement='The Hollow had 300 people', subject='tarrens-hollow',
                    quote='Dorren Hayle pressed the brass calipers against the vellum')


def _edit_earlier(project_dir):
    import os
    path = os.path.join(project_dir, 'scenes', f'{EARLIER}.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text + '\n\nA new line toward the source.\n')


def test_the_source_fix_row_stays_until_the_earlier_prose_changes(
        project_dir, tmp_path, adaptation, monkeypatch):
    _earlier_fact(project_dir)
    _backs(project_dir, tmp_path)
    assert gate.source_fix_waits(project_dir, EARLIER)
    _cmd_check(project_dir, monkeypatch).main(['--pending'])   # skipped, said
    assert EARLIER in gate.source_fixes(project_dir)
    _edit_earlier(project_dir)
    assert not gate.source_fix_waits(project_dir, EARLIER)


def test_a_passing_recheck_of_the_earlier_scene_keeps_its_source_fix(
        project_dir, tmp_path, adaptation):
    """#557's second review: the earlier scene was already listed for a
    re-check; its pass cleared the row and the source fix with it."""
    _earlier_fact(project_dir)
    gate.mark_pending(project_dir, EARLIER, gate.RECHECK, 're-check: x changed 1 fact(s)')
    _backs(project_dir, tmp_path)
    result = _run(project_dir, tmp_path, [WRONG], scene=EARLIER)   # the re-check passes
    assert result.passed and EARLIER not in gate.pending(project_dir)
    assert gate.source_fix_waits(project_dir, EARLIER)


@pytest.mark.parametrize('source', [RuntimeError('HTTP 500'),
                                    {'facts': [], 'contradictions': []}])
def test_a_regate_of_the_unchanged_earlier_scene_never_rebinds_the_wrong_fact(
        project_dir, tmp_path, adaptation, source):
    """#557's second review: re-gated with its prose unchanged, the earlier
    scene's wrong fact was read again as new and committed binding beside
    the superseded row (the source call failed, or gave no verdict)."""
    _earlier_fact(project_dir)
    _backs(project_dir, tmp_path)
    gate_source._MEMO.clear()
    result = _run(project_dir, tmp_path, [WRONG], scene=EARLIER, source=source)
    assert result.committed
    early = [r for r in ledger.load(project_dir)
             if r['scene_id'] == EARLIER and ledger.is_commitment(r)]
    assert [(r['statement'], r['status']) for r in early] == [
        ('The Hollow had 300 people', 'superseded')]
    assert any('superseded' in n for n in result.source_notes)


def _rewrite_earlier(project_dir, old, new):
    import os
    path = os.path.join(project_dir, 'scenes', f'{EARLIER}.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    assert old in text
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace(old, new, 1))


AGREES = {'facts': [{'n': 1, 'verdict': 'agrees', 'why': 'w'}], 'contradictions': []}
RIGHT = _commitment(statement='The Hollow had 412 people', subject='tarrens-hollow',
                    quote='Dorren Hayle set the brass calipers against the census')


def _early(project_dir):
    return sorted((r['statement'], r['status']) for r in ledger.load(project_dir)
                  if r['scene_id'] == EARLIER and ledger.is_commitment(r))


def test_fixing_the_earlier_prose_retires_its_superseded_rows_and_the_row(
        project_dir, tmp_path, adaptation):
    _earlier_fact(project_dir)
    _backs(project_dir, tmp_path)
    _rewrite_earlier(project_dir, 'Dorren Hayle pressed the brass calipers against the vellum',
                     'Dorren Hayle set the brass calipers against the census')
    gate_source._MEMO.clear()
    result = _run(project_dir, tmp_path, [RIGHT], scene=EARLIER, source=AGREES)
    assert result.committed
    assert _early(project_dir) == [('The Hollow had 412 people', 'binding')]
    assert EARLIER not in gate.source_fixes(project_dir)


@pytest.mark.parametrize('edit', [('morning', 'mornin'), ('vellum', 'vellum\n')])
@pytest.mark.parametrize('source', [AGREES, RuntimeError('HTTP 500'),
                                    {'facts': [], 'contradictions': []}])
def test_an_edit_elsewhere_is_not_a_fix(project_dir, tmp_path, adaptation, edit, source):
    """#557's third review: a one-word edit elsewhere, or an added newline,
    counted as a fix toward the source, retired the superseded row, and the
    wrong fact was bound again when the source call failed or gave no
    verdict."""
    _earlier_fact(project_dir)
    _backs(project_dir, tmp_path)
    _rewrite_earlier(project_dir, *edit)
    gate_source._MEMO.clear()
    result = _run(project_dir, tmp_path, [WRONG], scene=EARLIER, source=source)
    assert result.committed
    assert _early(project_dir) == [('The Hollow had 300 people', 'superseded')]
    assert EARLIER in gate.source_fixes(project_dir)


def test_a_fix_the_source_check_did_not_rule_on_retires_nothing(
        project_dir, tmp_path, adaptation):
    _earlier_fact(project_dir)
    _backs(project_dir, tmp_path)
    _rewrite_earlier(project_dir, 'Dorren Hayle pressed the brass calipers against the vellum',
                     'Dorren Hayle set the brass calipers against the census')
    gate_source._MEMO.clear()
    _run(project_dir, tmp_path, [RIGHT], scene=EARLIER, source=RuntimeError('HTTP 500'))
    assert ('The Hollow had 300 people', 'superseded') in _early(project_dir)
    assert EARLIER in gate.source_fixes(project_dir)


def test_the_wrong_claim_from_another_sentence_and_type_is_not_bound(
        project_dir, tmp_path, adaptation):
    """#557's third review (minor): the same claim, quoted from another
    sentence and filed under another type, was bound beside the
    superseded row."""
    _earlier_fact(project_dir)
    _backs(project_dir, tmp_path)
    gate_source._MEMO.clear()
    other = _commitment(statement='The census counted 300 people', subject='tarrens-hollow',
                        type='knowledge', quote='measuring the distance between the river '
                                                'fork and the ridgeline')
    _run(project_dir, tmp_path, [other], scene=EARLIER)
    assert _early(project_dir) == [('The Hollow had 300 people', 'superseded')]


def test_a_second_source_fix_adds_its_reason(project_dir, adaptation):
    gate.mark_source_fix(project_dir, EARLIER, 'first reason')
    gate.mark_source_fix(project_dir, EARLIER, 'the source tells it otherwise')
    row = gate.source_fixes(project_dir)[EARLIER]
    assert 'first reason' in row['reason'] and 'the source tells it otherwise' in row['reason']


def test_a_departing_fact_lists_the_scene_for_the_author(project_dir, tmp_path, adaptation):
    _run(project_dir, tmp_path, _two(), source={
        'facts': [{'n': 2, 'verdict': 'contradicts', 'why': 'w'}], 'contradictions': [],
        'findings': []})
    assert 'contradicts 1 fact' in gate.source_fixes(project_dir)[SCENE]['reason']


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


def test_source_fixes_do_not_stop_drafting_and_status_shows_them(project_dir):
    from storyforge import cmd_write
    from storyforge.status import gate_waiting
    gate.mark_source_fix(project_dir, EARLIER, 'later scene')
    assert cmd_write._gate_blockers(project_dir, 'act2-sc01') == []
    assert [r['command'] for r in gate_waiting(project_dir)] == ['source-fix']


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


# ---- #742: same-scene findings, the budget, and no fact dropped ----------

HERE_QUOTE = 'population four hundred and twelve at last census'
HAS_IT = 'the sword broke in his hand'


def _own():
    """A finding against the scene itself (as the blocking read's are)."""
    return {'kind': 'contradiction', 'code': 'PHY', 'scene_quote': HERE_QUOTE,
            'established_scene': SCENE, 'fact_id': '', 'explanation': 'the sword is broken',
            'established_quote': HERE_QUOTE}


def _ruled(verdict, quote=HAS_IT):
    return {'facts': [], 'contradictions': [], 'findings': [
        {'n': 1, 'verdict': verdict, 'source_quote': quote, 'why': 'the source tells it'}]}


def _blocking_sent(result):
    return [f for f in result.findings + result.unverified if f.established_scene == SCENE]


def test_a_same_scene_finding_is_sent_and_the_source_having_it_is_listed_not_cleared(
        project_dir, tmp_path, adaptation):
    """#742: same-scene findings were never sent, so Homer's own oddities
    (Menelaus throwing down the hilt of a sword that broke) stopped the gate
    with no word that the source has them. Ben (2026-11-26): the slip is
    still smoothed, and the source's passage goes to the author."""
    sent = []
    result = _run(project_dir, tmp_path, _two(), findings=[_own()], sent=sent,
                  source=_ruled('source-has-it'))
    assert '## Findings' in sent[0] and HERE_QUOTE in sent[0].split('## Findings')[1]
    assert not result.passed and _blocking_sent(result)   # still blocks, still fixed
    [(f, quote, why)] = result.source_has_it
    assert f.established_scene == SCENE and quote == HAS_IT
    [row] = gate.source_notes(project_dir)
    assert row['scene_id'] == SCENE and row['source_quote'] == HAS_IT
    assert any(line.startswith('SOURCE HAS IT (still blocking') for line in
               gate.report_lines(result))
    # a fix round with the same ruling adds no second row
    gate_source._MEMO.clear()
    _run(project_dir, tmp_path, _two(), findings=[_own()], source=_ruled('source-has-it'))
    assert len(gate.source_notes(project_dir)) == 1


@pytest.mark.parametrize('quote', [
    'the sword shattered in his grip',           # not the source's
    'sword broke',                                # too short
    'the herald recounts the hollow and his weapon fails him',   # our summary (CR-2)
    'the ... sword ... in ... hand',              # pieces joined by "..." (CR-3)
    'counted three hundred souls in the hollow',  # an earlier scene's source (CR-7)
])
def test_source_has_it_needs_this_scenes_own_source_words(
        project_dir, tmp_path, adaptation, quote):
    """#742's review (CR-2, CR-3, CR-7): only an unbroken run of the
    source's own prose, from the source this scene adapts."""
    _earlier_fact(project_dir)   # the earlier scene's source is sent too
    result = _run(project_dir, tmp_path, _two(), findings=[_own(), _contradiction()],
                  source=_ruled('source-has-it', quote))
    assert result.source_has_it == [] and gate.source_notes(project_dir) == []
    assert any('not words of the source this scene adapts' in n for n in result.source_notes)


def test_backing_this_scene_may_quote_any_source_prose_sent(project_dir, tmp_path, adaptation):
    """#742's review (T-7): an earlier-scene contradiction may quote the
    earlier scene's source; a quote from a source not sent is refused."""
    _earlier_fact(project_dir)
    result = _run(project_dir, tmp_path, _two(), findings=[_contradiction()],
                  source={'facts': [], 'findings': [], 'contradictions': [
                      {'n': 1, 'backs': 'this', 'why': 'w',
                       'source_quote': 'counted three hundred souls in the hollow'}]})
    assert result.source_backed
    gate_source._MEMO.clear()
    gate.clear_pending(project_dir, SCENE)
    result = _run(project_dir, tmp_path, [_commitment(statement='A new fact', quote=SECOND_QUOTE)],
                  findings=[_contradiction()],
                  source={'facts': [], 'findings': [], 'contradictions': [
                      {'n': 1, 'backs': 'this', 'why': 'w',
                       'source_quote': 'a line from a source never sent here'}]})
    assert result.source_backed == []
    assert any('not words of the source sent' in n for n in result.source_notes)


def test_an_unverified_finding_is_sent_too(project_dir, tmp_path, adaptation):
    """#742's review (T-2): every blocking finding, its quote checked or not."""
    sent = []
    bad = dict(_own(), scene_quote='words that are nowhere in the scene at all')
    result = _run(project_dir, tmp_path, _two(), findings=[bad], sent=sent)
    assert result.unverified
    assert 'words that are nowhere in the scene' in sent[0].split('## Findings')[1]


def test_a_notes_row_keeps_its_cells_and_lf(project_dir, tmp_path, adaptation):
    """#742's review (T-3): a `|` in the reasoning can't split the row."""
    import os
    reply = _ruled('source-has-it')
    reply['findings'][0]['why'] = 'the source | tells it'
    _run(project_dir, tmp_path, _two(), findings=[_own()], source=reply)
    [row] = gate.source_notes(project_dir)
    assert '|' not in row['why'] and row['source_quote'] == HAS_IT
    with open(os.path.join(project_dir, gate.SOURCE_NOTES_PATH), 'rb') as f:
        assert b'\r\n' not in f.read()


def test_a_second_finding_citing_the_same_passage_gets_its_own_row(
        project_dir, tmp_path, adaptation):
    """#742's review (SF-5)."""
    other = dict(_own(), explanation='the hilt is thrown down')
    reply = _ruled('source-has-it')
    reply['findings'].append(dict(reply['findings'][0], n=2))
    _run(project_dir, tmp_path, _two(), findings=[_own(), other], source=reply)
    assert len(gate.source_notes(project_dir)) == 2


def test_an_unreadable_notes_file_is_said_and_the_finding_still_blocks(
        project_dir, tmp_path, adaptation):
    """#742's review (T-4)."""
    import os
    path = os.path.join(project_dir, gate.SOURCE_NOTES_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('not|the|header\n')
    result = _run(project_dir, tmp_path, _two(), findings=[_own()],
                  source=_ruled('source-has-it'))
    assert not result.passed and result.source_has_it
    assert any(gate.SOURCE_NOTES_PATH in n and 'could not be updated' in n
               for n in result.source_notes)


def test_other_findings_are_part_of_the_memo(project_dir, tmp_path, adaptation):
    """#742's review (T-6): another finding is another ruling."""
    sent = []
    _run(project_dir, tmp_path, _two(), findings=[_own()], sent=sent)
    gate.clear_pending(project_dir, SCENE)
    _run(project_dir, tmp_path, _two(),
         findings=[dict(_own(), explanation='another problem')], sent=sent)
    assert len(sent) == 2


@pytest.mark.parametrize('verdict', ['silent', 'prose-departs'])
def test_a_finding_the_source_is_silent_on_still_stops_and_is_not_listed(
        project_dir, tmp_path, adaptation, verdict):
    """#742: the draft's own staging (Paris on the bed, Ajax's baldric)."""
    result = _run(project_dir, tmp_path, _two(), findings=[_own()],
                  source=_ruled(verdict, ''))
    assert not result.passed and result.source_has_it == []
    assert gate.source_notes(project_dir) == []


def test_a_contradiction_whose_earlier_source_does_not_fit_is_still_ruled_on(
        project_dir, tmp_path, adaptation, monkeypatch):
    """#742: the Aeneas finding went unruled because the earlier scene's
    source passed the budget, though the healing passage was in this
    scene's own source."""
    monkeypatch.setattr(gate_source, 'MAX_SOURCE_CHARS', 250)
    _earlier_fact(project_dir)
    sent = []
    result = _run(project_dir, tmp_path, _two(), findings=[_contradiction()], sent=sent,
                  source={'facts': [], 'findings': [], 'contradictions': [
                      {'n': 1, 'backs': 'this', 'why': 'w',
                       'source_quote': 'counted four hundred and twelve souls'}]})
    assert 'SOURCE s2' in sent[0] and 'SOURCE s1' not in sent[0]
    assert f'The source behind {EARLIER} is not shown' in sent[0]
    assert result.passed and result.source_backed
    assert any('ruled on from' in n and 'alone' in n for n in result.source_notes)


def test_a_contradiction_with_an_unmapped_earlier_scene_is_still_ruled_on(
        project_dir, tmp_path, adaptation):
    del adaptation.refs[EARLIER]
    sent = []
    _run(project_dir, tmp_path, _two(), findings=[_contradiction()], sent=sent)
    assert f'The source behind {EARLIER} is not shown' in sent[0]


def test_backing_this_scene_needs_the_sources_own_words(project_dir, tmp_path, adaptation):
    _earlier_fact(project_dir)
    result = _run(project_dir, tmp_path, _two(), findings=[_contradiction()],
                  source={'facts': [], 'findings': [], 'contradictions': [
                      {'n': 1, 'backs': 'this', 'why': 'w', 'source_quote': ''}]})
    assert not result.passed and result.source_backed == []
    assert any('the contradiction stands' in n for n in result.source_notes)


@pytest.mark.parametrize('why', ['The prose has 412, so the source is not contradicted.',
                                 'The source has a dry well. (Wait: this matches the source.)'])
def test_a_contradicts_whose_reasoning_concludes_it_agrees_is_set_aside(
        project_dir, tmp_path, adaptation, why):
    """#742: 5 of 18 "contradicts" verdicts contradicted their own reasoning."""
    result = _run(project_dir, tmp_path, _two(), source={
        'facts': [{'n': 2, 'verdict': 'contradicts', 'why': why}], 'contradictions': [],
        'findings': []})
    assert result.committed and result.source_departs == []
    assert SCENE not in gate.source_fixes(project_dir)
    assert any('set aside' in n for n in result.source_notes)


@pytest.mark.parametrize('why', [
    'The source has a spear, not an arrow.',
    'The prose no longer matches the source: the stern.',
    # #742's review (SF-2, CR-4, T-1): partial agreement, or a denial
    # inside a departure, is still a departure
    'The prose not only contradicts the source, it adds a death.',
    'The fact does not merely contradict the source; it reverses the outcome.',
    'No contradiction in the order, but the source has three, not four.',
    'Only the count matches the source; the person is wrong.',
    "The prose matches the source's count but not its cause: the source has a spear.",
    'Although the order matches the source, the outcome differs.',
])
def test_a_partial_or_denied_agreement_is_still_a_departure(
        project_dir, tmp_path, adaptation, why):
    assert not gate_source.says_agrees(why)
    result = _run(project_dir, tmp_path, _two(), source={
        'facts': [{'n': 2, 'verdict': 'contradicts', 'why': why}], 'contradictions': [],
        'findings': []})
    assert result.source_departs == [(SECOND, why)]


def _erratum(sid='s2', has='the well was full', original='well ran dry'):
    from storyforge.source import Erratum
    return Erratum('7.471', sid, has, original, 'Murray', 'butler', 'homer')


def _with_errata(monkeypatch, adaptation, errata):
    monkeypatch.setattr(gate_source, 'setup', lambda project_dir: gate_source.Setup(
        adaptation.refs, adaptation.rules, adaptation.map_rows, errata=errata))


def test_known_slips_are_sent_and_a_fact_following_the_original_is_not_a_departure(
        project_dir, tmp_path, adaptation, monkeypatch):
    """#742 (Ben, 2026-11-26): Homer wins over Butler; known slips are in an
    errata file, sent with the call, and a verdict resting on one, against a
    fact that follows the original, is set aside."""
    _with_errata(monkeypatch, adaptation, {('src', 's2'): [_erratum()]})
    sent = []
    result = _run(project_dir, tmp_path, _two(), sent=sent, source={
        'facts': [{'n': 2, 'verdict': 'contradicts',
                   'why': 'The source has "the well was full".'}],
        'contradictions': [], 'findings': []})
    assert '## Known slips of the source text' in sent[0]
    assert ('- 7.471, s2: butler has "the well was full"; homer has "well ran dry" '
            '(checked: Murray)') in sent[0]
    assert result.source_departs == []
    assert any('known slip' in n and '7.471' in n for n in result.source_notes)


def test_a_fact_following_the_slip_is_a_departure(project_dir, tmp_path, adaptation,
                                                  monkeypatch):
    """#742's review (CR-1): prose on the translation's side of a known slip,
    against the original, departs."""
    _with_errata(monkeypatch, adaptation, {('src', 's2'): [_erratum()]})
    butler = _commitment(statement='The hollow said the well was full', quote=SECOND_QUOTE)
    why = 'The original has "well ran dry"; the prose has "the well was full".'
    result = _run(project_dir, tmp_path, [_commitment(), butler], source={
        'facts': [{'n': 2, 'verdict': 'contradicts', 'why': why}],
        'contradictions': [], 'findings': []})
    assert result.source_departs == [('The hollow said the well was full', why)]


def test_a_slip_of_a_source_scene_not_in_the_call_is_not_used(
        project_dir, tmp_path, adaptation, monkeypatch):
    """#742's review (SF-3, T-5)."""
    _with_errata(monkeypatch, adaptation, {('src', 's1'): [_erratum('s1')]})
    sent = []
    why = 'The source has "the well was full".'
    result = _run(project_dir, tmp_path, _two(), sent=sent, source={
        'facts': [{'n': 2, 'verdict': 'contradicts', 'why': why}],
        'contradictions': [], 'findings': []})
    assert 'Known slips' not in sent[0]
    assert result.source_departs == [(SECOND, why)]


def test_a_departure_keeps_its_listing_until_it_is_gone_or_re_ruled(
        project_dir, tmp_path, adaptation):
    """#742's review (SF-1): the departing fact is committed, so it was never
    sent again; an edit that brought one new ruled fact cleared the scene's
    listing with the departure still in the prose."""
    import os
    departs = {'facts': [{'n': 2, 'verdict': 'contradicts', 'why': 'the well is full'}],
               'contradictions': [], 'findings': []}
    _run(project_dir, tmp_path, _two(), source=departs)
    assert SCENE in gate.source_fixes(project_dir)
    path = os.path.join(project_dir, 'scenes', f'{SCENE}.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text + '\n\nAn unrelated new line.\n')
    gate_source._MEMO.clear()
    sent = []
    new = _commitment(statement='The lamp was lit', quote=SECOND_QUOTE)
    _run(project_dir, tmp_path, _two() + [new], sent=sent, source={
        'facts': [{'n': 1, 'verdict': 'agrees', 'why': 'w'},
                  {'n': 2, 'verdict': 'contradicts', 'why': 'the well is full'},
                  {'n': 3, 'verdict': 'not-in-source', 'why': 'w'}],
        'contradictions': [], 'findings': []})
    assert SECOND in sent[0]   # sent again while listed
    assert SCENE in gate.source_fixes(project_dir)
    assert gate.source_fix_waits(project_dir, SCENE)   # waits on the author again
    # re-ruled with no departure: the listing comes off
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text + '\n\nAnother line.\n')
    gate_source._MEMO.clear()
    _run(project_dir, tmp_path, _two() + [new], source={
        'facts': [{'n': i, 'verdict': 'agrees', 'why': 'w'} for i in (1, 2, 3)],
        'contradictions': [], 'findings': []})
    assert SCENE not in gate.source_fixes(project_dir)


def test_without_errata_the_prompt_has_no_slips_section(project_dir, tmp_path, adaptation):
    sent = []
    _run(project_dir, tmp_path, _two(), sent=sent)
    assert 'Known slips' not in sent[0]


# ---- source.read_errata and the `errata` key -----------------------------

def _yaml(tmp_path, extra='', project_extra=''):
    (tmp_path / 'storyforge.yaml').write_text(
        'project:\n  title: T\nsource:\n  mode: faithful\n  projects:\n'
        f'    - slug: iliad\n      path: ../homer\n{project_extra}{extra}')
    return str(tmp_path)


def test_read_errata(tmp_path):
    from storyforge import source
    (tmp_path / 'errata.csv').write_text(
        'ref|source_scene|butler|homer|checked\n'
        '15.435|hector-fires-the-ships|prow|stern|Murray\n'
        '7.471|wine-ships|ten thousand measures|a thousand measures|Murray\n')
    project = _yaml(tmp_path, '  errata: errata.csv\n')
    cfg = source.read_config(project)
    got = source.read_errata(project, cfg)
    [e] = got[('iliad', 'hector-fires-the-ships')]
    assert (e.ref, e.has, e.original, e.has_label, e.original_label) == (
        '15.435', 'prow', 'stern', 'butler', 'homer')
    assert len(got) == 2


def test_a_projects_errata_overrides_the_blocks(tmp_path):
    from storyforge import source
    (tmp_path / 'mine.csv').write_text('ref|source_scene|text|original|checked\n'
                                       '1.1|s|a|b|\n')
    project = _yaml(tmp_path, '  errata: missing.csv\n', '      errata: mine.csv\n')
    assert list(source.read_errata(project, source.read_config(project))) == [('iliad', 's')]


@pytest.mark.parametrize('content,said', [
    (None, 'could not be read'),
    ('', 'is empty'),
    ('ref|scene|butler|homer|checked\n1|s|a|b|c\n', 'the header must be'),
    ('ref|source_scene|butler|homer|checked\n1|s|a|b\n', 'wrong number of cells'),
    ('ref|source_scene|butler|homer|checked\n1||a|b|c\n', 'needs a source_scene'),
])
def test_a_bad_errata_file_is_refused(tmp_path, content, said):
    from storyforge import source
    if content is not None:
        (tmp_path / 'errata.csv').write_text(content)
    project = _yaml(tmp_path, '  errata: errata.csv\n')
    with pytest.raises(source.SourceError, match=said):
        source.read_errata(project, source.read_config(project))


def test_setup_reads_the_errata_and_an_unreadable_file_skips_the_check(tmp_path, monkeypatch):
    from source_helpers import SNAPSHOT_FILES, _write, import_source, make_adaptation
    from storyforge import source
    project = make_adaptation(tmp_path)
    import_source(project)
    _write(project, SNAPSHOT_FILES)
    slips = {('odyssey', 'gods-debate'): [_erratum('gods-debate')]}
    monkeypatch.setattr(source, 'read_errata', lambda p, cfg: slips)
    assert gate_source.setup(project).errata == slips

    def bad(p, cfg):
        raise source.SourceError('source.errata: e.csv could not be read (gone)')
    monkeypatch.setattr(source, 'read_errata', bad)
    assert 'e.csv could not be read' in gate_source.setup(project).skip


def test_an_errata_row_naming_no_source_scene_is_said(tmp_path, monkeypatch):
    """#742's review (SF-4, CR-5): a mistyped source_scene was never sent,
    and nothing said so."""
    from source_helpers import SNAPSHOT_FILES, _write, import_source, make_adaptation
    from storyforge import source
    project = make_adaptation(tmp_path / 'book')
    import_source(project)
    _write(project, SNAPSHOT_FILES)
    monkeypatch.setattr(source, 'read_errata', lambda p, cfg: {
        ('odyssey', 'gods-debate'): [_erratum('gods-debate')],
        ('odyssey', 'gods-debat'): [_erratum('gods-debat')]})
    monkeypatch.setattr(source.SourceConfig, 'errata_path', lambda self, proj: 'e.csv')
    ctx = gate_source.setup(project)
    assert len(ctx.warnings) == 1 and "'gods-debat'" in ctx.warnings[0]
    assert 'e.csv' in ctx.warnings[0] and '7.471' in ctx.warnings[0]


def test_the_setups_warnings_are_said_on_every_run(project_dir, tmp_path, adaptation,
                                                    monkeypatch):
    said = 'e.csv: the known slip at 7.471 names source scene \'x\', which ...'
    monkeypatch.setattr(gate_source, 'setup', lambda p: gate_source.Setup(
        adaptation.refs, adaptation.rules, adaptation.map_rows, warnings=(said,)))
    assert said in _run(project_dir, tmp_path, _two()).source_notes


def test_no_errata_key_reads_nothing(tmp_path):
    from storyforge import source
    project = _yaml(tmp_path)
    assert source.read_errata(project, source.read_config(project)) == {}


class TestRulingReusedForFewerItems:
    """#736: the fix loop's re-check carries its facts, and its findings are
    the run before's or fewer; the memo was keyed on all three, so a
    re-check that passed (no findings) asked the source again about the
    same facts. A ruling made earlier in the process that covers every item
    is reused, cut to them; anything new is a call, sent as before."""

    def _finding(self, quote, why='w'):
        from storyforge.checker import Finding
        return Finding('contradiction', 'PHY', quote, '', '', '', why)

    def _review(self, project_dir, tmp_path, ctx, findings, facts=None, reply=None):
        sent = []

        def fake(path, body, **k):
            sent.append(body)
            return _text(reply or {'facts': [{'n': 1, 'verdict': 'contradicts',
                                              'why': 'the source says 300'}],
                                   'contradictions': [],
                                   'findings': [
                                       {'n': 1, 'verdict': 'source-has-it',
                                        'source_quote': 'words the source has not', 'why': 'a'},
                                       {'n': 2, 'verdict': 'source-has-it',
                                        'source_quote': 'the sword broke in his hand',
                                        'why': 'b'}]})
        with patch('storyforge.api._api_request', side_effect=fake):
            out = gate_source.review(project_dir, SCENE, 'prose', facts or [_commitment()], [],
                                     model='m', log_file=str(tmp_path / 'src.json'), ctx=ctx,
                                     findings=findings)
        return out, sent

    def test_fewer_findings_reuse_the_ruling_cut_to_them(self, project_dir, tmp_path,
                                                         adaptation):
        a, b = self._finding('She tapped the map'), self._finding('The sword broke')
        first, sent = self._review(project_dir, tmp_path, adaptation, [a, b])
        assert len(sent) == 1 and [i for i, _, _ in first.has_it] == [1]
        assert any('words the source has not' in n for n in first.notes)
        again, sent = self._review(project_dir, tmp_path, adaptation, [b])
        assert sent == []
        assert again.departs == first.departs and again.ruled == first.ruled
        assert again.has_it == [(0, 'the sword broke in his hand', 'b')]
        assert not any('words the source has not' in n for n in again.notes)
        passed, sent = self._review(project_dir, tmp_path, adaptation, [])
        assert sent == [] and passed.has_it == [] and passed.departs == first.departs

    def test_a_new_finding_or_other_facts_are_a_call(self, project_dir, tmp_path, adaptation):
        a, b = self._finding('She tapped the map'), self._finding('The sword broke')
        self._review(project_dir, tmp_path, adaptation, [a, b])
        _, sent = self._review(project_dir, tmp_path, adaptation,
                               [b, self._finding('The well ran dry')])
        assert len(sent) == 1
        _, sent = self._review(project_dir, tmp_path, adaptation, [b],
                               facts=[_commitment(statement='Other', quote='other words')])
        assert len(sent) == 1


def test_a_fix_away_from_every_quote_makes_no_source_call(project_dir, tmp_path, adaptation):
    """#736's acceptance, in a faithful adaptation: the re-check after a fix
    that left every quote alone makes no extraction, persistence or source
    call, and passes on the first run's facts and source ruling."""
    import os
    end, moved = 'She returned to the new map. Nothing.', 'She went back to the new map. Nothing.'
    calls = []

    def fake(path, body, **k):
        prompt = body['messages'][0]['content']
        prompt = prompt if isinstance(prompt, str) else ''.join(b.get('text', '') for b in prompt)
        if _is_persistence(body):
            calls.append('persistence')
            return _persistence_reply(body)
        if _is_source(body):
            calls.append('source')
            return _text({'facts': [{'n': 1, 'verdict': 'agrees', 'why': 'w'},
                                    {'n': 2, 'verdict': 'agrees', 'why': 'w'}],
                          'contradictions': [], 'findings': []})
        if 'tools' in body:
            calls.append('check')
            finding = {**_contradiction(), 'scene_quote': end}
            return _text({'findings': [finding] if end in prompt else [], 'kept': []})
        if 'edits' in json.dumps(body.get('output_config', {})):
            calls.append('fix')
            return _text({'edits': [{'problem': 1, 'find': end, 'replace': moved}]})
        calls.append('extract')
        return _text({'commitments': _two()})
    prose = open(os.path.join(project_dir, 'scenes', f'{SCENE}.md')).read()
    with patch('storyforge.api._api_request', side_effect=fake):
        out = gate.gate_and_fix(project_dir, SCENE, command='draft', prose=prose,
                                log_dir=str(tmp_path / 'logs'), extract_model='m',
                                check_model='m')
    assert out.fixed and out.result.passed, gate.report_lines(out.result)
    assert calls == ['extract', 'persistence', 'check', 'source', 'fix', 'check']
    assert out.result.source_ruled
