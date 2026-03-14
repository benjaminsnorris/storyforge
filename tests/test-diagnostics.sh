#!/bin/bash
# test-diagnostics.sh — Tests for diagnostic scoring functions
#
# Sourced by run-tests.sh which provides assertion functions,
# FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, and TMPDIR.

DIAG_TMPDIR="${TMPDIR}/diag-tests-$$"
mkdir -p "$DIAG_TMPDIR"

DIAGNOSTICS_CSV="${PLUGIN_DIR}/references/diagnostics.csv"

# ============================================================================
# build_diagnostic_markers
# ============================================================================

echo "  -- build_diagnostic_markers --"

result=$(build_diagnostic_markers "$DIAGNOSTICS_CSV")
assert_not_empty "$result" "build_diagnostic_markers produces output"
assert_contains "$result" "enter_late_leave_early" "markers include enter_late_leave_early"
assert_contains "$result" "economy_clarity" "markers include economy_clarity"
assert_contains "$result" "kill_darlings" "markers include kill_darlings"
assert_contains "$result" "[elle-1]" "markers include marker IDs"
assert_contains "$result" "[elle-1]" "markers include formatted marker entries"

# Count principles — should have headers for all 25
principle_count=$(echo "$result" | grep -c "^=== " || true)
assert_equals "25" "$principle_count" "markers cover all 25 principles"

# ============================================================================
# parse_diagnostic_output — mock response
# ============================================================================

echo "  -- parse_diagnostic_output --"

# Create a mock stream-json log with diagnostic output
# Use the result format that extract_claude_response Strategy 1 handles
MOCK_LOG="${DIAG_TMPDIR}/mock-diag.log"
printf '{"type":"result","result":"DIAGNOSTICS:\\nmarker_id|answer|evidence\\nelle-1|YES|She woke up and stretched.\\nelle-2|NO|CLEAN\\nesmt-1|NO|Cannot articulate the scene question\\nesmt-2|YES|The relationship shifts\\n","stop_reason":"end_turn"}\n' > "$MOCK_LOG"

parse_diagnostic_output "$MOCK_LOG" "$DIAG_TMPDIR" "test-scene"
assert_exit_code "0" "$?" "parse_diagnostic_output succeeds"

DIAG_FILE="${DIAG_TMPDIR}/.diag-test-scene.csv"
assert_file_exists "$DIAG_FILE" "diagnostic file created"

# Check header
header=$(head -1 "$DIAG_FILE")
assert_equals "marker_id|answer|evidence" "$header" "diagnostic file has correct header"

# Should have header + 4 data rows (trailing newline may add 1)
data_rows=$(awk -F'|' 'NR > 1 && NF >= 2 { count++ } END { print count+0 }' "$DIAG_FILE")
assert_equals "4" "$data_rows" "diagnostic file has 4 data rows"

# ============================================================================
# aggregate_diagnostic_scores
# ============================================================================

echo "  -- aggregate_diagnostic_scores --"

# Create a simplified diagnostics CSV for testing
TEST_DIAG_CSV="${DIAG_TMPDIR}/test-diagnostics.csv"
cat > "$TEST_DIAG_CSV" <<'EOF'
principle|marker_id|question|deficit_if|weight|evidence_required
alpha|a-1|Is there a problem?|yes|2|Quote it
alpha|a-2|Is there another problem?|yes|1|Quote it
alpha|a-3|Is the good thing missing?|yes|1|Quote it
beta|b-1|First problem check|yes|2|Quote
beta|b-2|Second problem check|yes|2|Quote
EOF

# Create diagnostic results: alpha has 1 deficit (a-1=YES), 2 clean (a-2=NO, a-3=NO)
# alpha deficit_points=2, max=4, ratio=0.50 -> score 3
# beta has no deficits (b-1=NO, b-2=NO) -> score 5
TEST_DIAG_RESULTS="${DIAG_TMPDIR}/.diag-test-agg.csv"
cat > "$TEST_DIAG_RESULTS" <<'EOF'
marker_id|answer|evidence
a-1|YES|"Found a problem here"
a-2|NO|CLEAN
a-3|NO|CLEAN
b-1|NO|CLEAN
b-2|NO|CLEAN
EOF

SCORES_OUT="${DIAG_TMPDIR}/agg-scores.csv"
RATIONALE_OUT="${DIAG_TMPDIR}/agg-rationale.csv"

aggregate_diagnostic_scores "$TEST_DIAG_RESULTS" "$TEST_DIAG_CSV" "$SCORES_OUT" "$RATIONALE_OUT" "test-scene"
assert_exit_code "0" "$?" "aggregate succeeds"

assert_file_exists "$SCORES_OUT" "scores file created"
assert_file_exists "$RATIONALE_OUT" "rationale file created"

# Check scores: alpha=3 (ratio 0.50), beta=5 (ratio 0)
scores_header=$(head -1 "$SCORES_OUT")
assert_contains "$scores_header" "alpha" "scores header contains alpha"
assert_contains "$scores_header" "beta" "scores header contains beta"

scores_row=$(tail -1 "$SCORES_OUT")
assert_contains "$scores_row" "test-scene" "scores row has scene id"
# Extract score values
alpha_score=$(echo "$scores_row" | awk -F'|' '{ print $2 }')
beta_score=$(echo "$scores_row" | awk -F'|' '{ print $3 }')
assert_equals "3" "$alpha_score" "alpha scores 3 (ratio 0.50)"
assert_equals "5" "$beta_score" "beta scores 5 (no deficits)"

