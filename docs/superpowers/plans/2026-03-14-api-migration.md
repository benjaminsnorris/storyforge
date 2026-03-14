# API Migration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate all autonomous `claude -p` invocations to direct Anthropic Messages API calls with batch mode as default.

**Architecture:** Extract API and batch helper functions from `scoring.sh` into new `api.sh` library. Update `common.sh` shared functions. Convert each autonomous script's `claude -p` invocations to use `invoke_anthropic_api` (direct) or batch API (default for multi-item scripts). Interactive mode stays on Claude Code.

**Tech Stack:** Bash, curl, jq, python3 (batch result parsing), Anthropic Messages API + Batch API

---

## Chunk 1: Foundation — api.sh Library

### Task 1: Extract api.sh from scoring.sh

**Files:**
- Create: `scripts/lib/api.sh`
- Modify: `scripts/lib/scoring.sh:1-140` (remove extracted functions)
- Modify: `scripts/lib/common.sh:589-596` (source api.sh)

- [ ] **Step 1: Create `scripts/lib/api.sh`**

Extract these functions from `scoring.sh` into the new file:
- `invoke_anthropic_api(prompt, model, log_file, [max_tokens])`
- `extract_api_response(log_file)`
- `extract_api_usage(log_file)`
- `log_api_usage(log_file, operation, target, model, [ledger])`

Add new batch helper functions:
- `submit_batch(batch_file)` — builds request body from JSONL, submits to Batch API, returns batch ID
- `poll_batch(batch_id)` — polls until `processing_status == "ended"`, logs progress
- `download_batch_results(batch_id, output_dir)` — downloads results JSONL, parses into per-item JSON + text files using python3

The file header:
```bash
#!/bin/bash
# api.sh — Direct Anthropic API invocation and Batch API helpers
#
# General-purpose library for calling the Anthropic Messages API.
# Provides both real-time (invoke_anthropic_api) and batch (submit_batch,
# poll_batch, download_batch_results) invocation patterns.
#
# Source this file from your script; do not execute it directly.
```

For `invoke_anthropic_api`: copy exactly from `scoring.sh` lines 18-65, but update the error message from "Required for direct API scoring" to "Required for direct API calls".

For `extract_api_response`: copy from `scoring.sh` lines 70-74.

For `extract_api_usage`: copy from `scoring.sh` lines 79-88.

For `log_api_usage`: copy from `scoring.sh` lines 92-140.

For `submit_batch`:
```bash
# submit_batch(batch_file)
# Submits a JSONL batch file to the Anthropic Batch API.
# The batch_file must contain one JSON request per line in the format:
#   {"custom_id": "...", "params": {"model": "...", "max_tokens": N, "messages": [...]}}
# Prints the batch ID to stdout. Returns 0 on success, 1 on failure.
submit_batch() {
    local batch_file="$1"

    if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
        log "ERROR: ANTHROPIC_API_KEY not set."
        return 1
    fi

    local batch_body="${TMPDIR:-/tmp}/storyforge-batch-body-$$.json"
    jq -s '{requests: .}' "$batch_file" > "$batch_body"

    local response
    response=$(curl -s "https://api.anthropic.com/v1/messages/batches" \
        -H "x-api-key: ${ANTHROPIC_API_KEY}" \
        -H "anthropic-version: 2023-06-01" \
        -H "content-type: application/json" \
        -d @"$batch_body") || {
        rm -f "$batch_body"
        log "ERROR: Failed to submit batch"
        return 1
    }
    rm -f "$batch_body"

    local batch_id
    batch_id=$(echo "$response" | jq -r '.id // empty')
    if [[ -z "$batch_id" ]]; then
        log "ERROR: No batch ID returned"
        log "  Response: $(echo "$response" | head -3)"
        return 1
    fi

    echo "$batch_id"
}
```

