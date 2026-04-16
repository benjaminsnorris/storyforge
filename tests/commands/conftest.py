"""Shared fixtures for command module tests.

Provides mock_api and mock_git fixtures that patch the API and git
boundaries so command orchestration logic can be tested without
real API calls or git operations.

Also provides a canned response loader, project_dir fixture for
write-safe tests, and mock_costs for cost tracking isolation.

Fixtures are composable -- a test can use mock_api without mock_git
or vice versa.
"""

import importlib
import json
import os
import shutil
import subprocess

import pytest


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

TESTS_DIR = os.path.dirname(os.path.dirname(__file__))
FIXTURE_DIR = os.path.join(TESTS_DIR, 'fixtures', 'test-project')
API_RESPONSES_DIR = os.path.join(TESTS_DIR, 'fixtures', 'api-responses')


# ---------------------------------------------------------------------------
# Command modules that import api/git/costs at top level.
# Defined once so all mock fixtures patch the same set.
# ---------------------------------------------------------------------------

_CMD_MODULES = [
    'storyforge.cmd_annotations',
    'storyforge.cmd_validate',
    'storyforge.cmd_write',
    'storyforge.cmd_score',
    'storyforge.cmd_extract',
    'storyforge.cmd_elaborate',
    'storyforge.cmd_evaluate',
    'storyforge.cmd_revise',
    'storyforge.cmd_hone',
    'storyforge.cmd_enrich',
    'storyforge.cmd_review',
    'storyforge.cmd_cleanup',
    'storyforge.cmd_assemble',
    'storyforge.cmd_timeline',
    'storyforge.cmd_scenes_setup',
    'storyforge.cmd_migrate',
    'storyforge.cmd_visualize',
]


# ---------------------------------------------------------------------------
# Canned response loader
# ---------------------------------------------------------------------------

def load_api_response(name: str) -> dict:
    """Load a canned API response from tests/fixtures/api-responses/.

    Args:
        name: Response filename without .json extension (e.g. 'drafting',
              'scoring', 'evaluation/synthesis').

    Returns:
        Parsed JSON dict in Anthropic Messages API response format.
    """
    path = os.path.join(API_RESPONSES_DIR, f'{name}.json')
    with open(path) as f:
        return json.load(f)


def load_api_response_text(name: str) -> str:
    """Load just the text content from a canned API response.

    Joins all text blocks with newlines, matching production extract_text behavior.
    """
    response = load_api_response(name)
    texts = []
    for block in response.get('content', []):
        if block.get('type') == 'text':
            texts.append(block.get('text', ''))
    return '\n'.join(texts)


# ---------------------------------------------------------------------------
# Prevent signal handler and log file leaks from main() calls
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_global_state(monkeypatch):
    """Prevent command main() calls from leaking global state.

    - install_signal_handlers: no-op to prevent SIGINT/SIGTERM handler changes
    - _log_file: reset after each test so log output doesn't go to stale paths
    """
    noop = lambda: None
    monkeypatch.setattr('storyforge.common.install_signal_handlers', noop)
    # Also patch where cmd modules import it at top level
    for mod_name in _CMD_MODULES:
        mod = importlib.import_module(mod_name)
        if hasattr(mod, 'install_signal_handlers'):
            monkeypatch.setattr(f'{mod_name}.install_signal_handlers', noop)
    yield
    import storyforge.common
    storyforge.common._log_file = None


# ---------------------------------------------------------------------------
# project_dir fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def project_dir(tmp_path):
    """A fresh copy of the test-project fixture in a temp directory.

    Use this when tests modify files. Each test gets its own copy
    so mutations don't leak between tests.

    Sets up the working/ subdirectories that command modules expect.
    """
    dest = tmp_path / 'test-project'
    shutil.copytree(FIXTURE_DIR, dest)

    # Ensure working directories that commands expect
    for subdir in [
        'working/logs', 'working/scores', 'working/costs',
        'working/evaluations', 'working/reviews', 'working/coaching',
    ]:
        os.makedirs(os.path.join(str(dest), subdir), exist_ok=True)

    return str(dest)


