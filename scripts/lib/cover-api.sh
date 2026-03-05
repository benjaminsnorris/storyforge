#!/bin/bash
# cover-api.sh — Image generation API helpers for Storyforge cover design
#
# Source this file from a script or skill session; do not execute it directly.
# Requires common.sh to be sourced first (for the `log` function).

# ============================================================================
# API Detection
# ============================================================================

# Check which image generation API is available.
# Returns: "openai", "bfl", or "none"
check_image_api() {
    if [[ -n "${OPENAI_API_KEY:-}" ]]; then
        echo "openai"
    elif [[ -n "${BFL_API_KEY:-}" ]]; then
        echo "bfl"
    else
        echo "none"
    fi
}

# ============================================================================
# Base64 Decoding (cross-platform)
# ============================================================================

# Decode base64 from stdin to stdout.
# macOS uses `base64 -D`, Linux uses `base64 -d`.
_decode_base64() {
    if base64 --help 2>&1 | grep -q '\-D'; then
        base64 -D
    else
        base64 -d
    fi
}

# ============================================================================
# OpenAI GPT Image API
# ============================================================================

# Generate an image using the OpenAI GPT Image API.
# Usage: openai_generate_image "prompt" "output_path" ["size"]
# Size defaults to "1024x1536" (portrait, ideal for book covers).
# Requires OPENAI_API_KEY environment variable.
openai_generate_image() {
    local prompt="$1"
    local output_path="$2"
    local size="${3:-1024x1536}"

    if [[ -z "${OPENAI_API_KEY:-}" ]]; then
        log "ERROR: OPENAI_API_KEY is not set"
        return 1
    fi

    log "Generating image via OpenAI GPT Image (${size})..."

    # Escape the prompt for JSON (handle quotes and newlines)
    local escaped_prompt
    escaped_prompt=$(printf '%s' "$prompt" | sed 's/\\/\\\\/g; s/"/\\"/g; s/$/\\n/g' | tr -d '\n' | sed 's/\\n$//')

    local response
    response=$(curl -s -w "\n%{http_code}" \
        -X POST "https://api.openai.com/v1/images/generations" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${OPENAI_API_KEY}" \
        -d "{
            \"model\": \"gpt-image-1\",
            \"prompt\": \"${escaped_prompt}\",
            \"n\": 1,
            \"size\": \"${size}\",
            \"quality\": \"high\",
            \"output_format\": \"png\"
        }" 2>&1)

    # Split response body and HTTP status code
    local http_code
    http_code=$(echo "$response" | tail -1)
    local body
    body=$(echo "$response" | sed '$d')

    # Check HTTP status
    if [[ "$http_code" != "200" ]]; then
        local error_msg
        error_msg=$(echo "$body" | grep -o '"message"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"message"[[:space:]]*:[[:space:]]*"//; s/"$//')
        if [[ -n "$error_msg" ]]; then
            log "ERROR: OpenAI API returned ${http_code}: ${error_msg}"
        else
            log "ERROR: OpenAI API returned ${http_code}"
        fi
        return 1
    fi

    # Extract base64 image data from JSON response
    # The response format is: {"data": [{"b64_json": "..."}]}
    local b64_data
    b64_data=$(echo "$body" | grep -o '"b64_json"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"b64_json"[[:space:]]*:[[:space:]]*"//; s/"$//')

    if [[ -z "$b64_data" ]]; then
        # Fallback: check for URL-based response
        local url
        url=$(echo "$body" | grep -o '"url"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"url"[[:space:]]*:[[:space:]]*"//; s/"$//')
        if [[ -n "$url" ]]; then
            log "Downloading image from URL..."
            curl -s -o "$output_path" "$url"
        else
            log "ERROR: Could not extract image data from API response"
            return 1
        fi
    else
        # Decode base64 to file
        mkdir -p "$(dirname "$output_path")"
        echo "$b64_data" | _decode_base64 > "$output_path"
    fi

    if [[ -f "$output_path" ]] && [[ -s "$output_path" ]]; then
        log "Image saved to ${output_path}"
        return 0
    else
        log "ERROR: Output file is empty or missing"
        return 1
    fi
}

# ============================================================================
# Flux (Black Forest Labs) API
# ============================================================================

# Generate an image using the Flux API (Black Forest Labs).
# Usage: bfl_generate_image "prompt" "output_path" ["size"]
# Size is advisory — Flux uses aspect_ratio. "1024x1536" maps to "2:3".
# Requires BFL_API_KEY environment variable.
bfl_generate_image() {
    local prompt="$1"
    local output_path="$2"
    local size="${3:-1024x1536}"

    if [[ -z "${BFL_API_KEY:-}" ]]; then
        log "ERROR: BFL_API_KEY is not set"
        return 1
    fi

    # Map size to aspect ratio
    local aspect_ratio="2:3"
    case "$size" in
        *x*)
            local w h
            w=$(echo "$size" | cut -d'x' -f1)
            h=$(echo "$size" | cut -d'x' -f2)
            if (( w > h )); then aspect_ratio="3:2"
            elif (( w == h )); then aspect_ratio="1:1"
            else aspect_ratio="2:3"
            fi
            ;;
    esac

    log "Generating image via Flux (aspect ratio ${aspect_ratio})..."

    # Escape prompt for JSON
    local escaped_prompt
    escaped_prompt=$(printf '%s' "$prompt" | sed 's/\\/\\\\/g; s/"/\\"/g; s/$/\\n/g' | tr -d '\n' | sed 's/\\n$//')

    # Step 1: Submit generation request
    local submit_response
    submit_response=$(curl -s -w "\n%{http_code}" \
        -X POST "https://api.bfl.ai/v1/flux-pro-1.1" \
        -H "accept: application/json" \
        -H "x-key: ${BFL_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "{
            \"prompt\": \"${escaped_prompt}\",
            \"aspect_ratio\": \"${aspect_ratio}\"
        }" 2>&1)

    local http_code
    http_code=$(echo "$submit_response" | tail -1)
    local body
    body=$(echo "$submit_response" | sed '$d')

    if [[ "$http_code" != "200" ]]; then
        local error_msg
        error_msg=$(echo "$body" | grep -o '"message"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"message"[[:space:]]*:[[:space:]]*"//; s/"$//')
        log "ERROR: Flux API returned ${http_code}: ${error_msg:-unknown error}"
        return 1
    fi

    # Extract task ID
    local task_id
    task_id=$(echo "$body" | grep -o '"id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"id"[[:space:]]*:[[:space:]]*"//; s/"$//')

    if [[ -z "$task_id" ]]; then
        log "ERROR: Could not extract task ID from Flux API response"
        return 1
    fi

    log "Generation submitted (task: ${task_id}). Polling for result..."

    # Step 2: Poll for result
    local timeout=120
    local elapsed=0
    local poll_interval=3

    while (( elapsed < timeout )); do
        local poll_response
        poll_response=$(curl -s \
            "https://api.bfl.ai/v1/get_result?id=${task_id}" \
            -H "x-key: ${BFL_API_KEY}" 2>&1)

        local status
        status=$(echo "$poll_response" | grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"status"[[:space:]]*:[[:space:]]*"//; s/"$//')

        case "$status" in
            Ready)
                local image_url
                image_url=$(echo "$poll_response" | grep -o '"sample"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"sample"[[:space:]]*:[[:space:]]*"//; s/"$//')

                if [[ -z "$image_url" ]]; then
                    log "ERROR: Result is Ready but no image URL found"
                    return 1
                fi

                log "Downloading generated image..."
                mkdir -p "$(dirname "$output_path")"
                curl -s -o "$output_path" "$image_url"

                if [[ -f "$output_path" ]] && [[ -s "$output_path" ]]; then
                    log "Image saved to ${output_path}"
                    return 0
                else
                    log "ERROR: Download failed or file is empty"
                    return 1
                fi
                ;;
            Error)
                local error_detail
                error_detail=$(echo "$poll_response" | grep -o '"error"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"error"[[:space:]]*:[[:space:]]*"//; s/"$//')
                log "ERROR: Flux generation failed: ${error_detail:-unknown error}"
                return 1
                ;;
            Pending|Processing)
                sleep "$poll_interval"
                elapsed=$((elapsed + poll_interval))
                ;;
            *)
                sleep "$poll_interval"
                elapsed=$((elapsed + poll_interval))
                ;;
        esac
    done

    log "ERROR: Flux generation timed out after ${timeout} seconds"
    return 1
}
