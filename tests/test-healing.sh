#!/bin/bash
# test-healing.sh — Tests for self-healing zone system
#
# Run via: ./tests/run-tests.sh
# Depends on: FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, assertion functions

# ============================================================================
# run_healing_zone — basic functionality
# ============================================================================

# Test: successful zone function doesn't trigger healing
_test_success_fn() {
    echo "success"
}
set +e
run_healing_zone "test success" _test_success_fn 2>/dev/null
_success_exit=$?
set -e
assert_equals "0" "$_success_exit" "healing: successful zone exits 0"

# Test: _SF_HEALING_ATTEMPT resets after success
assert_equals "0" "$_SF_HEALING_ATTEMPT" "healing: attempt counter resets after success"

# Test: zone description is cleared after success
assert_empty "$_SF_HEALING_ZONE" "healing: zone description cleared after success"

# ============================================================================
# Stubbed healing — test retry behavior without invoking Claude
# ============================================================================

# Override _run_healing_attempt to be a no-op for unit tests
_original_run_healing_attempt=$(declare -f _run_healing_attempt)

_run_healing_attempt() {
    log "TEST: healing attempt stub called (attempt $_SF_HEALING_ATTEMPT)"
}

# Test: failing zone exhausts attempts and exits with error code
# Run in a subshell because run_healing_zone calls exit when exhausted
_SF_HEALING_MAX_ATTEMPTS=3
set +e
(
    _run_healing_attempt() { :; }
    _test_fail_fn() { return 1; }
    run_healing_zone "test failure" _test_fail_fn 2>/dev/null
)
_fail_exit=$?
set -e

assert_equals "1" "$_fail_exit" "healing: exhausted zone exits with error code"

# ============================================================================
# Retry — zone that succeeds on third attempt
# ============================================================================

# Use a temp file for the counter since the zone function runs in a subshell
_retry_tmp=$(mktemp "${TMPDIR:-/tmp}/sf-test-retry.XXXXXX")
echo 0 > "$_retry_tmp"

_test_retry_fn() {
    local count
    count=$(cat "$_retry_tmp")
    count=$((count + 1))
    echo "$count" > "$_retry_tmp"
    if (( count < 3 )); then
        return 1
    fi
    return 0
}

_SF_HEALING_MAX_ATTEMPTS=3
set +e
run_healing_zone "test retry" _test_retry_fn 2>/dev/null
_retry_exit=$?
set -e

_retry_count=$(cat "$_retry_tmp")
rm -f "$_retry_tmp"

assert_equals "0" "$_retry_exit" "healing: zone succeeds on third attempt"
assert_equals "3" "$_retry_count" "healing: zone function called 3 times before success"
assert_equals "0" "$_SF_HEALING_ATTEMPT" "healing: attempt counter reset after eventual success"
assert_empty "$_SF_HEALING_ZONE" "healing: zone description cleared after eventual success"

# ============================================================================
# Restore original _run_healing_attempt
# ============================================================================
# Re-source common.sh to restore the real _run_healing_attempt
source "${PLUGIN_DIR}/scripts/lib/common.sh"

# Reset max attempts to default
_SF_HEALING_MAX_ATTEMPTS=3
