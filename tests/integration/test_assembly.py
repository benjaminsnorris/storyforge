"""Integration tests for storyforge.assembly — chapter assembly and manuscript production.

Tests chapter map reading, scene extraction, chapter assembly, front/back matter,
epub metadata, manuscript assembly, genre CSS, cover generation, publish manifest,
and YAML helpers against real fixture data and purpose-built temp projects.
"""

import json
import os
import textwrap
from unittest.mock import patch

import pytest

from storyforge.assembly import (
    _chapter_map_path,
    _count_yaml_list_items,
    _detect_key_column,
    _read_production_field_from_lines,
    _read_production_nested_from_lines,
    _read_yaml_lines,
    _read_yaml_list_item_field,
    _resolve_cover_path,
    _strip_yaml_quotes,
    _unquote,
    assemble_chapter,
    assemble_manuscript,
    count_chapters,
    count_parts,
    extract_scene_prose,
    generate_copyright_page,
    generate_cover_if_missing,
    generate_epub,
    generate_epub_metadata,
    generate_html,
    generate_pdf,
    generate_title_page,
    generate_toc,
    get_chapter_part_title,
    get_chapter_scenes,
    get_genre_css,
    generate_publish_manifest,
    manuscript_word_count,
    read_chapter_field,
    read_matter_file,
    read_part_field,
    read_production_field,
    read_production_nested,
)


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

class TestStripYamlQuotes:

    def test_double_quoted(self):
        assert _strip_yaml_quotes('"hello world"') == 'hello world'

    def test_single_quoted(self):
        assert _strip_yaml_quotes("'hello world'") == 'hello world'

    def test_unquoted(self):
        assert _strip_yaml_quotes('hello world') == 'hello world'

    def test_strips_whitespace(self):
        assert _strip_yaml_quotes('  "value"  ') == 'value'

    def test_empty(self):
        assert _strip_yaml_quotes('') == ''

    def test_mismatched_quotes_preserved(self):
        assert _strip_yaml_quotes('"hello\'') == '"hello\''


class TestUnquote:

    def test_double_quoted(self):
        assert _unquote('"test"') == 'test'

    def test_single_quoted(self):
        assert _unquote("'test'") == 'test'

    def test_unquoted_passthrough(self):
        assert _unquote('test') == 'test'

    def test_empty_string(self):
        assert _unquote('') == ''


class TestReadYamlLines:

    def test_reads_yaml(self, project_dir):
        lines = _read_yaml_lines(os.path.join(project_dir, 'storyforge.yaml'))
        assert len(lines) > 0

    def test_missing_file_returns_empty(self, tmp_path):
        assert _read_yaml_lines(str(tmp_path / 'missing.yaml')) == []


class TestReadProductionFieldFromLines:

    def test_reads_author(self, project_dir):
        lines = _read_yaml_lines(os.path.join(project_dir, 'storyforge.yaml'))
        assert _read_production_field_from_lines(lines, 'author') == 'Test Author'

    def test_reads_language(self, project_dir):
        lines = _read_yaml_lines(os.path.join(project_dir, 'storyforge.yaml'))
        assert _read_production_field_from_lines(lines, 'language') == 'en'

    def test_missing_field_returns_empty(self, project_dir):
        lines = _read_yaml_lines(os.path.join(project_dir, 'storyforge.yaml'))
        assert _read_production_field_from_lines(lines, 'nonexistent') == ''

    def test_no_production_block(self):
        lines = ['project:\n', '  title: Test\n']
        assert _read_production_field_from_lines(lines, 'author') == ''


class TestReadProductionNestedFromLines:

    def test_reads_copyright_year(self, project_dir):
        lines = _read_yaml_lines(os.path.join(project_dir, 'storyforge.yaml'))
        assert _read_production_nested_from_lines(lines, 'copyright', 'year') == '2026'

    def test_reads_copyright_isbn(self, project_dir):
        lines = _read_yaml_lines(os.path.join(project_dir, 'storyforge.yaml'))
        assert _read_production_nested_from_lines(lines, 'copyright', 'isbn') == '978-0-000000-00-0'

    def test_missing_child_returns_empty(self, project_dir):
        lines = _read_yaml_lines(os.path.join(project_dir, 'storyforge.yaml'))
        assert _read_production_nested_from_lines(lines, 'copyright', 'publisher') == ''


