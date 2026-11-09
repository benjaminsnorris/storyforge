"""Tests for storyforge.gate: extract → halt → check → commit for one scene.
The API is mocked at `api._api_request`: a request with tools is the
checker, one whose schema asks for `verdicts` the persistence check, any
other extraction."""

import copy
import json
import os
from unittest.mock import patch

import pytest

from storyforge import gate, ledger
from storyforge.gate import GateError, gate_scene

SCENE = 'act1-sc02'
HERE = 'population four hundred and twelve at last census'



@pytest.fixture(autouse=True)
def _pure_prose_scenes(request):
    """Scene files are pure prose (the gate refuses frontmatter); the shared
    fixture's older scenes still carry it."""
    if 'project_dir' not in request.fixturenames:
        return
    import glob
    import re as _re
    for path in glob.glob(os.path.join(request.getfixturevalue('project_dir'), 'scenes', '*.md')):
        with open(path, encoding='utf-8') as f:
            text = f.read()
        stripped = _re.sub(r'\A---\n.*?\n---\n\s*', '', text, flags=_re.S)
        if stripped != text:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(stripped)

def _text(payload, stop='end_turn'):
    return {'stop_reason': stop, 'model': 'claude-opus-5-5',
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 1, 'output_tokens': 1}}


def _commitment(**over):
    c = {'type': 'world', 'subject': '', 'statement': "Tarren's Hollow had 412 people",
         'quote': HERE, 'mutable': 'fixed', 'supersedes': '', 'ends': []}
    c.update(over)
    return c


def _contradiction():
    return {'kind': 'contradiction', 'code': 'TIM', 'scene_quote': HERE,
            'established_scene': 'act1-sc01', 'fact_id': '', 'explanation': 'why',
            'established_quote': 'Dorren Hayle pressed the brass calipers against the vellum'}


def _persistence_reply(body, drop=()):
    """The persistence check's answer: every numbered fact lasts, except the
    statements in `drop`."""
    import re
    prompt = body['messages'][0]['content']
    items = re.findall(r'^(\d+)\. \[[^\]]*\] [^:]*: (.*?)(?: — "|$)', prompt, re.M)
    return _text({'verdicts': [{'n': int(n), 'persists': st not in drop, 'why': 'w'}
                               for n, st in items]})


def _is_persistence(body):
    schema = (body.get('output_config') or {}).get('format', {}).get('schema', {})
    return 'verdicts' in schema.get('properties', {})


def _with_persistence(fake, drop=()):
    """`fake`, with the persistence check answered first (every fact lasts,
    except the statements in `drop`)."""
    def route(path, body, **k):
        if _is_persistence(body):
            return _persistence_reply(body, drop)
        return fake(path, body, **k)
    return route


def _gate(project_dir, tmp_path, commitments=(), findings=(), kept=(), cleared=None,
          drop=(), **kw):
    """`cleared`: the disputes the check clears; None clears every one it
    is asked about (a request with disputes asks for `cleared`). `drop`:
    statements the persistence check says don't last."""
    def fake(path, body, **k):
        if 'tools' in body:
            reply = {'findings': list(findings), 'kept': list(kept)}
            schema = body['output_config']['format']['schema']
            if 'cleared' in schema['properties']:
                prompt = body['messages'][0]['content']
                asked = [line.split(':')[0][2:] for line in prompt.split(
                    'may change\n\n')[1].split('\n\n')[1].split('\n') if line.startswith('- ')]
                reply['cleared'] = asked if cleared is None else list(cleared)
            return _text(reply)
        return _text({'commitments': list(commitments)})
    with patch('storyforge.api._api_request', side_effect=_with_persistence(fake, drop)):
        return gate_scene(project_dir, SCENE, command=kw.pop('command', 'draft'),
                          log_dir=str(tmp_path / 'logs'), extract_model='m',
                          check_model='m', **kw)


class TestCommit:
    def test_a_clean_scene_commits_its_commitments(self, project_dir, tmp_path):
        result = _gate(project_dir, tmp_path, [_commitment()])
        assert result.passed and result.committed
        rows = ledger.load(project_dir)
        mine = [r for r in rows if r['scene_id'] == SCENE and ledger.is_commitment(r)]
        assert [(r['introduced_by'], r['quote']) for r in mine] == [('draft', HERE)]

    def test_a_redraft_replaces_the_scenes_earlier_commitments(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment()])
        _gate(project_dir, tmp_path, [_commitment(statement='Hollow is gone')],
              command='redraft')
        mine = [r for r in ledger.load(project_dir)
                if r['scene_id'] == SCENE and ledger.is_commitment(r)]
        assert [(r['statement'], r['introduced_by']) for r in mine] == [
            ('Hollow is gone', 'redraft')]

    def test_a_kept_promise_fills_the_registry_quote(self, project_dir, tmp_path):
        result = _gate(project_dir, tmp_path,
                       kept=[{'fact_id': 'village-vanished', 'quote': HERE}])
        assert result.quotes_filled == ['village-vanished']
        row = next(r for r in ledger.load(project_dir) if r['id'] == 'village-vanished')
        assert row['quote'] == HERE

    def test_the_audit_log_names_the_command(self, project_dir, tmp_path):
        from storyforge import audit
        _gate(project_dir, tmp_path, [_commitment()], command='revise')
        assert any(e['command'] == 'revise' for e in audit.read_log(project_dir))


class TestNothingWrittenUnlessClean:
    def _unchanged(self, project_dir, before):
        assert ledger.load(project_dir) == before

    def test_a_finding_blocks_the_commit(self, project_dir, tmp_path):
        before = ledger.load(project_dir)
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()])
        assert not result.passed and not result.committed
        assert [f.code for f in result.findings] == ['TIM']
        self._unchanged(project_dir, before)

    def test_superseding_a_fixed_commitment_halts(self, project_dir, tmp_path):
        rows = ledger.load(project_dir)
        rows.append(dict({c: '' for c in ledger.COLUMNS}, id='eyes', type='trait',
                         statement='Her eyes are grey', origin='prose', status='binding',
                         mutable='fixed', introduced_by='draft', scene_id='act1-sc01'))
        ledger.save(project_dir, rows, command='test')
        before = ledger.load(project_dir)
        result = _gate(project_dir, tmp_path, [_commitment(supersedes='eyes')])
        assert [h.kind for h in result.halts] == ['supersedes-fixed']
        self._unchanged(project_dir, before)

    @pytest.mark.parametrize('recorded_here', [False, True])
    def test_extraction_superseding_a_registry_fact_goes_to_the_checker(
            self, project_dir, tmp_path, recorded_here):
        """Ben, 2026-10-30 (E4 run 2): extraction marks added detail as
        superseding a registry fact, which stopped write at 8 of 23 scenes.
        The link isn't applied; the checker rules on it (#450 review)."""
        rows = ledger.load(project_dir)
        target = next(r for r in rows if not ledger.is_commitment(r))
        if recorded_here:
            target['scene_id'] = SCENE
            ledger.save(project_dir, rows, command='test')
        result = _gate(project_dir, tmp_path, [_commitment(supersedes=target['id'])])
        assert result.halts == [] and result.committed
        assert [d.fact_id for d in result.check.cleared] == [target['id']]
        assert result.proposed[0]['supersedes'] == ''
        assert any(target['id'] in line and target['statement'] in line
                   for line in gate.report_lines(result) if line.startswith('NOTE (plan fact'))

    def test_a_dispute_the_checker_gives_no_ruling_on_blocks(self, project_dir, tmp_path):
        rows = ledger.load(project_dir)
        target = next(r for r in rows if not ledger.is_commitment(r))
        before = ledger.load(project_dir)
        result = _gate(project_dir, tmp_path, [_commitment(supersedes=target['id'])], cleared=[])
        assert [d.fact_id for d in result.unruled] == [target['id']]
        assert not result.passed and ledger.load(project_dir) == before
        assert any(line.startswith('UNRULED') for line in gate.report_lines(result))
        assert gate.problems_to_fix(result)[0].startswith('UNVERIFIED (extraction thinks')

    def test_a_dispute_ruled_a_contradiction_is_a_finding(self, project_dir, tmp_path):
        rows = ledger.load(project_dir)
        target = next(r for r in rows if not ledger.is_commitment(r))
        finding = dict(_contradiction(), established_scene='', fact_id=target['id'],
                       established_quote=target['statement'])
        result = _gate(project_dir, tmp_path, [_commitment(supersedes=target['id'])],
                       findings=[finding], cleared=[])
        assert result.unruled == [] and len(result.findings) == 1 and not result.passed

    def test_a_checker_finding_against_a_registry_fact_still_blocks(self, project_dir, tmp_path):
        rows = ledger.load(project_dir)
        reg = next(r for r in rows if not ledger.is_commitment(r))
        finding = dict(_contradiction(), established_scene='', fact_id=reg['id'],
                       established_quote=reg['statement'])
        before = ledger.load(project_dir)
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[finding])
        assert not result.passed and ledger.load(project_dir) == before


class TestEnds:
    def _state(self, project_dir, rid, writer):
        rows = ledger.load(project_dir)
        rows.append(dict({c: '' for c in ledger.COLUMNS}, id=rid, type='physical',
                         statement=rid, origin='prose', status='binding', mutable='state',
                         introduced_by=writer, scene_id='act1-sc01'))
        ledger.save(project_dir, rows, command='test')

    @pytest.mark.parametrize('writer', ['commitments', 'draft'])
    def test_ending_a_commitment_state_sets_its_resolves(self, project_dir, tmp_path, writer):
        self._state(project_dir, 'bleeding', writer)
        result = _gate(project_dir, tmp_path, [_commitment(ends=['bleeding'])])
        assert result.committed
        assert {r['id']: r for r in ledger.load(project_dir)}['bleeding']['resolves'] == SCENE

    def test_ending_a_state_a_later_scene_ended_moves_its_end_here(
            self, project_dir, tmp_path):
        """#621 (Telemachy): a re-gate gave scene 2's belief a new id, a later
        scene's re-check ended it, and scene 3, which ends it in the book,
        stopped on `ends again`. A state ends at its first end in reading
        order; the later scene is listed for a re-check."""
        self._state(project_dir, 'bleeding', 'draft')
        rows = ledger.load(project_dir)
        next(r for r in rows if r['id'] == 'bleeding')['resolves'] = 'act2-sc01'
        ledger.save(project_dir, rows, command='test')
        result = _gate(project_dir, tmp_path, [_commitment(ends=['bleeding'])])
        assert result.committed and not result.unresolved
        assert {r['id']: r for r in ledger.load(project_dir)}['bleeding']['resolves'] == SCENE
        assert result.problems['ends moved'] == [f'{SCENE}: bleeding (was: act2-sc01)']
        assert 'bleeding' in result.changed
        # the scene that ended it before is re-checked (#622's review)
        assert 'act2-sc01' in result.recheck
        assert gate.pending(project_dir)['act2-sc01']['command'] == gate.RECHECK
        assert any(line.startswith('NOTE (a state a later scene ended')
                   for line in gate.report_lines(result))

    def test_ending_a_registry_state_goes_to_the_checker_and_is_not_applied(
            self, project_dir, tmp_path):
        self._state(project_dir, 'limp', 'extract')
        result = _gate(project_dir, tmp_path, [_commitment(ends=['limp'])])
        assert result.halts == [] and result.committed
        assert [d.fact_id for d in result.check.cleared] == ['limp']
        assert 'ends in this scene' in result.check.cleared[0].claim
        assert {r['id']: r for r in ledger.load(project_dir)}['limp']['resolves'] == ''


class TestFailsLoud:
    def test_an_extraction_cut_off_raises(self, project_dir, tmp_path):
        def fake(path, body, **k):
            return _text({'commitments': []}, stop='max_tokens')
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)), \
                pytest.raises(GateError, match='extraction failed'):
            gate_scene(project_dir, SCENE, command='draft', log_dir=str(tmp_path),
                       extract_model='m', check_model='m')

    def test_a_failed_check_raises(self, project_dir, tmp_path):
        def fake(path, body, **k):
            if 'tools' in body:
                return {'stop_reason': 'refusal', 'content': [], 'usage': {}}
            return _text({'commitments': []})
        before = ledger.load(project_dir)
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)), \
                pytest.raises(GateError, match='refused'):
            gate_scene(project_dir, SCENE, command='draft', log_dir=str(tmp_path),
                       extract_model='m', check_model='m')
        assert ledger.load(project_dir) == before

    @pytest.mark.parametrize('command', ['commitments', 'hone', ''])
    def test_only_gate_commands(self, project_dir, tmp_path, command):
        with pytest.raises(ValueError, match='command must be'):
            gate_scene(project_dir, SCENE, command=command, log_dir=str(tmp_path))

    def test_empty_prose_raises(self, project_dir, tmp_path):
        with pytest.raises(GateError, match='no prose'):
            gate_scene(project_dir, SCENE, command='draft', prose='  \n', log_dir=str(tmp_path))


def test_gate_commands_are_commitment_writers():
    assert set(gate.GATE_COMMANDS) < set(ledger.COMMITMENT_WRITERS)
    assert ledger.COMMITMENTS_PASS not in gate.GATE_COMMANDS


class TestReview439:
    """Fixes from #439's review."""

    def test_an_unverified_finding_blocks_the_commit(self, project_dir, tmp_path):
        before = ledger.load(project_dir)
        bad = dict(_contradiction(), established_quote='words act1-sc01 never says')
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[bad])
        assert result.unverified and not result.findings
        assert not result.passed and ledger.load(project_dir) == before

    def test_a_redraft_is_checked_without_its_earlier_commitments(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment(statement='Hollow had 412 people')])
        seen = []

        def fake(path, body, **k):
            if 'tools' not in body:
                return _text({'commitments': [_commitment(statement='Hollow had 500')]})
            if len(body['messages']) == 1:
                return {'stop_reason': 'tool_use', 'usage': {}, 'content': [
                    {'type': 'tool_use', 'id': 't1', 'name': 'query_ledger',
                     'input': {'subject': '', 'type': 'world', 'text': 'hollow'}}]}
            seen.append(body['messages'][2]['content'][0]['content'])
            return _text({'findings': [], 'kept': []})
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)):
            result = gate_scene(project_dir, SCENE, command='redraft', log_dir=str(tmp_path),
                                extract_model='m', check_model='m')
        assert result.committed
        assert '412' not in seen[0]

    def test_a_redraft_clears_the_ends_its_earlier_version_set(self, project_dir, tmp_path):
        TestEnds()._state(project_dir, 'bleeding', 'draft')
        _gate(project_dir, tmp_path, [_commitment(ends=['bleeding'])])
        _gate(project_dir, tmp_path, [_commitment()], command='redraft')
        assert {r['id']: r for r in ledger.load(project_dir)}['bleeding']['resolves'] == ''

    def test_an_unresolved_extraction_problem_blocks_the_commit(self, project_dir, tmp_path):
        before = ledger.load(project_dir)
        result = _gate(project_dir, tmp_path, [_commitment(quote='words the scene lacks')])
        assert result.unresolved == [f'quote: {SCENE}: {result.proposed[0]["id"]}']
        assert not result.passed and ledger.load(project_dir) == before

    def test_a_ledger_changed_during_the_gate_is_not_overwritten(self, project_dir, tmp_path):
        def fake(path, body, **k):
            if 'tools' in body:
                rows = ledger.load(project_dir)
                rows[0]['statement'] = 'edited meanwhile'
                ledger.save(project_dir, rows, command='hand')
                return _text({'findings': [], 'kept': []})
            return _text({'commitments': [_commitment()]})
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)), \
                pytest.raises(GateError, match='changed while'):
            gate_scene(project_dir, SCENE, command='draft', log_dir=str(tmp_path),
                       extract_model='m', check_model='m')
        assert ledger.load(project_dir)[0]['statement'] == 'edited meanwhile'

    @pytest.mark.parametrize('fail_on', ['extract', 'check'])
    def test_an_api_failure_is_a_gate_error(self, project_dir, tmp_path, fail_on):
        def fake(path, body, **k):
            if ('tools' in body) == (fail_on == 'check'):
                raise RuntimeError('API returned HTTP 500')
            return _text({'commitments': []})
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)), \
                pytest.raises(GateError, match='HTTP 500'):
            gate_scene(project_dir, SCENE, command='draft', log_dir=str(tmp_path),
                       extract_model='m', check_model='m')

    def test_facts_tied_to_no_scene_are_reported(self, project_dir, tmp_path):
        rows = ledger.load(project_dir)
        rows[0]['scene_id'] = 'renamed-scene'
        ledger.save(project_dir, rows, command='test')
        result = _gate(project_dir, tmp_path, [_commitment()])
        assert result.problems['unplaced'] == [rows[0]['id']]


class TestPersistence:
    """The second question on extracted facts: does it last beyond the scene?"""

    def test_a_fact_that_does_not_last_is_not_committed_and_is_reported(
            self, project_dir, tmp_path):
        staging = _commitment(statement='Dorren sets the cup down on the left',
                              mutable='state')
        result = _gate(project_dir, tmp_path, [_commitment(), staging],
                       drop={'Dorren sets the cup down on the left'})
        assert result.committed
        assert [r['statement'] for r in result.proposed] == ["Tarren's Hollow had 412 people"]
        assert result.dropped == [('Dorren sets the cup down on the left', 'w')]
        assert any(line.startswith('NOTE (not recorded, judged not to last')
                   for line in gate.report_lines(result))
        assert 'cup' not in ' '.join(r['statement'] for r in ledger.load(project_dir))

    def test_a_fact_that_changes_another_is_not_asked_about(self, project_dir, tmp_path):
        TestEnds()._state(project_dir, 'bleeding', 'draft')
        asked = []

        def fake(path, body, **k):
            if _is_persistence(body):
                asked.append(body['messages'][0]['content'])
                return _persistence_reply(body, drop={'The bleeding stopped'})
            if 'tools' in body:
                return _text({'findings': [], 'kept': []})
            return _text({'commitments': [_commitment(statement='The bleeding stopped',
                                                      ends=['bleeding'])]})
        with patch('storyforge.api._api_request', side_effect=fake):
            result = gate_scene(project_dir, SCENE, command='draft', log_dir=str(tmp_path),
                                extract_model='m', check_model='m')
        assert asked == [] and result.dropped == []
        assert [r['statement'] for r in result.proposed] == ['The bleeding stopped']

    @pytest.mark.parametrize('reply', [
        {'verdicts': []},                                              # one unanswered
        {'verdicts': [{'n': 1, 'persists': True, 'why': ''}] * 2},     # answered twice
        {'verdicts': [{'n': 2, 'persists': True, 'why': ''}]},         # out of range
    ])
    def test_a_reply_that_does_not_answer_each_fact_once_is_a_gate_error(
            self, project_dir, tmp_path, reply):
        before = ledger.load(project_dir)

        def fake(path, body, **k):
            if _is_persistence(body):
                return _text(reply)
            return _text({'commitments': [_commitment()]})
        with patch('storyforge.api._api_request', side_effect=fake), \
                pytest.raises(GateError, match='persistence check failed'):
            gate_scene(project_dir, SCENE, command='draft', log_dir=str(tmp_path),
                       extract_model='m', check_model='m')
        assert ledger.load(project_dir) == before


class TestRecheck:
    """Phase 4 (docs/plans/2026-10-31-phase4-safe-revision-design.md §3): a
    redraft is no longer refused for what leans on it; what it changed lists
    the later scenes that depend on it, and `recheck_pending` re-gates them."""
    LATER = 'act2-sc01'

    def _mine(self, project_dir):
        return [r for r in ledger.load(project_dir)
                if r['scene_id'] == SCENE and ledger.is_commitment(r)]

    def _add(self, project_dir, **row):
        rows = ledger.load(project_dir)
        base = dict(rows[0], **{k: '' for k in rows[0]})
        base.update(status='binding', origin='prose', mutable='state', introduced_by='draft')
        base.update(row)
        ledger.save(project_dir, rows + [base], command='test')

    def _commit_with_dependent(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow')])
        old = self._mine(project_dir)[0]
        self._add(project_dir, id='later-fact', scene_id=self.LATER, type='world',
                  subject='tarrens-hollow', statement='The hollow is empty', supersedes=old['id'])
        return old

    def test_the_same_fact_keeps_its_id_and_its_later_end(self, project_dir, tmp_path):
        old = self._commit_with_dependent(project_dir, tmp_path)
        rows = ledger.load(project_dir)
        next(r for r in rows if r['id'] == old['id'])['resolves'] = self.LATER
        ledger.save(project_dir, rows, command='test')
        result = _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow')],
                       command='redraft')
        assert result.committed
        mine = self._mine(project_dir)
        assert [(r['id'], r['resolves']) for r in mine] == [(old['id'], self.LATER)]
        assert result.changed == [] and result.recheck == []
        assert gate.pending(project_dir) == {}

    def test_a_dependent_found_only_by_a_registry_alias_is_listed(self, project_dir, tmp_path):
        """The gate passes the registry names (#474): "Hayle" is an alias of
        dorren-hayle, and nothing else ties the later fact to it."""
        _gate(project_dir, tmp_path, [_commitment(subject='dorren-hayle', type='physical',
                                                  statement='Dorren has a limp')])
        self._add(project_dir, id='later-fact', scene_id=self.LATER, type='knowledge',
                  subject='tessa-merrin', statement='Tessa saw Hayle walk without help')
        result = _gate(project_dir, tmp_path, [_commitment(
            subject='dorren-hayle', type='physical', statement='Dorren walks well')],
            command='redraft')
        assert self.LATER in result.recheck and result.name_notes == []

    def test_a_missing_registry_is_reported(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow')])
        os.remove(os.path.join(project_dir, 'reference', 'locations.csv'))
        result = _gate(project_dir, tmp_path, [_commitment(
            subject='tarrens-hollow', statement='The hollow had 300 people')], command='redraft')
        assert result.changed and any('locations.csv' in n for n in result.name_notes)

    def test_an_unreadable_registry_stops_before_the_model_calls(self, project_dir, tmp_path):
        with open(os.path.join(project_dir, 'reference', 'characters.csv'), 'wb') as f:
            f.write(b'id|name\n\xff\xfe|x\n')
        with patch('storyforge.api._api_request', side_effect=AssertionError('called')):
            with pytest.raises(GateError):
                gate_scene(project_dir, SCENE, command='draft',
                           log_dir=str(tmp_path / 'logs'), extract_model='m', check_model='m')

    def test_a_dropped_fact_lists_its_dependents_for_a_recheck(self, project_dir, tmp_path):
        old = self._commit_with_dependent(project_dir, tmp_path)
        result = _gate(project_dir, tmp_path, [_commitment(
            subject='tarrens-hollow', statement='The hollow had 300 people')], command='redraft')
        assert result.committed
        assert result.changed == [old['id']] and result.recheck == [self.LATER]
        assert gate.pending(project_dir)[self.LATER]['command'] == 'recheck'

    def test_facts_new_to_the_scene_list_nothing(self, project_dir, tmp_path):
        self._add(project_dir, id='later-fact', scene_id=self.LATER, type='world',
                  subject='tarrens-hollow', statement='The hollow is empty')
        result = _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow')])
        assert result.committed and result.changed == [] and result.recheck == []

    def test_an_end_this_scene_no_longer_makes_is_a_change(self, project_dir, tmp_path):
        self._add(project_dir, id='early-state', scene_id='act1-sc01', subject='dorren-hayle',
                  type='physical', statement='Dorren is injured', resolves=SCENE)
        self._add(project_dir, id='later-state', scene_id=self.LATER, subject='dorren-hayle',
                  type='physical', statement='Dorren limps')
        result = _gate(project_dir, tmp_path, [_commitment()], command='redraft')
        assert 'early-state' in result.changed and result.recheck == [self.LATER]

    def test_a_scene_waiting_for_another_reason_keeps_its_reason(self, project_dir, tmp_path):
        self._commit_with_dependent(project_dir, tmp_path)
        gate.mark_pending(project_dir, self.LATER, 'draft', 'its own problem')
        _gate(project_dir, tmp_path, [_commitment(
            subject='tarrens-hollow', statement='The hollow had 300 people')], command='redraft')
        assert gate.pending(project_dir)[self.LATER]['reason'] == 'its own problem'

    def test_carried_ids_and_fresh_ids_never_collide(self):
        # extraction's ids never repeat an old one (`_extract`'s `reserved`)
        old = [{'id': 's--b', 'subject': '', 'type': 'world', 'statement': 'B', 'scene_id': 's'}]
        proposed = [{'id': 's--b-2', 'subject': '', 'type': 'world', 'statement': 'A'},
                    {'id': 's--b-3', 'subject': '', 'type': 'world', 'statement': 'B',
                     'supersedes': 's--b-2'},
                    {'id': 's--c', 'subject': '', 'type': 'world', 'statement': 'C',
                     'depends_on': 's--b-3'}]
        gate._carry_ids(proposed, old, [])
        ids = [p['id'] for p in proposed]
        assert ids == ['s--b-2', 's--b', 's--c']
        assert proposed[1]['supersedes'] == 's--b-2'   # it meant the first proposed row
        assert proposed[2]['depends_on'] == 's--b'     # follows its row's carried id

    def test_a_new_row_never_takes_a_kept_rows_id(self):
        """Beowulf B-034: a steady fact kept with its id, and a new fact from
        a changed paragraph that extraction gave the same id (the statements
        begin alike), both came out of the gate as
        'scyld-ship-given-to-sea--scyld-came-to-the-danes-as': the ledger
        then wouldn't load. Since #599 extraction mints it `-2` (the old ids
        are reserved) and `_carry_ids` leaves both ids as they are."""
        kept = {'id': 's--scyld-came', 'subject': 'scyld', 'type': 'trait',
                'statement': 'Scyld came as a foundling', 'scene_id': 's'}
        new = {'id': 's--scyld-came-2', 'subject': 'scyld', 'type': 'physical',
               'statement': 'Scyld came in an unmanned boat'}
        proposed = [dict(kept), new]
        gate._carry_ids(proposed, [kept], [kept['id']])
        assert [p['id'] for p in proposed] == ['s--scyld-came', 's--scyld-came-2']

    def test_two_kept_rows_stating_one_fact_keep_their_own_ids(self):
        """A kept row keeps its id even when an earlier kept row states the
        same fact (a ledger with the fact twice): renaming it would break
        the links to it."""
        a = {'id': 's--a', 'subject': '', 'type': 'world', 'statement': 'A', 'scene_id': 's'}
        b = dict(a, id='s--a-again')
        proposed = [dict(a), dict(b)]
        gate._carry_ids(proposed, [a, b], [a['id'], b['id']])
        assert [p['id'] for p in proposed] == ['s--a', 's--a-again']

    def test_a_new_row_sharing_a_kept_id_keeps_links_to_the_kept_one(self):
        kept = {'id': 's--a', 'subject': '', 'type': 'world', 'statement': 'A',
                'scene_id': 's'}
        proposed = [dict(kept),
                    {'id': 's--a-2', 'subject': '', 'type': 'world', 'statement': 'C'},
                    {'id': 's--d', 'subject': '', 'type': 'world', 'statement': 'D',
                     'depends_on': 's--a-2'}]
        gate._carry_ids(proposed, [kept], [kept['id']])
        assert len({p['id'] for p in proposed}) == 3
        # extraction's link names its own row, never the kept one
        assert proposed[2]['depends_on'] == proposed[1]['id'] == 's--a-2'

    def _recheck(self, project_dir, tmp_path, findings=()):
        def fake(path, body, **k):
            if 'tools' in body:
                return _text({'findings': list(findings), 'kept': []})
            return _text({'commitments': [_commitment(
                type='physical', subject='tessa-merrin', statement='Tessa is cold',
                quote='The edge of the mapped world was not a line on the ground')]})
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)):
            return gate.recheck_pending(project_dir, log_dir=str(tmp_path / 'rc'),
                                        extract_model='m', check_model='m')

    def test_a_recheck_that_passes_commits_and_clears(self, project_dir, tmp_path):
        self._add(project_dir, id='old-later', scene_id=self.LATER, subject='tessa-merrin',
                  type='physical', statement='Tessa is warm', introduced_by='redraft')
        gate.mark_pending(project_dir, self.LATER, 'recheck', 're-check: x')
        run = self._recheck(project_dir, tmp_path)
        assert run.passed == [self.LATER] and not run.failed
        assert gate.pending(project_dir) == {}
        later = [r for r in ledger.load(project_dir) if r['scene_id'] == self.LATER
                 and ledger.is_commitment(r)]
        assert [(r['statement'], r['introduced_by']) for r in later] == [
            ('Tessa is cold', 'redraft')]   # the prose's writer is kept

    def test_a_recheck_that_fails_stops_and_stays_pending(self, project_dir, tmp_path):
        gate.mark_pending(project_dir, 'new-x1', 'recheck', 're-check: x')
        gate.mark_pending(project_dir, self.LATER, 'recheck', 're-check: x')
        bad = {'kind': 'contradiction', 'code': 'TIM', 'scene_quote': 'x',
               'established_scene': '', 'established_quote': '', 'fact_id': 'nope',
               'explanation': 'why'}
        run = self._recheck(project_dir, tmp_path, [bad])
        assert run.failed == 'new-x1' and run.passed == []
        assert run.left == [self.LATER]
        row = gate.pending(project_dir)['new-x1']
        assert row['command'] == gate.RECHECK_FAILED and 're-check did not pass' in row['reason']
        # not re-run until the author acts
        assert gate.recheck_queue(project_dir) == [self.LATER]

    def test_over_the_cost_threshold_nothing_runs(self, project_dir, tmp_path, monkeypatch):
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '0.1')
        gate.mark_pending(project_dir, self.LATER, 'recheck', 're-check: x')
        with patch('storyforge.api._api_request', side_effect=AssertionError('spent')):
            run = gate.recheck_pending(project_dir, log_dir=str(tmp_path))
        assert run.over_budget and run.left == [self.LATER] and run.passed == []

    def test_only_recheck_rows_are_rechecked_and_skip_is_honoured(self, project_dir):
        gate.mark_pending(project_dir, 'new-x1', 'draft', 'its own problem')
        gate.mark_pending(project_dir, self.LATER, 'recheck', 'x')
        assert gate.recheck_queue(project_dir) == [self.LATER]
        assert gate.recheck_queue(project_dir, {self.LATER}) == []


