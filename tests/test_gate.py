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
    NAMES = frozenset({'thomas', 'thomas bright horse', 'cora'})

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
        assert not gate._is_plan_conflict(quote, self.LINE)   # no names known
        assert gate._is_plan_conflict('"Left hand on the case," said he. "Right hand free."',
                                      self.LINE)

    def test_speaker_names_come_from_the_character_registry(self, project_dir):
        import csv
        path = os.path.join(project_dir, 'reference', 'characters.csv')
        with open(path, newline='') as f:
            row = next(csv.DictReader(f, delimiter='|'))
        names = gate._speaker_names(project_dir)
        assert gate._words(row['name']).strip() in names

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
        out, dirs, _ = self._run(monkeypatch, tmp_path, [first, again],
                                 [(self.FIXED, self.EDITS)])
        assert _blocking_count(again) < _blocking_count(first)   # fewer, and still worse
        assert out.prose == self.PROSE and not out.fixed and out.discarded == 1
        assert out.result is first and out.first is first and out.rounds == []
        assert len(dirs) == 2   # no second round on the discarded prose
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
        out, _, _ = self._run(monkeypatch, tmp_path, [first, again], [(self.FIXED, self.EDITS)])
        assert out.prose == self.PROSE and out.result is first
        assert out.notes[0].startswith('fix round 1 brought in 1 problem(s) (TRT contradicts '
                                       'cache')

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

    def test_a_file_that_cannot_be_written_is_said_and_the_prose_kept(
            self, project_dir, monkeypatch, tmp_path):
        first, again = self._first_and_worse()
        self._runs(monkeypatch, project_dir, first, again)
        real = gate.record_blocked
        calls = []

        def flaky(pd, sid, command, findings):
            calls.append(findings)
            if len(calls) == 3:   # the put-back after the discard
                raise PermissionError('read-only')
            return real(pd, sid, command, findings)
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
        assert gate.RECHECK_COST_PER_SCENE == pytest.approx(0.95)


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
        result = _gate(project_dir, tmp_path, [_commitment()], findings=[promise],
                       command='recheck')
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
