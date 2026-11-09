"""#631 and #632 (iliad-teen, 2026-11-08: $231 of the book's $271 went to the
gate, most of it re-checks of scenes whose prose never changed).

#631: a re-check re-ran the blocking read (BLK) on unchanged prose, which
worded the same slip otherwise and blocked again; the check path gave the
re-check no baseline, so a finding within the scene that revise reports as
already there blocked; an accept matched exact words only.

#632: accepting a finding held back facts kept from unchanged prose, which
counted as changed and re-listed their dependents; an `ends` link a
re-extraction dropped counted as a change; `ledger.dependents` listed every
scene with a fact about a character any changed fact named.

The API is mocked at `api._api_request`: a request with tools is the
checker, one whose schema asks for `verdicts` the persistence check, one
whose findings have `other_quote` the blocking read, any other extraction."""

import json
import os
import re
import subprocess
from unittest.mock import patch

import pytest

from storyforge import gate, ledger

EARLY, SCENE, LATER = 'act1-sc01', 'act1-sc02', 'act2-sc01'

DESK = 'Dorren sat at her desk with the overlay sheets spread across every surface'
CALIPERS = 'Dorren Hayle pressed the brass calipers against the vellum'
# two readings of one slip, both in the third paragraph of act1-sc02
MURMURED = 'It was here last quarter," she murmured, pulling the older survey'
LIVES = 'Four hundred and twelve people going about their lives'
TEMPLE = 'Roads, wells, the little temple marked with its standard sigil'
TAPPED = 'She tapped the empty space on the map'
NOTHING = 'She returned to the new map. Nothing.'


@pytest.fixture(autouse=True)
def _pure_prose_scenes(request):
    """Scene files are pure prose (the gate refuses frontmatter)."""
    if 'project_dir' not in request.fixturenames:
        return
    import glob
    for path in glob.glob(os.path.join(request.getfixturevalue('project_dir'), 'scenes', '*.md')):
        with open(path, encoding='utf-8') as f:
            text = f.read()
        stripped = re.sub(r'\A---\n.*?\n---\n\s*', '', text, flags=re.S)
        if stripped != text:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(stripped)


def _text(payload):
    return {'stop_reason': 'end_turn', 'model': 'claude-opus-5-5',
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 1, 'output_tokens': 1}}


def _schema(body):
    return (body.get('output_config') or {}).get('format', {}).get('schema', {})


def _is_blocking(body):
    items = _schema(body).get('properties', {}).get('findings', {}).get('items', {})
    return 'other_quote' in items.get('properties', {})


def _fact(quote, statement, subject='dorren-hayle', type_='physical', **over):
    c = {'type': type_, 'subject': subject, 'statement': statement, 'quote': quote,
         'mutable': 'state', 'supersedes': '', 'ends': []}
    c.update(over)
    return c


def _blk(scene_quote, other_quote, why='A hand cannot be in two places.'):
    return {'kind': 'contradiction', 'scene_quote': scene_quote, 'other_quote': other_quote,
            'explanation': why}