class TestRecheckReview468:
    """Fixes from #468's review."""
    LATER = 'act2-sc01'

    _add = TestRecheck._add
    _mine = TestRecheck._mine

    def test_a_change_after_the_sixth_word_is_a_change(self, project_dir, tmp_path):
        """Both statements make the same id (scene + six words): the new fact
        must not take the old one's id, and the change must list dependents."""
        _gate(project_dir, tmp_path, [_commitment(
            subject='tarrens-hollow', statement="Tarren's Hollow had 412 people in spring")])
        old = self._mine(project_dir)[0]
        self._add(project_dir, id='later-fact', scene_id=self.LATER, type='world',
                  subject='', statement='x', supersedes=old['id'])
        result = _gate(project_dir, tmp_path, [_commitment(
            subject='tarrens-hollow', statement="Tarren's Hollow had 412 people in autumn")],
            command='redraft')
        new = self._mine(project_dir)[0]
        assert new['id'] != old['id']
        assert result.changed == [old['id']] and result.recheck == [self.LATER]

    def test_an_end_lists_only_scenes_after_this_one(self, project_dir, tmp_path):
        self._add(project_dir, id='early-state', scene_id='act1-sc01', subject='dorren-hayle',
                  type='physical', statement='Dorren is injured', resolves=SCENE)
        for sid, st in (('act1-sc02', 'Dorren winces'), ('new-x1', 'Dorren limps')):
            self._add(project_dir, id=f'{sid}-state', scene_id=sid, subject='dorren-hayle',
                      type='physical', statement=st)
        result = _gate(project_dir, tmp_path, [_commitment()], command='redraft')
        assert 'early-state' in result.changed
        assert result.recheck == ['new-x1']        # not act1-sc02 itself, nothing earlier

    def test_what_cant_be_rechecked_is_said(self, project_dir, tmp_path):
        from storyforge.elaborate import update_scene
        old = TestRecheck._commit_with_dependent(self, project_dir, tmp_path)
        self._add(project_dir, id='plan-link', scene_id='new-x1', type='world',
                  subject='', statement='y', depends_on=old['id'], introduced_by='hone')
        update_scene(self.LATER, os.path.join(project_dir, 'reference'), {'status': 'cut'})
        result = _gate(project_dir, tmp_path, [_commitment(
            subject='tarrens-hollow', statement='The hollow had 300 people')], command='redraft')
        assert result.recheck == ['new-x1']       # the registry row's scene
        assert result.not_rechecked == [f'{self.LATER} (cut or merged)']
        assert result.dangling == [f'plan-link → {old["id"]}']

    def test_a_gate_error_in_a_recheck_is_listed_failed(self, project_dir, tmp_path, monkeypatch):
        gate.mark_pending(project_dir, self.LATER, 'recheck', 'x')

        def boom(*a, **k):
            raise GateError('extraction failed: HTTP 500')
        monkeypatch.setattr(gate, 'gate_scene', boom)
        run = gate.recheck_pending(project_dir, log_dir=str(tmp_path))
        assert run.failed == self.LATER and 'HTTP 500' in run.why
        assert gate.pending(project_dir)[self.LATER]['command'] == gate.RECHECK_FAILED
        assert run.spent == gate.RECHECK_COST_PER_SCENE   # paid either way

    def test_the_cascade_moves_forward_and_counts_spend(self, project_dir, tmp_path, monkeypatch):
        """Each re-gated scene may list later ones; the run goes on in reading
        order, and the caller's earlier spend counts against the threshold."""
        gate.mark_pending(project_dir, 'act1-sc02', 'recheck', 'x')
        seen = []

        def fake(pd, sid, **k):
            seen.append(sid)
            gate.clear_pending(pd, sid)
            if sid == 'act1-sc02':
                gate.mark_pending(pd, self.LATER, 'recheck', 'listed by act1-sc02')
            r = gate.GateResult(sid, check=None)
            r.committed = True
            return r
        monkeypatch.setattr(gate, 'gate_scene', fake)
        monkeypatch.setattr(gate, '_writer', lambda pd, sid: 'draft')
        run = gate.recheck_pending(project_dir, log_dir=str(tmp_path), spent_before=1.0)
        assert seen == ['act1-sc02', self.LATER] and run.passed == seen
        assert run.spent == pytest.approx(1.0 + 2 * gate.RECHECK_COST_PER_SCENE)
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '1.0')
        gate.mark_pending(project_dir, self.LATER, 'recheck', 'x')
        run = gate.recheck_pending(project_dir, log_dir=str(tmp_path), spent_before=0.9)
        assert run.over_budget and seen == ['act1-sc02', self.LATER]


class TestRecheckReextracts:
    """#620 (Telemachy, 2026-11-07): a re-check's extractor joined two
    sentences across a dialogue tag into one quote; the re-check stopped and
    left 27 later scenes pending. A re-check (and `check --pending`) whose
    run only the extractor's slips stopped gates the same prose once more."""
    LATER = 'act2-sc01'

    def _misquote(self, sid):
        r = gate.GateResult(sid, check=None)
        rid = f'{sid}--a-fact'
        r.problems = {'quote': [f'{sid}: {rid}']}
        r.proposed = [{'id': rid, 'quote': 'My mother says I am. For my part'}]
        return r

    def _passed(self, sid):
        r = gate.GateResult(sid, check=None)
        r.committed = True
        return r

    def _run(self, project_dir, tmp_path, monkeypatch, runs):
        gate.mark_pending(project_dir, self.LATER, 'recheck', 'x')
        calls = []

        def fake(pd, sid, **k):
            calls.append(k)
            r = runs[len(calls) - 1](sid)
            if r.passed:
                gate.clear_pending(pd, sid)
            return r
        monkeypatch.setattr(gate, 'gate_scene', fake)
        monkeypatch.setattr(gate, '_writer', lambda pd, sid: 'draft')
        return gate.recheck_pending(project_dir, log_dir=str(tmp_path)), calls

    def test_a_misquote_alone_is_extracted_again_and_passes(
            self, project_dir, tmp_path, monkeypatch, capsys):
        run, calls = self._run(project_dir, tmp_path, monkeypatch,
                               [self._misquote, self._passed])
        assert run.passed == [self.LATER] and not run.failed
        assert len(calls) == 2 and calls[1]['log_dir'].endswith('reextract')
        assert calls[1]['introduced_by'] == 'draft' and calls[1]['prose'] is None
        assert run.spent == pytest.approx(2 * gate.RECHECK_COST_PER_SCENE)
        assert 'gated again (extraction and the check): it passed' in capsys.readouterr().out

    def test_a_second_misquote_is_kept_and_reported(self, project_dir, tmp_path, monkeypatch):
        run, calls = self._run(project_dir, tmp_path, monkeypatch,
                               [self._misquote, self._misquote])
        assert len(calls) == 2 and run.failed == self.LATER
        reason = gate.pending(project_dir)[self.LATER]['reason']
        assert 'misquoted the prose again' in reason and 'misquoted the prose again' in run.why

    def test_a_reextraction_that_fails_keeps_the_first_run(
            self, project_dir, tmp_path, monkeypatch):
        def boom(sid):
            raise GateError('extraction failed: HTTP 500')
        run, calls = self._run(project_dir, tmp_path, monkeypatch, [self._misquote, boom])
        assert len(calls) == 2 and run.failed == self.LATER
        assert 'which could not finish' in gate.pending(project_dir)[self.LATER]['reason']
        assert run.spent == pytest.approx(2 * gate.RECHECK_COST_PER_SCENE)

    def test_a_bug_in_the_reextraction_is_not_blamed_on_the_extractor(
            self, project_dir, tmp_path, monkeypatch):
        """#622's review (SF): there are no fix edits to keep on a re-check,
        so an exception that isn't `GateError` propagates."""
        def bug(sid):
            raise KeyError('id')
        with pytest.raises(KeyError):
            self._run(project_dir, tmp_path, monkeypatch, [self._misquote, bug])

    def test_no_reextraction_over_the_threshold(self, project_dir, tmp_path, monkeypatch):
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', str(gate.RECHECK_COST_PER_SCENE * 1.5))
        run, calls = self._run(project_dir, tmp_path, monkeypatch,
                               [self._misquote, self._passed])
        assert len(calls) == 1 and run.failed == self.LATER
        assert 'not run: it would pass the cost threshold' in run.why
        assert run.spent == pytest.approx(gate.RECHECK_COST_PER_SCENE)

    def test_a_passing_recheck_reports_the_links_it_applied(
            self, project_dir, tmp_path, monkeypatch):
        """#622's review (SF-H2): a moved end or an id read without its
        prefix in a re-check reached no log."""
        def applied(sid):
            r = self._passed(sid)
            r.problems = {'ends moved': [f'{sid}: a--x (was: c)'], 'id prefix': []}
            return r
        run, _ = self._run(project_dir, tmp_path, monkeypatch, [applied])
        assert run.notes == [f'{self.LATER}: NOTE (a state a later scene ended is ended here, '
                             f'its first end in reading order; the later scene is listed for '
                             f'a re-check): {self.LATER}: a--x (was: c)']

    def test_a_finding_is_not_extracted_again(self, project_dir, tmp_path, monkeypatch):
        from storyforge.checker import CheckResult, Finding

        def found(sid):
            f = Finding('contradiction', 'TIM', 'q', 'act1-sc01', 'e', '', 'why')
            r = self._misquote(sid)
            r.check = CheckResult(sid, findings=[f])
            return r
        run, calls = self._run(project_dir, tmp_path, monkeypatch, [found])
        assert len(calls) == 1 and run.failed == self.LATER

    def test_check_pending_extracts_again_too(self, project_dir, tmp_path, monkeypatch):
        from storyforge import cmd_check, costs
        gate.mark_pending(project_dir, self.LATER, 'recheck', 'x')
        runs = [self._misquote, self._passed]
        calls = []

        def fake(pd, sid, **k):
            calls.append(k)
            r = runs[len(calls) - 1](sid)
            if r.passed:
                gate.clear_pending(pd, sid)
            return r
        monkeypatch.setattr(gate, 'gate_scene', fake)
        monkeypatch.setattr(gate, '_writer', lambda pd, sid: 'draft')
        run = cmd_check._check_scenes(project_dir, [self.LATER], str(tmp_path),
                                      costs.RunBudget())
        assert len(calls) == 2 and run.passed == 1
        at = run.report.index(f'## {self.LATER}: passed')
        assert run.report[at + 2].startswith('- NOTE (re-extraction): the extractor misquoted')

    def test_check_pending_names_a_second_misquote_in_the_pending_reason(
            self, project_dir, tmp_path, monkeypatch):
        from storyforge import cmd_check, costs
        gate.mark_pending(project_dir, self.LATER, 'recheck', 'x')
        monkeypatch.setattr(gate, 'gate_scene', lambda pd, sid, **k: self._misquote(sid))
        monkeypatch.setattr(gate, '_writer', lambda pd, sid: 'draft')
        cmd_check._check_scenes(project_dir, [self.LATER], str(tmp_path), costs.RunBudget())
        assert 'misquoted the prose again' in gate.pending(project_dir)[self.LATER]['reason']


def test_every_extraction_problem_blocks_or_is_reported():
    """#622's review (TD): a kind in neither list never reaches a report."""
    from storyforge import extract
    kinds = set(extract.COMMITMENT_PROBLEMS) | {'rejected'}
    assert set(gate.UNRESOLVED) | set(gate.REPORTED) == kinds
    assert not set(gate.UNRESOLVED) & set(gate.REPORTED)


class TestRejected:
    """Phase 4 §4 (#470's review): a rejected commitment stays; prose that
    restates it doesn't pass; a revision listed after a rejection lists the
    scenes that depend on it."""
    LATER = 'act2-sc01'
    _add = TestRecheck._add
    _mine = TestRecheck._mine

    def _reject(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow')])
        rows = ledger.load(project_dir)
        mine = next(r for r in rows if r['scene_id'] == SCENE and ledger.is_commitment(r))
        mine['status'] = 'rejected'
        ledger.save(project_dir, rows, command='test')
        return mine['id']

    def test_restating_a_rejected_fact_does_not_pass_and_keeps_the_row(self, project_dir,
                                                                       tmp_path):
        rid = self._reject(project_dir, tmp_path)
        result = _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow')],
                       command='redraft')
        assert not result.passed and not result.committed
        assert any(f'restates {rid}' in x for x in result.unresolved)
        assert any('rejected' in x for x in gate.problems_to_fix(result))

    def test_a_revision_keeps_the_rejected_row_and_lists_dependents(self, project_dir,
                                                                    tmp_path):
        rid = self._reject(project_dir, tmp_path)
        self._add(project_dir, id='later-fact', scene_id=self.LATER, type='world',
                  subject='tarrens-hollow', statement='The hollow is empty')
        gate.mark_pending(project_dir, SCENE, gate.REVISE_REJECTED, f'x [rejected: {rid}]')
        result = _gate(project_dir, tmp_path, [_commitment(
            subject='tarrens-hollow', statement='The hollow had 300 people')], command='redraft')
        assert result.committed
        rows = {r['id']: r for r in ledger.load(project_dir)}
        assert rows[rid]['status'] == 'rejected'                 # the record stays
        assert rid in result.changed and result.recheck == [self.LATER]
        assert SCENE not in gate.pending(project_dir)

    def test_a_revision_also_lists_the_scenes_whose_brief_names_the_rejected_fact(
            self, project_dir, tmp_path, monkeypatch):
        """`audit --mark rejected` says these are listed once the revision
        passes; before #473's follow-up the gate listed dependents only."""
        rid = self._reject(project_dir, tmp_path)
        monkeypatch.setattr(gate.audit, 'leaning_scenes',
                            lambda p, ids: {i: ['new-x1', 'act1-sc01'] for i in ids})
        gate.mark_pending(project_dir, SCENE, gate.REVISE_REJECTED, f'x [rejected: {rid}]')
        result = _gate(project_dir, tmp_path, [_commitment(
            subject='tarrens-hollow', statement='The hollow had 300 people')], command='redraft')
        assert result.committed
        assert 'new-x1' in result.recheck and 'act1-sc01' not in result.recheck   # later only

    def test_the_gate_lists_what_audit_said_it_would(self, project_dir, tmp_path):
        """`audit --mark rejected` shows the scenes listed once the revision
        passes (dependents and briefs naming the fact); the gate lists the
        same ones. A real brief row, no stub."""
        from storyforge import cmd_audit
        rid = self._reject(project_dir, tmp_path)
        path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
        with open(path, encoding='utf-8') as f:
            text = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text.replace('new-x1|||||||', f'new-x1||||||{rid}|', 1))
        promised = cmd_audit._reject_recheck(project_dir, ledger.load(project_dir), [rid])
        assert 'new-x1' in promised[rid]['later']
        gate.mark_pending(project_dir, SCENE, gate.REVISE_REJECTED, f'x [rejected: {rid}]')
        result = _gate(project_dir, tmp_path, [_commitment(
            subject='tarrens-hollow', statement='The hollow had 300 people')], command='redraft')
        assert result.recheck == promised[rid]['later']
        assert all(gate.pending(project_dir)[s]['command'] == gate.RECHECK
                   for s in result.recheck)

    def test_a_brief_scene_not_in_the_book_is_said(self, project_dir, tmp_path, monkeypatch):
        rid = self._reject(project_dir, tmp_path)
        monkeypatch.setattr(gate.audit, 'leaning_scenes', lambda p, ids: {rid: ['ghost-scene']})
        gate.mark_pending(project_dir, SCENE, gate.REVISE_REJECTED, f'x [rejected: {rid}]')
        result = _gate(project_dir, tmp_path, [_commitment(
            subject='tarrens-hollow', statement='The hollow had 300 people')], command='redraft')
        assert result.committed
        assert any(x.startswith('ghost-scene (') and 'not in scenes.csv' in x
                   for x in result.not_rechecked)

    def test_a_bad_pending_file_stops_before_the_model_calls(self, project_dir, tmp_path):
        """It used to be read after the check and taken as empty, losing a
        rejection's re-check (#474 review)."""
        self._reject(project_dir, tmp_path)
        before = ledger.load(project_dir)
        os.makedirs(os.path.join(project_dir, 'working'), exist_ok=True)
        with open(os.path.join(project_dir, gate.PENDING_PATH), 'w') as f:
            f.write('not|the|header\n')
        with patch('storyforge.api._api_request', side_effect=AssertionError('called')):
            with pytest.raises(GateError, match='header'):
                gate_scene(project_dir, SCENE, command='redraft',
                           log_dir=str(tmp_path / 'logs'), extract_model='m', check_model='m')
        assert ledger.load(project_dir) == before

    def test_a_failed_check_keeps_a_revise_row_and_its_ids(self, project_dir):
        gate.mark_pending(project_dir, SCENE, gate.REVISE_REJECTED, 'x [rejected: a]')
        gate.mark_pending(project_dir, SCENE, 'advisor', '2 problem(s)')
        row = gate.pending(project_dir)[SCENE]
        assert row['command'] == gate.REVISE_REJECTED and gate.rejected_ids(row) == ['a']
        assert row['reason'].startswith('2 problem(s)')


def test_a_calendar_finding_names_the_calendar_in_the_fix_prompt(project_dir, tmp_path):
    """#478's review: a finding against scenes.csv reads as the calendar."""
    finding = {**_contradiction(), 'code': 'TIM', 'established_scene': 'scenes.csv',
               'established_quote': 'act1-sc01: day 1, morning'}
    result = _gate(project_dir, tmp_path, findings=[finding])
    assert not result.passed and result.check.unverified == []
    line = next(x for x in gate.problems_to_fix(result) if 'TIM contradiction' in x)
    assert 'but the calendar (scenes.csv) establishes "act1-sc01: day 1, morning"' in line


class TestInheritedAndPlanConflicts:
    """2026-11-01: E8's 14 "false alarms" were real. Six findings were
    already in the scene before the pass, and some came from the brief's
    own words. The first kind is reported and doesn't block; the second
    blocks and goes to the author, not the fix."""

    def test_a_contradiction_already_in_the_book_does_not_block(self, project_dir, tmp_path):
        snap = _snap(project_dir, f'Old prose. The map said {HERE}, plainly.')
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
                       command='revise', before=snap)
        assert result.passed and result.committed
        assert [f.code for f in result.inherited] == ['TIM'] and result.findings == []
        lines = gate.report_lines(result)
        assert any(x.startswith('ALREADY IN THE SCENE') and 'TIM' in x for x in lines)
        assert gate.blocking_lines(lines) == []
        assert gate.problems_to_fix(result) == []

    def test_without_a_baseline_it_still_blocks(self, project_dir, tmp_path):
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()])
        assert not result.passed and result.inherited == []

    def test_one_the_pass_wrote_still_blocks(self, project_dir, tmp_path):
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
                       command='revise', before=_snap(project_dir, 'Different words entirely.'))
        assert not result.passed and result.inherited == []

    def test_a_broken_promise_is_never_inherited(self, project_dir, tmp_path):
        promise = {**_contradiction(), 'kind': 'broken_promise', 'code': 'PRM'}
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[promise],
                       command='revise', before=_snap(project_dir, HERE))
        assert not result.passed and result.inherited == []

    def test_a_contradiction_in_the_briefs_own_words_is_a_plan_conflict(
            self, project_dir, tmp_path):
        quote = 'It was there forty years ago. It isn\'t there now.'   # act1-sc02's key_dialogue
        finding = {**_contradiction(), 'scene_quote': quote}
        with open(os.path.join(project_dir, 'scenes', f'{SCENE}.md'), 'a') as f:
            f.write(f'\n\n"{quote} There is no note."\n')
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[finding])
        assert not result.passed
        assert [f.scene_quote for f in result.plan_conflicts] == [quote]
        assert gate.problems_to_fix(result) == []
        line = next(x for x in gate.report_lines(result) if 'TIM' in x)
        assert line.startswith('PLAN CONFLICT') and 'fix the brief or act1-sc01' in line
        assert gate.blocking_lines([line]) == [line]

    def test_inherited_wins_over_plan_conflict(self, project_dir, tmp_path):
        quote = 'It was there forty years ago.'
        finding = {**_contradiction(), 'scene_quote': quote}
        with open(os.path.join(project_dir, 'scenes', f'{SCENE}.md'), 'a') as f:
            f.write(f'\n\n"{quote}"\n')
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[finding],
                       command='revise', before=_snap(project_dir, f'"{quote}"'))
        assert result.passed and result.plan_conflicts == [] and len(result.inherited) == 1

    def test_a_scripted_line_split_by_a_speech_tag_is_a_plan_conflict(
            self, project_dir, tmp_path):
        """mended-bridle (2026-11-03): the brief scripts "Left hand on the
        case. Right hand free. ..."; the prose split it with "he said", the
        checker called it a contradiction with a later scene (the one in
        error), and the fix rewrote the scene to match that scene. It is the
        brief against the book: the author's, never the fix's."""
        line = 'Left hand on the case. Right hand free. He carried it the same way.'
        _set_dialogue(project_dir, f'"{line}"')
        quote = '"Left hand on the case," he said. "Right hand free. He carried it the same way."'
        with open(os.path.join(project_dir, 'scenes', f'{SCENE}.md'), 'a') as f:
            f.write(f'\n\n{quote}\n')
        finding = {**_contradiction(), 'code': 'TRT', 'scene_quote': quote,
                   'established_scene': 'act1-sc01'}
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[finding])
        assert not result.passed
        assert [f.code for f in result.plan_conflicts] == ['TRT']
        assert gate.problems_to_fix(result) == []
        assert any(x.startswith('PLAN CONFLICT') for x in gate.report_lines(result))

    LINE = ['Left hand on the case. Right hand free. He carried it the same way.']
    NAMES = gate.Cast({'thomas': frozenset({'thomas-bright-horse'}),
                       'thomas bright horse': frozenset({'thomas-bright-horse'}),
                       'cora': frozenset({'cora-dunning'})})

    @pytest.mark.parametrize('quote, expected', [
        # the real mended-bridle split line, and the same with the opening
        # mark cut off (a quote may start mid-line)
        ('"Left hand on the case," he said. "Right hand free. He carried it the same way."',
         True),
        ('Left hand on the case," he said. "Right hand free.', True),
        # a name or a pronoun, either order; up to three words of name
        ('"Left hand on the case," said Thomas. "Right hand free."', True),
        ('"Left hand on the case," Thomas Bright Horse said. "Right hand free."', True),
        # curly double and single quotes; CRLF inside
        ('\u201cLeft hand on the case,\u201d he said. \u201cRight hand free.\u201d', True),
        ('\u2018Left hand on the case,\u2019 he said. \u2018Right hand free.\u2019', True),
        ('"Left hand on the case,"\r\nhe said. "Right hand free."', True),
        # CR-1/SF-2 (#504 review): narration before or after an unsplit line
        # is not a tag; a wrong speaker there may be the error
        ('"Left hand on the case, right hand free," said the dead man.', False),
        ('The dead man said, "Left hand on the case. Right hand free."', False),
        # anything in the tag beyond speaker and verb is narration
        ('"Left hand on the case," she said in Brennick. "Right hand free."', False),
        ('"Left hand on the case," Thomas said quietly. "Right hand free."', False),
        ('"Left hand on the case," said the dead man. "Right hand free."', False),
        ('"Left hand on the case," Ana Maria de la Cruz said. "Right hand free."', False),
        # narration past the line
        ('"Left hand on the case," he said, and she lifted it in her right hand.', False),
        ('"Left hand," he said. She took the case in her right hand and held it out.', False),
        # spoken words outside the brief's line are not ignored
        ('"Left hand on the case," he said. "Right hand free. In Brennick, always."', False),
        # no scripted words at all
        ('"Right shoulder," he said. "Fingers under the strap."', False),
    ])
    def test_only_a_line_split_by_a_speech_tag_is_seen_through(self, quote, expected):
        assert gate._is_plan_conflict(quote, self.LINE, self.NAMES) is expected

    def test_a_name_tag_needs_the_name_in_the_registry(self):
        quote = '"Left hand on the case," said Thomas. "Right hand free."'
        assert not gate._is_plan_conflict(quote, self.LINE, gate.Cast())   # no names known
        assert gate._is_plan_conflict('"Left hand on the case," said he. "Right hand free."',
                                      self.LINE, gate.Cast())

    def test_speaker_names_come_from_the_character_registry(self, project_dir):
        import csv
        path = os.path.join(project_dir, 'reference', 'characters.csv')
        with open(path, newline='') as f:
            row = next(csv.DictReader(f, delimiter='|'))
        names = gate._cast(project_dir).names
        assert gate._words(row['name']).strip() in names

    def test_a_short_brief_phrase_is_not_a_source(self, project_dir):
        _set_dialogue(project_dir, '"No."; "It was there forty years ago."')
        assert gate._brief_phrases(project_dir, SCENE) == ['It was there forty years ago.']


