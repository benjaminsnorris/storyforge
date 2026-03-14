#!/bin/bash
# common.sh — Shared functions for Storyforge scripts
#
# Source this file from your script; do not execute it directly.
# The calling script should set its own `set -euo pipefail`.

# ============================================================================
# Signal handling — graceful shutdown of long-running scripts
# ============================================================================

# Tracked child PIDs — scripts register background processes here so they
# can be cleaned up on interrupt.  Use register_child_pid / unregister_child_pid.
_SF_CHILD_PIDS=()
_SF_SHUTTING_DOWN=false

# Register a background PID for cleanup on interrupt.
# Usage: register_child_pid $!
register_child_pid() {
    _SF_CHILD_PIDS+=("$1")
}

# Remove a PID from the tracked list (call after wait succeeds).
# Usage: unregister_child_pid $PID
unregister_child_pid() {
    local target="$1"
    local new_pids=()
    for p in "${_SF_CHILD_PIDS[@]}"; do
        [[ "$p" != "$target" ]] && new_pids+=("$p")
    done
    _SF_CHILD_PIDS=("${new_pids[@]+"${new_pids[@]}"}")
}

# Signal handler — kills all tracked children, logs, and exits.
_sf_handle_interrupt() {
    # Guard against re-entry (multiple signals in quick succession)
    if [[ "$_SF_SHUTTING_DOWN" == true ]]; then
        return
    fi
    _SF_SHUTTING_DOWN=true

    echo ""
    log "INTERRUPTED — shutting down gracefully..."

    # Kill all tracked child processes and their children.
    # Use negative PID to kill the entire process group when possible,
    # ensuring claude processes spawned inside worker subshells also die.
    local killed=0
    for pid in "${_SF_CHILD_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            # Try process group kill first (kills subshell + its children)
            kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
            killed=$((killed + 1))
        fi
    done

    if (( killed > 0 )); then
        log "Sent SIGTERM to ${killed} background process(es). Waiting up to 10s..."

        # Give children a moment to exit cleanly
        local waited=0
        while (( waited < 10 )); do
            local still_running=0
            for pid in "${_SF_CHILD_PIDS[@]}"; do
                kill -0 "$pid" 2>/dev/null && still_running=$((still_running + 1))
            done
            (( still_running == 0 )) && break
            sleep 1
            waited=$((waited + 1))
        done

        # Force-kill any stragglers (process group + individual)
        for pid in "${_SF_CHILD_PIDS[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 -- -"$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
                log "Force-killed process ${pid}"
            fi
        done
    fi

    # Commit any partial work that's been staged
    if [[ -n "${PROJECT_DIR:-}" && -d "${PROJECT_DIR}/.git" ]]; then
        local has_staged
        has_staged=$(git -C "$PROJECT_DIR" diff --cached --quiet 2>/dev/null; echo $?)
        local has_unstaged_eval
        has_unstaged_eval=$(git -C "$PROJECT_DIR" status --porcelain working/evaluations/ 2>/dev/null || true)
        local has_unstaged_scenes
        has_unstaged_scenes=$(git -C "$PROJECT_DIR" status --porcelain scenes/ 2>/dev/null || true)

        local has_unstaged_scores
        has_unstaged_scores=$(git -C "$PROJECT_DIR" status --porcelain working/scores/ 2>/dev/null || true)

        if [[ "$has_staged" != "0" || -n "$has_unstaged_eval" || -n "$has_unstaged_scenes" || -n "$has_unstaged_scores" ]]; then
            log "Committing partial work before exit..."
            (
                cd "$PROJECT_DIR"
                git add working/evaluations/ working/logs/ working/scores/ working/costs/ scenes/ 2>/dev/null || true
                git commit -m "Interrupted: partial work saved" 2>/dev/null || true
                git push 2>/dev/null || true
            )
            log "Partial work committed."
        fi
    fi

    log "Shutdown complete."
    exit 130  # Standard exit code for SIGINT
}

# Install the signal handler.  Scripts that source common.sh get this
# automatically.  The handler fires on Ctrl+C (INT) and TERM.
trap _sf_handle_interrupt INT TERM

# ============================================================================
# Stream-JSON text extraction — shared by all scripts that invoke Claude
# ============================================================================

# extract_claude_response(log_file)
# Extract the text response from a Claude stream-json log file.
# Tries multiple strategies for different output formats.
# Prints the extracted text to stdout. Returns 1 if nothing found.
extract_claude_response() {
    local log_file="$1"
    [[ -f "$log_file" ]] || return 1

    local text=""

    # Strategy 1: Extract from "result" field (claude -p with stream-json)
    text=$(grep '"type":"result"' "$log_file" 2>/dev/null \
        | sed 's/.*"result":"//' | sed 's/","stop_reason.*//' \
        | sed 's/\\n/\n/g; s/\\t/\t/g; s/\\"/"/g; s/\\\\/\\/g' || true)

    # Strategy 2: Extract from assistant message content
    if [[ -z "$text" ]]; then
        text=$(grep '"type":"assistant"' "$log_file" 2>/dev/null \
            | sed 's/.*"text":"//' | sed 's/"}],"stop_reason.*//' \
            | sed 's/\\n/\n/g; s/\\t/\t/g; s/\\"/"/g; s/\\\\/\\/g' || true)
    fi

    # Strategy 3: Extract from content_block_delta (streaming format)
    if [[ -z "$text" ]]; then
        text=$(sed -n 's/.*"type":"content_block_delta".*"text":"\([^"]*\)".*/\1/p' "$log_file" \
            | sed 's/\\n/\n/g; s/\\t/\t/g; s/\\"/"/g; s/\\\\/\\/g' || true)
    fi

    # Strategy 4: Fallback to plain text lines
    if [[ -z "$text" ]]; then
        text=$(grep -v '^\s*{' "$log_file" 2>/dev/null || true)
    fi

    if [[ -z "$text" ]]; then
        return 1
    fi

    echo "$text"
}

# ============================================================================
# Self-healing zones — automatic error recovery for autonomous scripts
# ============================================================================
#
# Usage:
#   begin_healing_zone "description of what we're doing"
#     command1 ...
#     command2 ...
#   end_healing_zone
#
# If any command fails inside the zone, the system:
#   1. Captures the error (command, exit code, stderr)
#   2. Invokes Claude to diagnose and fix the issue
#   3. Retries the zone from the top
#   4. After 3 failed attempts, exits with the original error

_SF_HEALING_ZONE=""           # Current zone description (empty = not in a zone)
_SF_HEALING_ATTEMPT=0         # Current attempt number (0 = not healing)
_SF_HEALING_MAX_ATTEMPTS=3    # Max retries before giving up
_SF_HEALING_ERR_FILE=""       # Temp file capturing stderr during zone
_SF_HEALING_LOG=""            # Dedicated healing log file

# Begin a healing zone. Disables set -e and redirects stderr to capture errors.
# Usage: begin_healing_zone "drafting scene geometry-of-dying"
begin_healing_zone() {
    local description="$1"
    _SF_HEALING_ZONE="$description"

    if [[ "$_SF_HEALING_ATTEMPT" -eq 0 ]]; then
        _SF_HEALING_ATTEMPT=1
    fi

    # Create stderr capture file
    _SF_HEALING_ERR_FILE=$(mktemp "${TMPDIR:-/tmp}/sf-heal-err.XXXXXX")

    # Set up healing log
    if [[ -n "${PROJECT_DIR:-}" ]]; then
        _SF_HEALING_LOG="${PROJECT_DIR}/working/logs/healing-$(date '+%Y%m%d-%H%M%S').log"
        mkdir -p "$(dirname "$_SF_HEALING_LOG")"
    fi

    # Install error trap (replaces set -e behavior inside the zone)
    set +e
    trap '_sf_zone_error_handler "$BASH_COMMAND" $?' ERR
    set -o errtrace  # Ensure ERR trap fires in functions too
}

# End a healing zone. Restores set -e and clears state.
end_healing_zone() {
    # Remove zone error trap, restore set -e
    trap - ERR
    set +o errtrace 2>/dev/null || true
    set -e

    # Clean up
    rm -f "$_SF_HEALING_ERR_FILE"
    _SF_HEALING_ZONE=""
    _SF_HEALING_ATTEMPT=0
    _SF_HEALING_ERR_FILE=""
}

