#!/bin/bash
# test-scene-filter.sh — Tests for scene-filter.sh shared library

# Tests use $FIXTURE_DIR, $PROJECT_DIR, $PLUGIN_DIR, $TMPDIR
# Libraries are already sourced by run-tests.sh

METADATA_CSV="${FIXTURE_DIR}/reference/scenes.csv"

# ============================================================================
# build_scene_list
# ============================================================================

echo "--- build_scene_list ---"

build_scene_list "$METADATA_CSV"
assert_equals "6" "${#ALL_SCENE_IDS[@]}" "build_scene_list: finds all 6 scenes"
assert_equals "act1-sc01" "${ALL_SCENE_IDS[0]}" "build_scene_list: first scene by seq"
assert_equals "act1-sc02" "${ALL_SCENE_IDS[1]}" "build_scene_list: second scene by seq"
assert_equals "new-x1" "${ALL_SCENE_IDS[2]}" "build_scene_list: third scene by seq"
assert_equals "act2-sc01" "${ALL_SCENE_IDS[3]}" "build_scene_list: fourth scene by seq"
assert_equals "act2-sc02" "${ALL_SCENE_IDS[4]}" "build_scene_list: fifth scene by seq"
assert_equals "act2-sc03" "${ALL_SCENE_IDS[5]}" "build_scene_list: sixth scene by seq"

# Test that cut scenes are excluded
TMPCSV="${TMPDIR}/scenes-cut.csv"
cp "$METADATA_CSV" "$TMPCSV"
# Add a cut scene
echo "cut-scene|7|Cut Scene|1|Someone|Somewhere|1|morning||character|cut|500|500" >> "$TMPCSV"
build_scene_list "$TMPCSV"
assert_equals "6" "${#ALL_SCENE_IDS[@]}" "build_scene_list: excludes cut scenes"
rm -f "$TMPCSV"

# Test that merged scenes are excluded
TMPCSV="${TMPDIR}/scenes-merged.csv"
cp "$METADATA_CSV" "$TMPCSV"
echo "merged-scene|7|Merged Scene|1|Someone|Somewhere|1|morning||character|merged|3|500" >> "$TMPCSV"
build_scene_list "$TMPCSV"
assert_equals "6" "${#ALL_SCENE_IDS[@]}" "build_scene_list: excludes merged scenes"
rm -f "$TMPCSV"

# Test that stub scenes (below MIN_SCENE_WORDS) are excluded
TMPCSV="${TMPDIR}/scenes-stub.csv"
cp "$METADATA_CSV" "$TMPCSV"
echo "stub-scene|7|Stub Scene|1|Someone|Somewhere|1|morning||character|drafted|3|500" >> "$TMPCSV"
build_scene_list "$TMPCSV"
assert_equals "6" "${#ALL_SCENE_IDS[@]}" "build_scene_list: excludes scenes below MIN_SCENE_WORDS"
rm -f "$TMPCSV"

# Test that MIN_SCENE_WORDS threshold is respected
TMPCSV="${TMPDIR}/scenes-threshold.csv"
cp "$METADATA_CSV" "$TMPCSV"
echo "short-scene|7|Short Scene|1|Someone|Somewhere|1|morning||character|drafted|51|500" >> "$TMPCSV"
build_scene_list "$TMPCSV"
assert_equals "7" "${#ALL_SCENE_IDS[@]}" "build_scene_list: includes scenes at MIN_SCENE_WORDS+1"
rm -f "$TMPCSV"

# Restore for subsequent tests
build_scene_list "$METADATA_CSV"

# ============================================================================
# apply_scene_filter — all
# ============================================================================

echo "--- apply_scene_filter: all ---"

apply_scene_filter "$METADATA_CSV" "all"
assert_equals "6" "${#FILTERED_IDS[@]}" "filter all: returns all scenes"

# ============================================================================
# apply_scene_filter — scenes (comma-separated)
# ============================================================================

