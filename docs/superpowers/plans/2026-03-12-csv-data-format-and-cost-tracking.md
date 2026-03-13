# CSV Data Format & Cost Tracking Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace YAML-based structured data with pipe-delimited CSV to reduce token usage, add per-invocation cost tracking with forecasting, and migrate four existing book projects to the new format.

**Architecture:** New CSV read/write library in `scripts/lib/csv.sh`, new cost tracking library in `scripts/lib/costs.sh`, new migration script `scripts/storyforge-migrate`. Existing scripts (`storyforge-write`, `storyforge-evaluate`, `storyforge-revise`, `storyforge-assemble`) updated to use CSV functions and log costs. Backward compatibility: CSV-first with YAML fallback during transition.

**Tech Stack:** Pure bash/awk/sed (no external dependencies). Pipe-delimited CSV files with `||` array delimiters. Stream-json parsing for token usage extraction.

**Spec:** `docs/superpowers/specs/2026-03-12-csv-data-format-and-cost-tracking-design.md`

---

## Chunk 1: CSV Library

### Task 1: Create CSV reading library

**Files:**
- Create: `scripts/lib/csv.sh`
- Create: `tests/test-csv.sh`

- [ ] **Step 1: Write failing tests for `get_csv_field`**

Create `tests/test-csv.sh` with tests that source the CSV library and test field lookup by ID:

```bash
#!/bin/bash
# test-csv.sh — Tests for CSV library functions

# --- get_csv_field ---
RESULT=$(get_csv_field "$FIXTURE_DIR/scenes/metadata.csv" "act1-sc01" "title")
assert_equals "The Finest Cartographer" "$RESULT" "get_csv_field: reads title by id"

RESULT=$(get_csv_field "$FIXTURE_DIR/scenes/metadata.csv" "act1-sc01" "seq")
assert_equals "1" "$RESULT" "get_csv_field: reads integer field"

RESULT=$(get_csv_field "$FIXTURE_DIR/scenes/metadata.csv" "act1-sc01" "pov")
assert_equals "Dorren Hayle" "$RESULT" "get_csv_field: reads field with spaces"

RESULT=$(get_csv_field "$FIXTURE_DIR/scenes/metadata.csv" "nonexistent" "title")
assert_empty "$RESULT" "get_csv_field: returns empty for missing id"

RESULT=$(get_csv_field "$FIXTURE_DIR/scenes/metadata.csv" "act1-sc01" "fakefield")
assert_empty "$RESULT" "get_csv_field: returns empty for missing field"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tests/run-tests.sh test-csv`
Expected: FAIL — csv.sh does not exist yet

- [ ] **Step 3: Create CSV library with `get_csv_field`**

Create `scripts/lib/csv.sh`:

```bash
#!/bin/bash
# csv.sh — Pipe-delimited CSV reading and writing utilities
#
# File format: pipe-delimited (|), double-pipe (||) for arrays within fields.
# First row is always the header. Schema-aware: only declared array columns
# interpret || as array separator.

# get_csv_field(file, id, field) — print a single field value for a given ID
# Uses awk to match the id column and extract the named column.
get_csv_field() {
    local file="$1" id="$2" field="$3"
    [[ ! -f "$file" ]] && return 0
    awk -F'|' -v id="$id" -v field="$field" '
        NR==1 {
            for (i=1; i<=NF; i++) {
                if ($i == field) col=i
                if ($i == "id") idcol=i
            }
            next
        }
        col && idcol && $idcol == id { print $col; exit }
    ' "$file"
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tests/run-tests.sh test-csv`
Expected: PASS (requires fixture CSV — see Step 7)

- [ ] **Step 5: Write failing tests for `get_csv_row`**

Add to `tests/test-csv.sh`:

```bash
# --- get_csv_row ---
RESULT=$(get_csv_row "$FIXTURE_DIR/scenes/metadata.csv" "act1-sc01")
assert_contains "$RESULT" "The Finest Cartographer" "get_csv_row: contains title"
assert_contains "$RESULT" "Dorren Hayle" "get_csv_row: contains pov"

RESULT=$(get_csv_row "$FIXTURE_DIR/scenes/metadata.csv" "nonexistent")
assert_empty "$RESULT" "get_csv_row: returns empty for missing id"
```

- [ ] **Step 6: Implement `get_csv_row`**

Add to `scripts/lib/csv.sh`:

```bash
# get_csv_row(file, id) — print all field values for a given ID as pipe-delimited string
get_csv_row() {
    local file="$1" id="$2"
    [[ ! -f "$file" ]] && return 0
    awk -F'|' -v id="$id" '
        NR==1 {
            for (i=1; i<=NF; i++) if ($i == "id") idcol=i
            next
        }
        idcol && $idcol == id { print; exit }
    ' "$file"
}
```

- [ ] **Step 7: Create CSV test fixtures**

Create `tests/fixtures/test-project/scenes/metadata.csv`:

```
id|seq|title|pov|setting|part|type|timeline_day|time_of_day|status|word_count|target_words
act1-sc01|1|The Finest Cartographer|Dorren Hayle|Pressure Cartography Office|1|character|1|morning|drafted|2400|2500
act1-sc02|2|The Missing Village|Dorren Hayle|Dorren's private study|1|character|1|evening|drafted|95|3000
new-x1|3|The Archivist's Warning|Kael Maren|The Deep Archive|1|plot|2|afternoon|drafted|1200|1500
act2-sc01|4|The Hollow District|Tessa Merrin|Eastern Basin|2|world|3|morning|planned|0|2000
```

Create `tests/fixtures/test-project/scenes/intent.csv`:

```
id|function|emotional_arc|characters|threads|motifs|notes
act1-sc01|Establishes Dorren as institutional gatekeeper|Controlled competence to buried unease|Dorren Hayle||Tessa Merrin||Pell|institutional failure||chosen blindness|maps/cartography||governance-as-weight|
act1-sc02|Dorren notices a village has vanished from the pressure maps|Routine giving way to dread|Dorren Hayle|the anomaly||maps and territory|depth/descent|
new-x1|Kael warns about archive inconsistencies|Scholarly calm to urgent alarm|Kael Maren||Dorren Hayle|the anomaly||archive corruption|blindness/seeing|
act2-sc01|First exploration of the eastern damage|Professional detachment to visceral shock|Tessa Merrin||Pell|infrastructure failure||the subsidence|depth/descent||acceptable variance|
```