# Error handler — fired by ERR trap inside a healing zone.
_sf_zone_error_handler() {
    local failed_command="$1"
    local exit_code="$2"

    # Don't heal if we're shutting down
    if [[ "$_SF_SHUTTING_DOWN" == true ]]; then
        exit "$exit_code"
    fi

    log "HEALING: Command failed in zone '${_SF_HEALING_ZONE}'"
    log "  Command: ${failed_command}"
    log "  Exit code: ${exit_code}"
    log "  Attempt: ${_SF_HEALING_ATTEMPT} of ${_SF_HEALING_MAX_ATTEMPTS}"

    # Log to healing file too
    if [[ -n "$_SF_HEALING_LOG" ]]; then
        {
            echo "============================================"
            echo "Healing attempt ${_SF_HEALING_ATTEMPT}"
            echo "Zone: ${_SF_HEALING_ZONE}"
            echo "Failed command: ${failed_command}"
            echo "Exit code: ${exit_code}"
            echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
            echo "============================================"
        } >> "$_SF_HEALING_LOG"
    fi

    # Check if we've exhausted attempts
    if [[ "$_SF_HEALING_ATTEMPT" -ge "$_SF_HEALING_MAX_ATTEMPTS" ]]; then
        log "HEALING FAILED: Exhausted ${_SF_HEALING_MAX_ATTEMPTS} attempts for zone '${_SF_HEALING_ZONE}'"
        log "  Last error: ${failed_command} (exit ${exit_code})"

        # Clean up and restore normal error handling
        trap - ERR
        set +o errtrace 2>/dev/null || true
        set -e
        rm -f "$_SF_HEALING_ERR_FILE"
        _SF_HEALING_ZONE=""
        _SF_HEALING_ATTEMPT=0

        # Exit with the original error
        exit "$exit_code"
    fi

    # Capture recent stderr/log context
    local error_context=""
    if [[ -f "$_SF_HEALING_ERR_FILE" && -s "$_SF_HEALING_ERR_FILE" ]]; then
        error_context=$(tail -50 "$_SF_HEALING_ERR_FILE")
    fi

    # Also grab recent log output
    local recent_log=""
    if [[ -n "${LOG_FILE:-}" && -f "$LOG_FILE" ]]; then
        recent_log=$(tail -30 "$LOG_FILE")
    fi

    # Build diagnosis prompt
    _run_healing_attempt "$failed_command" "$exit_code" "$error_context" "$recent_log"
}

# Run a Claude-powered healing attempt.
_run_healing_attempt() {
    local failed_command="$1"
    local exit_code="$2"
    local error_context="$3"
    local recent_log="$4"

    log "HEALING: Invoking Claude to diagnose and fix (attempt ${_SF_HEALING_ATTEMPT})..."

    local heal_model
    heal_model=$(select_model "review")  # Use review-tier model for diagnosis

    local heal_log="${PROJECT_DIR}/working/logs/healing-attempt-${_SF_HEALING_ATTEMPT}.log"

    local heal_prompt
    read -r -d '' heal_prompt <<HEAL_EOF || true
You are a diagnostic assistant for the Storyforge novel-writing toolkit.

An autonomous script encountered an error and needs your help to fix it.

## What the script was doing
${_SF_HEALING_ZONE}

## What failed
Command: ${failed_command}
Exit code: ${exit_code}

## Error output (last 50 lines)
${error_context}

## Recent log output (last 30 lines)
${recent_log}

## Project location
${PROJECT_DIR}

## Your job
1. Diagnose why the command failed
2. Fix the root cause (edit files, fix YAML syntax, create missing files, etc.)
3. Commit your fix: git add -A && git commit -m "Heal: fix for ${_SF_HEALING_ZONE}"
4. Do NOT re-run the original command — the script will retry automatically

## Rules
- Only fix the immediate problem — do not make unrelated changes
- If the error is in a YAML file, read it and fix the syntax
- If a required file is missing, check if it should exist and create it if appropriate
- If the error is a code bug in a Storyforge script, fix it
- If you cannot determine the cause, create a file at working/logs/healing-diagnosis.md explaining what you found
HEAL_EOF

    # Log the prompt to the healing log
    if [[ -n "$_SF_HEALING_LOG" ]]; then
        {
            echo ""
            echo "--- Healing prompt ---"
            echo "$heal_prompt"
            echo "--- End prompt ---"
            echo ""
        } >> "$_SF_HEALING_LOG"
    fi

    # Invoke Claude to fix the issue
    set +e
    claude -p "$heal_prompt" \
        --model "$heal_model" \
        --dangerously-skip-permissions \
        --output-format stream-json \
        --verbose \
        > "$heal_log" 2>&1
    local heal_rc=$?
    set -e

    # Append Claude's output to healing log
    if [[ -n "$_SF_HEALING_LOG" && -f "$heal_log" ]]; then
        {
            echo "--- Claude healing output ---"
            tail -50 "$heal_log"
            echo "--- End output ---"
        } >> "$_SF_HEALING_LOG"
    fi

    if (( heal_rc != 0 )); then
        log "HEALING: Claude healing session itself failed (exit ${heal_rc})"
    else
        log "HEALING: Claude completed diagnosis. Retrying zone..."
    fi

    # Increment attempt counter for the retry
    _SF_HEALING_ATTEMPT=$((_SF_HEALING_ATTEMPT + 1))

    # NOTE: After this function returns, the ERR trap that called us
    # will have already interrupted the zone's execution. The calling
    # script needs to re-enter the zone. This is handled by wrapping
    # zones in a retry loop — see the integration pattern below.
}

# High-level wrapper that handles the retry loop.
# Usage: run_healing_zone "description" zone_function_name [args...]
#
# The zone function should contain the commands to execute.
# It will be called repeatedly until it succeeds or max attempts exhausted.
run_healing_zone() {
    local description="$1"
    shift
    local zone_fn="$1"
    shift

    _SF_HEALING_ATTEMPT=0
    local max=$_SF_HEALING_MAX_ATTEMPTS

    while true; do
        _SF_HEALING_ATTEMPT=$((_SF_HEALING_ATTEMPT + 1))

        if (( _SF_HEALING_ATTEMPT > 1 )); then
            log "HEALING: Retry ${_SF_HEALING_ATTEMPT} of ${max} for '${description}'"
        fi

        # Set up zone state
        _SF_HEALING_ZONE="$description"
        _SF_HEALING_ERR_FILE=$(mktemp "${TMPDIR:-/tmp}/sf-heal-err.XXXXXX")
        if [[ -n "${PROJECT_DIR:-}" && -z "${_SF_HEALING_LOG:-}" ]]; then
            _SF_HEALING_LOG="${PROJECT_DIR}/working/logs/healing-$(date '+%Y%m%d-%H%M%S').log"
            mkdir -p "$(dirname "$_SF_HEALING_LOG")"
        fi

        # Run the zone function
        set +e
        (
            set -e
            "$zone_fn" "$@"
        )
        local zone_rc=$?
        set -e

        rm -f "$_SF_HEALING_ERR_FILE"

        # Success — exit the loop
        if (( zone_rc == 0 )); then
            _SF_HEALING_ZONE=""
            _SF_HEALING_ATTEMPT=0
            _SF_HEALING_LOG=""
            return 0
        fi

        # Zone failed
        log "HEALING: Zone '${description}' failed (exit ${zone_rc}), attempt ${_SF_HEALING_ATTEMPT} of ${max}"

        if (( _SF_HEALING_ATTEMPT >= max )); then
            log "HEALING FAILED: Exhausted ${max} attempts for '${description}'"
            _SF_HEALING_ZONE=""
            _SF_HEALING_ATTEMPT=0
            _SF_HEALING_LOG=""
            exit "$zone_rc"
        fi

        # Capture context for healing
        local error_context=""
        if [[ -f "$_SF_HEALING_ERR_FILE" && -s "$_SF_HEALING_ERR_FILE" ]]; then
            error_context=$(tail -50 "$_SF_HEALING_ERR_FILE")
        fi
        local recent_log=""
        if [[ -n "${LOG_FILE:-}" && -f "$LOG_FILE" ]]; then
            recent_log=$(tail -30 "$LOG_FILE")
        fi

        # Run healing attempt
        _run_healing_attempt "zone: ${description}" "$zone_rc" "$error_context" "$recent_log"
    done
}

# ============================================================================
# Project root detection
# ============================================================================

