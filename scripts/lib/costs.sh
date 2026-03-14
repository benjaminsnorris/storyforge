#!/bin/bash
# costs.sh — Token usage tracking and cost calculation for Storyforge
#
# Tracks Claude API token usage, calculates costs, forecasts upcoming
# operations, and prints summaries.  Depends on csv.sh for append_csv_row.
#
# Source this file from your script; do not execute it directly.

# ============================================================================
# Pricing constants (per million tokens, env-overridable)
# ============================================================================

PRICING_OPUS_INPUT="${PRICING_OPUS_INPUT:-15.00}"
PRICING_OPUS_OUTPUT="${PRICING_OPUS_OUTPUT:-75.00}"
PRICING_OPUS_CACHE_READ="${PRICING_OPUS_CACHE_READ:-1.50}"
PRICING_OPUS_CACHE_CREATE="${PRICING_OPUS_CACHE_CREATE:-18.75}"

PRICING_SONNET_INPUT="${PRICING_SONNET_INPUT:-3.00}"
PRICING_SONNET_OUTPUT="${PRICING_SONNET_OUTPUT:-15.00}"
PRICING_SONNET_CACHE_READ="${PRICING_SONNET_CACHE_READ:-0.30}"
PRICING_SONNET_CACHE_CREATE="${PRICING_SONNET_CACHE_CREATE:-3.75}"

PRICING_HAIKU_INPUT="${PRICING_HAIKU_INPUT:-0.80}"
PRICING_HAIKU_OUTPUT="${PRICING_HAIKU_OUTPUT:-4.00}"
PRICING_HAIKU_CACHE_READ="${PRICING_HAIKU_CACHE_READ:-0.08}"
PRICING_HAIKU_CACHE_CREATE="${PRICING_HAIKU_CACHE_CREATE:-1.00}"

# ============================================================================
# get_model_pricing — return per-million-token price for a model
# ============================================================================
# Usage: get_model_pricing <model> <token_type>
# token_type: input, output, cache_read, cache_create
# Models containing "opus" use opus pricing, otherwise sonnet.
get_model_pricing() {
    local model="$1"
    local token_type="$2"

    local tier="SONNET"
    if echo "$model" | grep -qi "opus"; then
        tier="OPUS"
    elif echo "$model" | grep -qi "haiku"; then
        tier="HAIKU"
    fi

    case "$token_type" in
        input)
            eval echo "\${PRICING_${tier}_INPUT}"
            ;;
        output)
            eval echo "\${PRICING_${tier}_OUTPUT}"
            ;;
        cache_read)
            eval echo "\${PRICING_${tier}_CACHE_READ}"
            ;;
        cache_create)
            eval echo "\${PRICING_${tier}_CACHE_CREATE}"
            ;;
        *)
            echo "0.00"
            ;;
    esac
}

# ============================================================================
# log_usage — Parse stream-json log and append cost row to ledger
# ============================================================================
# Usage: log_usage <log_file> <operation> <target> <model> [ledger_file]
#
# Parses the stream-json log for a "usage" line and extracts token counts.
# Calculates cost and appends a row to the ledger CSV.
# If usage data is not found, writes a zero-cost row with warning.
log_usage() {
    local log_file="$1"
    local operation="$2"
    local target="$3"
    local model="$4"
    local ledger_file="${5:-${PROJECT_DIR}/working/costs/ledger.csv}"
    local ledger_header="timestamp|operation|target|model|input_tokens|output_tokens|cache_read|cache_create|cost_usd|duration_s"

    # Ensure ledger directory and header exist
    local ledger_dir
    ledger_dir="$(dirname "$ledger_file")"
    if [[ ! -d "$ledger_dir" ]]; then
        mkdir -p "$ledger_dir"
    fi
    if [[ ! -f "$ledger_file" ]]; then
        echo "$ledger_header" > "$ledger_file"
    fi

    # Calculate duration from _SF_INVOCATION_START if set
    local duration_s="0"
    if [[ -n "${_SF_INVOCATION_START:-}" ]]; then
        local now
        now="$(date +%s)"
        duration_s="$((now - _SF_INVOCATION_START))"
    fi

    local timestamp
    timestamp="$(date '+%Y-%m-%dT%H:%M:%S')"

    # Try to extract usage data from the log file
    local input_tokens=0
    local output_tokens=0
    local cache_read=0
    local cache_create=0

    if [[ -f "$log_file" ]]; then
        local usage_line
        usage_line="$(grep '"usage"' "$log_file" 2>/dev/null | tail -1 || true)"

        if [[ -n "$usage_line" ]]; then
            input_tokens="$(echo "$usage_line" | sed 's/.*"input_tokens"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/' || echo 0)"
            output_tokens="$(echo "$usage_line" | sed 's/.*"output_tokens"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/' || echo 0)"
            # cache fields may not exist
            cache_read="$(echo "$usage_line" | sed -n 's/.*"cache_read_input_tokens"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' || echo 0)"
            cache_create="$(echo "$usage_line" | sed -n 's/.*"cache_creation_input_tokens"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' || echo 0)"

            # Default empty to 0
            [[ -z "$input_tokens" || "$input_tokens" == "$usage_line" ]] && input_tokens=0
            [[ -z "$output_tokens" || "$output_tokens" == "$usage_line" ]] && output_tokens=0
            [[ -z "$cache_read" ]] && cache_read=0
            [[ -z "$cache_create" ]] && cache_create=0
        else
            # No usage data found — log warning
            if type log &>/dev/null; then
                log "WARNING: No usage data found in ${log_file}"
            fi
        fi
    else
        if type log &>/dev/null; then
            log "WARNING: Log file not found: ${log_file}"
        fi
    fi

    # Calculate cost via awk
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

    # Append row to ledger
    local row="${timestamp}|${operation}|${target}|${model}|${input_tokens}|${output_tokens}|${cache_read}|${cache_create}|${cost_usd}|${duration_s}"
    append_csv_row "$ledger_file" "$row"
}

