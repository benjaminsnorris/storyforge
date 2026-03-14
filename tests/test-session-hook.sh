#!/bin/bash
# test-session-hook.sh — Tests for hooks/session-end
#
# Sourced by run-tests.sh which provides assertion functions,
# FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, and TMPDIR.

# Skip if jq not available
if ! command -v jq &>/dev/null; then
    echo "  SKIP: jq not installed"
    return 0
fi

HOOK_SCRIPT="${PLUGIN_DIR}/hooks/session-end"
HOOK_TMPDIR="${TMPDIR}/hook-tests-$$"
mkdir -p "$HOOK_TMPDIR"

# Create a mock storyforge project
MOCK_PROJECT="${HOOK_TMPDIR}/mock-project"
mkdir -p "${MOCK_PROJECT}/working/costs"
echo "project:" > "${MOCK_PROJECT}/storyforge.yaml"

# ============================================================================
# Helper: run the hook with given input
# ============================================================================
run_hook() {
    local input="$1"
    echo "$input" | "$HOOK_SCRIPT"
}

# ============================================================================
# Build mock transcript
# ============================================================================

echo "  -- session-end hook --"

TRANSCRIPT="${HOOK_TMPDIR}/transcript.jsonl"
cat > "$TRANSCRIPT" <<'JSONL'
{"type":"user","message":{"text":"hello"}}
{"type":"assistant","message":{"model":"claude-opus-4-6","usage":{"input_tokens":1000,"output_tokens":500,"cache_read_input_tokens":200,"cache_creation_input_tokens":100}}}
{"type":"user","message":{"text":"thanks"}}
{"type":"assistant","message":{"model":"claude-opus-4-6","usage":{"input_tokens":2000,"output_tokens":800,"cache_read_input_tokens":300,"cache_creation_input_tokens":0}}}
JSONL

# ============================================================================
# Basic functionality: single model
# ============================================================================

LEDGER="${MOCK_PROJECT}/working/costs/ledger.csv"
rm -f "$LEDGER"

INPUT=$(jq -n \
    --arg sid "test-session-001" \
    --arg tp "$TRANSCRIPT" \
    --arg cwd "$MOCK_PROJECT" \
    '{session_id: $sid, transcript_path: $tp, cwd: $cwd, reason: "prompt_input_exit"}')

run_hook "$INPUT"

assert_file_exists "$LEDGER" "hook creates ledger file"

# Check header
header=$(head -1 "$LEDGER")
assert_equals "timestamp|operation|target|model|input_tokens|output_tokens|cache_read|cache_create|cost_usd|duration_s" "$header" "ledger has correct header"

# Check data row — should have summed tokens: 3000 input, 1300 output, 500 cache_read, 100 cache_create
data_row=$(tail -1 "$LEDGER")
assert_contains "$data_row" "|interactive|test-session-001|claude-opus-4-6|" "row has correct operation/target/model"
assert_contains "$data_row" "|3000|1300|500|100|" "row has correct summed token counts"

# Verify cost: (3000*15/1M) + (1300*75/1M) + (500*1.5/1M) + (100*18.75/1M)
# = 0.045 + 0.0975 + 0.00075 + 0.001875 = 0.145125
assert_contains "$data_row" "|0.145125|" "row has correct computed cost"

# ============================================================================
# Multiple models in one session
# ============================================================================

echo "  -- multiple models --"