def _set_characters(project_dir, rows):
    """Replace characters.csv with `rows` (dicts; the header is the first
    row's keys)."""
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    with open(path, 'w', newline='') as f:
        f.write('|'.join(rows[0]) + '\n')
        for r in rows:
            f.write('|'.join(r.values()) + '\n')


def _words_eq(a, b):
    return gate._words(a) == gate._words(b)


class TestSpeechTagSpeaker:
    """#504's known limit: a split line's tag naming someone other than the
    character the brief scripts the line for is not the brief's words, so
    the wrong-speaker error goes to the fix, not to the author as a plan
    conflict."""

    LINE = 'Left hand on the case. Right hand free. He carried it the same way.'
    SPLIT = '"Left hand on the case," {tag}. "Right hand free. He carried it the same way."'
    PEOPLE = [
        {'id': 'thomas-bright-horse', 'name': 'Thomas Bright Horse', 'aliases': 'Thomas',
         'pronouns': 'he/him'},
        {'id': 'emmett-slade', 'name': 'Emmett Slade', 'aliases': 'Emmett;Slade',
         'pronouns': 'he/him'},
        {'id': 'cora-dunning', 'name': 'Cora Dunning', 'aliases': 'Cora', 'pronouns': 'she'},
        {'id': 'lena-callis', 'name': 'Lena Callis', 'aliases': 'Lena', 'pronouns': ''},
        {'id': 'maren-cole', 'name': 'Maren Cole', 'aliases': 'Maren', 'pronouns': 'she'},
        {'id': 'rook', 'name': 'Rook', 'aliases': '', 'pronouns': 'she'},
    ]
    #: Thomas is an alias two characters share; only the full names tell them apart
    TWO_THOMASES = PEOPLE + [{'id': 'thomas-webb', 'name': 'Thomas Webb',
                              'aliases': 'Thomas', 'pronouns': 'he'}]

    def _cast(self, project_dir, people=None):
        _set_characters(project_dir, people or self.PEOPLE)
        return gate._cast(project_dir)

    def _lines(self, project_dir, dialogue, people=None):
        cast = self._cast(project_dir, people)
        _set_dialogue(project_dir, dialogue)
        return gate._brief_lines(project_dir, SCENE, cast), cast

    def _speaker(self, project_dir, dialogue, people=None, line=None):
        """The speaker the brief gives `line` (default LINE)."""
        lines, _ = self._lines(project_dir, dialogue.format(line=line or self.LINE), people)
        return next(p.speaker for p in lines if _words_eq(p.text, line or self.LINE))

    @pytest.mark.parametrize('dialogue', [
        'Thomas: "{line}"',
        'Thomas, low, to Cora: "{line}"',
        'Thomas tells Cora: "{line}"',                  # the listener after a verb
        '"{line}" — Thomas',
        '"{line}" – Thomas',                            # en dash
        '"{line}" -- Thomas Bright Horse, flat',
        '"You are Cora Dunning." / Thomas Bright Horse: "{line}"',
        'thomas-bright-horse: "{line}"',                # the id as a name
        # narration before the label's last clause names someone else
        '"Come inside." Cora does not move. Thomas, at the door: "{line}"',
        # CR-1: a stop before a bracket, a quote mark, a dash, an ellipsis
        '(Cora waits.) Thomas: "{line}"',
        'Cora mutters \'wait.\' Thomas: "{line}"',
        'Cora waits.— Thomas: "{line}"',
        'Cora waits… Thomas: "{line}"',
        'Cora waits...Thomas: "{line}"',
        # CR-2: a title doesn't end the clause, in any case
        'Thomas, to Sgt. Cora: "{line}"',
        'Thomas, to SGT. Cora: "{line}"',
        'Thomas, to det. Cora Dunning: "{line}"',
        'Thomas, to Capt. Emmett: "{line}"',
        # a label naming no one doesn't count against one that does
        'Council: "{line}" — Thomas',
        # escaped quotes (meridian-line's briefs)
        'Thomas: \\"{line}\\"',
        '\\"{line}\\" — Thomas',
    ])
    def test_the_brief_names_the_speaker(self, project_dir, dialogue):
        assert self._speaker(project_dir, dialogue) == 'thomas-bright-horse'

    def test_the_residue_line(self, project_dir):
        """CR-1: shared-dark's residue: "(Pause. Rook shifts her weight in
        the doorway.) Maren:" gave Maren's line to Rook."""
        line = 'Still you, after all of it?'
        dialogue = ('Hank: "No, it does not go away." (Pause. Rook shifts her weight in the '
                    'doorway.) Maren: "{line}"')
        assert self._speaker(project_dir, dialogue, line=line) == 'maren-cole'

    def test_only_the_first_clause_after_a_dash_counts(self, project_dir):
        lines, _ = self._lines(project_dir,
                               f'"{self.LINE}" — Lena. Thomas: "Come inside now, then."')
        assert [(p.text, p.speaker) for p in lines] == [
            (self.LINE, 'lena-callis'), ('Come inside now, then.', 'thomas-bright-horse')]

    @pytest.mark.parametrize('dialogue, why', [
        ('"{line}"', gate._NO_LABEL),                   # mended-bridle: no labels
        # not a character: said so (#513's review, SF-4)
        ('Council: "{line}"', gate._not_in_cast('Council')),
        ('Spoken to the grave: "{line}"', gate._not_in_cast('Spoken to the grave')),
        ('told Thomas: "{line}"', gate._NO_LABEL),      # C-4: the listener
        ('"{line}" — though he knew the answer', gate._NO_LABEL),
        ('"{line}" / "Come inside."', gate._NO_LABEL),
        # the dash clause ending in a colon labels the next line, not this one
        ('"{line}" — Cora, after he leaves: "Come inside, then."', gate._NO_LABEL),
        ('"{line}" — Thomas\'s answer to Cora', gate._UNCLEAR),   # a possessive
        ('Cora: "{line}" — Thomas', gate._UNCLEAR),     # two labels that disagree
        # CR-3: more than one character in the label
        ('Thomas and Cora: "{line}"', gate._UNCLEAR),
        ('Thomas or Emmett: "{line}"', gate._UNCLEAR),
        ('Thomas, Cora: "{line}"', gate._UNCLEAR),
        ('Thomas turns to Cora, who says: "{line}"', gate._UNCLEAR),
        ('Thomas looks at Cora, and Cora says: "{line}"', gate._UNCLEAR),
        ('Thomas watches as she says: "{line}"', gate._UNCLEAR),
        # CR-1: a spaced dash in the label
        ('Thomas, afraid — and Cora hears it: "{line}"', gate._UNCLEAR),
        ('"{line}" — Thomas, watching — Cora nods', gate._UNCLEAR),
    ])
    def test_the_brief_names_no_speaker(self, project_dir, dialogue, why):
        lines, _ = self._lines(project_dir, dialogue.format(line=self.LINE))
        assert (self.LINE, None, why) in lines

    def test_an_unquoted_line_has_no_speaker(self, project_dir):
        """SF-5: a key_dialogue item with no quote marks is given no
        speaker; a label naming a character is taken off it so its words
        can match the prose (#513's review, G-1)."""
        lines, _ = self._lines(project_dir, f'Thomas: {self.LINE}')
        assert lines == [(self.LINE, None, gate._NO_QUOTES)]

    def test_a_name_two_characters_share_names_no_one(self, project_dir):
        assert self._speaker(project_dir, 'Thomas: "{line}"', self.TWO_THOMASES) is None
        lines, _ = self._lines(project_dir, f'Thomas: "{self.LINE}"', self.TWO_THOMASES)
        assert lines[0].why == gate._SHARED
        # the full name tells them apart
        assert self._speaker(project_dir, 'Thomas Webb: "{line}"',
                             self.TWO_THOMASES) == 'thomas-webb'

    def test_no_characters_names_no_one(self, project_dir):
        os.remove(os.path.join(project_dir, 'reference', 'characters.csv'))
        _set_dialogue(project_dir, f'Thomas: "{self.LINE}"')
        cast = gate._cast(project_dir)
        assert gate._brief_lines(project_dir, SCENE, cast) == [
            (self.LINE, None, gate._NO_CAST)]

    @pytest.mark.parametrize('tag, expected', [
        # a name or alias: agree → plan conflict; disagree → to the fix
        ('Thomas said', True),
        ('said Thomas Bright Horse', True),
        ('Emmett said', False),
        ('said Slade', False),
        ('Cora said', False),
        # a pronoun, checked against known pronouns
        ('he said', True),
        ('she said', False),
        ('they said', False),
        # "I", "we", "you": can't tell, matched as before
        ('I said', True),
        ('we said', True),
        ('you said', True),
        # C-4: "told" names its listener after it; only "Thomas told" is a tag
        ('Thomas told', True),
        ('told Thomas', False),
    ])
    def test_the_tag_must_fit_the_briefs_speaker(self, project_dir, tag, expected):
        lines, cast = self._lines(project_dir, f'Thomas: "{self.LINE}"')
        quote = self.SPLIT.format(tag=tag)
        assert gate._is_plan_conflict(quote, lines, cast) is expected

    def test_a_shared_name_tag_fits_either_characters_line(self, project_dir):
        for label in ('Thomas Bright Horse', 'Thomas Webb'):
            lines, cast = self._lines(project_dir, f'{label}: "{self.LINE}"',
                                      self.TWO_THOMASES)
            assert gate._is_plan_conflict(self.SPLIT.format(tag='Thomas said'), lines, cast)
        lines, cast = self._lines(project_dir, f'Thomas Bright Horse: "{self.LINE}"',
                                  self.TWO_THOMASES)
        assert not gate._is_plan_conflict(self.SPLIT.format(tag='Thomas Webb said'),
                                          lines, cast)

    def test_an_id_tag_is_checked(self, project_dir):
        people = [{**p, 'id': 'old-man'} if p['id'] == 'thomas-bright-horse' else p
                  for p in self.PEOPLE]
        lines, cast = self._lines(project_dir, f'Thomas: "{self.LINE}"', people)
        assert lines[0].speaker == 'old-man'
        assert gate._is_plan_conflict(self.SPLIT.format(tag='old-man said'), lines, cast)
        assert not gate._is_plan_conflict(self.SPLIT.format(tag='Emmett said'), lines, cast)

    def test_every_tag_of_a_line_split_twice_must_fit(self, project_dir):
        lines, cast = self._lines(project_dir, f'Thomas: "{self.LINE}"')
        twice = ('"Left hand on the case," he said. "Right hand free," {}. '
                 '"He carried it the same way."')
        assert gate._is_plan_conflict(twice.format('Thomas said'), lines, cast)
        assert not gate._is_plan_conflict(twice.format('Emmett said'), lines, cast)

    def test_a_wrong_speaker_also_fails_the_half_rule(self, project_dir):
        """A scripted phrase that is half the split quote matches by the
        half rule; a tag naming someone else rules it out there too."""
        lines, cast = self._lines(project_dir, 'Thomas: "Left hand on the case, always"')
        quote = '"Left hand on the case, always," {}. "Right hand."'
        assert gate._is_plan_conflict(quote.format('Thomas said'), lines, cast)
        assert not gate._is_plan_conflict(quote.format('Emmett said'), lines, cast)

    @pytest.mark.parametrize('people', [
        # no pronouns column
        [{k: v for k, v in p.items() if k != 'pronouns'} for p in PEOPLE],
        # a column, but the speaker's cell is empty or unreadable
        [{**p, 'pronouns': ''} for p in PEOPLE],
        [{**p, 'pronouns': 'he/her'} for p in PEOPLE],
    ])
    def test_a_pronoun_tag_is_unchecked_without_known_pronouns(self, project_dir, people):
        lines, cast = self._lines(project_dir, f'Thomas: "{self.LINE}"', people)
        assert cast.pronouns.get('thomas-bright-horse') is None
        assert gate._is_plan_conflict(self.SPLIT.format(tag='she said'), lines, cast)
        # a name is still checked
        assert not gate._is_plan_conflict(self.SPLIT.format(tag='Emmett said'), lines, cast)

    def test_a_speaker_with_pronouns_she(self, project_dir):
        lines, cast = self._lines(project_dir, f'Cora: "{self.LINE}"')
        assert gate._is_plan_conflict(self.SPLIT.format(tag='she said'), lines, cast)
        assert not gate._is_plan_conflict(self.SPLIT.format(tag='he said'), lines, cast)

    @pytest.mark.parametrize('tag', ['Emmett said', 'she said', 'Thomas said', 'he said'])
    def test_an_unattributed_line_is_matched_as_before(self, project_dir, tag):
        """The real mended-bridle brief names no speakers: nothing to
        check, so any speaker's tag still matches."""
        lines, cast = self._lines(project_dir, f'"You are Cora Dunning." / "{self.LINE}"')
        assert gate._is_plan_conflict(self.SPLIT.format(tag=tag), lines, cast)

    def test_a_name_not_in_the_registry_is_not_a_tag(self, project_dir):
        """C-2: a tag naming someone not in characters.csv is narration: the
        line isn't split, so it isn't set aside."""
        lines, cast = self._lines(project_dir, f'"{self.LINE}"')
        assert not gate._is_plan_conflict(self.SPLIT.format(tag='Naseka said'), lines, cast)

    # -- what the report says (SF-1) ------------------------------------------

    @pytest.mark.parametrize('dialogue, tag, note', [
        ('Thomas: "{line}"', 'Thomas said', 'speaker checked: Thomas Bright Horse'),
        ('Thomas: "{line}"', 'he said', 'speaker checked: Thomas Bright Horse'),
        ('"{line}"', 'Emmett said', 'speaker not checked: the brief names no speaker'),
        ('Lena: "{line}"', 'she said',
         "speaker not checked: Lena Callis's pronouns are not known"),
        ('Thomas: "{line}"', 'I said', 'speaker not checked: the tag says "i"'),
        ('Thomas and Cora: "{line}"', 'Thomas said',
         "speaker not checked: the brief's speaker label is not clear"),
    ])
    def test_the_note_says_whether_the_speaker_was_checked(self, project_dir, dialogue,
                                                           tag, note):
        lines, cast = self._lines(project_dir, dialogue.format(line=self.LINE))
        assert gate._plan_conflict(self.SPLIT.format(tag=tag), lines, cast) == note

    def test_the_note_for_a_shared_name_and_an_unquoted_line(self, project_dir):
        lines, cast = self._lines(project_dir, f'Thomas: "{self.LINE}"', self.TWO_THOMASES)
        assert gate._plan_conflict(self.SPLIT.format(tag='he said'), lines, cast) == (
            'speaker not checked: the brief names a name two characters share')
        lines, cast = self._lines(project_dir, self.LINE)
        assert gate._plan_conflict(self.SPLIT.format(tag='he said'), lines, cast) == (
            'speaker not checked: the brief line has no quote marks')

    def test_the_note_for_a_quote_no_tag_splits(self, project_dir):
        lines, cast = self._lines(project_dir, f'Thomas: "{self.LINE}"')
        assert gate._plan_conflict(f'"{self.LINE}"', lines, cast) == (
            'speaker not checked: no speech tag splits the quote')

    def test_an_unchecked_match_wins_the_note(self, project_dir):
        """Two phrases match, one checked and one not: the conflict was set
        aside without the check, so the note says not checked."""
        lines, cast = self._lines(project_dir, f'Thomas: "{self.LINE}"; "{self.LINE}"')
        assert gate._plan_conflict(self.SPLIT.format(tag='Thomas said'), lines, cast) == (
            'speaker not checked: the brief names no speaker')

    def _gate_split(self, project_dir, tmp_path, dialogue, tag, people=None):
        self._cast(project_dir, people)
        _set_dialogue(project_dir, dialogue)
        quote = self.SPLIT.format(tag=tag)
        with open(os.path.join(project_dir, 'scenes', f'{SCENE}.md'), 'a') as f:
            f.write(f'\n\n{quote}\n')
        finding = {**_contradiction(), 'code': 'TRT', 'scene_quote': quote,
                   'established_scene': 'act1-sc01'}
        return _gate(project_dir, tmp_path, [_commitment()], findings=[finding])

    def test_the_gate_sends_a_wrong_speaker_to_the_fix(self, project_dir, tmp_path):
        result = self._gate_split(project_dir, tmp_path, f'Thomas: "{self.LINE}"',
                                  'Emmett said')
        assert not result.passed and result.plan_conflicts == []
        assert [f.code for f in result.fixable] == ['TRT']

    def test_the_gate_keeps_the_right_speaker_a_plan_conflict(self, project_dir, tmp_path):
        result = self._gate_split(project_dir, tmp_path, f'Thomas: "{self.LINE}"',
                                  'Thomas said')
        assert [f.code for f in result.plan_conflicts] == ['TRT']
        assert gate.problems_to_fix(result) == []
        line = next(x for x in gate.report_lines(result) if x.startswith('PLAN CONFLICT'))
        assert line.endswith('(speaker checked: Thomas Bright Horse)')

    def test_the_report_says_when_the_speaker_was_not_checked(self, project_dir, tmp_path):
        result = self._gate_split(project_dir, tmp_path, f'"{self.LINE}"', 'Emmett said')
        line = next(x for x in gate.report_lines(result) if x.startswith('PLAN CONFLICT'))
        assert line.endswith('(speaker not checked: the brief names no speaker)')

    def test_the_gate_reads_pronouns_from_the_registry(self, project_dir, tmp_path):
        result = self._gate_split(project_dir, tmp_path, f'Thomas: "{self.LINE}"', 'she said')
        assert result.plan_conflicts == [] and [f.code for f in result.fixable] == ['TRT']

    # -- what can't be checked is said (SF-3, SF-4) ---------------------------

    def _logged(self, monkeypatch):
        from storyforge import common
        logged = []
        monkeypatch.setattr(common, 'log', logged.append)
        monkeypatch.setattr(gate, '_WARNED', set())
        return logged

    def test_no_characters_csv_is_a_warning_once(self, project_dir, tmp_path, monkeypatch):
        logged = self._logged(monkeypatch)
        os.remove(os.path.join(project_dir, 'reference', 'characters.csv'))
        _set_dialogue(project_dir, f'Thomas: "{self.LINE}"')
        quote = self.SPLIT.format(tag='he said')
        with open(os.path.join(project_dir, 'scenes', f'{SCENE}.md'), 'a') as f:
            f.write(f'\n\n{quote}\n')
        for run in range(2):
            finding = {**_contradiction(), 'scene_quote': quote}
            result = _gate(project_dir, tmp_path / str(run), [_commitment()],
                           findings=[finding])
            assert len(result.plan_conflicts) == 1
        warned = [x for x in logged if 'characters.csv' in x]
        assert warned == ['WARNING: no reference/characters.csv: the gate checks no speaker '
                          'of a scripted line']

    def test_a_characters_csv_with_no_names_is_a_warning(self, project_dir):
        _set_characters(project_dir, [{'id': 'x', 'name': '', 'aliases': ''}])
        assert gate._cast(project_dir).warnings == (
            'reference/characters.csv has no named characters: the gate checks no speaker '
            'of a scripted line',)

    def test_an_unreadable_pronoun_is_a_warning(self, project_dir, monkeypatch):
        logged = self._logged(monkeypatch)
        people = [{**p, 'pronouns': 'he/her'} if p['id'] == 'thomas-bright-horse' else p
                  for p in self.PEOPLE]
        cast = self._cast(project_dir, people)
        gate._warn_once(cast.warnings)
        gate._warn_once(cast.warnings)
        assert len(logged) == 1
        assert "Thomas Bright Horse's pronouns ('he/her') can't be read" in logged[0]
        assert logged[0].startswith('WARNING: characters.csv:')

    def test_a_readable_cast_has_no_warnings(self, project_dir):
        assert self._cast(project_dir).warnings == ()


def _snap(project_dir, old_scene=None):
    """The book as it is (`gate.snapshot`), with SCENE's prose before the
    pass set to `old_scene` (None: as on disk)."""
    snap = gate.snapshot(project_dir)
    if old_scene is not None:
        snap.scenes[SCENE] = old_scene
    return snap


def _set_dialogue(project_dir, value):
    import csv
    path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f, delimiter='|'))
    for r in rows:
        if r['id'] == SCENE:
            r['key_dialogue'] = value
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter='|', lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


class TestReview480:
    """#480's review: what may count as inherited, and what happens to it."""

    def test_a_scene_waiting_on_the_gate_is_no_baseline(self, project_dir, tmp_path):
        """CR-1/SF-1: a retry that keeps the error the gate failed must not
        pass it as inherited."""
        gate.mark_pending(project_dir, SCENE, 'revise', '1 problem(s) after one fix: TIM')
        snap = gate.snapshot(project_dir)
        assert SCENE not in snap.scenes and 'waiting on the gate' in snap.left_out[SCENE]
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
                       command='revise', before=snap)
        assert not result.passed and result.inherited == []

    def test_an_unreadable_pending_list_trusts_no_scene(self, project_dir):
        path = os.path.join(project_dir, gate.PENDING_PATH)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write('bad header\n')
        snap = gate.snapshot(project_dir)
        assert snap.scenes == {} and all('unreadable' in v for v in snap.left_out.values())

    def test_a_scene_that_is_not_utf8_is_left_out_not_a_crash(self, project_dir):
        """SF-6: one cp1252 scene no longer stops every pass."""
        with open(os.path.join(project_dir, 'scenes', 'act2-sc01.md'), 'wb') as f:
            f.write('caf\xe9'.encode('cp1252'))
        snap = gate.snapshot(project_dir)
        assert 'act2-sc01' not in snap.scenes and 'UnicodeDecodeError' in snap.left_out['act2-sc01']

    def test_a_changed_established_scene_makes_it_new(self, project_dir, tmp_path):
        """CR-3: the scene's words are old, but the other side changed in
        this run, so the contradiction is new."""
        snap = _snap(project_dir, HERE)
        snap.scenes['act1-sc01'] = 'An earlier version of the established scene.'
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
                       command='revise', before=snap)
        assert not result.passed and result.inherited == []

    def test_a_changed_reference_file_makes_it_new(self, project_dir, tmp_path):
        snap = _snap(project_dir, HERE)
        finding = {**_contradiction(), 'established_scene': 'scenes.csv',
                   'established_quote': 'act1-sc01: day 1, morning'}
        snap.files['scenes.csv'] = 'not the current hash'
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[finding],
                       command='revise', before=snap)
        assert result.inherited == []

    def test_an_unchanged_reference_file_keeps_it_inherited(self, project_dir, tmp_path):
        finding = {**_contradiction(), 'established_scene': 'scenes.csv',
                   'established_quote': 'act1-sc01: day 1, morning'}
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[finding],
                       command='revise', before=_snap(project_dir, HERE))
        assert len(result.inherited) == 1

    def test_one_against_the_ledger_is_never_inherited(self, project_dir, tmp_path):
        finding = {**_contradiction(), 'established_scene': ''}
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[finding],
                       command='revise', before=_snap(project_dir, HERE))
        assert result.inherited == []

    def test_the_commitment_stating_it_is_held_back_and_reported(self, project_dir, tmp_path):
        """CR-4/SF-4: the ledger never records a fact the check showed
        contradicts the book."""
        other = _commitment(statement='The vellum was new', quote='She returned to the new map')
        result = _gate(project_dir, tmp_path, [_commitment(), other],
                       findings=[_contradiction()], command='revise',
                       before=_snap(project_dir, HERE))
        assert result.committed
        mine = [r['statement'] for r in ledger.load(project_dir)
                if r['scene_id'] == SCENE and ledger.is_commitment(r)]
        assert mine == ['The vellum was new']
        assert [st for st, _ in result.held_back] == ["Tarren's Hollow had 412 people"]
        assert any(x.startswith('NOTE (not recorded: states a contradiction')
                   for x in gate.report_lines(result))

    def test_it_is_kept_in_the_reported_file_until_the_scene_is_clean(self, project_dir,
                                                                       tmp_path):
        """SF-2: not only in the log."""
        _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
              command='revise', before=_snap(project_dir, HERE))
        rows = gate.reported(project_dir)[SCENE]
        assert [(r['command'], r['source'], r['quote']) for r in rows] == [
            ('revise', 'act1-sc01', HERE)]
        _gate(project_dir, tmp_path, [_commitment()], command='revise')
        assert gate.reported(project_dir) == {}
        assert not os.path.exists(os.path.join(project_dir, gate.REPORTED_PATH))

    def test_a_recheck_does_not_fail_on_one_already_reported(self, project_dir, tmp_path):
        """SF-3: a later re-check (no baseline) finds the same error and
        doesn't blame the scene that triggered it."""
        _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
              command='revise', before=_snap(project_dir, HERE))
        again = _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
                      command='recheck')
        assert again.passed and len(again.inherited) == 1

    def test_a_different_error_in_a_reported_scene_still_blocks(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
              command='revise', before=_snap(project_dir, HERE))
        other = {**_contradiction(), 'established_scene': 'act2-sc01'}
        again = _gate(project_dir, tmp_path, [_commitment()], findings=[other],
                      command='recheck')
        assert not again.passed

    def test_a_short_quote_is_never_inherited(self, project_dir, tmp_path):
        """CR-2: "four hundred" is in any old prose about the village."""
        finding = {**_contradiction(), 'scene_quote': 'four hundred'}
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[finding],
                       command='revise', before=_snap(project_dir, HERE))
        assert result.inherited == []

    def test_a_short_quote_inside_a_brief_line_is_not_a_plan_conflict(self, project_dir,
                                                                       tmp_path):
        """CR-5: 'forty years' is in the scripted line, but the error is the
        prose's to fix."""
        assert not gate._is_plan_conflict('forty years', [
            "It was there forty years ago. It isn't there now. There is no note."], gate.Cast())

    def test_a_short_brief_line_inside_a_long_quote_is_not_a_plan_conflict(self):
        """SF-8: the error ("three moons") is outside the scripted words."""
        assert not gate._is_plan_conflict(
            '"I\'ll see you at dawn," she said, as the three moons rose over the ridge',
            ["I'll see you at dawn"], gate.Cast())
        assert gate._is_plan_conflict('"I\'ll see you at dawn," she said',
                                      ["I'll see you at dawn"], gate.Cast())

    def test_curly_quotes_count_as_scripted(self, project_dir):
        _set_dialogue(project_dir, 'She says \u201cWe leave before the bells.\u201d')
        assert gate._brief_phrases(project_dir, SCENE) == ['We leave before the bells.']

    def test_unverified_findings_are_never_inherited(self, project_dir, tmp_path):
        """Their quotes didn't hold up, so what they quote can't be trusted
        to match the old prose: they block and go to the fix."""
        bad = {**_contradiction(), 'scene_quote': HERE + ' and more that is not in it'}
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[bad],
                       command='revise', before=_snap(project_dir, HERE))
        assert not result.passed and result.inherited == [] and result.unverified