class Book:
    """The fake API for a run of gate calls: set what extraction, the check
    and the blocking read answer before each, and read what was asked."""

    def __init__(self):
        self.facts, self.findings, self.blocking = [], [], []
        self.blocking_calls = []

    def __call__(self, path, body, **k):
        if 'verdicts' in _schema(body).get('properties', {}):
            prompt = body['messages'][0]['content']
            items = re.findall(r'^(\d+)\. ', prompt, re.M)
            return _text({'verdicts': [{'n': int(n), 'persists': True, 'why': 'w'}
                                       for n in items]})
        if 'tools' in body:
            reply = {'findings': list(self.findings), 'kept': []}
            if 'cleared' in _schema(body)['properties']:
                reply['cleared'] = []
            return _text(reply)
        if _is_blocking(body):
            self.blocking_calls.append(body)
            return _text({'findings': list(self.blocking)})
        return _text({'commitments': list(self.facts)})

    def gate(self, project_dir, tmp_path, scene, command='draft', **kw):
        with patch('storyforge.api._api_request', side_effect=self):
            return gate.gate_scene(project_dir, scene, command=command,
                                   log_dir=str(tmp_path / 'logs' / scene), extract_model='m',
                                   check_model='m', **kw)

    def unchanged(self, project_dir, tmp_path, scene, command):
        with patch('storyforge.api._api_request', side_effect=self):
            result, _ = gate.gate_unchanged(project_dir, scene, command=command,
                                            log_dir=str(tmp_path / 'logs' / scene),
                                            extract_model='m', check_model='m',
                                            introduced_by='draft')
        return result

    def recheck(self, project_dir, tmp_path):
        with patch('storyforge.api._api_request', side_effect=self):
            return gate.recheck_pending(project_dir, log_dir=str(tmp_path / 'rc'),
                                        extract_model='m', check_model='m')


def _git(project_dir):
    subprocess.run(['git', 'init', '-q', project_dir], check=True)


def _read(project_dir, scene):
    with open(os.path.join(project_dir, 'scenes', f'{scene}.md'), encoding='utf-8') as f:
        return f.read()


def _mine(project_dir, scene):
    return [r for r in ledger.load(project_dir)
            if r['scene_id'] == scene and ledger.is_commitment(r)]


def _add_later(project_dir, **row):
    rows = ledger.load(project_dir)
    base = dict(rows[0], **{k: '' for k in rows[0]})
    base.update(status='binding', origin='prose', mutable='state', introduced_by='draft',
                scene_id=LATER, type='physical', subject='dorren-hayle')
    base.update(row)
    ledger.save(project_dir, rows + [base], command='test')


# ============================================================================
# #631: accepted blocking findings stick on a re-check of unchanged prose
# ============================================================================

