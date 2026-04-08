"""Shared fixtures for integration tests.

Provides git_project (real git repo in tmp) and mock_api/mock_git
fixtures that patch API and git boundaries for end-to-end command tests.
"""

import json
import os
import shutil
import subprocess
import pytest

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'test-project')


@pytest.fixture
def git_project(tmp_path):
    """A real git repo with test-project fixture, initialized and committed."""
    dest = tmp_path / 'test-project'
    shutil.copytree(FIXTURE_DIR, dest)
    subprocess.run(['git', 'init'], cwd=dest, capture_output=True)
    subprocess.run(['git', 'add', '-A'], cwd=dest, capture_output=True)
    subprocess.run(
        ['git', 'commit', '-m', 'Initial test fixture'],
        cwd=dest, capture_output=True,
        env={**os.environ, 'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@test.com',
             'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@test.com'},
    )
    return str(dest)


@pytest.fixture
def project_dir(tmp_path):
    """A fresh copy of the test-project fixture in a temp directory (no git)."""
    dest = tmp_path / 'test-project'
    shutil.copytree(FIXTURE_DIR, dest)
    return str(dest)


@pytest.fixture
def mock_api(monkeypatch):
    """Patch all API functions to return canned responses.

    Returns a controller to configure per-call responses.

    Usage:
        def test_something(mock_api):
            mock_api.set_response('Hello world')
            # Now invoke_api/invoke/invoke_to_file return this text
    """

    class ApiMock:
        def __init__(self):
            self.calls = []
            self._response_text = 'mock response'
            self._response_dict = None
            self._response_fn = None

        def set_response(self, text):
            self._response_text = text
            self._response_dict = {
                'content': [{'type': 'text', 'text': text}],
                'usage': {'input_tokens': 100, 'output_tokens': 50},
            }

        def set_response_fn(self, fn):
            """Set a function that receives the prompt and returns response text."""
            self._response_fn = fn

        def _get_response_text(self, prompt):
            if self._response_fn:
                return self._response_fn(prompt)
            return self._response_text

        def _get_response_dict(self, prompt):
            text = self._get_response_text(prompt)
            if self._response_dict and not self._response_fn:
                return self._response_dict
            return {
                'content': [{'type': 'text', 'text': text}],
                'usage': {'input_tokens': 100, 'output_tokens': 50},
            }

        def _invoke(self, prompt, model, max_tokens=4096, label='', timeout=600):
            self.calls.append({
                'fn': 'invoke', 'prompt': prompt, 'model': model,
                'max_tokens': max_tokens, 'label': label, 'timeout': timeout,
            })
            return self._get_response_dict(prompt)

        def _invoke_to_file(self, prompt, model, log_file, max_tokens=4096,
                           label='', timeout=600):
            self.calls.append({
                'fn': 'invoke_to_file', 'prompt': prompt, 'model': model,
                'log_file': log_file, 'max_tokens': max_tokens,
            })
            response = self._get_response_dict(prompt)
            os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
            with open(log_file, 'w') as f:
                json.dump(response, f)
            return response

        def _invoke_api(self, prompt, model, max_tokens=4096, label='',
                       timeout=600):
            self.calls.append({
                'fn': 'invoke_api', 'prompt': prompt, 'model': model,
            })
            return self._get_response_text(prompt)

        def _extract_text_from_file(self, path):
            if not os.path.isfile(path):
                return ''
            with open(path) as f:
                data = json.load(f)
            for item in data.get('content', []):
                if item.get('type') == 'text':
                    return item.get('text', '')
            return ''

        def _submit_batch(self, batch_file):
            self.calls.append({'fn': 'submit_batch', 'batch_file': batch_file})
            return 'batch-test-123'

        def _poll_batch(self, batch_id, log_fn=None):
            self.calls.append({'fn': 'poll_batch', 'batch_id': batch_id})
            return 'https://example.com/batch-results'

        def _download_batch_results(self, results_url, output_dir, log_dir):
            self.calls.append({'fn': 'download_batch_results', 'results_url': results_url})
            return 0

    mock = ApiMock()
    monkeypatch.setattr('storyforge.api.invoke', mock._invoke)
    monkeypatch.setattr('storyforge.api.invoke_to_file', mock._invoke_to_file)
    monkeypatch.setattr('storyforge.api.invoke_api', mock._invoke_api)
    monkeypatch.setattr('storyforge.api.extract_text_from_file', mock._extract_text_from_file)
    monkeypatch.setattr('storyforge.api.submit_batch', mock._submit_batch)
    monkeypatch.setattr('storyforge.api.poll_batch', mock._poll_batch)
    monkeypatch.setattr('storyforge.api.download_batch_results', mock._download_batch_results)

    # Also patch where modules import these at top level
    for mod in [
        'storyforge.cmd_write',
        'storyforge.cmd_score',
        'storyforge.cmd_extract',
        'storyforge.cmd_elaborate',
    ]:
        try:
            monkeypatch.setattr(f'{mod}.invoke_to_file', mock._invoke_to_file)
        except AttributeError:
            pass
        try:
            monkeypatch.setattr(f'{mod}.extract_text_from_file', mock._extract_text_from_file)
        except AttributeError:
            pass
        try:
            monkeypatch.setattr(f'{mod}.invoke_api', mock._invoke_api)
        except AttributeError:
            pass
        try:
            monkeypatch.setattr(f'{mod}.submit_batch', mock._submit_batch)
        except AttributeError:
            pass
        try:
            monkeypatch.setattr(f'{mod}.poll_batch', mock._poll_batch)
        except AttributeError:
            pass
        try:
            monkeypatch.setattr(f'{mod}.download_batch_results', mock._download_batch_results)
        except AttributeError:
            pass

    return mock


