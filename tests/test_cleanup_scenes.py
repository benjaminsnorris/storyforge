"""Regression tests for storyforge cleanup --scenes."""

import os

from storyforge.cmd_cleanup import clean_scene_files


def _write_scene(scenes_dir, name, content):
    path = os.path.join(scenes_dir, f'{name}.md')
    with open(path, 'w') as f:
        f.write(content)
    return path


def _read_scene(scenes_dir, name):
    with open(os.path.join(scenes_dir, f'{name}.md')) as f:
        return f.read()


class TestCleanSceneFiles:
    """Tests for the clean_scene_files function."""

    def test_strips_h1_title(self, tmp_path):
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        _write_scene(str(scenes), 'test', '# The Big Scene\n\nShe walked in.\n')

        changed = clean_scene_files(str(tmp_path))
        assert changed == 1
        assert _read_scene(str(scenes), 'test') == 'She walked in.\n'

    def test_strips_h2_title(self, tmp_path):
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        _write_scene(str(scenes), 'test', '## The Big Scene\n\nShe walked in.\n')

        changed = clean_scene_files(str(tmp_path))
        assert changed == 1
        assert _read_scene(str(scenes), 'test') == 'She walked in.\n'

    def test_strips_continuity_tracker(self, tmp_path):
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        content = (
            'She walked in.\n\n'
            '---\n\n'
            '# Continuity Tracker Update\n\n'
            '## Character States\n'
            '- Alice: nervous\n'
        )
        _write_scene(str(scenes), 'test', content)

        changed = clean_scene_files(str(tmp_path))
        assert changed == 1
        assert _read_scene(str(scenes), 'test') == 'She walked in.\n'

    def test_strips_scene_markers(self, tmp_path):
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        content = (
            '=== SCENE: test ===\n'
            'She walked in.\n'
            '=== END SCENE: test ===\n'
        )
        _write_scene(str(scenes), 'test', content)

        changed = clean_scene_files(str(tmp_path))
        assert changed == 1
        assert _read_scene(str(scenes), 'test') == 'She walked in.\n'

    def test_strips_all_artifacts_combined(self, tmp_path):
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        content = (
            '=== SCENE: test ===\n'
            '# The Big Scene\n\n'
            'She walked in.\n\n'
            '---\n\n'
            '# Continuity Tracker Update\n\n'
            '## Character States\n'
            '- Alice: nervous\n'
            '=== END SCENE: test ===\n'
        )
        _write_scene(str(scenes), 'test', content)

        changed = clean_scene_files(str(tmp_path))
        assert changed == 1
        assert _read_scene(str(scenes), 'test') == 'She walked in.\n'

    def test_leaves_clean_files_untouched(self, tmp_path):
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        _write_scene(str(scenes), 'test', 'She walked in.\n')

        changed = clean_scene_files(str(tmp_path))
        assert changed == 0
        assert _read_scene(str(scenes), 'test') == 'She walked in.\n'

    def test_dry_run_does_not_modify(self, tmp_path):
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        original = '# Title\n\nShe walked in.\n'
        _write_scene(str(scenes), 'test', original)

        changed = clean_scene_files(str(tmp_path), dry_run=True)
        assert changed == 1
        # File should be unchanged
        assert _read_scene(str(scenes), 'test') == original

    def test_multiple_files(self, tmp_path):
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        _write_scene(str(scenes), 'clean', 'Fine prose.\n')
        _write_scene(str(scenes), 'dirty', '# Title\n\nDirty prose.\n')
        _write_scene(str(scenes), 'marked', '=== SCENE: marked ===\nMore prose.\n=== END SCENE: marked ===\n')

        changed = clean_scene_files(str(tmp_path))
        assert changed == 2
        assert _read_scene(str(scenes), 'clean') == 'Fine prose.\n'
        assert _read_scene(str(scenes), 'dirty') == 'Dirty prose.\n'
        assert _read_scene(str(scenes), 'marked') == 'More prose.\n'

    def test_no_scenes_dir(self, tmp_path):
        changed = clean_scene_files(str(tmp_path))
        assert changed == 0

    def test_ignores_non_md_files(self, tmp_path):
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        # Write a .txt file with artifacts — should be ignored
        with open(scenes / 'notes.txt', 'w') as f:
            f.write('# Title\n\nNotes.\n')
        _write_scene(str(scenes), 'test', 'Clean prose.\n')

        changed = clean_scene_files(str(tmp_path))
        assert changed == 0
