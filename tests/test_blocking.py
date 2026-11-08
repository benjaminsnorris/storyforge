"""Tests for storyforge.blocking (#626): the scene's own blocking, read alone,
and the gate's use of it. The API is mocked at `api._api_request`."""

import json
import os
from unittest.mock import patch

import pytest

from storyforge import blocking, gate
from storyforge.blocking import BLOCKING_CODE, BlockingError, check_blocking

SCENE = 'act1-sc02'

#: The slip the author found in gawain's `guide-offers-secret-flight`
#: ("These are the kinds of errors that ruin the continuity of a story")
KNOT = ("Gawain sat him and listened. The guide had finished and was waiting. "
        "Gawain's right hand had moved on his thigh. It lay over the knot at his "
        "left hip now, the gauntlet closed loosely on the silk.")
RIGHT_ON_THIGH = "Gawain's right hand had moved on his thigh"
OVER_LEFT_HIP = 'It lay over the knot at his left hip now'


def _text(payload, stop='end_turn'):
    return {'stop_reason': stop, 'model': 'claude-opus-5-5',
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 1, 'output_tokens': 1}}


def _knot_finding(**over):
    item = {'kind': 'impossible', 'scene_quote': OVER_LEFT_HIP,
            'other_quote': RIGHT_ON_THIGH,
            'explanation': 'A right hand resting on the thigh cannot lie over a knot at the '
                           'left hip.'}
    item.update(over)
    return item


def _is_blocking(body):
    schema = (body.get('output_config') or {}).get('format', {}).get('schema', {})
    items = schema.get('properties', {}).get('findings', {}).get('items', {})
    return 'other_quote' in items.get('properties', {})


def _write_scene(project_dir, prose, scene=SCENE):
    with open(os.path.join(project_dir, 'scenes', f'{scene}.md'), 'w', encoding='utf-8') as f:
        f.write(prose)


# ============================================================================
# The reply, as findings
# ============================================================================

class TestToFinding:
    def test_verified_finding_is_blk_against_the_scene_itself(self):
        f = blocking.to_finding(SCENE, KNOT, _knot_finding())
        assert f.problem == ''
        assert f.code == BLOCKING_CODE == 'BLK'
        assert f.kind == 'contradiction'
        assert f.established_scene == SCENE
        assert f.established_quote == RIGHT_ON_THIGH
        assert f.explanation.startswith('(impossible) ')
        assert "breaks the scene's own blocking" in f.message()

    def test_quote_not_in_scene_is_unverified(self):
        f = blocking.to_finding(SCENE, KNOT, _knot_finding(scene_quote='his left hand was free'))
        assert f.problem == 'its scene quote is not in the scene'

    def test_second_quote_not_in_scene_is_unverified(self):
        f = blocking.to_finding(SCENE, KNOT, _knot_finding(other_quote='he held the reins'))
        assert f.problem == 'its second quote is not in the scene'

    def test_contradiction_needs_both_sides(self):
        f = blocking.to_finding(SCENE, KNOT, _knot_finding(kind='contradiction', other_quote=''))
        assert f.problem == 'a contradiction with only one side quoted'

    def test_one_sided_finding_is_set_against_its_own_sentence(self):
        """`gate._classify` reads `established_quote` to tell whether the
        finding was in the scene before the pass."""
        f = blocking.to_finding(SCENE, KNOT, {'kind': 'unclear', 'scene_quote': OVER_LEFT_HIP,
                                              'other_quote': '', 'explanation': 'whose hand'})
        assert f.problem == ''
        assert f.established_quote == OVER_LEFT_HIP

    def test_empty_quote_is_unverified(self):
        f = blocking.to_finding(SCENE, KNOT, _knot_finding(scene_quote='  '))
        assert f.problem == 'it quotes nothing from the scene'


class TestParse:
    def test_off_schema_raises(self):
        for bad in ('not json', '{}', '{"findings": 3}',
                    '{"findings": [{"kind": "style", "scene_quote": "a", '
                    '"other_quote": "", "explanation": "e"}]}'):
            with pytest.raises(ValueError):
                blocking.parse(bad)

    def test_empty_list_is_clean(self):
        assert blocking.parse('{"findings": []}') == []


# ============================================================================
# check_blocking
# ============================================================================