@pytest.fixture
def mock_git(monkeypatch):
    """Patch git operations to avoid real git/gh calls.

    Returns a controller to inspect calls and set return values.
    """

    class GitMock:
        def __init__(self):
            self.calls = []
            self.branch = 'storyforge/test-20260407'
            self.has_gh = False

        def _current_branch(self, project_dir):
            return self.branch

        def _git(self, project_dir, *args, check=True):
            self.calls.append(args)
            return subprocess.CompletedProcess(
                args=['git'] + list(args), returncode=0,
                stdout=self.branch, stderr='',
            )

        def _has_gh(self):
            return self.has_gh

        def _commit_and_push(self, project_dir, message, paths=None):
            self.calls.append(('commit_and_push', message, paths))
            return True

        def _create_branch(self, command_name, project_dir):
            self.calls.append(('create_branch', command_name))
            return self.branch

        def _ensure_on_branch(self, command_name, project_dir):
            self.calls.append(('ensure_on_branch', command_name))
            return self.branch

        def _ensure_branch_pushed(self, project_dir, branch=None):
            self.calls.append(('ensure_branch_pushed',))
            return True

        def _create_draft_pr(self, title, body, project_dir, work_type=''):
            self.calls.append(('create_draft_pr', title))
            return '42'

        def _update_pr_task(self, task_text, project_dir, pr_number=''):
            self.calls.append(('update_pr_task', task_text))

        def _run_review_phase(self, review_type, project_dir, pr_number=''):
            self.calls.append(('run_review_phase', review_type))

    mock = GitMock()
    monkeypatch.setattr('storyforge.git.current_branch', mock._current_branch)
    monkeypatch.setattr('storyforge.git._git', mock._git)
    monkeypatch.setattr('storyforge.git.has_gh', mock._has_gh)
    monkeypatch.setattr('storyforge.git.commit_and_push', mock._commit_and_push)
    monkeypatch.setattr('storyforge.git.create_branch', mock._create_branch)
    monkeypatch.setattr('storyforge.git.ensure_on_branch', mock._ensure_on_branch)
    monkeypatch.setattr('storyforge.git.ensure_branch_pushed', mock._ensure_branch_pushed)
    monkeypatch.setattr('storyforge.git.create_draft_pr', mock._create_draft_pr)
    monkeypatch.setattr('storyforge.git.update_pr_task', mock._update_pr_task)
    monkeypatch.setattr('storyforge.git.run_review_phase', mock._run_review_phase)

    # Also patch where command modules import git functions at top level
    for mod in [
        'storyforge.cmd_write',
        'storyforge.cmd_score',
        'storyforge.cmd_extract',
        'storyforge.cmd_elaborate',
        'storyforge.cmd_assemble',
        'storyforge.cmd_hone',
        'storyforge.cmd_revise',
    ]:
        for fn_name, fn in [
            ('create_branch', mock._create_branch),
            ('ensure_branch_pushed', mock._ensure_branch_pushed),
            ('ensure_on_branch', mock._ensure_on_branch),
            ('create_draft_pr', mock._create_draft_pr),
            ('commit_and_push', mock._commit_and_push),
            ('update_pr_task', mock._update_pr_task),
            ('run_review_phase', mock._run_review_phase),
            ('_git', mock._git),
            ('has_gh', mock._has_gh),
            ('current_branch', mock._current_branch),
        ]:
            try:
                monkeypatch.setattr(f'{mod}.{fn_name}', fn)
            except AttributeError:
                pass

    return mock
