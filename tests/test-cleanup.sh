#!/bin/bash
# test-cleanup.sh — Tests for storyforge-cleanup functions

CLEANUP_FIXTURE="${TESTS_DIR}/fixtures/cleanup-project"

# ============================================================================
# Setup: copy fixture to temp dir (so we don't mutate fixtures)
# ============================================================================
WORK_DIR="${TMPDIR}/cleanup-test-$$"
cp -R "$CLEANUP_FIXTURE" "$WORK_DIR"

# Source the cleanup script's functions (we'll add a --source-only mode)
source "${PLUGIN_DIR}/scripts/storyforge-cleanup" --source-only

# ============================================================================
# Gitignore tests
# ============================================================================

# Test: missing entries get added
BEFORE=$(cat "$WORK_DIR/.gitignore")
update_gitignore "$WORK_DIR"
AFTER=$(cat "$WORK_DIR/.gitignore")

assert_contains "$AFTER" "working/logs/" "gitignore: adds working/logs/"
assert_contains "$AFTER" "working/scores/**/.batch-requests.jsonl" "gitignore: adds batch-requests pattern"
assert_contains "$AFTER" "working/evaluations/**/.status-*" "gitignore: adds status file pattern"
assert_contains "$AFTER" "working/scores/**/.markers-*" "gitignore: adds markers pattern"
assert_contains "$AFTER" ".DS_Store" "gitignore: preserves existing .DS_Store entry"
assert_contains "$AFTER" "working/.autopilot" "gitignore: preserves existing autopilot entry"
assert_contains "$AFTER" "working/.interactive" "gitignore: adds missing interactive entry"

# Test: idempotent — running again doesn't duplicate
update_gitignore "$WORK_DIR"
AGAIN=$(cat "$WORK_DIR/.gitignore")
LOGS_COUNT=$(grep -c "working/logs/" <<< "$AGAIN")
assert_equals "1" "$LOGS_COUNT" "gitignore: idempotent, no duplicates"

# Cleanup
rm -rf "$WORK_DIR"

# ============================================================================
# Missing directory tests
# ============================================================================
WORK_DIR="${TMPDIR}/cleanup-dirs-$$"
cp -R "$CLEANUP_FIXTURE" "$WORK_DIR"
source "${PLUGIN_DIR}/scripts/storyforge-cleanup" --source-only

assert_not_empty "$(create_missing_dirs "$WORK_DIR")" "missing_dirs: reports created dirs"
assert_file_exists "$WORK_DIR/manuscript/press-kit/.gitkeep" "missing_dirs: creates press-kit"
assert_file_exists "$WORK_DIR/working/recommendations/.gitkeep" "missing_dirs: creates recommendations"

SECOND=$(create_missing_dirs "$WORK_DIR")
assert_empty "$SECOND" "missing_dirs: idempotent, nothing to create"

rm -rf "$WORK_DIR"

# ============================================================================
# Junk file cleanup tests
# ============================================================================
WORK_DIR="${TMPDIR}/cleanup-junk-$$"
cp -R "$CLEANUP_FIXTURE" "$WORK_DIR"
source "${PLUGIN_DIR}/scripts/storyforge-cleanup" --source-only

assert_file_exists "$WORK_DIR/working/evaluations/eval-20260301-100000/.status-dev-editor" "junk: status file exists before"
assert_file_exists "$WORK_DIR/working/scores/cycle-1/.markers-prose_craft.txt" "junk: markers file exists before"
assert_file_exists "$WORK_DIR/working/scores/cycle-1/.batch-requests.jsonl" "junk: batch jsonl in cycle-1 exists before"
assert_file_exists "$WORK_DIR/working/scores/latest/.batch-requests.jsonl" "junk: batch jsonl in latest exists before"
assert_file_exists "$WORK_DIR/working/logs/drafting-1.log" "junk: log file exists before"

clean_junk_files "$WORK_DIR"

RESULT=$(ls "$WORK_DIR/working/evaluations/eval-20260301-100000/.status-"* 2>/dev/null || echo "gone")
assert_equals "gone" "$RESULT" "junk: status files removed"
RESULT=$(ls "$WORK_DIR/working/scores/cycle-1/.markers-"* 2>/dev/null || echo "gone")
assert_equals "gone" "$RESULT" "junk: markers files removed"
RESULT=$(ls "$WORK_DIR/working/scores/cycle-1/.batch-requests.jsonl" 2>/dev/null || echo "gone")
assert_equals "gone" "$RESULT" "junk: batch jsonl removed from cycle dirs"
assert_file_exists "$WORK_DIR/working/scores/latest/.batch-requests.jsonl" "junk: batch jsonl preserved in latest"
RESULT=$(ls "$WORK_DIR/working/logs/"*.log 2>/dev/null || echo "gone")
assert_equals "gone" "$RESULT" "junk: log files removed"
RESULT=$(ls -d "$WORK_DIR/working/enrich" 2>/dev/null || echo "gone")
assert_equals "gone" "$RESULT" "junk: empty enrich dir removed"
RESULT=$(ls -d "$WORK_DIR/working/coaching" 2>/dev/null || echo "gone")
assert_equals "gone" "$RESULT" "junk: empty coaching dir removed"

