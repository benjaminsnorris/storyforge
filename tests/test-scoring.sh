#!/bin/bash
# test-scoring.sh — Tests for scoring.sh weight management functions

# ============================================================================
# Setup
# ============================================================================

SCORING_TMP="$(mktemp -d)"
trap 'rm -rf "$SCORING_TMP"' EXIT

# ============================================================================
# init_craft_weights
# ============================================================================

echo "  --- init_craft_weights ---"

# Test: copies defaults to project dir when missing
test_project="${SCORING_TMP}/project1"
mkdir -p "$test_project"
init_craft_weights "$test_project" "$PLUGIN_DIR"
assert_file_exists "${test_project}/working/craft-weights.csv" \
    "init_craft_weights copies defaults to project"

# Verify content matches defaults
expected_lines=$(wc -l < "${PLUGIN_DIR}/references/default-craft-weights.csv" | tr -d ' ')
actual_lines=$(wc -l < "${test_project}/working/craft-weights.csv" | tr -d ' ')
assert_equals "$expected_lines" "$actual_lines" \
    "init_craft_weights: copied file has same line count as defaults"

# Test: does not overwrite existing file
echo "custom|content" > "${test_project}/working/craft-weights.csv"
init_craft_weights "$test_project" "$PLUGIN_DIR"
actual=$(cat "${test_project}/working/craft-weights.csv")
assert_equals "custom|content" "$actual" \
    "init_craft_weights does not overwrite existing file"

# ============================================================================
# get_effective_weight
# ============================================================================

echo "  --- get_effective_weight ---"

# Set up a weights file for testing
test_weights="${SCORING_TMP}/weights.csv"
cat > "$test_weights" <<'CSV'
section|principle|weight|author_weight|notes
scene_craft|enter_late_leave_early|5||
scene_craft|every_scene_must_turn|7|9|author override
prose_craft|economy_clarity|5|3|lowered
CSV

# Test: returns weight when no author_weight
result=$(get_effective_weight "$test_weights" "enter_late_leave_early")
assert_equals "5" "$result" \
    "get_effective_weight returns weight when no author_weight"

# Test: returns author_weight when set
result=$(get_effective_weight "$test_weights" "every_scene_must_turn")
assert_equals "9" "$result" \
    "get_effective_weight returns author_weight when set"

# Test: returns author_weight even when lower than weight
result=$(get_effective_weight "$test_weights" "economy_clarity")
assert_equals "3" "$result" \
    "get_effective_weight returns author_weight even when lower"

# ============================================================================
# get_csv_field with key_column
# ============================================================================

echo "  --- get_csv_field with key_column ---"

result=$(get_csv_field "$test_weights" "every_scene_must_turn" "weight" "principle")
assert_equals "7" "$result" \
    "get_csv_field with key_column=principle returns correct weight"

result=$(get_csv_field "$test_weights" "every_scene_must_turn" "section" "principle")
assert_equals "scene_craft" "$result" \
    "get_csv_field with key_column=principle returns correct section"

result=$(get_csv_field "$test_weights" "every_scene_must_turn" "notes" "principle")
assert_equals "author override" "$result" \
    "get_csv_field with key_column=principle returns correct notes"

# ============================================================================
# update_csv_field with key_column
# ============================================================================

echo "  --- update_csv_field with key_column ---"

update_weights="${SCORING_TMP}/update-weights.csv"
cp "$test_weights" "$update_weights"

update_csv_field "$update_weights" "enter_late_leave_early" "author_weight" "8" "principle"
result=$(get_csv_field "$update_weights" "enter_late_leave_early" "author_weight" "principle")
assert_equals "8" "$result" \
    "update_csv_field with key_column sets author_weight"

# Verify other rows unchanged
result=$(get_csv_field "$update_weights" "every_scene_must_turn" "author_weight" "principle")
assert_equals "9" "$result" \
    "update_csv_field with key_column does not affect other rows"

# ============================================================================
# get_csv_row with key_column
# ============================================================================

echo "  --- get_csv_row with key_column ---"

result=$(get_csv_row "$test_weights" "economy_clarity" "principle")
assert_contains "$result" "economy_clarity" \
    "get_csv_row with key_column returns matching row"
assert_contains "$result" "prose_craft" \
    "get_csv_row with key_column row contains section"