class TestQuotedIn:
    @pytest.mark.parametrize('quote, text, expected', [
        ('Ten days to the pass.', 'He said: "ten  days to the pass" and left.', True),
        ('Ten days.', 'He said: "ten days" and left.', False),          # too short
        ('in the', 'often in the end', False),
        ('On Day 12 there... the junction failed', 'On Day 12 there, the junction failed', True),
        ('the junction failed... On Day 12 there', 'On Day 12 there, the junction failed',
         False),                                                       # out of order
        ('Sam... was twelve', 'Sam ran. She was twelve.', False),       # a part too short
        ('', 'anything', False),
    ])
    def test_matching(self, quote, text, expected):
        assert gate._quoted_in(quote, text) is expected


class TestGateAndFixRoutes:
    def _result(self, *, inherited=(), conflict=False, other=False):
        from storyforge.checker import CheckResult, Finding
        f = Finding('contradiction', 'TIM', 'q', 'act1-sc01', 'e', '', 'why')
        g = Finding('contradiction', 'TRT', 'r', 'act1-sc01', 'e', '', 'why')
        findings = ([f] if conflict else []) + ([g] if other else []) + list(inherited)
        r = gate.GateResult(SCENE, check=CheckResult(SCENE, findings=findings))
        r.inherited = list(inherited)
        r.plan_conflicts = [f] if conflict else []
        return r

    def test_only_plan_conflicts_are_neither_fixed_nor_regated(self, monkeypatch, tmp_path):
        calls = []
        first = self._result(conflict=True)
        monkeypatch.setattr(gate, 'gate_scene', lambda *a, **k: calls.append(k['before']) or first)
        monkeypatch.setattr(gate, 'fix_scene', lambda *a, **k: pytest.fail('fixed'))
        out = gate.gate_and_fix('p', SCENE, command='revise', prose='x',
                                log_dir=str(tmp_path), before='old')
        assert out.result is first and not out.fixed and calls == ['old']

    def test_before_reaches_the_regate(self, monkeypatch, tmp_path):
        calls = []
        runs = iter([self._result(other=True), self._result()])
        monkeypatch.setattr(gate, 'gate_scene',
                            lambda *a, **k: calls.append(k['before']) or next(runs))
        monkeypatch.setattr(gate, 'fix_scene', lambda *a, **k: 'y')
        out = gate.gate_and_fix('p', SCENE, command='revise', prose='x',
                                log_dir=str(tmp_path), before='old')
        assert out.fixed and calls == ['old', 'old']


class _FixRounds:
    """`gate_and_fix` with `gate_scene` and `fix_scene` replaced (`_run`)."""

    PROSE = 'v0'

    def _result(self, *tags, extraction=False):
        from storyforge.checker import CheckResult, Finding
        # one target throughout (same source and established words), so a
        # later round's finding is the problem left, not a new one
        findings = [Finding('contradiction', 'TIM', t, 'act1-sc01',
                            'Dorren Hayle pressed the brass calipers', '', 'why')
                    for t in tags]
        r = gate.GateResult(SCENE, check=CheckResult(SCENE, findings=findings))
        if extraction:
            r.problems = {gate.UNRESOLVED[0]: ['x']}
        return r

    def _run(self, monkeypatch, tmp_path, runs, fixes):
        """`runs`: gate results (or a GateError to raise) in turn; `fixes`:
        (new prose, edits) or a GateError, in turn."""
        runs, fixes = iter(runs), iter(fixes)
        dirs, seen = [], []
        self.fix_dirs = []

        def gate_run(*a, **k):
            dirs.append(k['log_dir'])
            r = next(runs)
            if isinstance(r, Exception):
                raise r
            return r
        monkeypatch.setattr(gate, 'gate_scene', gate_run)

        def fix(scene, prose, result, **k):
            seen.append((prose, list(k['earlier'])))
            self.fix_dirs.append(k['log_dir'])
            if not gate.problems_to_fix(result):   # as fix_scene: no call
                return prose
            nxt = next(fixes)
            if isinstance(nxt, Exception):
                raise nxt
            new, edits = nxt
            k['edits_out'].extend(edits)
            return new
        monkeypatch.setattr(gate, 'fix_scene', fix)
        self.blocked = []
        monkeypatch.setattr(gate, '_note_blocked',
                            lambda pd, sid, cmd, result: self.blocked.append(result))
        out = gate.gate_and_fix('p', SCENE, command='revise', prose=self.PROSE,
                                log_dir=str(tmp_path))
        return out, dirs, seen



class TestSecondFixRound(_FixRounds):
    """2026-11-01: of E8's 28 gated replays, 10 still failed after the one
    fix, most because it half-fixed the finding (He → She with "him" left;
    "eight days" → "five", still off the calendar)."""

    def test_a_second_round_sees_the_first_and_can_pass(self, monkeypatch, tmp_path):
        e1 = [{'find': 'eight days', 'replace': 'five days', 'problem': 1}]
        e2 = [{'find': 'five days', 'replace': 'three days', 'problem': 1}]
        out, dirs, seen = self._run(monkeypatch, tmp_path,
                                    [self._result('eight'), self._result('five'), self._result()],
                                    [('v1', e1), ('v2', e2)])
        assert out.result.passed and out.prose == 'v2' and out.fixed
        assert [r.edits for r in out.rounds] == [e1, e2]
        assert seen[0] == ('v0', []) and seen[1][0] == 'v1'
        assert seen[1][1][0].edits == e1 and 'eight' in seen[1][1][0].problems[0]
        logs = out.log_dir
        assert os.path.dirname(os.path.dirname(logs)) == str(tmp_path)   # tmp/<scene>/<run>
        assert dirs == [logs, os.path.join(logs, 'recheck'), os.path.join(logs, 'recheck-2')]
        assert self.fix_dirs == [logs, os.path.join(logs, 'recheck')]   # beside its run

    def test_it_stops_after_fix_rounds(self, monkeypatch, tmp_path):
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result('a'), self._result('b'), self._result('c')],
                                 [('v1', []), ('v2', [])])
        assert gate.FIX_ROUNDS == 2 and len(dirs) == 3 and len(out.rounds) == 2
        assert not out.result.passed and out.prose == 'v2'

    def test_a_round_that_passes_stops(self, monkeypatch, tmp_path):
        out, dirs, _ = self._run(monkeypatch, tmp_path, [self._result('a'), self._result()],
                                 [('v1', [])])
        assert out.result.passed and len(dirs) == 2 and len(out.rounds) == 1

    def test_a_second_fix_with_no_edits_keeps_the_first_fixs_verdict(self, monkeypatch, tmp_path):
        second = self._result('b')
        out, dirs, _ = self._run(monkeypatch, tmp_path, [self._result('a'), second],
                                 [('v1', []), ('v1', [])])
        assert out.result is second and out.prose == 'v1' and len(dirs) == 2

    def test_plan_conflicts_left_after_a_fix_stop_it(self, monkeypatch, tmp_path):
        second = self._result('b')
        second.plan_conflicts = list(second.findings)
        out, dirs, seen = self._run(monkeypatch, tmp_path, [self._result('a'), second],
                                    [('v1', [])])
        assert out.result is second and len(seen) == 1 and len(dirs) == 2

    # #482's review: a later round never leaves things worse than the one before

    def test_a_failing_second_fix_keeps_round_ones_prose(self, monkeypatch, tmp_path):
        """SF-1: a round-2 GateError threw away a better round-1 scene."""
        r1 = self._result('b')
        out, dirs, _ = self._run(monkeypatch, tmp_path, [self._result('a'), r1],
                                 [('v1', [{'find': 'a', 'replace': 'b'}]),
                                  gate.GateError('occurs 0 times')])
        assert out.prose == 'v1' and out.result is r1 and len(out.rounds) == 1
        assert out.notes == ['fix round 2 failed (occurs 0 times); kept the prose and '
                             'verdict before it']

    def test_a_failing_second_check_keeps_round_ones_prose(self, monkeypatch, tmp_path):
        r1 = self._result('b')
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result('a'), r1, gate.GateError('cut off')],
                                 [('v1', []), ('v2', [])])
        assert out.prose == 'v1' and out.result is r1 and len(dirs) == 3
        assert out.notes[0].startswith('the check after fix round 2 failed (cut off)')

    def test_a_refused_ledger_write_after_round_two_says_so(self, monkeypatch, tmp_path):
        """SF-4: a refused write after a later round was reported as a
        failed check."""
        r1 = self._result('b')
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result('a'), r1,
                                  gate.LedgerWriteRefused('s: ledger write refused: x')],
                                 [('v1', []), ('v2', [])])
        assert out.prose == 'v1' and out.result is r1
        assert out.notes[0].startswith('the ledger write after fix round 2 was refused '
                                       '(s: ledger write refused: x)')

    def test_a_first_round_error_still_carries_the_first_run(self, monkeypatch, tmp_path):
        first = self._result('a')
        with pytest.raises(gate.GateError) as e:
            self._run(monkeypatch, tmp_path, [first, gate.GateError('cut off')], [('v1', [])])
        assert e.value.first is first

    def test_a_second_fix_that_puts_back_removed_words_is_not_gated(self, monkeypatch,
                                                                    tmp_path):
        """SF-2: an undo checked by a lucky pass would commit the first error."""
        r1 = self._result('b')
        out, dirs, _ = self._run(
            monkeypatch, tmp_path, [self._result('a'), r1],
            [('It took five days.', [{'find': 'eight days', 'replace': 'five days'}]),
             ('It took eight days.', [{'find': 'five days', 'replace': 'eight days'}])])
        assert len(dirs) == 2   # the undo was never gated, so never committed
        assert out.prose == 'It took five days.' and out.result is r1
        assert 'put back words an earlier fix removed ("eight days")' in out.notes[0]

    def test_a_second_fix_that_leaves_more_problems_is_discarded(self, monkeypatch, tmp_path):
        """SF-3: round 2's prose was kept even when it was worse."""
        r1 = self._result('b')
        out, _, _ = self._run(monkeypatch, tmp_path,
                              [self._result('a'), r1, self._result('c', 'd', 'e')],
                              [('v1', []), ('v2', [])])
        assert out.prose == 'v1' and out.result is r1 and len(out.rounds) == 1
        assert out.notes[0].startswith('fix round 2 left 3 problem(s), more than the 1')
        assert out.discarded == 2
        assert self.blocked == [r1]   # T-1 (#504's review): the kept run's again

    def test_extraction_only_then_a_fix(self, monkeypatch, tmp_path):
        """T-1: the re-gate counts as round 1; round 2's fix reads the re-gate."""
        out, dirs, seen = self._run(
            monkeypatch, tmp_path,
            [self._result(extraction=True), self._result('a'), self._result('b')],
            [('v1', [{'find': 'x', 'replace': 'y'}])])
        logs = out.log_dir
        assert dirs == [logs, os.path.join(logs, 'recheck'), os.path.join(logs, 'recheck-2')]
        assert self.fix_dirs == [logs, os.path.join(logs, 'recheck')]
        assert seen[1] == ('v0', [])
        assert len(out.rounds) == 1 and out.fixed and not out.result.passed

    def test_extraction_only_twice_stops(self, monkeypatch, tmp_path):
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result(extraction=True), self._result(extraction=True)],
                                 [])
        assert len(dirs) == 2 and out.rounds == [] and not out.fixed

    def test_the_round_cap_is_fix_rounds(self, monkeypatch, tmp_path):
        monkeypatch.setattr(gate, 'FIX_ROUNDS', 3)
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result('a'), self._result('b'), self._result('c'),
                                  self._result('d')],
                                 [('v1', []), ('v2', []), ('v3', [])])
        assert len(dirs) == 4 and len(out.rounds) == 3

    def test_the_prompt_names_the_earlier_edits(self):
        earlier = [gate.FixRound(['TIM contradiction: eight days'],
                                 [{'find': 'eight days', 'replace': 'five days'}])]
        prompt = gate.build_fix_prompt('s', 'Prose.', ['TIM contradiction: five days'],
                                       earlier=earlier)
        assert '## Earlier fixes' in prompt
        assert '- "eight days" became "five days"' in prompt
        assert "don't guess again" in prompt and 'change the rest' in prompt
        assert '## Earlier fixes' not in gate.build_fix_prompt('s', 'Prose.', ['x'])


class TestReextractAMisquote(_FixRounds):
    """#598 (Telemachy, 2026-11-05): a fix's re-check failed only on
    extraction's quote ("she would sit in his father's seat" for the prose's
    "he"). The fix edits prose, so nothing could repair it; the scene
    failed, and `write --keep-going` stopped the run with 18 scenes left. A
    second extraction of the same prose passed."""

    SAID = "she would sit in his father's seat"

    def _misquote(self, *tags, kind='quote', fact='a-fact', quote=SAID):
        r = self._result(*tags)
        rid = f'{SCENE}--{fact}'
        r.problems = {kind: [f'{SCENE}: {rid}']}
        r.proposed = [{'id': rid, 'quote': '' if kind == 'no quote' else quote}]
        return r

    def test_a_recheck_failing_only_on_a_misquote_extracts_again_and_passes(
            self, monkeypatch, tmp_path, capsys):
        e1 = [{'find': 'a', 'replace': 'b', 'problem': 1}]
        out, dirs, seen = self._run(monkeypatch, tmp_path,
                                    [self._result('a'), self._misquote(), self._result()],
                                    [('v1', e1)])
        logs = out.log_dir
        assert dirs == [logs, os.path.join(logs, 'recheck'), os.path.join(logs, 'reextract')]
        assert out.result.passed and out.prose == 'v1'
        assert len(out.rounds) == 1 and len(seen) == 1   # no fix was spent on it
        said = capsys.readouterr().out
        # SF-3 (#602's review): the fact, what was quoted, and what re-runs
        assert (f'{SCENE}: the extractor misquoted the prose ({SCENE}--a-fact: "{self.SAID}" '
                f'is not in the scene); gating the same prose again (extraction and the '
                f'check), not sending it to the fix' in said)
        assert out.reextraction == gate.Reextraction(
            [f'{SCENE}--a-fact: "{self.SAID}" is not in the scene'], gate.REGATE_PASSED)
        assert out.reextraction.summary().endswith(
            'so the same prose was gated again (extraction and the check): it passed')

    def test_a_misquote_after_the_last_round_extracts_again(self, monkeypatch, tmp_path):
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result('a'), self._result('b'), self._misquote(),
                                  self._result()],
                                 [('v1', [{'find': 'a', 'replace': 'b'}]),
                                  ('v2', [{'find': 'b', 'replace': 'c'}])])
        logs = out.log_dir
        assert dirs[-1] == os.path.join(logs, 'reextract') and len(dirs) == 4
        assert out.result.passed and out.prose == 'v2'

    def test_a_missing_quote_is_the_extractors_too(self, monkeypatch, tmp_path):
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result('a'), self._misquote(kind='no quote'),
                                  self._result()],
                                 [('v1', [{'find': 'a', 'replace': 'b'}])])
        assert out.result.passed and len(dirs) == 3
        # SF-3: a missing quote is not called a quote not in the scene
        assert out.reextraction.slips == [f'{SCENE}--a-fact: no quote']

    def test_a_long_quote_is_cut_and_many_slips_are_counted(self):
        r = self._misquote(quote='word ' * 40)
        r.problems['quote'] += [f'{SCENE}: {SCENE}--b', f'{SCENE}: {SCENE}--c',
                                f'{SCENE}: {SCENE}--d']
        slips = gate._describe_slips(r)
        assert slips[0] == (f'{SCENE}--a-fact: "' + ('word ' * 12).strip() + '…" is not in '
                            f'the scene')
        assert slips[1] == f'{SCENE}--b: its quote is not in the scene'   # no such row
        assert gate._slip_text(slips).endswith(f'{SCENE}--c: its quote is not in the scene; '
                                               f'and 1 more')

    def test_a_second_misquote_is_reported_not_repaired(self, monkeypatch, tmp_path):
        """No fuzzy match: the prose's words never replace the quote."""
        again = self._misquote(fact='b-fact', quote='he sat in the seat')
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result('a'), self._misquote(), again],
                                 [('v1', [{'find': 'a', 'replace': 'b'}])])
        assert len(dirs) == 3 and out.result is again and not out.result.passed
        # SF-4 (#602's review): both runs' slips, the first's kept beside the second's
        r = out.reextraction
        assert (r.outcome, r.others) == (gate.REGATE_FAILED, False)
        assert r.slips == [f'{SCENE}--a-fact: "{self.SAID}" is not in the scene']
        assert r.again == [f'{SCENE}--b-fact: "he sat in the seat" is not in the scene']
        assert (f'misquoted the prose ({SCENE}--a-fact: ' in r.summary()
                and f'it misquoted the prose again ({SCENE}--b-fact: ' in r.summary()
                and "no quote is replaced with the prose's words" in r.summary())
        # the stop rule stands: a commit would write the wrong quote
        again._ctx = object()   # as a finished gate run has
        assert gate.can_commit_provisionally(out.result) == (
            'extraction left problems a commit would write')

    def test_findings_the_reextraction_brings_go_to_the_next_fix(self, monkeypatch, tmp_path):
        out, dirs, seen = self._run(monkeypatch, tmp_path,
                                    [self._result('a'), self._misquote(), self._result('b'),
                                     self._result()],
                                    [('v1', [{'find': 'a', 'replace': 'b'}]),
                                     ('v2', [{'find': 'b', 'replace': 'c'}])])
        logs = out.log_dir
        assert dirs == [logs, os.path.join(logs, 'recheck'), os.path.join(logs, 'reextract'),
                        os.path.join(logs, 'recheck-2')]
        assert self.fix_dirs == [logs, os.path.join(logs, 'reextract')]   # beside its run
        assert seen[1][0] == 'v1' and out.result.passed and len(out.rounds) == 2

    def test_once_per_invocation(self, monkeypatch, tmp_path):
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result('a'), self._misquote(), self._result('b'),
                                  self._misquote()],
                                 [('v1', [{'find': 'a', 'replace': 'b'}]),
                                  ('v2', [{'find': 'b', 'replace': 'c'}])])
        assert len(dirs) == 4 and not out.result.passed and out.result.unresolved
        # the one there was: its run went on to round 2's fix
        assert out.reextraction.outcome == gate.REGATE_FAILED and out.reextraction.others
        assert out.reextraction.summary().endswith('it stopped on other problems (listed)')

    def test_round_ones_reroll_is_the_one_reextraction(self, monkeypatch, tmp_path, capsys):
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._misquote(), self._misquote()], [])
        assert len(dirs) == 2 and not out.result.passed
        assert out.reextraction.outcome == gate.REGATE_FAILED   # misquoted again
        assert 'the extractor misquoted the prose' in capsys.readouterr().out

    def test_a_reroll_for_another_extraction_problem_is_no_reextraction(self, monkeypatch,
                                                                         tmp_path):
        """SF-2 (#602's review): only a re-gate for slips is reported as one."""
        first = self._result()
        first.problems = {'ends again': [f'{SCENE}: some-state (resolves: act1-sc01)']}
        out, dirs, _ = self._run(monkeypatch, tmp_path, [first, self._misquote()], [])
        assert len(dirs) == 2 and out.reextraction is None   # and no second regate

    def test_another_extraction_problem_beside_it_is_not_retried(self, monkeypatch, tmp_path):
        mixed = self._misquote()
        mixed.problems['ends again'] = [f'{SCENE}: some-state (resolves: act1-sc01)']
        out, dirs, _ = self._run(monkeypatch, tmp_path, [self._result('a', 'c'), mixed],
                                 [('v1', [{'find': 'a', 'replace': 'b'}])])
        assert len(dirs) == 2 and out.result is mixed and out.reextraction is None

    def test_a_finding_beside_it_goes_to_the_fix_not_a_reextraction(self, monkeypatch,
                                                                    tmp_path):
        """The mixed case: the fix's re-check extracts the edited prose anyway."""
        out, dirs, seen = self._run(monkeypatch, tmp_path,
                                    [self._result('a', 'c'), self._misquote('b'),
                                     self._result()],
                                    [('v1', [{'find': 'a', 'replace': 'b'}]),
                                     ('v2', [{'find': 'b', 'replace': 'c'}])])
        logs = out.log_dir
        assert dirs == [logs, os.path.join(logs, 'recheck'), os.path.join(logs, 'recheck-2')]
        assert len(seen) == 2 and out.result.passed and out.reextraction is None

    def test_a_reextraction_that_fails_keeps_the_verdict_before_it(self, monkeypatch, tmp_path):
        r1 = self._misquote()
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result('a'), r1, gate.GateError('cut off')],
                                 [('v1', [{'find': 'a', 'replace': 'b'}])])
        assert out.result is r1 and out.prose == 'v1' and len(dirs) == 3
        assert out.reextraction.outcome == gate.REGATE_ERROR
        assert out.reextraction.summary().endswith(
            'which could not finish (cut off); the verdict before it stands')

    def test_an_unexpected_error_after_the_last_round_keeps_its_edits(self, monkeypatch,
                                                                       tmp_path):
        """SF-5 (#602's review): an exception other than GateError escaped
        to write's catch-all, which keeps the prose as drafted: both
        rounds' edits were lost and nothing said so."""
        r2 = self._misquote()
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result('a'), self._result('b'), r2,
                                  KeyError('proposed')],
                                 [('v1', [{'find': 'a', 'replace': 'b'}]),
                                  ('v2', [{'find': 'b', 'replace': 'c'}])])
        assert out.prose == 'v2' and out.fixed and len(out.rounds) == 2
        assert out.result is r2 and len(dirs) == 4
        assert out.reextraction.outcome == gate.REGATE_ERROR
        assert "could not finish (KeyError: 'proposed')" in out.reextraction.summary()

    def test_an_unexpected_error_in_a_later_round_keeps_round_ones_edits(self, monkeypatch,
                                                                       tmp_path):
        r1 = self._misquote()
        out, _, _ = self._run(monkeypatch, tmp_path,
                              [self._result('a'), r1, OSError('disk full')],
                              [('v1', [{'find': 'a', 'replace': 'b'}])])
        assert out.prose == 'v1' and out.result is r1
        assert 'could not finish (OSError: disk full)' in out.reextraction.summary()

    def test_a_partial_fix_run_failing_only_on_a_misquote_extracts_again(self, monkeypatch,
                                                                          tmp_path):
        """T-3 (#602's review): the run `_partial_fix` keeps is a re-check too."""
        e1 = [{'find': 'a', 'replace': 'b'}, {'find': 'c', 'replace': 'd'}]
        part_run = self._misquote()
        monkeypatch.setattr(gate, '_worse', lambda *a: 'fix round 1 left more problems')
        monkeypatch.setattr(gate, '_partial_fix',
                            lambda *a, **k: ([e1[0]], 'vp', part_run, '1 edit'))
        out, dirs, seen = self._run(monkeypatch, tmp_path,
                                    [self._result('a', 'c'), self._result('e', 'f', 'g'),
                                     self._result()],
                                    [('v1', e1)])
        logs = out.log_dir
        assert dirs == [logs, os.path.join(logs, 'recheck'), os.path.join(logs, 'reextract')]
        assert out.result.passed and out.prose == 'vp' and len(seen) == 1
        assert out.reextraction.outcome == gate.REGATE_PASSED

    def test_an_inherited_finding_beside_a_misquote_is_extracted_again(self, monkeypatch,
                                                                       tmp_path):
        """T-3: an inherited contradiction doesn't block, so the misquote is
        all that stopped the re-check; the fix is never sent the inherited one."""
        r1 = self._misquote('old')
        r1.inherited = list(r1.check.findings)
        done = self._result('old')
        done.inherited = list(done.check.findings)
        out, dirs, seen = self._run(monkeypatch, tmp_path, [self._result('a'), r1, done],
                                    [('v1', [{'find': 'a', 'replace': 'b'}])])
        assert out.result is done and done.passed and len(dirs) == 3 and len(seen) == 1

    def test_only_extractor_slips(self):
        assert gate._only_extractor_slips(self._misquote()) == [
            f'quote: {SCENE}: {SCENE}--a-fact']
        assert gate._only_extractor_slips(self._misquote(kind='no quote')) == [
            f'no quote: {SCENE}: {SCENE}--a-fact']
        assert gate._only_extractor_slips(self._result()) == []          # passed

    # T-1 (#602's review): each guard, alone beside a misquote, stops the
    # retry (mutating any one of them left every test passing)

    def test_a_finding_beside_the_slip_is_not_slips_only(self):
        assert gate._only_extractor_slips(self._misquote('a')) == []

    def test_a_halt_beside_the_slip_is_not_slips_only(self):
        from storyforge.audit import Halt
        r = self._misquote()
        r.halts = [Halt('fixed', 'some-fact', 'it changes')]
        assert gate._only_extractor_slips(r) == []

    def test_a_plan_conflict_beside_the_slip_is_not_slips_only(self):
        r = self._misquote('a')
        r.plan_conflicts = list(r.findings)
        assert r.fixable == [] and gate._only_extractor_slips(r) == []

    def test_an_unverified_finding_beside_the_slip_is_not_slips_only(self):
        from storyforge.checker import Finding
        r = self._misquote()
        r.check.unverified = [Finding('contradiction', 'TIM', 'q', 'act1-sc01', 'e', '', 'w',
                                      problem='its quote is not in the scene')]
        assert gate._only_extractor_slips(r) == []

    def test_an_unruled_dispute_beside_the_slip_is_not_slips_only(self):
        r = self._misquote()
        from storyforge.checker import Dispute
        r.check.unruled = [Dispute('plan-fact', 'the plan says', 'the scene says')]
        assert gate._only_extractor_slips(r) == []

    @pytest.mark.parametrize('kind', [k for k in gate.UNRESOLVED
                                      if k not in gate._EXTRACTOR_SLIPS])
    def test_another_extraction_problem_beside_the_slip_is_not_slips_only(self, kind):
        r = self._misquote()
        r.problems[kind] = ['x']
        assert gate._only_extractor_slips(r) == []

    def test_an_inherited_finding_beside_the_slip_is_slips_only(self):
        """An inherited contradiction doesn't block: the slip is all that does."""
        r = self._misquote('a')
        r.inherited = list(r.check.findings)
        assert gate._only_extractor_slips(r) == [f'quote: {SCENE}: {SCENE}--a-fact']

    def test_the_slips_are_extraction_problems_that_block(self):
        """TD-3: one spelling of each kind, shared with extraction."""
        from storyforge import extract
        assert gate._EXTRACTOR_SLIPS == (extract.MISQUOTE, extract.NO_QUOTE, 'supersedes',
                                         'ends')
        assert set(gate._EXTRACTOR_SLIPS) <= set(gate.UNRESOLVED)
        assert set(gate._EXTRACTOR_SLIPS) <= set(extract.COMMITMENT_PROBLEMS)

    def test_a_misquote_is_extracted_again_once(self, monkeypatch, tmp_path):
        """#634: a quote stitched from two sentences apart is re-extracted
        once; a second misquote is the verdict, no third run."""
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result('a'), self._misquote(), self._misquote()],
                                 [('v1', [{'find': 'a', 'replace': 'b'}])])
        logs = out.log_dir
        assert dirs == [logs, os.path.join(logs, 'recheck'), os.path.join(logs, 'reextract')]
        assert out.reextraction.outcome == gate.REGATE_FAILED and not out.result.passed

    @pytest.mark.parametrize('kind', ['supersedes', 'ends'])
    def test_a_link_naming_no_fact_in_force_is_extracted_again(self, monkeypatch, tmp_path,
                                                               capsys, kind):
        """#634 (iliad-teen): `ends` named an id the extractor made up from
        the `scene--first-words` pattern. No prose edit repairs it, so it
        earns the one re-extraction, not the fix, and is said for what it is."""
        slip = self._result()
        slip.problems = {kind: [f'{SCENE}: act1-sc01--a-made-up-id']}
        assert gate._only_extractor_slips(slip) == [f'{kind}: {SCENE}: act1-sc01--a-made-up-id']
        assert gate.problems_to_fix(slip) == []
        out, dirs, seen = self._run(monkeypatch, tmp_path,
                                    [self._result('a'), slip, self._result()],
                                    [('v1', [{'find': 'a', 'replace': 'b'}])])
        logs = out.log_dir
        assert dirs == [logs, os.path.join(logs, 'recheck'), os.path.join(logs, 'reextract')]
        assert out.result.passed and len(seen) == 1
        assert out.reextraction.slips == [f'{kind} act1-sc01--a-made-up-id: names no fact '
                                          f'in force']
        said = capsys.readouterr().out
        assert 'the extractor named a fact not in force (' in said
        assert out.reextraction.summary().startswith('the extractor named a fact not in force')

    def test_a_misquote_and_a_bad_link_are_both_named(self):
        r = self._misquote()
        r.problems['ends'] = [f'{SCENE}: act1-sc01--made-up']
        slips = gate._describe_slips(r)
        assert gate._slipped(slips) == 'misquoted the prose or named a fact not in force'
        assert gate._slipped(slips[:1]) == 'misquoted the prose'

    def test_one_regate_per_call(self):
        once = gate._OneRegate()
        assert not once.taken and once.take() and once.taken and not once.take()


