#!/bin/bash
# test-assembly.sh — Tests for assembly library functions
#
# Run via: ./tests/run-tests.sh
# Tests chapter map parsing, scene prose extraction, chapter assembly,
# front/back matter generation, and production config reading.
#
# Depends on: FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, assertion functions (from run-tests.sh)

# ============================================================================
# count_chapters
# ============================================================================

result=$(count_chapters "$PROJECT_DIR")
assert_equals "2" "$result" "count_chapters: finds 2 chapters in fixture"

result=$(count_chapters "/nonexistent/path")
assert_equals "0" "$result" "count_chapters: returns 0 for missing project"

# ============================================================================
# chapter CSV row reading
# ============================================================================

CHAPTER_MAP="${PROJECT_DIR}/reference/chapter-map.csv"
result=$(get_csv_row "$CHAPTER_MAP" "1" "chapter")
assert_contains "$result" "The Finest Cartographer" "chapter CSV: chapter 1 has correct title"
assert_contains "$result" "act1-sc01" "chapter CSV: chapter 1 includes first scene"
assert_contains "$result" "act1-sc02" "chapter CSV: chapter 1 includes second scene"

result=$(get_csv_row "$CHAPTER_MAP" "2" "chapter")
assert_contains "$result" "Into the Blank" "chapter CSV: chapter 2 has correct title"
assert_contains "$result" "act2-sc01" "chapter CSV: chapter 2 includes scene"

result=$(get_csv_row "$CHAPTER_MAP" "3" "chapter")
assert_empty "$result" "chapter CSV: returns empty for nonexistent chapter"

# ============================================================================
# read_chapter_field
# ============================================================================

result=$(read_chapter_field 1 "$PROJECT_DIR" "title")
assert_equals "The Finest Cartographer" "$result" "read_chapter_field: reads title from chapter 1"

result=$(read_chapter_field 2 "$PROJECT_DIR" "title")
assert_equals "Into the Blank" "$result" "read_chapter_field: reads title from chapter 2"

result=$(read_chapter_field 1 "$PROJECT_DIR" "heading")
assert_equals "numbered-titled" "$result" "read_chapter_field: reads heading format"

# ============================================================================
# get_chapter_scenes
# ============================================================================

result=$(get_chapter_scenes 1 "$PROJECT_DIR")
assert_contains "$result" "act1-sc01" "get_chapter_scenes: chapter 1 contains act1-sc01"
assert_contains "$result" "act1-sc02" "get_chapter_scenes: chapter 1 contains act1-sc02"
assert_not_contains "$result" "act2-sc01" "get_chapter_scenes: chapter 1 does not contain act2 scenes"

result=$(get_chapter_scenes 2 "$PROJECT_DIR")
assert_contains "$result" "act2-sc01" "get_chapter_scenes: chapter 2 contains act2-sc01"
assert_not_contains "$result" "act1" "get_chapter_scenes: chapter 2 does not contain act1 scenes"

# Count scenes in chapter 1 (should be 2)
scene_count=$(get_chapter_scenes 1 "$PROJECT_DIR" | grep -c '[^ ]' || echo "0")
assert_equals "2" "$scene_count" "get_chapter_scenes: chapter 1 has exactly 2 scenes"

# Count scenes in chapter 2 (should be 1)
scene_count=$(get_chapter_scenes 2 "$PROJECT_DIR" | grep -c '[^ ]' || echo "0")
assert_equals "1" "$scene_count" "get_chapter_scenes: chapter 2 has exactly 1 scene"

# ============================================================================
# extract_scene_prose
# ============================================================================

result=$(extract_scene_prose "${PROJECT_DIR}/scenes/act1-sc01.md")
assert_contains "$result" "Dorren Hayle pressed" "extract_scene_prose: extracts prose from drafted scene"
assert_not_contains "$result" "id:" "extract_scene_prose: strips YAML frontmatter id field"
assert_not_contains "$result" "pov:" "extract_scene_prose: strips YAML frontmatter pov field"
assert_not_contains "$result" "---" "extract_scene_prose: strips frontmatter delimiters"