- [ ] **Step 8: Run all CSV tests**

Run: `./tests/run-tests.sh test-csv`
Expected: All PASS

- [ ] **Step 9: Write failing tests for `get_csv_column` and `list_csv_ids`**

Add to `tests/test-csv.sh`:

```bash
# --- get_csv_column ---
RESULT=$(get_csv_column "$FIXTURE_DIR/scenes/metadata.csv" "pov")
assert_contains "$RESULT" "Dorren Hayle" "get_csv_column: contains first pov"
assert_contains "$RESULT" "Tessa Merrin" "get_csv_column: contains last pov"
LINE_COUNT=$(echo "$RESULT" | wc -l | tr -d ' ')
assert_equals "4" "$LINE_COUNT" "get_csv_column: returns all rows"

# --- list_csv_ids ---
RESULT=$(list_csv_ids "$FIXTURE_DIR/scenes/metadata.csv")
FIRST=$(echo "$RESULT" | head -1)
assert_equals "act1-sc01" "$FIRST" "list_csv_ids: first id"
LINE_COUNT=$(echo "$RESULT" | wc -l | tr -d ' ')
assert_equals "4" "$LINE_COUNT" "list_csv_ids: returns all ids"
```

- [ ] **Step 10: Implement `get_csv_column` and `list_csv_ids`**

Add to `scripts/lib/csv.sh`:

```bash
# get_csv_column(file, field) — print all values for a given column, one per line
get_csv_column() {
    local file="$1" field="$2"
    [[ ! -f "$file" ]] && return 0
    awk -F'|' -v field="$field" '
        NR==1 {
            for (i=1; i<=NF; i++) if ($i == field) col=i
            next
        }
        col { print $col }
    ' "$file"
}

# list_csv_ids(file) — print all IDs, one per line, in file order
list_csv_ids() {
    local file="$1"
    get_csv_column "$file" "id"
}
```

- [ ] **Step 11: Run tests**

Run: `./tests/run-tests.sh test-csv`
Expected: All PASS

- [ ] **Step 12: Write failing tests for CSV writing functions**

Add to `tests/test-csv.sh`:

```bash
# --- update_csv_field ---
cp "$FIXTURE_DIR/scenes/metadata.csv" "$TMPDIR/test-update.csv"
update_csv_field "$TMPDIR/test-update.csv" "act1-sc01" "status" "revised"
RESULT=$(get_csv_field "$TMPDIR/test-update.csv" "act1-sc01" "status")
assert_equals "revised" "$RESULT" "update_csv_field: updates field value"

# Verify other fields unchanged
RESULT=$(get_csv_field "$TMPDIR/test-update.csv" "act1-sc01" "title")
assert_equals "The Finest Cartographer" "$RESULT" "update_csv_field: preserves other fields"

# Verify other rows unchanged
RESULT=$(get_csv_field "$TMPDIR/test-update.csv" "act1-sc02" "status")
assert_equals "drafted" "$RESULT" "update_csv_field: preserves other rows"

# --- append_csv_row ---
cp "$FIXTURE_DIR/scenes/metadata.csv" "$TMPDIR/test-append.csv"
append_csv_row "$TMPDIR/test-append.csv" "new-sc99|99|New Scene|Pell|The Market|3|transition|5|noon|planned|0|1000"
RESULT=$(get_csv_field "$TMPDIR/test-append.csv" "new-sc99" "title")
assert_equals "New Scene" "$RESULT" "append_csv_row: appended row is readable"
LINE_COUNT=$(list_csv_ids "$TMPDIR/test-append.csv" | wc -l | tr -d ' ')
assert_equals "5" "$LINE_COUNT" "append_csv_row: row count increased"
```

- [ ] **Step 13: Implement CSV writing functions**

Add to `scripts/lib/csv.sh`:

```bash
# update_csv_field(file, id, field, value) — update a single field for a given ID
# Reads the file, updates the matching row, rewrites atomically via temp file + mv.
update_csv_field() {
    local file="$1" id="$2" field="$3" value="$4"
    local tmpfile
    tmpfile=$(mktemp "${TMPDIR:-/tmp}/csv-update.XXXXXX")
    awk -F'|' -v OFS='|' -v id="$id" -v field="$field" -v value="$value" '
        NR==1 {
            for (i=1; i<=NF; i++) {
                if ($i == field) col=i
                if ($i == "id") idcol=i
            }
            print; next
        }
        col && idcol && $idcol == id { $col = value }
        { print }
    ' "$file" > "$tmpfile"
    mv "$tmpfile" "$file"
}

# append_csv_row(file, row) — append a pipe-delimited row to the file
append_csv_row() {
    local file="$1" row="$2"
    printf '%s\n' "$row" >> "$file"
}
```

- [ ] **Step 14: Run all tests**

Run: `./tests/run-tests.sh test-csv`
Expected: All PASS

- [ ] **Step 15: Commit**

```bash
git add scripts/lib/csv.sh tests/test-csv.sh tests/fixtures/test-project/scenes/metadata.csv tests/fixtures/test-project/scenes/intent.csv
git commit -m "Add CSV library with read/write functions and tests"
git push
```

### Task 2: Register CSV library in test runner and common.sh

**Files:**
- Modify: `tests/run-tests.sh` — add test-csv to the test suite list
- Modify: `scripts/lib/common.sh` — source csv.sh
- Modify: `tests/run-tests.sh` — source csv.sh in test setup

- [ ] **Step 1: Update run-tests.sh to include test-csv and source csv.sh**

Add `test-csv` to the test suite array in `run-tests.sh`. Add `source "${PLUGIN_DIR}/scripts/lib/csv.sh"` to the library sourcing block.

- [ ] **Step 2: Add `source` line to common.sh**

After the existing library sourcing (near the top of common.sh where other libs are sourced), add:

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/csv.sh"
```

Note: if common.sh already has a `SCRIPT_DIR` or equivalent, use that. The key is that `csv.sh` is sourced by any script that sources `common.sh`.

- [ ] **Step 3: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All existing tests still pass, test-csv passes

- [ ] **Step 4: Commit**

```bash
git add tests/run-tests.sh scripts/lib/common.sh
git commit -m "Register CSV library in test runner and common.sh"
git push
```

---

## Chunk 2: Cost Tracking Library

### Task 3: Create cost tracking library

**Files:**
- Create: `scripts/lib/costs.sh`
- Create: `tests/test-costs.sh`

- [ ] **Step 1: Write failing tests for `log_usage`**

Create `tests/test-costs.sh`:

```bash
#!/bin/bash
# test-costs.sh — Tests for cost tracking functions

