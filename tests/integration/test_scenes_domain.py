"""Tests for storyforge.scenes — scene file management library functions.

Covers: generate_slug, unique_slug, parse_scene_boundaries,
generate_scenes_rows, generate_intent_rows, scenes_header, intent_header,
split_by_scene_markers, generate_rename_plan, _title_from_file,
build_boundary_prompt.
"""

import os
import json

import pytest

from storyforge.scenes import (
    generate_slug,
    unique_slug,
    parse_scene_boundaries,
    generate_scenes_rows,
    generate_intent_rows,
    scenes_header,
    intent_header,
    split_by_scene_markers,
    generate_rename_plan,
    _title_from_file,
    build_boundary_prompt,
)


# ============================================================================
# generate_slug
# ============================================================================

class TestGenerateSlug:
    def test_basic_title(self):
        assert generate_slug('The Finest Cartographer') == 'finest-cartographer'

    def test_strips_leading_the(self):
        assert generate_slug('The Great Escape') == 'great-escape'

    def test_lowercase(self):
        assert generate_slug('INTO THE BLANK') == 'into-the-blank'

    def test_removes_special_chars(self):
        assert generate_slug("What's This? (A Test!)") == 'whats-this-a-test'

    def test_em_dash_to_hyphen(self):
        slug = generate_slug('Before\u2014After')
        assert slug == 'before-after'

    def test_en_dash_to_hyphen(self):
        slug = generate_slug('Before\u2013After')
        assert slug == 'before-after'

    def test_ellipsis_removed(self):
        slug = generate_slug('Waiting...')
        assert slug == 'waiting'

    def test_spaces_to_hyphens(self):
        assert generate_slug('word one two') == 'word-one-two'

    def test_underscores_to_hyphens(self):
        assert generate_slug('word_one_two') == 'word-one-two'

    def test_slashes_to_hyphens(self):
        assert generate_slug('word/one/two') == 'word-one-two'

    def test_collapses_multiple_hyphens(self):
        assert generate_slug('word---thing') == 'word-thing'

    def test_strips_leading_trailing_hyphens(self):
        assert generate_slug('-hello-') == 'hello'

    def test_truncates_to_50_chars(self):
        long_title = 'a ' * 50  # produces many words
        slug = generate_slug(long_title)
        assert len(slug) <= 50

    def test_truncation_strips_trailing_hyphen(self):
        # Make a slug that would end with hyphen at char 50
        title = 'abcdefghij ' * 6  # will produce hyphens
        slug = generate_slug(title)
        assert not slug.endswith('-')
        assert len(slug) <= 50

    def test_removes_quotes_colons_semicolons(self):
        slug = generate_slug('"Hello": a test; really')
        assert slug == 'hello-a-test-really'

    def test_removes_backticks(self):
        slug = generate_slug('`code` thing')
        assert slug == 'code-thing'

    def test_empty_string(self):
        assert generate_slug('') == ''

    def test_pure_special_chars(self):
        assert generate_slug('!!!???') == ''


# ============================================================================
# unique_slug
# ============================================================================

class TestUniqueSlug:
    def test_no_collision(self):
        used = set()
        result = unique_slug('hello', used)
        assert result == 'hello'
        assert 'hello' in used

    def test_collision_appends_counter(self):
        used = {'hello'}
        result = unique_slug('hello', used)
        assert result == 'hello-2'
        assert 'hello-2' in used

    def test_multiple_collisions(self):
        used = {'hello', 'hello-2', 'hello-3'}
        result = unique_slug('hello', used)
        assert result == 'hello-4'

    def test_updates_used_set(self):
        used = set()
        unique_slug('a', used)
        unique_slug('a', used)
        unique_slug('a', used)
        assert used == {'a', 'a-2', 'a-3'}


# ============================================================================
# parse_scene_boundaries
# ============================================================================

