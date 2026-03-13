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

# ============================================================================
# generate_diagnosis
# ============================================================================

echo "  --- generate_diagnosis ---"

diag_dir="${SCORING_TMP}/diag-scores"
mkdir -p "$diag_dir"

# Create mock scene-scores.csv
cat > "${diag_dir}/scene-scores.csv" <<'CSV'
id|economy_clarity|thread_management|every_scene_must_turn
the-footnote|3|6|7
the-weight-of-the-rim|4|5|8
the-hollow-district|5|4|6
the-bridge|7|7|9
CSV

# Create mock weights file
diag_weights="${SCORING_TMP}/diag-weights.csv"
cat > "$diag_weights" <<'CSV'
section|principle|weight|author_weight|notes
prose_craft|economy_clarity|5||
scene_craft|thread_management|5||
scene_craft|every_scene_must_turn|7||
CSV

generate_diagnosis "$diag_dir" "" "$diag_weights"

assert_file_exists "${diag_dir}/diagnosis.csv" \
    "generate_diagnosis creates diagnosis.csv"

# Verify header
diag_header=$(head -1 "${diag_dir}/diagnosis.csv")
assert_equals "principle|scale|avg_score|worst_items|delta_from_last|priority" "$diag_header" \
    "generate_diagnosis header is correct"

# Verify economy_clarity row exists (avg ~4.75, < 6 -> medium or high)
diag_content=$(cat "${diag_dir}/diagnosis.csv")
assert_contains "$diag_content" "economy_clarity" \
    "generate_diagnosis includes economy_clarity"
assert_contains "$diag_content" "thread_management" \
    "generate_diagnosis includes thread_management"

# Verify at least one high or medium priority
diag_priorities=$(awk -F'|' 'NR > 1 { print $6 }' "${diag_dir}/diagnosis.csv" | sort -u)
assert_contains "$diag_priorities" "medium" \
    "generate_diagnosis assigns medium priority to below-6 avg principles"

# Test with previous cycle for delta computation
prev_dir="${SCORING_TMP}/prev-scores"
mkdir -p "$prev_dir"
cat > "${prev_dir}/scene-scores.csv" <<'CSV'
id|economy_clarity|thread_management|every_scene_must_turn
the-footnote|5|6|7
the-weight-of-the-rim|6|5|8
the-hollow-district|6|4|6
the-bridge|7|7|9
CSV

diag_dir2="${SCORING_TMP}/diag-scores2"
mkdir -p "$diag_dir2"
cp "${diag_dir}/scene-scores.csv" "${diag_dir2}/scene-scores.csv"

generate_diagnosis "$diag_dir2" "$prev_dir" "$diag_weights"
diag2_content=$(cat "${diag_dir2}/diagnosis.csv")
# economy_clarity went from avg 6.0 to 4.75 -> delta should be negative
assert_matches "$diag2_content" "economy_clarity.*-" \
    "generate_diagnosis computes negative delta for regressing principle"

# ============================================================================
# generate_proposals
# ============================================================================

echo "  --- generate_proposals ---"

generate_proposals "$diag_dir" "$diag_weights"

assert_file_exists "${diag_dir}/proposals.csv" \
    "generate_proposals creates proposals.csv"

# Verify header
prop_header=$(head -1 "${diag_dir}/proposals.csv")
assert_equals "id|principle|lever|target|change|rationale|status" "$prop_header" \
    "generate_proposals header is correct"

# Should have at least one proposal (economy_clarity avg < 6)
prop_count=$(awk -F'|' 'NR > 1 { count++ } END { print count+0 }' "${diag_dir}/proposals.csv")
assert_not_empty "$prop_count" \
    "generate_proposals generates at least one proposal"

# All proposals should have pending status
prop_statuses=$(awk -F'|' 'NR > 1 { print $7 }' "${diag_dir}/proposals.csv" | sort -u)
assert_equals "pending" "$prop_statuses" \
    "generate_proposals sets all statuses to pending"

