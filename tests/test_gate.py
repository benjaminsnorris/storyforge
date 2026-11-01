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

    def test_a_short_brief_phrase_is_not_a_source(self, project_dir):
        _set_dialogue(project_dir, '"No."; "It was there forty years ago."')
        assert gate._brief_phrases(project_dir, SCENE) == ['It was there forty years ago.']


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
            "It was there forty years ago. It isn't there now. There is no note."])

    def test_a_short_brief_line_inside_a_long_quote_is_not_a_plan_conflict(self):
        """SF-8: the error ("three moons") is outside the scripted words."""
        assert not gate._is_plan_conflict(
            '"I\'ll see you at dawn," she said, as the three moons rose over the ridge',
            ["I'll see you at dawn"])
        assert gate._is_plan_conflict('"I\'ll see you at dawn," she said',
                                      ["I'll see you at dawn"])

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


def test_a_recheck_is_gated_with_no_baseline(project_dir, tmp_path, monkeypatch):
    """#480's review: a re-check runs because another scene changed, not this
    one's words; a baseline would make every finding inherited."""
    gate.mark_pending(project_dir, SCENE, 'recheck', 'x')
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
    assert kwargs and all(k.get('before') is None for k in kwargs)
