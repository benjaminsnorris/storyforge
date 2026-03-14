#!/bin/bash
# test-revision-passes.sh — Tests for scripts/lib/revision-passes.sh
#
# Run via: ./tests/run-tests.sh
# Depends on: FIXTURE_DIR, PROJECT_DIR, assertion functions (from run-tests.sh)

# ============================================================================
# resolve_scope
# ============================================================================

# Full scope returns all scene files
result=$(resolve_scope "full" "$FIXTURE_DIR" 2>/dev/null)
assert_contains "$result" "act1-sc01.md" "resolve_scope full: contains act1-sc01"
assert_contains "$result" "act1-sc02.md" "resolve_scope full: contains act1-sc02"
assert_contains "$result" "act2-sc01.md" "resolve_scope full: contains act2-sc01"
assert_contains "$result" "new-x1.md" "resolve_scope full: contains new-x1"
count=$(echo "$result" | wc -l | tr -d ' ')
assert_equals "4" "$count" "resolve_scope full: returns 4 files"

# Act-level scope (now uses CSV part column, not ID prefix)
result=$(resolve_scope "act-1" "$FIXTURE_DIR" 2>/dev/null)
assert_contains "$result" "act1-sc01.md" "resolve_scope act-1: contains act1-sc01"
assert_contains "$result" "act1-sc02.md" "resolve_scope act-1: contains act1-sc02"
assert_contains "$result" "new-x1.md" "resolve_scope act-1: contains new-x1 (part=1)"
assert_not_contains "$result" "act2-sc01.md" "resolve_scope act-1: excludes act2"
count=$(echo "$result" | wc -l | tr -d ' ')
assert_equals "3" "$count" "resolve_scope act-1: returns 3 files"

# Act 2
result=$(resolve_scope "act-2" "$FIXTURE_DIR" 2>/dev/null)
assert_contains "$result" "act2-sc01.md" "resolve_scope act-2: contains act2-sc01"
assert_not_contains "$result" "act1-sc01.md" "resolve_scope act-2: excludes act1"
count=$(echo "$result" | wc -l | tr -d ' ')
assert_equals "1" "$count" "resolve_scope act-2: returns 1 file"

# Comma-separated IDs
result=$(resolve_scope "act1-sc01,act2-sc01" "$FIXTURE_DIR" 2>/dev/null)
assert_contains "$result" "act1-sc01.md" "resolve_scope comma: contains act1-sc01"
assert_contains "$result" "act2-sc01.md" "resolve_scope comma: contains act2-sc01"
assert_not_contains "$result" "act1-sc02.md" "resolve_scope comma: excludes act1-sc02"
count=$(echo "$result" | wc -l | tr -d ' ')
assert_equals "2" "$count" "resolve_scope comma: returns 2 files"

# Nonexistent scope returns error
result=$(resolve_scope "act-99" "$FIXTURE_DIR" 2>/dev/null)
rc=$?
assert_exit_code "1" "$rc" "resolve_scope: nonexistent act returns error"

# Part-level scope: part-1 includes all scenes under PART 1 header
result=$(resolve_scope "part-1" "$FIXTURE_DIR" 2>/dev/null)
assert_contains "$result" "act1-sc01.md" "resolve_scope part-1: contains act1-sc01"
assert_contains "$result" "act1-sc02.md" "resolve_scope part-1: contains act1-sc02"
assert_contains "$result" "new-x1.md" "resolve_scope part-1: contains new-x1"
assert_not_contains "$result" "act2-sc01.md" "resolve_scope part-1: excludes act2"
count=$(echo "$result" | wc -l | tr -d ' ')
assert_equals "3" "$count" "resolve_scope part-1: returns 3 files"

# Part-level scope: part-2 includes only scenes under PART 2 header
result=$(resolve_scope "part-2" "$FIXTURE_DIR" 2>/dev/null)
assert_contains "$result" "act2-sc01.md" "resolve_scope part-2: contains act2-sc01"
assert_not_contains "$result" "act1-sc01.md" "resolve_scope part-2: excludes act1"
assert_not_contains "$result" "new-x1.md" "resolve_scope part-2: excludes new-x1"
count=$(echo "$result" | wc -l | tr -d ' ')
assert_equals "1" "$count" "resolve_scope part-2: returns 1 file"

