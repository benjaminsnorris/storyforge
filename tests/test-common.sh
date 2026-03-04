#!/bin/bash
# test-common.sh — Tests for scripts/lib/common.sh
#
# Run via: ./tests/run-tests.sh
# Depends on: FIXTURE_DIR, PROJECT_DIR, assertion functions (from run-tests.sh)

# ============================================================================
# read_yaml_field
# ============================================================================

# Dotted key: project.title
result=$(read_yaml_field "project.title")
assert_equals "The Cartographer's Silence" "$result" "read_yaml_field: project.title"

# Dotted key: project.genre
result=$(read_yaml_field "project.genre")
assert_equals "fantasy" "$result" "read_yaml_field: project.genre"

# Dotted key: project.target_words
result=$(read_yaml_field "project.target_words")
assert_equals "90000" "$result" "read_yaml_field: project.target_words"

# Top-level key: phase
result=$(read_yaml_field "phase")
assert_equals "drafting" "$result" "read_yaml_field: phase (top-level)"

# Nonexistent key returns empty
result=$(read_yaml_field "nonexistent")
assert_empty "$result" "read_yaml_field: nonexistent key returns empty"

# Nonexistent dotted key returns empty
result=$(read_yaml_field "project.nonexistent")
assert_empty "$result" "read_yaml_field: nonexistent dotted key returns empty"

# ============================================================================
# detect_project_root
# ============================================================================

# Run detect_project_root from a subdirectory of the fixture
(
    cd "${FIXTURE_DIR}/scenes"
    detect_project_root
    assert_equals "$FIXTURE_DIR" "$PROJECT_DIR" "detect_project_root: finds root from subdirectory"
)

# Restore PROJECT_DIR after the subshell test
export PROJECT_DIR="$FIXTURE_DIR"

# ============================================================================
# check_file_exists
# ============================================================================

# Existing file should not exit
(check_file_exists "reference/voice-guide.md" "Voice guide" 2>/dev/null)
assert_exit_code "0" "$?" "check_file_exists: existing file succeeds"

# Missing file should exit with error (run in subshell to catch exit)
(check_file_exists "reference/nonexistent.md" "Missing file" 2>/dev/null)
assert_exit_code "1" "$?" "check_file_exists: missing file exits 1"

# ============================================================================
# get_plugin_dir
# ============================================================================

result=$(get_plugin_dir)
assert_equals "$PLUGIN_DIR" "$result" "get_plugin_dir: returns plugin root"

# ============================================================================
# extract_craft_sections
# ============================================================================

# Single section (section 2: Scene Craft)
result=$(extract_craft_sections 2)
assert_contains "$result" "## 2. Scene Craft" "extract_craft_sections: section 2 header"
assert_contains "$result" "Enter Late" "extract_craft_sections: section 2 content"

# Multiple sections with separators
result=$(extract_craft_sections 2 3 5)
assert_contains "$result" "## 2. Scene Craft" "extract_craft_sections: multi — section 2 present"
assert_contains "$result" "## 3. Prose Craft" "extract_craft_sections: multi — section 3 present"
assert_contains "$result" "## 5. The Rules" "extract_craft_sections: multi — section 5 present"
assert_contains "$result" "---" "extract_craft_sections: multi — separator present"

# Nonexistent section (99) returns empty content
result=$(extract_craft_sections 99)
assert_empty "$result" "extract_craft_sections: section 99 returns empty"

# No arguments returns empty
result=$(extract_craft_sections)
assert_empty "$result" "extract_craft_sections: no args returns empty"

# ============================================================================
# log
# ============================================================================

# log writes to stdout
result=$(log "test message")
assert_contains "$result" "test message" "log: outputs message"
assert_matches "$result" '^\[20[0-9]{2}-' "log: includes timestamp"