# Walk up from the current directory looking for storyforge.yaml.
# Sets PROJECT_DIR and exports it.
# Exits with error if not found within 20 levels.
detect_project_root() {
    local dir="$PWD"
    local depth=0
    local max_depth=20

    while [[ "$dir" != "/" ]] && (( depth < max_depth )); do
        if [[ -f "$dir/storyforge.yaml" ]]; then
            PROJECT_DIR="$dir"
            export PROJECT_DIR
            return 0
        fi
        dir="$(dirname "$dir")"
        depth=$((depth + 1))
    done

    echo "ERROR: Could not find storyforge.yaml in any parent directory." >&2
    echo "Are you inside a Storyforge project?" >&2
    exit 1
}

# ============================================================================
# YAML helpers (no yq dependency)
# ============================================================================

# Read a value from storyforge.yaml using grep/sed.
# Supports flat keys ("title") and one-level-deep dotted keys ("project.title").
#
# Usage:
#   read_yaml_field "title"            # top-level key
#   read_yaml_field "project.title"    # key under a parent mapping
#
# Returns the value with surrounding quotes stripped. Prints empty string if
# the key is not found.
read_yaml_field() {
    local field="$1"
    local yaml_file="${PROJECT_DIR}/storyforge.yaml"

    if [[ ! -f "$yaml_file" ]]; then
        echo ""
        return 1
    fi

    # Split on dot: parent.child
    if [[ "$field" == *.* ]]; then
        local parent="${field%%.*}"
        local child="${field#*.}"

        # Find the parent block, then look for the child key within it.
        # We grab lines after the parent header until the next top-level key.
        sed -n "/^${parent}:/,/^[^ ]/p" "$yaml_file" \
            | grep -E "^[[:space:]]+${child}:" \
            | head -1 \
            | sed 's/^[[:space:]]*'"${child}"':[[:space:]]*//' \
            | sed 's/^["'"'"']//' \
            | sed 's/["'"'"']$//' \
            | sed 's/[[:space:]]*$//'
    else
        grep -E "^${field}:" "$yaml_file" \
            | head -1 \
            | sed 's/^'"${field}"':[[:space:]]*//' \
            | sed 's/^["'"'"']//' \
            | sed 's/["'"'"']$//' \
            | sed 's/[[:space:]]*$//'
    fi
}

# ============================================================================
# Logging
# ============================================================================

# Timestamped log message to both stdout and LOG_FILE (if set).
# Usage: log "message"
log() {
    local timestamp
    timestamp="[$(date '+%Y-%m-%d %H:%M:%S')]"
    local msg="${timestamp} $*"

    echo "$msg"

    if [[ -n "${LOG_FILE:-}" ]]; then
        # Ensure log directory exists
        mkdir -p "$(dirname "$LOG_FILE")"
        echo "$msg" >> "$LOG_FILE"
    fi
}

# ============================================================================
# File checks
# ============================================================================

