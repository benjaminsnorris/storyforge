"""Shared fixtures for command module tests.

Provides mock_api and mock_git fixtures that patch the API and git
boundaries so command orchestration logic can be tested without
real API calls or git operations.
"""

import json
import os
import pytest


@pytest.fixture
def mock_api(monkeypatch):
    """Patch all API functions to return canned responses.

    Returns a controller object to configure per-call responses.

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

        def set_response(self, text):
            self._response_text = text
            self._response_dict = {
                'content': [{'type': 'text', 'text': text}],
                'usage': {'input_tokens': 100, 'output_tokens': 50},
            }

        def _invoke(self, prompt, model, max_tokens=4096, label='', timeout=600):
            self.calls.append({
                'fn': 'invoke', 'prompt': prompt, 'model': model,
                'max_tokens': max_tokens, 'label': label, 'timeout': timeout,
            })
            return self._response_dict or {
                'content': [{'type': 'text', 'text': self._response_text}],
                'usage': {'input_tokens': 100, 'output_tokens': 50},
            }

        def _invoke_to_file(self, prompt, model, log_file, max_tokens=4096,
                           label='', timeout=600):
            self.calls.append({
                'fn': 'invoke_to_file', 'prompt': prompt, 'model': model,
                'log_file': log_file, 'max_tokens': max_tokens,
            })
            response = self._invoke(prompt, model, max_tokens, label, timeout)
            os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
            with open(log_file, 'w') as f:
                json.dump(response, f)
            return response

        def _invoke_api(self, prompt, model, max_tokens=4096, label='',
                       timeout=600):
            self.calls.append({
                'fn': 'invoke_api', 'prompt': prompt, 'model': model,
            })
            return self._response_text

    mock = ApiMock()
    monkeypatch.setattr('storyforge.api.invoke', mock._invoke)
    monkeypatch.setattr('storyforge.api.invoke_to_file', mock._invoke_to_file)
    monkeypatch.setattr('storyforge.api.invoke_api', mock._invoke_api)
    return mock


@pytest.fixture
def mock_git(monkeypatch):
    """Patch git operations to avoid real git calls.

    Returns a controller to inspect calls and set return values.

    Usage:
        def test_something(mock_git):
            mock_git.branch = 'storyforge/test-branch'
            # Now current_branch() returns this
    """

    class GitMock:
        def __init__(self):
            self.calls = []
            self.branch = 'storyforge/test-20260407'
            self.has_gh = False

        def _current_branch(self, project_dir):
            return self.branch

        def _git(self, project_dir, *args, check=True):
            import subprocess
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

    mock = GitMock()
    monkeypatch.setattr('storyforge.git.current_branch', mock._current_branch)
    monkeypatch.setattr('storyforge.git._git', mock._git)
    monkeypatch.setattr('storyforge.git.has_gh', mock._has_gh)
    monkeypatch.setattr('storyforge.git.commit_and_push', mock._commit_and_push)
    monkeypatch.setattr('storyforge.git.create_branch', mock._create_branch)
    monkeypatch.setattr('storyforge.git.ensure_on_branch', mock._ensure_on_branch)
    return mock


def load_api_response(name):
    """Load a canned API response from tests/fixtures/api-responses/."""
    path = os.path.join(os.path.dirname(__file__), '..', 'fixtures',
                        'api-responses', f'{name}.json')
    with open(path) as f:
        return json.load(f)
