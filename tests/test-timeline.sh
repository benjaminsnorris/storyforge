#!/bin/bash
# test-timeline.sh — Tests for storyforge-timeline

# ============================================================================
# Fixtures are already available via run-tests.sh:
#   $FIXTURE_DIR = tests/fixtures/test-project
#   $PLUGIN_DIR  = repo root
#   $TMPDIR      = temp directory (cleaned up automatically)
#   Libraries (common.sh, csv.sh, scene-filter.sh) are already sourced
# ============================================================================

METADATA_CSV="${FIXTURE_DIR}/reference/scene-metadata.csv"

# --- Make a working copy so we don't pollute fixtures ---
TEST_META="${TMPDIR}/scene-metadata.csv"
cp "$METADATA_CSV" "$TEST_META"

# ============================================================================
# Scene list integration
# ============================================================================

build_scene_list "$TEST_META"
assert_not_empty "${ALL_SCENE_IDS[*]}" "timeline: scene list is populated"

apply_scene_filter "$TEST_META" "all"
assert_equals "4" "${#FILTERED_IDS[@]}" "timeline: all filter returns all scenes"

apply_scene_filter "$TEST_META" "act" "1"
assert_equals "3" "${#FILTERED_IDS[@]}" "timeline: act 1 filter returns 3 scenes"

apply_scene_filter "$TEST_META" "act" "2"
assert_equals "1" "${#FILTERED_IDS[@]}" "timeline: act 2 filter returns 1 scene"

# ============================================================================
# Timeline CSV field operations
# ============================================================================

# Read existing timeline_day
RESULT=$(get_csv_field "$TEST_META" "act1-sc01" "timeline_day")
assert_equals "1" "$RESULT" "timeline: reads existing timeline_day"

# Update timeline_day
update_csv_field "$TEST_META" "act2-sc01" "timeline_day" "5"
RESULT=$(get_csv_field "$TEST_META" "act2-sc01" "timeline_day")
assert_equals "5" "$RESULT" "timeline: updates timeline_day in CSV"

# Overwrite existing
update_csv_field "$TEST_META" "act1-sc01" "timeline_day" "99"
RESULT=$(get_csv_field "$TEST_META" "act1-sc01" "timeline_day")
assert_equals "99" "$RESULT" "timeline: overwrites existing timeline_day"

# ============================================================================
# Indicator parsing — TIMELINE: CSV block
# ============================================================================

MOCK_RESPONSE='Some preamble text here.

TIMELINE:
id|timeline_day
act1-sc01|1
act1-sc02|1
new-x1|2
act2-sc01|3

Some trailing text.'

# Reset test CSV
cp "$METADATA_CSV" "$TEST_META"