# ============================================================================
# aggregate_diagnostic_scores — all deficits
# ============================================================================

echo "  -- aggregate: all deficits --"

ALL_DEF="${DIAG_TMPDIR}/.diag-all-def.csv"
cat > "$ALL_DEF" <<'EOF'
marker_id|answer|evidence
a-1|YES|"problem 1"
a-2|YES|"problem 2"
a-3|YES|"missing good thing"
b-1|YES|"b problem"
b-2|YES|"b problem 2"
EOF

SCORES_OUT2="${DIAG_TMPDIR}/agg-scores-2.csv"
RATIONALE_OUT2="${DIAG_TMPDIR}/agg-rationale-2.csv"

aggregate_diagnostic_scores "$ALL_DEF" "$TEST_DIAG_CSV" "$SCORES_OUT2" "$RATIONALE_OUT2" "bad-scene"
scores_row2=$(tail -1 "$SCORES_OUT2")
alpha_score2=$(echo "$scores_row2" | awk -F'|' '{ print $2 }')
beta_score2=$(echo "$scores_row2" | awk -F'|' '{ print $3 }')
assert_equals "1" "$alpha_score2" "all deficits: alpha scores 1 (ratio 1.0)"
assert_equals "1" "$beta_score2" "all deficits: beta scores 1 (ratio 1.0)"

# ============================================================================
# aggregate_diagnostic_scores — no deficits
# ============================================================================

echo "  -- aggregate: no deficits --"

NO_DEF="${DIAG_TMPDIR}/.diag-no-def.csv"
cat > "$NO_DEF" <<'EOF'
marker_id|answer|evidence
a-1|NO|CLEAN
a-2|NO|CLEAN
a-3|NO|CLEAN
b-1|NO|CLEAN
b-2|NO|CLEAN
EOF

SCORES_OUT3="${DIAG_TMPDIR}/agg-scores-3.csv"
RATIONALE_OUT3="${DIAG_TMPDIR}/agg-rationale-3.csv"

aggregate_diagnostic_scores "$NO_DEF" "$TEST_DIAG_CSV" "$SCORES_OUT3" "$RATIONALE_OUT3" "good-scene"
scores_row3=$(tail -1 "$SCORES_OUT3")
alpha_score3=$(echo "$scores_row3" | awk -F'|' '{ print $2 }')
beta_score3=$(echo "$scores_row3" | awk -F'|' '{ print $3 }')
assert_equals "5" "$alpha_score3" "no deficits: alpha scores 5"
assert_equals "5" "$beta_score3" "no deficits: beta scores 5"

# ============================================================================
# identify_deep_dive_targets
# ============================================================================

echo "  -- identify_deep_dive_targets --"

# Using the first test case: alpha=3, beta=5
# Threshold default=3, so alpha should be a target, beta should not
targets=$(identify_deep_dive_targets "$TEST_DIAG_RESULTS" "$TEST_DIAG_CSV" 3)
assert_not_empty "$targets" "targets found for deficit principles"
assert_contains "$targets" "alpha" "alpha is a deep-dive target (score 3)"

# beta should NOT be a target (score 5)
beta_in_targets=$(echo "$targets" | grep "^beta|" || true)
assert_empty "$beta_in_targets" "beta is not a deep-dive target (score 5)"

# Check target format
alpha_target=$(echo "$targets" | grep "^alpha|")
assert_contains "$alpha_target" "a-1" "alpha target includes deficit marker a-1"

# With threshold=5, both should be targets
targets_all=$(identify_deep_dive_targets "$TEST_DIAG_RESULTS" "$TEST_DIAG_CSV" 5)
assert_contains "$targets_all" "alpha" "threshold 5: alpha is target"
assert_contains "$targets_all" "beta" "threshold 5: beta is target"

# With no-deficits file, no targets at any threshold
targets_none=$(identify_deep_dive_targets "$NO_DEF" "$TEST_DIAG_CSV" 3)
assert_empty "$targets_none" "no deficits: no deep-dive targets"

# ============================================================================
# build_principle_guide
# ============================================================================

echo "  -- build_principle_guide --"

GUIDE_FILE="${PLUGIN_DIR}/references/principle-guide.md"
if [[ -f "$GUIDE_FILE" ]]; then
    guide=$(build_principle_guide "enter_late_leave_early" "$GUIDE_FILE")
    assert_not_empty "$guide" "guide found for enter_late_leave_early"
    assert_contains "$guide" "When it works" "guide contains 'When it works'"
    assert_contains "$guide" "When it fails" "guide contains 'When it fails'"
    assert_contains "$guide" "What to look for" "guide contains 'What to look for'"

    guide_ec=$(build_principle_guide "economy_clarity" "$GUIDE_FILE")
    assert_not_empty "$guide_ec" "guide found for economy_clarity"

    guide_kd=$(build_principle_guide "kill_darlings" "$GUIDE_FILE")
    assert_not_empty "$guide_kd" "guide found for kill_darlings"

    # Non-existent principle should return empty
    guide_fake=$(build_principle_guide "nonexistent_principle" "$GUIDE_FILE")
    assert_empty "$guide_fake" "no guide for nonexistent principle"
else
    echo "  SKIP: principle-guide.md not found"
fi

# ============================================================================
# Cleanup
# ============================================================================

rm -rf "$DIAG_TMPDIR"