# Test voice_guide lever for high-weight principles
high_weight_dir="${SCORING_TMP}/highw-scores"
mkdir -p "$high_weight_dir"
cat > "${high_weight_dir}/scene-scores.csv" <<'CSV'
id|stuck_principle
scene-a|3
scene-b|4
CSV

cat > "${high_weight_dir}/diagnosis.csv" <<'CSV'
principle|scale|avg_score|worst_items|delta_from_last|priority
stuck_principle|scene|3.5|scene-a;scene-b||high
CSV

high_weights="${SCORING_TMP}/highw.csv"
cat > "$high_weights" <<'CSV'
section|principle|weight|author_weight|notes
scene_craft|stuck_principle|9||
CSV

generate_proposals "$high_weight_dir" "$high_weights"
highw_content=$(cat "${high_weight_dir}/proposals.csv")
assert_contains "$highw_content" "voice_guide" \
    "generate_proposals suggests voice_guide when weight >= 8"

# ============================================================================
# record_tuning
# ============================================================================

echo "  --- record_tuning ---"

tuning_project="${SCORING_TMP}/tuning-project"
mkdir -p "${tuning_project}/working"

record_tuning "$tuning_project" "1" "p001" "economy_clarity" "craft_weight" "weight 5 → 7" "4.2" "5.8" "true"

assert_file_exists "${tuning_project}/working/tuning.csv" \
    "record_tuning creates tuning.csv"

tuning_header=$(head -1 "${tuning_project}/working/tuning.csv")
assert_equals "cycle|proposal_id|principle|lever|change|score_before|score_after|kept" "$tuning_header" \
    "record_tuning header is correct"

tuning_row=$(tail -1 "${tuning_project}/working/tuning.csv")
assert_contains "$tuning_row" "economy_clarity" \
    "record_tuning row contains principle"
assert_contains "$tuning_row" "p001" \
    "record_tuning row contains proposal_id"

# Append second row
record_tuning "$tuning_project" "2" "p002" "economy_clarity" "craft_weight" "weight 7 → 8" "5.8" "6.5" "true"
tuning_lines=$(wc -l < "${tuning_project}/working/tuning.csv" | tr -d ' ')
assert_equals "3" "$tuning_lines" \
    "record_tuning appends rows (header + 2 data rows)"

# ============================================================================
# check_validated_patterns
# ============================================================================

echo "  --- check_validated_patterns ---"

# No validated patterns with only 2 rows
validated=$(check_validated_patterns "$tuning_project")
assert_empty "$validated" \
    "check_validated_patterns returns empty with fewer than 3 kept rows"

# Add a third row for the same principle+lever
record_tuning "$tuning_project" "3" "p003" "economy_clarity" "craft_weight" "weight 8 → 9" "6.5" "7.2" "true"

validated=$(check_validated_patterns "$tuning_project")
assert_not_empty "$validated" \
    "check_validated_patterns returns result with 3+ kept rows"
assert_contains "$validated" "economy_clarity|craft_weight" \
    "check_validated_patterns returns correct principle|lever pair"

# Test that non-kept rows are not counted
mixed_project="${SCORING_TMP}/mixed-tuning"
mkdir -p "${mixed_project}/working"
record_tuning "$mixed_project" "1" "p001" "thread_mgmt" "craft_weight" "w5→7" "4.0" "5.5" "true"
record_tuning "$mixed_project" "2" "p002" "thread_mgmt" "craft_weight" "w7→8" "5.5" "5.0" "false"
record_tuning "$mixed_project" "3" "p003" "thread_mgmt" "craft_weight" "w8→9" "5.0" "6.0" "true"

validated_mixed=$(check_validated_patterns "$mixed_project")
assert_empty "$validated_mixed" \
    "check_validated_patterns does not count rows where kept=false"