# Parse with FORCE=true
ASSIGNED=0
SKIPPED=0
FORCE=true
in_block=false
while IFS= read -r line; do
    if [[ "$line" == "TIMELINE:" ]]; then
        in_block=true
        continue
    fi
    [[ "$in_block" != true ]] && continue
    [[ "$line" == "id|timeline_day" ]] && continue
    [[ -z "$line" ]] && continue
    [[ "$line" == *":"* && "$line" != *"|"* ]] && break

    scene_id=$(echo "$line" | cut -d'|' -f1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    day_val=$(echo "$line" | cut -d'|' -f2 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

    if [[ "$day_val" =~ ^[0-9]+$ ]] && (( day_val > 0 )); then
        existing=$(get_csv_field "$TEST_META" "$scene_id" "timeline_day")
        if [[ -n "$existing" && "$FORCE" != true ]]; then
            SKIPPED=$((SKIPPED + 1))
        else
            update_csv_field "$TEST_META" "$scene_id" "timeline_day" "$day_val"
            ASSIGNED=$((ASSIGNED + 1))
        fi
    fi
done <<< "$MOCK_RESPONSE"

assert_equals "4" "$ASSIGNED" "timeline: parses all 4 timeline entries with force"
assert_equals "0" "$SKIPPED" "timeline: skips 0 with force"

RESULT=$(get_csv_field "$TEST_META" "act1-sc01" "timeline_day")
assert_equals "1" "$RESULT" "timeline: assigns day 1 to act1-sc01"

RESULT=$(get_csv_field "$TEST_META" "new-x1" "timeline_day")
assert_equals "2" "$RESULT" "timeline: assigns day 2 to new-x1"

RESULT=$(get_csv_field "$TEST_META" "act2-sc01" "timeline_day")
assert_equals "3" "$RESULT" "timeline: assigns day 3 to act2-sc01"

# ============================================================================
# Indicator parsing — skip without force
# ============================================================================

cp "$METADATA_CSV" "$TEST_META"

ASSIGNED=0
SKIPPED=0
FORCE=false
in_block=false
while IFS= read -r line; do
    if [[ "$line" == "TIMELINE:" ]]; then
        in_block=true
        continue
    fi
    [[ "$in_block" != true ]] && continue
    [[ "$line" == "id|timeline_day" ]] && continue
    [[ -z "$line" ]] && continue
    [[ "$line" == *":"* && "$line" != *"|"* ]] && break

    scene_id=$(echo "$line" | cut -d'|' -f1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    day_val=$(echo "$line" | cut -d'|' -f2 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

    if [[ "$day_val" =~ ^[0-9]+$ ]] && (( day_val > 0 )); then
        existing=$(get_csv_field "$TEST_META" "$scene_id" "timeline_day")
        if [[ -n "$existing" && "$FORCE" != true ]]; then
            SKIPPED=$((SKIPPED + 1))
        else
            update_csv_field "$TEST_META" "$scene_id" "timeline_day" "$day_val"
            ASSIGNED=$((ASSIGNED + 1))
        fi
    fi
done <<< "$MOCK_RESPONSE"

# All 4 scenes in fixture have existing timeline_day values
assert_equals "0" "$ASSIGNED" "timeline: no-force skips existing values"
assert_equals "4" "$SKIPPED" "timeline: counts 4 skipped without force"

# ============================================================================
# Indicator parsing — mixed (some empty, some set)
# ============================================================================

cp "$METADATA_CSV" "$TEST_META"
# Clear timeline_day for act2-sc01
update_csv_field "$TEST_META" "act2-sc01" "timeline_day" ""

ASSIGNED=0
SKIPPED=0
FORCE=false
in_block=false
while IFS= read -r line; do
    if [[ "$line" == "TIMELINE:" ]]; then
        in_block=true
        continue
    fi
    [[ "$in_block" != true ]] && continue
    [[ "$line" == "id|timeline_day" ]] && continue
    [[ -z "$line" ]] && continue
    [[ "$line" == *":"* && "$line" != *"|"* ]] && break

    scene_id=$(echo "$line" | cut -d'|' -f1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    day_val=$(echo "$line" | cut -d'|' -f2 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

    if [[ "$day_val" =~ ^[0-9]+$ ]] && (( day_val > 0 )); then
        existing=$(get_csv_field "$TEST_META" "$scene_id" "timeline_day")
        if [[ -n "$existing" && "$FORCE" != true ]]; then
            SKIPPED=$((SKIPPED + 1))
        else
            update_csv_field "$TEST_META" "$scene_id" "timeline_day" "$day_val"
            ASSIGNED=$((ASSIGNED + 1))
        fi
    fi
done <<< "$MOCK_RESPONSE"

assert_equals "1" "$ASSIGNED" "timeline: assigns 1 empty scene without force"
assert_equals "3" "$SKIPPED" "timeline: skips 3 existing without force"

# ============================================================================
# Invalid day values are rejected
# ============================================================================

MOCK_BAD='TIMELINE:
id|timeline_day
act1-sc01|0
act1-sc02|-1
new-x1|abc
act2-sc01|3'

cp "$METADATA_CSV" "$TEST_META"
ASSIGNED=0
FORCE=true
in_block=false
while IFS= read -r line; do
    if [[ "$line" == "TIMELINE:" ]]; then
        in_block=true
        continue
    fi
    [[ "$in_block" != true ]] && continue
    [[ "$line" == "id|timeline_day" ]] && continue
    [[ -z "$line" ]] && continue
    [[ "$line" == *":"* && "$line" != *"|"* ]] && break

    scene_id=$(echo "$line" | cut -d'|' -f1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    day_val=$(echo "$line" | cut -d'|' -f2 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

    if [[ "$day_val" =~ ^[0-9]+$ ]] && (( day_val > 0 )); then
        update_csv_field "$TEST_META" "$scene_id" "timeline_day" "$day_val"
        ASSIGNED=$((ASSIGNED + 1))
    fi
done <<< "$MOCK_BAD"

assert_equals "1" "$ASSIGNED" "timeline: rejects 0, negative, and non-numeric day values"

# ============================================================================
# Haiku indicator extraction parsing
# ============================================================================

HAIKU_RESPONSE='Here is my analysis of the temporal indicators in this scene.

INDICATORS: "the next morning", wakes up, breakfast, "three days later"'

indicators=$(echo "$HAIKU_RESPONSE" | grep -i "^INDICATORS:" | sed 's/^INDICATORS:[[:space:]]*//' | head -1 || true)
assert_not_empty "$indicators" "timeline: parses INDICATORS line from Haiku response"
assert_contains "$indicators" "the next morning" "timeline: extracts quoted time reference"
assert_contains "$indicators" "wakes up" "timeline: extracts sleep/wake indicator"
assert_contains "$indicators" "breakfast" "timeline: extracts meal reference"

# No indicators
HAIKU_EMPTY='I found no temporal indicators in this scene.

INDICATORS: (none)'

indicators=$(echo "$HAIKU_EMPTY" | grep -i "^INDICATORS:" | sed 's/^INDICATORS:[[:space:]]*//' | head -1 || true)
assert_equals "(none)" "$indicators" "timeline: handles (none) indicator response"

# ============================================================================
# Model selection
# ============================================================================

RESULT=$(select_model "extraction")
assert_equals "claude-haiku-4-5-20251001" "$RESULT" "timeline: select_model extraction returns haiku"

RESULT=$(select_model "evaluation")
assert_contains "$RESULT" "sonnet" "timeline: select_model evaluation returns sonnet"