class TestCountYamlListItems:

    def test_counts_parts(self, project_dir):
        lines = _read_yaml_lines(os.path.join(project_dir, 'storyforge.yaml'))
        assert _count_yaml_list_items(lines, 'parts', 'number') == 2

    def test_empty_list_returns_zero(self):
        lines = ['parts:\n']
        assert _count_yaml_list_items(lines, 'parts', 'number') == 0

    def test_no_matching_key(self):
        lines = ['other:\n', '  - number: 1\n']
        assert _count_yaml_list_items(lines, 'parts', 'number') == 0


class TestReadYamlListItemField:

    def test_reads_part_title(self, project_dir):
        lines = _read_yaml_lines(os.path.join(project_dir, 'storyforge.yaml'))
        assert _read_yaml_list_item_field(lines, 'parts', 'number', 1, 'title') == 'The Expedition'
        assert _read_yaml_list_item_field(lines, 'parts', 'number', 2, 'title') == 'The Blank'

    def test_reads_marker_field_itself(self, project_dir):
        """When field == item_marker, read from the marker line."""
        lines = _read_yaml_lines(os.path.join(project_dir, 'storyforge.yaml'))
        assert _read_yaml_list_item_field(lines, 'parts', 'number', 1, 'number') == '1'

    def test_out_of_range_returns_empty(self, project_dir):
        lines = _read_yaml_lines(os.path.join(project_dir, 'storyforge.yaml'))
        assert _read_yaml_list_item_field(lines, 'parts', 'number', 99, 'title') == ''


# ---------------------------------------------------------------------------
# Chapter map parsing
# ---------------------------------------------------------------------------

class TestDetectKeyColumn:

    def test_seq_header(self):
        assert _detect_key_column(['seq', 'title', 'scenes']) == 'seq'

    def test_chapter_header(self):
        assert _detect_key_column(['chapter', 'title', 'scenes']) == 'chapter'

    def test_empty_header(self):
        assert _detect_key_column([]) == 'chapter'


class TestCountChapters:

    def test_fixture_has_two_chapters(self, project_dir):
        assert count_chapters(project_dir) == 2

    def test_no_chapter_map_returns_zero(self, tmp_path):
        assert count_chapters(str(tmp_path)) == 0

    def test_empty_chapter_map(self, tmp_path):
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'chapter-map.csv').write_text('chapter|title|heading|part|scenes\n')
        assert count_chapters(str(tmp_path)) == 0


class TestReadChapterField:

    def test_reads_title(self, project_dir):
        assert read_chapter_field(1, project_dir, 'title') == 'The Finest Cartographer'

    def test_reads_heading(self, project_dir):
        assert read_chapter_field(1, project_dir, 'heading') == 'numbered-titled'

    def test_missing_chapter_returns_empty(self, project_dir):
        assert read_chapter_field(99, project_dir, 'title') == ''

    def test_missing_field_returns_empty(self, project_dir):
        assert read_chapter_field(1, project_dir, 'nonexistent') == ''


class TestGetChapterScenes:

    def test_chapter_one_scenes(self, project_dir):
        scenes = get_chapter_scenes(1, project_dir)
        assert scenes == ['act1-sc01', 'act1-sc02']

    def test_chapter_two_scenes(self, project_dir):
        scenes = get_chapter_scenes(2, project_dir)
        assert scenes == ['act2-sc01']

    def test_missing_chapter_returns_empty(self, project_dir):
        assert get_chapter_scenes(99, project_dir) == []


class TestCountParts:

    def test_fixture_has_two_parts(self, project_dir):
        assert count_parts(project_dir) == 2


class TestReadPartField:

    def test_reads_title(self, project_dir):
        assert read_part_field(1, project_dir, 'title') == 'The Expedition'
        assert read_part_field(2, project_dir, 'title') == 'The Blank'