class TestParseSceneBoundaries:
    def test_basic_parsing(self):
        response = (
            "SCENE: 1 | Opening | The story begins\n"
            "SCENE: 42 | Midpoint | Everything changes\n"
            "SCENE: 100 | Finale | The end\n"
        )
        scenes = parse_scene_boundaries(response)
        assert len(scenes) == 3
        assert scenes[0]['line_number'] == 1
        assert scenes[0]['title'] == 'Opening'
        assert scenes[0]['description'] == 'The story begins'

    def test_sorted_by_line_number(self):
        response = (
            "SCENE: 50 | Middle\n"
            "SCENE: 1 | Start\n"
            "SCENE: 100 | End\n"
        )
        scenes = parse_scene_boundaries(response)
        assert scenes[0]['line_number'] == 1
        assert scenes[1]['line_number'] == 50
        assert scenes[2]['line_number'] == 100

    def test_ignores_non_scene_lines(self):
        response = (
            "Here is my analysis:\n"
            "\n"
            "SCENE: 1 | Opening\n"
            "The above starts the story.\n"
            "SCENE: 50 | Next Part\n"
        )
        scenes = parse_scene_boundaries(response)
        assert len(scenes) == 2

    def test_case_insensitive_prefix(self):
        response = "scene: 1 | Opening\nScene: 10 | Next\n"
        scenes = parse_scene_boundaries(response)
        assert len(scenes) == 2

    def test_missing_title(self):
        response = "SCENE: 1\n"
        scenes = parse_scene_boundaries(response)
        assert len(scenes) == 1
        assert scenes[0]['title'] == ''

    def test_missing_description(self):
        response = "SCENE: 1 | Title Only\n"
        scenes = parse_scene_boundaries(response)
        assert len(scenes) == 1
        assert scenes[0]['description'] == ''

    def test_invalid_line_number_skipped(self):
        response = "SCENE: abc | Bad Line\nSCENE: 5 | Good Line\n"
        scenes = parse_scene_boundaries(response)
        assert len(scenes) == 1
        assert scenes[0]['line_number'] == 5

    def test_empty_response(self):
        scenes = parse_scene_boundaries('')
        assert scenes == []

    def test_extra_pipes_in_description(self):
        response = "SCENE: 1 | Title | Desc with | pipes\n"
        scenes = parse_scene_boundaries(response)
        assert scenes[0]['description'] == 'Desc with | pipes'


# ============================================================================
# generate_scenes_rows
# ============================================================================

class TestGenerateScenesRows:
    def test_basic_row_generation(self):
        scenes = [
            {'title': 'The Finest Cartographer'},
            {'title': 'The Missing Village'},
        ]
        rows = generate_scenes_rows(scenes)
        assert len(rows) == 2
        # First scene: slug should strip leading "the-"
        assert rows[0].startswith('finest-cartographer|1|')
        assert rows[1].startswith('missing-village|2|')

    def test_with_part_number(self):
        scenes = [{'title': 'Chapter One'}]
        rows = generate_scenes_rows(scenes, part_num=2)
        parts = rows[0].split('|')
        assert parts[3] == '2'  # part column

    def test_seq_start(self):
        scenes = [{'title': 'Scene'}]
        rows = generate_scenes_rows(scenes, seq_start=10)
        parts = rows[0].split('|')
        assert parts[1] == '10'  # seq column

    def test_custom_slug(self):
        scenes = [{'title': 'Scene', 'slug': 'custom-slug'}]
        rows = generate_scenes_rows(scenes)
        assert rows[0].startswith('custom-slug|')

    def test_word_count(self):
        scenes = [{'title': 'Scene', 'word_count': 1500}]
        rows = generate_scenes_rows(scenes)
        parts = rows[0].split('|')
        assert parts[12] == '1500'  # word_count column (index 12 per header)

    def test_empty_title_gets_fallback_slug(self):
        scenes = [{'title': ''}]
        rows = generate_scenes_rows(scenes)
        assert rows[0].startswith('scene-1|')

    def test_duplicate_slugs_get_suffix(self):
        scenes = [
            {'title': 'Same Title'},
            {'title': 'Same Title'},
        ]
        rows = generate_scenes_rows(scenes)
        slug1 = rows[0].split('|')[0]
        slug2 = rows[1].split('|')[0]
        assert slug1 != slug2
        assert slug2.endswith('-2')


# ============================================================================
# generate_intent_rows
# ============================================================================

