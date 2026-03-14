#!/bin/bash
# test-prompt-builder.sh — Tests for scripts/lib/prompt-builder.sh
#
# Run via: ./tests/run-tests.sh
# Depends on: FIXTURE_DIR, PROJECT_DIR, assertion functions (from run-tests.sh)

# ============================================================================
# get_scene_metadata
# ============================================================================

# Known scene returns its YAML block
result=$(get_scene_metadata "act1-sc01" "$FIXTURE_DIR")
assert_contains "$result" "id: act1-sc01" "get_scene_metadata: contains scene id"
assert_contains "$result" "The Finest Cartographer" "get_scene_metadata: contains title"
assert_contains "$result" "Dorren Hayle" "get_scene_metadata: contains pov"

# Second scene
result=$(get_scene_metadata "act1-sc02" "$FIXTURE_DIR")
assert_contains "$result" "id: act1-sc02" "get_scene_metadata: act1-sc02 id"
assert_contains "$result" "The Missing Village" "get_scene_metadata: act1-sc02 title"

# Last scene (no trailing entry to delimit)
result=$(get_scene_metadata "act2-sc01" "$FIXTURE_DIR")
assert_contains "$result" "id: act2-sc01" "get_scene_metadata: act2-sc01 id"
assert_contains "$result" "Into the Blank" "get_scene_metadata: act2-sc01 title"

# Nonexistent scene returns empty
result=$(get_scene_metadata "act9-sc99" "$FIXTURE_DIR")
assert_empty "$result" "get_scene_metadata: nonexistent scene returns empty"

# ============================================================================
# get_previous_scene
# ============================================================================

# First scene has no previous
result=$(get_previous_scene "act1-sc01" "$FIXTURE_DIR")
assert_empty "$result" "get_previous_scene: first scene returns empty"

# Second scene returns first
result=$(get_previous_scene "act1-sc02" "$FIXTURE_DIR")
assert_equals "act1-sc01" "$result" "get_previous_scene: act1-sc02 -> act1-sc01"

# Cross-part scene returns preceding scene
result=$(get_previous_scene "act2-sc01" "$FIXTURE_DIR")
assert_equals "new-x1" "$result" "get_previous_scene: act2-sc01 -> new-x1"

# Nonexistent scene returns empty
result=$(get_previous_scene "act9-sc99" "$FIXTURE_DIR")
assert_empty "$result" "get_previous_scene: nonexistent returns empty"

# ============================================================================
# list_reference_files
# ============================================================================

result=$(list_reference_files "$FIXTURE_DIR")
assert_contains "$result" "reference/character-bible.md" "list_reference_files: character-bible"
assert_contains "$result" "reference/voice-guide.md" "list_reference_files: voice-guide"
assert_contains "$result" "reference/continuity-tracker.md" "list_reference_files: continuity-tracker"
assert_contains "$result" "reference/key-decisions.md" "list_reference_files: key-decisions"

# Should be sorted (chapter-map.csv sorts before character-bible.md)
first_line=$(echo "$result" | head -1)
assert_equals "reference/chapter-map.csv" "$first_line" "list_reference_files: sorted (chapter-map first)"

# ============================================================================
# read_scene_field
# ============================================================================

result=$(read_scene_field "act1-sc01" "$FIXTURE_DIR" "title")
assert_equals "The Finest Cartographer" "$result" "read_scene_field: title"

result=$(read_scene_field "act1-sc01" "$FIXTURE_DIR" "pov")
assert_equals "Dorren Hayle" "$result" "read_scene_field: pov"

result=$(read_scene_field "act1-sc01" "$FIXTURE_DIR" "target_words")
assert_equals "2500" "$result" "read_scene_field: target_words"

# ============================================================================
# get_scene_status
# ============================================================================

# act1-sc01 has status in frontmatter -> "drafted"
result=$(get_scene_status "act1-sc01" "$FIXTURE_DIR")
assert_equals "drafted" "$result" "get_scene_status: act1-sc01 from frontmatter"

# act1-sc02 has status "drafted" in scene-index.yaml
result=$(get_scene_status "act1-sc02" "$FIXTURE_DIR")
assert_equals "drafted" "$result" "get_scene_status: act1-sc02 from scene-index"

# ============================================================================
# build_scene_prompt
# ============================================================================

prompt=$(build_scene_prompt "act1-sc01" "$FIXTURE_DIR")

# Contains project info
assert_contains "$prompt" "The Cartographer's Silence" "build_scene_prompt: contains title"
assert_contains "$prompt" "fantasy" "build_scene_prompt: contains genre"

# Contains scene metadata
assert_contains "$prompt" "act1-sc01" "build_scene_prompt: contains scene id"
assert_contains "$prompt" "The Finest Cartographer" "build_scene_prompt: contains scene title"

# Contains reference files
assert_contains "$prompt" "reference/voice-guide.md" "build_scene_prompt: references voice guide"
assert_contains "$prompt" "reference/character-bible.md" "build_scene_prompt: references character bible"

# Contains craft principles
assert_contains "$prompt" "CRAFT PRINCIPLES" "build_scene_prompt: has craft principles section"