@pytest.mark.real_gate
def test_a_misquote_after_a_fix_no_longer_stops_write(project_dir, tmp_path, capsys):
    """#598 end to end, through write's gate step with `--keep-going`: the
    first run's contradiction is fixed, the re-check's extraction misquotes
    the prose, and a second extraction of the same prose passes. The scene
    is committed, so the run goes on, and the re-extraction's spend is a
    `gate` row like the other runs'."""
    from storyforge import cmd_write
    scene_file = os.path.join(project_dir, 'scenes', f'{SCENE}.md')
    with open(scene_file, encoding='utf-8') as f:
        assert HERE in f.read()
    right = 'Blank parchment. Not even a contour line.'
    quotes = iter([right, 'Blank vellum. Not even a contour line.', right])
    calls = []

    def fake(path, body, **k):
        prompt = body['messages'][0]['content']
        if 'tools' in body:
            calls.append('check')
            return _text({'findings': [_contradiction()] if HERE in prompt else [],
                          'kept': []})
        if 'edits' in json.dumps(body.get('output_config', {})):
            calls.append('fix')
            return _text({'edits': [{'problem': 1, 'find': HERE,
                                     'replace': 'a village of some size'}]})
        calls.append('extract')
        return _text({'commitments': [_commitment(statement='The map is blank there',
                                                  quote=next(quotes))]})
    with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)):
        passed, why = cmd_write._gate_drafted_scene(project_dir, SCENE, scene_file, 'draft',
                                                    str(tmp_path / 'logs'), keep_going=True)
    assert (passed, why) == (True, '')
    assert calls == ['extract', 'check', 'fix', 'extract', 'check', 'extract', 'check']
    said = capsys.readouterr().out
    assert 'Gate passed' in said
    # SF-2 (#602's review): the author can see a misquote happened
    assert ('NOTE: the extractor misquoted the prose (' in said
            and '"Blank vellum. Not even a contour line." is not in the scene), so the same '
                'prose was gated again (extraction and the check): it passed' in said)
    mine = [r for r in ledger.load(project_dir) if r['scene_id'] == SCENE
            and ledger.is_commitment(r)]
    assert [r['quote'] for r in mine] == [right]
    with open(scene_file, encoding='utf-8') as f:
        assert 'a village of some size' in f.read()
    assert SCENE not in gate.pending(project_dir)
    with open(os.path.join(project_dir, 'working', 'costs', 'ledger.csv')) as f:
        ops = [line.split('|') for line in f.read().splitlines()]
    op, tokens = ops[0].index('operation'), ops[0].index('input_tokens')
    # every reply 1 token: three gate runs of extraction, persistence and
    # the check, the re-extraction's included, and the one fix
    assert sum(int(r[tokens]) for r in ops[1:] if r[op] == 'gate') == 9
    assert sum(int(r[tokens]) for r in ops[1:] if r[op] == 'gate-fix') == 1


@pytest.mark.real_gate
def test_a_second_misquote_still_stops_write(project_dir, tmp_path):
    """The stop rule stands (#598): a scene whose quote is still not the
    prose's would commit a wrong quote, so it isn't committed provisionally."""
    from storyforge import cmd_write
    scene_file = os.path.join(project_dir, 'scenes', f'{SCENE}.md')
    wrong = 'Blank vellum. Not even a contour line.'
    quotes = iter(['Blank parchment. Not even a contour line.', wrong, wrong])
    calls = []

    def fake(path, body, **k):
        prompt = body['messages'][0]['content']
        calls.append('check' if 'tools' in body else 'fix' if 'edits' in json.dumps(
            body.get('output_config', {})) else 'extract')
        if 'tools' in body:
            return _text({'findings': [_contradiction()] if HERE in prompt else [],
                          'kept': []})
        if 'edits' in json.dumps(body.get('output_config', {})):
            return _text({'edits': [{'problem': 1, 'find': HERE,
                                     'replace': 'a village of some size'}]})
        return _text({'commitments': [_commitment(statement='The map is blank there',
                                                  quote=next(quotes))]})
    with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)):
        passed, why = cmd_write._gate_drafted_scene(project_dir, SCENE, scene_file, 'draft',
                                                    str(tmp_path / 'logs'), keep_going=True)
    assert not passed and 'EXTRACTION: quote' in why
    assert not why.startswith('provisional')
    # T-2 (#602's review): the re-extraction ran (a third extraction)
    assert calls == ['extract', 'check', 'fix', 'extract', 'check', 'extract', 'check']
    # SF-1: the pending reason says the extractor misquoted, twice
    row = gate.pending(project_dir)[SCENE]
    assert row['command'] == 'draft'
    assert ('so the same prose was gated again (extraction and the check): it misquoted the '
            'prose again (' in row['reason'])
    assert "no quote is replaced with the prose's words" in row['reason']


@pytest.mark.real_gate
def test_a_reextraction_that_crashes_keeps_the_fixed_prose_and_says_so(project_dir, tmp_path,
                                                                       monkeypatch):
    """SF-5 (#602's review), through write: the fix's edit is written to the
    scene, and the pending reason names the error, not "the gate failed
    unexpectedly" with the prose as drafted."""
    from storyforge import cmd_write
    scene_file = os.path.join(project_dir, 'scenes', f'{SCENE}.md')
    quotes = iter(['Blank parchment. Not even a contour line.',
                   'Blank vellum. Not even a contour line.'])

    def fake(path, body, **k):
        prompt = body['messages'][0]['content']
        if 'tools' in body:
            return _text({'findings': [_contradiction()] if HERE in prompt else [],
                          'kept': []})
        if 'edits' in json.dumps(body.get('output_config', {})):
            return _text({'edits': [{'problem': 1, 'find': HERE,
                                     'replace': 'a village of some size'}]})
        return _text({'commitments': [_commitment(statement='The map is blank there',
                                                  quote=next(quotes))]})
    real, runs = gate.gate_scene, []

    def gate_run(*a, **k):
        runs.append(k['log_dir'])
        if len(runs) == 3:
            raise KeyError('id')
        return real(*a, **k)
    monkeypatch.setattr(gate, 'gate_scene', gate_run)
    with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)):
        passed, why = cmd_write._gate_drafted_scene(project_dir, SCENE, scene_file, 'draft',
                                                    str(tmp_path / 'logs'), keep_going=True)
    assert not passed and runs[-1].endswith('reextract')
    with open(scene_file, encoding='utf-8') as f:
        assert 'a village of some size' in f.read()
    reason = gate.pending(project_dir)[SCENE]['reason']
    assert "could not finish (KeyError: 'id'); the verdict before it stands" in reason
    assert 'failed unexpectedly' not in reason


class TestFirstFixNeverWorse(_FixRounds):
    """mended-bridle (2026-11-03): the draft gave Cora the left-hand grip its
    brief and the ledger give. The check reported it against a later scene
    (the one in error) with two real problems; the first fix made the scene
    match that scene, and its re-check failed on one broken promise, in the
    words the fix wrote. Round 1's prose was kept unconditionally, so the
    worse scene was written."""

    TAIL = (' Out on the flat the wind had dropped. Emmett walked the roan along the fence '
            'line and counted the posts, and the sun stood a hand above the ridge.')
    PROSE = ('A man had lain on the shelf for two days. She took the case in her left hand, '
             'the strap looped between two fingers. Her right hand came up empty to the '
             'cheekpiece. The coffeepot sat cold on the stove.' + TAIL)
    FIXED = ('A man had lain on the shelf. She kept the case on her right shoulder, two '
             'fingers hooked under the strap. Her left hand came up to the cheekpiece. The '
             'coffeepot was already hot on the stove.' + TAIL)
    EDITS = [{'problem': 1, 'find': ' for two days', 'replace': ''},
             {'problem': 3, 'find': 'took the case in her left hand',
              'replace': 'kept the case on her right shoulder'}]

    def _finding(self, kind, quote, source='cache', established='the case riding her '
                 'right shoulder the way her father had', fact_id='', code='TRT'):
        from storyforge.checker import Finding
        return Finding(kind, code, quote, source, established, fact_id, 'why')

    def _with(self, *findings):
        from storyforge.checker import CheckResult
        return gate.GateResult(SCENE, check=CheckResult(SCENE, findings=list(findings)))

    def _first(self):
        return self._with(
            self._finding('contradiction', 'A man had lain on the shelf for two days',
                          source='judges-morning', established='Watch her. Route, methods, '
                          'schedule.', code='PHY'),
            self._finding('contradiction', 'The coffeepot sat cold on the stove',
                          established='He had had it on since he saw the dust', code='PHY'),
            self._finding('contradiction', 'She took the case in her left hand'))

    def _promise(self, quote):
        return self._finding('broken-promise', quote, source='',
                             established='"Left hand on the case. Right hand free."',
                             fact_id='key_dialogue', code='PRM')

    def test_a_first_fix_that_breaks_a_promise_in_its_own_words_is_discarded(
            self, monkeypatch, tmp_path):
        first = self._first()
        again = self._with(self._promise('She kept the case on her right shoulder'))
        # the retry with the edit that didn't do it (#556) can't finish
        out, dirs, _ = self._run(monkeypatch, tmp_path, [first, again, GateError('x')],
                                 [(self.FIXED, self.EDITS)])
        assert _blocking_count(again) < _blocking_count(first)   # fewer, and still worse
        assert out.prose == self.PROSE and not out.fixed and out.discarded == 1
        assert out.result is first and out.first is first and out.rounds == []
        assert len(dirs) == 3   # the partial retry; no second round on discarded prose
        assert dirs[2].endswith('partial-1')
        assert out.notes[0].startswith('fix round 1 brought in 1 problem(s) (PRM breaks the '
                                       'brief [key_dialogue]')
        assert out.notes[0].endswith('kept the prose as given and the first verdict')
        assert self.blocked == [first]   # gate-blocked.csv is the kept run's again

    def test_a_first_fix_that_leaves_more_problems_is_discarded(self, monkeypatch, tmp_path):
        first = self._with(self._finding('contradiction', 'The coffeepot sat cold on the '
                                         'stove', code='PHY'))
        again = self._with(*[self._finding('contradiction', q, source=s, code='PHY')
                             for q, s in (('words not in the scene', 'x'),
                                          ('other words not in it', 'y'))])
        out, _, _ = self._run(monkeypatch, tmp_path, [first, again],
                              [(self.FIXED, self.EDITS)])
        assert out.prose == self.PROSE and out.result is first
        assert out.notes[0].startswith('fix round 1 left 2 problem(s), more than the 1')
        # SF-3 (#504's review): they couldn't be placed, and that is said
        assert out.notes[1] == ('fix round 1: 2 new finding(s) of the check after it could '
                                'not be placed in the fixed prose (PHY vs x, PHY vs y): '
                                'judged by the problem count only')

    def test_findings_in_words_the_fix_left_alone_do_not_count_against_it(self, monkeypatch,
                                                                          tmp_path):
        """E4's missing-persons (2026-11-03): the fix cleared both first
        findings and the re-check found four new ones, all in words it
        hadn't touched. They are in the prose as given too: a plain count
        threw away a good fix."""
        first = self._first()
        alone = ['the wind had dropped', 'Emmett walked the roan', 'counted the posts',
                 'a hand above the ridge']
        again = self._with(*[self._finding('contradiction', q, source=f's{i}', code='TIM')
                             for i, q in enumerate(alone)])
        out, _, _ = self._run(monkeypatch, tmp_path, [first, again],
                              [(self.FIXED, self.EDITS), (self.FIXED, [])])
        assert out.prose == self.FIXED and out.result is again and out.notes == []

    def test_a_finding_next_to_the_words_a_fix_put_in_counts(self, monkeypatch, tmp_path):
        """E4's missing-persons, round 2: the fix added words right after
        "Seven forty-one." and the re-check still found the calendar wrong.
        The first quote, untouched but next to the insert, was what it
        fixed: it counts, so two findings after against four before is not
        worse."""
        before, after = 'She picked up the phone. Seven forty-one. The coffee was cold.', (
            'She picked up the phone. Seven forty-one, the morning after. The coffee was cold.')
        f = self._finding('contradiction', 'She picked up the phone. Seven forty-one.',
                          source='scenes.csv')
        d = gate._diff(before, after)
        assert not gate._in_untouched_text(f, d.before_spans, d.before)
        assert not gate._in_untouched_text(self._finding('contradiction', 'The coffee was '
                                                         'cold'), d.before_spans, d.before)
        far = before + ' ' + 'Nothing else moved in the house that morning.'
        d = gate._diff(far, after + far[len(before):])
        assert gate._in_untouched_text(self._finding('contradiction', 'in the house that '
                                                     'morning'), d.before_spans, d.before)

    @pytest.mark.parametrize('gap, alone', [(3, False), (4, True), (5, True)])
    def test_away_from_the_fix_means_four_unchanged_words_between(self, gap, alone):
        """TD-5 (#504's review): code and docs say the same thing."""
        filler = ' '.join(f'w{i}' for i in range(gap))
        before = f'alpha beta gamma {filler} one two three'
        after = f'alpha beta CHANGED {filler} one two three'
        d = gate._diff(before, after)
        f = self._finding('contradiction', 'one two three')
        assert gate._in_untouched_text(f, d.after_spans, d.after) is alone

    def test_a_new_finding_in_words_the_fix_left_alone_is_not_the_fixs(self, monkeypatch,
                                                                        tmp_path):
        """Two readings of the same words differ: a re-check finds things the
        first run didn't, and that doesn't make the fix worse."""
        first = self._first()
        again = self._with(self._finding('contradiction', 'A man had lain on the shelf',
                                         source='arrival', code='PHY'))
        out, _, _ = self._run(monkeypatch, tmp_path, [first, again],
                              [(self.FIXED, self.EDITS), (self.FIXED, [])])
        assert out.prose == self.FIXED and out.result is again and out.notes == []
        assert len(out.rounds) == 1

    def test_a_problem_the_fix_did_not_clear_is_not_one_it_brought_in(self, monkeypatch,
                                                                      tmp_path):
        """The same contradiction (same source, same established words) in
        the rewritten words: a half-fix. The fix didn't clear it, it didn't
        make it, and round 2 is for it (T-3, #504's review: round 2 runs)."""
        first = self._first()
        again = self._with(self._finding('contradiction', 'She kept the case on her right '
                                         'shoulder'))
        last = self._with()
        v2 = self.FIXED.replace('right shoulder', 'left hand')
        out, dirs, seen = self._run(monkeypatch, tmp_path, [first, again, last],
                                    [(self.FIXED, self.EDITS),
                                     (v2, [{'find': 'right shoulder', 'replace': 'left hand'}])])
        assert len(seen) == 2 and len(dirs) == 3 and seen[1][0] == self.FIXED
        assert out.prose == v2 and out.result is last and out.notes == []

    def test_another_contradiction_with_the_same_file_is_new(self, monkeypatch, tmp_path):
        """CR-3/SF-4 (#504's review): a bible or the calendar is one source
        for many facts; a fix that swaps one contradiction with it for
        another (other established words) made the new one."""
        first = self._first()
        again = self._with(self._finding('contradiction', 'She kept the case on her right '
                                         'shoulder', established='Thomas watched the strap '
                                         'go slack in her fingers'))
        out, _, _ = self._run(monkeypatch, tmp_path, [first, again, GateError('x')],
                              [(self.FIXED, self.EDITS)])
        assert out.prose == self.PROSE and out.result is first
        assert out.notes[0].startswith('fix round 1 brought in 1 problem(s) (TRT contradicts '
                                       'cache')

    def test_the_edits_that_held_are_kept_when_one_broke_a_promise(self, monkeypatch,
                                                                    tmp_path):
        """B-030 (#556): one fix rewrote three problems; the third edit broke
        the brief, and the whole fix (the two good ones with it) was thrown
        away. Now the edit that brought the problem in is dropped, the rest
        re-gated, and kept when that isn't worse."""
        first = self._first()
        again = self._with(self._promise('She kept the case on her right shoulder'))
        partial = gate.GateResult(SCENE)   # no check problems: passed
        partial.check = __import__('storyforge.checker', fromlist=['CheckResult']).CheckResult(
            SCENE, findings=[])
        out, dirs, _ = self._run(monkeypatch, tmp_path, [first, again, partial],
                                 [(self.FIXED, self.EDITS)])
        assert out.result is partial and out.fixed and out.discarded == 0
        assert out.prose == self.PROSE.replace(' for two days', '')
        assert [r.edits for r in out.rounds] == [[self.EDITS[0]]]
        assert 'kept its 1 edit(s) that did not' in out.notes[0]
        assert 'took the case in her left hand' in out.notes[0]

    def test_a_partial_fix_that_is_worse_is_discarded_too(self, monkeypatch, tmp_path):
        first = self._first()
        again = self._with(self._promise('She kept the case on her right shoulder'))
        worse = self._with(*[self._finding('contradiction', q, source=s, code='PHY')
                             for q, s in (('a', 'x'), ('b', 'y'), ('c', 'z'), ('d', 'w'))])
        out, _, _ = self._run(monkeypatch, tmp_path, [first, again, worse],
                              [(self.FIXED, self.EDITS)])
        assert out.result is first and out.prose == self.PROSE and out.discarded == 1

    def test_a_single_edit_fix_is_not_retried(self, monkeypatch, tmp_path):
        first = self._first()
        again = self._with(self._promise('She kept the case on her right shoulder'))
        out, dirs, _ = self._run(monkeypatch, tmp_path, [first, again],
                                 [(self.FIXED, [self.EDITS[1]])])
        assert out.result is first and len(dirs) == 2

    @pytest.mark.parametrize('before, after, persists', [
        # the same scripted line broken again: the problem left, not a new one
        (('key_dialogue', '"Left hand on the case. Right hand free."'),
         ('key_dialogue', '"Left hand on the case. Right hand free."'), True),
        # another scripted line of the same field: a new promise broken
        (('key_dialogue', '"Left hand on the case. Right hand free."'),
         ('key_dialogue', '"You are Cora Dunning."'), False),
        # a registry promise: the id is the promise
        (('rowan-field-books-cached', 'x'), ('rowan-field-books-cached', 'y'), True),
    ])
    def test_the_same_promise_persists(self, before, after, persists):
        """T-2 (#504's review): the broken-promise branch of _persists."""
        a = self._finding('broken-promise', '', source='', fact_id=after[0],
                          established=after[1], code='PRM')
        b = self._finding('broken-promise', '', source='', fact_id=before[0],
                          established=before[1], code='PRM')
        assert gate._persists(a, [b]) is persists

    @pytest.mark.parametrize('fact_a, fact_b, persists', [
        ('cora-left-hand', 'cora-left-hand', True),
        ('cora-left-hand', 'rowan-right-shoulder', False),
        ('', '', False),   # no source, no fact: not shown to be the same
    ])
    def test_a_ledger_contradiction_persists_by_fact_id(self, fact_a, fact_b, persists):
        """T-2: a contradiction with the ledger (no source scene)."""
        est = 'Cora carries the transit case in her left hand'
        a = self._finding('contradiction', 'q', source='', fact_id=fact_a, established=est)
        b = self._finding('contradiction', 'q', source='', fact_id=fact_b, established=est)
        assert gate._persists(a, [b]) is persists

    def test_a_fix_that_takes_out_a_promises_words_is_discarded(self, monkeypatch, tmp_path):
        """CR-2 (#504's review): the re-check reports the promise broken with
        no quote (its words are gone), the count is unchanged, and the fix
        was kept."""
        first = self._with(self._finding('contradiction', 'The coffeepot sat cold on the '
                                         'stove', code='PHY'))
        again = self._with(self._promise(''))
        out, _, _ = self._run(monkeypatch, tmp_path, [first, again], [(self.FIXED, self.EDITS)])
        assert out.prose == self.PROSE and out.result is first
        assert out.notes[0].startswith('fix round 1 brought in 1 problem(s) (PRM breaks')

    def test_a_new_broken_promise_far_from_the_fix_is_not_its(self, monkeypatch, tmp_path):
        """Its nearest words are in a paragraph the fix never came near: a
        reading's variance, as for a contradiction."""
        first = self._with(self._finding('contradiction', 'The coffeepot sat cold on the '
                                         'stove', code='PHY'))
        again = self._with(self._promise('a hand above the ridge'))
        out, _, _ = self._run(monkeypatch, tmp_path, [first, again],
                              [(self.FIXED, self.EDITS), (self.FIXED, [])])
        assert out.prose == self.FIXED and out.result is again and out.notes == []

    def test_a_quote_across_words_the_fix_took_out_is_the_fixs(self):
        before = 'He did not see her. She rode on.'
        after = 'He did see her. She rode on.'
        d = gate._diff(before, after)
        changed, words = d.after_spans, d.after
        f = self._finding('contradiction', 'He did see her')
        assert gate._in_edited_text(f, changed, words)
        assert not gate._in_edited_text(self._finding('contradiction', 'She rode on'),
                                        changed, words)

    def test_a_quote_found_outside_the_edit_too_is_not_tied_to_it(self):
        before = 'The river ran high. The road was dry.'
        after = 'The river ran high. The road was dry. The river ran high.'
        f = self._finding('contradiction', 'The river ran high')
        d = gate._diff(before, after)
        assert not gate._in_edited_text(f, d.after_spans, d.after)

    def test_a_reroll_with_no_edit_keeps_its_verdict(self, monkeypatch, tmp_path):
        """Extraction-only: the same prose gated again, its verdict stands
        even with more problems (they are the prose's, not a fix's)."""
        again = self._result('a', 'b')
        out, dirs, _ = self._run(monkeypatch, tmp_path,
                                 [self._result(extraction=True), again, self._result('c')],
                                 [(self.PROSE, [])])
        assert out.notes == [] and out.result is again and len(dirs) == 2

    def test_a_pass_after_the_first_fix_is_kept(self, monkeypatch, tmp_path):
        out, _, _ = self._run(monkeypatch, tmp_path, [self._first(), self._with()],
                              [(self.FIXED, self.EDITS)])
        assert out.result.passed and out.prose == self.FIXED and out.fixed