class TestCheckBlocking:
    def test_reads_the_scene_alone_and_returns_verified_findings(self, project_dir, tmp_path):
        _write_scene(project_dir, KNOT)
        sent = []

        def fake(path, body, **k):
            sent.append(body)
            return _text({'findings': [_knot_finding(),
                                       _knot_finding(scene_quote='nowhere in it')]})

        with patch('storyforge.api._api_request', side_effect=fake):
            result = check_blocking(project_dir, SCENE, model='m', readings=1,
                                    log_file=str(tmp_path / 'b.json'))
        assert len(sent) == 1
        prompt = sent[0]['messages'][0]['content']
        assert KNOT in prompt
        assert 'tools' not in sent[0]
        assert _is_blocking(sent[0])
        assert [f.scene_quote for f in result.findings] == [OVER_LEFT_HIP]
        assert [f.scene_quote for f in result.unverified] == ['nowhere in it']
        assert os.path.isfile(tmp_path / 'b.json')

    def test_prose_in_place_of_the_file(self, project_dir):
        with patch('storyforge.api._api_request',
                   side_effect=lambda p, b, **k: _text({'findings': [_knot_finding()]})):
            result = check_blocking(project_dir, SCENE, prose=KNOT, model='m')
        assert len(result.findings) == 1

    def test_retries_once_then_fails_loud(self, project_dir):
        calls = []

        def fake(path, body, **k):
            calls.append(body)
            return _text({'wrong': True})

        with patch('storyforge.api._api_request', side_effect=fake):
            with pytest.raises(BlockingError, match='failed twice'):
                check_blocking(project_dir, SCENE, prose=KNOT, model='m', readings=1)
        assert len(calls) == 2
        assert 'Your last answer was not usable' in calls[1]['messages'][0]['content']

    def test_retry_that_answers_is_used(self, project_dir):
        replies = iter([_text({'wrong': True}), _text({'findings': [_knot_finding()]})])
        with patch('storyforge.api._api_request', side_effect=lambda p, b, **k: next(replies)):
            result = check_blocking(project_dir, SCENE, prose=KNOT, model='m', readings=1)
        assert len(result.findings) == 1

    def test_truncated_reply_is_retried(self, project_dir):
        replies = iter([_text({'findings': []}, stop='max_tokens'), _text({'findings': []})])
        with patch('storyforge.api._api_request', side_effect=lambda p, b, **k: next(replies)):
            assert check_blocking(project_dir, SCENE, prose=KNOT, model='m',
                                  readings=1).findings == []

    def test_two_readings_by_default_their_union(self, project_dir, tmp_path):
        """One reading misses what another finds (#626: the author's own
        example was missed by one full read and found by the next)."""
        other = _knot_finding(kind='unclear', scene_quote='The guide had finished and was waiting',
                              other_quote='')
        replies = iter([_text({'findings': [_knot_finding()]}),
                        _text({'findings': [_knot_finding(scene_quote='left hip now'), other]})])
        sent = []

        def fake(path, body, **k):
            sent.append(body['messages'][0]['content'])
            return next(replies)

        with patch('storyforge.api._api_request', side_effect=fake):
            result = check_blocking(project_dir, SCENE, prose=KNOT, model='m',
                                    log_file=str(tmp_path / 'b.json'))
        assert blocking.BLOCKING_READINGS == 2
        assert len(sent) == 2
        assert 'independent reading 2' in sent[1] and 'independent reading' not in sent[0]
        # the second reading's quote of the same slip is one finding, kept once
        assert [f.scene_quote for f in result.findings] == [
            OVER_LEFT_HIP, 'The guide had finished and was waiting']
        assert os.path.isfile(tmp_path / 'b.r2.json')

    def test_readings_below_one_raise(self, project_dir):
        with pytest.raises(ValueError):
            check_blocking(project_dir, SCENE, prose=KNOT, model='m', readings=0)

    def test_no_prose_raises(self, project_dir):
        with pytest.raises(BlockingError, match='no prose'):
            check_blocking(project_dir, SCENE, prose='   ', model='m')


# ============================================================================
# The gate (#626's regression: the author's slip passed every gate run)
# ============================================================================

