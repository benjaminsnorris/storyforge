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
FIXTURE_DIR_GN = TESTS_DIR / 'fixtures' / 'test-project-gn'


# A fixed Models API catalog, so model resolution never reaches the network in
# tests. Tests of resolution itself monkeypatch ``storyforge.common._catalog``.
STUB_MODEL_CATALOG = [
    {'id': 'claude-opus-5-5', 'created_at': '2026-09-21T16:24:00Z', 'max_tokens': 128000},
    {'id': 'claude-sonnet-5-5', 'created_at': '2026-09-28T00:00:00Z', 'max_tokens': 128000},
    {'id': 'claude-haiku-5-5', 'created_at': '2026-10-07T18:00:00Z', 'max_tokens': 128000},
    {'id': 'claude-opus-4-8', 'created_at': '2026-05-28T00:00:00Z', 'max_tokens': 128000},
    {'id': 'claude-sonnet-4-6', 'created_at': '2026-02-17T00:00:00Z', 'max_tokens': 128000},
    {'id': 'claude-haiku-4-5-20251001', 'created_at': '2025-10-15T00:00:00Z', 'max_tokens': 64000},
]


@pytest.fixture(autouse=True)
def _stub_model_catalog(monkeypatch):
    import storyforge.common as common
    monkeypatch.setattr(common, '_catalog', [dict(m) for m in STUB_MODEL_CATALOG])


@pytest.fixture(autouse=True)
def _no_live_api(monkeypatch):
    """No test reaches the network: `api`'s HTTP call fails the test instead
    of spending (a test that mocks `urlopen`, `_live_request`, `_api_request`
    or a caller replaces or never reaches this)."""
    import storyforge.api as api

    def live(*a, **k):
        raise AssertionError('a test tried a live API request (mock api._api_request '
                             'or the function calling it)')
    monkeypatch.setattr(api, 'urlopen', live)


@pytest.fixture(autouse=True)
def _fresh_fallback_replies(monkeypatch):
    """api records refusal-fallback replies per process; keep them per test."""
    import storyforge.api as api
    monkeypatch.setattr(api, '_fallback_replies', [])


@pytest.fixture(autouse=True)
def _gate_passes_in_write(request, monkeypatch):
    """`write` gates every drafted scene (storyforge.gate), which makes model
    calls of its own. Tests about drafting itself mock one reply per scene,
    so the gate is a pass here unless a test is marked `real_gate`."""
    if request.node.get_closest_marker('real_gate'):
        return
    import storyforge.cmd_write as cmd_write
    monkeypatch.setattr(cmd_write, '_gate_drafted_scene', lambda *a, **k: (True, ''))


def pytest_configure(config):
    config.addinivalue_line('markers', 'real_gate: run write\'s gate instead of the pass stub')


@pytest.fixture
def fixture_dir_gn():
    """Path to the graphic-novel test-project fixture."""
    return str(FIXTURE_DIR_GN)


@pytest.fixture
def project_dir_gn(tmp_path):
    """A fresh copy of the graphic-novel fixture in a temp directory."""
    dest = tmp_path / 'test-project-gn'
    shutil.copytree(FIXTURE_DIR_GN, dest)
    return str(dest)


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