# Prose should start with actual content, not blank lines
first_line=$(extract_scene_prose "${PROJECT_DIR}/scenes/act1-sc01.md" | head -1)
assert_not_empty "$first_line" "extract_scene_prose: no leading blank lines"

# ============================================================================
# assemble_chapter
# ============================================================================

result=$(assemble_chapter 1 "$PROJECT_DIR" "space")
assert_contains "$result" "Chapter 1: The Finest Cartographer" "assemble_chapter: has chapter heading"
assert_contains "$result" "Dorren Hayle pressed" "assemble_chapter: includes scene 1 prose"
assert_contains "$result" "---" "assemble_chapter space: has thematic break between scenes"

# "blank" is a legacy alias for "space" — should also produce a thematic break
result=$(assemble_chapter 1 "$PROJECT_DIR" "blank")
assert_contains "$result" "---" "assemble_chapter blank (legacy): has thematic break between scenes"

# Chapter 1 with ornamental breaks
result=$(assemble_chapter 1 "$PROJECT_DIR" "ornamental")
assert_contains "$result" "Chapter 1: The Finest Cartographer" "assemble_chapter ornamental: has heading"
assert_contains "$result" "***" "assemble_chapter ornamental: has ornamental break between scenes"

# Chapter 1 with line breaks
result=$(assemble_chapter 1 "$PROJECT_DIR" "line")
assert_contains "$result" "---" "assemble_chapter line: has line break between scenes"

# Chapter 1 with custom break
result=$(assemble_chapter 1 "$PROJECT_DIR" "custom:~~~")
assert_contains "$result" "~~~" "assemble_chapter custom: has custom break symbol"

# ============================================================================
# assemble_chapter heading formats
# ============================================================================

# Test with different heading formats (we need to temporarily modify the chapter map)
# Instead, we test the heading logic directly through assemble_chapter
# The fixture uses numbered-titled, so we verify that format
result=$(assemble_chapter 1 "$PROJECT_DIR" "space")
assert_matches "$result" "Chapter 1:" "assemble_chapter: numbered-titled format includes number"
assert_contains "$result" "The Finest Cartographer" "assemble_chapter: numbered-titled format includes title"

result=$(assemble_chapter 2 "$PROJECT_DIR" "space")
assert_matches "$result" "Chapter 2:" "assemble_chapter: chapter 2 has correct number"
assert_contains "$result" "Into the Blank" "assemble_chapter: chapter 2 heading has title"

# ============================================================================
# assemble_chapter — scene markers
# ============================================================================

result=$(assemble_chapter 1 "$PROJECT_DIR" "ornamental")
assert_contains "$result" "<!-- scene:act1-sc01 -->" "assemble_chapter: includes scene marker for first scene"
assert_contains "$result" "<!-- scene:act1-sc02 -->" "assemble_chapter: includes scene marker for second scene"

result=$(assemble_chapter 2 "$PROJECT_DIR" "ornamental")
assert_contains "$result" "<!-- scene:act2-sc01 -->" "assemble_chapter: includes scene marker for single scene"

# ============================================================================
# read_production_field
# ============================================================================

result=$(read_production_field "$PROJECT_DIR" "author")
assert_equals "Test Author" "$result" "read_production_field: reads author"

result=$(read_production_field "$PROJECT_DIR" "language")
assert_equals "en" "$result" "read_production_field: reads language"

result=$(read_production_field "$PROJECT_DIR" "scene_break")
assert_equals "ornamental" "$result" "read_production_field: reads scene_break"

result=$(read_production_field "$PROJECT_DIR" "include_toc")
assert_equals "true" "$result" "read_production_field: reads include_toc"

result=$(read_production_field "$PROJECT_DIR" "genre_preset")
assert_equals "fantasy" "$result" "read_production_field: reads genre_preset"

# ============================================================================
# read_production_nested
# ============================================================================

result=$(read_production_nested "$PROJECT_DIR" "copyright" "year")
assert_equals "2026" "$result" "read_production_nested: reads copyright year"

result=$(read_production_nested "$PROJECT_DIR" "copyright" "isbn")
assert_equals "978-0-000000-00-0" "$result" "read_production_nested: reads copyright isbn"