TRANSCRIPT_MULTI="${HOOK_TMPDIR}/transcript-multi.jsonl"
cat > "$TRANSCRIPT_MULTI" <<'JSONL'
{"type":"assistant","message":{"model":"claude-opus-4-6","usage":{"input_tokens":1000,"output_tokens":500,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"assistant","message":{"model":"claude-haiku-4-5-20251001","usage":{"input_tokens":2000,"output_tokens":1000,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"assistant","message":{"model":"claude-opus-4-6","usage":{"input_tokens":1000,"output_tokens":500,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
JSONL

LEDGER_MULTI="${MOCK_PROJECT}/working/costs/ledger-multi.csv"
rm -f "$LEDGER_MULTI"

# Point ledger to a fresh file by using a separate project dir
MOCK_PROJECT_MULTI="${HOOK_TMPDIR}/mock-project-multi"
mkdir -p "${MOCK_PROJECT_MULTI}/working/costs"
echo "project:" > "${MOCK_PROJECT_MULTI}/storyforge.yaml"

INPUT_MULTI=$(jq -n \
    --arg sid "test-session-002" \
    --arg tp "$TRANSCRIPT_MULTI" \
    --arg cwd "$MOCK_PROJECT_MULTI" \
    '{session_id: $sid, transcript_path: $tp, cwd: $cwd, reason: "other"}')

run_hook "$INPUT_MULTI"

LEDGER_MULTI="${MOCK_PROJECT_MULTI}/working/costs/ledger.csv"
row_count=$(awk 'END { print NR }' "$LEDGER_MULTI")
assert_equals "3" "$row_count" "multi-model session produces header + 2 data rows"

# Check opus row: 2000 input, 1000 output
opus_row=$(grep "opus" "$LEDGER_MULTI")
assert_contains "$opus_row" "|2000|1000|0|0|" "opus row has summed tokens"

# Check haiku row: 2000 input, 1000 output
haiku_row=$(grep "haiku" "$LEDGER_MULTI")
assert_contains "$haiku_row" "|2000|1000|0|0|" "haiku row has correct tokens"

# Haiku cost: (2000*0.8/1M) + (1000*4/1M) = 0.0016 + 0.004 = 0.0056
assert_contains "$haiku_row" "|0.005600|" "haiku row has correct cost"

# ============================================================================
# Guard: not a storyforge project
# ============================================================================

echo "  -- guards --"

NON_PROJECT="${HOOK_TMPDIR}/not-a-project"
mkdir -p "$NON_PROJECT"

INPUT_NOPROJECT=$(jq -n \
    --arg sid "test-session-003" \
    --arg tp "$TRANSCRIPT" \
    --arg cwd "$NON_PROJECT" \
    '{session_id: $sid, transcript_path: $tp, cwd: $cwd, reason: "other"}')

run_hook "$INPUT_NOPROJECT"
# Should exit silently — no ledger created
assert_equals "false" "$([ -f "${NON_PROJECT}/working/costs/ledger.csv" ] && echo true || echo false)" "no ledger in non-storyforge project"

# ============================================================================
# Guard: missing transcript
# ============================================================================

INPUT_NOTRANSCRIPT=$(jq -n \
    --arg sid "test-session-004" \
    --arg tp "/nonexistent/transcript.jsonl" \
    --arg cwd "$MOCK_PROJECT" \
    '{session_id: $sid, transcript_path: $tp, cwd: $cwd, reason: "other"}')

# Should not error
run_hook "$INPUT_NOTRANSCRIPT"
assert_exit_code "0" "$?" "missing transcript exits cleanly"

# ============================================================================
# Guard: empty transcript (no assistant records)
# ============================================================================

TRANSCRIPT_EMPTY="${HOOK_TMPDIR}/transcript-empty.jsonl"
echo '{"type":"user","message":{"text":"hello"}}' > "$TRANSCRIPT_EMPTY"

MOCK_PROJECT_EMPTY="${HOOK_TMPDIR}/mock-project-empty"
mkdir -p "$MOCK_PROJECT_EMPTY"
echo "project:" > "${MOCK_PROJECT_EMPTY}/storyforge.yaml"

INPUT_EMPTY=$(jq -n \
    --arg sid "test-session-005" \
    --arg tp "$TRANSCRIPT_EMPTY" \
    --arg cwd "$MOCK_PROJECT_EMPTY" \
    '{session_id: $sid, transcript_path: $tp, cwd: $cwd, reason: "other"}')

run_hook "$INPUT_EMPTY"
assert_equals "false" "$([ -f "${MOCK_PROJECT_EMPTY}/working/costs/ledger.csv" ] && echo true || echo false)" "empty transcript creates no ledger"

# ============================================================================
# Guard: missing fields in input
# ============================================================================

run_hook '{"session_id": "x"}'
assert_exit_code "0" "$?" "partial input exits cleanly"

run_hook '{}'
assert_exit_code "0" "$?" "empty JSON exits cleanly"

# ============================================================================
# Haiku pricing in costs.sh
# ============================================================================

echo "  -- haiku pricing in costs.sh --"

result="$(get_model_pricing "claude-haiku-4-5" "input")"
assert_equals "0.80" "$result" "haiku input pricing"

result="$(get_model_pricing "claude-haiku-4-5" "output")"
assert_equals "4.00" "$result" "haiku output pricing"

result="$(get_model_pricing "claude-haiku-4-5" "cache_read")"
assert_equals "0.08" "$result" "haiku cache_read pricing"

result="$(get_model_pricing "claude-haiku-4-5" "cache_create")"
assert_equals "1.00" "$result" "haiku cache_create pricing"

# ============================================================================
# Cleanup
# ============================================================================

rm -rf "$HOOK_TMPDIR"