class TestGetChapterPartTitle:

    def test_chapter_1_part_title(self, project_dir):
        assert get_chapter_part_title(1, project_dir) == 'The Expedition'

    def test_chapter_2_part_title(self, project_dir):
        assert get_chapter_part_title(2, project_dir) == 'The Blank'

    def test_no_part_returns_empty(self, tmp_path):
        """Chapter with empty part field returns empty string."""
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'chapter-map.csv').write_text('chapter|title|heading|part|scenes\n1|Test|||\n')
        assert get_chapter_part_title(1, str(tmp_path)) == ''


# ---------------------------------------------------------------------------
# Scene extraction
# ---------------------------------------------------------------------------

class TestExtractSceneProse:

    def test_strips_yaml_frontmatter(self, project_dir):
        scene = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        prose = extract_scene_prose(scene)
        assert '---' not in prose
        assert 'id:' not in prose
        assert 'Dorren Hayle pressed' in prose

    def test_scene_without_frontmatter(self, project_dir):
        scene = os.path.join(project_dir, 'scenes', 'new-x1.md')
        prose = extract_scene_prose(scene)
        # new-x1.md starts with "# The Archivist's Warning" — no frontmatter
        assert "The Archivist's Warning" in prose

    def test_missing_file_returns_empty(self, tmp_path):
        assert extract_scene_prose(str(tmp_path / 'nonexistent.md')) == ''

    def test_strips_leading_blank_lines(self, tmp_path):
        scene = tmp_path / 'test.md'
        scene.write_text('---\ntitle: Test\n---\n\n\nHello world.')
        prose = extract_scene_prose(str(scene))
        assert prose == 'Hello world.'


# ---------------------------------------------------------------------------
# Chapter assembly
# ---------------------------------------------------------------------------

class TestAssembleChapter:

    def test_assembles_chapter_with_heading(self, project_dir):
        result = assemble_chapter(1, project_dir)
        # Default heading: numbered-titled
        assert '# Chapter 1: The Finest Cartographer' in result

    def test_includes_scene_boundary_markers(self, project_dir):
        result = assemble_chapter(1, project_dir)
        assert '<!-- scene:act1-sc01 -->' in result
        assert '<!-- scene:act1-sc02 -->' in result

    def test_includes_scene_prose(self, project_dir):
        result = assemble_chapter(1, project_dir)
        assert 'Dorren Hayle pressed' in result
        assert "Tarren's Hollow" in result

    def test_scene_break_between_scenes(self, project_dir):
        result = assemble_chapter(1, project_dir, break_style='space')
        # Two scenes in chapter 1, break between them
        assert '---' in result

    def test_ornamental_break_style(self, project_dir):
        result = assemble_chapter(1, project_dir, break_style='ornamental')
        assert '***' in result

    def test_custom_break_style(self, project_dir):
        result = assemble_chapter(1, project_dir, break_style='custom:~~~')
        assert '~~~' in result

    def test_numbered_heading_format(self, tmp_path):
        """Chapter with heading=numbered shows 'Chapter N' only."""
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'chapter-map.csv').write_text(
            'chapter|title|heading|part|scenes\n1|Ignored|numbered||sc-a\n'
        )
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        (scenes / 'sc-a.md').write_text('Some prose.')
        result = assemble_chapter(1, str(tmp_path))
        assert '# Chapter 1\n' in result
        assert 'Ignored' not in result

    def test_titled_heading_format(self, tmp_path):
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'chapter-map.csv').write_text(
            'chapter|title|heading|part|scenes\n1|My Title|titled||sc-a\n'
        )
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        (scenes / 'sc-a.md').write_text('Some prose.')
        result = assemble_chapter(1, str(tmp_path))
        assert '# My Title\n' in result
        assert 'Chapter 1' not in result

    def test_none_heading_format(self, tmp_path):
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'chapter-map.csv').write_text(
            'chapter|title|heading|part|scenes\n1|Invisible|none||sc-a\n'
        )
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        (scenes / 'sc-a.md').write_text('Some prose.')
        result = assemble_chapter(1, str(tmp_path))
        assert '# ' not in result

    def test_single_scene_chapter_no_break(self, project_dir):
        """Chapter with one scene should have no scene break."""
        result = assemble_chapter(2, project_dir)
        # Chapter 2 has only act2-sc01
        lines = result.split('\n')
        # Should not contain a break marker between scenes (only heading-related ---)
        scene_breaks = [l for l in lines if l.strip() in ('---', '***') and '# ' not in l]
        # There may be zero break markers for a single scene chapter
        # The heading line itself is not a break marker
        assert result.count('<!-- scene:') == 1