@pytest.mark.blocking_read
class TestAcceptedBlockingSticks:

    def _accepted_and_passed(self, project_dir, tmp_path, book):
        """act1-sc01 committed; act1-sc02 stopped by a blocking slip, the
        author accepts it, and `check --pending` passes it on a new reading
        of the same paragraph."""
        _git(project_dir)
        book.facts = [_fact(CALIPERS, 'Dorren holds brass calipers')]
        assert book.gate(project_dir, tmp_path, EARLY).committed
        book.facts = [_fact(DESK, 'Dorren is at her desk')]
        book.blocking = [_blk(MURMURED, LIVES)]
        first = book.gate(project_dir, tmp_path, SCENE)
        assert not first.passed and [f.code for f in first.findings] == ['BLK']
        rows = gate.accept_blocked(project_dir, SCENE)
        assert rows and rows[0]['paragraphs']   # where the slip lies, for the accept
        # the next blocking read words it otherwise, in the same paragraph
        book.blocking = [_blk(TEMPLE, MURMURED, 'The survey is in two places.')]
        again = book.unchanged(project_dir, tmp_path, SCENE, 'advisor')
        assert again.passed and again.committed
        assert [f.scene_quote for f in again.inherited] == [TEMPLE]
        return again

    def test_a_recheck_of_unchanged_prose_skips_the_blocking_read_and_passes(
            self, project_dir, tmp_path):
        """#631's acceptance: accept, change an earlier scene's facts so the
        accepted scene is re-checked, and the re-check passes on a blocking
        read that would word the slip otherwise; none is made."""
        book = Book()
        self._accepted_and_passed(project_dir, tmp_path, book)
        # act1-sc01 is redrafted: its Dorren fact changes, act1-sc02 depends on it
        prose = _read(project_dir, EARLY).replace('brass calipers', 'steel dividers')
        book.facts = [_fact(CALIPERS.replace('brass calipers', 'steel dividers'),
                            'Dorren holds steel dividers')]
        book.blocking = []
        redraft = book.gate(project_dir, tmp_path, EARLY, command='redraft', prose=prose)
        assert redraft.committed and redraft.recheck == [SCENE]
        assert gate.pending(project_dir)[SCENE]['command'] == gate.RECHECK
        book.facts = [_fact(DESK, 'Dorren sits at her desk')]
        book.blocking = [_blk(LIVES, TEMPLE, 'yet another wording')]
        book.blocking_calls.clear()
        run = book.recheck(project_dir, tmp_path)
        assert run.passed == [SCENE] and not run.failed
        assert book.blocking_calls == []   # no blocking read on unchanged prose
        assert gate.pending(project_dir) == {}

    def test_the_skip_is_said_and_the_reported_blocking_findings_kept(
            self, project_dir, tmp_path):
        book = Book()
        self._accepted_and_passed(project_dir, tmp_path, book)
        before = gate.reported(project_dir)[SCENE]
        gate.mark_pending(project_dir, SCENE, gate.RECHECK, 're-check: x')
        book.blocking_calls.clear()
        result = book.unchanged(project_dir, tmp_path, SCENE, 'recheck')
        assert result.passed and result.blocking_skipped and book.blocking_calls == []
        assert any(line.startswith('NOTE (re-check): blocking read skipped')
                   for line in gate.report_lines(result))
        # the reported (inherited) reading isn't lost because none was made
        assert [r['quote'] for r in gate.reported(project_dir)[SCENE]] == [
            r['quote'] for r in before]

    def test_a_recheck_of_changed_prose_reads_the_blocking(self, project_dir, tmp_path):
        book = Book()
        self._accepted_and_passed(project_dir, tmp_path, book)
        path = os.path.join(project_dir, 'scenes', f'{SCENE}.md')
        with open(path, 'a', encoding='utf-8') as f:
            f.write('\nShe rolled the maps away.\n')
        book.blocking, book.blocking_calls = [], []
        result = book.unchanged(project_dir, tmp_path, SCENE, 'recheck')
        assert len(book.blocking_calls) == 2   # BLOCKING_READINGS
        assert result.blocking_note == 'blocking read run: its prose changed since its last gate'

    def test_a_scene_gated_before_the_blocking_read_gets_one(self, project_dir, tmp_path):
        """A scene committed with no blocking read (before #626) is read once."""
        _git(project_dir)
        book = Book()
        book.facts = [_fact(DESK, 'Dorren is at her desk')]
        with patch.object(gate, 'GATE_BLOCKING', False):
            assert book.gate(project_dir, tmp_path, SCENE).committed
        assert gate.blocking_read_before(project_dir, SCENE, _read(project_dir, SCENE)) == (
            False, 'its last gate had no blocking read (gated before it existed)')
        first = book.unchanged(project_dir, tmp_path, SCENE, 'recheck')
        assert len(book.blocking_calls) == 2 and first.committed
        assert 'gated before it existed' in first.blocking_note
        book.blocking_calls.clear()
        second = book.unchanged(project_dir, tmp_path, SCENE, 'recheck')
        assert book.blocking_calls == [] and second.blocking_skipped

    def test_advisor_mode_always_reads_the_blocking(self, project_dir, tmp_path):
        book = Book()
        self._accepted_and_passed(project_dir, tmp_path, book)
        book.blocking, book.blocking_calls = [], []
        result = book.unchanged(project_dir, tmp_path, SCENE, 'advisor')
        assert len(book.blocking_calls) == 2 and not result.blocking_skipped
        assert result.blocking_note == ''

    def test_an_accept_does_not_cover_a_reading_in_another_paragraph(
            self, project_dir, tmp_path):
        book = Book()
        _git(project_dir)
        book.facts = [_fact(DESK, 'Dorren is at her desk')]
        book.blocking = [_blk(MURMURED, LIVES)]
        book.gate(project_dir, tmp_path, SCENE)
        gate.accept_blocked(project_dir, SCENE)
        book.blocking = [_blk(TAPPED, MURMURED)]   # one side in the second paragraph
        result = book.unchanged(project_dir, tmp_path, SCENE, 'advisor')
        assert not result.passed and [f.scene_quote for f in result.findings] == [TAPPED]

    def test_an_accept_does_not_cover_its_paragraph_once_changed(self, project_dir, tmp_path):
        book = Book()
        _git(project_dir)
        book.facts = [_fact(DESK, 'Dorren is at her desk')]
        book.blocking = [_blk(MURMURED, LIVES)]
        book.gate(project_dir, tmp_path, SCENE)
        gate.accept_blocked(project_dir, SCENE)
        path = os.path.join(project_dir, 'scenes', f'{SCENE}.md')
        text = _read(project_dir, SCENE).replace('Roads, wells,', 'Roads, two wells,')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        book.blocking = [_blk(LIVES, MURMURED, 'reworded')]
        result = book.unchanged(project_dir, tmp_path, SCENE, 'advisor')
        assert not result.passed and [f.code for f in result.findings] == ['BLK']


