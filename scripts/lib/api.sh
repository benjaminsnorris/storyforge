#!/bin/bash
# api.sh — Direct Anthropic API invocation and Batch API helpers
#
# General-purpose library for calling the Anthropic Messages API.
# Provides both real-time (invoke_anthropic_api) and batch (submit_batch,
# poll_batch, download_batch_results) invocation patterns.
#
# Source this file from your script; do not execute it directly.

# ============================================================================
# API key validation
# ============================================================================

# _sf_api_key_verified — skip re-checking after first success
_sf_api_key_verified=false

# verify_api_key()
# Lightweight auth check — sends a minimal request that returns 400 (valid key)
# or 401 (invalid key). No tokens consumed. Caches result for the session.
# Returns 0 if key is valid, 1 if not.
verify_api_key() {
    if [[ "$_sf_api_key_verified" == true ]]; then
        return 0
    fi

    if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
        log "ERROR: ANTHROPIC_API_KEY not set."
        return 1
    fi

    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        "https://api.anthropic.com/v1/messages" \
        -H "x-api-key: ${ANTHROPIC_API_KEY}" \
        -H "anthropic-version: 2023-06-01" \
        -H "content-type: application/json" \
        -d '{"model":"claude-haiku-4-5-20251001","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}' 2>/dev/null) || {
        log "ERROR: Could not reach Anthropic API"
        return 1
    }

    if [[ "$http_code" == "401" || "$http_code" == "403" ]]; then
        log "ERROR: ANTHROPIC_API_KEY is invalid (HTTP ${http_code})"
        return 1
    fi

    _sf_api_key_verified=true
    return 0
}

# ============================================================================
# Direct API invocation
# ============================================================================

# invoke_anthropic_api(prompt, model, log_file, [max_tokens])
# Calls the Anthropic Messages API directly via curl.
# Requires ANTHROPIC_API_KEY environment variable.
# Writes the full API response to log_file.
# Returns 0 on success, 1 on failure.
invoke_anthropic_api() {
    local prompt="$1"
    local model="$2"
    local log_file="$3"
    local max_tokens="${4:-4096}"

    verify_api_key || return 1

    # Build the JSON request — escape the prompt for JSON embedding
    local json_prompt
    json_prompt=$(jq -Rs '.' <<< "$prompt")

    local request_body
    request_body=$(cat <<JSONEOF
{
    "model": "${model}",
    "max_tokens": ${max_tokens},
    "messages": [
        {"role": "user", "content": ${json_prompt}}
    ]
}
JSONEOF
)

    # Make the API call
    local http_code
    http_code=$(curl -s -w "%{http_code}" -o "$log_file" \
        "https://api.anthropic.com/v1/messages" \
        -H "x-api-key: ${ANTHROPIC_API_KEY}" \
        -H "anthropic-version: 2023-06-01" \
        -H "content-type: application/json" \
        -d "$request_body" 2>/dev/null) || {
        log "WARNING: curl failed for API call"
        return 1
    }

    if [[ "$http_code" != "200" ]]; then
        log "WARNING: API returned HTTP ${http_code}"
        [[ -f "$log_file" ]] && log "  Response: $(head -1 "$log_file")"
        return 1
    fi

    return 0
}

# ============================================================================
# Response parsing
# ============================================================================

# extract_api_response(log_file)
# Extracts the text content from an Anthropic Messages API JSON response.
# Prints the text to stdout.
extract_api_response() {
    local log_file="$1"
    [[ -f "$log_file" ]] || return 1
    jq -r '.content[] | select(.type == "text") | .text' "$log_file" 2>/dev/null
}

# extract_api_usage(log_file)
# Extracts usage data from an Anthropic Messages API response.
# Prints: input_tokens|output_tokens|cache_read|cache_create
extract_api_usage() {
    local log_file="$1"
    [[ -f "$log_file" ]] || return 1
    jq -r '[
        (.usage.input_tokens // 0),
        (.usage.output_tokens // 0),
        (.usage.cache_read_input_tokens // 0),
        (.usage.cache_creation_input_tokens // 0)
    ] | join("|")' "$log_file" 2>/dev/null
}

# log_api_usage(log_file, operation, target, model, [ledger_file])
# Parses an Anthropic API response and appends a cost row to the ledger.
log_api_usage() {
    local log_file="$1"
    local operation="$2"
    local target="$3"
    local model="$4"
    local ledger_file="${5:-${PROJECT_DIR}/working/costs/ledger.csv}"
    local ledger_header="timestamp|operation|target|model|input_tokens|output_tokens|cache_read|cache_create|cost_usd|duration_s"

    local ledger_dir
    ledger_dir="$(dirname "$ledger_file")"
    mkdir -p "$ledger_dir"
    if [[ ! -f "$ledger_file" ]]; then
        echo "$ledger_header" > "$ledger_file"
    fi

    local duration_s="0"
    if [[ -n "${_SF_INVOCATION_START:-}" ]]; then
        duration_s="$(( $(date +%s) - _SF_INVOCATION_START ))"
    fi

    local timestamp
    timestamp="$(date '+%Y-%m-%dT%H:%M:%S')"

    local usage_data
    usage_data=$(extract_api_usage "$log_file")
    if [[ -z "$usage_data" ]]; then
        echo "${timestamp}|${operation}|${target}|${model}|0|0|0|0|0.000000|${duration_s}" >> "$ledger_file"
        return
    fi

    IFS='|' read -r input_tokens output_tokens cache_read cache_create <<< "$usage_data"

    local price_input price_output price_cache_read price_cache_create
    price_input="$(get_model_pricing "$model" input)"
    price_output="$(get_model_pricing "$model" output)"
    price_cache_read="$(get_model_pricing "$model" cache_read)"
    price_cache_create="$(get_model_pricing "$model" cache_create)"

    local cost_usd
    cost_usd="$(awk "BEGIN {
        cost = ($input_tokens * $price_input / 1000000) + \
               ($output_tokens * $price_output / 1000000) + \
               ($cache_read * $price_cache_read / 1000000) + \
               ($cache_create * $price_cache_create / 1000000)
        printf \"%.6f\", cost
    }")"

    echo "${timestamp}|${operation}|${target}|${model}|${input_tokens}|${output_tokens}|${cache_read}|${cache_create}|${cost_usd}|${duration_s}" >> "$ledger_file"
}

# ============================================================================
# Batch API helpers
# ============================================================================

# Global variable set by poll_batch for download_batch_results
_SF_BATCH_RESULTS_URL=""

# submit_batch(batch_file)
# Submits a JSONL batch file to the Anthropic Batch API.
# The batch_file must contain one JSON request per line in the format:
#   {"custom_id": "...", "params": {"model": "...", "max_tokens": N, "messages": [...]}}
# Prints the batch ID to stdout. Returns 0 on success, 1 on failure.
submit_batch() {
    local batch_file="$1"

    verify_api_key || return 1

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

# poll_batch(batch_id)
# Polls a batch until processing_status is "ended".
# Logs progress at increasing intervals.
# Sets _SF_BATCH_RESULTS_URL for download_batch_results.
# Returns 0 when ended.
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
            _SF_BATCH_RESULTS_URL=$(echo "$status_response" | jq -r '.results_url // empty')
            return 0
        fi

        (( poll_interval < 30 )) && poll_interval=$((poll_interval + 5))
    done
}

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