echo "--- apply_scene_filter: scenes ---"

apply_scene_filter "$METADATA_CSV" "scenes" "act1-sc01,new-x1"
assert_equals "2" "${#FILTERED_IDS[@]}" "filter scenes: finds 2 requested"
assert_equals "act1-sc01" "${FILTERED_IDS[0]}" "filter scenes: first match"
assert_equals "new-x1" "${FILTERED_IDS[1]}" "filter scenes: second match"

# ============================================================================
# apply_scene_filter — single
# ============================================================================

echo "--- apply_scene_filter: single ---"

apply_scene_filter "$METADATA_CSV" "single" "new-x1"
assert_equals "1" "${#FILTERED_IDS[@]}" "filter single: finds one scene"
assert_equals "new-x1" "${FILTERED_IDS[0]}" "filter single: correct ID"

# ============================================================================
# apply_scene_filter — act (CSV part column)
# ============================================================================

echo "--- apply_scene_filter: act ---"

apply_scene_filter "$METADATA_CSV" "act" "1"
assert_equals "3" "${#FILTERED_IDS[@]}" "filter act 1: finds 3 scenes in part 1"

apply_scene_filter "$METADATA_CSV" "act" "2"
assert_equals "3" "${#FILTERED_IDS[@]}" "filter act 2: finds 3 scenes in part 2"
assert_equals "act2-sc01" "${FILTERED_IDS[0]}" "filter act 2: correct first ID"

# ============================================================================
# apply_scene_filter — from_seq (single number = onward)
# ============================================================================

echo "--- apply_scene_filter: from_seq (onward) ---"

apply_scene_filter "$METADATA_CSV" "from_seq" "3"
assert_equals "4" "${#FILTERED_IDS[@]}" "filter from_seq 3: finds scenes with seq >= 3"
assert_equals "new-x1" "${FILTERED_IDS[0]}" "filter from_seq 3: first match is seq 3"
assert_equals "act2-sc01" "${FILTERED_IDS[1]}" "filter from_seq 3: second match is seq 4"

apply_scene_filter "$METADATA_CSV" "from_seq" "1"
assert_equals "6" "${#FILTERED_IDS[@]}" "filter from_seq 1: finds all scenes"

# ============================================================================
# apply_scene_filter — from_seq (range N-M)
# ============================================================================

echo "--- apply_scene_filter: from_seq (range) ---"

apply_scene_filter "$METADATA_CSV" "from_seq" "2-3"
assert_equals "2" "${#FILTERED_IDS[@]}" "filter from_seq 2-3: finds scenes with seq 2-3"
assert_equals "act1-sc02" "${FILTERED_IDS[0]}" "filter from_seq 2-3: first is seq 2"
assert_equals "new-x1" "${FILTERED_IDS[1]}" "filter from_seq 2-3: second is seq 3"

apply_scene_filter "$METADATA_CSV" "from_seq" "1-1"
assert_equals "1" "${#FILTERED_IDS[@]}" "filter from_seq 1-1: single scene in range"
assert_equals "act1-sc01" "${FILTERED_IDS[0]}" "filter from_seq 1-1: correct scene"

apply_scene_filter "$METADATA_CSV" "from_seq" "1-6"
assert_equals "6" "${#FILTERED_IDS[@]}" "filter from_seq 1-6: all scenes in range"

# ============================================================================
# apply_scene_filter — range (by position / scene IDs)
# ============================================================================

echo "--- apply_scene_filter: range ---"

apply_scene_filter "$METADATA_CSV" "range" "act1-sc02" "new-x1"
assert_equals "2" "${#FILTERED_IDS[@]}" "filter range: finds 2 scenes in positional range"
assert_equals "act1-sc02" "${FILTERED_IDS[0]}" "filter range: start scene"
assert_equals "new-x1" "${FILTERED_IDS[1]}" "filter range: end scene"