For `poll_batch`:
```bash
# poll_batch(batch_id)
# Polls a batch until processing_status is "ended".
# Logs progress at increasing intervals.
# Returns 0 on success, 1 on failure.
poll_batch() {
    local batch_id="$1"
    local poll_interval=15
    local start_time
    start_time=$(date +%s)

    while true; do
        sleep "$poll_interval"
        local status_response
        status_response=$(curl -s "https://api.anthropic.com/v1/messages/batches/${batch_id}" \
            -H "x-api-key: ${ANTHROPIC_API_KEY}" \
            -H "anthropic-version: 2023-06-01")

        local pstatus succeeded errored elapsed
        pstatus=$(echo "$status_response" | jq -r '.processing_status')
        succeeded=$(echo "$status_response" | jq -r '.request_counts.succeeded')
        errored=$(echo "$status_response" | jq -r '.request_counts.errored')
        elapsed=$(( $(date +%s) - start_time ))

        log "  ${elapsed}s: ${pstatus} (${succeeded} succeeded, ${errored} errored)"

        if [[ "$pstatus" == "ended" ]]; then
            # Store results_url for download_batch_results
            _SF_BATCH_RESULTS_URL=$(echo "$status_response" | jq -r '.results_url // empty')
            return 0
        fi

        (( poll_interval < 30 )) && poll_interval=$((poll_interval + 5))
    done
}
```

For `download_batch_results`:
```bash
# download_batch_results(batch_id, output_dir, log_dir)
# Downloads batch results and parses into per-item files:
#   output_dir/.status-{custom_id}  — "ok" or "fail"
#   log_dir/{custom_id}.json        — API response (for log_api_usage)
#   log_dir/{custom_id}.txt         — text content (for script-specific parsing)
# Returns 0 on success, 1 on failure.
download_batch_results() {
    local batch_id="$1"
    local output_dir="$2"
    local log_dir="$3"

    # Use stored results URL from poll_batch, or fetch it
    local results_url="${_SF_BATCH_RESULTS_URL:-}"
    if [[ -z "$results_url" ]]; then
        local status_response
        status_response=$(curl -s "https://api.anthropic.com/v1/messages/batches/${batch_id}" \
            -H "x-api-key: ${ANTHROPIC_API_KEY}" \
            -H "anthropic-version: 2023-06-01")
        results_url=$(echo "$status_response" | jq -r '.results_url // empty')
    fi

    if [[ -z "$results_url" ]]; then
        log "ERROR: No results URL for batch ${batch_id}"
        return 1
    fi

    local results_file="${output_dir}/.batch-results.jsonl"
    curl -s "$results_url" \
        -H "x-api-key: ${ANTHROPIC_API_KEY}" \
        -H "anthropic-version: 2023-06-01" \
        > "$results_file"

    mkdir -p "$log_dir"

    python3 -c "
import json, sys, os

results_file = '${results_file}'
output_dir = '${output_dir}'
log_dir = '${log_dir}'

with open(results_file) as f:
    for line in f:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        cid = obj.get('custom_id', '')
        result = obj.get('result', {})
        rtype = result.get('type', '')

        if rtype != 'succeeded':
            with open(os.path.join(output_dir, f'.status-{cid}'), 'w') as sf:
                sf.write('fail')
            continue

        msg = result.get('message', {})
        usage = msg.get('usage', {})

        text = ''
        for block in msg.get('content', []):
            if block.get('type') == 'text':
                text = block.get('text', '')

        response_file = os.path.join(log_dir, f'{cid}.json')
        with open(response_file, 'w') as rf:
            json.dump({'usage': usage, 'content': msg.get('content', [])}, rf)

        text_file = os.path.join(log_dir, f'{cid}.txt')
        with open(text_file, 'w') as tf:
            tf.write(text)

        with open(os.path.join(output_dir, f'.status-{cid}'), 'w') as sf:
            sf.write('ok')

print('done')
" || {
        log "ERROR: Failed to parse batch results"
        return 1
    }

    rm -f "$results_file"
}
```