# Create a mock stream-json log with usage data
MOCK_LOG="$TMPDIR/mock-claude-output.log"
cat > "$MOCK_LOG" << 'JSONEOF'
{"type":"message_start","message":{"id":"msg_01","model":"claude-opus-4-6-20250320"}}
{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}
{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}
{"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"input_tokens":8432,"output_tokens":3210,"cache_read_input_tokens":1500,"cache_creation_input_tokens":200}}
JSONEOF

LEDGER="$TMPDIR/test-ledger.csv"
rm -f "$LEDGER"

log_usage "$MOCK_LOG" "draft" "the-finest-cartographer" "claude-opus-4-6" "$LEDGER"

assert_file_exists "$LEDGER" "log_usage: creates ledger file"

HEADER=$(head -1 "$LEDGER")
assert_contains "$HEADER" "timestamp" "log_usage: ledger has header"
assert_contains "$HEADER" "input_tokens" "log_usage: header has input_tokens"

ROW=$(tail -1 "$LEDGER")
assert_contains "$ROW" "draft" "log_usage: row has operation"
assert_contains "$ROW" "the-finest-cartographer" "log_usage: row has target"
assert_contains "$ROW" "8432" "log_usage: row has input_tokens"
assert_contains "$ROW" "3210" "log_usage: row has output_tokens"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tests/run-tests.sh test-costs`
Expected: FAIL — costs.sh does not exist

- [ ] **Step 3: Create costs library with `log_usage`**

Create `scripts/lib/costs.sh`:

```bash
#!/bin/bash
# costs.sh — Token usage tracking and cost calculation
#
# Parses stream-json output from Claude invocations, calculates cost,
# and maintains an append-only ledger.

# Pricing per million tokens (USD) — update as pricing changes
PRICING_OPUS_INPUT=${STORYFORGE_PRICING_OPUS_INPUT:-15.00}
PRICING_OPUS_OUTPUT=${STORYFORGE_PRICING_OPUS_OUTPUT:-75.00}
PRICING_OPUS_CACHE_READ=${STORYFORGE_PRICING_OPUS_CACHE_READ:-1.50}
PRICING_OPUS_CACHE_CREATE=${STORYFORGE_PRICING_OPUS_CACHE_CREATE:-18.75}
PRICING_SONNET_INPUT=${STORYFORGE_PRICING_SONNET_INPUT:-3.00}
PRICING_SONNET_OUTPUT=${STORYFORGE_PRICING_SONNET_OUTPUT:-15.00}
PRICING_SONNET_CACHE_READ=${STORYFORGE_PRICING_SONNET_CACHE_READ:-0.30}
PRICING_SONNET_CACHE_CREATE=${STORYFORGE_PRICING_SONNET_CACHE_CREATE:-3.75}

COST_LEDGER_HEADER="timestamp|operation|target|model|input_tokens|output_tokens|cache_read|cache_create|cost_usd|duration_s"

# get_model_pricing(model, token_type) — return per-million-token price
# token_type: input, output, cache_read, cache_create
get_model_pricing() {
    local model="$1" token_type="$2"
    local prefix="PRICING_SONNET"
    [[ "$model" == *opus* ]] && prefix="PRICING_OPUS"
    local var="${prefix}_$(echo "$token_type" | tr '[:lower:]' '[:upper:]')"
    echo "${!var}"
}

# log_usage(log_file, operation, target, model, [ledger_file])
# Parse stream-json log for usage data, calculate cost, append to ledger.
# If usage data not found, writes a zero-cost row with a warning.
log_usage() {
    local log_file="$1" operation="$2" target="$3" model="$4"
    local ledger="${5:-${PROJECT_DIR}/working/costs/ledger.csv}"
    local timestamp
    timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

    # Ensure ledger directory and header exist
    mkdir -p "$(dirname "$ledger")"
    if [[ ! -f "$ledger" ]]; then
        echo "$COST_LEDGER_HEADER" > "$ledger"
    fi

    # Extract usage from the last message_delta line with usage data
    local usage_line
    usage_line=$(grep '"usage"' "$log_file" 2>/dev/null | tail -1)

    local input_tokens=0 output_tokens=0 cache_read=0 cache_create=0 duration_s=0
    if [[ -n "$usage_line" ]]; then
        input_tokens=$(echo "$usage_line" | awk -F'"input_tokens":' '{print $2}' | awk -F'[^0-9]' '{print $1}')
        output_tokens=$(echo "$usage_line" | awk -F'"output_tokens":' '{print $2}' | awk -F'[^0-9]' '{print $1}')
        cache_read=$(echo "$usage_line" | awk -F'"cache_read_input_tokens":' '{print $2}' | awk -F'[^0-9]' '{print $1}')
        cache_create=$(echo "$usage_line" | awk -F'"cache_creation_input_tokens":' '{print $2}' | awk -F'[^0-9]' '{print $1}')
        # Default to 0 if extraction failed
        input_tokens=${input_tokens:-0}
        output_tokens=${output_tokens:-0}
        cache_read=${cache_read:-0}
        cache_create=${cache_create:-0}
    else
        log "WARNING: No usage data found in $log_file — recording zero-cost row"
    fi

    # Read duration from _SF_INVOCATION_START if set
    if [[ -n "${_SF_INVOCATION_START:-}" ]]; then
        local now
        now=$(date +%s)
        duration_s=$(( now - _SF_INVOCATION_START ))
    fi

    # Calculate cost
    local price_in price_out price_cr price_cc cost_usd
    price_in=$(get_model_pricing "$model" "input")
    price_out=$(get_model_pricing "$model" "output")
    price_cr=$(get_model_pricing "$model" "cache_read")
    price_cc=$(get_model_pricing "$model" "cache_create")

    cost_usd=$(awk "BEGIN { printf \"%.4f\", ($input_tokens * $price_in + $output_tokens * $price_out + $cache_read * $price_cr + $cache_create * $price_cc) / 1000000 }")

    # Append row
    append_csv_row "$ledger" "${timestamp}|${operation}|${target}|${model}|${input_tokens}|${output_tokens}|${cache_read}|${cache_create}|${cost_usd}|${duration_s}"
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tests/run-tests.sh test-costs`
Expected: PASS

- [ ] **Step 5: Write failing tests for `estimate_cost` and `check_cost_threshold`**

Add to `tests/test-costs.sh`:

```bash
# --- estimate_cost ---
RESULT=$(estimate_cost "evaluate" 6 15000 "claude-sonnet-4-6")
assert_not_empty "$RESULT" "estimate_cost: returns non-empty"
# Result should be a decimal string
assert_matches "$RESULT" '^[0-9]+\.[0-9]+$' "estimate_cost: returns decimal"

# --- check_cost_threshold (under threshold — should proceed) ---
STORYFORGE_COST_THRESHOLD=100
RESULT=$(check_cost_threshold "0.50")
assert_equals "0" "$?" "check_cost_threshold: proceeds when under threshold"

# --- print_cost_summary ---
# Populate a test ledger with known data
TEST_LEDGER="$TMPDIR/test-summary-ledger.csv"
echo "$COST_LEDGER_HEADER" > "$TEST_LEDGER"
append_csv_row "$TEST_LEDGER" "2026-03-12T14:30:00Z|draft|sc01|claude-opus-4-6|8000|3000|1000|0|0.3465|30"
append_csv_row "$TEST_LEDGER" "2026-03-12T14:31:00Z|draft|sc02|claude-opus-4-6|7500|2800|1200|0|0.3225|28"

RESULT=$(print_cost_summary "draft" "$TEST_LEDGER")
assert_contains "$RESULT" "2 invocations" "print_cost_summary: shows invocation count"
assert_contains "$RESULT" "0.6690" "print_cost_summary: shows total cost"
```

- [ ] **Step 6: Implement `estimate_cost`, `check_cost_threshold`, and `print_cost_summary`**

Add to `scripts/lib/costs.sh`:

```bash
# estimate_cost(operation, scope_count, avg_words, model)
# Estimate cost for an operation. Returns decimal USD string.
estimate_cost() {
    local operation="$1" scope_count="$2" avg_words="$3" model="$4"
    local tokens_per_word=1.3
    local est_input est_output price_in price_out

    # Estimate input: prose tokens + ~3000 overhead (reference docs, prompt template)
    est_input=$(awk "BEGIN { printf \"%d\", $scope_count * ($avg_words * $tokens_per_word + 3000) }")

    # Estimate output: drafting ~1500 tokens/scene, evaluation ~2000, revision ~1000
    case "$operation" in
        draft)     est_output=$(awk "BEGIN { printf \"%d\", $scope_count * 1500 }") ;;
        evaluate)  est_output=$(awk "BEGIN { printf \"%d\", $scope_count * 2000 }") ;;
        revise)    est_output=$(awk "BEGIN { printf \"%d\", $scope_count * 1000 }") ;;
        *)         est_output=$(awk "BEGIN { printf \"%d\", $scope_count * 1500 }") ;;
    esac

    price_in=$(get_model_pricing "$model" "input")
    price_out=$(get_model_pricing "$model" "output")

    awk "BEGIN { printf \"%.2f\", ($est_input * $price_in + $est_output * $price_out) / 1000000 }"
}

