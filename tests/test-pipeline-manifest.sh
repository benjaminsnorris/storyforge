#!/bin/bash
# test-pipeline-manifest.sh — Tests for pipeline manifest CRUD functions
#
# Run via: ./tests/run-tests.sh
# Depends on: FIXTURE_DIR, PROJECT_DIR, assertion functions (from run-tests.sh)

# ============================================================================
# Setup: use a temp directory for pipeline manifest tests (writes files)
# ============================================================================

PIPELINE_ORIG_PROJECT_DIR="$PROJECT_DIR"
PIPELINE_TMP_DIR=$(mktemp -d)

# Copy fixture structure into temp
cp -R "$FIXTURE_DIR"/* "$PIPELINE_TMP_DIR/" 2>/dev/null || true
mkdir -p "$PIPELINE_TMP_DIR/working/plans"
mkdir -p "$PIPELINE_TMP_DIR/working/evaluations"

export PROJECT_DIR="$PIPELINE_TMP_DIR"

# ============================================================================
# get_pipeline_file
# ============================================================================

result=$(get_pipeline_file)
assert_equals "${PIPELINE_TMP_DIR}/working/pipeline.yaml" "$result" \
    "get_pipeline_file: returns correct path"

# ============================================================================
# ensure_pipeline_manifest
# ============================================================================

# Should create the file when it doesn't exist
rm -f "${PIPELINE_TMP_DIR}/working/pipeline.yaml"
ensure_pipeline_manifest
assert_file_exists "${PIPELINE_TMP_DIR}/working/pipeline.yaml" \
    "ensure_pipeline_manifest: creates file"

result=$(get_current_cycle)
assert_equals "0" "$result" "ensure_pipeline_manifest: initial cycle is 0"

# Should be idempotent
ensure_pipeline_manifest
result=$(get_current_cycle)
assert_equals "0" "$result" "ensure_pipeline_manifest: idempotent — still 0"

# ============================================================================
# start_new_cycle
# ============================================================================

cycle_id=$(start_new_cycle)
assert_equals "1" "$cycle_id" "start_new_cycle: first cycle is 1"

result=$(get_current_cycle)
assert_equals "1" "$result" "start_new_cycle: current_cycle updated to 1"

# Start a second cycle
cycle_id=$(start_new_cycle)
assert_equals "2" "$cycle_id" "start_new_cycle: second cycle is 2"

result=$(get_current_cycle)
assert_equals "2" "$result" "start_new_cycle: current_cycle updated to 2"

# ============================================================================
# read_cycle_field
# ============================================================================

result=$(read_cycle_field "1" "status")
assert_equals "pending" "$result" "read_cycle_field: cycle 1 status is pending"

result=$(read_cycle_field "2" "status")
assert_equals "pending" "$result" "read_cycle_field: cycle 2 status is pending"

# Started date should be today
today=$(date '+%Y-%m-%d')
result=$(read_cycle_field "1" "started")
assert_equals "$today" "$result" "read_cycle_field: cycle 1 started is today"

# Empty fields return empty
result=$(read_cycle_field "1" "evaluation")
assert_empty "$result" "read_cycle_field: cycle 1 evaluation is empty initially"

# Nonexistent cycle returns empty
result=$(read_cycle_field "99" "status")
assert_empty "$result" "read_cycle_field: nonexistent cycle returns empty"

# ============================================================================
# update_cycle_field
# ============================================================================

update_cycle_field "1" "status" "evaluating"
result=$(read_cycle_field "1" "status")
assert_equals "evaluating" "$result" "update_cycle_field: cycle 1 status → evaluating"

update_cycle_field "1" "evaluation" "eval-20260305-091500"
result=$(read_cycle_field "1" "evaluation")
assert_equals "eval-20260305-091500" "$result" "update_cycle_field: cycle 1 evaluation set"

# Updating cycle 1 shouldn't affect cycle 2
result=$(read_cycle_field "2" "status")
assert_equals "pending" "$result" "update_cycle_field: cycle 2 unchanged"

update_cycle_field "2" "status" "evaluating"
result=$(read_cycle_field "2" "status")
assert_equals "evaluating" "$result" "update_cycle_field: cycle 2 status → evaluating"

update_cycle_field "1" "plan" "revision-plan-1.yaml"
result=$(read_cycle_field "1" "plan")
assert_equals "revision-plan-1.yaml" "$result" "update_cycle_field: cycle 1 plan set"

update_cycle_field "1" "status" "complete"
result=$(read_cycle_field "1" "status")
assert_equals "complete" "$result" "update_cycle_field: cycle 1 status → complete"

update_cycle_field "1" "summary" "Addressed 8/12 findings."
result=$(read_cycle_field "1" "summary")
assert_equals "Addressed 8/12 findings." "$result" "update_cycle_field: cycle 1 summary set"

# ============================================================================
# get_cycle_plan_file
# ============================================================================

result=$(get_cycle_plan_file "1")
assert_equals "${PIPELINE_TMP_DIR}/working/plans/revision-plan-1.yaml" "$result" \
    "get_cycle_plan_file: cycle 1 returns named plan"

# Cycle 2 has no plan set — should fall back to legacy path
result=$(get_cycle_plan_file "2")
assert_equals "${PIPELINE_TMP_DIR}/working/plans/revision-plan.yaml" "$result" \
    "get_cycle_plan_file: cycle with no plan falls back to legacy"

# Default (no arg) uses current cycle
update_cycle_field "2" "plan" "revision-plan-2.yaml"
result=$(get_cycle_plan_file)
assert_equals "${PIPELINE_TMP_DIR}/working/plans/revision-plan-2.yaml" "$result" \
    "get_cycle_plan_file: default uses current cycle"

# ============================================================================
# get_cycle_eval_dir
# ============================================================================

update_cycle_field "2" "evaluation" "eval-20260305-120000"
result=$(get_cycle_eval_dir "2")
assert_equals "${PIPELINE_TMP_DIR}/working/evaluations/eval-20260305-120000" "$result" \
    "get_cycle_eval_dir: cycle 2 returns correct dir"

result=$(get_cycle_eval_dir "1")
assert_equals "${PIPELINE_TMP_DIR}/working/evaluations/eval-20260305-091500" "$result" \
    "get_cycle_eval_dir: cycle 1 returns correct dir"

# Default uses current cycle
result=$(get_cycle_eval_dir)
assert_equals "${PIPELINE_TMP_DIR}/working/evaluations/eval-20260305-120000" "$result" \
    "get_cycle_eval_dir: default uses current cycle"

# ============================================================================
# Full lifecycle: simulate evaluate → plan → revise → review
# ============================================================================

# Reset for lifecycle test
rm -f "${PIPELINE_TMP_DIR}/working/pipeline.yaml"
ensure_pipeline_manifest

# Evaluate starts a new cycle
LIFECYCLE_CYCLE=$(start_new_cycle)
assert_equals "1" "$LIFECYCLE_CYCLE" "lifecycle: evaluate starts cycle 1"

update_cycle_field "$LIFECYCLE_CYCLE" "evaluation" "eval-20260305-143022"
update_cycle_field "$LIFECYCLE_CYCLE" "status" "evaluating"

result=$(read_cycle_field "$LIFECYCLE_CYCLE" "status")
assert_equals "evaluating" "$result" "lifecycle: status is evaluating"

# Evaluation completes → planning
update_cycle_field "$LIFECYCLE_CYCLE" "status" "planning"

# Plan-revision saves plan
update_cycle_field "$LIFECYCLE_CYCLE" "plan" "revision-plan-1.yaml"

# Revise reads the plan and starts
result=$(get_cycle_plan_file "$LIFECYCLE_CYCLE")
assert_contains "$result" "revision-plan-1.yaml" "lifecycle: revise reads correct plan"

update_cycle_field "$LIFECYCLE_CYCLE" "status" "revising"

# Revision completes → reviewing
update_cycle_field "$LIFECYCLE_CYCLE" "status" "reviewing"
update_cycle_field "$LIFECYCLE_CYCLE" "review" "pipeline-review-20260305-163000.md"

# Recommend completes cycle
update_cycle_field "$LIFECYCLE_CYCLE" "recommendations" "recommendations-1.md"
update_cycle_field "$LIFECYCLE_CYCLE" "status" "complete"

result=$(read_cycle_field "$LIFECYCLE_CYCLE" "status")
assert_equals "complete" "$result" "lifecycle: cycle 1 is complete"

# Second cycle doesn't affect first
LIFECYCLE_CYCLE2=$(start_new_cycle)
assert_equals "2" "$LIFECYCLE_CYCLE2" "lifecycle: second cycle is 2"

result=$(read_cycle_field "1" "status")
assert_equals "complete" "$result" "lifecycle: cycle 1 still complete after cycle 2 starts"

result=$(read_cycle_field "1" "evaluation")
assert_equals "eval-20260305-143022" "$result" "lifecycle: cycle 1 evaluation preserved"

# ============================================================================
# Cleanup
# ============================================================================

rm -rf "$PIPELINE_TMP_DIR"
export PROJECT_DIR="$PIPELINE_ORIG_PROJECT_DIR"
