#!/bin/bash
# test-coaching.sh — Tests for coaching level system
#
# Run via: ./tests/run-tests.sh
# Depends on: FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, assertion functions (from run-tests.sh)

# ============================================================================
# Helper: capture script output in dry-run mode
# ============================================================================

run_dry_run() {
    local script="$1"
    shift
    (
        cd "$FIXTURE_DIR"
        bash "${PLUGIN_DIR}/scripts/${script}" --dry-run "$@" 2>/dev/null
    )
}

# ============================================================================
# get_coaching_level — defaults
# ============================================================================

# Fixture YAML has no coaching_level field, no env var set — should default to "full"
(
    unset STORYFORGE_COACHING
    result=$(get_coaching_level)
    assert_equals "full" "$result" "get_coaching_level: defaults to full when no YAML field and no env var"
)

# ============================================================================
# get_coaching_level — reads from YAML
# ============================================================================

# Temporarily add coaching_level to fixture YAML, verify it reads back
(
    unset STORYFORGE_COACHING
    cp "${FIXTURE_DIR}/storyforge.yaml" "${FIXTURE_DIR}/storyforge.yaml.bak"
    sed -i '' 's/^project:/project:\n  coaching_level: coach/' "${FIXTURE_DIR}/storyforge.yaml"
    result=$(get_coaching_level)
    mv "${FIXTURE_DIR}/storyforge.yaml.bak" "${FIXTURE_DIR}/storyforge.yaml"
    assert_equals "coach" "$result" "get_coaching_level: reads coach from YAML"
)

(
    unset STORYFORGE_COACHING
    cp "${FIXTURE_DIR}/storyforge.yaml" "${FIXTURE_DIR}/storyforge.yaml.bak"
    sed -i '' 's/^project:/project:\n  coaching_level: strict/' "${FIXTURE_DIR}/storyforge.yaml"
    result=$(get_coaching_level)
    mv "${FIXTURE_DIR}/storyforge.yaml.bak" "${FIXTURE_DIR}/storyforge.yaml"
    assert_equals "strict" "$result" "get_coaching_level: reads strict from YAML"
)

(
    unset STORYFORGE_COACHING
    cp "${FIXTURE_DIR}/storyforge.yaml" "${FIXTURE_DIR}/storyforge.yaml.bak"
    sed -i '' 's/^project:/project:\n  coaching_level: full/' "${FIXTURE_DIR}/storyforge.yaml"
    result=$(get_coaching_level)
    mv "${FIXTURE_DIR}/storyforge.yaml.bak" "${FIXTURE_DIR}/storyforge.yaml"
    assert_equals "full" "$result" "get_coaching_level: reads full from YAML"
)

# ============================================================================
# get_coaching_level — env override
# ============================================================================

# STORYFORGE_COACHING env var overrides YAML value
(
    cp "${FIXTURE_DIR}/storyforge.yaml" "${FIXTURE_DIR}/storyforge.yaml.bak"
    sed -i '' 's/^project:/project:\n  coaching_level: full/' "${FIXTURE_DIR}/storyforge.yaml"
    STORYFORGE_COACHING=coach
    export STORYFORGE_COACHING
    result=$(get_coaching_level)
    mv "${FIXTURE_DIR}/storyforge.yaml.bak" "${FIXTURE_DIR}/storyforge.yaml"
    assert_equals "coach" "$result" "get_coaching_level: env var overrides YAML (coach over full)"
)

(
    STORYFORGE_COACHING=strict
    export STORYFORGE_COACHING
    result=$(get_coaching_level)
    assert_equals "strict" "$result" "get_coaching_level: env var strict without YAML field"
)

(
    STORYFORGE_COACHING=full
    export STORYFORGE_COACHING
    result=$(get_coaching_level)
    assert_equals "full" "$result" "get_coaching_level: env var full without YAML field"
)

# ============================================================================
# get_coaching_level — validation (invalid values)
# ============================================================================

# Invalid YAML value falls back to "full"
(
    unset STORYFORGE_COACHING
    cp "${FIXTURE_DIR}/storyforge.yaml" "${FIXTURE_DIR}/storyforge.yaml.bak"
    sed -i '' 's/^project:/project:\n  coaching_level: banana/' "${FIXTURE_DIR}/storyforge.yaml"
    result=$(get_coaching_level)
    mv "${FIXTURE_DIR}/storyforge.yaml.bak" "${FIXTURE_DIR}/storyforge.yaml"
    assert_equals "full" "$result" "get_coaching_level: invalid YAML value 'banana' falls back to full"
)

# Invalid YAML value with numbers
(
    unset STORYFORGE_COACHING
    cp "${FIXTURE_DIR}/storyforge.yaml" "${FIXTURE_DIR}/storyforge.yaml.bak"
    sed -i '' 's/^project:/project:\n  coaching_level: 123/' "${FIXTURE_DIR}/storyforge.yaml"
    result=$(get_coaching_level)
    mv "${FIXTURE_DIR}/storyforge.yaml.bak" "${FIXTURE_DIR}/storyforge.yaml"
    assert_equals "full" "$result" "get_coaching_level: invalid YAML value '123' falls back to full"
)

# Note: env var is NOT validated by get_coaching_level (it trusts the caller).
# The scripts validate at parse time. So an invalid env value passes through.
(
    STORYFORGE_COACHING=banana
    export STORYFORGE_COACHING
    result=$(get_coaching_level)
    assert_equals "banana" "$result" "get_coaching_level: env var not validated (trusted from caller)"
)

# ============================================================================
# write script --coaching flag (dry-run)
# ============================================================================