rm -rf "$WORK_DIR"

# ============================================================================
# Legacy file and reorganization tests
# ============================================================================
WORK_DIR="${TMPDIR}/cleanup-legacy-$$"
cp -R "$CLEANUP_FIXTURE" "$WORK_DIR"
mkdir -p "$WORK_DIR/working/recommendations"
source "${PLUGIN_DIR}/scripts/storyforge-cleanup" --source-only

assert_file_exists "$WORK_DIR/working/pipeline.yaml" "legacy: pipeline.yaml exists before"
assert_file_exists "$WORK_DIR/working/assemble.py" "legacy: assemble.py exists before"

delete_legacy_files "$WORK_DIR"

RESULT=$(ls "$WORK_DIR/working/pipeline.yaml" 2>/dev/null || echo "gone")
assert_equals "gone" "$RESULT" "legacy: pipeline.yaml deleted"
RESULT=$(ls "$WORK_DIR/working/assemble.py" 2>/dev/null || echo "gone")
assert_equals "gone" "$RESULT" "legacy: assemble.py deleted"

assert_file_exists "$WORK_DIR/working/recommendations.md" "reorg: loose rec exists before"
assert_file_exists "$WORK_DIR/working/recommendations-3.md" "reorg: loose rec-3 exists before"

reorganize_loose_files "$WORK_DIR"

RESULT=$(ls "$WORK_DIR/working/recommendations.md" 2>/dev/null || echo "gone")
assert_equals "gone" "$RESULT" "reorg: loose rec moved"
assert_file_exists "$WORK_DIR/working/recommendations/recommendations.md" "reorg: rec in subdir"
assert_file_exists "$WORK_DIR/working/recommendations/recommendations-3.md" "reorg: rec-3 in subdir"

rm -rf "$WORK_DIR"

# ============================================================================
# Pipeline CSV column tests
# ============================================================================
WORK_DIR="${TMPDIR}/cleanup-pipeline-$$"
cp -R "$CLEANUP_FIXTURE" "$WORK_DIR"
source "${PLUGIN_DIR}/scripts/storyforge-cleanup" --source-only

HEADER=$(head -1 "$WORK_DIR/working/pipeline.csv")
assert_not_contains "$HEADER" "scoring" "pipeline: missing scoring column before"

migrate_pipeline_csv "$WORK_DIR"

HEADER=$(head -1 "$WORK_DIR/working/pipeline.csv")
assert_contains "$HEADER" "scoring" "pipeline: scoring column added"
assert_contains "$HEADER" "review" "pipeline: review column added"
assert_contains "$HEADER" "recommendations" "pipeline: recommendations column added"

DATA_LINE=$(tail -1 "$WORK_DIR/working/pipeline.csv")
EXPECTED_FIELDS=$(head -1 "$WORK_DIR/working/pipeline.csv" | awk -F'|' '{print NF}')
ACTUAL_FIELDS=$(echo "$DATA_LINE" | awk -F'|' '{print NF}')
assert_equals "$EXPECTED_FIELDS" "$ACTUAL_FIELDS" "pipeline: data rows have correct field count"

migrate_pipeline_csv "$WORK_DIR"
HEADER2=$(head -1 "$WORK_DIR/working/pipeline.csv")
assert_equals "$HEADER" "$HEADER2" "pipeline: idempotent"

rm -rf "$WORK_DIR"

# ============================================================================
# Pipeline review dedup tests
# ============================================================================
WORK_DIR="${TMPDIR}/cleanup-dedup-$$"
cp -R "$CLEANUP_FIXTURE" "$WORK_DIR"
source "${PLUGIN_DIR}/scripts/storyforge-cleanup" --source-only

BEFORE_COUNT=$(ls "$WORK_DIR/working/reviews/pipeline-review-"* 2>/dev/null | wc -l | tr -d ' ')
assert_equals "4" "$BEFORE_COUNT" "dedup: 4 pipeline reviews before"

dedup_pipeline_reviews "$WORK_DIR"

AFTER_COUNT=$(ls "$WORK_DIR/working/reviews/pipeline-review-"* 2>/dev/null | wc -l | tr -d ' ')
assert_equals "2" "$AFTER_COUNT" "dedup: 2 pipeline reviews after (1 per day)"

assert_file_exists "$WORK_DIR/working/reviews/pipeline-review-20260301-120000.md" "dedup: keeps latest from day 1"
RESULT=$(ls "$WORK_DIR/working/reviews/pipeline-review-20260301-100000.md" 2>/dev/null || echo "gone")
assert_equals "gone" "$RESULT" "dedup: removes earlier from day 1"

assert_file_exists "$WORK_DIR/working/reviews/review-20260301.md" "dedup: summary review preserved"

rm -rf "$WORK_DIR"