def _blocking_count(result):
    return gate._blocking_count(result)


class TestDiscardKeepsTheBlockedList:
    """T-1/SF-1 (#504's review): after a discard, working/gate-blocked.csv
    lists the kept run's contradictions, written for real; when it can't be
    written, the discard still returns the kept prose, says so, and
    `check --accept` refuses rows for prose not on disk."""

    PROSE = TestFirstFixNeverWorse.PROSE
    FIXED = TestFirstFixNeverWorse.FIXED

    def _runs(self, monkeypatch, project_dir, first, again):
        runs = iter([first, again])

        def gate_run(pd, sid, *, command, **k):
            r = next(runs)
            gate._note_blocked(pd, sid, command, r)   # as the real gate does on a fail
            return r
        monkeypatch.setattr(gate, 'gate_scene', gate_run)
        monkeypatch.setattr(gate, 'fix_scene', lambda sid, prose, result, **k: (
            k['edits_out'].append({'find': 'x', 'replace': 'y'}) or self.FIXED))
        monkeypatch.setattr(gate, '_brief_phrases', lambda *a: [])

    def _first_and_worse(self):
        t = TestFirstFixNeverWorse()
        first = t._with(t._finding('contradiction', 'The coffeepot sat cold on the stove',
                                   code='PHY'))
        again = t._with(t._finding('contradiction', 'She kept the case on her right shoulder',
                                   established='Thomas watched the strap go slack in her '
                                   'fingers'))
        return first, again

    def test_the_file_is_put_back_to_the_kept_run(self, project_dir, monkeypatch, tmp_path):
        first, again = self._first_and_worse()
        self._runs(monkeypatch, project_dir, first, again)
        out = gate.gate_and_fix(project_dir, SCENE, command='draft', prose=self.PROSE,
                                log_dir=str(tmp_path))
        assert out.discarded == 1 and out.blocked_stale == ''
        assert [r['quote'] for r in gate.blocked(project_dir)[SCENE]] == [
            'The coffeepot sat cold on the stove']

    def test_the_advisory_list_is_put_back_to_the_kept_run(self, project_dir, monkeypatch,
                                                           tmp_path):
        """T4 (#642's review): the discarded fix's advisory promises don't
        replace the kept run's."""
        from storyforge.checker import Finding
        first, again = self._first_and_worse()
        first.advisory = [Finding('broken-promise', 'PRM', '', '', 'Finds nothing',
                                  'key_actions', 'kept run')]
        again.advisory = [Finding('broken-promise', 'PRM', '', '', 'Searches removal logs',
                                  'key_actions', 'discarded fix')]
        runs = iter([first, again])

        def gate_run(pd, sid, *, command, **k):
            r = next(runs)
            gate._note_advisory(pd, sid, command, r, prose='x')   # as the real gate does
            gate._note_blocked(pd, sid, command, r)
            return r
        monkeypatch.setattr(gate, 'gate_scene', gate_run)
        monkeypatch.setattr(gate, 'fix_scene', lambda sid, prose, result, **k: (
            k['edits_out'].append({'find': 'x', 'replace': 'y'}) or self.FIXED))
        monkeypatch.setattr(gate, '_brief_phrases', lambda *a: [])
        out = gate.gate_and_fix(project_dir, SCENE, command='draft', prose=self.PROSE,
                                log_dir=str(tmp_path))
        assert out.discarded == 1
        assert [r['quote'] for r in gate.advisories(project_dir)[SCENE]] == ['Finds nothing']

    def test_a_file_that_cannot_be_written_is_said_and_the_prose_kept(
            self, project_dir, monkeypatch, tmp_path):
        first, again = self._first_and_worse()
        self._runs(monkeypatch, project_dir, first, again)
        real = gate.record_blocked
        calls = []

        def flaky(pd, sid, command, findings, **kw):
            calls.append(findings)
            if len(calls) == 3:   # the put-back after the discard
                raise PermissionError('read-only')
            return real(pd, sid, command, findings, **kw)
        monkeypatch.setattr(gate, 'record_blocked', flaky)
        out = gate.gate_and_fix(project_dir, SCENE, command='draft', prose=self.PROSE,
                                log_dir=str(tmp_path))
        assert out.prose == self.PROSE and out.discarded == 1
        assert 'read-only' in out.blocked_stale
        assert any(n.startswith('WARNING: ') and 'check --accept' in n for n in out.notes)
        # the file still describes the discarded fix's prose: accept refuses it
        with open(os.path.join(project_dir, 'scenes', f'{SCENE}.md'), 'w') as f:
            f.write(self.PROSE)
        with pytest.raises(gate.GateError, match='describes other prose; nothing accepted'):
            gate.accept_blocked(project_dir, SCENE)
        assert gate.reported(project_dir) == {}

    @pytest.mark.real_gate
    def test_write_names_a_stale_list_in_the_pending_reason(self, project_dir, monkeypatch):
        from storyforge import cmd_write
        from storyforge.checker import CheckResult, Finding
        bad = Finding('contradiction', 'TIM', 'q', 'act1-sc01', 'e', '', 'why')
        r = gate.GateResult('act1-sc01', check=CheckResult('act1-sc01', findings=[bad]))
        monkeypatch.setattr(gate, 'gate_and_fix', lambda *a, **k: gate.GatedScene(
            'prose', r, r, discarded=1, blocked_stale='working/gate-blocked.csv could not '
            'be updated: read-only'))
        path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        passed, why = cmd_write._gate_drafted_scene(project_dir, 'act1-sc01', path, 'draft',
                                                    str(project_dir))
        assert not passed and 'could not be updated: read-only' in why
        assert '`storyforge check act1-sc01`' in why


class TestRunLogs:
    """Callers pass a fixed log dir (working/logs/gate, working/logs/check)
    and the files are named by scene alone, so a later gate run of a scene,
    or a re-check of it in the same run, overwrote the earlier run's record
    (2026-11-03: mended-bridle's first fix log was gone by the time anyone
    looked)."""

    def test_each_call_gets_its_own_directory_under_the_scene(self, tmp_path):
        """T-5 (#504's review): the clock and pid are injected, so a second
        boundary between the calls can't change what is asserted."""
        from datetime import datetime
        when = datetime(2026, 11, 3, 8, 2, 38)
        a = gate.run_log_dir(str(tmp_path), SCENE, now=when, pid=42)
        b = gate.run_log_dir(str(tmp_path), SCENE, now=when, pid=42)
        c = gate.run_log_dir(str(tmp_path), SCENE, now=when, pid=42)
        assert [os.path.relpath(x, tmp_path) for x in (a, b, c)] == [
            os.path.join(SCENE, '20261103-080238-42'),
            os.path.join(SCENE, '20261103-080238-42-2'),
            os.path.join(SCENE, '20261103-080238-42-3')]
        assert all(os.path.isdir(x) for x in (a, b, c))

    def test_the_default_stamp_is_the_clock_and_pid(self, tmp_path):
        a = gate.run_log_dir(str(tmp_path), SCENE)
        assert os.path.basename(a).endswith(f'-{os.getpid()}')
        assert os.path.dirname(a) == str(tmp_path / SCENE)

    def test_a_directory_that_cannot_be_made_is_a_gate_error(self, tmp_path):
        """SF-5 (#504's review): a makedirs failure was a traceback."""
        blocker = tmp_path / 'logs'
        blocker.write_text('a file where the directory goes')
        with pytest.raises(gate.GateError, match="can't make the gate log directory"):
            gate.run_log_dir(str(blocker), SCENE)

    def test_a_recheck_whose_logs_cannot_be_made_is_listed_failed(self, project_dir,
                                                                   tmp_path, monkeypatch):
        """SF-5: the re-check says why and stops, never a traceback."""
        blocker = tmp_path / 'logs'
        blocker.write_text('x')
        monkeypatch.setattr('storyforge.costs.check_threshold', lambda cost: True)
        gate.mark_pending(project_dir, SCENE, gate.RECHECK, 'x')
        run = gate.recheck_pending(project_dir, log_dir=str(blocker))
        assert run.failed == SCENE and "can't make the gate log directory" in run.why
        assert gate.pending(project_dir)[SCENE]['command'] == gate.RECHECK_FAILED

    def test_two_gate_and_fix_runs_keep_both_logs(self, monkeypatch, tmp_path):
        from storyforge.checker import CheckResult, Finding
        bad = Finding('contradiction', 'TIM', 'q', 'act1-sc01', 'e', '', 'why')

        def gate_run(pd, sid, *, log_dir, prose, **k):
            with open(os.path.join(log_dir, f'gate-check-{sid}.json'), 'w') as f:
                f.write(prose)
            return gate.GateResult(sid, check=CheckResult(sid, findings=[bad]))
        monkeypatch.setattr(gate, 'gate_scene', gate_run)
        monkeypatch.setattr(gate, 'fix_scene', lambda sid, prose, *a, **k: prose)
        one = gate.gate_and_fix('p', SCENE, command='draft', prose='first run',
                                log_dir=str(tmp_path))
        two = gate.gate_and_fix('p', SCENE, command='draft', prose='second run',
                                log_dir=str(tmp_path))
        assert one.log_dir != two.log_dir
        for out, text in ((one, 'first run'), (two, 'second run')):
            with open(os.path.join(out.log_dir, f'gate-check-{SCENE}.json')) as f:
                assert f.read() == text

    def test_a_gate_error_names_its_logs(self, monkeypatch, tmp_path):
        def fail(*a, **k):
            raise gate.GateError('cut off')
        monkeypatch.setattr(gate, 'gate_scene', fail)
        with pytest.raises(gate.GateError) as e:
            gate.gate_and_fix('p', SCENE, command='draft', prose='x', log_dir=str(tmp_path))
        assert e.value.log_dir.startswith(str(tmp_path / SCENE)) and e.value.first is None

    def test_each_recheck_gets_its_own_directory(self, project_dir, tmp_path, monkeypatch):
        dirs = []

        def fake(pd, sid, **k):
            dirs.append(k['log_dir'])
            if len(dirs) == 1:   # the first re-check lists the scene again
                gate.mark_pending(pd, sid, gate.RECHECK, 're-check: again')
            else:
                gate.clear_pending(pd, sid)
            r = gate.GateResult(sid, check=None)
            r.committed = True
            return r
        monkeypatch.setattr(gate, 'gate_scene', fake)
        monkeypatch.setattr(gate, '_writer', lambda pd, sid: 'draft')
        monkeypatch.setattr('storyforge.costs.check_threshold', lambda cost: True)
        gate.mark_pending(project_dir, SCENE, gate.RECHECK, 'x')
        gate.recheck_pending(project_dir, log_dir=str(tmp_path))
        assert len(dirs) == 2 and dirs[0] != dirs[1]
        assert all(os.path.dirname(d) == str(tmp_path / 'recheck' / SCENE) for d in dirs)


def test_an_unquoted_action_is_not_the_briefs_words(project_dir):
    """act1-sc02's key_actions ("Discovers missing village") paraphrase; a
    scene saying so isn't in conflict with the plan."""
    assert all('village' not in p for p in gate._brief_phrases(project_dir, SCENE))


class TestFixConverges:
    """2026-11-01: in all 14 of E8's failed clean replays the one fix
    cleared the first findings and made new ones (Tam's age seven → nine,
    Sera Holdt renamed Wenna Marsh, a scripted line changed)."""

    def test_the_rules_say_take_the_books_value_or_drop_the_detail(self):
        prompt = gate.build_fix_prompt('s', 'Prose.', ['TIM contradiction: ...'])
        assert "Take the book's value, never a new one." in prompt
        assert 'remove the detail or make it vague' in prompt
        assert "don't rename a character" in prompt
        assert 'Lines the brief scripts' not in prompt   # none to keep

    def test_the_briefs_lines_are_listed_to_keep(self):
        prompt = gate.build_fix_prompt('s', 'Prose.', ['x'], ['Vasht. Six days ago.'])
        assert '## Lines the brief scripts' in prompt
        assert '- "Vasht. Six days ago."' in prompt

    def test_gate_and_fix_protects_the_brief_lines_the_scene_has(self, project_dir, monkeypatch,
                                                              tmp_path):
        from storyforge.checker import CheckResult, Finding
        bad = Finding('contradiction', 'TIM', 'q', 'act1-sc01', 'e', '', 'why')
        first = gate.GateResult(SCENE, check=CheckResult(SCENE, findings=[bad]))
        monkeypatch.setattr(gate, 'gate_scene', lambda *a, **k: first)
        seen = []
        monkeypatch.setattr(gate, 'fix_scene', lambda *a, **k: seen.append(k['protected']) or a[1])
        prose = '"It was there forty years ago. It isn\'t there now. There is no note."'
        gate.gate_and_fix(project_dir, SCENE, command='revise', prose=prose,
                          log_dir=str(tmp_path))
        assert seen == [["It was there forty years ago. It isn't there now. There is no note."]]
        seen.clear()   # a line the scene doesn't have isn't sent: nothing to keep
        gate.gate_and_fix(project_dir, SCENE, command='revise', prose='Other words.',
                          log_dir=str(tmp_path))
        assert seen == [[]]


def test_a_recheck_is_gated_against_its_own_prose_only(project_dir, tmp_path, monkeypatch):
    """#480's review: a re-check runs because another scene changed, not this
    one's words; a baseline of the book would make every finding inherited.
    #631: its baseline is the scene's own gated prose alone, so only a
    finding within the scene can be inherited."""
    gate.mark_pending(project_dir, SCENE, 'recheck', 'x')
    monkeypatch.setattr(gate, 'gated_prose', lambda pd, sid: ('The gated prose.', ''))
    kwargs = []

    def fake(pd, sid, **k):
        kwargs.append(k)
        gate.clear_pending(pd, sid)
        r = gate.GateResult(sid, check=None)
        r.committed = True
        return r
    monkeypatch.setattr(gate, 'gate_scene', fake)
    monkeypatch.setattr(gate, '_writer', lambda pd, sid: 'draft')
    gate.recheck_pending(project_dir, log_dir=str(tmp_path))
    assert kwargs and all(k['before'].scenes == {SCENE: 'The gated prose.'}
                          and k['before'].files == {} for k in kwargs)


@pytest.mark.gate_readings
class TestTwoReadings:
    """The gate reads each scene `GATE_READINGS` times and blocks on the
    union: a finding only the second reading makes still stops the commit."""

    def _gate(self, project_dir, tmp_path, by_reading, **kw):
        checks = []

        def fake(path, body, **k):
            if 'tools' in body:
                prompt = body['messages'][0]['content']
                n = 2 if 'Reading 2:' in prompt else 1
                checks.append(n)
                return _text({'findings': by_reading.get(n, []), 'kept': []})
            return _text({'commitments': [_commitment()]})
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)):
            result = gate_scene(project_dir, SCENE, command=kw.pop('command', 'draft'),
                                log_dir=str(tmp_path / 'logs'), extract_model='m',
                                check_model='m', **kw)
        return result, checks

    def test_the_gate_takes_two_readings(self, project_dir, tmp_path):
        from storyforge import gate
        assert gate.GATE_READINGS == 2
        result, checks = self._gate(project_dir, tmp_path, {})
        assert checks == [1, 2] and result.check.readings == 2
        assert result.passed and result.committed
        assert (tmp_path / 'logs' / f'gate-check-{SCENE}.r2.json').exists()

    def test_a_finding_only_the_second_reading_makes_blocks(self, project_dir, tmp_path):
        result, _ = self._gate(project_dir, tmp_path, {2: [_contradiction()]})
        assert not result.passed and not result.committed
        assert [f.scene_quote for f in result.findings] == [HERE]
        assert not any(r['scene_id'] == SCENE and ledger.is_commitment(r)
                       for r in ledger.load(project_dir))

    def test_one_finding_both_readings_make_is_sent_once(self, project_dir, tmp_path):
        from storyforge import gate
        result, _ = self._gate(project_dir, tmp_path,
                               {1: [_contradiction()], 2: [_contradiction()]})
        assert len(gate.problems_to_fix(result)) == 1

    def test_the_report_names_the_reading_past_the_first(self, project_dir, tmp_path):
        """#483 review SF-9: its exchange is in gate-check-<scene>.r2.json."""
        result, _ = self._gate(project_dir, tmp_path, {2: [_contradiction()]})
        lines = gate_blocking(result)
        assert len(lines) == 1 and lines[0].startswith('CONTRADICTION [reading 2]:')

    def test_a_second_readings_finding_already_in_the_scene_does_not_block(
            self, project_dir, tmp_path):
        """_classify reads the union: a reading-2 finding is inherited too."""
        result, _ = self._gate(project_dir, tmp_path, {2: [_contradiction()]},
                               command='revise',
                               before=_snap(project_dir, f'Old prose. The map said {HERE}.'))
        assert result.passed and [f.reading for f in result.inherited] == [2]

    def test_the_recheck_forecast_prices_every_reading(self):
        """#483 review SF-6: a re-check is GATE_READINGS checks."""
        from storyforge import gate
        assert gate.RECHECK_COST_PER_SCENE == pytest.approx(1.0)   # + the blocking read (#626)


def gate_blocking(result):
    from storyforge import gate
    return gate.blocking_lines(gate.report_lines(result))


@pytest.mark.gate_readings
def test_a_finding_only_the_second_reading_makes_is_fixed_and_rechecked(project_dir, tmp_path):
    """#483 review T-5: gate_and_fix with two readings. Reading 2 alone
    finds the slip; it goes to the fix, and the re-check (two readings
    again) passes the fixed prose."""
    with open(os.path.join(project_dir, 'scenes', f'{SCENE}.md'), encoding='utf-8') as f:
        prose = f.read()
    assert HERE in prose
    calls = []

    def fake(path, body, **k):
        prompt = body['messages'][0]['content']
        if 'tools' in body:
            n = 2 if 'Reading 2:' in prompt else 1
            calls.append(('check', n))
            found = [_contradiction()] if n == 2 and HERE in prompt else []
            return _text({'findings': found, 'kept': []})
        if 'edits' in json.dumps(body.get('output_config', {})):
            calls.append(('fix',))
            return _text({'edits': [{'problem': 1, 'find': HERE,
                                     'replace': 'a village of some size'}]})
        return _text({'commitments': [_commitment(
            statement='The map is blank there', quote='Blank parchment. Not even a contour line.')]})
    with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)):
        out = gate.gate_and_fix(project_dir, SCENE, command='revise', prose=prose,
                                log_dir=str(tmp_path / 'logs'))
    assert calls == [('check', 1), ('check', 2), ('fix',), ('check', 1), ('check', 2)]
    assert out.fixed and out.result.passed and HERE not in out.prose
    assert [f.reading for f in out.first.findings] == [2]


class TestAccepted:
    """Ben, 2026-11-02: a stop on an error in the book is the author's to fix
    or accept. A failing gate records its contradictions (`BLOCKED_PATH`);
    `accept_blocked` moves them to `REPORTED_PATH` as accepted, so later
    runs report them instead of stopping."""

    def test_a_failing_gate_records_its_contradictions_and_a_pass_clears_them(
            self, project_dir, tmp_path):
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
                       command='recheck')
        assert not result.passed
        rows = gate.blocked(project_dir)[SCENE]
        assert [(r['command'], r['source'], r['quote']) for r in rows] == [
            ('recheck', 'act1-sc01', HERE)]
        assert _gate(project_dir, tmp_path, [_commitment()], command='recheck').committed
        assert gate.blocked(project_dir) == {}
        assert not os.path.exists(os.path.join(project_dir, gate.BLOCKED_PATH))

    def test_only_verified_contradictions_are_recorded(self, project_dir, tmp_path):
        from storyforge.elaborate import get_scene
        outcome = get_scene(SCENE, f'{project_dir}/reference')['outcome']
        promise = {'kind': 'broken-promise', 'code': 'PRM', 'scene_quote': '',
                   'established_scene': '', 'fact_id': 'outcome', 'explanation': 'w',
                   'established_quote': outcome}
        both = [promise, {**_contradiction(), 'scene_quote': 'no such words in the scene'}]
        result = _gate(project_dir, tmp_path, [_commitment()], findings=both,
                       command='recheck')
        # #642: the broken promise is advisory; the unverified contradiction blocks
        assert not result.passed and gate.blocked(project_dir) == {}

    def test_accepting_moves_them_and_lists_a_failed_recheck_again(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
              command='recheck')
        gate.mark_pending(project_dir, SCENE, gate.RECHECK_FAILED, 'x')
        rows = gate.accept_blocked(project_dir, SCENE)
        assert [r['quote'] for r in rows] == [HERE]
        assert [(r['command'], r['quote']) for r in gate.reported(project_dir)[SCENE]] == [
            (gate.ACCEPTED, HERE)]
        assert gate.blocked(project_dir) == {}
        assert gate.pending(project_dir)[SCENE]['command'] == gate.RECHECK

    def test_nothing_recorded_accepts_nothing(self, project_dir):
        gate.mark_pending(project_dir, SCENE, gate.RECHECK_FAILED, 'x')
        assert gate.accept_blocked(project_dir, SCENE) == []
        assert gate.pending(project_dir)[SCENE]['command'] == gate.RECHECK_FAILED
        assert gate.reported(project_dir) == {}

    def test_an_accepted_error_is_reported_not_blocking_and_stays(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
              command='recheck')
        gate.accept_blocked(project_dir, SCENE)
        again = _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
                      command='recheck')
        assert again.passed and len(again.inherited) == 1
        assert [(r['command'], r['quote']) for r in gate.reported(project_dir)[SCENE]] == [
            (gate.ACCEPTED, HERE)]   # not duplicated by the run that found it again

    def test_a_run_that_does_not_raise_it_keeps_it(self, project_dir, tmp_path):
        """The checker's findings vary run to run: an accepted error a run
        happens not to raise must not block again later."""
        _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
              command='recheck')
        gate.accept_blocked(project_dir, SCENE)
        assert _gate(project_dir, tmp_path, [_commitment()], command='recheck').committed
        assert gate.reported(project_dir)[SCENE][0]['command'] == gate.ACCEPTED
        later = _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
                      command='recheck')
        assert later.passed

    def test_it_goes_when_its_words_leave_the_scene(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
              command='recheck')
        gate.accept_blocked(project_dir, SCENE)
        path = os.path.join(project_dir, 'scenes', f'{SCENE}.md')
        with open(path, encoding='utf-8') as f:
            text = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text.replace(HERE, 'a village nobody had counted in years'))
        new = _commitment(statement='Nobody had counted the village',
                          quote='a village nobody had counted in years')
        assert _gate(project_dir, tmp_path, [new], command='draft').committed
        assert gate.reported(project_dir) == {}

    def test_a_different_error_still_blocks(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
              command='recheck')
        gate.accept_blocked(project_dir, SCENE)
        other = {**_contradiction(), 'established_scene': 'act2-sc01'}
        assert not _gate(project_dir, tmp_path, [_commitment()], findings=[other],
                         command='recheck').passed

    def test_an_unwritable_blocked_file_is_said_and_the_verdict_stands(
            self, project_dir, tmp_path, capsys):
        os.makedirs(os.path.join(project_dir, 'working'), exist_ok=True)
        with open(os.path.join(project_dir, gate.BLOCKED_PATH), 'w') as f:
            f.write('not|the|header\n')
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[_contradiction()],
                       command='recheck')
        assert not result.passed
        assert f'{gate.BLOCKED_PATH} could not be updated' in capsys.readouterr().out


class TestOfferCapSaid:
    """#564 (B-008, G-029): a scene offered only part of the facts in force
    was reported as `NOTE (cap): scene (62)`; the line now says what was
    cut, and the run's summary counts the scenes."""

    def test_the_cap_note_says_what_it_means_and_the_summary_counts_it(
            self, project_dir, tmp_path, monkeypatch):
        from storyforge import extract, prompts
        monkeypatch.setattr(extract, 'MAX_KNOWN_COMMITMENTS', 1)
        monkeypatch.setattr(gate, 'OFFER_LEFT_OUT', {})
        monkeypatch.setattr(prompts, '_STATES_LEFT_OUT', {})
        result = _gate(project_dir, tmp_path, [_commitment()])
        assert SCENE in gate.OFFER_LEFT_OUT
        note = next(x for x in gate.report_lines(result) if 'over the cap' in x)
        assert note.startswith('NOTE (facts in force left out of what extraction was offered')
        assert f'{SCENE} ({gate.OFFER_LEFT_OUT[SCENE]})' in note
        [line] = prompts.ledger_window_summary()
        assert line.startswith('the gate offered 1 scene(s) only 1 of the facts in force')