# --coaching coach should appear in the log output and affect prompt
result=$(run_dry_run "storyforge-write" --coaching coach act1-sc01)
rc=$?
assert_exit_code "0" "$rc" "write --coaching coach dry-run: exits 0"
assert_contains "$result" "Coaching level: coach" "write --coaching coach dry-run: logs coaching level"
assert_contains "$result" "writing guide" "write --coaching coach dry-run: prompt requests writing guide"

# --coaching strict
result=$(run_dry_run "storyforge-write" --coaching strict act1-sc01)
rc=$?
assert_exit_code "0" "$rc" "write --coaching strict dry-run: exits 0"
assert_contains "$result" "Coaching level: strict" "write --coaching strict dry-run: logs coaching level"
assert_contains "$result" "brief data" "write --coaching strict dry-run: prompt outputs brief data"

# --coaching full should produce standard draft output (no coaching paths)
result=$(run_dry_run "storyforge-write" --coaching full act1-sc01)
rc=$?
assert_exit_code "0" "$rc" "write --coaching full dry-run: exits 0"
assert_contains "$result" "Coaching level: full" "write --coaching full dry-run: logs coaching level"
assert_contains "$result" "DRY RUN: act1-sc01" "write --coaching full dry-run: has dry-run header"

# ============================================================================
# write script --coaching invalid value
# ============================================================================

# Invalid coaching value should exit with error
result=$(run_dry_run "storyforge-write" --coaching banana act1-sc01 2>&1)
rc=$?
assert_exit_code "1" "$rc" "write --coaching banana: exits 1"

# ============================================================================
# revise script --coaching flag (dry-run)
# ============================================================================

result=$(run_dry_run "storyforge-revise" --coaching coach)
rc=$?
assert_exit_code "0" "$rc" "revise --coaching coach dry-run: exits 0"
assert_contains "$result" "Coaching level: coach" "revise --coaching coach dry-run: logs coaching level"
assert_contains "$result" "DRY RUN: prose-tightening" "revise --coaching coach dry-run: has pass header"

result=$(run_dry_run "storyforge-revise" --coaching strict)
rc=$?
assert_exit_code "0" "$rc" "revise --coaching strict dry-run: exits 0"
assert_contains "$result" "Coaching level: strict" "revise --coaching strict dry-run: logs coaching level"

# ============================================================================
# evaluate script has no --coaching flag
# ============================================================================

# evaluate should not accept --coaching (it ignores coaching entirely)
result=$(
    cd "$FIXTURE_DIR"
    bash "${PLUGIN_DIR}/scripts/storyforge-evaluate" --dry-run 2>/dev/null
)
rc=$?
assert_exit_code "0" "$rc" "evaluate dry-run: exits 0 (baseline)"
assert_not_contains "$result" "Coaching level" "evaluate dry-run: does not mention coaching level"

# ============================================================================
# coaching affects output path — coach mode references working/coaching/
# ============================================================================

# Write dry-run in coach mode should reference writing guide
result=$(run_dry_run "storyforge-write" --coaching coach act1-sc01)
assert_contains "$result" "writing guide" "write coach dry-run: prompt requests writing guide"

# Write dry-run in strict mode should reference brief data
result=$(run_dry_run "storyforge-write" --coaching strict act1-sc01)
assert_contains "$result" "brief data" "write strict dry-run: prompt outputs brief data"

# Revise dry-run in coach mode should reference notes files
result=$(run_dry_run "storyforge-revise" --coaching coach)
assert_contains "$result" "working/coaching/" "revise coach dry-run: prompt references working/coaching/ directory"

# Revise dry-run in strict mode should reference checklist files
result=$(run_dry_run "storyforge-revise" --coaching strict)
assert_contains "$result" "working/coaching/" "revise strict dry-run: prompt references working/coaching/ directory"

# ============================================================================
# STORYFORGE_COACHING env var in dry-run
# ============================================================================

# Set env var instead of --coaching flag, verify same effect
result=$(
    cd "$FIXTURE_DIR"
    STORYFORGE_COACHING=coach bash "${PLUGIN_DIR}/scripts/storyforge-write" --dry-run act1-sc01 2>/dev/null
)
rc=$?
assert_exit_code "0" "$rc" "write env STORYFORGE_COACHING=coach dry-run: exits 0"
assert_contains "$result" "Coaching level: coach" "write env STORYFORGE_COACHING=coach dry-run: logs coaching level"
assert_contains "$result" "writing guide" "write env STORYFORGE_COACHING=coach dry-run: prompt requests writing guide"

result=$(
    cd "$FIXTURE_DIR"
    STORYFORGE_COACHING=strict bash "${PLUGIN_DIR}/scripts/storyforge-write" --dry-run act1-sc01 2>/dev/null
)
rc=$?
assert_exit_code "0" "$rc" "write env STORYFORGE_COACHING=strict dry-run: exits 0"
assert_contains "$result" "Coaching level: strict" "write env STORYFORGE_COACHING=strict dry-run: logs coaching level"
assert_contains "$result" "brief data" "write env STORYFORGE_COACHING=strict dry-run: prompt outputs brief data"

# ============================================================================
# --coaching flag overrides STORYFORGE_COACHING env var
# ============================================================================

# The flag sets STORYFORGE_COACHING, so the last write wins (flag runs after env).
# --coaching coach should override STORYFORGE_COACHING=strict
result=$(
    cd "$FIXTURE_DIR"
    STORYFORGE_COACHING=strict bash "${PLUGIN_DIR}/scripts/storyforge-write" --dry-run --coaching coach act1-sc01 2>/dev/null
)
rc=$?
assert_exit_code "0" "$rc" "write flag overrides env: exits 0"
assert_contains "$result" "Coaching level: coach" "write --coaching coach overrides STORYFORGE_COACHING=strict"