# ============================================================================
# #631: the check path's re-check has the scene's own gated prose as baseline
# ============================================================================

def _within(scene_quote, other):
    """A checker finding set against the scene itself."""
    return {'kind': 'contradiction', 'code': 'PHY', 'scene_quote': scene_quote,
            'established_scene': SCENE, 'fact_id': '', 'explanation': 'why',
            'established_quote': other}


class TestRecheckBaseline:
    def _committed(self, project_dir, tmp_path):
        _git(project_dir)
        book = Book()
        book.facts = [_fact(CALIPERS, 'Dorren holds brass calipers')]
        book.gate(project_dir, tmp_path, EARLY)
        book.facts = [_fact(DESK, 'Dorren is at her desk')]
        assert book.gate(project_dir, tmp_path, SCENE).committed
        gate.mark_pending(project_dir, SCENE, gate.RECHECK, 're-check: x')
        return book

    def test_a_finding_within_unchanged_prose_is_inherited(self, project_dir, tmp_path):
        book = self._committed(project_dir, tmp_path)
        book.findings = [_within(TAPPED, DESK)]
        result = book.unchanged(project_dir, tmp_path, SCENE, 'recheck')
        assert result.passed and [f.scene_quote for f in result.inherited] == [TAPPED]

    def test_a_finding_against_an_earlier_scene_still_blocks(self, project_dir, tmp_path):
        """#631's second acceptance (and #480's review): a re-check runs
        because another scene changed; a contradiction with it blocks."""
        book = self._committed(project_dir, tmp_path)
        book.findings = [{'kind': 'contradiction', 'code': 'PHY', 'scene_quote': DESK,
                          'established_scene': EARLY, 'fact_id': '', 'explanation': 'why',
                          'established_quote': CALIPERS}]
        result = book.unchanged(project_dir, tmp_path, SCENE, 'recheck')
        assert not result.passed and result.inherited == []

    def test_a_finding_within_words_new_since_the_gate_blocks(self, project_dir, tmp_path):
        book = self._committed(project_dir, tmp_path)
        path = os.path.join(project_dir, 'scenes', f'{SCENE}.md')
        with open(path, 'a', encoding='utf-8') as f:
            f.write('\nShe had never sat at that desk.\n')
        book.findings = [_within('She had never sat at that desk', DESK)]
        result = book.unchanged(project_dir, tmp_path, SCENE, 'recheck')
        assert not result.passed and result.inherited == []

    def test_the_baseline_holds_the_scene_alone(self, project_dir, tmp_path):
        self._committed(project_dir, tmp_path)
        snap = gate.own_snapshot(project_dir, SCENE)
        assert list(snap.scenes) == [SCENE] and snap.files == {}
        assert snap.scenes[SCENE] == _read(project_dir, SCENE)

    def test_no_gated_prose_no_baseline(self, project_dir):
        assert gate.own_snapshot(project_dir, SCENE) is None


