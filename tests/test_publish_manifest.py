"""Tests for publish manifest generation."""
import json
import os

import pytest


def _make_project(tmp_path, scenes, chapters):
    """Helper to create a minimal project for manifest tests."""
    ref = tmp_path / 'reference'
    ref.mkdir(exist_ok=True)
    scenes_dir = tmp_path / 'scenes'
    scenes_dir.mkdir(exist_ok=True)
    (tmp_path / 'storyforge.yaml').write_text('project:\n  title: Test Book\n  author: Test Author\n')

    # scenes.csv
    lines = ['id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words']
    for i, sid in enumerate(scenes, 1):
        lines.append(f'{sid}|{i}|Title {i}|1|pov|loc|1|morning|short|action|drafted|100|200')
    (ref / 'scenes.csv').write_text('\n'.join(lines) + '\n')

    # chapter-map.csv
    ch_lines = ['chapter|title|heading|part|scenes']
    for i, (title, scene_ids) in enumerate(chapters, 1):
        ch_lines.append(f'{i}|{title}|numbered|1|{";".join(scene_ids)}')
    (ref / 'chapter-map.csv').write_text('\n'.join(ch_lines) + '\n')

    # scene markdown files
    for sid in scenes:
        (scenes_dir / f'{sid}.md').write_text(f'The prose for scene {sid}. Some words here.\n')

    return str(tmp_path)


class TestGeneratePublishManifest:
    def test_generates_valid_json(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1', 's2', 's3'],
                             [('Chapter One', ['s1', 's2']), ('Chapter Two', ['s3'])])
        path = generate_publish_manifest(proj)
        assert os.path.isfile(path)
        with open(path) as f:
            manifest = json.load(f)
        assert manifest['title'] == 'Test Book'
        assert manifest['author'] == 'Test Author'
        assert manifest['slug'] == 'test-book'
        assert 'metadata' in manifest
        assert len(manifest['chapters']) == 2

    def test_chapters_match_chapter_map(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1', 's2', 's3'],
                             [('Ch One', ['s1', 's2']), ('Ch Two', ['s3'])])
        path = generate_publish_manifest(proj)
        with open(path) as f:
            manifest = json.load(f)
        ch1 = manifest['chapters'][0]
        assert ch1['number'] == 1
        assert ch1['title'] == 'Ch One'
        assert len(ch1['scenes']) == 2
        assert ch1['scenes'][0]['slug'] == 's1'
        assert ch1['scenes'][1]['slug'] == 's2'

    def test_scenes_have_html_content(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        path = generate_publish_manifest(proj)
        with open(path) as f:
            manifest = json.load(f)
        scene = manifest['chapters'][0]['scenes'][0]
        assert '<p>' in scene['content_html']
        assert 's1' in scene['content_html']

    def test_word_counts_computed(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        # Overwrite with known word count
        with open(os.path.join(proj, 'scenes', 's1.md'), 'w') as f:
            f.write('One two three four five.\n')
        path = generate_publish_manifest(proj)
        with open(path) as f:
            manifest = json.load(f)
        assert manifest['chapters'][0]['scenes'][0]['word_count'] == 5

    def test_sort_order_sequential(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1', 's2', 's3'],
                             [('Ch', ['s1', 's2', 's3'])])
        path = generate_publish_manifest(proj)
        with open(path) as f:
            manifest = json.load(f)
        scenes = manifest['chapters'][0]['scenes']
        assert scenes[0]['sort_order'] == 1
        assert scenes[1]['sort_order'] == 2
        assert scenes[2]['sort_order'] == 3

    def test_manifest_path(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        path = generate_publish_manifest(proj)
        assert path == os.path.join(proj, 'working', 'publish-manifest.json')

    def test_stale_chapter_map_raises(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        import pytest
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
            'scene-a|1|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            'scene-b|2|B|1|k|here|1|morning|short|action|drafted|1000|1500\n'
        )
        (ref / 'chapter-map.csv').write_text(
            'chapter|title|heading|part|scenes\n'
            '1|Ch|numbered|1|scene-a\n'
        )
        (tmp_path / 'storyforge.yaml').write_text('project:\n  title: Test\n  author: Me\n')
        with pytest.raises(ValueError, match='stale'):
            generate_publish_manifest(str(tmp_path))

    def test_strips_yaml_frontmatter(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        with open(os.path.join(proj, 'scenes', 's1.md'), 'w') as f:
            f.write('---\ntitle: Some Title\n---\nActual prose content here.\n')
        path = generate_publish_manifest(proj)
        with open(path) as f:
            manifest = json.load(f)
        html = manifest['chapters'][0]['scenes'][0]['content_html']
        assert 'title: Some Title' not in html
        assert 'Actual prose' in html

    def test_includes_dashboard_data(self, tmp_path):
        """Manifest should always include structured dashboard_data."""
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        # Need scene-intent.csv for load_dashboard_data
        ref = os.path.join(proj, 'reference')
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s1|test fn|action|calm to tense|truth|+/-|revelation|A|A|\n')
        path = generate_publish_manifest(proj)
        with open(path) as f:
            manifest = json.load(f)
        assert 'dashboard_data' in manifest
        assert 'scenes' in manifest['dashboard_data']
        assert 'project' in manifest['dashboard_data']


class TestOptimizeCoverImage:
    def test_small_jpeg_returns_original(self, tmp_path):
        """Small JPEG files should pass through without optimization."""
        from storyforge.assembly import _optimize_cover_image
        # Create a small fake JPEG (under threshold)
        cover = tmp_path / 'cover.jpg'
        cover.write_bytes(b'\xff\xd8\xff' + b'\x00' * 100)
        result = _optimize_cover_image(str(cover), str(tmp_path))
        assert result == str(cover)

    def test_large_png_triggers_optimization(self, tmp_path, monkeypatch):
        """Large PNG files should be converted to optimized JPEG."""
        import platform
        import subprocess
        import storyforge.assembly as asm
        if platform.system() != 'Darwin':
            pytest.skip('sips only available on macOS')
        # Create a real PNG using sips
        cover = tmp_path / 'cover.png'
        try:
            subprocess.run(
                ['sips', '-s', 'format', 'png', '-z', '2000', '2000',
                 '/System/Library/Desktop Pictures/Solid Colors/Black.png',
                 '--out', str(cover)],
                capture_output=True, check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip('Could not create test PNG with sips')
        # Lower the threshold so the test image triggers optimization
        monkeypatch.setattr(asm, '_COVER_MAX_BYTES', 1000)
        result = asm._optimize_cover_image(str(cover), str(tmp_path))
        assert result != str(cover)
        assert result.endswith('.jpg')
        assert os.path.getsize(result) < cover.stat().st_size