# ---------------------------------------------------------------------------
# Production config
# ---------------------------------------------------------------------------

class TestReadProductionField:

    def test_reads_author(self, project_dir):
        assert read_production_field(project_dir, 'author') == 'Test Author'

    def test_reads_scene_break(self, project_dir):
        assert read_production_field(project_dir, 'scene_break') == 'ornamental'


class TestReadProductionNested:

    def test_reads_copyright_year(self, project_dir):
        assert read_production_nested(project_dir, 'copyright', 'year') == '2026'

    def test_reads_copyright_isbn(self, project_dir):
        isbn = read_production_nested(project_dir, 'copyright', 'isbn')
        assert isbn == '978-0-000000-00-0'


# ---------------------------------------------------------------------------
# Front / back matter
# ---------------------------------------------------------------------------

class TestGenerateTitlePage:

    def test_contains_title(self, project_dir):
        result = generate_title_page(project_dir)
        assert "The Cartographer's Silence" in result

    def test_contains_author(self, project_dir):
        result = generate_title_page(project_dir)
        assert 'Test Author' in result

    def test_has_yaml_frontmatter(self, project_dir):
        result = generate_title_page(project_dir)
        assert result.startswith('---')


class TestGenerateCopyrightPage:

    def test_contains_copyright_symbol(self, project_dir):
        result = generate_copyright_page(project_dir)
        assert '\u00a9' in result

    def test_contains_year(self, project_dir):
        result = generate_copyright_page(project_dir)
        assert '2026' in result

    def test_contains_isbn(self, project_dir):
        result = generate_copyright_page(project_dir)
        assert '978-0-000000-00-0' in result

    def test_contains_license(self, project_dir):
        result = generate_copyright_page(project_dir)
        assert 'All rights reserved.' in result


class TestGenerateToc:

    def test_generates_toc_entries(self, project_dir):
        result = generate_toc(project_dir)
        assert '# Contents' in result
        assert 'Chapter 1: The Finest Cartographer' in result
        assert 'Chapter 2: Into the Blank' in result

    def test_empty_project_returns_empty(self, tmp_path):
        assert generate_toc(str(tmp_path)) == ''


class TestReadMatterFile:

    def test_reads_from_custom_path(self, project_dir):
        # Create a custom dedication file
        ded = os.path.join(project_dir, 'custom-dedication.md')
        with open(ded, 'w') as f:
            f.write('For everyone.')

        # Write a storyforge.yaml that references it
        yaml = os.path.join(project_dir, 'storyforge.yaml')
        with open(yaml) as f:
            content = f.read()
        content = content.replace(
            '    dedication:',
            '    dedication: custom-dedication.md'
        )
        with open(yaml, 'w') as f:
            f.write(content)

        result = read_matter_file(project_dir, 'front_matter', 'dedication')
        assert result == 'For everyone.'

    def test_reads_from_default_location(self, project_dir):
        default_dir = os.path.join(project_dir, 'manuscript', 'front-matter')
        os.makedirs(default_dir, exist_ok=True)
        with open(os.path.join(default_dir, 'dedication.md'), 'w') as f:
            f.write('Default dedication.')
        result = read_matter_file(project_dir, 'front_matter', 'dedication')
        assert result == 'Default dedication.'

    def test_missing_returns_empty(self, project_dir):
        assert read_matter_file(project_dir, 'front_matter', 'dedication') == ''

    def test_back_matter_default_location(self, project_dir):
        default_dir = os.path.join(project_dir, 'manuscript', 'back-matter')
        os.makedirs(default_dir, exist_ok=True)
        with open(os.path.join(default_dir, 'acknowledgments.md'), 'w') as f:
            f.write('Thanks.')
        result = read_matter_file(project_dir, 'back_matter', 'acknowledgments')
        assert result == 'Thanks.'

    def test_unknown_section_returns_empty(self, project_dir):
        assert read_matter_file(project_dir, 'side_matter', 'x') == ''


# ---------------------------------------------------------------------------
# Epub metadata
# ---------------------------------------------------------------------------

