"""Shared fixtures for integration tests.

Provides git_project (real git repo in tmp) and mock_api_rich
(API mock with response matching based on prompt content).
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
