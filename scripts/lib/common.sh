#!/bin/bash
# common.sh — Shared functions for Storyforge scripts
#
# Source this file from your script; do not execute it directly.
# The calling script should set its own `set -euo pipefail`.

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