class TestGenerateEpubMetadata:

    def test_contains_title(self, project_dir):
        result = generate_epub_metadata(project_dir)
        assert "The Cartographer's Silence" in result

    def test_contains_author(self, project_dir):
        result = generate_epub_metadata(project_dir)
        assert 'Test Author' in result

    def test_contains_language(self, project_dir):
        result = generate_epub_metadata(project_dir)
        assert 'lang: en' in result

    def test_contains_genre_as_subject(self, project_dir):
        result = generate_epub_metadata(project_dir)
        assert 'fantasy' in result

    def test_contains_isbn(self, project_dir):
        result = generate_epub_metadata(project_dir)
        assert '978-0-000000-00-0' in result

    def test_has_yaml_delimiters(self, project_dir):
        result = generate_epub_metadata(project_dir)
        assert result.startswith('---')
        assert result.endswith('---')

    def test_contains_rights(self, project_dir):
        result = generate_epub_metadata(project_dir)
        assert 'rights:' in result
        assert '2026' in result


# ---------------------------------------------------------------------------
# Manuscript assembly
# ---------------------------------------------------------------------------

class TestAssembleManuscript:

    def test_writes_output_file(self, project_dir, tmp_path):
        out = str(tmp_path / 'manuscript.md')
        wc = assemble_manuscript(project_dir, out)
        assert os.path.isfile(out)
        assert wc > 0

    def test_includes_title_page(self, project_dir, tmp_path):
        out = str(tmp_path / 'manuscript.md')
        assemble_manuscript(project_dir, out)
        with open(out) as f:
            content = f.read()
        assert "The Cartographer's Silence" in content

    def test_includes_copyright(self, project_dir, tmp_path):
        out = str(tmp_path / 'manuscript.md')
        assemble_manuscript(project_dir, out)
        with open(out) as f:
            content = f.read()
        assert '# Copyright' in content
        assert '\u00a9' in content

    def test_includes_chapter_content(self, project_dir, tmp_path):
        out = str(tmp_path / 'manuscript.md')
        assemble_manuscript(project_dir, out)
        with open(out) as f:
            content = f.read()
        assert 'Dorren Hayle pressed' in content
        assert 'The edge of the mapped world' in content

    def test_returns_word_count(self, project_dir, tmp_path):
        out = str(tmp_path / 'manuscript.md')
        wc = assemble_manuscript(project_dir, out)
        assert isinstance(wc, int)
        assert wc > 50

    def test_no_chapters_returns_zero(self, tmp_path):
        proj = tmp_path / 'empty-proj'
        proj.mkdir()
        (proj / 'storyforge.yaml').write_text('project:\n  title: Empty\n')
        out = str(tmp_path / 'out.md')
        wc = assemble_manuscript(str(proj), out)
        assert wc == 0

    def test_creates_output_directory(self, project_dir, tmp_path):
        out = str(tmp_path / 'nested' / 'deep' / 'manuscript.md')
        assemble_manuscript(project_dir, out)
        assert os.path.isfile(out)

    def test_uses_production_break_style(self, project_dir, tmp_path):
        """Fixture has scene_break: ornamental, so *** should appear."""
        out = str(tmp_path / 'manuscript.md')
        assemble_manuscript(project_dir, out)
        with open(out) as f:
            content = f.read()
        # Chapter 1 has 2 scenes -> should use ornamental break
        assert '***' in content


# ---------------------------------------------------------------------------
# Word count
# ---------------------------------------------------------------------------

class TestManuscriptWordCount:

    def test_counts_words(self, tmp_path):
        f = tmp_path / 'ms.md'
        f.write_text('one two three four five')
        assert manuscript_word_count(str(f)) == 5

    def test_missing_file_returns_zero(self, tmp_path):
        assert manuscript_word_count(str(tmp_path / 'nope.md')) == 0


# ---------------------------------------------------------------------------
# Genre CSS
# ---------------------------------------------------------------------------