# Contains previous scene instruction (first scene = no previous)
assert_contains "$prompt" "first scene" "build_scene_prompt: sc01 says first scene"

# Contains step structure
assert_contains "$prompt" "STEP 1:" "build_scene_prompt: has step 1"
assert_contains "$prompt" "STEP 4: DRAFT" "build_scene_prompt: has step 4"
assert_contains "$prompt" "STEP 8: GIT COMMIT" "build_scene_prompt: has step 8"

# Contains target words
assert_contains "$prompt" "2500" "build_scene_prompt: contains target_words"

# Second scene references previous
prompt2=$(build_scene_prompt "act1-sc02" "$FIXTURE_DIR")
assert_contains "$prompt2" "scenes/act1-sc01.md" "build_scene_prompt: sc02 references previous scene"

# Cross-part scene references correct previous
prompt3=$(build_scene_prompt "act2-sc01" "$FIXTURE_DIR")
assert_contains "$prompt3" "scenes/new-x1.md" "build_scene_prompt: act2-sc01 references new-x1"

# ============================================================================
# build_weighted_directive
# ============================================================================

# Returns error (1) when no weights file exists
_bwd_result=$(build_weighted_directive "$FIXTURE_DIR" 2>/dev/null; echo "EXIT:$?")
_bwd_exit=$(echo "$_bwd_result" | tail -1 | sed 's/EXIT://')
assert_equals "1" "$_bwd_exit" "build_weighted_directive: returns 1 when no weights file"

# Setup: create a weights file in the fixture
mkdir -p "${FIXTURE_DIR}/working"
cat > "${FIXTURE_DIR}/working/craft-weights.csv" <<'WCSV'
section|principle|weight|author_weight|notes
scene_craft|every_scene_must_turn|7||
scene_craft|enter_late_leave_early|5||
prose_craft|economy_clarity|5||
character_craft|want_need|6||
rules|write_what_you_know|3||
narrative|kishotenketsu|3||
scene_craft|pacing_variety|8|9|author boosted
WCSV

# Returns output when weights file exists
_bwd_output=$(build_weighted_directive "$FIXTURE_DIR")
_bwd_rc=$?
assert_equals "0" "$_bwd_rc" "build_weighted_directive: returns 0 when weights file exists"
assert_not_empty "$_bwd_output" "build_weighted_directive: produces output"

# High-weight principles appear
assert_contains "$_bwd_output" "every scene must turn" "build_weighted_directive: high-weight principle listed"
assert_contains "$_bwd_output" "pacing variety" "build_weighted_directive: author-boosted principle listed"
assert_contains "$_bwd_output" "priority: 9/10" "build_weighted_directive: author_weight overrides weight"

# Medium-weight principles appear in awareness list
assert_contains "$_bwd_output" "enter late leave early" "build_weighted_directive: medium principle in awareness"
assert_contains "$_bwd_output" "want need" "build_weighted_directive: medium principle (6) in awareness"

# Low-weight principles (<=3) do NOT appear
assert_not_contains "$_bwd_output" "write what you know" "build_weighted_directive: low-weight excluded"
assert_not_contains "$_bwd_output" "kishotenketsu" "build_weighted_directive: low-weight excluded (3)"

# ============================================================================
# get_scene_overrides
# ============================================================================

# Returns empty when no overrides file
_ov_result=$(get_scene_overrides "act1-sc01" "$FIXTURE_DIR")
assert_empty "$_ov_result" "get_scene_overrides: empty when no overrides file"

# Setup: create overrides file
mkdir -p "${FIXTURE_DIR}/working/scores/latest"
cat > "${FIXTURE_DIR}/working/scores/latest/overrides.csv" <<'OCSV'
id|pass|instruction
act1-sc01|voice|Tighten Dorren's internal monologue
act1-sc01|pacing|Reduce exposition in opening paragraph
act1-sc02|voice|More sensory detail needed
OCSV

_ov_result=$(get_scene_overrides "act1-sc01" "$FIXTURE_DIR")
assert_contains "$_ov_result" "Tighten Dorren" "get_scene_overrides: returns matching override"
assert_contains "$_ov_result" "Reduce exposition" "get_scene_overrides: returns second override"
assert_not_contains "$_ov_result" "sensory detail" "get_scene_overrides: excludes other scenes"

# ============================================================================
# build_scene_prompt with weighted directives
# ============================================================================

# With craft-weights.csv present, build_scene_prompt should use weighted directive
_wp=$(build_scene_prompt "act1-sc01" "$FIXTURE_DIR")
assert_contains "$_wp" "Craft Priorities" "build_scene_prompt: uses weighted directive when weights exist"
assert_contains "$_wp" "every scene must turn" "build_scene_prompt: weighted principle in prompt"

# Scene-specific overrides should be included
assert_contains "$_wp" "Scene-Specific Notes" "build_scene_prompt: includes scene overrides section"
assert_contains "$_wp" "Tighten Dorren" "build_scene_prompt: includes override instruction"

# Cleanup fixture additions
rm -f "${FIXTURE_DIR}/working/craft-weights.csv"
rm -rf "${FIXTURE_DIR}/working/scores"