# Verify that a required file exists. If it does not, log an error and exit.
# Usage: check_file_exists "reference/voice-guide.md" "Voice guide"
check_file_exists() {
    local filepath="$1"
    local label="${2:-$filepath}"

    # Resolve relative paths against PROJECT_DIR
    if [[ "$filepath" != /* ]]; then
        filepath="${PROJECT_DIR}/${filepath}"
    fi

    if [[ ! -f "$filepath" ]]; then
        log "ERROR: Required file missing — ${label}: ${filepath}"
        exit 1
    fi
}

# ============================================================================
# Plugin directory
# ============================================================================

# Get the Storyforge plugin directory (where references/ and templates/ live).
# Navigates up from this script's location to the repo root.
# Usage: PLUGIN_DIR=$(get_plugin_dir)
get_plugin_dir() {
    local script_source="${BASH_SOURCE[0]}"
    # Resolve symlinks
    while [[ -L "$script_source" ]]; do
        local link_target
        link_target="$(readlink "$script_source")"
        if [[ "$link_target" == /* ]]; then
            script_source="$link_target"
        else
            script_source="$(dirname "$script_source")/$link_target"
        fi
    done
    local lib_dir
    lib_dir="$(cd "$(dirname "$script_source")" && pwd)"
    # lib/ -> scripts/ -> repo root
    echo "$(dirname "$(dirname "$lib_dir")")"
}

# Source companion libraries that live alongside common.sh
_sf_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "${_sf_lib_dir}/csv.sh" ]] && source "${_sf_lib_dir}/csv.sh"
[[ -f "${_sf_lib_dir}/costs.sh" ]] && source "${_sf_lib_dir}/costs.sh"
[[ -f "${_sf_lib_dir}/scoring.sh" ]] && source "${_sf_lib_dir}/scoring.sh"
[[ -f "${_sf_lib_dir}/scene-filter.sh" ]] && source "${_sf_lib_dir}/scene-filter.sh"
[[ -f "${_sf_lib_dir}/characters.sh" ]] && source "${_sf_lib_dir}/characters.sh"
unset _sf_lib_dir

# ============================================================================
# Craft engine section extraction
# ============================================================================

# Extract one or more sections from the craft engine by section number.
#
# The craft engine uses "## N. Section Title" as section delimiters.
# This function extracts full sections including subsections (### headings).
#
# Arguments:
#   $1..N — One or more section numbers (e.g., 2 3 5)
#
# Globals:
#   Uses get_plugin_dir() to locate the craft engine file.
#
# Output:
#   Prints the extracted sections to stdout, separated by --- dividers.
#   Returns 1 if the craft engine file is not found.
#
# Usage:
#   extract_craft_sections 2 3 5       # Scene Craft + Prose Craft + Rules
#   sections=$(extract_craft_sections 2 3 5)
extract_craft_sections() {
    local plugin_dir
    plugin_dir=$(get_plugin_dir)
    local craft_file="${plugin_dir}/references/craft-engine.md"

    if [[ ! -f "$craft_file" ]]; then
        log "WARNING: Craft engine not found at ${craft_file}"
        return 1
    fi

    local first=true
    for section_num in "$@"; do
        if [[ "$first" == true ]]; then
            first=false
        else
            echo ""
            echo "---"
            echo ""
        fi
        awk -v num="$section_num" '
            $0 ~ "^## " num "\\. " { found=1 }
            found && /^## [0-9]+\. / && !($0 ~ "^## " num "\\. ") { found=0 }
            found { print }
        ' "$craft_file"
    done
}

# ============================================================================
# Background progress monitor
# ============================================================================

# Poll filesystem every 30 seconds during a claude invocation and log milestones.
# Run in background: monitor_progress ... &
#
# Arguments:
#   $1 — scene_id (e.g., "act1-sc05")
#   $2 — git HEAD before invocation
#   $3 — start time (epoch seconds)
#
# Globals used: PROJECT_DIR, LOG_FILE (via log function)
monitor_progress() {
    local scene_id="$1"
    local head_before="$2"
    local start_time="$3"

    local scene_file="${PROJECT_DIR}/scenes/${scene_id}.md"
    local continuity_file="${PROJECT_DIR}/reference/continuity-tracker.md"

    local draft_detected=false
    local continuity_detected=false
    local commit_detected=false
    local last_word_count=0
    local ticks=0

    # Snapshot continuity tracker mtime (macOS stat syntax, with Linux fallback)
    local tracker_mtime=0
    if [[ -f "$continuity_file" ]]; then
        tracker_mtime=$(stat -f %m "$continuity_file" 2>/dev/null \
                     || stat -c %Y "$continuity_file" 2>/dev/null \
                     || echo 0)
    fi

    while true; do
        sleep 30
        ticks=$((ticks + 1))
        local elapsed=$(( $(date +%s) - start_time ))
        local mins=$(( elapsed / 60 ))

        # Scene file created or growing?
        if [[ -f "$scene_file" ]]; then
            local wc
            wc=$(wc -w < "$scene_file" 2>/dev/null | tr -d ' ')
            if [[ "$draft_detected" == false ]]; then
                draft_detected=true
                log "  [${scene_id}] Scene file created (~${wc} words) [${mins}m]"
            elif (( wc > last_word_count + 300 )); then
                log "  [${scene_id}] Draft growing: ~${wc} words [${mins}m]"
            fi
            last_word_count=$wc
        fi

        # Continuity tracker modified?
        if [[ "$continuity_detected" == false && -f "$continuity_file" ]]; then
            local tracker_now
            tracker_now=$(stat -f %m "$continuity_file" 2>/dev/null \
                       || stat -c %Y "$continuity_file" 2>/dev/null \
                       || echo 0)
            if (( tracker_now > tracker_mtime )); then
                continuity_detected=true
                log "  [${scene_id}] Continuity tracker updated [${mins}m]"
            fi
        fi

        # Git commit made?
        if [[ "$commit_detected" == false ]]; then
            local head_now
            head_now=$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo "")
            if [[ -n "$head_now" && "$head_now" != "$head_before" ]]; then
                commit_detected=true
                log "  [${scene_id}] Git commit detected [${mins}m]"
            fi
        fi

        # Heartbeat every 2 minutes (4 ticks x 30s)
        if (( ticks % 4 == 0 )); then
            log "  [${scene_id}] ${mins}m elapsed..."
        fi
    done
}

# ============================================================================
# Model selection
# ============================================================================

# Default model for each task type. These are the smart defaults that balance
# quality vs. cost. Override with STORYFORGE_MODEL env var.
#
# Task types:
#   drafting     — scene writing (maximum creativity)
#   revision     — prose/voice/character revision (high creativity)
#   mechanical   — continuity, fact-checking, thread tracking (low creativity)
#   evaluation   — evaluator agents (analytical, structured output)
#   synthesis    — cross-evaluator reconciliation (high reasoning)
#   review       — pipeline QA (structured, bounded, mechanical)
#
# Usage: model=$(select_model "drafting")
select_model() {
    local task_type="$1"

    # Environment override takes precedence
    if [[ -n "${STORYFORGE_MODEL:-}" ]]; then
        echo "$STORYFORGE_MODEL"
        return 0
    fi

    case "$task_type" in
        drafting)    echo "claude-opus-4-6" ;;
        revision)    echo "claude-opus-4-6" ;;
        mechanical)  echo "claude-sonnet-4-6" ;;
        evaluation)  echo "claude-sonnet-4-6" ;;
        synthesis)   echo "claude-opus-4-6" ;;
        review)      echo "claude-sonnet-4-6" ;;
        *)           echo "claude-opus-4-6" ;;
    esac
}

# Select model for a revision pass based on pass name and purpose.
# Creative passes (prose, voice, character) get Opus.
# Mechanical passes (continuity, timeline) get Sonnet.
#
# Usage: model=$(select_revision_model "prose-tightening" "Cut filler, tighten sentences")
select_revision_model() {
    local pass_name="$1"
    local purpose="$2"

    # Environment override
    if [[ -n "${STORYFORGE_MODEL:-}" ]]; then
        echo "$STORYFORGE_MODEL"
        return 0
    fi

    local pass_key
    pass_key="$(echo "$pass_name $purpose" | tr '[:upper:]' '[:lower:]')"

    # Mechanical passes: continuity, timeline, fact-checking — Sonnet is sufficient.
    # But "voice-consistency" or "character-consistency" are creative, not mechanical.
    # Only match when continuity/timeline/fact-check is the primary concern.
    if [[ "$pass_key" =~ (continuity|timeline|fact.check|thread.track) ]]; then
        echo "claude-sonnet-4-6"  # Mechanical — factual verification
    else
        echo "claude-opus-4-6"    # Creative — prose, voice, character, structure
    fi
}

# ============================================================================
# Coaching level
# ============================================================================

# Get the coaching level for this session.
#
# Priority:
#   1. STORYFORGE_COACHING env var (set by --coaching flag in scripts)
#   2. project.coaching_level from storyforge.yaml
#   3. Default: "full"
#
# Valid values: full, coach, strict
#
# Usage: level=$(get_coaching_level)
get_coaching_level() {
    # Flag/env override takes precedence
    if [[ -n "${STORYFORGE_COACHING:-}" ]]; then
        echo "$STORYFORGE_COACHING"
        return 0
    fi

    # Read from project config
    local level
    level=$(read_yaml_field "project.coaching_level" 2>/dev/null || echo "")

    if [[ -z "$level" ]]; then
        echo "full"
        return 0
    fi

    # Validate
    case "$level" in
        full|coach|strict) echo "$level" ;;
        *) echo "full" ;;
    esac
}

# ============================================================================
# Pipeline manifest (multi-cycle evaluation/revision tracking)
# ============================================================================

# Get the pipeline manifest path.
# Usage: pipeline_file=$(get_pipeline_file)
get_pipeline_file() {
    echo "${PROJECT_DIR}/working/pipeline.yaml"
}

# Initialize the pipeline manifest if it doesn't exist.
# Creates working/pipeline.yaml with current_cycle: 0 and empty cycles list.
# Idempotent — no-op if file already exists.
# Usage: ensure_pipeline_manifest
ensure_pipeline_manifest() {
    local pipeline_file
    pipeline_file=$(get_pipeline_file)

    if [[ -f "$pipeline_file" ]]; then
        return 0
    fi

    mkdir -p "$(dirname "$pipeline_file")"

    cat > "$pipeline_file" <<'MANIFEST_EOF'
# Pipeline Manifest — tracks evaluation/revision cycles
# Auto-maintained by Storyforge scripts. Do not edit manually.

current_cycle: 0

cycles: []
MANIFEST_EOF
}

# Get the current cycle number from the pipeline manifest.
# Returns 0 if manifest doesn't exist or current_cycle is not set.
# Usage: cycle=$(get_current_cycle)
get_current_cycle() {
    local pipeline_file
    pipeline_file=$(get_pipeline_file)

    if [[ ! -f "$pipeline_file" ]]; then
        echo "0"
        return 0
    fi

    local cycle
    cycle=$(grep -E '^current_cycle:' "$pipeline_file" \
        | head -1 \
        | sed 's/^current_cycle:[[:space:]]*//' \
        | sed 's/[[:space:]]*$//')

    echo "${cycle:-0}"
}

# Read a field from a specific cycle in the pipeline manifest.
# Usage: read_cycle_field 2 "evaluation" → "eval-20260305-091500"
read_cycle_field() {
    local cycle_id="$1"
    local field="$2"
    local pipeline_file
    pipeline_file=$(get_pipeline_file)

    if [[ ! -f "$pipeline_file" ]]; then
        echo ""
        return 1
    fi

    # Extract the value of the field from the matching cycle block
    awk -v cid="$cycle_id" -v fld="$field" '
        /^cycles:/ { in_cycles = 1; next }
        !in_cycles { next }
        /^[^ \t]/ && !/^[[:space:]]/ { exit }
        /^[[:space:]]*- id:/ {
            match($0, /id:[[:space:]]*/)
            val = substr($0, RSTART + RLENGTH)
            gsub(/[[:space:]]*$/, "", val)
            gsub(/^["'"'"']|["'"'"']$/, "", val)
            found = (val == cid) ? 1 : 0
        }
        found && $0 ~ "^[[:space:]]+" fld ":" {
            sub("^[[:space:]]+" fld ":[[:space:]]*", "")
            gsub(/^["'"'"']|["'"'"']$/, "")
            gsub(/[[:space:]]*$/, "")
            print
            exit
        }
    ' "$pipeline_file"
}

# Start a new cycle in the pipeline manifest.
# Increments current_cycle, appends a new cycle entry.
# Returns the new cycle ID.
# Usage: CYCLE_ID=$(start_new_cycle)
start_new_cycle() {
    ensure_pipeline_manifest

    local pipeline_file
    pipeline_file=$(get_pipeline_file)

    local current
    current=$(get_current_cycle)
    local new_id=$((current + 1))
    local today
    today=$(date '+%Y-%m-%d')

    # Update current_cycle
    sed -i '' "s/^current_cycle:.*/current_cycle: ${new_id}/" "$pipeline_file"

    # Append new cycle entry
    # Handle the empty list case: replace "cycles: []" with "cycles:" + entry
    if grep -q '^cycles: \[\]' "$pipeline_file"; then
        sed -i '' "s/^cycles: \[\]/cycles:/" "$pipeline_file"
    fi

    cat >> "$pipeline_file" <<CYCLE_EOF
  - id: ${new_id}
    started: "${today}"
    status: pending
    evaluation:
    plan:
    review:
    recommendations:
    summary:
CYCLE_EOF

    echo "$new_id"
}

# Update a field on a specific cycle in the pipeline manifest.
# Usage: update_cycle_field 2 "status" "revising"
# Usage: update_cycle_field 2 "plan" "revision-plan-2.yaml"
update_cycle_field() {
    local cycle_id="$1"
    local field="$2"
    local value="$3"
    local pipeline_file
    pipeline_file=$(get_pipeline_file)

    if [[ ! -f "$pipeline_file" ]]; then
        return 1
    fi

    local tmp_file="${pipeline_file}.tmp"

    awk -v cid="$cycle_id" -v fld="$field" -v newval="$value" '
        /^cycles:/ { in_cycles = 1; print; next }
        !in_cycles { print; next }
        /^[^ \t]/ && !/^[[:space:]]/ { in_cycles = 0; print; next }
        /^[[:space:]]*- id:/ {
            match($0, /id:[[:space:]]*/)
            val = substr($0, RSTART + RLENGTH)
            gsub(/[[:space:]]*$/, "", val)
            gsub(/^["'"'"']|["'"'"']$/, "", val)
            in_target = (val == cid) ? 1 : 0
            print; next
        }
        in_target && $0 ~ "^[[:space:]]+" fld ":" {
            match($0, /^[[:space:]]+/)
            indent = substr($0, RSTART, RLENGTH)
            if (newval == "") {
                print indent fld ":"
            } else {
                print indent fld ": " newval
            }
            next
        }
        { print }
    ' "$pipeline_file" > "$tmp_file"

    mv "$tmp_file" "$pipeline_file"
}

# Get the plan file path for the current or specified cycle.
# Falls back to the legacy hardcoded path if no manifest or no plan set.
# Usage: plan_file=$(get_cycle_plan_file)
# Usage: plan_file=$(get_cycle_plan_file 2)
get_cycle_plan_file() {
    local cycle="${1:-}"
    if [[ -z "$cycle" ]]; then
        cycle=$(get_current_cycle)
    fi

    local plan_name
    plan_name=$(read_cycle_field "$cycle" "plan")

    if [[ -n "$plan_name" ]]; then
        echo "${PROJECT_DIR}/working/plans/${plan_name}"
    else
        # Fallback to legacy path
        echo "${PROJECT_DIR}/working/plans/revision-plan.yaml"
    fi
}

# Get the evaluation directory for the current or specified cycle.
# Usage: eval_dir=$(get_cycle_eval_dir)
# Usage: eval_dir=$(get_cycle_eval_dir 2)
get_cycle_eval_dir() {
    local cycle="${1:-}"
    if [[ -z "$cycle" ]]; then
        cycle=$(get_current_cycle)
    fi

    local eval_name
    eval_name=$(read_cycle_field "$cycle" "evaluation")

    if [[ -n "$eval_name" ]]; then
        echo "${PROJECT_DIR}/working/evaluations/${eval_name}"
    else
        echo ""
    fi
}

# ============================================================================
# Git branch and PR workflow
# ============================================================================

# Check if the gh CLI is available.
# Usage: has_gh && echo "yes" || echo "no"
has_gh() {
    command -v gh >/dev/null 2>&1
}

# Get the current git branch name.
# Usage: branch=$(current_branch "$PROJECT_DIR")
current_branch() {
    local project_dir="$1"
    git -C "$project_dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo ""
}

# Create a feature branch for a storyforge command.
# If already on a storyforge/* branch, treats it as a resume (no-op).
# Sets and exports STORYFORGE_BRANCH.
#
# Usage: create_branch "write" "$PROJECT_DIR"
create_branch() {
    local command_name="$1"
    local project_dir="$2"

    local branch
    branch=$(current_branch "$project_dir")

    # Already on a storyforge feature branch — resume
    if [[ "$branch" == storyforge/* ]]; then
        STORYFORGE_BRANCH="$branch"
        export STORYFORGE_BRANCH
        log "Resuming on branch: ${STORYFORGE_BRANCH}"
        return 0
    fi

    # Create new feature branch
    STORYFORGE_BRANCH="storyforge/${command_name}-$(date '+%Y%m%d-%H%M')"
    export STORYFORGE_BRANCH

    set +e
    git -C "$project_dir" checkout -b "$STORYFORGE_BRANCH" 2>/dev/null
    local branch_rc=$?
    set -e
    if [[ $branch_rc -ne 0 ]]; then
        log "ERROR: Failed to create branch ${STORYFORGE_BRANCH}"
        return 1
    fi

    log "Created branch: ${STORYFORGE_BRANCH}"
    return 0
}

# Push the current branch with -u to set up upstream tracking.
# If the branch has no commits ahead of its parent, creates an initial
# commit (updates storyforge.yaml phase or empty commit) so the push
# and subsequent PR creation succeed.
# Idempotent — safe to call multiple times.
#
# Usage: ensure_branch_pushed "$PROJECT_DIR"
ensure_branch_pushed() {
    local project_dir="$1"
    local branch="${STORYFORGE_BRANCH:-$(current_branch "$project_dir")}"

    if [[ -z "$branch" ]]; then
        log "WARNING: No branch to push"
        return 1
    fi

    # Check if the branch has any commits ahead of its merge base.
    # If not, we need an initial commit so gh pr create has a diff.
    local base_branch
    base_branch=$(git -C "$project_dir" rev-parse --abbrev-ref '@{upstream}' 2>/dev/null \
               || git -C "$project_dir" config init.defaultBranch 2>/dev/null \
               || echo "main")
    # Strip remote prefix (e.g., "origin/main" -> "main")
    base_branch="${base_branch#origin/}"

    local ahead
    ahead=$(git -C "$project_dir" rev-list --count "${base_branch}..HEAD" 2>/dev/null || echo "0")

    if [[ "$ahead" == "0" ]]; then
        # Try to stage any pending state changes (phase update, yaml edits)
        local committed=false
        if ! git -C "$project_dir" diff --quiet 2>/dev/null; then
            # There are unstaged changes — stage storyforge.yaml and CLAUDE.md
            git -C "$project_dir" add storyforge.yaml 2>/dev/null || true
            git -C "$project_dir" add CLAUDE.md 2>/dev/null || true
            git -C "$project_dir" commit -m "Start ${branch##storyforge/}" 2>/dev/null && committed=true
        fi

        if [[ "$committed" != true ]]; then
            # No changes to commit, or commit failed — create an empty commit
            git -C "$project_dir" commit --allow-empty \
                -m "Start ${branch##storyforge/}" 2>/dev/null && committed=true
        fi

        if [[ "$committed" == true ]]; then
            log "Initial commit on ${branch}"
        fi
    fi

    git -C "$project_dir" push -u origin "$branch" 2>/dev/null || {
        log "WARNING: Could not push branch ${branch} to origin"
        return 1
    }

    return 0
}

# Ensure a GitHub label exists (create silently if missing).
# Usage: ensure_label "in-progress" "fef2c0" "Work is underway" "$PROJECT_DIR"
ensure_label() {
    local label_name="$1"
    local color="$2"
    local description="$3"
    local project_dir="$4"

    has_gh || return 0
    (cd "$project_dir" && gh label create "$label_name" \
        --color "$color" \
        --description "$description" \
        2>/dev/null) || true
}

# Ensure all storyforge labels exist in the repo.
# Called once by create_draft_pr before creating a PR.
# Usage: ensure_all_labels "$PROJECT_DIR"
ensure_all_labels() {
    local project_dir="$1"

    has_gh || return 0

    # Status labels
    ensure_label "in-progress"    "fef2c0" "Autonomous work is underway"           "$project_dir"
    ensure_label "reviewing"      "5319e7" "Pipeline review in progress"            "$project_dir"
    ensure_label "ready-to-merge" "0e8a16" "Review complete — author may merge"     "$project_dir"

    # Work type labels
    ensure_label "drafting"       "1d76db" "Scene drafting session"                 "$project_dir"
    ensure_label "evaluation"     "d93f0b" "Multi-agent evaluation panel"           "$project_dir"
    ensure_label "revision"       "c5def5" "Revision pass execution"               "$project_dir"
    ensure_label "assembly"       "bfdadc" "Manuscript assembly and production"     "$project_dir"
}

# Create a draft PR for the current branch.
# If a PR already exists for this branch, fetches its number instead.
# Sets and exports STORYFORGE_PR_NUMBER.
#
# Usage: create_draft_pr "Draft: My Novel scenes" "$PR_BODY" "$PROJECT_DIR" "drafting"
create_draft_pr() {
    local title="$1"
    local body="$2"
    local project_dir="$3"
    local work_type="${4:-}"

    if ! has_gh; then
        log "WARNING: gh CLI not available — skipping PR creation"
        STORYFORGE_PR_NUMBER=""
        export STORYFORGE_PR_NUMBER
        return 0
    fi

    # Ensure all labels exist
    ensure_all_labels "$project_dir"

    # Check if PR already exists for this branch
    local existing_pr
    existing_pr=$(cd "$project_dir" && gh pr view --json number --jq '.number' 2>/dev/null || echo "")

    if [[ -n "$existing_pr" ]]; then
        STORYFORGE_PR_NUMBER="$existing_pr"
        export STORYFORGE_PR_NUMBER
        log "Found existing PR #${STORYFORGE_PR_NUMBER}"
        return 0
    fi

    # Create draft PR
    local label_args="--label in-progress"
    if [[ -n "$work_type" ]]; then
        label_args="${label_args} --label ${work_type}"
    fi

    local pr_url
    pr_url=$(cd "$project_dir" && gh pr create \
        --draft \
        --title "$title" \
        --body "$body" \
        $label_args 2>/dev/null) || {
        log "WARNING: Failed to create draft PR"
        STORYFORGE_PR_NUMBER=""
        export STORYFORGE_PR_NUMBER
        return 1
    }

    # Extract PR number from URL (format: https://github.com/owner/repo/pull/123)
    STORYFORGE_PR_NUMBER=$(echo "$pr_url" | grep -oE '[0-9]+$' || echo "")
    export STORYFORGE_PR_NUMBER

    if [[ -n "$STORYFORGE_PR_NUMBER" ]]; then
        log "Created draft PR #${STORYFORGE_PR_NUMBER}: ${title}"
    else
        log "WARNING: PR created but could not parse number from: ${pr_url}"
    fi

    return 0
}

# Check off a task in the PR body.
# Replaces "- [ ] {task_text}" with "- [x] {task_text}".
#
# Usage: update_pr_task "Draft scene act1-sc01" "$PROJECT_DIR"
update_pr_task() {
    local task_text="$1"
    local project_dir="${2:-${PROJECT_DIR:-}}"
    local pr_number="${STORYFORGE_PR_NUMBER:-}"

    if ! has_gh || [[ -z "$pr_number" ]]; then
        return 0
    fi

    # Fetch current body
    local body
    body=$(cd "$project_dir" && gh pr view "$pr_number" --json body --jq '.body' 2>/dev/null) || return 0

    # Escape special sed characters in task text
    local escaped
    escaped=$(printf '%s' "$task_text" | sed 's/[\/&.*[\^$]/\\&/g')

    # Replace unchecked with checked
    local new_body
    new_body=$(echo "$body" | sed "s/- \[ \] ${escaped}/- [x] ${escaped}/")

    # Update PR body
    (cd "$project_dir" && gh pr edit "$pr_number" --body "$new_body" 2>/dev/null) || {
        log "WARNING: Failed to update PR task: ${task_text}"
    }
}

# ============================================================================
# Review phase helpers
# ============================================================================

# Run a single headless Claude session for review/cleanup/recommend.
# Usage: _run_headless_session "$prompt" "$model" "$log_file"
_run_headless_session() {
    local prompt="$1"
    local model="$2"
    local log_file="$3"

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

# Run a cleanup pass — fix items identified in the review report.
# Usage: run_cleanup_pass "$review_file" "$review_type" "$project_dir" "$iteration"
run_cleanup_pass() {
    local review_file="$1"
    local review_type="$2"
    local project_dir="$3"
    local iteration="$4"

    local cleanup_log="${project_dir}/working/logs/cleanup-${iteration}.log"
    local cleanup_model
    cleanup_model=$(select_model "review")

    local cleanup_prompt
    read -r -d '' cleanup_prompt <<CLEANUP_EOF || true
You are performing cleanup pass ${iteration} on a Storyforge project after a ${review_type} review.

Read the review report at: ${review_file}

Focus ONLY on the "## Fixable Items" section. For each unchecked item (lines starting with "- [ ]"):
1. Read the referenced file
2. Make the specific fix described
3. Stage the change

After fixing all items, commit and push:
  git add -A
  git commit -m "Review: cleanup pass ${iteration} (${review_type})"
  git push

Rules:
- Only fix items listed in "Fixable Items" — nothing else
- Do not make subjective changes, creative edits, or prose improvements
- Do not modify scene prose content
- If an item is ambiguous or requires author judgment, skip it
CLEANUP_EOF

    log "  Cleanup pass ${iteration} (model: ${cleanup_model})..."
    _run_headless_session "$cleanup_prompt" "$cleanup_model" "$cleanup_log"
    local rc=$?

    if (( rc != 0 )); then
        log "WARNING: Cleanup pass ${iteration} failed (exit code ${rc})"
    fi

    return $rc
}

# Run the recommend step — write next-step recommendations.
# Usage: run_recommend_step "$review_type" "$project_dir"
run_recommend_step() {
    local review_type="$1"
    local project_dir="$2"

    local title
    title=$(read_yaml_field "project.title" 2>/dev/null || read_yaml_field "title" 2>/dev/null || echo "Unknown")
    local today
    today=$(date '+%Y-%m-%d')

    # Determine cycle-aware output file
    local cycle_id
    cycle_id=$(get_current_cycle)
    local recommend_file="working/recommendations.md"
    if [[ "$cycle_id" != "0" ]]; then
        recommend_file="working/recommendations-${cycle_id}.md"
    fi

    local recommend_log="${project_dir}/working/logs/recommend-$(date '+%Y%m%d-%H%M%S').log"
    local recommend_model
    recommend_model=$(select_model "review")

    # Build pipeline context for the prompt
    local pipeline_context=""
    local pipeline_file
    pipeline_file=$(get_pipeline_file)
    if [[ -f "$pipeline_file" ]]; then
        pipeline_context="- working/pipeline.yaml (pipeline manifest — shows cycle history)"
    fi

    local recommend_prompt
    read -r -d '' recommend_prompt <<RECOMMEND_EOF || true
You are writing next-step recommendations for a Storyforge novel project after a ${review_type} pipeline run.

## Read Project State

Read ALL of the following files to understand the full picture:
- storyforge.yaml (project config, phase, coaching level, artifact status)
${pipeline_context}
- CLAUDE.md (recent activity, standing instructions)
- The most recent review report in working/reviews/
- The most recent evaluation findings in working/evaluations/ — read findings.yaml or synthesis.md if they exist. Note severity counts (critical/major/minor).
- The current cycle's revision plan in working/plans/ (if it exists) — check pass completion status
- reference/key-decisions.md (if it exists) — do not recommend against settled decisions
- Prior recommendations in working/recommendations*.md — avoid repeating the same recommendation

## Decision Framework

Apply these priorities in order. Stop at the first one that applies:

1. **Pipeline cycle state** — if a cycle is in progress (evaluating/planning/revising/reviewing), recommend the next step in that cycle. Do not start something new mid-cycle.
   - Status "planning" → recommend /storyforge:plan-revision
   - Status "revising" → revision is running, note progress
   - Status "reviewing" → recommend /storyforge:review

2. **Unaddressed evaluation findings** — if critical/major findings exist without a revision plan, recommend /storyforge:plan-revision with specific finding counts and top issues.

3. **Blockers** — empty scene index (recommend /storyforge:scenes), missing voice guide (recommend /storyforge:voice), no drafted scenes but ready to draft (recommend ./storyforge write).

4. **Artifact gaps** — missing character bible, world bible, story architecture. Recommend /storyforge:develop with specific direction.

5. **Deepening** — artifacts exist but are thin. Recommend the most impactful deepening.

6. **Creative exploration** — foundation is solid, recommend what-if exercises, thematic work, or subplot development.

## Write the Recommendation

Save to: ${recommend_file}

Use this exact format:

# Next Steps — ${title}
**After:** ${review_type} pipeline (cycle ${cycle_id})
**Date:** ${today}

## Recommended Next Step
[One clear recommendation with rationale. Be specific about what command or skill to run and why. Not "work on characters" but "Run /storyforge:plan-revision to address the 3 critical findings from evaluation — pacing issues in Act 2 and the unresolved continuity gap in chapters 8-10."]

## Other Options
- [Next priority from the framework, with brief rationale]
- [Another option, with brief rationale]

## Project Health
[One sentence assessment of where the manuscript stands]

Then commit and push:
  git add ${recommend_file}
  git commit -m "Recommend: next steps after ${review_type} (cycle ${cycle_id})"
  git push
RECOMMEND_EOF

    log "Running recommend step..."
    _run_headless_session "$recommend_prompt" "$recommend_model" "$recommend_log"
    local rc=$?

    if (( rc != 0 )); then
        log "WARNING: Recommend step failed (exit code ${rc})"
    fi

    # Fallback commit if Claude didn't
    if [[ -f "${project_dir}/${recommend_file}" ]]; then
        local head_before head_after
        head_before=$(git -C "$project_dir" rev-parse HEAD 2>/dev/null || echo "none")
        (
            cd "$project_dir"
            git add "${recommend_file}" working/logs/ working/pipeline.yaml 2>/dev/null || true
            git commit -m "Recommend: next steps after ${review_type} (cycle ${cycle_id})" 2>/dev/null || true
            git push 2>/dev/null || true
        )
        log "Recommendations saved: ${recommend_file}"
    fi

    # Update pipeline manifest
    if [[ "$cycle_id" != "0" ]]; then
        local recommend_basename
        recommend_basename=$(basename "$recommend_file")
        update_cycle_field "$cycle_id" "recommendations" "$recommend_basename"
        update_cycle_field "$cycle_id" "status" "complete"
    fi
}

# Build the PR comment for the review phase.
# For evaluations, posts a synthesis summary instead of the review report.
# Usage: build_pr_comment "$review_type" "$review_file" "$project_dir"
build_pr_comment() {
    local review_type="$1"
    local review_file="$2"
    local project_dir="$3"

    if [[ "$review_type" == "evaluation" ]]; then
        # Post synthesis summary instead of review meta-analysis
        local synth_file
        synth_file=$(ls -t "${project_dir}"/working/evaluations/*/synthesis.md 2>/dev/null | head -1)
        if [[ -n "$synth_file" && -f "$synth_file" ]]; then
            echo "## Evaluation Synthesis Summary"
            echo ""
            # Extract Overall Assessment and Prioritized Action Items
            awk '/^## Overall Assessment$/,0' "$synth_file"
            return 0
        fi
    fi

    # Default: post the review report itself
    if [[ -f "$review_file" ]]; then
        cat "$review_file"
    fi
}

# ============================================================================
# Review phase (main entry point)
# ============================================================================

# Run the review phase at the end of an autonomous process.
#
# Sequence:
#   1. PR label: in-progress → reviewing
#   2. Run Claude review (produces report with Fixable Items section)
#   3. If coaching == "full": cleanup loop (fix items, re-review, max 3x)
#   4. If coaching == "full": recommend step (write next-steps)
#   5. PR label: reviewing → ready-to-merge, post comment
#   6. Check off "Review" task
#
# Usage: run_review_phase "drafting" "$PROJECT_DIR"
run_review_phase() {
    local review_type="$1"
    local project_dir="$2"
    local pr_number="${STORYFORGE_PR_NUMBER:-}"

    local review_timestamp
    review_timestamp=$(date '+%Y%m%d-%H%M%S')
    local review_file="${project_dir}/working/reviews/pipeline-review-${review_timestamp}.md"
    local review_log="${project_dir}/working/logs/review-${review_timestamp}.log"

    mkdir -p "${project_dir}/working/reviews" "${project_dir}/working/logs"

    local cycle_id
    cycle_id=$(get_current_cycle)

    log "Starting review phase (${review_type})..."

    # --- Step 1: PR state change (start of review) ---
    if has_gh && [[ -n "$pr_number" ]]; then
        log "Updating PR #${pr_number}: in-progress → reviewing"
        (
            cd "$project_dir"
            gh pr edit "$pr_number" --remove-label "in-progress" --add-label "reviewing" 2>/dev/null || true
            gh pr ready "$pr_number" 2>/dev/null || true
        )
    fi

    # --- Step 2: Build and run the review prompt ---
    local diff_stat
    diff_stat=$(git -C "$project_dir" diff origin/main...HEAD --stat 2>/dev/null \
             || git -C "$project_dir" diff --stat HEAD~1 HEAD 2>/dev/null \
             || echo "(no diff available)")

    local changed_files
    changed_files=$(git -C "$project_dir" diff origin/main...HEAD --name-only 2>/dev/null \
                 || git -C "$project_dir" diff --name-only HEAD~1 HEAD 2>/dev/null \
                 || echo "(no changed files available)")

    local title
    title=$(read_yaml_field "project.title" 2>/dev/null || read_yaml_field "title" 2>/dev/null || echo "Unknown")
    local genre
    genre=$(read_yaml_field "project.genre" 2>/dev/null || read_yaml_field "genre" 2>/dev/null || echo "")

    local review_criteria=""
    case "$review_type" in
        drafting)
            review_criteria="   - Voice consistency across drafted scenes
   - Continuity with existing scenes and reference materials
   - Scene function clarity — does each scene earn its place?
   - Word count vs. targets"
            ;;
        evaluation)
            review_criteria="   - Completeness — did all evaluators produce substantive reports?
   - Coverage — are all key aspects of the manuscript addressed?
   - Synthesis quality — does the synthesis accurately reflect individual reports?
   - Actionability — are findings specific enough to act on?"
            ;;
        revision)
            review_criteria="   - Were revision targets met (word count reductions, instance counts, etc.)?
   - Was voice preserved during revision?
   - Were continuity and reference materials updated?
   - Are there new issues introduced by the revision?"
            ;;
        assembly)
            review_criteria="   - Chapter structure — do chapters have logical boundaries?
   - Scene breaks — are they consistent and appropriate?
   - Front/back matter completeness
   - Metadata accuracy (title, author, copyright)"
            ;;
        *)
            review_criteria="   - Overall quality of the changes
   - Consistency with project conventions
   - Any issues or concerns"
            ;;
    esac

    local review_prompt
    read -r -d '' review_prompt <<REVIEW_EOF || true