# Nonexistent part returns error
result=$(resolve_scope "part-99" "$FIXTURE_DIR" 2>/dev/null)
rc=$?
assert_exit_code "1" "$rc" "resolve_scope: nonexistent part returns error"

# ============================================================================
# resolve_scene_file — fallback for ID formatting mismatches
# ============================================================================

# Create temp project with numeric scene IDs
NUMERIC_TMPDIR=$(mktemp -d)
mkdir -p "${NUMERIC_TMPDIR}/scenes"
echo "test" > "${NUMERIC_TMPDIR}/scenes/9.md"
echo "test" > "${NUMERIC_TMPDIR}/scenes/13.md"
echo "test" > "${NUMERIC_TMPDIR}/scenes/0.md"

# Exact match works
result=$(resolve_scene_file "${NUMERIC_TMPDIR}/scenes" "9" 2>/dev/null)
assert_contains "$result" "9.md" "resolve_scene_file: exact match works"

# scene-09 falls back to 9.md
result=$(resolve_scene_file "${NUMERIC_TMPDIR}/scenes" "scene-09" 2>/dev/null)
assert_contains "$result" "9.md" "resolve_scene_file: scene-09 resolves to 9.md"

# scene-13 falls back to 13.md
result=$(resolve_scene_file "${NUMERIC_TMPDIR}/scenes" "scene-13" 2>/dev/null)
assert_contains "$result" "13.md" "resolve_scene_file: scene-13 resolves to 13.md"

# 09 (leading zero) falls back to 9.md
result=$(resolve_scene_file "${NUMERIC_TMPDIR}/scenes" "09" 2>/dev/null)
assert_contains "$result" "9.md" "resolve_scene_file: 09 resolves to 9.md"

# scene-0 falls back to 0.md
result=$(resolve_scene_file "${NUMERIC_TMPDIR}/scenes" "scene-0" 2>/dev/null)
assert_contains "$result" "0.md" "resolve_scene_file: scene-0 resolves to 0.md"

# Nonexistent returns empty
result=$(resolve_scene_file "${NUMERIC_TMPDIR}/scenes" "scene-999" 2>/dev/null)
assert_empty "$result" "resolve_scene_file: nonexistent returns empty"

# resolve_scope comma-separated with fallback
mkdir -p "${NUMERIC_TMPDIR}/reference"
cat > "${NUMERIC_TMPDIR}/reference/scene-metadata.csv" <<'CSV'
id|seq|title|pov|location|part|type|timeline_day|time_of_day|status|word_count|target_words
9|1|Chapter Nine||||||||||
13|2|Chapter Thirteen||||||||||
CSV
result=$(resolve_scope "scene-09,scene-13" "$NUMERIC_TMPDIR" 2>/dev/null)
assert_contains "$result" "9.md" "resolve_scope comma fallback: scene-09 resolves to 9.md"
assert_contains "$result" "13.md" "resolve_scope comma fallback: scene-13 resolves to 13.md"
count=$(echo "$result" | wc -l | tr -d ' ')
assert_equals "2" "$count" "resolve_scope comma fallback: returns 2 files"

rm -rf "$NUMERIC_TMPDIR"

# ============================================================================
# read_pass_guidance
# ============================================================================

# Pass 1 (prose-tightening) has guidance
result=$(read_pass_guidance 1 "$FIXTURE_DIR")
assert_contains "$result" "cartographic metaphor" "read_pass_guidance: pass 1 contains guidance"
assert_contains "$result" "Rationale:" "read_pass_guidance: pass 1 has rationale"

# Pass 2 (character-arc-deepening) has guidance
result=$(read_pass_guidance 2 "$FIXTURE_DIR")
assert_contains "$result" "emotional reveals subtle" "read_pass_guidance: pass 2 contains guidance"

# ============================================================================
# build_revision_prompt — keyword matching
# ============================================================================

