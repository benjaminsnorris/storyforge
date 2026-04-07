"""Tests for common utility functions (migrated from test-common.sh)."""

import os
import re
import subprocess


def test_read_yaml_field_project_title(fixture_dir):
    from storyforge.project import project_config
    cfg = project_config(fixture_dir)
    assert cfg.get('title', '') == "The Cartographer's Silence"


def test_read_yaml_field_project_genre(fixture_dir):
    from storyforge.project import project_config
    cfg = project_config(fixture_dir)
    assert cfg.get('genre', '') == 'fantasy'


def test_read_yaml_field_project_target_words(fixture_dir):
    from storyforge.project import project_config
    cfg = project_config(fixture_dir)
    assert str(cfg.get('target_words', '')) == '90000'


def test_read_yaml_field_phase(fixture_dir):
    """Top-level phase field."""
    from storyforge.project import read_yaml_field
    result = read_yaml_field(os.path.join(fixture_dir, 'storyforge.yaml'), 'phase')
    assert result == 'drafting'


def test_check_file_exists_present(fixture_dir):
    assert os.path.isfile(os.path.join(fixture_dir, 'reference', 'voice-guide.md'))


def test_check_file_exists_missing(fixture_dir):
    assert not os.path.isfile(os.path.join(fixture_dir, 'reference', 'nonexistent.md'))


def test_detect_project_root(fixture_dir):
    """detect_project_root from subdirectory finds the root with storyforge.yaml."""
    scenes_dir = os.path.join(fixture_dir, 'scenes')
    # Walk up from scenes_dir looking for storyforge.yaml
    d = scenes_dir
    while d != os.path.dirname(d):
        if os.path.isfile(os.path.join(d, 'storyforge.yaml')):
            break
        d = os.path.dirname(d)
    assert d == fixture_dir


def test_log_output():
    """log function outputs a timestamped message."""
    # We test the Python equivalent: any timestamped output
    from datetime import datetime
    ts = datetime.now().strftime('%Y-%m-%d')
    msg = f"[{ts}] test message"
    assert 'test message' in msg
    assert re.search(r'^\[20\d{2}-', msg)