- [ ] **Step 2: Remove extracted functions from `scoring.sh`**

Remove the API invocation section (lines 1-140 of scoring.sh) — the functions `invoke_anthropic_api`, `extract_api_response`, `extract_api_usage`, and `log_api_usage`. Keep the file header but update it:

```bash
#!/bin/bash
# scoring.sh — Scoring library for principled evaluation
#
# Provides weight management and score parsing for the craft-weights system.
# API invocation functions are in api.sh (sourced by common.sh).
# Source this file from your script; do not execute it directly.
```

The file should start with `init_craft_weights` (currently line 142).

- [ ] **Step 3: Source `api.sh` from `common.sh`**

In `common.sh` around line 591, add the api.sh source before scoring.sh:

```bash
[[ -f "${_sf_lib_dir}/api.sh" ]] && source "${_sf_lib_dir}/api.sh"
```

- [ ] **Step 4: Update `storyforge-score` to use shared batch helpers**

Replace the inline batch submission/polling/download code in `storyforge-score` (the `batch)` case starting around line 501) with calls to the new shared functions:

In the batch case, after building the JSONL file, replace the submit/poll/download code with:
```bash
log "Submitting batch ($(wc -c < "$BATCH_FILE" | tr -d ' ') bytes)..."
BATCH_ID=$(submit_batch "$BATCH_FILE") || { log "ERROR: Batch submission failed"; exit 1; }
log "Batch submitted: ${BATCH_ID}"
log "Polling for results..."
poll_batch "$BATCH_ID"
log "Results downloaded. Parsing..."
download_batch_results "$BATCH_ID" "$CYCLE_DIR" "$LOG_DIR"
```

Then update the result processing loop: the scoring script currently looks for `score-{id}.json` and `score-{id}.txt` but `download_batch_results` writes `{custom_id}.json` and `{custom_id}.txt`. Align the naming — score script passes scene IDs as custom_id, so files will be `{id}.json` and `{id}.txt`. Update references:
```bash
text_file="${LOG_DIR}/${id}.txt"
json_file="${LOG_DIR}/${id}.json"
```

- [ ] **Step 5: Run tests**

Run: `./tests/run-tests.sh tests/test-scoring.sh`
Expected: All existing scoring tests pass (they test weight management, not API calls).

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/api.sh scripts/lib/scoring.sh scripts/lib/common.sh scripts/storyforge-score
git commit -m "Extract api.sh library from scoring.sh with batch helpers"
```

---

### Task 2: Update common.sh shared functions

**Files:**
- Modify: `scripts/lib/common.sh:280-374` (healing zone)
- Modify: `scripts/lib/common.sh:1294-1309` (`_run_headless_session`)

- [ ] **Step 1: Update `_run_headless_session` to use API**

Replace the `claude -p` call with `invoke_anthropic_api`. The function is used by review/cleanup phases which are autonomous.

```bash
_run_headless_session() {
    local prompt="$1"
    local model="$2"
    local log_file="$3"

    if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
        # Direct API (preferred for autonomous mode)
        invoke_anthropic_api "$prompt" "$model" "$log_file" 8192
        return $?
    fi

    # Fallback to claude -p if no API key
    set +e
    claude -p "$prompt" \
        --model "$model" \
        --dangerously-skip-permissions \
        --output-format stream-json \
        --verbose \
        > "$log_file" 2>&1
    local rc=$?
    set -e
    return $rc
}
```

- [ ] **Step 2: Update healing zone to use API**

In `_run_healing_attempt` (around line 342), replace the `claude -p` call:

```bash
    if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
        invoke_anthropic_api "$heal_prompt" "$heal_model" "$heal_log" 8192
        heal_rc=$?
    else
        set +e
        claude -p "$heal_prompt" \
            --model "$heal_model" \
            --dangerously-skip-permissions \
            --output-format stream-json \
            --verbose \
            > "$heal_log" 2>&1
        heal_rc=$?
        set -e
    fi
