"""Tests for `storyforge check` (advisor mode) and the gate's fix pass.
The API is mocked at `api._api_request`: a request with tools is the
checker, one with the fix schema is the fix, any other is extraction."""

import json
import os
from unittest.mock import patch

import pytest

from storyforge import cmd_check, gate, ledger

SCENE = 'act1-sc02'
HERE = 'population four hundred and twelve at last census'
BAD = {'kind': 'contradiction', 'code': 'TIM', 'scene_quote': HERE,
       'established_scene': 'act1-sc01', 'fact_id': '', 'explanation': 'why',
       'established_quote': 'Dorren Hayle pressed the brass calipers against the vellum'}



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

def _text(payload):
    return {'stop_reason': 'end_turn', 'model': 'm', 'usage': {},
            'content': [{'type': 'text', 'text': json.dumps(payload)}]}


def _api(checks, edits=()):
    """A fake API: each check reply in turn (findings lists), the fix edits."""
    checks = list(checks)

    def fake(path, body, **k):
        if 'tools' in body:
            return _text({'findings': checks.pop(0), 'kept': []})
        if 'edits' in json.dumps(body.get('output_config', {})):
            return _text({'edits': list(edits)})
        return _text({'commitments': []})
    return patch('storyforge.api._api_request', side_effect=fake)


@pytest.fixture
def project(project_dir, monkeypatch):
    monkeypatch.setattr(cmd_check, 'detect_project_root', lambda: project_dir)
    monkeypatch.setattr('storyforge.git.create_branch', lambda *a: 'b')
    commits = []
    monkeypatch.setattr('storyforge.git.commit_and_push',
                        lambda d, msg, paths=None: commits.append((msg, paths)) or True)
    monkeypatch.setenv('STORYFORGE_MODEL', 'm')
    return project_dir, commits


class TestCheck:
    def test_a_clean_scene_passes_and_commits_its_facts(self, project):
        project_dir, commits = project
        with _api([[]]):
            cmd_check.main([SCENE])
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert f'## {SCENE}: passed' in report
        assert commits and 'reference/commitments.csv' in commits[0][1]

    def test_a_finding_is_reported_never_fixed_and_exits_1(self, project):
        project_dir, _ = project
        path = os.path.join(project_dir, 'scenes', f'{SCENE}.md')
        before_prose, before_ledger = open(path).read(), ledger.load(project_dir)
        with _api([[BAD]]), pytest.raises(SystemExit) as e:
            cmd_check.main([SCENE])
        assert e.value.code == 1
        assert open(path).read() == before_prose
        assert ledger.load(project_dir) == before_ledger
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert f'## {SCENE}: did not pass' in report and 'CONTRADICTION: TIM' in report

    def test_the_first_failure_stops_the_run_and_lists_the_rest(self, project):
        """Review of #441 (H1): later scenes would be checked, and committed,
        against a ledger without the failing scene's facts."""
        project_dir, _ = project
        with _api([[BAD], []]) as api, pytest.raises(SystemExit) as e:
            cmd_check.main(['--scenes', f'{SCENE},act2-sc01'])
        assert e.value.code == 1
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert 'Not checked: act2-sc01' in report
        assert sum('tools' in c.args[1] for c in api.call_args_list) == 1
        assert SCENE in gate.pending(project_dir)

    def test_a_gate_error_stops_the_run_too(self, project, monkeypatch):
        project_dir, _ = project

        def boom(*a, **k):
            raise gate.GateError('extraction failed:\nHTTP 500')
        monkeypatch.setattr(gate, 'gate_scene', boom)
        with pytest.raises(SystemExit):
            cmd_check.main(['--scenes', f'{SCENE},act2-sc01'])
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert f'## {SCENE}: not checked' in report and 'failed: HTTP 500' in report
        assert 'Not checked: act2-sc01' in report

    def test_scenes_are_checked_in_reading_order(self, project, monkeypatch):
        seen = []

        def record(project_dir, scene_id, **k):
            seen.append(scene_id)
            return gate.GateResult(scene_id, check=None)
        monkeypatch.setattr(gate, 'gate_scene', record)
        cmd_check.main(['--scenes', f'act2-sc01,{SCENE}'])
        assert seen == [SCENE, 'act2-sc01']

    def test_an_unknown_scene_is_an_error(self, project):
        with pytest.raises(SystemExit) as e:
            cmd_check.main(['--scenes', f'{SCENE},nope-sc99'])
        assert e.value.code == 1

    def test_a_failed_commit_exits_1(self, project, monkeypatch):
        monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **k: False)
        with _api([[]]), pytest.raises(SystemExit) as e:
            cmd_check.main([SCENE])
        assert e.value.code == 1

    def test_no_scenes_named_is_an_error(self, project):
        with pytest.raises(SystemExit) as e:
            cmd_check.main([])
        assert e.value.code == 1