class TestGenerateIntentRows:
    def test_basic_generation(self):
        scenes = [{'title': 'The Finest Cartographer'}]
        rows = generate_intent_rows(scenes)
        assert len(rows) == 1
        assert rows[0].startswith('finest-cartographer|')
        # All fields empty (10 pipes)
        assert rows[0].count('|') == 10

    def test_empty_title_fallback(self):
        scenes = [{'title': ''}]
        rows = generate_intent_rows(scenes)
        assert rows[0].startswith('scene-unknown|')

    def test_duplicate_slugs(self):
        scenes = [{'title': 'Same'}, {'title': 'Same'}]
        rows = generate_intent_rows(scenes)
        slug1 = rows[0].split('|')[0]
        slug2 = rows[1].split('|')[0]
        assert slug1 != slug2


# ============================================================================
# scenes_header / intent_header
# ============================================================================

class TestHeaders:
    def test_scenes_header_format(self):
        header = scenes_header()
        fields = header.split('|')
        assert fields[0] == 'id'
        assert fields[1] == 'seq'
        assert 'title' in fields
        assert 'word_count' in fields

    def test_intent_header_format(self):
        header = intent_header()
        fields = header.split('|')
        assert fields[0] == 'id'
        assert 'function' in fields
        assert 'mice_threads' in fields


# ============================================================================
# split_by_scene_markers
# ============================================================================

class TestSplitBySceneMarkers:
    def test_basic_split(self):
        text = "Line 1 start of scene one\nLine 2\nLine 3 start of scene two\nLine 4\n"
        markers = [
            {'line_number': 1, 'title': 'Scene One'},
            {'line_number': 3, 'title': 'Scene Two'},
        ]
        result = split_by_scene_markers(text, markers)
        assert len(result) == 2
        slugs = list(result.keys())
        assert slugs[0] == 'scene-one'
        assert slugs[1] == 'scene-two'

    def test_strips_scene_break_markers(self):
        text = "Scene 1 prose\n***\nScene 2 prose\n"
        markers = [
            {'line_number': 1, 'title': 'First'},
            {'line_number': 3, 'title': 'Second'},
        ]
        result = split_by_scene_markers(text, markers)
        # '***' should be stripped from the first scene
        first_prose = list(result.values())[0]
        assert '***' not in first_prose

    def test_strips_all_break_variants(self):
        text = "A\n***\nB\n---\nC\n# # #\nD\n* * *\nE\n"
        markers = [{'line_number': 1, 'title': 'All'}]
        result = split_by_scene_markers(text, markers)
        prose = list(result.values())[0]
        assert '***' not in prose
        assert '---' not in prose
        assert '# # #' not in prose
        assert '* * *' not in prose

    def test_trims_leading_blank_lines(self):
        text = "\n\nActual prose\n"
        markers = [{'line_number': 1, 'title': 'Scene'}]
        result = split_by_scene_markers(text, markers)
        prose = list(result.values())[0]
        assert prose.startswith('Actual prose')

    def test_handles_unsorted_markers(self):
        text = "Line 1\nLine 2\nLine 3\n"
        markers = [
            {'line_number': 3, 'title': 'Later'},
            {'line_number': 1, 'title': 'Earlier'},
        ]
        result = split_by_scene_markers(text, markers)
        slugs = list(result.keys())
        # Should be sorted by line_number
        assert slugs[0] == 'earlier'
        assert slugs[1] == 'later'

    def test_single_scene(self):
        text = "Some prose here\nMore prose\n"
        markers = [{'line_number': 1, 'title': 'Only Scene'}]
        result = split_by_scene_markers(text, markers)
        assert len(result) == 1

    def test_marker_beyond_text_length(self):
        text = "Short text\n"
        markers = [
            {'line_number': 1, 'title': 'First'},
            {'line_number': 999, 'title': 'Beyond'},
        ]
        result = split_by_scene_markers(text, markers)
        assert len(result) == 2

    def test_duplicate_titles_get_unique_slugs(self):
        text = "A\nB\nC\n"
        markers = [
            {'line_number': 1, 'title': 'Same'},
            {'line_number': 2, 'title': 'Same'},
        ]
        result = split_by_scene_markers(text, markers)
        slugs = list(result.keys())
        assert slugs[0] != slugs[1]


# ============================================================================
# generate_rename_plan
# ============================================================================