```

- [ ] **Step 3: Add `extract_headless_response` wrapper**

After `_run_headless_session`, add a helper that extracts text from either format:

```bash
# Extract text from a headless session log file.
# Handles both API JSON format and stream-json format.
_extract_headless_response() {
    local log_file="$1"
    [[ -f "$log_file" ]] || return 1

    # Try API JSON format first (has .content array)
    local api_text
    api_text=$(extract_api_response "$log_file" 2>/dev/null)
    if [[ -n "$api_text" ]]; then
        echo "$api_text"
        return 0
    fi

    # Fall back to stream-json format
    extract_claude_response "$log_file" 2>/dev/null
}
```

- [ ] **Step 4: Update callers of `_run_headless_session` that parse responses**

Search for uses of `_run_headless_session` followed by `extract_claude_response`. Replace with `_extract_headless_response`. These are in the review phase helpers in `common.sh`.

- [ ] **Step 5: Run tests**

Run: `./tests/run-tests.sh tests/test-healing.sh tests/test-common.sh`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/common.sh
git commit -m "Update common.sh headless session and healing to use API"
```

---

### Task 3: Write tests for api.sh

**Files:**
- Create: `tests/test-api.sh`

- [ ] **Step 1: Write tests**

Test the non-network functions (`extract_api_response`, `extract_api_usage`, `_extract_headless_response`) with fixture data. Cannot test actual API calls without a key, but can test JSON parsing.

```bash
#!/bin/bash
# test-api.sh — Tests for api.sh API helper functions

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

# Test: returns empty for missing file
result=$(extract_api_response "${API_TMP}/nonexistent.json" 2>/dev/null || true)
assert_empty "$result" "extract_api_response: empty for missing file"

# ============================================================================
# extract_api_usage
# ============================================================================

echo "  --- extract_api_usage ---"

# Test: extracts usage data
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

# Test: returns empty for missing file
result=$(_extract_headless_response "${API_TMP}/missing.json" 2>/dev/null || true)
assert_empty "$result" "_extract_headless_response: empty for missing file"
```

- [ ] **Step 2: Run tests**

Run: `./tests/run-tests.sh tests/test-api.sh`
Expected: All pass.

- [ ] **Step 3: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All suites pass — no regressions from the extraction.

- [ ] **Step 4: Commit**

```bash
git add tests/test-api.sh
git commit -m "Add tests for api.sh library functions"
```

---

## Chunk 2: Convert Scripts to API

### Task 4: Convert storyforge-enrich

**Files:**
- Modify: `scripts/storyforge-enrich:687-711` (claude -p invocation in worker subshell)

The enrich script processes many scenes in parallel — perfect for batch mode.

- [ ] **Step 1: Add API key check at startup**

After `detect_project_root` and before main logic, add:
```bash
# Require API key for autonomous mode
if [[ -z "${ANTHROPIC_API_KEY:-}" ]] && [[ "$INTERACTIVE" != true ]]; then
    log "ERROR: ANTHROPIC_API_KEY required for autonomous mode."
    log "  Set it with: export ANTHROPIC_API_KEY=your-key"
    log "  Or use --interactive for Claude Code session mode."
    exit 1
fi
```

- [ ] **Step 2: Add `--direct` flag to argument parsing**

In the argument parsing section, add `--direct` to accept direct API mode:
```bash
--direct)
    SCORE_MODE="direct"
    shift ;;
```

Add at the top with other defaults:
```bash
SCORE_MODE="batch"
```

- [ ] **Step 3: Implement batch mode for enrichment**

Replace the parallel worker loop with a batch submission pattern. Before the main loop, build a JSONL batch file:

```bash
if [[ "$SCORE_MODE" == "batch" && "$INTERACTIVE" != true ]]; then
    log "Building batch request for ${#FILTERED_IDS[@]} scenes..."
    BATCH_FILE="${ENRICH_DIR}/.batch-requests.jsonl"
    rm -f "$BATCH_FILE"

    for id in "${FILTERED_IDS[@]}"; do
        prompt=$(build_enrich_prompt "$id")
        jq -nc --arg id "$id" --arg model "$MODEL" --arg prompt "$prompt" '{
            custom_id: $id,
            params: { model: $model, max_tokens: 4096, messages: [{role: "user", content: $prompt}] }
        }' >> "$BATCH_FILE"
    done

    BATCH_ID=$(submit_batch "$BATCH_FILE") || { log "ERROR: Batch submission failed"; exit 1; }
    log "Batch submitted: ${BATCH_ID}"
    poll_batch "$BATCH_ID"
    download_batch_results "$BATCH_ID" "$ENRICH_DIR" "$LOG_DIR"

    # Process results
    for id in "${FILTERED_IDS[@]}"; do
        status_file="${ENRICH_DIR}/.status-${id}"
        text_file="${LOG_DIR}/${id}.txt"
        json_file="${LOG_DIR}/${id}.json"

        if [[ -f "$status_file" && "$(cat "$status_file")" == "ok" && -f "$text_file" ]]; then
            log_api_usage "$json_file" "enrich" "$id" "$MODEL"
            response=$(cat "$text_file")
            # ... existing field extraction logic from the worker subshell ...
        else
            log "WARNING: Failed to enrich ${id}"
        fi
        rm -f "$status_file"
    done

    rm -f "$BATCH_FILE"
else
    # Direct mode or interactive — keep parallel workers
    # For direct mode: replace claude -p with invoke_anthropic_api
    # For interactive: keep claude -p as-is
fi
```

- [ ] **Step 4: Update direct mode parallel workers**

In the else branch (direct/interactive), update the worker subshell for direct mode:

```bash
if [[ "$INTERACTIVE" == true ]]; then
    # Keep claude -p for interactive mode
    claude -p "$prompt" ...
else
    # Direct API
    invoke_anthropic_api "$prompt" "$MODEL" "$log_file" 4096 || true
    response=$(extract_api_response "$log_file" 2>/dev/null || true)
    log_api_usage "$log_file" "enrich" "$id" "$MODEL"
fi
```

- [ ] **Step 5: Update cost forecast for batch discount**

In the cost estimation section, apply 50% discount when in batch mode:
```bash
if [[ "$SCORE_MODE" == "batch" ]]; then
    ESTIMATED=$(awk "BEGIN { printf \"%.2f\", $ESTIMATED * 0.5 }")
    log "Cost forecast: ~\$${ESTIMATED} (${SCENE_COUNT} calls via Batch API, 50% off)"
else
    log "Cost forecast: ~\$${ESTIMATED} (${SCENE_COUNT} calls)"
fi
```

- [ ] **Step 6: Test with `--dry-run`**

Run `./storyforge-enrich --dry-run` from a novel project to verify argument parsing works.

- [ ] **Step 7: Commit**

```bash
git add scripts/storyforge-enrich
git commit -m "Convert storyforge-enrich to Anthropic API with batch mode"
```

---

### Task 5: Convert storyforge-timeline

**Files:**
- Modify: `scripts/storyforge-timeline:360-378` (phase 1 parallel workers)
- Modify: `scripts/storyforge-timeline:500-525` (phase 2 sequential)

- [ ] **Step 1: Add API key check and `--direct` flag**

Same pattern as enrich — add API key check and `--direct` argument.

- [ ] **Step 2: Convert phase 1 to batch mode**

Phase 1 uses Haiku for many parallel temporal indicator extractions. Convert to batch:

Build JSONL with each scene's prompt, submit batch, poll, download results. Parse DELTA/EVIDENCE/ANCHOR from each result's text file.

- [ ] **Step 3: Convert phase 1 direct mode**