class TestFix:
    def test_apply_edits(self):
        assert gate.apply_edits('a b c', [{'find': 'b', 'replace': 'B'},
                                          {'find': 'c', 'replace': 'C'}]) == 'a B C'

    @pytest.mark.parametrize('edits, why', [
        ([{'find': 'x', 'replace': 'y'}], 'occurs 0 times'),
        ([{'find': 'a', 'replace': 'y'}], 'occurs 2 times'),
        ([{'find': 'a b', 'replace': ''}, {'find': 'b c', 'replace': ''}], 'overlap'),
    ])
    def test_apply_edits_refuses(self, edits, why):
        with pytest.raises(gate.GateError, match=why):
            gate.apply_edits('a b c a', edits)

    def test_a_failing_scene_is_fixed_once_and_rechecked(self, project_dir, tmp_path):
        prose = open(os.path.join(project_dir, 'scenes', f'{SCENE}.md')).read()
        edit = {'problem': 1, 'find': HERE, 'replace': 'population four hundred at last census'}
        with _api([[BAD], []], [edit]):
            out = gate.gate_and_fix(project_dir, SCENE, command='draft', prose=prose,
                                    log_dir=str(tmp_path), extract_model='m',
                                    check_model='m', fix_model='m')
        assert out.fixed and out.result.passed and out.result.committed
        assert not out.first.passed
        assert 'four hundred at last census' in out.prose

    def test_still_failing_after_the_fix_commits_nothing(self, project_dir, tmp_path):
        prose = open(os.path.join(project_dir, 'scenes', f'{SCENE}.md')).read()
        before = ledger.load(project_dir)
        with _api([[BAD], [BAD]], []):
            out = gate.gate_and_fix(project_dir, SCENE, command='draft', prose=prose,
                                    log_dir=str(tmp_path), extract_model='m',
                                    check_model='m', fix_model='m')
        assert not out.result.passed and not out.fixed
        assert ledger.load(project_dir) == before

    def test_a_fix_with_no_edits_is_not_regated(self, project_dir, tmp_path):
        """Review of #441 (M2): re-checking identical prose is a paid re-roll
        that could commit what the first check rejected."""
        prose = open(os.path.join(project_dir, 'scenes', f'{SCENE}.md')).read()
        with _api([[BAD], []], []) as api:
            out = gate.gate_and_fix(project_dir, SCENE, command='draft', prose=prose,
                                    log_dir=str(tmp_path), extract_model='m',
                                    check_model='m', fix_model='m')
        assert out.result is out.first and not out.result.passed
        assert sum('tools' in c.args[1] for c in api.call_args_list) == 1

    def test_a_failing_fix_keeps_the_first_runs_findings(self, project_dir, tmp_path):
        prose = open(os.path.join(project_dir, 'scenes', f'{SCENE}.md')).read()
        with _api([[BAD]], [{'problem': 1, 'find': 'not in the scene', 'replace': 'x'}]), \
                pytest.raises(gate.GateError) as e:
            gate.gate_and_fix(project_dir, SCENE, command='draft', prose=prose,
                              log_dir=str(tmp_path), extract_model='m',
                              check_model='m', fix_model='m')
        assert e.value.first.findings[0].code == 'TIM'

    @pytest.mark.parametrize('reply', [
        {'stop_reason': 'max_tokens', 'content': [{'type': 'text', 'text': '{}'}], 'usage': {}},
        _text('not json'),
        {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': '{"x": 1}'}], 'usage': {}},
    ])
    def test_a_bad_fix_reply_is_a_gate_error(self, tmp_path, reply):
        from storyforge.checker import CheckResult, Finding
        result = gate.GateResult(SCENE, check=CheckResult(SCENE, findings=[Finding(**BAD)]))
        with patch('storyforge.api._api_request', return_value=reply), \
                pytest.raises(gate.GateError, match='the fix failed'):
            gate.fix_scene(SCENE, 'prose', result, log_dir=str(tmp_path), model='m')

    def test_unverified_and_halts_are_told_apart_in_the_fix_prompt(self):
        from storyforge import audit
        from storyforge.checker import CheckResult, Finding
        result = gate.GateResult(SCENE, check=CheckResult(
            SCENE, unverified=[Finding(**BAD, problem='its established quote is not in x')]))
        result.proposed = [{'id': 'p1', 'statement': 'S', 'quote': 'the words'}]
        result.halts = [audit.Halt('supersedes-fixed', 'p1',
                                   "the prose supersedes the registry fact r1 ('R')")]
        lines = gate.problems_to_fix(result)
        assert 'The scene says: "the words"' in lines[0] and "'R'" in lines[0]
        assert lines[1].startswith('UNVERIFIED (the check\'s quotes did not hold up: '
                                   'its established quote is not in x')

    def test_apply_edits_on_crlf_prose(self):
        assert gate.apply_edits('a\r\nb c', [{'find': 'a\nb', 'replace': 'X'}]) == 'X c'

    def test_frontmatter_is_refused(self, project_dir, tmp_path):
        with pytest.raises(gate.GateError, match='frontmatter'):
            gate.gate_scene(project_dir, SCENE, command='draft', prose='---\nid: x\n---\nText',
                            log_dir=str(tmp_path))

    def test_the_fix_prompt_lists_each_problem(self, project_dir, tmp_path):
        result = gate.GateResult(SCENE)
        from storyforge.checker import CheckResult, Finding
        result.check = CheckResult(SCENE, findings=[Finding(**BAD)])
        problems = gate.problems_to_fix(result)
        assert len(problems) == 1 and HERE in problems[0]
        assert '1. TIM contradiction' in gate.build_fix_prompt(SCENE, 'prose', problems)
