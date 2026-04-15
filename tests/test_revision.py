"""Tests for storyforge.revision — scope resolution and prompt building."""

import os

import pytest

from storyforge.revision import resolve_scope, resolve_scene_file


# ============================================================================
# resolve_scene_file
# ============================================================================

class TestResolveSceneFile:
    """Basic tests for scene file lookup."""

    def test_exact_match(self, project_dir):
        scene_dir = os.path.join(project_dir, 'scenes')
        result = resolve_scene_file(scene_dir, 'act1-sc01')
        assert result is not None
        assert result.endswith('act1-sc01.md')

    def test_missing_file_returns_none(self, project_dir):
        scene_dir = os.path.join(project_dir, 'scenes')
        result = resolve_scene_file(scene_dir, 'nonexistent-scene')
        assert result is None


# ============================================================================
# resolve_scope — existing behavior
# ============================================================================

class TestResolveScopeBasic:
    """Tests for existing resolve_scope behavior."""

    def test_full_scope_resolves_existing_files(self, project_dir):
        """Full scope includes scenes that have files."""
        results = resolve_scope('full', project_dir)
        basenames = [os.path.basename(p) for p in results]
        assert 'act1-sc01.md' in basenames
        assert 'act1-sc02.md' in basenames

    def test_specific_scene_id(self, project_dir):
        """Single scene ID resolves to its file."""
        results = resolve_scope('act1-sc01', project_dir)
        assert len(results) == 1
        assert results[0].endswith('act1-sc01.md')

    def test_comma_separated_ids(self, project_dir):
        """Comma-separated scene IDs resolve correctly."""
        results = resolve_scope('act1-sc01,act1-sc02', project_dir)
        assert len(results) == 2

    def test_act_filter(self, project_dir):
        """act-N scope filters by part number."""
        results = resolve_scope('act-1', project_dir)
        basenames = [os.path.basename(p) for p in results]
        # act1 scenes: act1-sc01, act1-sc02, new-x1 all have part=1
        assert 'act1-sc01.md' in basenames
        assert 'act1-sc02.md' in basenames

    def test_unknown_scope_raises(self, project_dir):
        """Completely unknown scene ID with no CSV entry raises ValueError."""
        with pytest.raises(ValueError, match='No scene files matched'):
            resolve_scope('totally-unknown-scene', project_dir)


# ============================================================================
# resolve_scope — issue #183 regression tests
# ============================================================================

class TestResolveScopeMissingProse:
    """Regression tests for issue #183: scenes with metadata but no prose file.

    When a scene ID exists in scenes.csv but has no corresponding file in
    scenes/, resolve_scope should treat it as a NEW: scene to draft rather
    than skipping it or raising ValueError.
    """

    def test_scene_with_metadata_but_no_file_returns_new_path(self, project_dir):
        """A scene in scenes.csv with no prose file gets a NEW: path.

        act2-sc02 exists in the fixture's scenes.csv (seq 5) but has no
        file in scenes/. It should be returned as NEW:act2-sc02.md.
        """
        # Confirm the file does not exist
        scene_file = os.path.join(project_dir, 'scenes', 'act2-sc02.md')
        assert not os.path.exists(scene_file), 'Fixture should not have this file'

        results = resolve_scope('act2-sc02', project_dir)
        assert len(results) == 1
        assert 'NEW:act2-sc02.md' in os.path.basename(results[0])

    def test_scene_with_no_metadata_and_no_file_still_warns(self, project_dir, capsys):
        """A completely unknown scene ID still produces a warning and is skipped.

        'ghost-scene' is not in scenes.csv and has no file. It should warn
        and not appear in results. Since it's the only target, ValueError
        should be raised.
        """
        with pytest.raises(ValueError, match='No scene files matched'):
            resolve_scope('ghost-scene', project_dir)

        captured = capsys.readouterr()
        assert 'WARNING' in captured.err
        assert 'ghost-scene' in captured.err

    def test_mixed_scope_existing_and_missing(self, project_dir):
        """A scope with both existing and missing-prose scenes returns both.

        act1-sc01 has a file; act2-sc02 has metadata but no file.
        Both should appear in results — one as a real path, the other as NEW:.
        """
        results = resolve_scope('act1-sc01,act2-sc02', project_dir)
        assert len(results) == 2

        basenames = [os.path.basename(p) for p in results]
        # Existing scene is a normal path
        assert 'act1-sc01.md' in basenames
        # Missing-prose scene gets NEW: prefix
        assert 'NEW:act2-sc02.md' in basenames

    def test_full_scope_includes_new_paths_for_missing_files(self, project_dir):
        """Full scope includes NEW: paths for scenes in CSV that lack prose files.

        The fixture has 6 active scenes in scenes.csv but only 4 scene files.
        act2-sc02 and act2-sc03 should appear with NEW: prefix.
        """
        results = resolve_scope('full', project_dir)
        basenames = [os.path.basename(p) for p in results]

        # Scenes with files are normal paths
        assert 'act1-sc01.md' in basenames
        assert 'act1-sc02.md' in basenames
        assert 'new-x1.md' in basenames
        assert 'act2-sc01.md' in basenames

        # Scenes without files get NEW: prefix
        assert 'NEW:act2-sc02.md' in basenames
        assert 'NEW:act2-sc03.md' in basenames

        # Total count matches all active scenes in CSV
        assert len(results) == 6

    def test_info_message_for_metadata_only_scene(self, project_dir, capsys):
        """Resolving a metadata-only scene prints an INFO message, not WARNING."""
        resolve_scope('act2-sc02', project_dir)
        captured = capsys.readouterr()
        assert 'INFO' in captured.err
        assert 'act2-sc02' in captured.err
        assert 'draft from scratch' in captured.err

    def test_act_scope_includes_new_paths_for_missing_files(self, project_dir):
        """Act-scoped resolution also produces NEW: paths for missing files.

        act-2 scenes: act2-sc01 (has file), act2-sc02 (no file), act2-sc03 (no file).
        """
        results = resolve_scope('act-2', project_dir)
        basenames = [os.path.basename(p) for p in results]

        assert 'act2-sc01.md' in basenames
        assert 'NEW:act2-sc02.md' in basenames
        assert 'NEW:act2-sc03.md' in basenames
        assert len(results) == 3
