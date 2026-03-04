#!/bin/bash
# run-tests.sh — Storyforge test runner
#
# Usage: ./tests/run-tests.sh [test-file...]
#   With no arguments, runs all test-*.sh files in this directory.
#   With arguments, runs only the specified test files.
set -uo pipefail

# ============================================================================
# Setup
# ============================================================================

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(dirname "$TESTS_DIR")"
FIXTURE_DIR="${TESTS_DIR}/fixtures/test-project"

# Global counters
TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_SUITES=0
FAILED_SUITES=()

# ============================================================================
# Assertion library
# ============================================================================

# Per-suite counters (reset by each test file)
PASS=0
FAIL=0

assert_equals() {
    local expected="$1"
    local actual="$2"
    local label="${3:-assert_equals}"

    if [[ "$expected" == "$actual" ]]; then
        PASS=$((PASS + 1))
        echo "  PASS: ${label}"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: ${label}"
        echo "    Expected: $(echo "$expected" | head -3)"
        echo "    Actual:   $(echo "$actual" | head -3)"
        if [[ $(echo "$expected" | wc -l) -gt 3 ]]; then
            echo "    (output truncated)"
        fi
    fi
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local label="${3:-assert_contains}"

    if echo "$haystack" | grep -qF -- "$needle"; then
        PASS=$((PASS + 1))
        echo "  PASS: ${label}"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: ${label}"
        echo "    Expected to contain: ${needle}"
        echo "    In: $(echo "$haystack" | head -5)"
    fi
}

assert_not_contains() {
    local haystack="$1"
    local needle="$2"
    local label="${3:-assert_not_contains}"

    if echo "$haystack" | grep -qF -- "$needle"; then
        FAIL=$((FAIL + 1))
        echo "  FAIL: ${label}"
        echo "    Expected NOT to contain: ${needle}"
    else
        PASS=$((PASS + 1))
        echo "  PASS: ${label}"
    fi
}

assert_matches() {
    local haystack="$1"
    local pattern="$2"
    local label="${3:-assert_matches}"

    if echo "$haystack" | grep -qE "$pattern"; then
        PASS=$((PASS + 1))
        echo "  PASS: ${label}"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: ${label}"
        echo "    Expected to match pattern: ${pattern}"
        echo "    In: $(echo "$haystack" | head -5)"
    fi
}

assert_empty() {
    local value="$1"
    local label="${2:-assert_empty}"

    if [[ -z "$value" ]]; then
        PASS=$((PASS + 1))
        echo "  PASS: ${label}"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: ${label}"
        echo "    Expected empty, got: $(echo "$value" | head -3)"
    fi
}

assert_not_empty() {
    local value="$1"
    local label="${2:-assert_not_empty}"

    if [[ -n "$value" ]]; then
        PASS=$((PASS + 1))
        echo "  PASS: ${label}"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: ${label}"
        echo "    Expected non-empty value"
    fi
}

assert_exit_code() {
    local expected="$1"
    local actual="$2"
    local label="${3:-assert_exit_code}"

    if [[ "$expected" == "$actual" ]]; then
        PASS=$((PASS + 1))
        echo "  PASS: ${label}"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: ${label}"
        echo "    Expected exit code: ${expected}"
        echo "    Actual exit code:   ${actual}"
    fi
}

assert_file_exists() {
    local filepath="$1"
    local label="${2:-assert_file_exists: ${filepath}}"

    if [[ -f "$filepath" ]]; then
        PASS=$((PASS + 1))
        echo "  PASS: ${label}"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: ${label}"
        echo "    File not found: ${filepath}"
    fi
}

assert_line_count() {
    local value="$1"
    local expected="$2"
    local label="${3:-assert_line_count}"

    local actual
    actual=$(echo "$value" | wc -l | tr -d ' ')
    if [[ "$actual" == "$expected" ]]; then
        PASS=$((PASS + 1))
        echo "  PASS: ${label}"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: ${label}"
        echo "    Expected ${expected} lines, got ${actual}"
    fi
}

# ============================================================================
# Test execution
# ============================================================================

run_suite() {
    local test_file="$1"
    local suite_name
    suite_name="$(basename "$test_file" .sh)"

    PASS=0
    FAIL=0

    echo ""
    echo "=== ${suite_name} ==="

    # Source the test file (it uses the assertion functions above)
    source "$test_file"

    TOTAL_PASS=$((TOTAL_PASS + PASS))
    TOTAL_FAIL=$((TOTAL_FAIL + FAIL))
    TOTAL_SUITES=$((TOTAL_SUITES + 1))

    if [[ $FAIL -gt 0 ]]; then
        FAILED_SUITES+=("$suite_name")
        echo "  --- ${PASS} passed, ${FAIL} FAILED ---"
    else
        echo "  --- ${PASS} passed ---"
    fi
}

# ============================================================================
# Main
# ============================================================================

echo "Storyforge Test Suite"
echo "Fixture: ${FIXTURE_DIR}"

# Source the libraries under test
source "${PLUGIN_DIR}/scripts/lib/common.sh"
source "${PLUGIN_DIR}/scripts/lib/prompt-builder.sh"
source "${PLUGIN_DIR}/scripts/lib/revision-passes.sh"

# Set PROJECT_DIR to the fixture
export PROJECT_DIR="$FIXTURE_DIR"

# Collect test files
if [[ $# -gt 0 ]]; then
    test_files=("$@")
else
    test_files=()
    for f in "${TESTS_DIR}"/test-*.sh; do
        [[ -f "$f" ]] && test_files+=("$f")
    done
fi

if [[ ${#test_files[@]} -eq 0 ]]; then
    echo "No test files found."
    exit 1
fi

# Run each suite
for test_file in "${test_files[@]}"; do
    run_suite "$test_file"
done

# Summary
echo ""
echo "========================================"
echo "Total: $((TOTAL_PASS + TOTAL_FAIL)) tests, ${TOTAL_PASS} passed, ${TOTAL_FAIL} failed (${TOTAL_SUITES} suites)"

if [[ ${#FAILED_SUITES[@]} -gt 0 ]]; then
    echo "Failed suites: ${FAILED_SUITES[*]}"
    echo "========================================"
    exit 1
else
    echo "========================================"
    exit 0
fi