@pytest.mark.blocking_read
class TestGateReadsBlocking:
    def _run(self, project_dir, tmp_path, blocking_findings, before=None):
        asked = []

        def fake(path, body, **k):
            schema = (body.get('output_config') or {}).get('format', {}).get('schema', {})
            if 'tools' in body:
                return _text({'findings': [], 'kept': []})
            if 'verdicts' in schema.get('properties', {}):
                return _text({'verdicts': []})
            if _is_blocking(body):
                asked.append(body)
                return _text({'findings': list(blocking_findings)})
            return _text({'commitments': []})

        _write_scene(project_dir, KNOT)
        with patch('storyforge.api._api_request', side_effect=fake):
            result = gate.gate_scene(project_dir, SCENE, command='draft',
                                     log_dir=str(tmp_path / 'logs'), extract_model='m',
                                     check_model='m', before=before)
        return result, asked

    def test_the_authors_slip_stops_the_gate(self, project_dir, tmp_path):
        result, asked = self._run(project_dir, tmp_path, [_knot_finding()])
        assert len(asked) == 2   # BLOCKING_READINGS
        assert not result.passed
        assert not result.committed
        assert [f.code for f in result.findings] == ['BLK']
        assert os.path.isfile(tmp_path / 'logs' / f'gate-blocking-{SCENE}.json')
        report = '\n'.join(gate.report_lines(result))
        assert OVER_LEFT_HIP in report

    def test_clean_blocking_passes(self, project_dir, tmp_path):
        result, asked = self._run(project_dir, tmp_path, [])
        assert len(asked) == 2
        assert result.passed

    def test_unverified_blocking_finding_blocks(self, project_dir, tmp_path):
        result, _ = self._run(project_dir, tmp_path,
                              [_knot_finding(scene_quote='a sentence not in it')])
        assert not result.passed
        assert [f.code for f in result.unverified] == ['BLK']

    def test_slip_already_in_the_scene_is_inherited(self, project_dir, tmp_path):
        """A revise pass that didn't make the slip isn't stopped by it."""
        snap = gate.snapshot(project_dir)
        snap.scenes[SCENE] = KNOT
        result, _ = self._run(project_dir, tmp_path, [_knot_finding()], before=snap)
        assert [f.code for f in result.inherited] == ['BLK']
        assert result.passed

    def test_slip_the_pass_made_is_not_inherited(self, project_dir, tmp_path):
        snap = gate.snapshot(project_dir)
        snap.scenes[SCENE] = 'Gawain sat him and listened. His left hand was on the reins.'
        result, _ = self._run(project_dir, tmp_path, [_knot_finding()], before=snap)
        assert result.inherited == []
        assert not result.passed

    def test_fix_problem_names_the_scene_against_itself(self, project_dir, tmp_path):
        result, _ = self._run(project_dir, tmp_path, [_knot_finding()])
        lines = gate.problems_to_fix(result)
        assert any('BLK blocking' in line and RIGHT_ON_THIGH in line for line in lines)

    def test_blocking_failure_is_a_gate_error(self, project_dir, tmp_path):
        def fake(path, body, **k):
            if 'tools' in body:
                return _text({'findings': [], 'kept': []})
            if _is_blocking(body):
                return _text({'nope': 1})
            return _text({'commitments': []})

        _write_scene(project_dir, KNOT)
        with patch('storyforge.api._api_request', side_effect=fake):
            with pytest.raises(gate.GateError, match='blocking check failed twice'):
                gate.gate_scene(project_dir, SCENE, command='draft',
                                log_dir=str(tmp_path / 'logs'), extract_model='m',
                                check_model='m')


class TestGateBlockingSwitch:
    def test_off_outside_marked_tests(self):
        """conftest turns the read off for tests whose fakes don't answer it."""
        assert gate.GATE_BLOCKING is False


# ============================================================================
# The fix prompt and the drafting prompt
# ============================================================================

class TestFixPrompt:
    def test_blk_problem_gets_its_rule(self):
        prompt = gate.build_fix_prompt(SCENE, KNOT, [
            f'BLK blocking: the scene says "{OVER_LEFT_HIP}", against "{RIGHT_ON_THIGH}" '
            f'in the same scene. why'])
        assert 'the scene against itself, not against the book' in prompt

    def test_no_blk_problem_leaves_the_prompt_as_it_was(self):
        prompt = gate.build_fix_prompt(SCENE, KNOT, ['TIM contradiction: x'])
        assert 'against itself' not in prompt
        assert ("move an event to make a contradiction go away.\n- A broken promise"
                in prompt)


class TestDraftingRule:
    def test_brief_prompt_asks_for_straight_blocking(self, project_dir, plugin_dir):
        from storyforge.prompts import build_scene_prompt_from_briefs
        prompt = build_scene_prompt_from_briefs(SCENE, project_dir, plugin_dir,
                                                coaching_level='full')
        assert 'Keep the blocking straight within the scene' in prompt
        assert "can't do anything else until it lets go" in prompt


# ============================================================================
# check --blocking
# ============================================================================

class TestCheckBlockingCommand:
    def _main(self, project_dir, monkeypatch, argv, reply):
        from storyforge import cmd_check
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '100')
        monkeypatch.setattr(cmd_check, 'detect_project_root', lambda: project_dir)
        with patch('storyforge.api._api_request', side_effect=lambda p, b, **k: reply(b)):
            with pytest.raises(SystemExit) as e:
                cmd_check.main(argv)
        return e.value.code

    def test_finding_is_reported_and_exits_1(self, project_dir, monkeypatch):
        _write_scene(project_dir, KNOT)

        def reply(body):
            prompt = body['messages'][0]['content']
            return _text({'findings': [_knot_finding()] if KNOT in prompt else []})

        code = self._main(project_dir, monkeypatch, ['--blocking', '--scenes', SCENE], reply)
        assert code == 1
        with open(os.path.join(project_dir, 'working', 'blocking-report.md')) as f:
            report = f.read()
        assert f'## {SCENE}' in report and OVER_LEFT_HIP in report

    def test_clean_scene_exits_0(self, project_dir, monkeypatch):
        _write_scene(project_dir, KNOT)
        code = self._main(project_dir, monkeypatch, ['--blocking', '--scenes', SCENE],
                          lambda b: _text({'findings': []}))
        assert code == 0
        with open(os.path.join(project_dir, 'working', 'blocking-report.md')) as f:
            assert 'holds together' in f.read()

    def test_refuses_pending(self, project_dir, monkeypatch):
        code = self._main(project_dir, monkeypatch, ['--blocking', '--pending'],
                          lambda b: _text({'findings': []}))
        assert code == 1