# ============================================================================
# estimate_cost — Forecast cost for an operation
# ============================================================================
# Usage: estimate_cost <operation> <scope_count> <avg_words> <model>
#
# Input tokens ≈ scope_count * (avg_words * 1.3 + 3000 overhead)
# Output estimate by operation type:
#   draft ~1500, evaluate ~2000, revise ~1000 tokens per scope item
# Returns decimal USD string.
estimate_cost() {
    local operation="$1"
    local scope_count="$2"
    local avg_words="$3"
    local model="$4"

    # Output tokens per scope item by operation type
    local output_per_item=1500
    case "$operation" in
        draft|write)    output_per_item=1500 ;;
        evaluate)       output_per_item=2000 ;;
        revise)         output_per_item=1000 ;;
        score)          output_per_item=800 ;;
        *)              output_per_item=1500 ;;
    esac

    local price_input price_output
    price_input="$(get_model_pricing "$model" input)"
    price_output="$(get_model_pricing "$model" output)"

    awk "BEGIN {
        input_tokens = $scope_count * ($avg_words * 1.3 + 3000)
        output_tokens = $scope_count * $output_per_item
        cost = (input_tokens * $price_input / 1000000) + \
               (output_tokens * $price_output / 1000000)
        printf \"%.2f\", cost
    }"
}

# ============================================================================
# check_cost_threshold — Prompt for confirmation if cost exceeds threshold
# ============================================================================
# Usage: check_cost_threshold <estimated_cost>
# Returns 0 to proceed, 1 to abort.
# Non-interactive (no tty) always proceeds.
check_cost_threshold() {
    local estimated_cost="$1"
    local threshold="${STORYFORGE_COST_THRESHOLD:-10}"

    # Check if estimated exceeds threshold
    local exceeds
    exceeds="$(awk "BEGIN { print ($estimated_cost > $threshold) ? 1 : 0 }")"

    if [[ "$exceeds" != "1" ]]; then
        return 0
    fi

    # Non-interactive — always proceed
    if [[ ! -t 0 ]]; then
        return 0
    fi

    echo ""
    echo "WARNING: Estimated cost \$${estimated_cost} exceeds threshold \$${threshold}."
    printf "Proceed? (y/N) "
    local answer
    read -r answer
    case "$answer" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

# ============================================================================
# print_cost_summary — Print end-of-operation summary from ledger
# ============================================================================
# Usage: print_cost_summary <operation> [ledger_file]
#
# Prints invocation count, total input/output/cache tokens, total cost.
# Filters by operation type.
print_cost_summary() {
    local operation="$1"
    local ledger_file="${2:-${PROJECT_DIR}/working/costs/ledger.csv}"

    if [[ ! -f "$ledger_file" ]]; then
        echo "No cost data available."
        return 0
    fi

    local summary
    summary="$(awk -F'|' -v op="$operation" '
        NR == 1 { next }
        $2 == op {
            count++
            input += $5
            output += $6
            cache_r += $7
            cache_c += $8
            cost += $9
            dur += $10
        }
        END {
            if (count == 0) {
                print "No cost data for operation: " op
                exit
            }
            printf "--- Cost Summary: %s ---\n", op
            printf "Invocations:  %d\n", count
            printf "Input tokens: %d\n", input
            printf "Output tokens: %d\n", output
            printf "Cache read:   %d\n", cache_r
            printf "Cache create: %d\n", cache_c
            printf "Total cost:   $%.4f\n", cost
            printf "Total time:   %ds\n", dur
        }
    ' "$ledger_file")"

    echo "$summary"
}