# check_cost_threshold(estimated_cost)
# Prompt for confirmation if over threshold. Returns 0 to proceed, 1 to abort.
# Non-interactive (no tty) always proceeds.
check_cost_threshold() {
    local estimated="$1"
    local threshold="${STORYFORGE_COST_THRESHOLD:-10}"

    local over
    over=$(awk "BEGIN { print ($estimated > $threshold) ? 1 : 0 }")
    if [[ "$over" == "1" ]] && [[ -t 0 ]]; then
        printf "Estimated cost: \$%s (threshold: \$%s). Proceed? [y/N] " "$estimated" "$threshold"
        local reply
        read -r reply
        [[ "$reply" =~ ^[Yy] ]] && return 0 || return 1
    fi
    return 0
}

# print_cost_summary(operation, [ledger_file])
# Print end-of-operation cost summary from ledger entries.
print_cost_summary() {
    local operation="$1"
    local ledger="${2:-${PROJECT_DIR}/working/costs/ledger.csv}"
    [[ ! -f "$ledger" ]] && return 0

    awk -F'|' -v op="$operation" '
        NR==1 { next }
        $2 == op {
            count++
            input += $5
            output += $6
            cache += $7
            cost += $9
        }
        END {
            if (count > 0) {
                printf "%s complete. %d invocations.\n", op, count
                printf "  Input:  %'\''d tokens\n", input
                printf "  Output: %'\''d tokens\n", output
                if (cache > 0) printf "  Cache:  %'\''d tokens read\n", cache
                printf "  Cost:   $%.4f\n", cost
            }
        }
    ' "$ledger"
}
```

- [ ] **Step 7: Run tests**

Run: `./tests/run-tests.sh test-costs`
Expected: All PASS

- [ ] **Step 8: Register costs library in common.sh and test runner**

Source `costs.sh` in `common.sh` after `csv.sh`. Add `test-costs` to the test suite list in `run-tests.sh`. Source `costs.sh` in the test setup block.

- [ ] **Step 9: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All tests pass

- [ ] **Step 10: Commit**

```bash
git add scripts/lib/costs.sh tests/test-costs.sh tests/run-tests.sh scripts/lib/common.sh
git commit -m "Add cost tracking library with usage logging, forecasting, and summaries"
git push
```

---

## Chunk 3: Migration Script

### Task 4: Create storyforge-migrate script — core scene migration

**Files:**
- Create: `scripts/storyforge-migrate`
- Create: `tests/test-migrate.sh`

- [ ] **Step 1: Write failing tests for YAML-to-CSV scene metadata extraction**

Create `tests/test-migrate.sh` with tests that run the migration in dry-run mode against the test fixture:

```bash
#!/bin/bash
# test-migrate.sh — Tests for storyforge-migrate

# Setup: copy fixture to a temp dir for migration testing
MIGRATE_DIR="$TMPDIR/migrate-test"
rm -rf "$MIGRATE_DIR"
cp -r "$FIXTURE_DIR" "$MIGRATE_DIR"

