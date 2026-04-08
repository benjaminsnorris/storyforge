"""Command-level tests for storyforge.common module.

Tests core infrastructure: project root detection, YAML reading, model selection,
coaching level, pipeline manifest CRUD, and signal handling.
"""

import os
import sys

import pytest

from storyforge.common import (
    detect_project_root,
    read_yaml_field,
    _strip_yaml_value,
    select_model,
    select_revision_model,
    get_coaching_level,
    get_plugin_dir,
    log,
    set_log_file,
    check_file_exists,
    get_pipeline_file,
    ensure_pipeline_manifest,
    get_current_cycle,
    start_new_cycle,
    update_cycle_field,
    install_signal_handlers,
    is_shutting_down,
    PIPELINE_HEADER,
)


# ============================================================================
# detect_project_root
# ============================================================================

class TestDetectProjectRoot:
    def test_from_project_dir(self, fixture_dir):
        result = detect_project_root(fixture_dir)
        assert result == fixture_dir

    def test_from_subdirectory(self, fixture_dir):
        sub = os.path.join(fixture_dir, 'scenes')
        result = detect_project_root(sub)
        assert result == fixture_dir

    def test_from_deep_subdirectory(self, fixture_dir):
        sub = os.path.join(fixture_dir, 'reference')
        result = detect_project_root(sub)
        assert result == fixture_dir

    def test_missing_yaml_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            detect_project_root(str(tmp_path))


# ============================================================================
# read_yaml_field
# ============================================================================

class TestReadYamlField:
    def test_simple_field(self, fixture_dir):
        result = read_yaml_field('phase', fixture_dir)
        assert result == 'drafting'

    def test_dotted_field(self, fixture_dir):
        result = read_yaml_field('project.title', fixture_dir)
        assert result == "The Cartographer's Silence"

    def test_dotted_genre(self, fixture_dir):
        result = read_yaml_field('project.genre', fixture_dir)
        assert result == 'fantasy'

    def test_missing_field_returns_empty(self, fixture_dir):
        result = read_yaml_field('nonexistent.field', fixture_dir)
        assert result == ''

    def test_no_yaml_returns_empty(self, tmp_path):
        result = read_yaml_field('anything', str(tmp_path))
        assert result == ''

    def test_strip_yaml_value_unquoted(self):
        assert _strip_yaml_value('hello') == 'hello'

    def test_strip_yaml_value_double_quoted(self):
        assert _strip_yaml_value('"hello world"') == 'hello world'

    def test_strip_yaml_value_single_quoted(self):
        assert _strip_yaml_value("'hello world'") == 'hello world'

    def test_strip_yaml_value_whitespace(self):
        assert _strip_yaml_value('  hello  ') == 'hello'


# ============================================================================
# select_model
# ============================================================================

class TestSelectModel:
    def test_drafting_gets_opus(self):
        result = select_model('drafting')
        assert 'opus' in result

    def test_evaluation_gets_sonnet(self):
        result = select_model('evaluation')
        assert 'sonnet' in result

    def test_unknown_defaults_to_opus(self):
        result = select_model('unknown_type')
        assert 'opus' in result

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_MODEL', 'custom-model')
        result = select_model('drafting')
        assert result == 'custom-model'

    def test_env_override_cleared(self, monkeypatch):
        monkeypatch.delenv('STORYFORGE_MODEL', raising=False)
        result = select_model('drafting')
        assert 'opus' in result

    def test_extraction_gets_haiku(self):
        result = select_model('extraction')
        assert 'haiku' in result

    def test_review_gets_sonnet(self):
        result = select_model('review')
        assert 'sonnet' in result


# ============================================================================
# select_revision_model
# ============================================================================

class TestSelectRevisionModel:
    def test_continuity_pass_gets_sonnet(self):
        result = select_revision_model('continuity-fix', 'fix continuity issues')
        assert 'sonnet' in result

    def test_timeline_pass_gets_sonnet(self):
        result = select_revision_model('timeline-check', '')
        assert 'sonnet' in result

    def test_creative_pass_gets_opus(self):
        result = select_revision_model('prose-polish', 'voice consistency')
        assert 'opus' in result

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_MODEL', 'my-model')
        result = select_revision_model('anything', '')
        assert result == 'my-model'


# ============================================================================
# get_coaching_level
# ============================================================================

