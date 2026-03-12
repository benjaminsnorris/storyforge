#!/bin/bash
# test-annotations.sh — Tests for annotation build integration
#
# Run via: ./tests/run-tests.sh tests/test-annotations.sh
# Tests scene marker injection, section wrapping, and annotation flag behavior.
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
# --annotate flag integration (requires pandoc)
# ============================================================================

if command -v pandoc &>/dev/null && [[ -d "${PROJECT_DIR}/scenes" ]]; then
    # Build web book WITH --annotate
    (cd "$PROJECT_DIR" && "${PLUGIN_DIR}/scripts/storyforge-assemble" --format web --annotate 2>/dev/null)
    if [[ -f "${PROJECT_DIR}/manuscript/output/web/chapters/chapter-01.html" ]]; then
        ch1=$(cat "${PROJECT_DIR}/manuscript/output/web/chapters/chapter-01.html")
        assert_contains "$ch1" 'data-scene=' "annotate flag: chapter HTML contains data-scene attributes"
        assert_contains "$ch1" 'Annotation Overlay' "annotate flag: chapter HTML contains annotation JS"
        assert_contains "$ch1" 'sf-highlight' "annotate flag: chapter HTML contains annotation CSS"
        assert_contains "$ch1" 'data-book=' "annotate flag: chapter HTML contains data-book attribute"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: annotate flag: web book chapter-01.html not generated"
    fi

    # Build web book WITHOUT --annotate
    (cd "$PROJECT_DIR" && "${PLUGIN_DIR}/scripts/storyforge-assemble" --format web 2>/dev/null)
    if [[ -f "${PROJECT_DIR}/manuscript/output/web/chapters/chapter-01.html" ]]; then
        ch1_clean=$(cat "${PROJECT_DIR}/manuscript/output/web/chapters/chapter-01.html")
        assert_not_contains "$ch1_clean" 'sf-highlight' "no annotate flag: chapter HTML does not contain annotation CSS"
        assert_not_contains "$ch1_clean" 'data-scene=' "no annotate flag: chapter HTML does not contain data-scene attributes"
    fi
fi