You are performing a pipeline review for "${title}"${genre:+ (${genre})}. This is a quality check at the end of a ${review_type} session.

## Changed Files

These files were modified in this session:

${changed_files}

## Diff Summary

${diff_stat}

## Instructions

1. Read every changed file listed above.
2. Based on the review type (${review_type}), assess:
${review_criteria}

3. Write a structured review with these sections:
   - **Summary**: 2-3 sentences on what was done
   - **Quality Signals**: What looks good
   - **Concerns**: Any issues found (with specifics — cite files and details)
   - **Recommendation**: Ready to merge, needs attention, or needs rework

4. After your main review, add one final section:

## Fixable Items

List specific items that can be fixed automatically without author input.
Include ONLY items that are:
- Concrete and unambiguous (not subjective quality judgments)
- Small enough to fix in a single pass
- Examples: unstaged files needing git add, stale YAML fields (phase, dates,
  artifact exists flags), missing or incomplete reference file updates,
  broken internal file references, scene frontmatter inconsistencies

Format each as a checkbox:
- [ ] {specific file}: {what needs to change}

If nothing is auto-fixable, write: "None — all concerns require author judgment."

5. Save the review to: ${review_file}

6. Commit and push:
   git add working/reviews/ working/logs/
   git commit -m "Review: pipeline review (${review_type})"
   git push
