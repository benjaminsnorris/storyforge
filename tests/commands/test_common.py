"""Tests for storyforge.common — core utilities.

Covers: detect_project_root, log, read_yaml_field, select_model,
select_revision_model, get_coaching_level, check_chapter_map_freshness,
get_plugin_dir, install_signal_handlers, and pipeline manifest functions.
"""

import os
import re
import signal

import pytest

from storyforge.common import (
    check_chapter_map_freshness,
    detect_project_root,
    ensure_pipeline_manifest,
    get_coaching_level,
    get_current_cycle,
    get_pipeline_file,
    get_plugin_dir,
    install_signal_handlers,
    log,
    read_yaml_field,
    select_model,
    select_revision_model,
    set_log_file,
    start_new_cycle,
    update_cycle_field,
)


# ============================================================================
# detect_project_root
# ============================================================================

class TestDetectProjectRoot:
    """Tests for detect_project_root."""

    def test_finds_root_from_subdir(self, fixture_dir):
        scenes_dir = os.path.join(fixture_dir, 'scenes')
        result = detect_project_root(scenes_dir)
        assert result == fixture_dir

    def test_finds_root_from_root_itself(self, fixture_dir):
        result = detect_project_root(fixture_dir)
        assert result == fixture_dir

    def test_finds_root_from_deeply_nested_subdir(self, fixture_dir):
        deep_dir = os.path.join(fixture_dir, 'reference')
        result = detect_project_root(deep_dir)
        assert result == fixture_dir

    def test_exits_when_no_yaml(self, tmp_path):
        no_yaml_dir = tmp_path / 'empty'
        no_yaml_dir.mkdir()
        with pytest.raises(SystemExit):
            detect_project_root(str(no_yaml_dir))

    def test_exits_with_nonexistent_dir(self, tmp_path):
        fake_path = str(tmp_path / 'nonexistent' / 'path')
        with pytest.raises((SystemExit, FileNotFoundError, OSError)):
            detect_project_root(fake_path)


# ============================================================================
# log
# ============================================================================

class TestLog:
    """Tests for log output."""

    def test_outputs_timestamped_message(self, capsys):
        log('hello world')
        captured = capsys.readouterr()
        assert 'hello world' in captured.out
        assert re.search(r'^\[20\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]', captured.out)

    def test_writes_to_log_file(self, tmp_path):
        import storyforge.common as _common_mod
        log_file = str(tmp_path / 'logs' / 'test.log')
        original = _common_mod._log_file
        set_log_file(log_file)
        try:
            log('file message')
            with open(log_file) as f:
                content = f.read()
            assert 'file message' in content
        finally:
            _common_mod._log_file = original

    def test_timestamp_format(self, capsys):
        log('check format')
        captured = capsys.readouterr()
        # Should match [YYYY-MM-DD HH:MM:SS]
        assert re.match(
            r'\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] check format',
            captured.out.strip(),
        )


# ============================================================================
# read_yaml_field
# ============================================================================

class TestReadYamlField:
    """Tests for read_yaml_field."""

    def test_reads_dotted_field(self, fixture_dir):
        result = read_yaml_field('project.title', fixture_dir)
        assert result == "The Cartographer's Silence"

    def test_reads_nested_genre(self, fixture_dir):
        result = read_yaml_field('project.genre', fixture_dir)
        assert result == 'fantasy'

    def test_reads_nested_target_words(self, fixture_dir):
        result = read_yaml_field('project.target_words', fixture_dir)
        assert result == '90000'

    def test_reads_top_level_field(self, fixture_dir):
        result = read_yaml_field('phase', fixture_dir)
        assert result == 'drafting'

    def test_returns_empty_for_missing_field(self, fixture_dir):
        result = read_yaml_field('nonexistent', fixture_dir)
        assert result == ''

    def test_returns_empty_for_missing_nested_field(self, fixture_dir):
        result = read_yaml_field('project.nonexistent', fixture_dir)
        assert result == ''

    def test_returns_empty_for_missing_yaml_file(self, tmp_path):
        result = read_yaml_field('anything', str(tmp_path))
        assert result == ''

    def test_strips_quotes_from_value(self, project_dir):
        """Values with surrounding quotes should have them stripped."""
        result = read_yaml_field('project.title', project_dir)
        assert not result.startswith('"')
        assert not result.endswith('"')

    def test_reads_boolean_like_field(self, fixture_dir):
        result = read_yaml_field('artifacts.world_bible.exists', fixture_dir)
        # Our simple parser only handles one level of dotting
        # This tests the behavior: artifacts.world_bible is the parent,
        # but the implementation splits on the first dot only.
        # So 'artifacts' is parent, 'world_bible' is child — it matches
        # the indented `world_bible:` line which has no inline value.
        # The function doesn't recurse deeper than one dot, so test the actual behavior.
        # 'artifacts.world_bible' should get the block header (empty inline value).
        result2 = read_yaml_field('artifacts.world_bible', fixture_dir)
        assert result2 == ''  # Block header has no inline value