# --- Dry run should not modify files ---
"$PLUGIN_DIR/scripts/storyforge-migrate" --project-dir "$MIGRATE_DIR" --dry-run 2>&1
assert_file_exists "$MIGRATE_DIR/scenes/scene-index.yaml" "dry-run: scene-index.yaml still exists"
assert_equals "1" "$(test ! -f "$MIGRATE_DIR/scenes/metadata.csv" && echo 1 || echo 0)" "dry-run: metadata.csv not created"

# --- Execute migration ---
"$PLUGIN_DIR/scripts/storyforge-migrate" --project-dir "$MIGRATE_DIR" --execute 2>&1

# Verify metadata.csv created
assert_file_exists "$MIGRATE_DIR/scenes/metadata.csv" "migrate: metadata.csv created"

# Verify header
HEADER=$(head -1 "$MIGRATE_DIR/scenes/metadata.csv")
assert_contains "$HEADER" "id|seq|title" "migrate: metadata.csv has correct header"

# Verify scene data extracted
RESULT=$(get_csv_field "$MIGRATE_DIR/scenes/metadata.csv" "act1-sc01" "title")
assert_equals "The Finest Cartographer" "$RESULT" "migrate: extracts title"

RESULT=$(get_csv_field "$MIGRATE_DIR/scenes/metadata.csv" "act1-sc01" "pov")
assert_equals "Dorren Hayle" "$RESULT" "migrate: extracts pov"

# Verify seq ordering
RESULT=$(get_csv_field "$MIGRATE_DIR/scenes/metadata.csv" "act1-sc01" "seq")
assert_equals "1" "$RESULT" "migrate: first scene has seq 1"
RESULT=$(get_csv_field "$MIGRATE_DIR/scenes/metadata.csv" "act1-sc02" "seq")
assert_equals "2" "$RESULT" "migrate: second scene has seq 2"

# Verify intent.csv created
assert_file_exists "$MIGRATE_DIR/scenes/intent.csv" "migrate: intent.csv created"
RESULT=$(get_csv_field "$MIGRATE_DIR/scenes/intent.csv" "act1-sc01" "function")
assert_not_empty "$RESULT" "migrate: intent has function"

# Verify scene file frontmatter stripped
FIRST_LINE=$(head -1 "$MIGRATE_DIR/scenes/act1-sc01.md")
assert_not_contains "$FIRST_LINE" "---" "migrate: frontmatter stripped from scene file"

# Verify backup created
assert_file_exists "$MIGRATE_DIR/working/backups/pre-migration/scene-index.yaml" "migrate: backup created"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tests/run-tests.sh test-migrate`
Expected: FAIL — storyforge-migrate does not exist

- [ ] **Step 3: Create storyforge-migrate script — argument parsing and dry-run framework**

Create `scripts/storyforge-migrate` with:
- Argument parsing (`--dry-run`, `--execute`, `--project-dir`, `--skip-rename`, `--skip-backup`)
- Project root detection
- Dry-run vs execute mode
- Backup creation
- Logging

```bash
#!/bin/bash
set -eo pipefail

# storyforge-migrate — Convert project from YAML to CSV format
# Usage: storyforge-migrate [--dry-run|--execute] [--project-dir DIR] [--skip-rename] [--skip-backup]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

MODE="dry-run"
SKIP_RENAME=false
SKIP_BACKUP=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)     MODE="dry-run"; shift ;;
        --execute)     MODE="execute"; shift ;;
        --project-dir) PROJECT_DIR="$2"; shift 2 ;;
        --skip-rename) SKIP_RENAME=true; shift ;;
        --skip-backup) SKIP_BACKUP=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

[[ -z "${PROJECT_DIR:-}" ]] && detect_project_root
SCENE_INDEX="${PROJECT_DIR}/scenes/scene-index.yaml"
SCENES_DIR="${PROJECT_DIR}/scenes"

[[ ! -f "$SCENE_INDEX" ]] && { echo "No scene-index.yaml found at $SCENE_INDEX"; exit 1; }

# Implementation functions follow in subsequent steps
```

- [ ] **Step 4: Implement YAML-to-CSV scene metadata extraction**

Add functions to `storyforge-migrate`:

```bash
# Extract scene data from YAML index and write metadata.csv + intent.csv
migrate_scene_metadata() {
    local metadata_file="${SCENES_DIR}/metadata.csv"
    local intent_file="${SCENES_DIR}/intent.csv"

    if [[ "$MODE" == "dry-run" ]]; then
        echo "[DRY RUN] Would create: $metadata_file"
        echo "[DRY RUN] Would create: $intent_file"
        return 0
    fi

    # Create backup
    if [[ "$SKIP_BACKUP" != true ]]; then
        local backup_dir="${PROJECT_DIR}/working/backups/pre-migration"
        mkdir -p "$backup_dir"
        cp "$SCENE_INDEX" "$backup_dir/scene-index.yaml"
        echo "Backed up scene-index.yaml"
    fi

    # Write metadata.csv header
    echo "id|seq|title|pov|setting|part|type|timeline_day|time_of_day|status|word_count|target_words" > "$metadata_file"

    # Write intent.csv header
    echo "id|function|emotional_arc|characters|threads|motifs|notes" > "$intent_file"

    # Parse YAML and extract fields
    local seq=0
    local current_id="" current_title="" current_pov="" current_setting="" current_part=""
    local current_type="" current_timeline="" current_tod="" current_status="" current_words=""
    local current_target="" current_function="" current_arc="" current_chars=""
    local current_threads="" current_motifs="" current_notes=""
    local in_scene=false field_name=""

    while IFS= read -r line; do
        # New scene entry
        if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*id:[[:space:]]*(.*) ]]; then
            # Write previous scene if we have one
            if [[ -n "$current_id" ]]; then
                seq=$((seq + 1))
                _write_scene_row
            fi
            # Start new scene
            current_id=$(echo "${BASH_REMATCH[1]}" | sed 's/^["'\'']//' | sed 's/["'\'']*$//' | sed 's/[[:space:]]*$//')
            in_scene=true
            _reset_scene_fields
            continue
        fi

        if [[ "$in_scene" == true ]] && [[ "$line" =~ ^[[:space:]]+([a-z_]+):[[:space:]]*(.*) ]]; then
            field_name="${BASH_REMATCH[1]}"
            local value="${BASH_REMATCH[2]}"
            value=$(echo "$value" | sed 's/^["'\'']//' | sed 's/["'\'']*$//' | sed 's/[[:space:]]*$//')

            case "$field_name" in
                title)         current_title="$value" ;;
                pov)           current_pov="$value" ;;
                setting|location) current_setting="$value" ;;
                part)          current_part="$value" ;;
                type)          current_type="$value" ;;
                timeline_day|timeline_position) current_timeline="$value" ;;
                time_of_day|time) current_tod="$value" ;;
                status)        current_status="$value" ;;
                words|word_count) current_words="$value" ;;
                target_words|word_target) current_target="$value" ;;
                function)      current_function="$value" ;;
                emotional_arc) current_arc="$value" ;;
                notes|summary) current_notes="$value" ;;
            esac
        fi
    done < "$SCENE_INDEX"

    # Write last scene
    if [[ -n "$current_id" ]]; then
        seq=$((seq + 1))
        _write_scene_row
    fi

    echo "Created $metadata_file ($seq scenes)"
    echo "Created $intent_file"
}