REVIEW_EOF

    # --- Dry-run mode: print prompt and skip ---
    if [[ "${DRY_RUN:-false}" == true ]]; then
        echo "===== DRY RUN: review (${review_type}) ====="
        echo "$review_prompt"
        echo "===== END DRY RUN: review ====="
        return 0
    fi

    local head_before
    head_before=$(git -C "$project_dir" rev-parse HEAD 2>/dev/null || echo "none")

    local review_model
    review_model=$(select_model "review")

    local interactive_file="${project_dir}/working/.interactive"
    if [[ -f "$interactive_file" ]]; then
        # Interactive review — user can discuss findings with Claude
        show_interactive_banner "Pipeline Review (${review_type})"

        log "Invoking interactive claude for review..."

        set +e
        claude "$review_prompt" \
            --model "$review_model" \
            --dangerously-skip-permissions \
            --append-system-prompt "You are in interactive mode for the pipeline review. Complete the review, then wait for the user. They may ask questions about findings or request adjustments. Type /exit when done."
        local review_exit=$?
        set -e
    else
        log "Invoking claude for review (model: ${review_model})..."
        _run_headless_session "$review_prompt" "$review_model" "$review_log"
        local review_exit=$?
    fi

    if (( review_exit != 0 )); then
        log "WARNING: Review claude invocation failed (exit code ${review_exit})"
        log "See: ${review_log}"
    fi

    # Fallback commit if Claude didn't
    local head_after
    head_after=$(git -C "$project_dir" rev-parse HEAD 2>/dev/null || echo "none")
    if [[ "$head_before" == "$head_after" && -f "$review_file" ]]; then
        (
            cd "$project_dir"
            git add working/reviews/ working/logs/ working/pipeline.yaml 2>/dev/null || true
            git commit -m "Review: pipeline review (${review_type})" 2>/dev/null || true
            git push 2>/dev/null || true
        )
    fi

    # Record review file in manifest (only after we know the file exists)
    if [[ "$cycle_id" != "0" && -f "$review_file" ]]; then
        local review_basename
        review_basename=$(basename "$review_file")
        update_cycle_field "$cycle_id" "review" "$review_basename"
    fi

    # --- Step 3: Cleanup loop + Recommend (full coaching only) ---
    local coaching
    coaching=$(get_coaching_level)

    if [[ "$coaching" == "full" && -f "$review_file" ]]; then
        # Cleanup loop: fix minor items, re-review, max 3 iterations
        local max_cleanup=3
        local cleanup_iter=0

        while (( cleanup_iter < max_cleanup )); do
            # Parse review report for fixable items
            local fixable_section
            fixable_section=$(sed -n '/^## Fixable Items/,/^## /p' "$review_file" 2>/dev/null \
                           | tail -n +2 | sed '/^## /d')

            # Exit if section is empty, says "None", or has no unchecked items
            if [[ -z "$fixable_section" ]]; then
                break
            fi
            if echo "$fixable_section" | grep -qi "^None"; then
                break
            fi
            if ! echo "$fixable_section" | grep -q '^\- \[ \]'; then
                break
            fi

            local item_count
            item_count=$(echo "$fixable_section" | grep -c '^\- \[ \]' || echo "0")
            log "Review found ${item_count} fixable item(s). Running cleanup pass $((cleanup_iter + 1))..."

            run_cleanup_pass "$review_file" "$review_type" "$project_dir" "$((cleanup_iter + 1))"

            # Re-run review to check if cleanup was successful
            log "Re-running review after cleanup..."
            review_timestamp=$(date '+%Y%m%d-%H%M%S')
            review_file="${project_dir}/working/reviews/pipeline-review-${review_timestamp}.md"
            review_log="${project_dir}/working/logs/review-${review_timestamp}.log"

            # Update the review prompt with the new file path
            review_prompt="${review_prompt/pipeline-review-*.md/pipeline-review-${review_timestamp}.md}"

            _run_headless_session "$review_prompt" "$review_model" "$review_log"

            # Fallback commit
            head_before=$(git -C "$project_dir" rev-parse HEAD 2>/dev/null || echo "none")
            if [[ -f "$review_file" ]]; then
                (
                    cd "$project_dir"
                    git add working/reviews/ working/logs/ working/pipeline.yaml 2>/dev/null || true
                    git commit -m "Review: re-review after cleanup $((cleanup_iter + 1)) (${review_type})" 2>/dev/null || true
                    git push 2>/dev/null || true
                )
            fi

            cleanup_iter=$((cleanup_iter + 1))
        done

        if (( cleanup_iter > 0 )); then
            log "Cleanup complete after ${cleanup_iter} pass(es)."
        fi

        # Recommend step (also sets cycle status to complete)
        run_recommend_step "$review_type" "$project_dir"
    else
        # In coach/strict mode, no recommend step runs — mark cycle complete here
        if [[ "$cycle_id" != "0" ]]; then
            update_cycle_field "$cycle_id" "status" "complete"
        fi
    fi

    # --- Step 4: PR state change (end of review) ---
    if has_gh && [[ -n "$pr_number" ]]; then
        # Build and post PR comment
        local pr_comment
        pr_comment=$(build_pr_comment "$review_type" "$review_file" "$project_dir")
        if [[ -n "$pr_comment" ]]; then
            log "Posting review to PR #${pr_number}..."
            (cd "$project_dir" && echo "$pr_comment" | gh pr comment "$pr_number" --body-file - 2>/dev/null) || {
                log "WARNING: Failed to post review comment"
            }
        fi

        # Swap labels: reviewing → ready-to-merge
        (
            cd "$project_dir"
            gh pr edit "$pr_number" --remove-label "reviewing" --add-label "ready-to-merge" 2>/dev/null || true
        )
        log "PR #${pr_number} marked ready-to-merge"
    fi

    # --- Step 5: Check off Review task ---
    update_pr_task "Review" "$project_dir"

    if [[ -f "$review_file" ]]; then
        log "Review saved: ${review_file}"
    else
        log "WARNING: Review file was not created"
    fi
}

