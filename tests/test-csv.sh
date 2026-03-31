#!/bin/bash
# test-csv.sh — Tests for CSV library functions (scripts/lib/csv.sh)
#
# Run via: ./tests/run-tests.sh
# Depends on: FIXTURE_DIR, PROJECT_DIR, assertion functions (from run-tests.sh)

META_CSV="${FIXTURE_DIR}/reference/scene-metadata.csv"
INTENT_CSV="${FIXTURE_DIR}/reference/scene-intent.csv"

# ============================================================================
# get_csv_field
# ============================================================================

result=$(get_csv_field "$META_CSV" "act1-sc01" "title")
assert_equals "The Finest Cartographer" "$result" "get_csv_field: title of act1-sc01"

result=$(get_csv_field "$META_CSV" "act1-sc01" "word_count")
assert_equals "2400" "$result" "get_csv_field: word_count of act1-sc01"

result=$(get_csv_field "$META_CSV" "act2-sc01" "status")
assert_equals "pending" "$result" "get_csv_field: status of act2-sc01"

result=$(get_csv_field "$META_CSV" "act1-sc02" "pov")
assert_equals "Dorren Hayle" "$result" "get_csv_field: pov of act1-sc02"

result=$(get_csv_field "$META_CSV" "new-x1" "type")
assert_equals "plot" "$result" "get_csv_field: type of new-x1"

# Nonexistent ID returns empty
result=$(get_csv_field "$META_CSV" "no-such-id" "title")
assert_empty "$result" "get_csv_field: nonexistent ID returns empty"

# Nonexistent field returns empty
result=$(get_csv_field "$META_CSV" "act1-sc01" "nonexistent")
assert_empty "$result" "get_csv_field: nonexistent field returns empty"

# Missing file returns empty
result=$(get_csv_field "/tmp/nonexistent-csv-$$" "act1-sc01" "title")
assert_empty "$result" "get_csv_field: missing file returns empty"

# ============================================================================
# get_csv_row
# ============================================================================

result=$(get_csv_row "$META_CSV" "act1-sc01")
assert_contains "$result" "act1-sc01" "get_csv_row: contains id"
assert_contains "$result" "The Finest Cartographer" "get_csv_row: contains title"
assert_contains "$result" "2400" "get_csv_row: contains word_count"

result=$(get_csv_row "$META_CSV" "act2-sc01")
assert_contains "$result" "Tessa Merrin" "get_csv_row: act2-sc01 contains pov"

# Nonexistent ID
result=$(get_csv_row "$META_CSV" "no-such-id")
assert_empty "$result" "get_csv_row: nonexistent ID returns empty"

# Missing file
result=$(get_csv_row "/tmp/nonexistent-csv-$$" "act1-sc01")
assert_empty "$result" "get_csv_row: missing file returns empty"

# ============================================================================
# get_csv_column
# ============================================================================

result=$(get_csv_column "$META_CSV" "id")
assert_contains "$result" "act1-sc01" "get_csv_column: id column contains act1-sc01"
assert_contains "$result" "act2-sc01" "get_csv_column: id column contains act2-sc01"

result=$(get_csv_column "$META_CSV" "status")
assert_contains "$result" "drafted" "get_csv_column: status column contains drafted"
assert_contains "$result" "pending" "get_csv_column: status column contains pending"

line_count=$(get_csv_column "$META_CSV" "title" | wc -l | tr -d ' ')
assert_equals "4" "$line_count" "get_csv_column: title column has 4 rows"

# Nonexistent column
result=$(get_csv_column "$META_CSV" "nonexistent")
assert_empty "$result" "get_csv_column: nonexistent column returns empty"

# Missing file
result=$(get_csv_column "/tmp/nonexistent-csv-$$" "title")
assert_empty "$result" "get_csv_column: missing file returns empty"

# ============================================================================
# list_csv_ids
# ============================================================================

result=$(list_csv_ids "$META_CSV")
assert_contains "$result" "act1-sc01" "list_csv_ids: contains act1-sc01"
assert_contains "$result" "new-x1" "list_csv_ids: contains new-x1"
assert_contains "$result" "act2-sc01" "list_csv_ids: contains act2-sc01"

line_count=$(list_csv_ids "$META_CSV" | wc -l | tr -d ' ')
assert_equals "4" "$line_count" "list_csv_ids: returns 4 IDs"

# First ID should be act1-sc01 (file order)
first_id=$(list_csv_ids "$META_CSV" | head -1)
assert_equals "act1-sc01" "$first_id" "list_csv_ids: first ID is act1-sc01"