# ============================================================================
# #632: an accept never changes the ledger; steady ends; why a scene is listed
# ============================================================================

class TestAcceptKeepsSteadyFacts:
    def test_an_accepted_finding_on_unchanged_prose_changes_nothing(self, project_dir,
                                                                     tmp_path):
        """#632's acceptance: accept a finding on a scene with unchanged
        prose; the next `--pending` commits the scene with no changed facts
        and lists no dependents."""
        _git(project_dir)
        book = Book()
        book.facts = [_fact(CALIPERS, 'Dorren holds brass calipers')]
        book.gate(project_dir, tmp_path, EARLY)
        book.facts = [_fact(DESK, 'Dorren is at her desk'),
                      _fact(TEMPLE, 'The old survey shows a temple', subject='tarrens-hollow',
                            type_='world', mutable='fixed')]
        assert book.gate(project_dir, tmp_path, SCENE).committed
        _add_later(project_dir, id='later-dorren', statement='Dorren stands at the window')
        before = {r['id']: r for r in _mine(project_dir, SCENE)}
        gate.mark_pending(project_dir, SCENE, gate.RECHECK, 're-check: x')
        contradiction = {'kind': 'contradiction', 'code': 'PHY', 'scene_quote': DESK,
                         'established_scene': EARLY, 'fact_id': '', 'explanation': 'why',
                         'established_quote': CALIPERS}
        book.findings = [contradiction]
        failed = book.unchanged(project_dir, tmp_path, SCENE, 'recheck')
        assert not failed.passed
        gate.accept_blocked(project_dir, SCENE)
        book.facts = [_fact(DESK, 'Dorren is seated at her desk'),   # reworded
                      _fact(TEMPLE, 'The old survey marks a temple', subject='tarrens-hollow',
                            type_='world', mutable='fixed')]
        result = book.unchanged(project_dir, tmp_path, SCENE, 'recheck')
        assert result.passed and result.committed
        assert result.changed == [] and result.recheck == []
        assert result.held_back == []
        assert [st for st, _ in result.kept_stating] == ['Dorren is at her desk']
        assert any(line.startswith('NOTE (kept as it was, from unchanged prose')
                   for line in gate.report_lines(result))
        assert {r['id']: r for r in _mine(project_dir, SCENE)} == before
        assert LATER not in gate.pending(project_dir)


