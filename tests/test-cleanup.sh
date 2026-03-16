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