class TestProvisional:
    """#556: `write --keep-going` commits a scene the gate stopped only for
    the check's findings, less the facts stating them."""
    OTHER = 'She tapped the empty space on the map'

    def _failing(self, project_dir, tmp_path, **kw):
        return _gate(project_dir, tmp_path,
                     [_commitment(), _commitment(statement='The world has an edge',
                                                 quote=self.OTHER, type='world')],
                     findings=[_contradiction()], **kw)

    def test_the_facts_not_stating_a_finding_are_committed(self, project_dir, tmp_path):
        result = self._failing(project_dir, tmp_path)
        assert not result.passed and gate.can_commit_provisionally(result) == ''
        gate.commit_provisional(project_dir, result, 'provisional: 1 problem')
        assert result.committed and result.provisional and not result.passed
        mine = [r['statement'] for r in ledger.load(project_dir)
                if r['scene_id'] == SCENE and ledger.is_commitment(r)]
        assert mine == ['The world has an edge']   # the 412 fact is held back
        assert gate.pending(project_dir)[SCENE]['command'] == gate.PROVISIONAL
        assert gate.blocked(project_dir)[SCENE]   # for check --accept
        lines = gate.report_lines(result)
        assert any(line.startswith('COMMITTED (provisionally') for line in lines)
        assert any('states what stopped the commit' in line for line in lines)

    def test_an_extraction_problem_is_not_committed_provisionally(self, project_dir,
                                                                  tmp_path):
        result = _gate(project_dir, tmp_path, [_commitment(quote='words not in the scene')],
                       findings=[_contradiction()])
        assert 'extraction' in gate.can_commit_provisionally(result)
        with pytest.raises(GateError):
            gate.commit_provisional(project_dir, result, 'x')
        assert not [r for r in ledger.load(project_dir) if r['scene_id'] == SCENE
                    and ledger.is_commitment(r)]

    def test_an_ends_on_a_fixed_fact_is_reported_not_blocking(self, project_dir, tmp_path):
        """G-028: extraction said the scene `ends` a fixed fact; a fixed fact
        can't end, the link is never applied, and the run stopped on it."""
        rows = ledger.load(project_dir)
        base = dict(rows[0], **{k: '' for k in rows[0]})
        base.update(id='hunt-runs-all-day', scene_id='act1-sc01', type='timeline',
                    statement='The hunt runs through the day', status='binding',
                    origin='prose', mutable='fixed', introduced_by='draft')
        ledger.save(project_dir, rows + [base], command='test')
        result = _gate(project_dir, tmp_path, [_commitment(ends=['hunt-runs-all-day'])])
        assert result.passed and result.committed
        assert result.problems['ends fixed'] == [f'{SCENE}: hunt-runs-all-day']
        assert any(line.startswith('NOTE (ends fixed)') for line in gate.report_lines(result))
        hunt = next(r for r in ledger.load(project_dir) if r['id'] == 'hunt-runs-all-day')
        assert hunt['resolves'] == ''


class TestSteadyParagraphs:
    """#558 (B-032): re-extraction rewords facts whose prose never changed,
    and each rewording counted as a change that re-checked every later scene
    sharing its subject. A fact read from a paragraph the new prose has
    unchanged and in place is kept as it was."""
    LATER = 'act2-sc01'
    TEMPLE = 'the little temple marked with its standard sigil'
    TEMPLE_PARA = 'Roads, wells, the little temple'

    def _git(self, project_dir):
        import subprocess
        subprocess.run(['git', 'init', '-q', project_dir], check=True)

    def _add_later(self, project_dir, **row):
        rows = ledger.load(project_dir)
        base = dict(rows[0], **{k: '' for k in rows[0]})
        base.update(status='binding', origin='prose', mutable='state', introduced_by='draft',
                    scene_id=self.LATER, type='world')
        base.update(row)
        ledger.save(project_dir, rows + [base], command='test')

    def _temple(self, statement='Dorren knows the old survey marked a temple'):
        return _commitment(subject='dorren-hayle', type='knowledge', quote=self.TEMPLE,
                           statement=statement)

    def _first(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow'), self._temple()])
        self._add_later(project_dir, id='later-hollow', subject='tarrens-hollow',
                        statement='The hollow is empty')
        self._add_later(project_dir, id='later-dorren', subject='dorren-hayle',
                        statement='Dorren doubts the survey')
        return {r['subject']: r for r in self._mine(project_dir)}

    def _mine(self, project_dir):
        return [r for r in ledger.load(project_dir)
                if r['scene_id'] == SCENE and ledger.is_commitment(r)]

    def _path(self, project_dir):
        return os.path.join(project_dir, 'scenes', f'{SCENE}.md')

    def _edit(self, project_dir, old, new):
        with open(self._path(project_dir), encoding='utf-8') as f:
            text = f.read()
        assert old in text
        with open(self._path(project_dir), 'w', encoding='utf-8') as f:
            f.write(text.replace(old, new))

    def test_a_reworded_fact_from_an_unchanged_paragraph_is_kept_as_it_was(
            self, project_dir, tmp_path):
        self._git(project_dir)
        old = self._first(project_dir, tmp_path)
        self._edit(project_dir, 'Roads, wells, the little', 'Roads and wells, the little')
        result = _gate(project_dir, tmp_path, [
            _commitment(subject='tarrens-hollow', type='knowledge',
                        statement="Tarren's Hollow had 412 people at the last census"),
            self._temple('Dorren knows the old survey shows a temple')], command='redraft')
        assert result.committed and result.steady == [old['tarrens-hollow']['id']]
        mine = {r['subject']: r for r in self._mine(project_dir)}
        assert mine['tarrens-hollow'] == old['tarrens-hollow']   # id, statement, all of it
        assert result.changed == [old['dorren-hayle']['id']]     # its paragraph changed
        assert result.recheck == [self.LATER]
        assert result.prose_notes == []

    def test_a_number_changed_in_its_paragraph_is_a_change(self, project_dir, tmp_path):
        """#558's review: "twelve winters" becoming "three winters" must re-check."""
        self._git(project_dir)
        old = self._first(project_dir, tmp_path)
        self._edit(project_dir, 'population four hundred and twelve',
                   'population three hundred and twelve')
        result = _gate(project_dir, tmp_path, [
            _commitment(subject='tarrens-hollow', statement="Tarren's Hollow had 312 people",
                        quote='population three hundred and twelve at last census'),
            self._temple()], command='redraft')
        assert result.changed == [old['tarrens-hollow']['id']]
        assert result.steady == [old['dorren-hayle']['id']]

    def test_a_steady_fact_re_extraction_left_out_is_kept(self, project_dir, tmp_path):
        self._git(project_dir)
        old = self._first(project_dir, tmp_path)
        result = _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow')],
                       command='redraft')
        assert result.changed == [] and result.recheck == []
        assert {r['id'] for r in self._mine(project_dir)} == {r['id'] for r in old.values()}

    def test_a_new_fact_from_a_changed_paragraph_is_never_matched_to_a_kept_one(
            self, project_dir, tmp_path):
        """#558's second review: a changed paragraph's new fact sharing four
        words with a fact kept from an unchanged paragraph was dropped, and
        never reached the ledger."""
        self._git(project_dir)
        self._first(project_dir, tmp_path)
        self._edit(project_dir, 'She returned to the new map. Nothing.',
                   'She returned to the new map. Nothing. Still four hundred and twelve at '
                   'last census, the clerk insisted.')
        echo = _commitment(subject='tarrens-hollow', type='knowledge',
                           statement='The clerk insists the census still counts 412',
                           quote='Still four hundred and twelve at last census, the clerk '
                                 'insisted')
        result = _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow'),
                                               self._temple(), echo], command='redraft')
        assert result.committed
        assert 'The clerk insists the census still counts 412' in [
            r['statement'] for r in self._mine(project_dir)]

    def test_a_kept_fact_stating_an_accepted_contradiction_stays_and_is_said(
            self, project_dir, tmp_path):
        """#558's second review ran the kept facts through the hold-back,
        which then dropped them; #632 (iliad-teen: each accept dropped steady
        facts, which counted as changed and re-listed most of the book): a
        kept fact is in the ledger already and its prose didn't change, so
        it stays, and the report says it states the contradiction."""
        self._git(project_dir)
        old = self._first(project_dir, tmp_path)
        gate.record_reported(project_dir, SCENE, 'draft', [gate.Finding(
            'contradiction', 'TIM', HERE, 'act1-sc01',
            'Dorren Hayle pressed the brass calipers against the vellum', '', 'why')])
        self._edit(project_dir, 'Roads, wells, the little', 'Roads and wells, the little')
        result = _gate(project_dir, tmp_path, [self._temple()],
                       findings=[_contradiction()], command='redraft')
        assert result.committed and result.inherited
        mine = {r['id']: r for r in self._mine(project_dir)}
        assert mine[old['tarrens-hollow']['id']] == old['tarrens-hollow']
        assert result.held_back == []
        assert [st for st, _ in result.kept_stating] == [old['tarrens-hollow']['statement']]
        assert old['tarrens-hollow']['id'] not in result.changed

    # #599 (Telemachy pilot): `check --pending`'s re-checks read prose that
    # hasn't changed, and extraction quoted another sentence for a fact the
    # scene already had; the ledger was then written with an id on two rows
    LIVES = 'Four hundred and twelve people going about their lives'

    def _recheck_ok(self, project_dir, result):
        assert result.committed
        assert ledger.file_problems(ledger.ledger_path(project_dir)) == []

    TAPPED = 'She tapped the empty space on the map'

    def _statements(self, project_dir):
        return {r['statement']: r['id'] for r in self._mine(project_dir)}

    def test_a_recheck_drops_a_reading_again_that_says_nothing_new_and_says_so(
            self, project_dir, tmp_path, capsys):
        """A fact the scene has, read again from another unchanged paragraph
        in words that add nothing, is not a second fact; the drop is
        reported and logged (#599's review, T-2)."""
        self._git(project_dir)
        old = self._first(project_dir, tmp_path)['tarrens-hollow']
        again = _commitment(subject='tarrens-hollow',
                            statement="Tarren's Hollow had 412 people living there",
                            quote=self.LIVES)
        result = _gate(project_dir, tmp_path, [again, self._temple()], command='recheck')
        self._recheck_ok(project_dir, result)
        mine = [r for r in self._mine(project_dir) if r['subject'] == 'tarrens-hollow']
        assert mine == [old]
        assert result.changed == [] and result.recheck == []
        assert result.reread == [(again['statement'], old['id'])]
        assert any(line.startswith(f'NOTE (not recorded: a reading again of {old["id"]}')
                   and 'living there' in line for line in gate.report_lines(result))
        assert f'a reading again of {old["id"]}' in capsys.readouterr().out

    def test_a_recheck_keeps_a_reworded_fact_under_a_new_id_and_lists_it(
            self, project_dir, tmp_path):
        """The pilot's scab ("split open and bled" / "splits and bleeds"):
        words changed, so containment can't call it the same; it is kept as a
        new fact with the next id and listed for the author."""
        self._git(project_dir)
        old = self._first(project_dir, tmp_path)['tarrens-hollow']
        reworded = _commitment(subject='tarrens-hollow',
                               statement="Tarren's village had 412 people",
                               quote=self.LIVES)
        result = _gate(project_dir, tmp_path, [reworded, self._temple()], command='recheck')
        self._recheck_ok(project_dir, result)
        assert self._statements(project_dir)[reworded['statement']] not in (old['id'], '')
        assert result.reread == [] and result.restates == [(reworded['statement'], old['id'])]
        assert any('reads much like ' + old['id'] in line for line in gate.report_lines(result))

    def test_a_recheck_keeps_a_fact_of_another_subject_beginning_alike(
            self, project_dir, tmp_path):
        """The pilot's case 3 ("Telemachus tells Pisistratus that his father
        ...", subjects telemachus and pisistratus): same type, same opening,
        another subject: a fact of its own, under the next id (#599's
        review, CR-1 (a): it was dropped and the gate said committed)."""
        self._git(project_dir)
        old = self._first(project_dir, tmp_path)['tarrens-hollow']
        other = _commitment(subject='dorren-hayle',
                            statement="Tarren's Hollow had 412 people, Dorren recalls",
                            quote=self.LIVES)
        assert other['type'] == old['type']
        # the kept fact not read again: the new one is the first to begin so
        result = _gate(project_dir, tmp_path, [other, self._temple()], command='recheck')
        self._recheck_ok(project_dir, result)
        ids = self._statements(project_dir)
        assert ids[old['statement']] == old['id']
        assert ids[other['statement']] == old['id'] + '-2'
        assert result.reread == [] and result.restates == []

    def test_a_recheck_keeps_a_different_fact_of_the_same_subject(
            self, project_dir, tmp_path):
        """CR-1 (b): "... the old survey marked a well" is not "... marked a
        temple", though all but one word is the same."""
        self._git(project_dir)
        self._first(project_dir, tmp_path)
        well = self._temple('Dorren knows the old survey marked a well')
        well['quote'] = self.LIVES
        result = _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow'),
                                               self._temple(), well], command='recheck')
        self._recheck_ok(project_dir, result)
        assert well['statement'] in self._statements(project_dir)
        assert result.reread == []

    def test_a_redraft_keeps_a_different_fact_from_another_unchanged_paragraph(
            self, project_dir, tmp_path):
        """CR-1 (c): a redraft's new reading of an unchanged paragraph that
        says something the kept facts don't is recorded."""
        self._git(project_dir)
        self._first(project_dir, tmp_path)
        self._edit(project_dir, 'She returned to the new map. Nothing.',
                   'She returned to the new map. Nothing at all.')
        well = self._temple('Dorren knows the old survey marked a well')
        well['quote'] = self.TAPPED
        result = _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow'),
                                               self._temple(), well], command='redraft')
        assert result.committed
        assert well['statement'] in self._statements(project_dir)

    def test_a_redraft_drops_the_same_fact_from_another_unchanged_paragraph(
            self, project_dir, tmp_path):
        """CR-1 (c), decided by #558's rule: an unchanged paragraph's facts
        are kept as they were, and only a changed paragraph's are new
        readings. The same fact read from another unchanged paragraph is a
        reading again, in a redraft as in a re-check, and reported."""
        self._git(project_dir)
        old = self._first(project_dir, tmp_path)
        self._edit(project_dir, 'She returned to the new map. Nothing.',
                   'She returned to the new map. Nothing at all.')
        again = self._temple('Dorren knows that the old survey marked a temple there')
        again['quote'] = self.TAPPED
        result = _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow'),
                                               self._temple(), again], command='redraft')
        assert result.committed
        assert again['statement'] not in self._statements(project_dir)
        assert result.reread == [(again['statement'], old['dorren-hayle']['id'])]

    def test_an_earlier_fact_not_kept_is_never_dropped_as_a_reading_again(
            self, project_dir, tmp_path):
        """CR-1b: the census fact's paragraph changed, so it isn't kept; the
        redraft reads it again from the unchanged temple paragraph (its
        quote shares four words with the kept temple fact's). Dropping that
        row would delete the census fact and re-check what depends on it,
        though the fact is still there."""
        self._git(project_dir)
        old = self._first(project_dir, tmp_path)
        self._edit(project_dir, 'should have been exactly here',
                   'should have been right here')
        census = _commitment(subject='tarrens-hollow', quote=self.TEMPLE)
        result = _gate(project_dir, tmp_path, [census, self._temple()], command='redraft')
        assert result.committed
        assert self._statements(project_dir)[census['statement']] == \
            old['tarrens-hollow']['id']
        assert old['tarrens-hollow']['id'] not in result.changed
        assert result.reread == []

    def test_a_reworded_copy_quoted_across_paragraphs_is_kept_and_listed(
            self, project_dir, tmp_path):
        """T-4: a reading whose quote lies in no one paragraph can't be
        placed in unchanged prose, so it is never dropped as a reading
        again; when it reads much like a kept fact it is listed, so the
        copy is the author's to see. Kept rather than dropped: dropping on
        the statement alone would drop facts from changed prose too."""
        self._git(project_dir)
        old = self._first(project_dir, tmp_path)['tarrens-hollow']
        across = _commitment(subject='tarrens-hollow',
                             statement="Tarren's Hollow had 412 people counted",
                             quote='should have been exactly here. She tapped the empty space')
        result = _gate(project_dir, tmp_path, [across, self._temple()], command='recheck')
        self._recheck_ok(project_dir, result)
        assert self._statements(project_dir)[across['statement']] == old['id'] + '-2'
        assert result.restates == [(across['statement'], old['id'])]

    def test_a_changed_paragraphs_fact_beginning_as_a_kept_one_gets_a_new_id(
            self, project_dir, tmp_path):
        """Beowulf B-034 through the gate: a kept fact and a new one from a
        changed paragraph whose statements begin alike."""
        self._git(project_dir)
        old = self._first(project_dir, tmp_path)['tarrens-hollow']
        self._edit(project_dir, 'She returned to the new map. Nothing.',
                   'She returned to the new map. Nothing. A mill had stood by the river.')
        mill = _commitment(subject='tarrens-hollow',
                           statement="Tarren's Hollow had 412 people and a mill",
                           quote='A mill had stood by the river')
        result = _gate(project_dir, tmp_path, [mill, self._temple()], command='redraft')
        self._recheck_ok(project_dir, result)
        ids = {r['statement']: r['id'] for r in self._mine(project_dir)}
        assert ids[old['statement']] == old['id']
        assert ids[mill['statement']] == old['id'] + '-2'

    CENSUS_ID = 'act1-sc02--tarren-s-hollow-had-412-people'

    def test_an_id_a_ledger_link_names_is_never_minted_again(self, project_dir, tmp_path):
        """#599's review (TD-1/SF-2): an id the ledger no longer has but a
        later fact's `supersedes` still names, minted again, would put that
        link on a different fact."""
        self._add_later(project_dir, id='later-hollow', subject='tarrens-hollow',
                        statement='The hollow is empty', supersedes=self.CENSUS_ID)
        _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow')])
        ids = [r['id'] for r in self._mine(project_dir)]
        assert ids == [self.CENSUS_ID + '-2']

    def test_an_id_a_brief_names_is_never_minted_again(self, project_dir, tmp_path):
        path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
        with open(path, encoding='utf-8') as f:
            lines = f.read().split('\n')
        header = lines[0].split('|')
        cells = lines[1].split('|')
        k = header.index('knowledge_in')
        cells[k] = ';'.join(filter(None, [cells[k], self.CENSUS_ID]))
        lines[1] = '|'.join(cells)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow')])
        assert [r['id'] for r in self._mine(project_dir)] == [self.CENSUS_ID + '-2']

    def test_reserved_is_the_old_ids_and_every_id_a_link_names(self):
        loaded = [{'id': 'a', 'supersedes': 'gone;b', 'depends_on': 'c'}, {'id': 'b'}]
        assert gate._reserved_ids({'s--x'}, loaded, {'brief-fact'}) == {
            's--x', 'gone', 'b', 'c', 'brief-fact'}

    def test_a_new_row_with_an_old_id_stops_the_commit(self):
        """TD-2: `_carry_ids` checks what it relies on: a row minted without
        the reserved ids, neither kept nor carried, never keeps an old id."""
        old = {'id': 's--a', 'subject': '', 'type': 'world', 'statement': 'A',
               'scene_id': 's'}
        stray = {'id': 's--a', 'subject': '', 'type': 'world', 'statement': 'B',
                 'scene_id': 's'}
        with pytest.raises(GateError, match="'s--a' has the id of an earlier commitment"):
            gate._carry_ids([stray], [old], [])

    def test_reserved_ids_are_required(self):
        from storyforge.extract import COMMITMENT_PROBLEMS, commitment_rows
        with pytest.raises(TypeError, match='reserved'):
            commitment_rows([], 's', '', [], [], [], {}, 'draft',
                            {k: [] for k in COMMITMENT_PROBLEMS},
                            own_writers=ledger.COMMITMENT_WRITERS)

    def test_a_commit_that_would_repeat_an_id_writes_nothing(
            self, project_dir, tmp_path, monkeypatch):
        """Whatever slips past the ids, the ledger is never written as one
        the next command can't load: the gate stops, nothing written."""
        self._git(project_dir)
        self._first(project_dir, tmp_path)
        path = ledger.ledger_path(project_dir)
        before = open(path, encoding='utf-8').read()

        def collide(proposed, old_rows, *_):
            for p in proposed:
                p['id'] = old_rows[0]['id']
        monkeypatch.setattr(gate, '_carry_ids', collide)
        with pytest.raises(gate.LedgerWriteRefused,
                           match="ledger write refused: .*'act1-sc02--tarren-s-hollow"
                                 "-had-412-people' would be on 2 rows \\(from act1-sc02\\)"):
            _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow'),
                                          self._temple()], command='recheck')
        assert open(path, encoding='utf-8').read() == before

    def test_a_refused_commit_leaves_the_result_as_it_was(
            self, project_dir, tmp_path, monkeypatch):
        """TD-3: a refused write never leaves the result half-committed (ids
        carried, steady facts kept, `changed` set) for the caller to read."""
        self._git(project_dir)
        self._first(project_dir, tmp_path)
        self._edit(project_dir, 'Roads, wells, the little', 'Roads and wells, the little')
        seen = {}
        real = gate._commit

        def watch(project_dir_, result, *a, **k):
            seen['before'] = copy.deepcopy({k_: v for k_, v in vars(result).items()
                                            if k_ != '_ctx'})
            seen['result'] = result
            return real(project_dir_, result, *a, **k)

        def refuse(*a, **k):
            raise ledger.LedgerError('refused')
        monkeypatch.setattr(gate, '_commit', watch)
        monkeypatch.setattr(ledger, 'save', refuse)
        with pytest.raises(gate.LedgerWriteRefused, match='ledger write refused: refused'):
            _gate(project_dir, tmp_path, [_commitment(subject='tarrens-hollow'),
                                          self._temple('Dorren knows the survey shows a temple')],
                  command='redraft')
        after = {k: v for k, v in vars(seen['result']).items() if k != '_ctx'}
        assert after == seen['before'] and not seen['result'].committed
        assert seen['result'].steady == [] and seen['result'].changed == []

    def test_a_cell_that_would_break_its_row_is_a_refused_write(
            self, project_dir, tmp_path, monkeypatch):
        """SF-3: the ValueError a breaking cell raises was not caught, and it
        stopped `check --pending --keep-going`; it is a refused write, and a
        re-check that hits it is listed failed."""
        self._git(project_dir)
        self._first(project_dir, tmp_path)
        path = ledger.ledger_path(project_dir)
        before = open(path, encoding='utf-8').read()
        gate.mark_pending(project_dir, SCENE, gate.RECHECK, 're-check: x changed 1 fact(s)')

        def corrupt(proposed, old_rows, *_):
            proposed[0]['mutable'] = 'state|fixed'
        monkeypatch.setattr(gate, '_carry_ids', corrupt)

        def fake(path_, body, **k):
            if 'tools' in body:
                return _text({'findings': [], 'kept': []})
            return _text({'commitments': [_commitment(subject='tarrens-hollow'),
                                          self._temple()]})
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)):
            run = gate.recheck_pending(project_dir, log_dir=str(tmp_path / 'rc'),
                                       extract_model='m', check_model='m')
        assert run.failed == SCENE and 'ledger write refused' in run.why
        assert gate.pending(project_dir)[SCENE]['command'] == gate.RECHECK_FAILED
        assert open(path, encoding='utf-8').read() == before

    def test_a_recheck_that_would_repeat_an_id_is_listed_failed(
            self, project_dir, tmp_path, monkeypatch):
        self._git(project_dir)
        self._first(project_dir, tmp_path)
        path = ledger.ledger_path(project_dir)
        before = open(path, encoding='utf-8').read()
        gate.mark_pending(project_dir, SCENE, gate.RECHECK, 're-check: x changed 1 fact(s)')

        def collide(proposed, old_rows, *_):
            for p in proposed:
                p['id'] = old_rows[0]['id']
        monkeypatch.setattr(gate, '_carry_ids', collide)

        def fake(path, body, **k):
            if 'tools' in body:
                return _text({'findings': [], 'kept': []})
            return _text({'commitments': [_commitment(subject='tarrens-hollow'),
                                          self._temple()]})
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)):
            run = gate.recheck_pending(project_dir, log_dir=str(tmp_path / 'rc'),
                                       extract_model='m', check_model='m')
        assert run.failed == SCENE and 'ledger write refused' in run.why
        assert 'would be on 2 rows' in run.why
        assert gate.pending(project_dir)[SCENE]['command'] == gate.RECHECK_FAILED
        assert open(path, encoding='utf-8').read() == before
        ledger.load(project_dir)   # the next command can read it

    def test_a_moved_paragraph_is_not_steady(self):
        earlier = 'One para here.\n\nTwo para here.\n\nThree para here.'
        assert gate.steady_paragraphs(earlier, earlier) == {0, 1, 2}
        moved = 'One para here.\n\nThree para here.\n\nTwo para here.'
        assert gate.steady_paragraphs(earlier, moved) == {0}

    def test_a_paragraph_after_a_new_antecedent_is_not_steady(self):
        earlier = 'He came in.\n\nShe hit him.\n\nHe fell.'
        prose = 'He came in.\n\nA stranger followed.\n\nShe hit him.\n\nHe fell.'
        # "She hit him" now follows a new paragraph: "him" may be the stranger
        assert gate.steady_paragraphs(earlier, prose) == {0, 2}
        assert gate.steady_facts([{'id': 'a', 'quote': 'She hit him'},
                                  {'id': 'b', 'quote': 'He came in'}], earlier, prose) == {'b': 0}

    def test_without_git_a_rewording_still_counts_and_is_said(self, project_dir, tmp_path):
        old = self._first(project_dir, tmp_path)
        result = _gate(project_dir, tmp_path, [
            _commitment(subject='tarrens-hollow', statement="The Hollow held 412 people"),
            self._temple()], command='redraft')
        assert result.changed == [old['tarrens-hollow']['id']] and result.steady == []
        assert any(gate.PROSE_PATH in n for n in result.prose_notes)
        assert not os.path.exists(os.path.join(project_dir, gate.PROSE_PATH))

    def _commit(self, project_dir, message):
        import subprocess
        subprocess.run(['git', '-C', project_dir, 'add', '-A'], check=True)
        subprocess.run(['git', '-C', project_dir, '-c', 'user.name=t', '-c', 'user.email=t@t',
                        'commit', '-qm', message], check=True)

    def _legacy(self, project_dir, tmp_path):
        """A book gated before #558: its ledger and prose in git, no
        gate-prose.csv (Beowulf B-033)."""
        self._git(project_dir)
        old = self._first(project_dir, tmp_path)
        os.remove(os.path.join(project_dir, gate.PROSE_PATH))
        self._commit(project_dir, 'Draft and gate')
        with open(self._path(project_dir), encoding='utf-8') as f:
            return old, f.read()

    def test_a_book_gated_before_the_record_reads_its_prose_from_git(
            self, project_dir, tmp_path):
        """Beowulf B-033: with no gate-prose.csv, a one-scene revision of the
        prelude re-read every fact as changed and queued 47 re-checks."""
        old, prose = self._legacy(project_dir, tmp_path)
        assert gate.gated_prose(project_dir, SCENE) == (prose, '')
        self._edit(project_dir, 'Roads, wells, the little', 'Roads and wells, the little')
        result = _gate(project_dir, tmp_path, [
            _commitment(subject='tarrens-hollow', type='knowledge',
                        statement="Tarren's Hollow had 412 people at the last census"),
            self._temple('Dorren knows the old survey shows a temple')], command='revise')
        assert result.committed and result.steady == [old['tarrens-hollow']['id']]
        assert result.changed == [old['dorren-hayle']['id']]
        assert result.prose_notes == []

    def test_history_skips_a_commit_of_the_prose_alone(self, project_dir, tmp_path):
        """revise commits the revised prose before the gate reads it: the
        prose the facts were read from is the one at the ledger's commit."""
        _, prose = self._legacy(project_dir, tmp_path)
        self._edit(project_dir, 'Roads, wells, the little', 'Roads and wells, the little')
        self._commit(project_dir, 'Revision, before the gate')
        assert gate.gated_prose(project_dir, SCENE) == (prose, '')

    def test_history_is_not_read_when_the_ledger_has_uncommitted_rows(
            self, project_dir, tmp_path):
        self._legacy(project_dir, tmp_path)
        rows = ledger.load(project_dir)
        mine = next(r for r in rows if r['scene_id'] == SCENE and ledger.is_commitment(r))
        mine['statement'] += ' (edited by hand)'
        ledger.save(project_dir, rows, command='test')
        earlier, why = gate.gated_prose(project_dir, SCENE)
        assert earlier is None and 'record' in why

    def test_the_committed_prose_is_recorded_and_read_back(self, project_dir, tmp_path):
        self._git(project_dir)
        _gate(project_dir, tmp_path, [_commitment()])
        with open(self._path(project_dir), encoding='utf-8') as f:
            prose = f.read()
        assert gate.gated_prose(project_dir, SCENE) == (prose, '')
        self._edit(project_dir, 'Blank parchment.', 'Blank vellum.')
        assert gate.gated_prose(project_dir, SCENE) == (prose, '')   # the gated one


