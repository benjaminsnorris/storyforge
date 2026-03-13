#!/bin/bash
# test-costs.sh — Tests for scripts/lib/costs.sh
#
# Sourced by run-tests.sh which provides assertion functions,
# FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, and TMPDIR.

# Use a temp directory for test ledger files
COST_TMPDIR="${TMPDIR}/cost-tests-$$"
mkdir -p "$COST_TMPDIR"

# ============================================================================
# get_model_pricing tests
# ============================================================================

echo "  -- get_model_pricing --"

result="$(get_model_pricing "claude-opus-4" "input")"
assert_equals "15.00" "$result" "opus input pricing"

result="$(get_model_pricing "claude-opus-4" "output")"
assert_equals "75.00" "$result" "opus output pricing"

result="$(get_model_pricing "claude-opus-4" "cache_read")"
assert_equals "1.50" "$result" "opus cache_read pricing"

result="$(get_model_pricing "claude-opus-4" "cache_create")"
assert_equals "18.75" "$result" "opus cache_create pricing"

result="$(get_model_pricing "claude-sonnet-4" "input")"
assert_equals "3.00" "$result" "sonnet input pricing"

result="$(get_model_pricing "claude-sonnet-4" "output")"
assert_equals "15.00" "$result" "sonnet output pricing"

result="$(get_model_pricing "claude-sonnet-4" "cache_read")"
assert_equals "0.30" "$result" "sonnet cache_read pricing"

result="$(get_model_pricing "claude-sonnet-4" "cache_create")"
assert_equals "3.75" "$result" "sonnet cache_create pricing"

result="$(get_model_pricing "some-model" "input")"
assert_equals "3.00" "$result" "unknown model defaults to sonnet pricing"

result="$(get_model_pricing "claude-opus-4" "unknown_type")"
assert_equals "0.00" "$result" "unknown token type returns 0"

# ============================================================================
# log_usage tests — with mock stream-json log
# ============================================================================

echo "  -- log_usage with mock log --"

# Create mock stream-json log with usage data
MOCK_LOG="${COST_TMPDIR}/mock-stream.json"
cat > "$MOCK_LOG" <<'MOCKEOF'
{"type":"content_block_delta","delta":{"text":"Hello"}}
{"type":"message_delta","usage":{"input_tokens":1000,"output_tokens":500,"cache_read_input_tokens":200,"cache_creation_input_tokens":100}}
MOCKEOF

LEDGER="${COST_TMPDIR}/ledger.csv"

# Save and set PROJECT_DIR for this test
_OLD_PROJECT_DIR="$PROJECT_DIR"
export PROJECT_DIR="$COST_TMPDIR"

log_usage "$MOCK_LOG" "draft" "chapter-01" "claude-sonnet-4" "$LEDGER"

assert_file_exists "$LEDGER" "ledger file created"

# Check header
header="$(head -1 "$LEDGER")"
assert_equals "timestamp|operation|target|model|input_tokens|output_tokens|cache_read|cache_create|cost_usd|duration_s" "$header" "ledger has correct header"

# Check data row
data_row="$(tail -1 "$LEDGER")"
assert_contains "$data_row" "|draft|chapter-01|claude-sonnet-4|" "ledger row has correct operation/target/model"
assert_contains "$data_row" "|1000|500|200|100|" "ledger row has correct token counts"
assert_matches "$data_row" "[0-9]\.[0-9]" "ledger row has cost value"

# Verify cost calculation: (1000*3/1M) + (500*15/1M) + (200*0.3/1M) + (100*3.75/1M)
# = 0.003 + 0.0075 + 0.00006 + 0.000375 = 0.010935
assert_contains "$data_row" "|0.010935|" "ledger row has correct computed cost"

# ============================================================================
# log_usage with missing log file
# ============================================================================

echo "  -- log_usage with missing log --"

LEDGER2="${COST_TMPDIR}/ledger2.csv"
log_usage "/nonexistent/file.json" "evaluate" "chapter-02" "claude-opus-4" "$LEDGER2"

assert_file_exists "$LEDGER2" "ledger created even with missing log"

data_row2="$(tail -1 "$LEDGER2")"
assert_contains "$data_row2" "|evaluate|chapter-02|claude-opus-4|0|0|0|0|0.000000|" "missing log writes zero-cost row"

# ============================================================================
# log_usage with empty log file
# ============================================================================

echo "  -- log_usage with empty log --"

EMPTY_LOG="${COST_TMPDIR}/empty.json"
touch "$EMPTY_LOG"

LEDGER3="${COST_TMPDIR}/ledger3.csv"
log_usage "$EMPTY_LOG" "revise" "chapter-03" "claude-sonnet-4" "$LEDGER3"

data_row3="$(tail -1 "$LEDGER3")"
assert_contains "$data_row3" "|revise|chapter-03|claude-sonnet-4|0|0|0|0|0.000000|" "empty log writes zero-cost row"

# ============================================================================
# log_usage appends multiple rows
# ============================================================================

echo "  -- log_usage appends multiple rows --"

log_usage "$MOCK_LOG" "draft" "chapter-04" "claude-sonnet-4" "$LEDGER"

