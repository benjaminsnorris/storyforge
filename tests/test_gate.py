"""Tests for storyforge.gate: extract → halt → check → commit for one scene.
The API is mocked at `api._api_request`: a request with tools is the
checker, one without is extraction."""

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


def _gate(project_dir, tmp_path, commitments=(), findings=(), kept=(), **kw):
    def fake(path, body, **k):
        if 'tools' in body:
            return _text({'findings': list(findings), 'kept': list(kept)})
        return _text({'commitments': list(commitments)})
    with patch('storyforge.api._api_request', side_effect=fake):
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

    def test_superseding_a_registry_fact_in_force_is_a_plan_contradiction(
            self, project_dir, tmp_path):
        """Review of #439 (M4): the design note halts on superseding a
        registry fact in force entering the scene, not only one recorded for
        it, as ending one already did."""
        rows = ledger.load(project_dir)
        before = ledger.load(project_dir)
        result = _gate(project_dir, tmp_path, [_commitment(supersedes=rows[0]['id'])])
        assert [(h.kind, h.fact_id) for h in result.halts] == [
            ('plan-contradiction', result.proposed[0]['id'])]
        assert rows[0]['id'] in result.halts[0].detail
        self._unchanged(project_dir, before)

    def test_disagreeing_with_the_scenes_registry_fact_is_a_plan_contradiction(
            self, project_dir, tmp_path):
        rows = ledger.load(project_dir)
        here = next(r for r in rows if not ledger.is_commitment(r))
        here['scene_id'] = SCENE
        ledger.save(project_dir, rows, command='test')
        result = _gate(project_dir, tmp_path, [_commitment(supersedes=here['id'])])
        assert [h.kind for h in result.halts] == ['plan-contradiction']
        assert not result.committed


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

    def test_ending_a_registry_state_its_resolves_does_not_end_here_halts(
            self, project_dir, tmp_path):
        self._state(project_dir, 'limp', 'extract')
        result = _gate(project_dir, tmp_path, [_commitment(ends=['limp'])])
        assert [h.kind for h in result.halts] == ['plan-contradiction']
        assert {r['id']: r for r in ledger.load(project_dir)}['limp']['resolves'] == ''


class TestFailsLoud:
    def test_an_extraction_cut_off_raises(self, project_dir, tmp_path):
        def fake(path, body, **k):
            return _text({'commitments': []}, stop='max_tokens')
        with patch('storyforge.api._api_request', side_effect=fake), \
                pytest.raises(GateError, match='extraction failed'):
            gate_scene(project_dir, SCENE, command='draft', log_dir=str(tmp_path),
                       extract_model='m', check_model='m')

    def test_a_failed_check_raises(self, project_dir, tmp_path):
        def fake(path, body, **k):
            if 'tools' in body:
                return {'stop_reason': 'refusal', 'content': [], 'usage': {}}
            return _text({'commitments': []})
        before = ledger.load(project_dir)
        with patch('storyforge.api._api_request', side_effect=fake), \
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
        with patch('storyforge.api._api_request', side_effect=fake):
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
        with patch('storyforge.api._api_request', side_effect=fake), \
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
        with patch('storyforge.api._api_request', side_effect=fake), \
                pytest.raises(GateError, match='HTTP 500'):
            gate_scene(project_dir, SCENE, command='draft', log_dir=str(tmp_path),
                       extract_model='m', check_model='m')

    def test_facts_tied_to_no_scene_are_reported(self, project_dir, tmp_path):
        rows = ledger.load(project_dir)
        rows[0]['scene_id'] = 'renamed-scene'
        ledger.save(project_dir, rows, command='test')
        result = _gate(project_dir, tmp_path, [_commitment()])
        assert result.problems['unplaced'] == [rows[0]['id']]