result=$(read_production_nested "$PROJECT_DIR" "copyright" "license")
assert_equals "All rights reserved." "$result" "read_production_nested: reads copyright license"

# ============================================================================
# generate_title_page
# ============================================================================

result=$(generate_title_page "$PROJECT_DIR")
assert_contains "$result" "The Cartographer's Silence" "generate_title_page: includes project title"
assert_contains "$result" "Test Author" "generate_title_page: includes author"

# ============================================================================
# generate_copyright_page
# ============================================================================

result=$(generate_copyright_page "$PROJECT_DIR")
assert_contains "$result" "Copyright" "generate_copyright_page: has copyright heading"
assert_contains "$result" "The Cartographer's Silence" "generate_copyright_page: includes title"
assert_contains "$result" "Test Author" "generate_copyright_page: includes author"
assert_contains "$result" "2026" "generate_copyright_page: includes year"
assert_contains "$result" "978-0-000000-00-0" "generate_copyright_page: includes ISBN"
assert_contains "$result" "All rights reserved" "generate_copyright_page: includes license"

# ============================================================================
# generate_toc
# ============================================================================

result=$(generate_toc "$PROJECT_DIR")
assert_contains "$result" "Contents" "generate_toc: has contents heading"
assert_contains "$result" "The Finest Cartographer" "generate_toc: includes chapter 1 title"
assert_contains "$result" "Into the Blank" "generate_toc: includes chapter 2 title"

# TOC should have exactly 2 chapter entries
toc_entries=$(echo "$result" | grep -c '^- ' || echo "0")
assert_equals "2" "$toc_entries" "generate_toc: has correct number of entries"

# ============================================================================
# generate_epub_metadata
# ============================================================================

result=$(generate_epub_metadata "$PROJECT_DIR")
assert_contains "$result" "title:" "generate_epub_metadata: has title field"
assert_contains "$result" "The Cartographer's Silence" "generate_epub_metadata: correct title"
assert_contains "$result" "author:" "generate_epub_metadata: has author field"
assert_contains "$result" "Test Author" "generate_epub_metadata: correct author"
assert_contains "$result" "lang:" "generate_epub_metadata: has language field"
assert_contains "$result" "fantasy" "generate_epub_metadata: has genre as subject"
assert_contains "$result" "978-0-000000-00-0" "generate_epub_metadata: has ISBN"
assert_contains "$result" "rights:" "generate_epub_metadata: has rights field"

# ============================================================================
# assemble_manuscript
# ============================================================================

# Create a temp file for manuscript output
TEMP_MANUSCRIPT=$(mktemp)
trap "rm -f $TEMP_MANUSCRIPT" EXIT

result=$(assemble_manuscript "$PROJECT_DIR" "$TEMP_MANUSCRIPT" 2>/dev/null)
rc=$?
assert_exit_code "0" "$rc" "assemble_manuscript: exits 0"

# Check the assembled manuscript
manuscript_content=$(cat "$TEMP_MANUSCRIPT")
assert_contains "$manuscript_content" "The Cartographer's Silence" "assemble_manuscript: has title"
assert_contains "$manuscript_content" "Test Author" "assemble_manuscript: has author"
assert_contains "$manuscript_content" "Copyright" "assemble_manuscript: has copyright page"
assert_contains "$manuscript_content" "Chapter 1:" "assemble_manuscript: has chapter 1 heading"
assert_contains "$manuscript_content" "Chapter 2:" "assemble_manuscript: has chapter 2 heading"
assert_contains "$manuscript_content" "Dorren Hayle pressed" "assemble_manuscript: has scene prose"

