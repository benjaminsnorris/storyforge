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

    def test_a_later_fact_leaning_on_a_replaced_commitment_raises(self, project_dir, tmp_path):
        _gate(project_dir, tmp_path, [_commitment()])
        rows = ledger.load(project_dir)
        mine = next(r for r in rows if r['scene_id'] == SCENE and ledger.is_commitment(r))
        later = dict(mine, id='later-fact', scene_id='act2-sc01', depends_on=mine['id'])
        ledger.save(project_dir, rows + [later], command='test')
        with pytest.raises(GateError, match='lean on'):
            _gate(project_dir, tmp_path, [_commitment()], command='redraft')

    def test_a_replaced_state_a_later_scene_ended_raises(self, project_dir, tmp_path):
        """Replacing it would drop the later scene's end: the state would read
        as in force for the rest of the book."""
        _gate(project_dir, tmp_path, [_commitment()])
        rows = ledger.load(project_dir)
        mine = next(r for r in rows if r['scene_id'] == SCENE and ledger.is_commitment(r))
        mine['resolves'] = 'act2-sc01'
        ledger.save(project_dir, rows, command='test')
        with pytest.raises(GateError, match='act2-sc01 ends'):
            _gate(project_dir, tmp_path, [_commitment()], command='redraft')

    def test_a_state_ended_in_its_own_scene_or_never_does_not_lean(self):
        rows = [{'id': 'a', 'scene_id': 's1', 'resolves': 's1'},
                {'id': 'b', 'scene_id': 's1', 'resolves': 'never'},
                {'id': 'c', 'scene_id': 's1', 'resolves': ''}]
        assert gate._leaning_on(rows, {'a', 'b', 'c'}) == []

    def test_an_end_at_a_deleted_scene_does_not_lean(self):
        rows = [{'id': 'a', 'scene_id': 's1', 'resolves': 'gone'}]
        assert gate._leaning_on(rows, {'a'}, {'s1': 0}) == []
        assert gate._leaning_on(rows, {'a'}) == ['gone ends → a']

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