# ============================================================================
# Interactive mode helpers
# ============================================================================

# Display the interactive mode banner before launching a claude session.
# Pass "multi" as the second arg to show autopilot instructions (for loops).
# Omit or pass "single" to hide autopilot instructions (for one-off steps).
#
# Usage:
#   show_interactive_banner "Scene 3 of 12" "multi"   # shows autopilot
#   show_interactive_banner "Evaluation Synthesis"      # no autopilot
show_interactive_banner() {
    local subtitle="$1"
    local mode="${2:-single}"
    local banner_width=60

    local lines=(
        "INTERACTIVE MODE - ${subtitle}"
        ""
        "You can watch, give feedback, or redirect Claude."
        "When done with this step, type /exit to continue."
    )
    if [[ "$mode" == "multi" ]]; then
        lines+=('Say "finish without me" to run the rest autonomously.')
    fi

    echo ""
    printf '╔%*s╗\n' "$banner_width" '' | tr ' ' '═'
    for line in "${lines[@]}"; do
        printf '║  %-*s  ║\n' "$((banner_width - 4))" "$line"
    done
    printf '╚%*s╝\n' "$banner_width" '' | tr ' ' '═'
    echo ""
}

# Between headless steps, offer the user a chance to go interactive.
# Pauses for STORYFORGE_REJOIN_TIMEOUT seconds (default 5) and listens for 'i'.
# If pressed, creates the interactive file and returns 0 (switched to interactive).
# Otherwise returns 1 (stay in headless/autopilot).
#
# Usage:
#   if offer_interactive "$PROJECT_DIR" "Scene 5 (5/12)"; then
#       # switched to interactive
#   fi
offer_interactive() {
    local project_dir="$1"
    local step_label="$2"
    local interactive_file="${project_dir}/working/.interactive"
    local timeout="${STORYFORGE_REJOIN_TIMEOUT:-5}"

    echo ""
    echo -n "  Next: ${step_label}. Press 'i' for interactive, or wait ${timeout}s... "
    local key=""
    read -t "$timeout" -n 1 key 2>/dev/null || true
    echo ""

    if [[ "$key" == "i" || "$key" == "I" ]]; then
        touch "$interactive_file"
        echo "  Switching to interactive mode."
        return 0
    fi

    return 1
}