In the direct/interactive else branch, replace `claude -p` with `invoke_anthropic_api` for non-interactive mode:
```bash
if [[ "$INTERACTIVE" == true ]]; then
    claude -p "$prompt" ... # unchanged
else
    invoke_anthropic_api "$prompt" "$HAIKU_MODEL" "$log_file" 4096 || true
    response=$(extract_api_response "$log_file" 2>/dev/null || true)
    log_api_usage "$log_file" "timeline-phase1" "$id" "$HAIKU_MODEL"
fi
```

- [ ] **Step 4: Convert phase 2 to direct API**

Phase 2 is a single Sonnet call. Replace `claude -p` with `invoke_anthropic_api`:
```bash
if [[ "$INTERACTIVE" == true ]]; then
    claude -p "$timeline_prompt" ... # unchanged
else
    invoke_anthropic_api "$timeline_prompt" "$SONNET_MODEL" "$tl_log" 8192 || true
    log_api_usage "$tl_log" "timeline-phase2" "assignment" "$SONNET_MODEL"
fi
```

Update the response extraction after phase 2 to use `extract_api_response` instead of `extract_claude_response` when in non-interactive mode.

- [ ] **Step 5: Commit**

```bash
git add scripts/storyforge-timeline
git commit -m "Convert storyforge-timeline to Anthropic API with batch mode"
```

---

### Task 6: Convert storyforge-scenes-setup

**Files:**
- Modify: `scripts/storyforge-scenes-setup:470-491` (scene boundary detection)

- [ ] **Step 1: Add API key check and `--direct` flag**

Same pattern.

- [ ] **Step 2: Convert to batch mode**

Scene detection processes multiple chapters. Build JSONL batch, submit, parse results.

- [ ] **Step 3: Convert direct mode fallback**

Replace `claude -p` with `invoke_anthropic_api`:
```bash
invoke_anthropic_api "$prompt" "$MODEL" "$log_file" 4096 || true
response=$(extract_api_response "$log_file" 2>/dev/null || true)
log_api_usage "$log_file" "scene-detect" "$chapter_id" "$MODEL"
```

- [ ] **Step 4: Commit**

```bash
git add scripts/storyforge-scenes-setup
git commit -m "Convert storyforge-scenes-setup to Anthropic API with batch mode"
```

---

### Task 7: Convert storyforge-evaluate

**Files:**
- Modify: `scripts/storyforge-evaluate:760-810` (core + custom evaluator launches)
- Modify: `scripts/storyforge-evaluate:1020-1035` (synthesis)

- [ ] **Step 1: Add API key check and `--direct` flag**

Same pattern.

- [ ] **Step 2: Convert evaluators to batch mode**

Build JSONL with all evaluator prompts (core + custom), submit as single batch. Each evaluator gets a unique `custom_id` (the evaluator name).

- [ ] **Step 3: Convert synthesis to direct API**

Synthesis is a single call after evaluators complete. Replace `claude -p` with `invoke_anthropic_api`.

- [ ] **Step 4: Convert direct mode fallback**

In direct mode, run evaluators as parallel `invoke_anthropic_api` calls instead of parallel `claude -p`.

- [ ] **Step 5: Update response extraction**

Each evaluator's response is currently extracted with `extract_claude_response`. Switch to `extract_api_response` for non-interactive mode, keep `extract_claude_response` for interactive.

- [ ] **Step 6: Commit**

```bash
git add scripts/storyforge-evaluate
git commit -m "Convert storyforge-evaluate to Anthropic API with batch mode"
```

---

### Task 8: Convert storyforge-write

**Files:**
- Modify: `scripts/storyforge-write:415-435` (scene drafting invocation)

- [ ] **Step 1: Add API key check and `--direct` flag**

Same pattern.

- [ ] **Step 2: Convert to batch mode**

Build JSONL with all scene drafting prompts. Note: writing uses Opus with high max_tokens (8192+). Batch gets 50% discount on Opus which is significant.

After batch results, each scene's text file contains the drafted prose. Write to scene files same as current logic.

- [ ] **Step 3: Convert direct mode**