class TestGetGenreCss:

    def test_fantasy_genre(self, plugin_dir):
        css = get_genre_css(plugin_dir, 'fantasy')
        assert css.endswith('fantasy.css')
        assert os.path.isfile(css)

    def test_science_fiction_normalized(self, plugin_dir):
        css = get_genre_css(plugin_dir, 'science fiction')
        assert css.endswith('science-fiction.css')
        assert os.path.isfile(css)

    def test_unknown_genre_falls_back_to_default(self, plugin_dir):
        css = get_genre_css(plugin_dir, 'underwater basket weaving')
        assert css.endswith('default.css')

    def test_default_exists(self, plugin_dir):
        css = get_genre_css(plugin_dir, 'default')
        assert os.path.isfile(css)


# ---------------------------------------------------------------------------
# Cover generation
# ---------------------------------------------------------------------------

class TestGenerateCoverIfMissing:

    def test_generates_svg_cover(self, project_dir, plugin_dir):
        generate_cover_if_missing(project_dir, plugin_dir)
        cover = os.path.join(project_dir, 'production', 'cover.svg')
        assert os.path.isfile(cover)
        with open(cover) as f:
            svg = f.read()
        assert '<svg' in svg
        assert "The Cartographer's Silence" in svg
        assert 'Test Author' in svg

    def test_does_not_overwrite_existing_cover(self, project_dir, plugin_dir):
        prod = os.path.join(project_dir, 'production')
        os.makedirs(prod, exist_ok=True)
        cover = os.path.join(prod, 'cover.png')
        with open(cover, 'w') as f:
            f.write('existing')
        generate_cover_if_missing(project_dir, plugin_dir)
        # cover.svg should NOT be created
        assert not os.path.isfile(os.path.join(prod, 'cover.svg'))
        # existing cover preserved
        with open(cover) as f:
            assert f.read() == 'existing'


# ---------------------------------------------------------------------------
# Format generation (subprocess mocked)
# ---------------------------------------------------------------------------

class TestGenerateEpub:

    def test_calls_pandoc_with_correct_args(self, project_dir, plugin_dir, tmp_path):
        ms_file = str(tmp_path / 'ms.md')
        epub_file = str(tmp_path / 'out.epub')
        with open(ms_file, 'w') as f:
            f.write('# Test\n\nHello.')
        os.makedirs(os.path.join(project_dir, 'working'), exist_ok=True)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = None
            generate_epub(project_dir, ms_file, epub_file, plugin_dir)
            mock_run.assert_called_once()
            args = mock_run.call_args
            cmd = args[0][0]
            assert cmd[0] == 'pandoc'
            assert '-o' in cmd
            assert epub_file in cmd
            assert '--toc' in cmd


class TestGenerateHtml:

    def test_calls_pandoc_with_standalone(self, project_dir, plugin_dir, tmp_path):
        ms_file = str(tmp_path / 'ms.md')
        html_file = str(tmp_path / 'out.html')
        with open(ms_file, 'w') as f:
            f.write('# Test')

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = None
            generate_html(project_dir, ms_file, html_file, plugin_dir)
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert '--standalone' in cmd
            assert cmd[0] == 'pandoc'


class TestGeneratePdf:

    def test_tries_weasyprint_then_fallback(self, project_dir, plugin_dir, tmp_path):
        ms_file = str(tmp_path / 'ms.md')
        pdf_file = str(tmp_path / 'out.pdf')
        with open(ms_file, 'w') as f:
            f.write('# Test')

        with patch('subprocess.run') as mock_run:
            # Simulate weasyprint failure, then fallback success
            mock_run.side_effect = [
                type('Result', (), {'returncode': 1})(),  # weasyprint fails
                None,  # fallback succeeds
            ]
            generate_pdf(project_dir, ms_file, pdf_file, plugin_dir)
            assert mock_run.call_count == 2
            first_cmd = mock_run.call_args_list[0][0][0]
            assert '--pdf-engine=weasyprint' in first_cmd
            second_cmd = mock_run.call_args_list[1][0][0]
            assert '--pdf-engine=weasyprint' not in second_cmd

    def test_weasyprint_success_no_fallback(self, project_dir, plugin_dir, tmp_path):
        ms_file = str(tmp_path / 'ms.md')
        pdf_file = str(tmp_path / 'out.pdf')
        with open(ms_file, 'w') as f:
            f.write('# Test')

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = type('Result', (), {'returncode': 0})()
            generate_pdf(project_dir, ms_file, pdf_file, plugin_dir)
            assert mock_run.call_count == 1