class TestSteadyEnds:
    def _ended(self, project_dir, tmp_path):
        _git(project_dir)
        rows = ledger.load(project_dir)
        base = dict(rows[0], **{k: '' for k in rows[0]})
        base.update(id='dorren-holds-calipers', scene_id=EARLY, type='physical',
                    subject='dorren-hayle', statement='Dorren holds the calipers',
                    status='binding', origin='prose', mutable='state', introduced_by='draft')
        ledger.save(project_dir, rows + [base], command='test')
        _add_later(project_dir, id='later-dorren', statement='Dorren stands at the window')
        book = Book()
        book.facts = [_fact(DESK, 'Dorren is at her desk', ends=['dorren-holds-calipers'])]
        assert book.gate(project_dir, tmp_path, SCENE).committed
        assert ledger.ended_by(ledger.load(project_dir), SCENE) == {'dorren-holds-calipers'}
        return book

    def test_a_rewording_that_re_adds_the_same_end_lists_nothing(self, project_dir,
                                                                  tmp_path):
        """#632's acceptance: rewords facts and re-adds the same `ends` link
        on unchanged paragraphs; no dependents."""
        book = self._ended(project_dir, tmp_path)
        book.facts = [_fact(DESK, 'Dorren is seated at her desk',
                            ends=['dorren-holds-calipers'])]
        result = book.unchanged(project_dir, tmp_path, SCENE, 'recheck')
        assert result.committed and result.changed == [] and result.recheck == []

    def test_an_end_the_new_reading_drops_is_kept(self, project_dir, tmp_path):
        book = self._ended(project_dir, tmp_path)
        book.facts = [_fact(DESK, 'Dorren is seated at her desk')]
        result = book.unchanged(project_dir, tmp_path, SCENE, 'recheck')
        assert result.committed and result.changed == [] and result.recheck == []
        assert ledger.ended_by(ledger.load(project_dir), SCENE) == {'dorren-holds-calipers'}
        assert any('kept its end of dorren-holds-calipers' in n for n in result.prose_notes)

    def test_a_new_end_on_unchanged_prose_is_not_applied(self, project_dir, tmp_path):
        _git(project_dir)
        rows = ledger.load(project_dir)
        base = dict(rows[0], **{k: '' for k in rows[0]})
        base.update(id='dorren-holds-calipers', scene_id=EARLY, type='physical',
                    subject='dorren-hayle', statement='Dorren holds the calipers',
                    status='binding', origin='prose', mutable='state', introduced_by='draft')
        ledger.save(project_dir, rows + [base], command='test')
        _add_later(project_dir, id='later-dorren', statement='Dorren stands at the window')
        book = Book()
        book.facts = [_fact(DESK, 'Dorren is at her desk')]
        assert book.gate(project_dir, tmp_path, SCENE).committed
        book.facts = [_fact(DESK, 'Dorren is at her desk', ends=['dorren-holds-calipers'])]
        result = book.unchanged(project_dir, tmp_path, SCENE, 'recheck')
        assert result.committed and result.changed == [] and result.recheck == []
        assert ledger.ended_by(ledger.load(project_dir), SCENE) == set()

    def test_on_changed_prose_a_dropped_end_is_a_change(self, project_dir, tmp_path):
        book = self._ended(project_dir, tmp_path)
        prose = _read(project_dir, SCENE) + '\nShe rolled the maps away.\n'
        book.facts = [_fact(DESK, 'Dorren is at her desk')]
        result = book.gate(project_dir, tmp_path, SCENE, command='redraft', prose=prose)
        assert 'dorren-holds-calipers' in result.changed and result.recheck == [LATER]


class TestSteadyAcrossParagraphs:
    def test_a_fact_quoted_across_unchanged_paragraphs_is_steady(self):
        earlier = 'One two three four.\n\nFive six seven eight.\n\nNine ten.'
        prose = earlier + '\n\nEleven twelve.'
        row = {'id': 'x', 'quote': 'three four. Five six'}
        assert gate.steady_facts([row], earlier, prose) == {'x': 0}

    def test_across_a_changed_paragraph_it_is_not(self):
        earlier = 'One two three four.\n\nFive six seven eight.'
        prose = 'One two three four.\n\nFive six seven nine.'
        row = {'id': 'x', 'quote': 'three four. Five six'}
        assert gate.steady_facts([row], earlier, prose) == {}


class TestWhyListed:
    def test_the_pending_reason_and_result_name_the_fact_and_rule(self, project_dir,
                                                                  tmp_path):
        _git(project_dir)
        book = Book()
        book.facts = [_fact(DESK, 'Dorren is at her desk')]
        assert book.gate(project_dir, tmp_path, SCENE).committed
        _add_later(project_dir, id='later-dorren', statement='Dorren stands at the window')
        old = _mine(project_dir, SCENE)[0]['id']
        prose = _read(project_dir, SCENE).replace('Dorren sat at', 'Dorren stood at')
        book.facts = [_fact(DESK.replace('sat', 'stood'), 'Dorren stands at her desk')]
        result = book.gate(project_dir, tmp_path, SCENE, command='redraft', prose=prose)
        assert result.recheck == [LATER]
        assert result.recheck_why == {LATER: f'{old} (same subject: dorren-hayle)'}
        assert f'({old} (same subject: dorren-hayle))' in gate.pending(project_dir)[LATER][
            'reason']


