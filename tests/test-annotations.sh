#!/bin/bash
# test-annotations.sh — Tests for annotation build integration
#
# Run via: ./tests/run-tests.sh tests/test-annotations.sh
# Tests scene marker injection, section wrapping, and annotation asset injection.
#
# Depends on: FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, assertion functions (from run-tests.sh)

# ============================================================================
# Scene markers in assembled chapters
# ============================================================================

result=$(assemble_chapter 1 "$PROJECT_DIR" "ornamental")
assert_contains "$result" "<!-- scene:act1-sc01 -->" "annotations: chapter 1 has scene marker for act1-sc01"
assert_contains "$result" "<!-- scene:act1-sc02 -->" "annotations: chapter 1 has scene marker for act1-sc02"

# Scene markers appear before scene prose
first_marker=$(echo "$result" | grep -n "scene:act1-sc01" | head -1 | cut -d: -f1)
first_prose=$(echo "$result" | grep -n "Dorren Hayle" | head -1 | cut -d: -f1)
if [[ "$first_marker" -lt "$first_prose" ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: annotations: scene marker appears before scene prose"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: annotations: scene marker should appear before scene prose"
fi

# Single-scene chapter also gets marker
result=$(assemble_chapter 2 "$PROJECT_DIR" "ornamental")
assert_contains "$result" "<!-- scene:act2-sc01 -->" "annotations: single-scene chapter has scene marker"

# ============================================================================
# _wrap_scene_sections
# ============================================================================

input='<h2>Chapter 1</h2>
<!-- scene:act1-sc01 -->
<p>First scene paragraph.</p>
<p>Second paragraph.</p>
<!-- scene:act1-sc02 -->
<p>Second scene paragraph.</p>'

result=$(echo "$input" | _wrap_scene_sections)
assert_contains "$result" '<section data-scene="act1-sc01">' "wrap_sections: creates section for first scene"
assert_contains "$result" '<section data-scene="act1-sc02">' "wrap_sections: creates section for second scene"
assert_contains "$result" '</section>' "wrap_sections: closes section tags"
assert_not_contains "$result" '<!-- scene:' "wrap_sections: removes HTML comment markers"

# Heading before first scene marker should not be wrapped
assert_contains "$result" '<h2>Chapter 1</h2>' "wrap_sections: preserves content before first scene marker"

# Single scene wrapping
input_single='<!-- scene:sc01 -->
<p>Only scene.</p>'
result=$(echo "$input_single" | _wrap_scene_sections)
assert_contains "$result" '<section data-scene="sc01">' "wrap_sections: works with single scene"
assert_contains "$result" '</section>' "wrap_sections: closes single scene section"

# ============================================================================
# Annotation asset injection (unit test — no full pipeline)
# ============================================================================

# Create a minimal chapter HTML file matching the template structure
_ann_test_dir=$(mktemp -d "${TMPDIR:-/tmp}/sf-ann-test.XXXXXX")
cat > "${_ann_test_dir}/chapter-01.html" << 'HTMLEOF'
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<script>var headScript = true;</script>
<style>
body { color: black; }
</style>
</head>
<body data-chapter="chapter-01">
<p>Hello world</p>
<script>
var reading = true;
</script>
</body>
</html>
HTMLEOF

# Create annotation CSS and JS temp files
_ann_css_tmp=$(mktemp "${TMPDIR:-/tmp}/sf-ann-css.XXXXXX")
_ann_js_tmp=$(mktemp "${TMPDIR:-/tmp}/sf-ann-js.XXXXXX")
printf '%s\n' '.sf-highlight { background: yellow; }' > "$_ann_css_tmp"
printf '%s\n' '// Storyforge Annotation Overlay' > "$_ann_js_tmp"

_ch_out="${_ann_test_dir}/chapter-01.html"

# Inject CSS BEFORE </style>
awk -v file="$_ann_css_tmp" '
    /<\/style>/ { while ((getline line < file) > 0) print line; close(file) }
    { print }
' "$_ch_out" > "${_ch_out}.tmp" && mv "${_ch_out}.tmp" "$_ch_out"

# Inject JS BEFORE the last </script>
_sc_count=$(grep -c '</script>' "$_ch_out")
awk -v file="$_ann_js_tmp" -v target="$_sc_count" '
    BEGIN { n = 0 }
    /<\/script>/ { n++ }
    /<\/script>/ && n == target { while ((getline line < file) > 0) print line; close(file) }
    { print }
' "$_ch_out" > "${_ch_out}.tmp" && mv "${_ch_out}.tmp" "$_ch_out"

_result=$(cat "$_ch_out")
assert_contains "$_result" 'sf-highlight' "asset injection: annotation CSS injected into chapter HTML"
assert_contains "$_result" 'Annotation Overlay' "asset injection: annotation JS injected into chapter HTML"

# CSS should be inside <style> block (before </style>)
_css_line=$(echo "$_result" | grep -n 'sf-highlight' | head -1 | cut -d: -f1)
_style_close=$(echo "$_result" | grep -n '</style>' | head -1 | cut -d: -f1)
if [[ "$_css_line" -lt "$_style_close" ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: asset injection: CSS is inside <style> block"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: asset injection: CSS should be before </style>"
fi

# JS should be inside the LAST <script> block, not the head script
_js_line=$(echo "$_result" | grep -n 'Annotation Overlay' | head -1 | cut -d: -f1)
_head_script_close=$(echo "$_result" | grep -n '</script>' | head -1 | cut -d: -f1)
_last_script_close=$(echo "$_result" | grep -n '</script>' | tail -1 | cut -d: -f1)
if [[ "$_js_line" -gt "$_head_script_close" && "$_js_line" -lt "$_last_script_close" ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: asset injection: JS is in main <script> block, not head"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: asset injection: JS should be in main script block (line $_js_line), not head (closes at $_head_script_close)"
fi

# data-book attribute injection (string substitution test)
_body_line='<body data-chapter="chapter-01" data-chapter-num="1">'
_book_slug="test-book"
_annotated_line="${_body_line//data-chapter=/data-book=\"${_book_slug}\" data-chapter=}"
assert_contains "$_annotated_line" 'data-book="test-book"' "data-book: attribute injected into body tag"
assert_contains "$_annotated_line" 'data-chapter="chapter-01"' "data-book: preserves existing data-chapter"

# Cleanup
rm -rf "$_ann_test_dir" "$_ann_css_tmp" "$_ann_js_tmp"