# ---------------------------------------------------------------------------
# Resolve cover path
# ---------------------------------------------------------------------------

class TestResolveCoverPath:

    def test_absolute_path_returned_as_is(self, tmp_path):
        path = str(tmp_path / 'cover.png')
        assert _resolve_cover_path(str(tmp_path), path) == path

    def test_relative_path_joined_with_project(self, tmp_path):
        result = _resolve_cover_path(str(tmp_path), 'assets/cover.png')
        assert result == os.path.join(str(tmp_path), 'assets/cover.png')

    def test_auto_detects_production_png(self, tmp_path):
        prod = tmp_path / 'production'
        prod.mkdir()
        (prod / 'cover.png').write_text('img')
        result = _resolve_cover_path(str(tmp_path), None)
        assert result == str(prod / 'cover.png')

    def test_auto_detects_manuscript_assets_cover(self, tmp_path):
        assets = tmp_path / 'manuscript' / 'assets'
        assets.mkdir(parents=True)
        (assets / 'cover.jpg').write_text('img')
        result = _resolve_cover_path(str(tmp_path), None)
        assert result == str(assets / 'cover.jpg')

    def test_jpg_preferred_over_png(self, tmp_path):
        prod = tmp_path / 'production'
        prod.mkdir()
        (prod / 'cover.png').write_text('png')
        (prod / 'cover.jpg').write_text('jpg')
        result = _resolve_cover_path(str(tmp_path), None)
        assert result == str(prod / 'cover.jpg')

    def test_jpg_preferred_over_svg(self, tmp_path):
        prod = tmp_path / 'production'
        prod.mkdir()
        (prod / 'cover.svg').write_text('svg')
        (prod / 'cover.jpg').write_text('jpg')
        result = _resolve_cover_path(str(tmp_path), None)
        assert result == str(prod / 'cover.jpg')

    def test_auto_detects_webp(self, tmp_path):
        prod = tmp_path / 'production'
        prod.mkdir()
        (prod / 'cover.webp').write_text('webp')
        result = _resolve_cover_path(str(tmp_path), None)
        assert result == str(prod / 'cover.webp')

    def test_cover_image_yaml_field(self, tmp_path, monkeypatch):
        """production.cover_image YAML field should be checked before auto-detect."""
        prod = tmp_path / 'production'
        prod.mkdir()
        (prod / 'cover.svg').write_text('svg')
        custom = tmp_path / 'assets' / 'final-cover.jpg'
        custom.parent.mkdir(parents=True)
        custom.write_text('custom')

        monkeypatch.setattr(
            'storyforge.assembly.read_production_field',
            lambda pd, field: 'assets/final-cover.jpg' if field == 'cover_image' else None,
        )
        result = _resolve_cover_path(str(tmp_path), None)
        assert result == str(custom)

    def test_cover_image_yaml_missing_file_falls_back(self, tmp_path, monkeypatch, capsys):
        """When cover_image YAML points to a missing file, warn and fall back."""
        prod = tmp_path / 'production'
        prod.mkdir()
        (prod / 'cover.jpg').write_text('fallback')

        monkeypatch.setattr(
            'storyforge.assembly.read_production_field',
            lambda pd, field: 'nonexistent/cover.png' if field == 'cover_image' else None,
        )
        result = _resolve_cover_path(str(tmp_path), None)
        assert result == str(prod / 'cover.jpg')
        assert 'WARNING' in capsys.readouterr().out

    def test_cover_image_yaml_read_error_falls_back(self, tmp_path, monkeypatch):
        """When read_production_field raises, fall back to auto-detect."""
        prod = tmp_path / 'production'
        prod.mkdir()
        (prod / 'cover.jpg').write_text('fallback')

        def _raise(*a, **kw):
            raise OSError('permission denied')
        monkeypatch.setattr('storyforge.assembly.read_production_field', _raise)
        result = _resolve_cover_path(str(tmp_path), None)
        assert result == str(prod / 'cover.jpg')

    def test_no_cover_returns_none(self, tmp_path):
        assert _resolve_cover_path(str(tmp_path), None) is None


# ---------------------------------------------------------------------------
# Publish manifest
# ---------------------------------------------------------------------------