Replace `claude -p` with `invoke_anthropic_api`. The progress monitor watches git for changes — it still works since the script writes scene files after getting results.

Note: In direct mode, the monitor needs adjustment since files are written after the API call returns, not streamed during. The monitor should still work (it polls on intervals), but the timing will differ.

- [ ] **Step 4: Update response extraction and cost tracking**

```bash
if [[ "$INTERACTIVE" == true ]]; then
    # Keep existing claude -p code path
else
    invoke_anthropic_api "$PROMPT" "$SCENE_MODEL" "$SCENE_LOG" 8192
    EXIT_CODE=$?
    response=$(extract_api_response "$SCENE_LOG")
    log_api_usage "$SCENE_LOG" "draft" "$SCENE_ID" "$SCENE_MODEL"
fi
```

- [ ] **Step 5: Commit**

```bash
git add scripts/storyforge-write
git commit -m "Convert storyforge-write to Anthropic API with batch mode"
```

---

### Task 9: Convert storyforge-revise

**Files:**
- Modify: `scripts/storyforge-revise:660-685` (headless revision invocation)

- [ ] **Step 1: Add API key check**

Same pattern. Note: revise doesn't need `--direct` flag since it defaults to direct (single calls per pass).

- [ ] **Step 2: Convert headless revision to direct API**

Replace `claude -p` in the headless mode branch:
```bash
if [[ "$INTERACTIVE" == true ]]; then
    # Keep existing claude -p interactive code path
else
    invoke_anthropic_api "$PROMPT" "$PASS_MODEL" "$STEP_LOG" 8192
    EXIT_CODE=$?
    log_api_usage "$STEP_LOG" "revise" "$PASS_NAME" "$PASS_MODEL"
fi
```

- [ ] **Step 3: Update response extraction**

Where `extract_claude_response` is used after the headless invocation, switch to `extract_api_response`.

- [ ] **Step 4: Commit**

```bash
git add scripts/storyforge-revise
git commit -m "Convert storyforge-revise to Anthropic API"
```

---

## Chunk 3: Cleanup and Version Bump

### Task 10: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md` — update Claude Invocation Pattern and add API pattern

- [ ] **Step 1: Update the Claude Invocation Pattern section**

Replace the current pattern with:

```markdown
### Claude Invocation — Autonomous (API)
```bash
_SF_INVOCATION_START=$(date +%s)
export _SF_INVOCATION_START

begin_healing_zone "description"

invoke_anthropic_api "$prompt" "$MODEL" "$log_file" 4096

end_healing_zone

response=$(extract_api_response "$log_file")
log_api_usage "$log_file" "operation" "$target" "$MODEL"
```

### Claude Invocation — Batch (API)
```bash
# Build JSONL
for id in "${IDS[@]}"; do
    prompt=$(build_prompt "$id")
    jq -nc --arg id "$id" --arg model "$MODEL" --arg prompt "$prompt" '{
        custom_id: $id,
        params: { model: $model, max_tokens: 4096, messages: [{role: "user", content: $prompt}] }
    }' >> "$BATCH_FILE"
done

BATCH_ID=$(submit_batch "$BATCH_FILE")
poll_batch "$BATCH_ID"
download_batch_results "$BATCH_ID" "$OUTPUT_DIR" "$LOG_DIR"
```

### Claude Invocation — Interactive (Claude Code)
```bash
claude -p "$prompt" \
    --model "$MODEL" \
    --dangerously-skip-permissions \
    --output-format stream-json \
    --verbose \
    > "$log_file" 2>&1
response=$(extract_claude_response "$log_file")
log_usage "$log_file" "operation" "$target" "$MODEL"
```
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "Update CLAUDE.md with API and batch invocation patterns"
```

---

### Task 11: Version bump and final verification

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All suites pass.

- [ ] **Step 2: Bump version**

Bump to `0.26.0` (new feature: API migration).

- [ ] **Step 3: Commit and push**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 0.26.0"
```