# ---------------------------------------------------------------------------
# mock_api fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_api(monkeypatch):
    """Patch all API functions to return canned responses.

    Returns a controller object to configure per-call responses.

    Usage:
        def test_something(mock_api):
            mock_api.set_response('Hello world')
            # Now invoke_api/invoke/invoke_to_file return this text

        def test_with_canned(mock_api):
            data = load_api_response('scoring')
            mock_api.set_response_dict(data)

        def test_sequence(mock_api):
            mock_api.set_responses(['first call', 'second call'])
            # Returns them in order, then repeats the last one

        def test_pattern(mock_api):
            mock_api.set_response_fn(lambda prompt: 'score' if 'score' in prompt else 'other')
    """

    class ApiMock:
        def __init__(self):
            self.calls = []
            self._response_text = 'mock response'
            self._response_dict = None
            self._response_fn = None
            self._responses_queue = []
            self._batch_results = []

        def set_response(self, text: str):
            """Set a static text response for all API calls."""
            self._response_text = text
            self._response_dict = {
                'content': [{'type': 'text', 'text': text}],
                'usage': {'input_tokens': 100, 'output_tokens': 50},
            }
            self._response_fn = None
            self._responses_queue = []

        def set_response_dict(self, response: dict):
            """Set a full API response dict (e.g. from load_api_response)."""
            self._response_dict = response
            # Extract text for invoke_api convenience
            for block in response.get('content', []):
                if block.get('type') == 'text':
                    self._response_text = block.get('text', '')
                    break
            self._response_fn = None
            self._responses_queue = []

        def set_responses(self, texts: list[str]):
            """Set a sequence of responses. Returns them in order,
            repeating the last one once exhausted."""
            self._responses_queue = list(texts)
            self._response_fn = None

        def set_response_fn(self, fn):
            """Set a function that receives the prompt and returns response text.

            Useful for tests that need different responses based on prompt content.
            """
            self._response_fn = fn
            self._responses_queue = []

        def _get_response_text(self, prompt: str) -> str:
            if self._response_fn:
                return self._response_fn(prompt)
            if self._responses_queue:
                text = self._responses_queue.pop(0)
                if not self._responses_queue:
                    # Keep last response for subsequent calls
                    self._responses_queue.append(text)
                return text
            return self._response_text

        def _get_response_dict(self, prompt: str) -> dict:
            text = self._get_response_text(prompt)
            if self._response_dict and not self._response_fn and not self._responses_queue:
                return self._response_dict
            return {
                'content': [{'type': 'text', 'text': text}],
                'usage': {'input_tokens': 100, 'output_tokens': 50},
            }

        def _invoke(self, prompt, model, max_tokens=4096, label='', timeout=600,
                    system=None):
            self.calls.append({
                'fn': 'invoke', 'prompt': prompt, 'model': model,
                'max_tokens': max_tokens, 'label': label, 'timeout': timeout,
                'system': system,
            })
            return self._get_response_dict(prompt)

        def _invoke_to_file(self, prompt, model, log_file, max_tokens=4096,
                           label='', timeout=600, system=None):
            self.calls.append({
                'fn': 'invoke_to_file', 'prompt': prompt, 'model': model,
                'log_file': log_file, 'max_tokens': max_tokens,
                'system': system,
            })
            response = self._get_response_dict(prompt)
            os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
            with open(log_file, 'w') as f:
                json.dump(response, f)
            return response

        def _invoke_api(self, prompt, model, max_tokens=4096, label='',
                       timeout=600, system=None):
            self.calls.append({
                'fn': 'invoke_api', 'prompt': prompt, 'model': model,
                'system': system,
            })
            return self._get_response_text(prompt)

        def _extract_text_from_file(self, path):
            if not os.path.isfile(path):
                return ''
            with open(path) as f:
                data = json.load(f)
            # Join all text blocks — matches production extract_text behavior
            texts = []
            for item in data.get('content', []):
                if item.get('type') == 'text':
                    texts.append(item.get('text', ''))
            return '\n'.join(texts)

        def _submit_batch(self, batch_file):
            self.calls.append({'fn': 'submit_batch', 'batch_file': batch_file})
            return 'batch-test-123'

        def _poll_batch(self, batch_id, log_fn=None):
            self.calls.append({'fn': 'poll_batch', 'batch_id': batch_id})
            return 'https://example.com/batch-results'

        def _download_batch_results(self, results_url, output_dir, log_dir):
            self.calls.append({
                'fn': 'download_batch_results',
                'results_url': results_url,
                'output_dir': output_dir,
                'log_dir': log_dir,
            })
            return self._batch_results

        @property
        def call_count(self) -> int:
            return len(self.calls)

        def calls_for(self, fn_name: str) -> list[dict]:
            """Return only calls to a specific function."""
            return [c for c in self.calls if c.get('fn') == fn_name]

        def last_prompt(self, fn_name: str = None) -> str:
            """Return the prompt from the most recent call (optionally filtered by fn)."""
            calls = self.calls_for(fn_name) if fn_name else self.calls
            if not calls:
                return ''
            return calls[-1].get('prompt', '')

    mock = ApiMock()
    monkeypatch.setattr('storyforge.api.invoke', mock._invoke)
    monkeypatch.setattr('storyforge.api.invoke_to_file', mock._invoke_to_file)
    monkeypatch.setattr('storyforge.api.invoke_api', mock._invoke_api)
    monkeypatch.setattr('storyforge.api.extract_text_from_file', mock._extract_text_from_file)
    monkeypatch.setattr('storyforge.api.submit_batch', mock._submit_batch)
    monkeypatch.setattr('storyforge.api.poll_batch', mock._poll_batch)
    monkeypatch.setattr('storyforge.api.download_batch_results', mock._download_batch_results)

    # Also patch where command modules import these at top level.
    # Use importlib+hasattr so typos and broken modules fail loudly
    # while genuinely absent imports are skipped silently.
    _api_attrs = [
        ('invoke', mock._invoke),
        ('invoke_to_file', mock._invoke_to_file),
        ('invoke_api', mock._invoke_api),
        ('extract_text_from_file', mock._extract_text_from_file),
        ('submit_batch', mock._submit_batch),
        ('poll_batch', mock._poll_batch),
        ('download_batch_results', mock._download_batch_results),
    ]
    for mod_name in _CMD_MODULES:
        mod = importlib.import_module(mod_name)
        for attr, fn in _api_attrs:
            if hasattr(mod, attr):
                monkeypatch.setattr(f'{mod_name}.{attr}', fn)

    return mock


