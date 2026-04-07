"""Tests for assembly library functions (migrated from test-assembly.sh).

Many bash tests tested shell functions (assemble_chapter, generate_title_page, etc.)
that don't have direct Python equivalents. We test the Python assembly module instead.
"""

import os

from storyforge.assembly import (
    count_chapters,
    read_chapter_field,
    get_chapter_scenes,
    extract_scene_prose,
    word_count,
)


class TestCountChapters:
    def test_finds_chapters(self, fixture_dir):
        assert count_chapters(fixture_dir) == 2

    def test_missing_project(self):
        assert count_chapters('/nonexistent/path') == 0


class TestReadChapterField:
    def test_title_chapter1(self, fixture_dir):
        assert read_chapter_field(1, fixture_dir, 'title') == 'The Finest Cartographer'

    def test_title_chapter2(self, fixture_dir):
        assert read_chapter_field(2, fixture_dir, 'title') == 'Into the Blank'


class TestGetChapterScenes:
    def test_chapter1_scenes(self, fixture_dir):
        scenes = get_chapter_scenes(1, fixture_dir)
        assert 'act1-sc01' in scenes
        assert 'act1-sc02' in scenes
        assert 'act2-sc01' not in str(scenes)

    def test_chapter2_scenes(self, fixture_dir):
        scenes = get_chapter_scenes(2, fixture_dir)
        assert 'act2-sc01' in scenes
        assert 'act1' not in str(scenes)


class TestExtractSceneProse:
    def test_extracts_prose(self, project_dir):
        result = extract_scene_prose(os.path.join(project_dir, 'scenes', 'act1-sc01.md'))
        assert 'Dorren Hayle pressed' in result
        assert '---' not in result

    def test_no_leading_blanks(self, project_dir):
        result = extract_scene_prose(os.path.join(project_dir, 'scenes', 'act1-sc01.md'))
        first_line = result.strip().split('\n')[0]
        assert first_line != ''


class TestWordCount:
    def test_counts_correctly(self, tmp_path):
        test_file = str(tmp_path / 'test.md')
        with open(test_file, 'w') as f:
            f.write('One two three four five six seven eight nine ten.')
        assert word_count(test_file) == 10
