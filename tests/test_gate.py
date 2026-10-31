"""Tests for storyforge.gate: extract → halt → check → commit for one scene.
The API is mocked at `api._api_request`: a request with tools is the
checker, one whose schema asks for `verdicts` the persistence check, any
other extraction."""

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
        old = [{'id': 's--b', 'subject': '', 'type': 'world', 'statement': 'B', 'scene_id': 's'}]
        proposed = [{'id': 's--b', 'subject': '', 'type': 'world', 'statement': 'A'},
                    {'id': 's--b-2', 'subject': '', 'type': 'world', 'statement': 'B',
                     'supersedes': 's--b'}]
        gate._carry_ids(proposed, old, [], 's')
        ids = [p['id'] for p in proposed]
        assert ids[1] == 's--b' and ids[0] not in ('s--b', 's--b-2') and len(set(ids)) == 2
        assert proposed[1]['supersedes'] == ids[0]   # it meant the first proposed row

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