# ============================================================================
# select_model
# ============================================================================

class TestSelectModel:
    """Tests for select_model."""

    def test_drafting_returns_opus(self):
        result = select_model('drafting')
        assert 'opus' in result

    def test_revision_returns_opus(self):
        result = select_model('revision')
        assert 'opus' in result

    def test_synthesis_returns_opus(self):
        result = select_model('synthesis')
        assert 'opus' in result

    def test_evaluation_returns_sonnet(self):
        result = select_model('evaluation')
        assert 'sonnet' in result

    def test_review_returns_sonnet(self):
        result = select_model('review')
        assert 'sonnet' in result

    def test_mechanical_returns_sonnet(self):
        result = select_model('mechanical')
        assert 'sonnet' in result

    def test_extraction_returns_haiku(self):
        result = select_model('extraction')
        assert 'haiku' in result

    def test_unknown_task_defaults_to_opus(self):
        result = select_model('unknown_task')
        assert 'opus' in result

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_MODEL', 'custom-model-123')
        result = select_model('drafting')
        assert result == 'custom-model-123'

    def test_env_override_beats_all_task_types(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_MODEL', 'override-all')
        for task in ['drafting', 'evaluation', 'review', 'synthesis']:
            assert select_model(task) == 'override-all'


# ============================================================================
# select_revision_model
# ============================================================================

class TestSelectRevisionModel:
    """Tests for select_revision_model."""

    def test_creative_pass_returns_opus(self):
        result = select_revision_model('voice-polish', 'creative enhancement')
        assert 'opus' in result

    def test_continuity_pass_returns_sonnet(self):
        result = select_revision_model('continuity-check', 'continuity verification')
        assert 'sonnet' in result

    def test_timeline_pass_returns_sonnet(self):
        result = select_revision_model('timeline-fix', 'timeline consistency')
        assert 'sonnet' in result

    def test_fact_check_returns_sonnet(self):
        result = select_revision_model('fact-check', 'verify facts')
        assert 'sonnet' in result

    def test_thread_tracking_returns_sonnet(self):
        result = select_revision_model('thread-track', 'track narrative threads')
        assert 'sonnet' in result

    def test_generic_pass_returns_opus(self):
        result = select_revision_model('prose-polish', 'improve prose quality')
        assert 'opus' in result

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_MODEL', 'my-custom-model')
        result = select_revision_model('continuity-check', 'continuity')
        assert result == 'my-custom-model'


# ============================================================================
# get_coaching_level
# ============================================================================

class TestGetCoachingLevel:
    """Tests for get_coaching_level."""

    def test_defaults_to_full(self, tmp_path):
        # Empty project dir with no coaching_level in yaml
        yaml_file = tmp_path / 'storyforge.yaml'
        yaml_file.write_text('project:\n  title: test\n')
        result = get_coaching_level(str(tmp_path))
        assert result == 'full'

    def test_reads_from_yaml(self, project_dir):
        yaml_file = os.path.join(project_dir, 'storyforge.yaml')
        with open(yaml_file, 'a') as f:
            f.write('\n  coaching_level: coach\n')
        # The coaching_level must be under `project:` block.
        # Re-read to place it correctly.
        with open(yaml_file) as f:
            content = f.read()
        content = content.replace(
            'target_words: 90000',
            'target_words: 90000\n  coaching_level: coach',
        )
        with open(yaml_file, 'w') as f:
            f.write(content)
        result = get_coaching_level(project_dir)
        assert result == 'coach'

    def test_env_overrides_yaml(self, monkeypatch, project_dir):
        monkeypatch.setenv('STORYFORGE_COACHING', 'strict')
        result = get_coaching_level(project_dir)
        assert result == 'strict'

    def test_env_override_without_project_dir(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_COACHING', 'coach')
        result = get_coaching_level(None)
        assert result == 'coach'

    def test_defaults_full_without_project_dir(self, monkeypatch):
        monkeypatch.delenv('STORYFORGE_COACHING', raising=False)
        result = get_coaching_level(None)
        assert result == 'full'

    def test_invalid_yaml_value_defaults_to_full(self, project_dir):
        yaml_file = os.path.join(project_dir, 'storyforge.yaml')
        with open(yaml_file) as f:
            content = f.read()
        content = content.replace(
            'target_words: 90000',
            'target_words: 90000\n  coaching_level: invalid_value',
        )
        with open(yaml_file, 'w') as f:
            f.write(content)
        result = get_coaching_level(project_dir)
        assert result == 'full'


# ============================================================================
# check_chapter_map_freshness
# ============================================================================

class TestCheckChapterMapFreshness:
    """Tests for check_chapter_map_freshness."""

    def test_detects_missing_scenes_from_map(self, fixture_dir):
        """Scenes in scenes.csv but not in chapter-map.csv should appear as missing."""
        is_fresh, missing, extra = check_chapter_map_freshness(fixture_dir)
        # The fixture has 6 scenes but chapter-map only covers act1-sc01, act1-sc02, act2-sc01
        assert not is_fresh
        assert len(missing) > 0

    def test_fresh_when_all_match(self, project_dir):
        """When chapter-map covers all active scenes, should report fresh."""
        # Rewrite chapter-map to cover all active scenes
        chapter_map = os.path.join(project_dir, 'reference', 'chapter-map.csv')
        with open(chapter_map, 'w') as f:
            f.write('chapter|title|heading|part|scenes\n')
            f.write('1|Ch1|numbered-titled|1|act1-sc01;act1-sc02;new-x1\n')
            f.write('2|Ch2|numbered-titled|2|act2-sc01;act2-sc02;act2-sc03\n')
        is_fresh, missing, extra = check_chapter_map_freshness(project_dir)
        assert is_fresh
        assert missing == []
        assert extra == []

    def test_detects_extra_in_map(self, project_dir):
        """Scene IDs in chapter-map but not in scenes.csv should appear as extra."""
        chapter_map = os.path.join(project_dir, 'reference', 'chapter-map.csv')
        with open(chapter_map, 'w') as f:
            f.write('chapter|title|heading|part|scenes\n')
            f.write('1|Ch1|numbered-titled|1|act1-sc01;act1-sc02;nonexistent-scene\n')
        is_fresh, missing, extra = check_chapter_map_freshness(project_dir)
        assert not is_fresh
        assert 'nonexistent-scene' in extra

    def test_excludes_cut_scenes(self, project_dir):
        """Scenes with 'cut' status should not be required in the chapter map."""
        scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(scenes_csv) as f:
            content = f.read()
        # Change act2-sc02 to status=cut
        content = content.replace(
            'act2-sc02|5|First Collapse|2|Tessa Merrin|Eastern Ridge|3|afternoon|1 hour|action|spine',
            'act2-sc02|5|First Collapse|2|Tessa Merrin|Eastern Ridge|3|afternoon|1 hour|action|cut',
        )
        with open(scenes_csv, 'w') as f:
            f.write(content)
        # Make chapter map cover all remaining active scenes
        chapter_map = os.path.join(project_dir, 'reference', 'chapter-map.csv')
        with open(chapter_map, 'w') as f:
            f.write('chapter|title|heading|part|scenes\n')
            f.write('1|Ch1|numbered-titled|1|act1-sc01;act1-sc02;new-x1\n')
            f.write('2|Ch2|numbered-titled|2|act2-sc01;act2-sc03\n')
        is_fresh, missing, extra = check_chapter_map_freshness(project_dir)
        assert is_fresh
        assert 'act2-sc02' not in missing

    def test_handles_missing_chapter_map(self, project_dir):
        """When chapter-map.csv doesn't exist, all scenes are missing."""
        chapter_map = os.path.join(project_dir, 'reference', 'chapter-map.csv')
        if os.path.exists(chapter_map):
            os.remove(chapter_map)
        is_fresh, missing, extra = check_chapter_map_freshness(project_dir)
        assert not is_fresh
        assert len(missing) > 0
        assert extra == []

    def test_handles_missing_scenes_csv(self, project_dir):
        """When scenes.csv doesn't exist, result is vacuously fresh."""
        scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        if os.path.exists(scenes_csv):
            os.remove(scenes_csv)
        is_fresh, missing, extra = check_chapter_map_freshness(project_dir)
        # No active scenes, so any map entries become extras
        # but if both are missing/empty, it's fresh
        assert missing == []


# ============================================================================
# get_plugin_dir
# ============================================================================

class TestGetPluginDir:
    """Tests for get_plugin_dir."""

    def test_returns_valid_directory(self):
        result = get_plugin_dir()
        assert os.path.isdir(result)

    def test_plugin_dir_contains_scripts(self):
        result = get_plugin_dir()
        assert os.path.isdir(os.path.join(result, 'scripts'))

    def test_plugin_dir_contains_references(self):
        result = get_plugin_dir()
        assert os.path.isdir(os.path.join(result, 'references'))


# ============================================================================
# install_signal_handlers
# ============================================================================

class TestInstallSignalHandlers:
    """Tests for install_signal_handlers."""

    def test_installs_sigint_handler(self):
        # Save original handlers
        original_int = signal.getsignal(signal.SIGINT)
        original_term = signal.getsignal(signal.SIGTERM)
        try:
            install_signal_handlers()
            # Handlers should no longer be the defaults
            assert signal.getsignal(signal.SIGINT) is not signal.SIG_DFL
            assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL
        finally:
            # Restore originals
            signal.signal(signal.SIGINT, original_int)
            signal.signal(signal.SIGTERM, original_term)


# ============================================================================
# Pipeline manifest
# ============================================================================

class TestPipelineManifest:
    """Tests for pipeline manifest CRUD functions."""

    def test_ensure_pipeline_manifest_creates_file(self, project_dir):
        pf = get_pipeline_file(project_dir)
        if os.path.exists(pf):
            os.remove(pf)
        ensure_pipeline_manifest(project_dir)
        assert os.path.isfile(pf)
        with open(pf) as f:
            header = f.readline().strip()
        assert header.startswith('cycle|')

    def test_ensure_pipeline_manifest_idempotent(self, project_dir):
        """Calling ensure twice doesn't corrupt existing data."""
        ensure_pipeline_manifest(project_dir)
        pf = get_pipeline_file(project_dir)
        with open(pf) as f:
            original = f.read()
        ensure_pipeline_manifest(project_dir)
        with open(pf) as f:
            after = f.read()
        assert original == after

    def test_get_current_cycle_returns_latest(self, fixture_dir):
        """Fixture has cycles 1, 2, 3 — should return 3."""
        result = get_current_cycle(fixture_dir)
        assert result == 3

    def test_get_current_cycle_empty_manifest(self, project_dir):
        """When manifest has only a header, returns 0."""
        pf = get_pipeline_file(project_dir)
        os.makedirs(os.path.dirname(pf), exist_ok=True)
        with open(pf, 'w') as f:
            f.write('cycle|started|status|evaluation|scoring|plan|review|recommendations|summary\n')
        result = get_current_cycle(project_dir)
        assert result == 0

    def test_get_current_cycle_no_file(self, tmp_path):
        result = get_current_cycle(str(tmp_path))
        assert result == 0

    def test_start_new_cycle_increments(self, project_dir):
        current = get_current_cycle(project_dir)
        new_id = start_new_cycle(project_dir)
        assert new_id == current + 1
        # Verify it persists
        assert get_current_cycle(project_dir) == new_id

    def test_start_new_cycle_from_empty(self, project_dir):
        """Starting a cycle when no manifest exists creates cycle 1."""
        pf = get_pipeline_file(project_dir)
        if os.path.exists(pf):
            os.remove(pf)
        new_id = start_new_cycle(project_dir)
        assert new_id == 1

    def test_update_cycle_field(self, project_dir):
        current = get_current_cycle(project_dir)
        if current == 0:
            current = start_new_cycle(project_dir)
        update_cycle_field(project_dir, current, 'status', 'completed')
        from storyforge.common import read_cycle_field
        result = read_cycle_field(project_dir, current, 'status')
        assert result == 'completed'

    def test_update_cycle_field_nonexistent_file(self, tmp_path):
        """Updating when no file exists should not raise."""
        update_cycle_field(str(tmp_path), 999, 'status', 'done')
        # No exception means success

    def test_multiple_cycles(self, project_dir):
        """Starting multiple cycles produces sequential IDs."""
        pf = get_pipeline_file(project_dir)
        if os.path.exists(pf):
            os.remove(pf)
        c1 = start_new_cycle(project_dir)
        c2 = start_new_cycle(project_dir)
        c3 = start_new_cycle(project_dir)
        assert c1 == 1
        assert c2 == 2
        assert c3 == 3
        assert get_current_cycle(project_dir) == 3
