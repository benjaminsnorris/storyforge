#!/bin/bash
# test-python.sh — Tests for Python core modules (parsing, api)

PYTHON_DIR="${PLUGIN_DIR}/scripts/lib/python"

# ============================================================================
# storyforge.parsing
# ============================================================================

echo "  --- parsing: extract_scenes_from_response ---"

PARSE_TMP="$(mktemp -d)"

# Create a mock response with scene markers
cat > "${PARSE_TMP}/response.json" <<'JSON'
{"content":[{"type":"text","text":"Here is the revision.\n\n=== SCENE: test-scene-1 ===\nFirst scene content.\nSecond line.\n=== END SCENE: test-scene-1 ===\n\n=== SCENE: test-scene-2 ===\nAnother scene.\n=== END SCENE: test-scene-2 ===\n\nSummary text here."}],"usage":{"input_tokens":100,"output_tokens":50}}
JSON

mkdir -p "${PARSE_TMP}/scenes"
result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.parsing extract-scenes "${PARSE_TMP}/response.json" "${PARSE_TMP}/scenes" 2>/dev/null)
assert_contains "$result" "Wrote: test-scene-1" "parsing: extracts first scene"
assert_contains "$result" "Wrote: test-scene-2" "parsing: extracts second scene"
assert_contains "$result" "Total: 2" "parsing: reports correct count"
assert_file_exists "${PARSE_TMP}/scenes/test-scene-1.md" "parsing: creates scene file 1"
assert_file_exists "${PARSE_TMP}/scenes/test-scene-2.md" "parsing: creates scene file 2"

scene1=$(cat "${PARSE_TMP}/scenes/test-scene-1.md")
assert_contains "$scene1" "First scene content" "parsing: scene 1 has correct content"
assert_not_contains "$scene1" "=== SCENE:" "parsing: scene 1 no markers in content"

# Test: skip parenthetical entries
cat > "${PARSE_TMP}/response-parens.json" <<'JSON'
{"content":[{"type":"text","text":"=== SCENE: my-scene ===\nOriginal.\n=== END SCENE: my-scene ===\n\n=== SCENE: my-scene (revised note) ===\nShould be skipped.\n=== END SCENE: my-scene (revised note) ==="}],"usage":{"input_tokens":10,"output_tokens":5}}
JSON

rm -f "${PARSE_TMP}/scenes/"*
result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.parsing extract-scenes "${PARSE_TMP}/response-parens.json" "${PARSE_TMP}/scenes" 2>/dev/null)
assert_contains "$result" "Total: 1" "parsing: skips parenthetical entries"
# Should NOT create a file with parens in the name
if [[ -f "${PARSE_TMP}/scenes/my-scene (revised note).md" ]]; then
    FAIL=$((FAIL + 1))
    echo "  FAIL: parsing: should not create parenthetical scene file"
else
    PASS=$((PASS + 1))
    echo "  PASS: parsing: no parenthetical scene file created"
fi

echo "  --- parsing: extract_single_scene ---"

cat > "${PARSE_TMP}/single.json" <<'JSON'
{"content":[{"type":"text","text":"Some analysis.\n\n=== SCENE: drafted-scene ===\nThe prose goes here.\nMore prose.\n=== END SCENE: drafted-scene ===\n\nNotes about the scene."}],"usage":{"input_tokens":10,"output_tokens":5}}
JSON

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.parsing extract-single "${PARSE_TMP}/single.json" "${PARSE_TMP}/output.md" 2>/dev/null)
assert_file_exists "${PARSE_TMP}/output.md" "parsing: single extraction creates file"
content=$(cat "${PARSE_TMP}/output.md")
assert_contains "$content" "The prose goes here" "parsing: single extraction has prose"
assert_not_contains "$content" "=== SCENE:" "parsing: single extraction no markers"
assert_not_contains "$content" "Notes about" "parsing: single extraction no trailing text"

# ============================================================================
# storyforge.api (non-network functions only)
# ============================================================================

echo "  --- api: extract_text_from_file ---"

cat > "${PARSE_TMP}/api-response.json" <<'JSON'
{"content":[{"type":"text","text":"Hello world"}],"usage":{"input_tokens":10,"output_tokens":5}}
JSON

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.api extract-text "${PARSE_TMP}/api-response.json" 2>/dev/null)
assert_equals "Hello world" "$result" "api: extracts text from response"

echo "  --- api: log_usage ---"

PROJECT_DIR="${PARSE_TMP}/project"
mkdir -p "${PROJECT_DIR}/working/costs"
export PROJECT_DIR

cat > "${PARSE_TMP}/usage-response.json" <<'JSON'
{"content":[{"type":"text","text":"test"}],"usage":{"input_tokens":1000,"output_tokens":500,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}
JSON

PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.api log-usage "${PARSE_TMP}/usage-response.json" "test-op" "test-target" "claude-sonnet-4-6" 2>/dev/null
ledger="${PROJECT_DIR}/working/costs/ledger.csv"
assert_file_exists "$ledger" "api: log_usage creates ledger"

row_count=$(wc -l < "$ledger" | tr -d ' ')
assert_equals "2" "$row_count" "api: ledger has header + 1 row"

data_row=$(tail -1 "$ledger")
assert_contains "$data_row" "test-op|test-target|claude-sonnet-4-6|1000|500" "api: row has correct data"

rm -rf "$PARSE_TMP"
