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
assert_contains "$result" "Scene Brief:" "write dry-run: prompt has scene brief section"
assert_contains "$result" "drafting a scene" "write dry-run: prompt has drafting instruction"
assert_contains "$result" "Voice Guide" "write dry-run: prompt references voice guide"

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

eval_result_file="${TMPDIR:-/tmp}/storyforge-eval-dry-run-$$.txt"
run_dry_run "storyforge-evaluate" > "$eval_result_file"
rc=$?

# Use file-based grep for evaluate dry-run since output can be ~75KB
# which causes SIGPIPE issues with echo|grep -q under pipefail
assert_exit_code "0" "$rc" "evaluate dry-run: exits 0"
_eval_file_contains() {
    grep -qF "$1" "$eval_result_file"
}
_eval_file_contains "DRY RUN: developmental-editor" && { PASS=$((PASS+1)); echo "  PASS: evaluate dry-run: has dev-editor evaluator"; } || { FAIL=$((FAIL+1)); echo "  FAIL: evaluate dry-run: has dev-editor evaluator"; }
_eval_file_contains "DRY RUN: line-editor" && { PASS=$((PASS+1)); echo "  PASS: evaluate dry-run: has line-editor evaluator"; } || { FAIL=$((FAIL+1)); echo "  FAIL: evaluate dry-run: has line-editor evaluator"; }
_eval_file_contains "DRY RUN: literary-agent" && { PASS=$((PASS+1)); echo "  PASS: evaluate dry-run: has literary-agent evaluator"; } || { FAIL=$((FAIL+1)); echo "  FAIL: evaluate dry-run: has literary-agent evaluator"; }
_eval_file_contains "DRY RUN: first-reader" && { PASS=$((PASS+1)); echo "  PASS: evaluate dry-run: has first-reader evaluator"; } || { FAIL=$((FAIL+1)); echo "  FAIL: evaluate dry-run: has first-reader evaluator"; }
_eval_file_contains "DRY RUN: genre-expert" && { PASS=$((PASS+1)); echo "  PASS: evaluate dry-run: has genre-expert evaluator"; } || { FAIL=$((FAIL+1)); echo "  FAIL: evaluate dry-run: has genre-expert evaluator"; }
_eval_file_contains "DRY RUN: writing-coach" && { PASS=$((PASS+1)); echo "  PASS: evaluate dry-run: has writing-coach evaluator"; } || { FAIL=$((FAIL+1)); echo "  FAIL: evaluate dry-run: has writing-coach evaluator"; }
_eval_file_contains "DRY RUN: synthesis" && { PASS=$((PASS+1)); echo "  PASS: evaluate dry-run: has synthesis section"; } || { FAIL=$((FAIL+1)); echo "  FAIL: evaluate dry-run: has synthesis section"; }
_eval_file_contains "The Cartographer's Silence" && { PASS=$((PASS+1)); echo "  PASS: evaluate dry-run: prompt contains title"; } || { FAIL=$((FAIL+1)); echo "  FAIL: evaluate dry-run: prompt contains title"; }
_eval_file_contains "scenes/act1-sc01.md" && { PASS=$((PASS+1)); echo "  PASS: evaluate dry-run: prompt lists scene files"; } || { FAIL=$((FAIL+1)); echo "  FAIL: evaluate dry-run: prompt lists scene files"; }
rm -f "$eval_result_file"

# Evaluate dry-run should not create new evaluation directories
eval_dirs_before=$(ls -d "${FIXTURE_DIR}/working/evaluations/"*/ 2>/dev/null | wc -l | tr -d ' ')
run_dry_run "storyforge-evaluate" >/dev/null
eval_dirs_after=$(ls -d "${FIXTURE_DIR}/working/evaluations/"*/ 2>/dev/null | wc -l | tr -d ' ')
assert_equals "$eval_dirs_before" "$eval_dirs_after" "evaluate dry-run: does not create new eval directory"

# ============================================================================
# storyforge-assemble --dry-run
# ============================================================================

result=$(run_dry_run "storyforge-assemble")
rc=$?

assert_exit_code "0" "$rc" "assemble dry-run: exits 0"
assert_contains "$result" "DRY RUN: assemble" "assemble dry-run: has dry-run header"
assert_contains "$result" "END DRY RUN: assemble" "assemble dry-run: has dry-run footer"
assert_contains "$result" "The Cartographer's Silence" "assemble dry-run: shows project title"
assert_contains "$result" "Chapters: 2" "assemble dry-run: shows chapter count"
assert_contains "$result" "The Finest Cartographer" "assemble dry-run: shows chapter 1 title"
assert_contains "$result" "Into the Blank" "assemble dry-run: shows chapter 2 title"
assert_contains "$result" "act1-sc01" "assemble dry-run: lists scene IDs"
assert_contains "$result" "act2-sc01" "assemble dry-run: lists scenes in chapter 2"

# Dry-run should not create manuscript directory
if [[ -d "${FIXTURE_DIR}/manuscript" ]]; then
    FAIL=$((FAIL + 1))
    echo "  FAIL: assemble dry-run: should not create manuscript directory"
else
    PASS=$((PASS + 1))
    echo "  PASS: assemble dry-run: does not create manuscript directory"
fi

# ============================================================================
# --no-annotate flag
# ============================================================================

result=$(cd "$PROJECT_DIR" && "${PLUGIN_DIR}/scripts/storyforge-assemble" --dry-run --format web 2>&1)
assert_contains "$result" "annotations: true" "storyforge-assemble: annotations on by default in dry-run"

result=$(cd "$PROJECT_DIR" && "${PLUGIN_DIR}/scripts/storyforge-assemble" --dry-run --no-annotate --format web 2>&1)
assert_contains "$result" "annotations: false" "storyforge-assemble: --no-annotate disables annotations in dry-run"

# ============================================================================
# storyforge-review --dry-run
# ============================================================================

result=$(run_dry_run "storyforge-review" --type drafting)
rc=$?

assert_exit_code "0" "$rc" "review dry-run: exits 0"
assert_contains "$result" "DRY RUN: review" "review dry-run: has dry-run header"
assert_contains "$result" "END DRY RUN: review" "review dry-run: has dry-run footer"
assert_contains "$result" "drafting" "review dry-run: shows review type"
assert_contains "$result" "pipeline review" "review dry-run: prompt mentions pipeline review"