_reset_scene_fields() {
    current_title="" current_pov="" current_setting="" current_part=""
    current_type="" current_timeline="" current_tod="" current_status="" current_words=""
    current_target="" current_function="" current_arc="" current_chars=""
    current_threads="" current_motifs="" current_notes=""
}

_write_scene_row() {
    # Also check scene file frontmatter for fields missing from index
    local scene_file="${SCENES_DIR}/${current_id}.md"
    if [[ -f "$scene_file" ]]; then
        # Extract word_count from frontmatter if not in index
        if [[ -z "$current_words" ]]; then
            current_words=$(sed -n '/^---$/,/^---$/p' "$scene_file" | grep '^word_count:' | sed 's/^word_count:[[:space:]]*//')
        fi
        # Extract status from frontmatter if not in index
        if [[ -z "$current_status" ]]; then
            current_status=$(sed -n '/^---$/,/^---$/p' "$scene_file" | grep '^status:' | sed 's/^status:[[:space:]]*//' | sed 's/["'\'']//g')
        fi
    fi

    append_csv_row "${SCENES_DIR}/metadata.csv" "${current_id}|${seq}|${current_title}|${current_pov}|${current_setting}|${current_part}|${current_type}|${current_timeline}|${current_tod}|${current_status}|${current_words}|${current_target}"
    append_csv_row "${SCENES_DIR}/intent.csv" "${current_id}|${current_function}|${current_arc}|${current_chars}|${current_threads}|${current_motifs}|${current_notes}"
}
```

- [ ] **Step 5: Implement frontmatter stripping**

Add to `storyforge-migrate`:

```bash
# Strip YAML frontmatter from scene files, leaving pure prose
strip_frontmatter() {
    local count=0
    for scene_file in "${SCENES_DIR}"/*.md; do
        [[ ! -f "$scene_file" ]] && continue
        local first_line
        first_line=$(head -1 "$scene_file")
        [[ "$first_line" != "---" ]] && continue

        if [[ "$MODE" == "dry-run" ]]; then
            echo "[DRY RUN] Would strip frontmatter from: $(basename "$scene_file")"
            count=$((count + 1))
            continue
        fi

        # Find end of frontmatter (second ---) and keep everything after
        local end_line
        end_line=$(awk 'NR>1 && /^---$/ { print NR; exit }' "$scene_file")
        if [[ -n "$end_line" ]]; then
            local tmpfile
            tmpfile=$(mktemp "${TMPDIR:-/tmp}/strip-fm.XXXXXX")
            tail -n "+$((end_line + 1))" "$scene_file" | sed '/./,$!d' > "$tmpfile"
            mv "$tmpfile" "$scene_file"
            count=$((count + 1))
        fi
    done
    echo "Stripped frontmatter from $count scene files"
}
```

- [ ] **Step 6: Add main execution flow**

Add at the bottom of `storyforge-migrate`:

```bash
echo "=== Storyforge Migration ==="
echo "Project: $PROJECT_DIR"
echo "Mode: $MODE"
echo ""

migrate_scene_metadata
strip_frontmatter

# TODO: Additional file migrations (chapter-map, timeline, etc.) in Task 5

echo ""
echo "Migration ${MODE} complete."
if [[ "$MODE" == "dry-run" ]]; then
    echo "Run with --execute to apply changes."
fi
```

- [ ] **Step 7: Make script executable and run tests**

```bash
chmod +x scripts/storyforge-migrate
```

Run: `./tests/run-tests.sh test-migrate`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add scripts/storyforge-migrate tests/test-migrate.sh
git commit -m "Add storyforge-migrate script for YAML to CSV conversion"
git push
```

### Task 5: Add additional file migrations to storyforge-migrate

**Files:**
- Modify: `scripts/storyforge-migrate`
- Modify: `tests/test-migrate.sh`

- [ ] **Step 1: Write failing tests for chapter-map migration**

Add to `tests/test-migrate.sh`:

```bash
# --- Chapter map migration ---
assert_file_exists "$MIGRATE_DIR/reference/chapter-map.csv" "migrate: chapter-map.csv created"
CH_HEADER=$(head -1 "$MIGRATE_DIR/reference/chapter-map.csv")
assert_contains "$CH_HEADER" "seq|title" "migrate: chapter-map.csv has correct header"
```

- [ ] **Step 2: Implement chapter-map.yaml to chapter-map.csv migration**

Add `migrate_chapter_map()` function to `storyforge-migrate`. Parse the YAML list of chapters, extract title/heading/part/scenes fields, write to `reference/chapter-map.csv`. Scene lists use `||` as the array delimiter.

- [ ] **Step 3: Write failing tests for findings migration**

Add tests for `working/evaluations/*/findings.yaml` → `findings.csv` conversion.

- [ ] **Step 4: Implement findings migration**

Add `migrate_findings()` function. Parse findings YAML, extract fields, write to findings.csv, strengths.csv, false-positives.csv.

- [ ] **Step 5: Write failing tests for revision-plan and pipeline migration**

Add tests for `working/plans/revision-plan.yaml` → `revision-plan.csv` and `working/pipeline.yaml` → `pipeline.csv`.

- [ ] **Step 6: Implement revision-plan and pipeline migration**

Add `migrate_revision_plan()` and `migrate_pipeline()` functions.

- [ ] **Step 7: Wire all migrations into the main execution flow**

Update the main flow at the bottom of `storyforge-migrate` to call all migration functions.

- [ ] **Step 8: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add scripts/storyforge-migrate tests/test-migrate.sh
git commit -m "Add chapter-map, findings, revision-plan, and pipeline migrations"
git push
```

---

## Chunk 4: Script Integration

### Task 6: Update prompt-builder.sh to read from CSV

**Files:**
- Modify: `scripts/lib/prompt-builder.sh`
- Modify: `tests/test-prompt-builder.sh`

- [ ] **Step 1: Write failing tests for CSV-based metadata reading**

Add to `tests/test-prompt-builder.sh`:

```bash
# --- CSV-based scene metadata ---
# Test that get_scene_metadata works with CSV when metadata.csv exists
RESULT=$(get_scene_metadata "act1-sc01" "$PROJECT_DIR")
assert_contains "$RESULT" "Dorren Hayle" "get_scene_metadata: reads pov from CSV"
assert_contains "$RESULT" "Pressure Cartography Office" "get_scene_metadata: reads setting from CSV"
```

- [ ] **Step 2: Update `get_scene_metadata` with CSV-first fallback**

Modify `get_scene_metadata()` in `prompt-builder.sh` to check for `scenes/metadata.csv` first. If found, read from CSV. If not, fall back to YAML with a deprecation warning.

```bash
get_scene_metadata() {
    local scene_id="$1" project_dir="$2"
    local csv_file="${project_dir}/scenes/metadata.csv"
    local yaml_file="${project_dir}/scenes/scene-index.yaml"

    if [[ -f "$csv_file" ]]; then
        # Read from CSV — format as key: value pairs for prompt injection
        local row
        row=$(get_csv_row "$csv_file" "$scene_id")
        [[ -z "$row" ]] && return 0
        local header
        header=$(head -1 "$csv_file")
        # Combine header + row into key: value format
        paste <(echo "$header" | tr '|' '\n') <(echo "$row" | tr '|' '\n') | awk -F'\t' '{ print $1 ": " $2 }'
    elif [[ -f "$yaml_file" ]]; then
        log "WARNING: Using deprecated scene-index.yaml — run storyforge-migrate to convert to CSV"
        # Existing YAML extraction logic
        # ... (keep existing implementation)
    fi
}
```

- [ ] **Step 3: Add `get_scene_intent` function**

Add new function to `prompt-builder.sh`:

```bash
get_scene_intent() {
    local scene_id="$1" project_dir="$2"
    local csv_file="${project_dir}/scenes/intent.csv"
    [[ ! -f "$csv_file" ]] && return 0
    local row
    row=$(get_csv_row "$csv_file" "$scene_id")
    [[ -z "$row" ]] && return 0
    local header
    header=$(head -1 "$csv_file")
    paste <(echo "$header" | tr '|' '\n') <(echo "$row" | tr '|' '\n') | awk -F'\t' '{ print $1 ": " $2 }'
}
```

- [ ] **Step 4: Update `build_scene_prompt` to remove frontmatter instructions**

In `build_scene_prompt()`, remove instructions telling Claude to write YAML frontmatter. Replace with instructions to write pure prose only. Add intent data injection when available.

- [ ] **Step 5: Update `list_reference_files` to include *.csv**

In `list_reference_files()`, add `*.csv` to the find/glob pattern alongside `*.md`, `*.yaml`, `*.yml`, `*.txt`.

- [ ] **Step 6: Run tests**

Run: `./tests/run-tests.sh`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/prompt-builder.sh tests/test-prompt-builder.sh
git commit -m "Update prompt-builder to read from CSV with YAML fallback"
git push
```

### Task 7: Update storyforge-write with CSV reading and cost tracking

**Files:**
- Modify: `scripts/storyforge-write`

- [ ] **Step 1: Update scene list building to read from CSV**

Replace the YAML-based scene list extraction (lines 196-203) with CSV-based reading:

```bash
# Build scene list from metadata.csv (or fall back to scene-index.yaml)
METADATA_CSV="${SCENES_DIR}/metadata.csv"
if [[ -f "$METADATA_CSV" ]]; then
    while IFS= read -r id; do
        [[ -z "$id" ]] && continue
        ALL_SCENE_IDS+=("$id")
    done < <(awk -F'|' 'NR>1 && $10 != "cut" { print $1 }' "$METADATA_CSV" | while IFS= read -r id; do
        seq=$(get_csv_field "$METADATA_CSV" "$id" "seq")
        echo "$seq $id"
    done | sort -n | awk '{print $2}')
else
    # Existing YAML fallback
    log "WARNING: Using deprecated scene-index.yaml — run storyforge-migrate"
    # ... keep existing YAML parsing
fi
```

- [ ] **Step 2: Add cost forecasting before drafting**

After scene list is built, before the main loop:

```bash
# Cost forecast
if [[ -f "$METADATA_CSV" ]]; then
    AVG_WORDS=$(awk -F'|' 'NR>1 { sum += $11; count++ } END { if(count>0) printf "%d", sum/count; else print 1500 }' "$METADATA_CSV")
else
    AVG_WORDS=1500
fi
SCENE_MODEL=$(select_model "drafting")
ESTIMATED_COST=$(estimate_cost "draft" "${#PENDING_IDS[@]}" "$AVG_WORDS" "$SCENE_MODEL")
echo "Drafting ${#PENDING_IDS[@]} scenes. Estimated cost: \$${ESTIMATED_COST}"
check_cost_threshold "$ESTIMATED_COST" || { echo "Aborted."; exit 0; }
```

- [ ] **Step 3: Add `log_usage` after each Claude invocation**

After the headless Claude invocation (around line 466), add:

```bash
_SF_INVOCATION_START=$_sf_start_time
log_usage "$SCENE_LOG" "draft" "$SCENE_ID" "$SCENE_MODEL"
```

Set `_sf_start_time=$(date +%s)` before the invocation.

- [ ] **Step 4: Update word_count and status in metadata.csv after drafting**

After scene file is verified (around line 520), replace frontmatter-based tracking:

```bash
if [[ -f "$METADATA_CSV" ]]; then
    local actual_words
    actual_words=$(wc -w < "$SCENE_FILE" | tr -d ' ')
    update_csv_field "$METADATA_CSV" "$SCENE_ID" "word_count" "$actual_words"
    update_csv_field "$METADATA_CSV" "$SCENE_ID" "status" "drafted"
fi
```

- [ ] **Step 5: Add end-of-operation cost summary**

After the main loop completes, before the review phase:

```bash
print_cost_summary "draft"
```

- [ ] **Step 6: Run existing write tests**

Run: `./tests/run-tests.sh test-dry-run`
Expected: All PASS (dry-run tests should work with YAML fallback)

- [ ] **Step 7: Commit**

```bash
git add scripts/storyforge-write
git commit -m "Update storyforge-write to use CSV metadata and cost tracking"
git push
```

### Task 8: Update storyforge-evaluate with CSV and cost tracking

**Files:**
- Modify: `scripts/storyforge-evaluate`

- [ ] **Step 1: Add cost forecasting before evaluation**

Add forecast calculation based on manuscript size and evaluator count.

- [ ] **Step 2: Add `log_usage` after each evaluator invocation**

Track timing with `_SF_INVOCATION_START` before each Claude call, then `log_usage` after.

- [ ] **Step 3: Update findings output to CSV format**

Replace YAML findings output with CSV. Write `findings.csv`, `strengths.csv`, `false-positives.csv` in the evaluation directory.

- [ ] **Step 4: Add cost summary at end**

Call `print_cost_summary "evaluate"` at the end of the operation.

- [ ] **Step 5: Run existing evaluate tests**

Run: `./tests/run-tests.sh`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/storyforge-evaluate
git commit -m "Update storyforge-evaluate to use CSV findings and cost tracking"
git push
```

### Task 9: Update storyforge-revise with CSV and cost tracking

**Files:**
- Modify: `scripts/storyforge-revise`

- [ ] **Step 1: Update revision plan reading to CSV**

Replace YAML revision plan parsing with CSV reading from `working/plans/revision-plan.csv`.

- [ ] **Step 2: Add cost forecasting and per-pass usage logging**

Add forecast before the revision cycle. Add `log_usage` after each revision pass.

- [ ] **Step 3: Update word_count in metadata.csv after revision**

After each pass modifies scene files, recalculate and update word counts in `metadata.csv`.

- [ ] **Step 4: Add cost summary at end**

Call `print_cost_summary "revise"`.

- [ ] **Step 5: Run existing revise tests**

Run: `./tests/run-tests.sh test-revision-passes`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/storyforge-revise
git commit -m "Update storyforge-revise to use CSV revision plans and cost tracking"
git push
```

### Task 10: Update storyforge-assemble with CSV

**Files:**
- Modify: `scripts/storyforge-assemble`

- [ ] **Step 1: Update chapter map reading to CSV**

Replace YAML chapter-map reading with CSV reading from `reference/chapter-map.csv`.

- [ ] **Step 2: Add cost tracking for assembly invocations**

Add `log_usage` after Claude invocations during assembly.

- [ ] **Step 3: Run existing assembly tests**

Run: `./tests/run-tests.sh test-assembly`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/storyforge-assemble
git commit -m "Update storyforge-assemble to use CSV chapter map and cost tracking"
git push
```

---

## Chunk 5: Skills, Fixtures, and Cleanup

### Task 11: Update skills to read/write CSV

**Files:**
- Modify: `skills/scenes/SKILL.md`
- Modify: `skills/plan-revision/SKILL.md`
- Modify: `skills/review/SKILL.md`
- Modify: `skills/forge/SKILL.md`

- [ ] **Step 1: Update scenes skill**

Update `skills/scenes/SKILL.md` to read scene data from `scenes/metadata.csv` and `scenes/intent.csv` instead of `scene-index.yaml`. When creating or modifying scenes, write to CSV files. Update references to frontmatter.

- [ ] **Step 2: Update plan-revision skill**

Update to write `working/plans/revision-plan.csv` instead of YAML. Read findings from CSV.

- [ ] **Step 3: Update review skill**

Update to read findings from CSV format.

- [ ] **Step 4: Update forge hub skill**

Update project status reading to check for CSV files.

- [ ] **Step 5: Commit**

```bash
git add skills/
git commit -m "Update skills to read/write CSV instead of YAML"
git push
```

### Task 12: Update test fixtures for CSV format

**Files:**
- Modify: `tests/fixtures/test-project/` — add CSV fixtures alongside YAML
- Modify: `tests/test-prompt-builder.sh` — ensure tests work with CSV
- Modify: `tests/test-dry-run.sh` — ensure tests work with CSV

- [ ] **Step 1: Add CSV fixtures to test-project**

The CSV fixtures were created in Task 1 Step 7. Verify they exist and are consistent with the YAML fixtures. Keep YAML fixtures for backward-compatibility testing.

- [ ] **Step 2: Update test-prompt-builder.sh tests**

Ensure prompt-builder tests exercise the CSV code path. Add tests that verify the CSV→YAML fallback works.

- [ ] **Step 3: Update test-dry-run.sh tests**

Ensure dry-run tests work with CSV metadata. The YAML fallback should keep existing tests passing.

- [ ] **Step 4: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All tests pass (401+ tests)

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "Update test fixtures and tests for CSV format"
git push
```

### Task 13: Update scene-schema reference and documentation

**Files:**
- Modify: `references/scene-schema.md`
- Modify: `references/storyforge-yaml-schema.md`

- [ ] **Step 1: Update scene-schema.md**

Update the scene schema reference to document:
- Scene files are pure prose (no frontmatter)
- Filename is the scene ID
- metadata.csv and intent.csv are the canonical metadata sources
- CSV format conventions (pipe delimiter, double-pipe arrays)

- [ ] **Step 2: Update storyforge-yaml-schema.md**

Update artifact references to point to CSV files instead of YAML. Note that `scene_index` artifact path changes from `scenes/scene-index.yaml` to `scenes/metadata.csv`.

- [ ] **Step 3: Commit**

```bash
git add references/
git commit -m "Update schema documentation for CSV data format"
git push
```

### Task 14: Version bump and changelog

**Files:**
- Modify: `.claude-plugin/plugin.json` — bump version

- [ ] **Step 1: Bump version in plugin.json**

Bump version to 0.16.0 (minor version bump for new data format).

- [ ] **Step 2: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 0.16.0 for CSV data format and cost tracking (v0.16.0)"
git push
```