# Build the system prompt appendix for interactive mode.
# Contains the rules (single-step scope, exit-to-continue behavior)
# that the user should not see but Claude must follow.
#
# Usage: system_prompt=$(build_interactive_system_prompt "$PROJECT_DIR" "scene")
build_interactive_system_prompt() {
    local project_dir="$1"
    local work_unit="${2:-step}"  # "scene", "pass", "evaluator", "step"
    local interactive_file="${project_dir}/working/.interactive"

    cat <<SYSPROMPT_EOF
You are in interactive mode, managed by a script that loops over ${work_unit}s one at a time.

RULES:
- Complete THIS ${work_unit} ONLY. Do not proceed to the next ${work_unit} — the script handles sequencing.
- When this ${work_unit} is done, tell the user it is complete and wait for them to respond.
- The user may give you feedback, ask for changes, or say they are satisfied.
- When the user is done with this ${work_unit}, they will type /exit to move on.

AUTOPILOT:
- If the user says 'autopilot the rest', 'go autonomous', 'finish without me', 'go auto', 'auto mode', or similar:
  1. Run: rm -f ${interactive_file}
  2. Tell them: 'Switching to autopilot — the remaining ${work_unit}s will run autonomously. Type /exit to continue.'
- Do NOT exit on your own. The user types /exit when ready.
SYSPROMPT_EOF
}