class TestGateNarrowsOnlyWhatTheProseChanged:
    """The gate lists a changed fact's dependents by the narrower rule; a
    rejected fact's revision keeps the wide rule, which `audit --mark
    rejected` told the author it would list."""
    CENSUS = 'population four hundred and twelve at last census'

    def _hollow(self, project_dir, tmp_path):
        _git(project_dir)
        book = Book()
        book.facts = [_fact(self.CENSUS, "Tarren's Hollow had 412 people",
                            subject='tarrens-hollow', type_='world')]
        assert book.gate(project_dir, tmp_path, SCENE).committed
        # a later fact of another subject, of another type, naming the hollow
        _add_later(project_dir, id='later-tessa', subject='tessa-merrin',
                   statement='Tessa walks the road to Tarrens Hollow')
        book.facts = [_fact(self.CENSUS, "Tarren's Hollow had 300 people",
                            subject='tarrens-hollow', type_='world')]
        return book

    def test_a_changed_fact_does_not_list_a_physical_mention(self, project_dir, tmp_path):
        book = self._hollow(project_dir, tmp_path)
        # the census's paragraph changes, so its fact is read anew
        prose = _read(project_dir, SCENE).replace('sat at her desk', 'sat at the desk')
        result = book.gate(project_dir, tmp_path, SCENE, command='redraft', prose=prose)
        assert result.committed and result.changed and result.recheck == []

    def test_a_rejected_facts_revision_still_does(self, project_dir, tmp_path):
        book = self._hollow(project_dir, tmp_path)
        rows = ledger.load(project_dir)
        mine = next(r for r in rows if r['scene_id'] == SCENE and ledger.is_commitment(r))
        mine['status'] = 'rejected'
        ledger.save(project_dir, rows, command='test')
        gate.mark_pending(project_dir, SCENE, gate.REVISE_REJECTED,
                          f'x [rejected: {mine["id"]}]')
        prose = _read(project_dir, SCENE).replace('sat at her desk', 'sat at the desk')
        result = book.gate(project_dir, tmp_path, SCENE, command='redraft', prose=prose)
        assert result.committed and result.recheck == [LATER]
        assert result.recheck_why[LATER] == f'{mine["id"]} (later-tessa names tarrens hollow)'


def test_report_changes_says_why_each_scene_was_listed(capsys):
    from storyforge.cmd_write import report_changes
    result = gate.GateResult(SCENE, recheck=[LATER],
                             recheck_why={LATER: 'f-1 (same subject: dorren-hayle)'})
    report_changes(result)
    assert (f'NOTE: {LATER} listed for a re-check: {SCENE} changed f-1 (same subject: '
            f'dorren-hayle)') in capsys.readouterr().out


# ============================================================================
# #632: the gate's narrower dependents
# ============================================================================

ORDER = {'s1': 0, 's2': 1, 's3': 2, 's4': 3, 's5': 4}


def _row(rid, scene, subject, type_='physical', statement='x', **kw):
    r = {'id': rid, 'scene_id': scene, 'subject': subject, 'type': type_,
         'statement': statement, 'status': 'binding', 'supersedes': '', 'depends_on': '',
         'resolves': '', 'mutable': 'state'}
    r.update(kw)
    return r