row_count="$(awk 'END { print NR }' "$LEDGER")"
assert_equals "3" "$row_count" "ledger has header + 2 data rows after two log_usage calls"

# ============================================================================
# log_usage with _SF_INVOCATION_START
# ============================================================================

echo "  -- log_usage duration tracking --"

LEDGER_DUR="${COST_TMPDIR}/ledger-dur.csv"
export _SF_INVOCATION_START="$(($(date +%s) - 42))"
log_usage "$MOCK_LOG" "draft" "chapter-05" "claude-sonnet-4" "$LEDGER_DUR"
unset _SF_INVOCATION_START

dur_row="$(tail -1 "$LEDGER_DUR")"
assert_matches "$dur_row" "\|4[0-9]\$" "duration ~42 seconds recorded"

# ============================================================================
# estimate_cost tests
# ============================================================================

echo "  -- estimate_cost --"

# draft: 5 scenes, 2000 avg words, sonnet
# input = 5 * (2000*1.3 + 3000) = 5 * 5600 = 28000
# output = 5 * 1500 = 7500
# cost = (28000 * 3/1M) + (7500 * 15/1M) = 0.084 + 0.1125 = 0.1965
result="$(estimate_cost "draft" 5 2000 "claude-sonnet-4")"
assert_equals "0.20" "$result" "draft estimate for 5 scenes"

# evaluate: 10 scenes, 3000 avg words, opus
# input = 10 * (3000*1.3 + 3000) = 10 * 6900 = 69000
# output = 10 * 2000 = 20000
# cost = (69000 * 15/1M) + (20000 * 75/1M) = 1.035 + 1.5 = 2.535
result="$(estimate_cost "evaluate" 10 3000 "claude-opus-4")"
assert_equals "2.54" "$result" "evaluate estimate for 10 scenes with opus"

# revise: 1 scene, 1000 words, sonnet
# input = 1 * (1000*1.3 + 3000) = 4300
# output = 1 * 1000 = 1000
# cost = (4300 * 3/1M) + (1000 * 15/1M) = 0.0129 + 0.015 = 0.0279
result="$(estimate_cost "revise" 1 1000 "claude-sonnet-4")"
assert_equals "0.03" "$result" "revise estimate for 1 scene"

# Zero scope should return 0
result="$(estimate_cost "draft" 0 2000 "claude-sonnet-4")"
assert_equals "0.00" "$result" "zero scope returns zero cost"

# ============================================================================
# check_cost_threshold tests
# ============================================================================

echo "  -- check_cost_threshold --"

# Under threshold — should return 0
export STORYFORGE_COST_THRESHOLD=100
check_cost_threshold "5.00"
assert_equals "0" "$?" "under threshold returns 0"

check_cost_threshold "99.99"
assert_equals "0" "$?" "just under threshold returns 0"

# Over threshold, non-interactive (stdin is not a tty in tests) — should return 0
check_cost_threshold "150.00"
assert_equals "0" "$?" "over threshold non-interactive returns 0 (auto-proceed)"

# At exactly threshold — should return 0
check_cost_threshold "100.00"
assert_equals "0" "$?" "at threshold returns 0"

unset STORYFORGE_COST_THRESHOLD

# ============================================================================
# print_cost_summary tests
# ============================================================================

echo "  -- print_cost_summary --"

# Build a ledger with known data
SUMMARY_LEDGER="${COST_TMPDIR}/summary-ledger.csv"
echo "timestamp|operation|target|model|input_tokens|output_tokens|cache_read|cache_create|cost_usd|duration_s" > "$SUMMARY_LEDGER"
echo "2026-03-12T10:00:00|draft|ch01|claude-sonnet-4|1000|500|0|0|0.010500|30" >> "$SUMMARY_LEDGER"
echo "2026-03-12T10:01:00|draft|ch02|claude-sonnet-4|2000|800|100|0|0.018030|45" >> "$SUMMARY_LEDGER"
echo "2026-03-12T10:02:00|evaluate|ch01|claude-opus-4|3000|1000|0|0|0.120000|60" >> "$SUMMARY_LEDGER"

summary="$(print_cost_summary "draft" "$SUMMARY_LEDGER")"
assert_contains "$summary" "Cost Summary: draft" "summary shows operation name"
assert_contains "$summary" "Invocations:  2" "summary shows correct invocation count"
assert_contains "$summary" "Input tokens: 3000" "summary shows total input tokens"
assert_contains "$summary" "Output tokens: 1300" "summary shows total output tokens"
assert_contains "$summary" "Cache read:   100" "summary shows total cache read"
assert_contains "$summary" "Total cost:   \$0.0285" "summary shows total cost"
assert_contains "$summary" "Total time:   75s" "summary shows total duration"

# Summary for operation with no data
summary_empty="$(print_cost_summary "assemble" "$SUMMARY_LEDGER")"
assert_contains "$summary_empty" "No cost data for operation: assemble" "summary handles missing operation"

# Summary with missing ledger file
summary_missing="$(print_cost_summary "draft" "/nonexistent/ledger.csv")"
assert_contains "$summary_missing" "No cost data available" "summary handles missing file"

# Restore PROJECT_DIR
export PROJECT_DIR="$_OLD_PROJECT_DIR"

# Cleanup
rm -rf "$COST_TMPDIR"