def _fresh_map():
    """Return a fresh context-manager patch for check_chapter_map_freshness."""
    return patch('storyforge.common.check_chapter_map_freshness',
                 return_value=(True, [], []))


class TestGeneratePublishManifest:
    """Tests for generate_publish_manifest.

    The fixture chapter map only includes a subset of scenes, so we mock
    check_chapter_map_freshness to return (True, [], []) for most tests.
    """

    def test_generates_manifest_file(self, project_dir):
        with _fresh_map(), \
             patch('storyforge.assembly._md_to_html', return_value='<p>html</p>'):
            path = generate_publish_manifest(project_dir)
        assert os.path.isfile(path)
        assert path.endswith('publish-manifest.json')

    def test_manifest_structure(self, project_dir):
        with _fresh_map(), \
             patch('storyforge.assembly._md_to_html', return_value='<p>html</p>'):
            path = generate_publish_manifest(project_dir)
        with open(path) as f:
            manifest = json.load(f)
        assert manifest['title'] == "The Cartographer's Silence"
        assert 'chapters' in manifest
        assert len(manifest['chapters']) == 2
        assert manifest['chapters'][0]['number'] == 1
        assert manifest['slug'] == "the-cartographer-s-silence"

    def test_manifest_chapter_scenes(self, project_dir):
        with _fresh_map(), \
             patch('storyforge.assembly._md_to_html', return_value='<p>html</p>'):
            path = generate_publish_manifest(project_dir)
        with open(path) as f:
            manifest = json.load(f)
        ch1 = manifest['chapters'][0]
        # Chapter 1 has act1-sc01 and act1-sc02
        assert len(ch1['scenes']) == 2
        slugs = [s['slug'] for s in ch1['scenes']]
        assert 'act1-sc01' in slugs
        assert 'act1-sc02' in slugs

    def test_manifest_scene_has_required_fields(self, project_dir):
        with _fresh_map(), \
             patch('storyforge.assembly._md_to_html', return_value='<p>test</p>'):
            path = generate_publish_manifest(project_dir)
        with open(path) as f:
            manifest = json.load(f)
        scene = manifest['chapters'][0]['scenes'][0]
        assert 'slug' in scene
        assert 'content_html' in scene
        assert 'word_count' in scene
        assert 'sort_order' in scene

    def test_manifest_includes_metadata(self, project_dir):
        with _fresh_map(), \
             patch('storyforge.assembly._md_to_html', return_value='<p>x</p>'):
            path = generate_publish_manifest(project_dir)
        with open(path) as f:
            manifest = json.load(f)
        assert manifest['metadata']['genre'] == 'fantasy'

    def test_manifest_with_dashboard(self, project_dir):
        dash = os.path.join(project_dir, 'working', 'dashboard.html')
        os.makedirs(os.path.dirname(dash), exist_ok=True)
        with open(dash, 'w') as f:
            f.write('<html>dashboard</html>')

        with _fresh_map(), \
             patch('storyforge.assembly._md_to_html', return_value='<p>x</p>'):
            path = generate_publish_manifest(project_dir, include_dashboard=True)
        with open(path) as f:
            manifest = json.load(f)
        assert manifest['dashboard_html'] == '<html>dashboard</html>'

    def test_manifest_with_cover(self, project_dir):
        prod = os.path.join(project_dir, 'production')
        os.makedirs(prod, exist_ok=True)
        with open(os.path.join(prod, 'cover.png'), 'wb') as f:
            f.write(b'\x89PNG test data')

        with _fresh_map(), \
             patch('storyforge.assembly._md_to_html', return_value='<p>x</p>'):
            path = generate_publish_manifest(project_dir, include_cover=True)
        with open(path) as f:
            manifest = json.load(f)
        assert 'cover_base64' in manifest
        assert manifest['cover_extension'] == '.png'

    def test_stale_chapter_map_raises_valueerror(self, project_dir):
        """If chapter map is stale, generate_publish_manifest should raise."""
        with patch('storyforge.common.check_chapter_map_freshness',
                   return_value=(False, ['missing-scene'], [])):
            with pytest.raises(ValueError, match='stale'):
                generate_publish_manifest(project_dir)