class TestNarrowDependents:
    NAMES = {'achilles': {'achilles'}, 'thersites': {'thersites'}}

    def _book(self):
        """A main character with a fact in every scene; a minor one in two."""
        rows = [_row(f'a{n}', f's{n}', 'achilles', statement=f'Achilles stands at post {n}')
                for n in range(1, 6)]
        rows += [_row('t1', 's1', 'thersites', statement='Thersites mocks Achilles'),
                 _row('t4', 's4', 'thersites', statement='Thersites nurses a bruise')]
        return rows

    def test_a_minor_characters_reworded_fact_lists_only_his_scenes(self):
        """#632's acceptance: with a main character in every scene, one
        reworded fact about a minor character re-lists only his scenes."""
        found = ledger.dependents(self._book(), ['t1'], ORDER, names=self.NAMES, narrow=True)
        assert found.scenes == ['s4']
        assert found.why == {'s4': 't1 (same subject: thersites)'}
        # the wide rule (a rejection's) reaches every Achilles scene
        wide = ledger.dependents(self._book(), ['t1'], ORDER, names=self.NAMES)
        assert wide.scenes == ['s2', 's3', 's4', 's5']

    def test_a_knowledge_fact_naming_the_subject_still_depends(self):
        rows = self._book() + [_row('k3', 's3', 'nestor', type_='knowledge',
                                    statement='Nestor heard what Thersites said')]
        found = ledger.dependents(rows, ['t1'], ORDER, names=self.NAMES, narrow=True)
        assert found.scenes == ['s3', 's4']
        assert found.why['s3'] == 't1 (k3 names thersites)'

    def test_a_relationship_fact_naming_the_subject_still_depends(self):
        """The re-check-set eval's one hit for shared-dark's Madison fact is a
        relationship naming her ("Ostrowski has daughters Brianna and
        Madison"); with mentions in knowledge facts alone, recall fell."""
        rows = self._book() + [_row('r5', 's5', 'odysseus', type_='relationship',
                                    statement='Odysseus beat Thersites with the staff')]
        found = ledger.dependents(rows, ['t1'], ORDER, names=self.NAMES, narrow=True)
        assert found.scenes == ['s4', 's5']

    def test_a_physical_fact_naming_the_subject_does_not(self):
        rows = self._book() + [_row('p3', 's3', 'nestor',
                                    statement='Nestor stands beside Thersites')]
        found = ledger.dependents(rows, ['t1'], ORDER, names=self.NAMES, narrow=True)
        assert found.scenes == ['s4']

    def test_an_incompatible_type_of_the_same_subject_does_not(self):
        rows = [_row('f', 's1', 'hank', type_='physical'),
                _row('b', 's2', 'hank', type_='trait'),
                _row('c', 's3', 'hank', type_='timeline'),
                _row('d', 's4', 'hank', type_='knowledge')]
        found = ledger.dependents(rows, ['f'], ORDER, names={}, narrow=True)
        assert found.scenes == ['s3', 's4']

    def test_a_fixed_fact_reaches_every_type_of_its_subject(self):
        rows = [_row('f', 's1', 'hank', type_='trait', mutable='fixed'),
                _row('b', 's2', 'hank', type_='physical')]
        assert ledger.dependents(rows, ['f'], ORDER, names={}, narrow=True).scenes == ['s2']

    def test_links_ends_and_no_subject_are_kept(self):
        rows = [_row('f', 's1', 'hank', resolves='s5'),
                _row('a', 's2', 'zed', type_='trait', depends_on='f'),
                _row('g', 's1', '', type_='world'), _row('w', 's3', 'zed', type_='world')]
        found = ledger.dependents(rows, ['f', 'g'], ORDER, names={}, narrow=True)
        assert found.scenes == ['s2', 's3', 's5']
        assert found.why == {'s5': 'f (it ends it)', 's2': 'f (a links to it)',
                             's3': 'g (no subject, same type: world)'}

    def test_without_the_guess_a_subjectless_fact_keeps_links_and_mentions(self):
        """#641's review, TD-2 (`GateBlockers` weighing briefs' facts): no
        type guess, but a link and its statement naming a subject still count."""
        rows = [_row('g', 's1', '', type_='knowledge', statement='Zed saw the map'),
                _row('w', 's2', 'yan', type_='knowledge'),
                _row('z', 's3', 'zed', type_='physical'),
                _row('l', 's4', 'yan', type_='knowledge', depends_on='g')]
        found = ledger.dependents(rows, ['g'], ORDER, names={}, guess=False)
        assert found.scenes == ['s3', 's4']
        assert 'only its links' in found.unrelated['g']
        assert ledger.dependents(rows, ['g'], ORDER, names={}).scenes == ['s2', 's3', 's4']