class TestALinkPastTheOfferCap:
    """#634 (iliad-teen, 2026-11-08): a scene is offered at most
    `MAX_KNOWN_COMMITMENTS` of the book's facts in force, and the extractor
    wrote `ends: hector-outside-the-gate--hector-decides-to-stand-and-fight`
    for one it wasn't shown. The link names a real fact in force: it is
    applied, with a NOTE, not blocked as UNRESOLVED."""

    EARLIER = 'act1-sc01'
    GONE = f'{EARLIER}--hector-decides-to-stand-and-fight'

    def _fill(self, project_dir, n=230):
        """`GONE` and `n` more states from the earlier scene, `GONE` the
        oldest: past the cap the oldest are left out of the offer."""
        from storyforge.extract import MAX_KNOWN_COMMITMENTS
        assert n > MAX_KNOWN_COMMITMENTS
        rows = ledger.load(project_dir)
        base = {k: '' for k in rows[0]}
        base.update(status='binding', origin='prose', mutable='state', introduced_by='draft',
                    scene_id=self.EARLIER, type='physical')
        rows.append(dict(base, id=self.GONE, statement='Hector decides to stand and fight'))
        rows += [dict(base, id=f'{self.EARLIER}--crate-{i}-is-in-the-hold',
                      statement=f'Crate {i} is in the hold') for i in range(n)]
        ledger.save(project_dir, rows, command='test')

    def test_an_ends_naming_a_real_fact_left_out_passes_with_a_note(self, project_dir,
                                                                    tmp_path):
        self._fill(project_dir)
        result = _gate(project_dir, tmp_path, [_commitment(ends=[self.GONE])])
        assert result.problems['cap'], 'the offer was not capped: the test proves nothing'
        assert result.passed and result.committed, gate.report_lines(result)
        assert result.problems['unoffered'] == [f'{SCENE}: {self.GONE}']
        assert not result.unresolved
        row = next(r for r in ledger.load(project_dir) if r['id'] == self.GONE)
        assert row['resolves'] == SCENE
        notes = [line for line in gate.report_lines(result)
                 if line.startswith('NOTE') and self.GONE in line]
        assert len(notes) == 1 and 'not offered' in notes[0]
        assert any(self.GONE in line for line in gate.applied_lines(result))

    def test_a_supersedes_naming_a_real_fact_left_out_is_linked(self, project_dir, tmp_path):
        self._fill(project_dir)
        result = _gate(project_dir, tmp_path, [_commitment(supersedes=self.GONE)])
        assert result.passed, gate.report_lines(result)
        assert result.proposed[0]['supersedes'] == self.GONE
        assert result.problems['unoffered'] == [f'{SCENE}: {self.GONE}']

    def test_a_made_up_id_one_word_off_is_read_as_the_nearest(self, project_dir, tmp_path):
        self._fill(project_dir)
        wrong = f'{self.EARLIER}--hector-decided-to-stand-and-fight'
        result = _gate(project_dir, tmp_path, [_commitment(ends=[wrong])])
        assert result.passed, gate.report_lines(result)
        assert result.problems['unoffered'] == [f'{SCENE}: {wrong} -> {self.GONE}']

    def test_an_id_naming_nothing_still_blocks(self, project_dir, tmp_path):
        self._fill(project_dir)
        nothing = f'{self.EARLIER}--nothing-like-this-was-said'
        result = _gate(project_dir, tmp_path, [_commitment(ends=[nothing])])
        assert not result.passed and not result.committed
        assert result.problems['ends'] == [f'{SCENE}: {nothing}']
        assert gate._only_extractor_slips(result)   # so it earns the re-extraction


# ============================================================================
# #642: a broken promise is advisory unless the brief marks the beat `must:`
# ============================================================================

def _set_brief(project_dir, **cols):
    """Set the scene's brief columns, pipe-delimited and unquoted as the
    project writes them."""
    path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    header = lines[0].split('|')
    for n, line in enumerate(lines[1:], start=1):
        cells = line.split('|')
        if cells[0] == SCENE:
            for col, value in cols.items():
                cells[header.index(col)] = value
            lines[n] = '|'.join(cells)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def _promise(quote, fact_id='key_actions', scene_quote=''):
    return {'kind': 'broken-promise', 'code': 'PRM', 'scene_quote': scene_quote,
            'established_scene': '', 'fact_id': fact_id, 'explanation': 'not delivered',
            'established_quote': quote}


class TestAdvisoryPromises:
    def test_a_broken_promise_is_reported_but_does_not_stop_the_scene(
            self, project_dir, tmp_path):
        result = _gate(project_dir, tmp_path, [_commitment()],
                       findings=[_promise('Searches removal logs')])
        assert result.passed and result.committed
        assert [f.established_quote for f in result.advisory] == ['Searches removal logs']
        assert result.findings == [] and gate.problems_to_fix(result) == []
        lines = gate.report_lines(result)
        advisory = [line for line in lines if line.startswith('ADVISORY')]
        assert len(advisory) == 1 and 'Searches removal logs' in advisory[0]
        assert 'must:' in advisory[0] and gate.ADVISORY_PATH in advisory[0]
        assert not any(line.startswith('ADVISORY') for line in gate.blocking_lines(lines))
        rows = gate.advisories(project_dir)[SCENE]
        assert [(r['command'], r['source'], r['quote']) for r in rows] == [
            ('draft', 'key_actions', 'Searches removal logs')]

    def test_a_broken_must_beat_still_stops_the_scene(self, project_dir, tmp_path):
        _set_brief(project_dir, key_actions='Cross-references maps;must: Searches removal '
                                            'logs;Finds nothing')
        # the check may quote the beat without its marker, or with it
        for quote in ('Searches removal logs', 'must: Searches removal logs'):
            result = _gate(project_dir, tmp_path, [_commitment()], findings=[_promise(quote)])
            assert not result.passed and not result.committed
            assert result.advisory == []
            assert [f.established_quote for f in result.findings] == [quote]
            assert any('Broken promise' in p for p in gate.problems_to_fix(result))
            assert gate.advisories(project_dir) == {}

    def test_only_the_must_beat_blocks(self, project_dir, tmp_path):
        _set_brief(project_dir, key_actions='Cross-references maps;MUST : Searches removal '
                                            'logs;Finds nothing')
        result = _gate(project_dir, tmp_path, [_commitment()],
                       findings=[_promise('Finds nothing'), _promise('Searches removal logs')])
        assert not result.passed
        assert [f.established_quote for f in result.findings] == ['Searches removal logs']
        assert [f.established_quote for f in result.advisory] == ['Finds nothing']
        # reported on a failing run too
        assert [r['quote'] for r in gate.advisories(project_dir)[SCENE]] == ['Finds nothing']

    def test_an_unverified_broken_promise_is_advisory(self, project_dir, tmp_path):
        result = _gate(project_dir, tmp_path, [_commitment()],
                       findings=[_promise('Burns the archive to the ground')])
        assert result.passed
        assert [f.problem != '' for f in result.advisory] == [True]
        assert result.unverified == []
        assert 'unverified' in gate.advisories(project_dir)[SCENE][0]['finding']

    def test_an_unverified_broken_must_beat_blocks(self, project_dir, tmp_path):
        _set_brief(project_dir, key_actions='Cross-references maps;must: Searches the '
                                            'removal logs twice over')
        # quoted in part, under a made-up id: not verified, still the must beat's
        result = _gate(project_dir, tmp_path, [_commitment()],
                       findings=[_promise('Searches the removal logs twice', fact_id='beat-3')])
        assert not result.passed and result.advisory == []
        assert len(result.unverified) == 1

    def test_a_registry_promise_is_advisory(self, project_dir, tmp_path):
        result = _gate(project_dir, tmp_path, [_commitment()],
                       findings=[_promise('', fact_id='village-vanished')])
        assert result.passed and [f.fact_id for f in result.advisory] == ['village-vanished']

    # #642's review: when the brief has a must beat, only a quote that is
    # positively an unmarked item is advisory (TD-1, CR-2, T2)
    def test_a_paraphrased_must_beat_blocks(self, project_dir, tmp_path):
        _set_brief(project_dir, key_actions="Cross-references maps;must: Priam kisses "
                                            "Achilles' hands")
        for quote in ('Priam kisses the hands of Achilles', 'Priam kneels and kisses hands'):
            result = _gate(project_dir, tmp_path, [_commitment()],
                           findings=[_promise(quote)])
            assert not result.passed and result.advisory == [], quote
            assert [w for _, w in result.promise_why] == [gate.MUST_BEAT]

    def test_a_short_partial_quote_of_a_must_beat_blocks(self, project_dir, tmp_path):
        _set_brief(project_dir, key_actions='Cross-references maps;must: Achilles chases him '
                                            'round the walls')
        result = _gate(project_dir, tmp_path, [_commitment()],
                       findings=[_promise('Achilles chases him')])
        assert not result.passed and result.advisory == []

    def test_a_quote_naming_an_unmarked_item_stays_advisory(self, project_dir, tmp_path):
        _set_brief(project_dir, key_actions='Searches the removal logs for the village;'
                                            'must: Dorren burns the archive')
        result = _gate(project_dir, tmp_path, [_commitment()],
                       findings=[_promise('the removal logs for the village')])
        assert result.passed
        assert [f.established_quote for f in result.advisory] == [
            'the removal logs for the village']

    def test_a_verified_outcome_promise_is_advisory_beside_a_must_beat(
            self, project_dir, tmp_path):
        # SF-6: outcome takes no marker; sharing words with a must beat
        # doesn't make its promise one
        _set_brief(project_dir, outcome='Dorren searches removal logs and finds nothing',
                   key_actions='must: Dorren searches removal logs')
        for quote in ('Dorren searches removal logs and finds nothing',
                      'searches removal logs and finds nothing'):
            result = _gate(project_dir, tmp_path, [_commitment()],
                           findings=[_promise(quote, fact_id='outcome')])
            assert result.passed and len(result.advisory) == 1, quote

    def test_a_must_line_reported_under_another_field_blocks(self, project_dir, tmp_path):
        # T1: the check files the must line under key_actions, which has a
        # must beat of its own
        _set_brief(project_dir, key_actions='Hector runs;must: Achilles chases him round the '
                                            'walls',
                   key_dialogue='must: Dorren: "I have kissed the hands of the man"')
        result = _gate(project_dir, tmp_path, [_commitment()],
                       findings=[_promise('Dorren: "I have kissed the hands of the man"')])
        assert not result.passed and result.advisory == []

    def test_a_must_line_beside_its_unmarked_longer_form_blocks(self, project_dir, tmp_path):
        # SF-1: the check reports the unmarked line (advisory); the must line
        # inside it is missing too, and still blocks
        _set_brief(project_dir, key_dialogue='Dorren: "The map has been altered by hand, '
                                             'Tessa";must: Dorren: "The map has been altered '
                                             'by hand"')
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[_promise(
            'Dorren: "The map has been altered by hand, Tessa"', fact_id='key_dialogue')])
        assert not result.passed
        assert [f.established_quote for f in result.advisory] == [
            'Dorren: "The map has been altered by hand, Tessa"']
        assert [f.established_quote for f in result.findings] == [
            'must: Dorren: "The map has been altered by hand"']

    def test_a_registry_promise_set_up_in_this_scene_blocks(self, project_dir, tmp_path):
        # CR-1, SF-2: the ledger sets archive-key-dorren up in this scene;
        # committed without it, later scenes would be read against a fact
        # the prose never established
        result = _gate(project_dir, tmp_path, [_commitment()],
                       findings=[_promise('', fact_id='archive-key-dorren')])
        assert not result.passed and not result.committed and result.advisory == []
        assert [f.fact_id for f in result.findings] == ['archive-key-dorren']
        line = next(line for line in gate.report_lines(result)
                    if line.startswith('BROKEN-PROMISE'))
        assert 'blocking: the ledger sets up archive-key-dorren in this scene' in line
        assert any('archive-key-dorren' in p for p in gate.problems_to_fix(result))

    def test_a_later_run_without_one_clears_the_scenes_rows(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment()], findings=[_promise('Finds nothing')])
        assert SCENE in gate.advisories(project_dir)
        _gate(project_dir, tmp_path, [_commitment()], command='recheck')
        assert gate.advisories(project_dir) == {}
        assert not os.path.exists(os.path.join(project_dir, gate.ADVISORY_PATH))

    def test_a_bare_marker_is_reported(self, project_dir, tmp_path):
        _set_brief(project_dir, key_actions='Cross-references maps;must:;Finds nothing')
        result = _gate(project_dir, tmp_path, [_commitment()],
                       findings=[_promise('Finds nothing')])
        assert result.passed and result.bare_must == ['key_actions (1)']
        assert any(line.startswith('NOTE (brief items that are only the must: marker')
                   for line in gate.report_lines(result))

    def test_a_misplaced_marker_is_reported(self, project_dir, tmp_path):
        # SF-3: the label-first form marks nothing, and says so
        _set_brief(project_dir, key_dialogue='Dorren: must: "The map has been altered"',
                   outcome='must: Dorren pursues it')
        result = _gate(project_dir, tmp_path, [_commitment()])
        assert result.passed
        assert result.misplaced_must == ['outcome: must: Dorren pursues it',
                                         'key_dialogue: Dorren: must: "The map has been altered"']
        assert any(line.startswith('NOTE (brief items with a must: that marks nothing')
                   for line in gate.report_lines(result))

    def test_an_unwritable_list_is_a_warning_not_a_stop(self, project_dir, tmp_path, capsys):
        os.makedirs(os.path.join(project_dir, 'working'), exist_ok=True)
        with open(os.path.join(project_dir, gate.ADVISORY_PATH), 'w') as f:
            f.write('not|the|header\n')
        result = _gate(project_dir, tmp_path, [_commitment()],
                       findings=[_promise('Finds nothing')])
        assert result.passed
        assert f'{gate.ADVISORY_PATH} could not be updated' in capsys.readouterr().out

    def test_advisory_lines(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment()], findings=[_promise('Finds nothing')])
        lines = gate.advisory_lines(project_dir)
        assert lines == [f'{SCENE}: PRM the brief\'s key_actions promises "Finds nothing" '
                         f'— not delivered']
        assert gate.advisory_lines(project_dir, ['act1-sc01']) == []

    def test_a_gate_run_stamps_its_rows_with_what_it_read(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment()], findings=[_promise('Finds nothing')])
        [row] = gate.advisories(project_dir)[SCENE]
        assert row['paragraphs'].startswith('prose=') and ';brief=' in row['paragraphs']
        assert [r['stale'] for r in gate.read_advisory(project_dir).rows] == ['']

    def test_an_unreadable_list_is_a_warning_not_a_promise(self, project_dir):
        # CR-4, SF-5, TD-2
        os.makedirs(os.path.join(project_dir, 'working'), exist_ok=True)
        with open(os.path.join(project_dir, gate.ADVISORY_PATH), 'w') as f:
            f.write('not|the|header\n')
        found = gate.read_advisory(project_dir)
        assert found.rows == [] and len(found.problems) == 1
        assert gate.advisory_lines(project_dir) == []
        [line] = gate.advisory_summary(project_dir)
        assert line.startswith(f'WARNING: {gate.ADVISORY_PATH} could not be read')
        assert 'broken promise' not in line

    def test_an_unreadable_reading_order_is_said(self, project_dir, tmp_path):
        # SF-8: listed unordered, and said
        _gate(project_dir, tmp_path, [_commitment()], findings=[_promise('Finds nothing')])
        with patch('storyforge.ledger.scene_order', side_effect=ValueError('no seq')):
            found = gate.read_advisory(project_dir)
            summary = gate.advisory_summary(project_dir)
        assert len(found.rows) == 1
        assert found.problems == [f'{gate.ADVISORY_PATH}: listed unordered, the reading '
                                  f'order could not be read: no seq']
        assert summary[0] == f'WARNING: {found.problems[0]}'
        assert summary[1].startswith('WARNING: 1 broken promise(s)')

    def test_gate_and_fix_does_not_fix_an_advisory_promise(self, project_dir, tmp_path):
        calls = []

        def fake(path, body, **k):
            calls.append(body)
            if 'tools' in body:
                return _text({'findings': [_promise('Finds nothing')], 'kept': []})
            if 'commitments' in body['output_config']['format']['schema']['properties']:
                return _text({'commitments': [_commitment()]})
            raise AssertionError('the fix was called')
        prose = open(os.path.join(project_dir, 'scenes', f'{SCENE}.md')).read()
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake, ())):
            out = gate.gate_and_fix(project_dir, SCENE, command='draft', prose=prose,
                                    log_dir=str(tmp_path / 'logs'), extract_model='m',
                                    check_model='m')
        assert out.result.passed and not out.fixed and out.rounds == []


class TestMustLines:
    """A `must` beat's scripted words are checked word for word, by code."""

    def test_a_must_line_in_the_prose_passes(self, project_dir, tmp_path):
        _set_dialogue_raw(project_dir, 'must: Dorren: "It was here last quarter"')
        result = _gate(project_dir, tmp_path, [_commitment()])
        assert result.passed

    def test_a_must_line_missing_from_the_prose_blocks(self, project_dir, tmp_path):
        _set_dialogue_raw(project_dir, 'must: Dorren: "The map has been altered by hand"')
        result = _gate(project_dir, tmp_path, [_commitment()])
        assert not result.passed
        [f] = result.findings
        assert (f.kind, f.fact_id) == ('broken-promise', 'key_dialogue')
        assert 'The map has been altered by hand' in f.explanation
        assert f.established_quote == 'must: Dorren: "The map has been altered by hand"'

    def test_a_paraphrase_is_not_the_line(self, project_dir, tmp_path):
        _set_dialogue_raw(project_dir, 'must: Dorren: "It was there last quarter"')
        assert not _gate(project_dir, tmp_path, [_commitment()]).passed

    def test_an_unmarked_missing_line_is_left_to_the_check(self, project_dir, tmp_path):
        _set_dialogue_raw(project_dir, 'Dorren: "The map has been altered by hand"')
        assert _gate(project_dir, tmp_path, [_commitment()]).passed

    def test_a_quoted_line_in_a_must_action_is_checked(self, project_dir, tmp_path):
        _set_brief(project_dir, key_actions='must: Dorren says "the map has been altered"')
        assert not _gate(project_dir, tmp_path, [_commitment()]).passed

    def test_an_unquoted_must_action_is_left_to_the_check(self, project_dir, tmp_path):
        _set_brief(project_dir, key_actions='must: Dorren burns the archive')
        assert _gate(project_dir, tmp_path, [_commitment()]).passed

    def test_the_code_found_finding_has_its_own_code(self, project_dir, tmp_path):
        # TD-5: told apart from a checker's reading
        _set_dialogue_raw(project_dir, 'must: Dorren: "The map has been altered by hand"')
        [f] = _gate(project_dir, tmp_path, [_commitment()]).findings
        assert f.code == gate.MUST_CODE != 'PRM'

    # T3: an unquoted must line, with a cast label or a role label
    def test_an_unquoted_cast_labelled_line_in_the_prose_passes(self, project_dir, tmp_path):
        _set_dialogue_raw(project_dir, 'must: Dorren: It was here last quarter')
        assert _gate(project_dir, tmp_path, [_commitment()]).passed

    def test_an_unquoted_role_labelled_line_in_the_prose_passes(self, project_dir, tmp_path):
        _set_dialogue_raw(project_dir, 'must: The old cartographer: It was here last quarter')
        assert _gate(project_dir, tmp_path, [_commitment()]).passed

    def test_an_unquoted_role_labelled_line_missing_blocks(self, project_dir, tmp_path):
        _set_dialogue_raw(project_dir, 'must: The old cartographer: The map was altered by '
                                       'hand')
        assert not _gate(project_dir, tmp_path, [_commitment()]).passed

    def test_a_must_line_too_short_to_check_is_noted(self, project_dir, tmp_path):
        # CR-5: not checked by code, and said
        _set_dialogue_raw(project_dir, 'must: Dorren: "Pity me."')
        result = _gate(project_dir, tmp_path, [_commitment()])
        assert result.passed and result.short_must == ['key_dialogue: "Pity me."']
        assert any(line.startswith('NOTE (must: lines under 3 words')
                   and 'Pity me.' in line for line in gate.report_lines(result))

    def test_one_finding_when_the_check_reported_it_too(self, project_dir, tmp_path):
        _set_dialogue_raw(project_dir, 'must: Dorren: "The map has been altered by hand"')
        result = _gate(project_dir, tmp_path, [_commitment()],
                       findings=[_promise('Dorren: "The map has been altered by hand"',
                                          fact_id='key_dialogue')])
        assert len(result.findings) == 1 and result.findings[0].explanation == 'not delivered'


class TestMustLineFixed:
    def test_gate_and_fix_fixes_a_missing_must_line(self, project_dir, tmp_path):
        """T5: the code-found must finding goes to the fix, and the fixed
        scene passes."""
        _set_dialogue_raw(project_dir, 'must: Dorren: "The map has been altered by hand"')
        prompts = []

        def fake(path, body, **k):
            if 'tools' in body:
                return _text({'findings': [], 'kept': []})
            if 'edits' in json.dumps(body.get('output_config', {})):
                prompts.append(body['messages'][0]['content'])
                return _text({'edits': [{
                    'problem': 1, 'find': 'She tapped the empty space on the map.',
                    'replace': 'She tapped the empty space on the map. "The map has been '
                               'altered by hand," she said.'}]})
            return _text({'commitments': [_commitment()]})
        prose = open(os.path.join(project_dir, 'scenes', f'{SCENE}.md')).read()
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake, ())):
            out = gate.gate_and_fix(project_dir, SCENE, command='draft', prose=prose,
                                    log_dir=str(tmp_path / 'logs'), extract_model='m',
                                    check_model='m')
        assert len(prompts) == 1 and 'The map has been altered by hand' in prompts[0]
        assert out.fixed and out.result.passed, gate.report_lines(out.result)


def _set_dialogue_raw(project_dir, value):
    _set_brief(project_dir, key_dialogue=value)


class TestVerbatimIn:
    PROSE = '"Left hand on the case," he said quietly. "Right hand free." She nodded.'

    def test_whole(self):
        assert gate._verbatim_in('right hand free', self.PROSE)

    def test_split_by_a_speech_tag(self):
        assert gate._verbatim_in('Left hand on the case, right hand free.', self.PROSE)

    def test_parts_too_far_apart(self):
        prose = ('"Left hand on the case," he said, and then he walked to the window and '
                 'looked out at the rain for a long time. "Right hand free."')
        assert not gate._verbatim_in('Left hand on the case, right hand free.', prose)

    def test_words_put_inside_the_quotation_are_not_a_tag(self):
        # CR-3: the inserted words invert the line; they are inside the quote
        line = 'I have kissed the hands, of the man, who killed my son'
        assert not gate._verbatim_in(
            line, '"I have kissed the hands, he said, but never of the man who killed my son."')
        assert gate._verbatim_in(
            line, '"I have kissed the hands," he said, "of the man, who killed my son."')
        assert not gate._verbatim_in(
            'Kill him, now', '"Kill him," she said, "never, not now."')

    def test_curly_quotes_split_by_a_tag(self):
        assert gate._verbatim_in('Left hand on the case, right hand free.',
                                 '\u201cLeft hand on the case,\u201d he said. '
                                 '\u201cRight hand free.\u201d')

    def test_quotations_in_different_paragraphs_are_not_joined(self):
        assert not gate._verbatim_in('Left hand on the case, right hand free.',
                                     '"Left hand on the case," he said.\n\n"Right hand free."')

    def test_a_word_changed(self):
        assert not gate._verbatim_in('Left hand on the box, right hand free.', self.PROSE)
