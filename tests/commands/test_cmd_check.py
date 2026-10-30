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

    def test_later_scenes_checked_without_a_failing_scenes_facts_say_so(self, project):
        project_dir, _ = project
        with _api([[BAD], []]), pytest.raises(SystemExit):
            cmd_check.main(['--scenes', f'{SCENE},act2-sc01'])
        report = open(os.path.join(project_dir, 'working', 'check-report.md')).read()
        assert 'Checked without the facts' in report and 'act2-sc01' in report

    def test_no_scenes_named_is_an_error(self, project):
        with pytest.raises(SystemExit):
            cmd_check.main([])


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

    def test_the_fix_prompt_lists_each_problem(self, project_dir, tmp_path):
        result = gate.GateResult(SCENE)
        from storyforge.checker import CheckResult, Finding
        result.check = CheckResult(SCENE, findings=[Finding(**BAD)])
        problems = gate.problems_to_fix(result)
        assert len(problems) == 1 and HERE in problems[0]
        assert '1. TIM contradiction' in gate.build_fix_prompt(SCENE, 'prose', problems)