# Prose pass → sections 3+5
result=$(build_revision_prompt "prose-tightening" "Cut filler, tighten sentences" "full" "$FIXTURE_DIR" "" 2>/dev/null)
assert_contains "$result" "## 3. Prose Craft" "build_revision_prompt prose: contains Prose Craft"
assert_contains "$result" "## 5. The Rules" "build_revision_prompt prose: contains Rules"
assert_not_contains "$result" "## 4. Character Craft" "build_revision_prompt prose: no Character Craft"
assert_not_contains "$result" "## 2. Scene Craft" "build_revision_prompt prose: no Scene Craft"

# Character pass → sections 4+5
result=$(build_revision_prompt "character-arc-deepening" "Deepen emotional arcs" "full" "$FIXTURE_DIR" "" 2>/dev/null)
assert_contains "$result" "## 4. Character Craft" "build_revision_prompt character: contains Character Craft"
assert_contains "$result" "## 5. The Rules" "build_revision_prompt character: contains Rules"
assert_not_contains "$result" "## 3. Prose Craft" "build_revision_prompt character: no Prose Craft"

# Structure pass → sections 1+2
result=$(build_revision_prompt "structure-reorder" "Fix pacing issues" "full" "$FIXTURE_DIR" "" 2>/dev/null)
assert_contains "$result" "## 1. Narrative Structure" "build_revision_prompt structure: contains Structure"
assert_contains "$result" "## 2. Scene Craft" "build_revision_prompt structure: contains Scene Craft"
assert_not_contains "$result" "## 3. Prose Craft" "build_revision_prompt structure: no Prose Craft"

# Continuity pass → no craft sections
result=$(build_revision_prompt "continuity-audit" "Check timeline consistency" "full" "$FIXTURE_DIR" "" 2>/dev/null)
assert_not_contains "$result" "Craft Principles for This Pass" "build_revision_prompt continuity: no craft section"

# Default → sections 2+3+5
result=$(build_revision_prompt "general-cleanup" "Miscellaneous cleanup" "full" "$FIXTURE_DIR" "" 2>/dev/null)
assert_contains "$result" "## 2. Scene Craft" "build_revision_prompt default: contains Scene Craft"
assert_contains "$result" "## 3. Prose Craft" "build_revision_prompt default: contains Prose Craft"
assert_contains "$result" "## 5. The Rules" "build_revision_prompt default: contains Rules"

# ============================================================================
# build_revision_prompt — pass config
# ============================================================================

config_block="name: test-pass
purpose: test
targets:
  - metric: word_count
    target: -10%"

result=$(build_revision_prompt "test-pass" "Test purpose" "full" "$FIXTURE_DIR" "$config_block" 2>/dev/null)
assert_contains "$result" "Pass Configuration" "build_revision_prompt: has config section"
assert_contains "$result" "word_count" "build_revision_prompt: config contains target"
assert_contains "$result" "Protection list" "build_revision_prompt: has protection list note"

# ============================================================================
# build_revision_prompt — structural content
# ============================================================================

result=$(build_revision_prompt "prose-tightening" "Tighten prose" "full" "$FIXTURE_DIR" "" 2>/dev/null)

# Has scope info
assert_contains "$result" "4 scene file" "build_revision_prompt: shows file count"

# Has instruction sections
assert_contains "$result" "Read Reference Context First" "build_revision_prompt: has instruction 1"
assert_contains "$result" "Read All In-Scope Scene Files" "build_revision_prompt: has instruction 2"
assert_contains "$result" "Apply the Revision" "build_revision_prompt: has instruction 3"
assert_contains "$result" "Preserve Voice" "build_revision_prompt: has instruction 4"
assert_contains "$result" "Maintain Continuity" "build_revision_prompt: has instruction 5"
assert_contains "$result" "Commit and Push" "build_revision_prompt: has instruction 6"
assert_contains "$result" "Post-Pass Summary" "build_revision_prompt: has instruction 7"

# Has the purpose embedded
assert_contains "$result" "Tighten prose" "build_revision_prompt: contains purpose"
