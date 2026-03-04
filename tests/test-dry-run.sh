#!/bin/bash
# test-dry-run.sh — Integration tests for --dry-run modes
#
# Run via: ./tests/run-tests.sh
# Tests that storyforge-write, storyforge-evaluate, and storyforge-revise
# build correct prompts in dry-run mode without invoking Claude or modifying files.
#
# Depends on: FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, assertion functions (from run-tests.sh)

# ============================================================================
# Helper: capture script output in dry-run mode
# ============================================================================

# The scripts call detect_project_root() which walks up from $PWD.
# We need to be inside the fixture project for that to work.
# Also, scripts use `set -euo pipefail` so we need to handle errors.

run_dry_run() {
    local script="$1"
    shift
    (
        cd "$FIXTURE_DIR"
        bash "${PLUGIN_DIR}/scripts/${script}" --dry-run "$@" 2>/dev/null
    )
}

# ============================================================================
# storyforge-write --dry-run
# ============================================================================

# Dry-run a single scene
result=$(run_dry_run "storyforge-write" act1-sc01)
rc=$?

assert_exit_code "0" "$rc" "write dry-run: exits 0"
assert_contains "$result" "DRY RUN: act1-sc01" "write dry-run: has dry-run header"
assert_contains "$result" "END DRY RUN: act1-sc01" "write dry-run: has dry-run footer"
assert_contains "$result" "The Cartographer's Silence" "write dry-run: prompt contains title"
assert_contains "$result" "STEP 1:" "write dry-run: prompt has step structure"
assert_contains "$result" "CRAFT PRINCIPLES" "write dry-run: prompt has craft principles"
assert_contains "$result" "reference/voice-guide.md" "write dry-run: prompt references voice guide"

# Dry-run doesn't modify scene files
before_mtime=$(stat -f %m "${FIXTURE_DIR}/scenes/act1-sc01.md" 2>/dev/null || stat -c %Y "${FIXTURE_DIR}/scenes/act1-sc01.md" 2>/dev/null)
result=$(run_dry_run "storyforge-write" act1-sc01)
after_mtime=$(stat -f %m "${FIXTURE_DIR}/scenes/act1-sc01.md" 2>/dev/null || stat -c %Y "${FIXTURE_DIR}/scenes/act1-sc01.md" 2>/dev/null)
assert_equals "$before_mtime" "$after_mtime" "write dry-run: does not modify scene files"

# ============================================================================
# storyforge-revise --dry-run
# ============================================================================

result=$(run_dry_run "storyforge-revise")
rc=$?

assert_exit_code "0" "$rc" "revise dry-run: exits 0"
assert_contains "$result" "DRY RUN: prose-tightening" "revise dry-run: has prose pass header"
assert_contains "$result" "DRY RUN: character-arc-deepening" "revise dry-run: has character pass header"
assert_contains "$result" "Revision Pass:" "revise dry-run: prompt has pass title"
assert_contains "$result" "Purpose" "revise dry-run: prompt has purpose section"
assert_contains "$result" "Scope" "revise dry-run: prompt has scope section"
assert_contains "$result" "Craft Principles" "revise dry-run: prompt has craft principles"
assert_contains "$result" "Instructions" "revise dry-run: prompt has instructions"

# Verify prose pass gets correct craft sections
assert_contains "$result" "Prose Craft" "revise dry-run: prose pass includes Prose Craft"
# Verify character pass gets correct craft sections
assert_contains "$result" "Character Craft" "revise dry-run: character pass includes Character Craft"

# Plan file should not be modified
plan_content=$(cat "${FIXTURE_DIR}/working/plans/revision-plan.yaml")
assert_contains "$plan_content" 'status: "pending"' "revise dry-run: plan status unchanged"

# ============================================================================
# storyforge-evaluate --dry-run
# ============================================================================

result=$(run_dry_run "storyforge-evaluate")
rc=$?

assert_exit_code "0" "$rc" "evaluate dry-run: exits 0"
assert_contains "$result" "DRY RUN: developmental-editor" "evaluate dry-run: has dev-editor evaluator"
assert_contains "$result" "DRY RUN: line-editor" "evaluate dry-run: has line-editor evaluator"
assert_contains "$result" "DRY RUN: literary-agent" "evaluate dry-run: has literary-agent evaluator"
assert_contains "$result" "DRY RUN: first-reader" "evaluate dry-run: has first-reader evaluator"
assert_contains "$result" "DRY RUN: genre-expert" "evaluate dry-run: has genre-expert evaluator"
assert_contains "$result" "DRY RUN: writing-coach" "evaluate dry-run: has writing-coach evaluator"
assert_contains "$result" "DRY RUN: synthesis" "evaluate dry-run: has synthesis section"
assert_contains "$result" "The Cartographer's Silence" "evaluate dry-run: prompt contains title"
assert_contains "$result" "scenes/act1-sc01.md" "evaluate dry-run: prompt lists scene files"

# Evaluate dry-run should not create new evaluation directories
eval_dirs_before=$(ls -d "${FIXTURE_DIR}/working/evaluations/"*/ 2>/dev/null | wc -l | tr -d ' ')
run_dry_run "storyforge-evaluate" >/dev/null
eval_dirs_after=$(ls -d "${FIXTURE_DIR}/working/evaluations/"*/ 2>/dev/null | wc -l | tr -d ' ')
assert_equals "$eval_dirs_before" "$eval_dirs_after" "evaluate dry-run: does not create new eval directory"