# ---------------------------------------------------------------------------
# mock_git fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_git(monkeypatch):
    """Patch git operations to avoid real git calls.

    Returns a controller to inspect calls and set return values.

    Usage:
        def test_something(mock_git):
            mock_git.branch = 'storyforge/test-branch'
            # Now current_branch() returns this

        def test_pr(mock_git):
            mock_git.has_gh = True
            mock_git.pr_number = '99'
            # create_draft_pr now returns '99'
    """

    class GitMock:
        def __init__(self):
            self.calls = []
            self.branch = 'storyforge/test-20260407'
            self.has_gh = False
            self.pr_number = '42'
            self.commit_success = True

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
            return self.commit_success

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
            return self.pr_number

        def _update_pr_task(self, task_text, project_dir, pr_number=''):
            self.calls.append(('update_pr_task', task_text))

        def _run_review_phase(self, review_type, project_dir, pr_number=''):
            self.calls.append(('run_review_phase', review_type))

        def _commit_partial_work(self, project_dir):
            self.calls.append(('commit_partial_work',))

        @property
        def call_count(self) -> int:
            return len(self.calls)

        def calls_for(self, fn_name: str) -> list:
            """Return calls whose first element matches fn_name."""
            return [c for c in self.calls if isinstance(c, tuple) and c[0] == fn_name]

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
    monkeypatch.setattr('storyforge.git.commit_partial_work', mock._commit_partial_work)

    # Also patch where command modules import git functions at top level.
    _git_attrs = [
        ('create_branch', mock._create_branch),
        ('ensure_branch_pushed', mock._ensure_branch_pushed),
        ('ensure_on_branch', mock._ensure_on_branch),
        ('create_draft_pr', mock._create_draft_pr),
        ('commit_and_push', mock._commit_and_push),
        ('update_pr_task', mock._update_pr_task),
        ('run_review_phase', mock._run_review_phase),
        ('commit_partial_work', mock._commit_partial_work),
        ('_git', mock._git),
        ('has_gh', mock._has_gh),
        ('current_branch', mock._current_branch),
    ]
    for mod_name in _CMD_MODULES:
        mod = importlib.import_module(mod_name)
        for attr, fn in _git_attrs:
            if hasattr(mod, attr):
                monkeypatch.setattr(f'{mod_name}.{attr}', fn)

    return mock


# ---------------------------------------------------------------------------
# mock_costs fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_costs(monkeypatch):
    """Patch cost tracking functions to avoid file I/O.

    Returns a controller to inspect logged operations.
    """

    class CostsMock:
        def __init__(self):
            self.operations = []
            self.estimates = []
            self.threshold_ok = True

        def _log_operation(self, project_dir, operation, model,
                          input_tokens, output_tokens, cost,
                          duration_s=0, target='',
                          cache_read=0, cache_create=0):
            self.operations.append({
                'operation': operation, 'model': model,
                'input_tokens': input_tokens, 'output_tokens': output_tokens,
                'cost': cost, 'duration_s': duration_s, 'target': target,
                'cache_read': cache_read, 'cache_create': cache_create,
            })

        def _estimate_cost(self, operation, scope_count, avg_words, model):
            self.estimates.append({
                'operation': operation, 'scope_count': scope_count,
                'avg_words': avg_words, 'model': model,
            })
            return 0.10  # Nominal cost

        def _check_threshold(self, estimated_cost):
            return self.threshold_ok

        def _print_summary(self, project_dir, operation=None, session_start=None):
            self.operations.append({
                'fn': 'print_summary', 'operation': operation,
                'session_start': session_start,
            })

    mock = CostsMock()
    monkeypatch.setattr('storyforge.costs.log_operation', mock._log_operation)
    monkeypatch.setattr('storyforge.costs.estimate_cost', mock._estimate_cost)
    monkeypatch.setattr('storyforge.costs.check_threshold', mock._check_threshold)
    monkeypatch.setattr('storyforge.costs.print_summary', mock._print_summary)

    # Patch in command modules
    _cost_attrs = [
        ('log_operation', mock._log_operation),
        ('estimate_cost', mock._estimate_cost),
        ('check_threshold', mock._check_threshold),
        ('print_summary', mock._print_summary),
    ]
    for mod_name in _CMD_MODULES:
        mod = importlib.import_module(mod_name)
        for attr, fn in _cost_attrs:
            if hasattr(mod, attr):
                monkeypatch.setattr(f'{mod_name}.{attr}', fn)

    return mock
