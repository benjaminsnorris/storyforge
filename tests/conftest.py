"""Shared pytest fixtures for Storyforge tests.

Replaces the bash test runner's setup: FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR,
and all assertion functions (now native pytest assertions).
"""

import os
import shutil
import sys
from pathlib import Path

import pytest

# Add the Python library to the path
TESTS_DIR = Path(__file__).parent
PLUGIN_DIR = TESTS_DIR.parent
PYTHON_LIB = PLUGIN_DIR / 'scripts' / 'lib' / 'python'
sys.path.insert(0, str(PYTHON_LIB))

FIXTURE_DIR = TESTS_DIR / 'fixtures' / 'test-project'


@pytest.fixture
def fixture_dir():
    """Path to the test-project fixture directory."""
    return str(FIXTURE_DIR)


@pytest.fixture
def project_dir(tmp_path):
    """A fresh copy of the test-project fixture in a temp directory.

    Use this when tests modify files — prevents contaminating the fixture.
    """
    dest = tmp_path / 'test-project'
    shutil.copytree(FIXTURE_DIR, dest)
    return str(dest)


@pytest.fixture
def plugin_dir():
    """Path to the Storyforge plugin root directory."""
    return str(PLUGIN_DIR)


@pytest.fixture
def ref_dir(fixture_dir):
    """Path to the reference directory in the fixture."""
    return os.path.join(fixture_dir, 'reference')


@pytest.fixture
def meta_csv(fixture_dir):
    """Path to the scenes.csv in the fixture."""
    return os.path.join(fixture_dir, 'reference', 'scenes.csv')


@pytest.fixture
def intent_csv(fixture_dir):
    """Path to the scene-intent.csv in the fixture."""
    return os.path.join(fixture_dir, 'reference', 'scene-intent.csv')


@pytest.fixture
def briefs_csv(fixture_dir):
    """Path to the scene-briefs.csv in the fixture."""
    return os.path.join(fixture_dir, 'reference', 'scene-briefs.csv')