class TestGetCoachingLevel:
    def test_default_is_full(self, tmp_path):
        # tmp_path has no storyforge.yaml
        result = get_coaching_level(str(tmp_path))
        assert result == 'full'

    def test_env_override(self, monkeypatch, fixture_dir):
        monkeypatch.setenv('STORYFORGE_COACHING', 'strict')
        result = get_coaching_level(fixture_dir)
        assert result == 'strict'

    def test_env_cleared_defaults(self, monkeypatch, fixture_dir):
        monkeypatch.delenv('STORYFORGE_COACHING', raising=False)
        # fixture doesn't have coaching_level set, so defaults to full
        result = get_coaching_level(fixture_dir)
        assert result == 'full'

    def test_none_project_dir_returns_full(self, monkeypatch):
        monkeypatch.delenv('STORYFORGE_COACHING', raising=False)
        result = get_coaching_level(None)
        assert result == 'full'


# ============================================================================
# get_plugin_dir
# ============================================================================

class TestGetPluginDir:
    def test_returns_repo_root(self, plugin_dir):
        result = get_plugin_dir()
        assert result == plugin_dir


# ============================================================================
# Pipeline manifest CRUD
# ============================================================================

class TestPipelineManifest:
    def test_get_pipeline_file(self, project_dir):
        pf = get_pipeline_file(project_dir)
        assert pf == os.path.join(project_dir, 'working', 'pipeline.csv')

    def test_ensure_creates_file(self, tmp_path):
        """Use a fresh dir with no pipeline.csv."""
        pdir = str(tmp_path / 'proj')
        os.makedirs(os.path.join(pdir, 'working'), exist_ok=True)
        ensure_pipeline_manifest(pdir)
        pf = get_pipeline_file(pdir)
        assert os.path.isfile(pf)
        with open(pf) as f:
            header = f.readline().strip()
        assert header == PIPELINE_HEADER

    def test_get_current_cycle_empty(self, tmp_path):
        """No pipeline.csv means cycle 0."""
        pdir = str(tmp_path / 'proj')
        os.makedirs(pdir)
        assert get_current_cycle(pdir) == 0

    def test_start_new_cycle(self, tmp_path):
        pdir = str(tmp_path / 'proj')
        os.makedirs(os.path.join(pdir, 'working'), exist_ok=True)
        cycle_id = start_new_cycle(pdir)
        assert cycle_id == 1
        assert get_current_cycle(pdir) == 1

    def test_start_second_cycle(self, tmp_path):
        pdir = str(tmp_path / 'proj')
        os.makedirs(os.path.join(pdir, 'working'), exist_ok=True)
        start_new_cycle(pdir)
        cycle_id = start_new_cycle(pdir)
        assert cycle_id == 2
        assert get_current_cycle(pdir) == 2

    def test_get_current_cycle_from_fixture(self, project_dir):
        """Fixture already has 3 cycles."""
        assert get_current_cycle(project_dir) == 3

    def test_update_cycle_field(self, project_dir):
        cycle_id = start_new_cycle(project_dir)
        update_cycle_field(project_dir, cycle_id, 'status', 'complete')
        from storyforge.common import read_cycle_field
        val = read_cycle_field(project_dir, cycle_id, 'status')
        assert val == 'complete'


# ============================================================================
# check_file_exists
# ============================================================================

class TestCheckFileExists:
    def test_existing_file_ok(self, fixture_dir):
        # Should not raise
        check_file_exists(
            os.path.join(fixture_dir, 'storyforge.yaml'),
            'storyforge.yaml',
        )

    def test_missing_file_exits(self, fixture_dir):
        with pytest.raises(SystemExit):
            check_file_exists(
                os.path.join(fixture_dir, 'nonexistent.txt'),
                'test file',
            )

    def test_relative_path_with_project_dir(self, fixture_dir):
        # storyforge.yaml is in fixture_dir
        check_file_exists('storyforge.yaml', project_dir=fixture_dir)


# ============================================================================
# Logging
# ============================================================================

class TestLogging:
    def test_log_to_file(self, tmp_path):
        logfile = str(tmp_path / 'test.log')
        set_log_file(logfile)
        log('test message')
        with open(logfile) as f:
            content = f.read()
        assert 'test message' in content
        # Reset log file to avoid side effects
        import storyforge.common as c
        c._log_file = None

    def test_log_includes_timestamp(self, capsys):
        import storyforge.common as c
        c._log_file = None
        log('hello')
        captured = capsys.readouterr()
        assert '[' in captured.out
        assert 'hello' in captured.out


# ============================================================================
# Signal handling
# ============================================================================

class TestSignalHandling:
    def test_install_signal_handlers_no_error(self):
        install_signal_handlers()

    def test_is_shutting_down_initially_false(self):
        import storyforge.common as c
        c._shutting_down = False
        assert not is_shutting_down()