# Missing file
result=$(list_csv_ids "/tmp/nonexistent-csv-$$")
assert_empty "$result" "list_csv_ids: missing file returns empty"

# ============================================================================
# update_csv_field (uses a temp copy to avoid corrupting fixtures)
# ============================================================================

TMP_CSV=$(mktemp)
cp "$META_CSV" "$TMP_CSV"

# Update word_count for act1-sc02
update_csv_field "$TMP_CSV" "act1-sc02" "word_count" "2800"
result=$(get_csv_field "$TMP_CSV" "act1-sc02" "word_count")
assert_equals "2800" "$result" "update_csv_field: word_count updated to 2800"

# Other rows untouched
result=$(get_csv_field "$TMP_CSV" "act1-sc01" "word_count")
assert_equals "2400" "$result" "update_csv_field: other row unchanged"

# Update status
update_csv_field "$TMP_CSV" "act2-sc01" "status" "drafted"
result=$(get_csv_field "$TMP_CSV" "act2-sc01" "status")
assert_equals "drafted" "$result" "update_csv_field: status updated to drafted"

# Header row preserved
header=$(head -1 "$TMP_CSV")
assert_contains "$header" "id|seq|title" "update_csv_field: header preserved"

# Missing file is a no-op (no error)
update_csv_field "/tmp/nonexistent-csv-$$" "act1-sc01" "word_count" "999"
assert_equals "0" "$?" "update_csv_field: missing file returns 0"

rm -f "$TMP_CSV"

# ============================================================================
# append_csv_row (uses a temp copy)
# ============================================================================

TMP_CSV=$(mktemp)
cp "$META_CSV" "$TMP_CSV"

append_csv_row "$TMP_CSV" "act3-sc01|5|The Final Descent|Dorren Hayle|The Chasm|3|plot|5|night|planned|0|3000"

# New row readable
result=$(get_csv_field "$TMP_CSV" "act3-sc01" "title")
assert_equals "The Final Descent" "$result" "append_csv_row: new row title readable"

result=$(get_csv_field "$TMP_CSV" "act3-sc01" "status")
assert_equals "planned" "$result" "append_csv_row: new row status readable"

# ID count increased
line_count=$(list_csv_ids "$TMP_CSV" | wc -l | tr -d ' ')
assert_equals "5" "$line_count" "append_csv_row: now 5 IDs"

# Existing rows untouched
result=$(get_csv_field "$TMP_CSV" "act1-sc01" "title")
assert_equals "The Finest Cartographer" "$result" "append_csv_row: existing rows untouched"

# Missing file is a no-op
append_csv_row "/tmp/nonexistent-csv-$$" "test|row"
assert_equals "0" "$?" "append_csv_row: missing file returns 0"

rm -f "$TMP_CSV"

# ============================================================================
# Cross-file: intent.csv
# ============================================================================

result=$(get_csv_field "$INTENT_CSV" "act1-sc01" "function")
assert_equals "Establishes Dorren as institutional gatekeeper" "$result" "intent.csv: function field"

result=$(get_csv_field "$INTENT_CSV" "new-x1" "emotional_arc")
assert_equals "Scholarly calm to urgent alarm" "$result" "intent.csv: emotional_arc field"

result=$(list_csv_ids "$INTENT_CSV" | wc -l | tr -d ' ')
assert_equals "4" "$result" "intent.csv: 4 IDs"

# ============================================================================
# renumber_scenes
# ============================================================================

RN_CSV="${TMPDIR}/renumber-test-$$.csv"
cat > "$RN_CSV" <<'RNEOF'
id|seq|title|pov
scene-a|5|Scene A|Alice
scene-b|10|Scene B|Bob
scene-c|2|Scene C|Carol
RNEOF

renumber_scenes "$RN_CSV"
result=$(get_csv_field "$RN_CSV" "scene-c" "seq")
assert_equals "1" "$result" "renumber_scenes: lowest seq becomes 1"

result=$(get_csv_field "$RN_CSV" "scene-a" "seq")
assert_equals "2" "$result" "renumber_scenes: middle seq becomes 2"

result=$(get_csv_field "$RN_CSV" "scene-b" "seq")
assert_equals "3" "$result" "renumber_scenes: highest seq becomes 3"

# Verify other columns untouched
result=$(get_csv_field "$RN_CSV" "scene-a" "title")
assert_equals "Scene A" "$result" "renumber_scenes: title preserved"

rm -f "$RN_CSV"