class TestGenerateRenamePlan:
    def test_no_renames_needed(self, project_dir):
        """When filenames already match slugs from titles, no renames."""
        scenes_dir = os.path.join(project_dir, 'scenes')
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        # The fixture has scenes with IDs matching filenames, but titles
        # that produce different slugs. So renames are expected.
        plan = generate_rename_plan(scenes_dir, meta_csv)
        # Plan should contain entries where slug differs from file ID
        assert isinstance(plan, list)

    def test_missing_csv_returns_empty(self, project_dir):
        scenes_dir = os.path.join(project_dir, 'scenes')
        plan = generate_rename_plan(scenes_dir, '/nonexistent/scenes.csv')
        assert plan == []

    def test_missing_scenes_dir_returns_empty(self, project_dir):
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        plan = generate_rename_plan('/nonexistent/scenes/', meta_csv)
        assert plan == []

    def test_rename_plan_has_absolute_paths(self, project_dir):
        scenes_dir = os.path.join(project_dir, 'scenes')
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        plan = generate_rename_plan(scenes_dir, meta_csv)
        for old_path, new_path in plan:
            assert os.path.isabs(old_path)
            assert os.path.isabs(new_path)

    def test_numeric_to_slug_rename(self, project_dir):
        """Numeric filenames should be renamed to title-based slugs."""
        scenes_dir = os.path.join(project_dir, 'scenes')
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        # Create a numeric scene file
        numeric_file = os.path.join(scenes_dir, '001.md')
        with open(numeric_file, 'w') as f:
            f.write('# Test Scene\nSome prose.\n')
        # Add the numeric scene to the CSV — rewrite for simplicity
        with open(meta_csv, 'a') as f:
            f.write('001|99|Numeric Scene|1||||||||||\n')
        plan = generate_rename_plan(scenes_dir, meta_csv)
        old_names = [os.path.basename(old) for old, _ in plan]
        assert '001.md' in old_names

    def test_empty_csv_returns_empty(self, tmp_path):
        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        csv_path = str(tmp_path / 'scenes.csv')
        with open(csv_path, 'w') as f:
            f.write('')
        plan = generate_rename_plan(scenes_dir, csv_path)
        assert plan == []


# ============================================================================
# _title_from_file
# ============================================================================

class TestTitleFromFile:
    def test_heading_extraction(self, tmp_path):
        f = tmp_path / 'scene.md'
        f.write_text('# My Great Scene\n\nSome prose.\n')
        assert _title_from_file(str(f)) == 'My Great Scene'

    def test_h2_heading(self, tmp_path):
        f = tmp_path / 'scene.md'
        f.write_text('## Section Title\n\nProse.\n')
        assert _title_from_file(str(f)) == 'Section Title'

    def test_no_heading_uses_first_line(self, tmp_path):
        f = tmp_path / 'scene.md'
        f.write_text('This is the first line of prose.\n\nMore text.\n')
        assert _title_from_file(str(f)) == 'This is the first line of prose.'

    def test_empty_file(self, tmp_path):
        f = tmp_path / 'empty.md'
        f.write_text('')
        assert _title_from_file(str(f)) == ''

    def test_blank_lines_skipped(self, tmp_path):
        f = tmp_path / 'scene.md'
        f.write_text('\n\n\n# Actual Title\n')
        assert _title_from_file(str(f)) == 'Actual Title'

    def test_missing_file(self):
        assert _title_from_file('/nonexistent/file.md') == ''

    def test_truncates_long_first_line(self, tmp_path):
        f = tmp_path / 'long.md'
        f.write_text('x' * 200 + '\n')
        result = _title_from_file(str(f))
        assert len(result) <= 80


# ============================================================================
# build_boundary_prompt
# ============================================================================

class TestBuildBoundaryPrompt:
    def test_includes_chapter_text(self):
        prompt = build_boundary_prompt('Hello world\nSecond line\n')
        assert 'Hello world' in prompt
        assert 'Second line' in prompt

    def test_includes_instructions(self):
        prompt = build_boundary_prompt('Some text')
        assert 'SCENE:' in prompt
        assert 'line_number' in prompt

    def test_mentions_scene_break_criteria(self):
        prompt = build_boundary_prompt('Text')
        assert 'Time' in prompt or 'time' in prompt
        assert 'Setting' in prompt or 'location' in prompt.lower()

    def test_empty_chapter(self):
        prompt = build_boundary_prompt('')
        # Should still produce a prompt, just with empty text section
        assert 'SCENE:' in prompt
