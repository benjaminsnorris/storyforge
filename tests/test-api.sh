#!/bin/bash
# test-api.sh — Tests for api.sh API helper functions

# ============================================================================
# Setup
# ============================================================================

API_TMP="$(mktemp -d)"
trap 'rm -rf "$API_TMP"' EXIT

# ============================================================================
# extract_api_response
# ============================================================================

echo "  --- extract_api_response ---"

# Test: extracts text from valid API response
cat > "${API_TMP}/response.json" <<'JSON'
{"content":[{"type":"text","text":"Hello world"}],"usage":{"input_tokens":10,"output_tokens":5}}
JSON
result=$(extract_api_response "${API_TMP}/response.json")
assert_equals "Hello world" "$result" "extract_api_response: extracts text content"

# Test: handles multi-block response
cat > "${API_TMP}/multi.json" <<'JSON'
{"content":[{"type":"text","text":"Part 1"},{"type":"text","text":"Part 2"}],"usage":{"input_tokens":10,"output_tokens":5}}
JSON
result=$(extract_api_response "${API_TMP}/multi.json")
assert_contains "$result" "Part 1" "extract_api_response: multi-block includes first"
assert_contains "$result" "Part 2" "extract_api_response: multi-block includes second"

# Test: returns failure for missing file
extract_api_response "${API_TMP}/nonexistent.json" > /dev/null 2>&1
rc=$?
assert_equals "1" "$rc" "extract_api_response: returns 1 for missing file"

# ============================================================================
# extract_api_usage
# ============================================================================

echo "  --- extract_api_usage ---"

# Test: extracts usage data with all fields
cat > "${API_TMP}/usage.json" <<'JSON'
{"content":[{"type":"text","text":"test"}],"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":25,"cache_creation_input_tokens":10}}
JSON
result=$(extract_api_usage "${API_TMP}/usage.json")
assert_equals "100|50|25|10" "$result" "extract_api_usage: extracts all token counts"

# Test: handles missing cache fields
cat > "${API_TMP}/no-cache.json" <<'JSON'
{"content":[{"type":"text","text":"test"}],"usage":{"input_tokens":100,"output_tokens":50}}
JSON
result=$(extract_api_usage "${API_TMP}/no-cache.json")
assert_equals "100|50|0|0" "$result" "extract_api_usage: defaults cache to 0"

# Test: returns failure for missing file
extract_api_usage "${API_TMP}/nonexistent.json" > /dev/null 2>&1
rc=$?
assert_equals "1" "$rc" "extract_api_usage: returns 1 for missing file"

# ============================================================================
# _extract_headless_response
# ============================================================================

echo "  --- _extract_headless_response ---"

# Test: extracts from API JSON format
cat > "${API_TMP}/api-format.json" <<'JSON'
{"content":[{"type":"text","text":"API response text"}],"usage":{"input_tokens":10,"output_tokens":5}}
JSON
result=$(_extract_headless_response "${API_TMP}/api-format.json")
assert_equals "API response text" "$result" "_extract_headless_response: handles API format"

# Test: returns failure for missing file
_extract_headless_response "${API_TMP}/missing.json" > /dev/null 2>&1
rc=$?
assert_equals "1" "$rc" "_extract_headless_response: returns 1 for missing file"

# ============================================================================
# log_api_usage
# ============================================================================

echo "  --- log_api_usage ---"

# Test: appends cost row to ledger
PROJECT_DIR="${API_TMP}/project"
mkdir -p "${PROJECT_DIR}/working/costs"

cat > "${API_TMP}/api-log.json" <<'JSON'
{"content":[{"type":"text","text":"test"}],"usage":{"input_tokens":1000,"output_tokens":500,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}
JSON

_SF_INVOCATION_START=$(date +%s)
log_api_usage "${API_TMP}/api-log.json" "test-op" "test-target" "claude-sonnet-4-6"

ledger="${PROJECT_DIR}/working/costs/ledger.csv"
assert_file_exists "$ledger" "log_api_usage: creates ledger file"

# Check header
header=$(head -1 "$ledger")
assert_contains "$header" "timestamp|operation" "log_api_usage: ledger has header"

# Check data row
row_count=$(wc -l < "$ledger" | tr -d ' ')
assert_equals "2" "$row_count" "log_api_usage: ledger has header + 1 row"

data_row=$(tail -1 "$ledger")
assert_contains "$data_row" "test-op|test-target|claude-sonnet-4-6|1000|500" \
    "log_api_usage: row contains correct operation, target, model, tokens"