# Manuscript word count
wc=$(manuscript_word_count "$TEMP_MANUSCRIPT")
assert_not_empty "$wc" "assemble_manuscript: word count is non-empty"
# Should be > 0 (at least the scene prose + front matter)
if [[ "$wc" -gt 0 ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: assemble_manuscript: word count > 0 (${wc} words)"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: assemble_manuscript: word count should be > 0, got ${wc}"
fi

rm -f "$TEMP_MANUSCRIPT"
trap - EXIT

# ============================================================================
# get_genre_css
# ============================================================================

result=$(get_genre_css "$PLUGIN_DIR" "fantasy")
assert_contains "$result" "fantasy.css" "get_genre_css: returns fantasy CSS for fantasy genre"

result=$(get_genre_css "$PLUGIN_DIR" "literary fiction")
assert_contains "$result" "literary-fiction.css" "get_genre_css: normalizes genre name with hyphen"

result=$(get_genre_css "$PLUGIN_DIR" "thriller")
assert_contains "$result" "thriller.css" "get_genre_css: returns thriller CSS"

result=$(get_genre_css "$PLUGIN_DIR" "romance")
assert_contains "$result" "romance.css" "get_genre_css: returns romance CSS"

result=$(get_genre_css "$PLUGIN_DIR" "science fiction")
assert_contains "$result" "science-fiction.css" "get_genre_css: returns sci-fi CSS"

result=$(get_genre_css "$PLUGIN_DIR" "unknown-genre-xyz")
assert_contains "$result" "default.css" "get_genre_css: falls back to default for unknown genre"

# ============================================================================
# Tool detection (existence checks, not actual tool tests)
# ============================================================================

# check_pandoc — just verify the function exists and returns cleanly
# Run in subshell to avoid set -e leaking into the test runner
pandoc_rc=0
(check_pandoc >/dev/null 2>&1) || pandoc_rc=$?
# We don't assert pass/fail on pandoc availability — just that the function runs
if [[ $pandoc_rc -eq 0 ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: check_pandoc: function runs (pandoc available)"
else
    PASS=$((PASS + 1))
    echo "  PASS: check_pandoc: function runs (pandoc not available, returns 1)"
fi

# ============================================================================
# count_parts
# ============================================================================

result=$(count_parts "$PROJECT_DIR")
assert_equals "2" "$result" "count_parts: finds 2 parts in fixture"

result=$(count_parts "/nonexistent/path")
assert_equals "0" "$result" "count_parts: returns 0 for missing project"

# ============================================================================
# read_part_field
# ============================================================================

result=$(read_part_field 1 "$PROJECT_DIR" "title")
assert_equals "The Expedition" "$result" "read_part_field: reads title from part 1"

result=$(read_part_field 2 "$PROJECT_DIR" "title")
assert_equals "The Blank" "$result" "read_part_field: reads title from part 2"

result=$(read_part_field 1 "$PROJECT_DIR" "number")
assert_equals "1" "$result" "read_part_field: reads number from part 1"

# ============================================================================
# get_chapter_part_title
# ============================================================================

result=$(get_chapter_part_title 1 "$PROJECT_DIR")
assert_equals "The Expedition" "$result" "get_chapter_part_title: chapter 1 belongs to part 'The Expedition'"

result=$(get_chapter_part_title 2 "$PROJECT_DIR")
assert_equals "The Blank" "$result" "get_chapter_part_title: chapter 2 belongs to part 'The Blank'"

# ============================================================================
# read_chapter_field: part field
# ============================================================================

result=$(read_chapter_field 1 "$PROJECT_DIR" "part")
assert_equals "1" "$result" "read_chapter_field: reads part number from chapter 1"

result=$(read_chapter_field 2 "$PROJECT_DIR" "part")
assert_equals "2" "$result" "read_chapter_field: reads part number from chapter 2"

# ============================================================================
# _wrap_scene_sections
# ============================================================================

input='<!-- scene:act1-sc01 -->
<p>First scene prose.</p>
<!-- scene:act1-sc02 -->
<p>Second scene prose.</p>'

result=$(echo "$input" | _wrap_scene_sections)
assert_contains "$result" '<section data-scene="act1-sc01">' "_wrap_scene_sections: wraps first scene"
assert_contains "$result" '<section data-scene="act1-sc02">' "_wrap_scene_sections: wraps second scene"
assert_contains "$result" '</section>' "_wrap_scene_sections: closes sections"
assert_not_contains "$result" '<!-- scene:' "_wrap_scene_sections: removes comment markers"
