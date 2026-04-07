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
    generate_epub_metadata,
    manuscript_word_count,
    _unquote,
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


class TestUnquote:
    def test_double_quoted(self):
        assert _unquote('"hello"') == 'hello'

    def test_single_quoted(self):
        assert _unquote("'hello'") == 'hello'

    def test_unquoted(self):
        assert _unquote('hello') == 'hello'

    def test_empty(self):
        assert _unquote('') == ''

    def test_mismatched_quotes(self):
        assert _unquote('"hello\'') == '"hello\''

    def test_single_char(self):
        assert _unquote('"') == '"'

    def test_nested_double_quotes(self):
        # Outer layer of quotes is stripped, leaving inner quotes
        assert _unquote('""Unicorn Tail""') == '"Unicorn Tail"'


class TestGenerateEpubMetadata:
    def test_no_nested_quotes(self, project_dir):
        """Values with existing quotes should not produce nested quotes."""
        # Write a storyforge.yaml with a quoted title
        yaml_path = os.path.join(project_dir, 'storyforge.yaml')
        with open(yaml_path, 'r') as f:
            content = f.read()
        content = content.replace(
            "The Cartographer's Silence",
            '"Unicorn Tail"',
        )
        with open(yaml_path, 'w') as f:
            f.write(content)
        result = generate_epub_metadata(project_dir)
        # Should NOT contain nested quotes like ''Unicorn Tail''
        assert "'\"Unicorn Tail\"'" not in result
        assert "title: 'Unicorn Tail'" in result

    def test_basic_structure(self, project_dir):
        result = generate_epub_metadata(project_dir)
        assert result.startswith('---')
        assert result.endswith('---')
        assert 'title:' in result
        assert 'author:' in result
        assert 'rights:' in result

    def test_single_quotes_used(self, project_dir):
        result = generate_epub_metadata(project_dir)
        lines = result.split('\n')
        title_line = [l for l in lines if l.startswith('title:')][0]
        # Values should be wrapped in single quotes, not double
        assert title_line.startswith("title: '")
        assert title_line.endswith("'")


class TestWordCount:
    def test_counts_correctly(self, tmp_path):
        test_file = str(tmp_path / 'test.md')
        with open(test_file, 'w') as f:
            f.write('One two three four five six seven eight nine ten.')
        assert manuscript_word_count(test_file) == 10
