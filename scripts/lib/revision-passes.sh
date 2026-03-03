#!/bin/bash
# revision-passes.sh — Functions for building and executing revision passes
#
# Source this file from your script; do not execute it directly.
# Requires: lib/common.sh must be sourced first (provides PROJECT_DIR, log,
#           read_yaml_field, check_file_exists, get_plugin_dir).

# ============================================================================
# Scope resolution
# ============================================================================

# Convert a scope specification to a list of scene file paths.
#
# Scope formats:
#   "full"                           — all scenes
#   "act-2" or "act-1"              — all scenes whose ID starts with the act prefix
#   "act1-sc03,act2-sc07,act3-sc12" — comma-separated scene IDs
#
# Usage:
#   file_list=$(resolve_scope "act-2" "/path/to/project")
#   file_list=$(resolve_scope "full" "/path/to/project")
#   file_list=$(resolve_scope "act1-sc03,act2-sc07" "/path/to/project")
#
# Prints one file path per line. Exits with error if scene-index.yaml is
# missing or a named scene file does not exist.
resolve_scope() {
    local scope="$1"
    local project_dir="$2"
    local index_file="${project_dir}/scenes/scene-index.yaml"

    if [[ ! -f "$index_file" ]]; then
        log "ERROR: scene-index.yaml not found at ${index_file}"
        return 1
    fi

    local scene_dir="${project_dir}/scenes"
    local matched_files=()

    if [[ "$scope" == "full" ]]; then
        # Every scene ID listed in the index
        local ids
        ids=$(grep -E '^\s*-\s*id:\s*' "$index_file" \
            | sed 's/^[[:space:]]*-[[:space:]]*id:[[:space:]]*//' \
            | sed 's/^["'"'"']//' | sed 's/["'"'"']$//' \
            | sed 's/[[:space:]]*$//')

        while IFS= read -r sid; do
            [[ -z "$sid" ]] && continue
            local f="${scene_dir}/${sid}.md"
            if [[ -f "$f" ]]; then
                matched_files+=("$f")
            else
                log "WARNING: Scene file missing for id '${sid}': ${f}"
            fi
        done <<< "$ids"

    elif [[ "$scope" =~ ^act-[0-9]+$ ]]; then
        # Act-level scope: "act-2" matches IDs starting with "act2-"
        local act_num="${scope#act-}"
        local prefix="act${act_num}-"

        local ids
        ids=$(grep -E '^\s*-\s*id:\s*' "$index_file" \
            | sed 's/^[[:space:]]*-[[:space:]]*id:[[:space:]]*//' \
            | sed 's/^["'"'"']//' | sed 's/["'"'"']$//' \
            | sed 's/[[:space:]]*$//')

        while IFS= read -r sid; do
            [[ -z "$sid" ]] && continue
            if [[ "$sid" == ${prefix}* ]]; then
                local f="${scene_dir}/${sid}.md"
                if [[ -f "$f" ]]; then
                    matched_files+=("$f")
                else
                    log "WARNING: Scene file missing for id '${sid}': ${f}"
                fi
            fi
        done <<< "$ids"

    else
        # Comma-separated scene IDs: "act1-sc03,act2-sc07,act3-sc12"
        IFS=',' read -ra id_list <<< "$scope"
        for sid in "${id_list[@]}"; do
            sid=$(echo "$sid" | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//')
            [[ -z "$sid" ]] && continue
            local f="${scene_dir}/${sid}.md"
            if [[ -f "$f" ]]; then
                matched_files+=("$f")
            else
                log "WARNING: Scene file missing for id '${sid}': ${f}"
            fi
        done
    fi

    if [[ ${#matched_files[@]} -eq 0 ]]; then
        log "ERROR: No scene files matched scope '${scope}'"
        return 1
    fi

    printf '%s\n' "${matched_files[@]}"
}

# ============================================================================
# Prompt construction
# ============================================================================

# Build a prompt for an autonomous revision pass.
#
# The resulting prompt instructs Claude to:
#   1. Read the voice guide and continuity tracker for context
#   2. Read every in-scope scene file
#   3. Apply the stated revision purpose to each scene
#   4. Preserve the established voice
#   5. Maintain and update continuity
#   6. NOT commit — the calling script handles git
#
# Usage:
#   prompt=$(build_revision_prompt "prose-tightening" \
#       "Cut filler, tighten sentences, reduce word count ~8%" \
#       "full" "/path/to/project")
#
# Prints the assembled prompt to stdout.
build_revision_prompt() {
    local pass_name="$1"
    local purpose="$2"
    local scope="$3"
    local project_dir="$4"

    # Resolve which files are in scope
    local file_list
    file_list=$(resolve_scope "$scope" "$project_dir") || return 1

    local file_count
    file_count=$(echo "$file_list" | wc -l | tr -d ' ')

    # Locate reference files
    local voice_guide="${project_dir}/reference/voice-guide.md"
    local continuity_tracker="${project_dir}/reference/continuity-tracker.md"
    local scene_index="${project_dir}/scenes/scene-index.yaml"

    # Build the file list as a readable block for the prompt
    local file_block=""
    while IFS= read -r fpath; do
        # Show path relative to project root for clarity
        local rel="${fpath#${project_dir}/}"
        file_block+="- ${rel}"$'\n'
    done <<< "$file_list"

    # Assemble the prompt
    cat <<PROMPT_EOF
# Revision Pass: ${pass_name}

## Purpose

${purpose}

## Scope

This pass covers ${file_count} scene file(s):

${file_block}
## Instructions

You are performing an autonomous revision pass on a novel manuscript. Follow these rules precisely:

### 1. Read Reference Context First

Before making any changes, read these reference files to understand the project's voice and continuity state:

- \`reference/voice-guide.md\` — the established voice rules, prose style, and per-character dialogue fingerprints. Every edit you make must be consistent with this guide.
- \`reference/continuity-tracker.md\` — the living ledger of continuity facts, promises, and threads. Consult this before changing any plot-relevant detail.
- \`scenes/scene-index.yaml\` — the master scene list for structural context.

### 2. Read All In-Scope Scene Files

Read every scene file listed above in full before making changes. Understand the narrative arc across these scenes before editing any individual scene.

### 3. Apply the Revision

For each in-scope scene file, apply the revision purpose stated above:

> ${purpose}

Work through each file methodically. Make edits directly to the scene files.

### 4. Preserve Voice

Every edit must be consistent with the voice guide. Do not flatten distinctive character voices. Do not introduce vocabulary, rhythms, or registers that violate the established style. When in doubt, preserve the original phrasing.

### 5. Maintain Continuity

If your edits change any plot-relevant detail — character knowledge, physical state, timeline position, object presence, setting detail — update the continuity tracker to reflect the change. Do not create contradictions with other scenes (including those outside this pass's scope).

### 6. Do Not Commit

Do NOT run any git commands. Do NOT create commits. The calling script handles all git operations after this pass completes.

### 7. Summary

After completing all edits, print a brief summary:
- How many files were modified
- What kinds of changes were made
- Any continuity updates applied
- Any issues discovered that may need a separate pass
PROMPT_EOF
}

# ============================================================================
# Change verification
# ============================================================================

# Verify that a revision pass produced changes.
#
# Checks for either uncommitted changes in the working tree or new commits
# since the recorded HEAD.
#
# Usage:
#   HEAD_BEFORE=$(git -C "$PROJECT_DIR" rev-parse HEAD)
#   # ... run revision pass ...
#   if verify_revision_changes "$HEAD_BEFORE" "$PROJECT_DIR"; then
#       echo "Changes detected"
#   fi
#
# Returns 0 if changes exist, 1 if the pass produced no changes.
verify_revision_changes() {
    local head_before="$1"
    local project_dir="$2"

    # Check for new commits
    local head_now
    head_now=$(git -C "$project_dir" rev-parse HEAD 2>/dev/null || echo "")
    if [[ -n "$head_now" && "$head_now" != "$head_before" ]]; then
        log "  New commit(s) detected since pass started."
        return 0
    fi

    # Check for uncommitted changes (staged or unstaged)
    if ! git -C "$project_dir" diff --quiet 2>/dev/null; then
        log "  Unstaged changes detected."
        return 0
    fi

    if ! git -C "$project_dir" diff --cached --quiet 2>/dev/null; then
        log "  Staged changes detected."
        return 0
    fi

    # Check for untracked files in scenes/ or reference/
    local untracked
    untracked=$(git -C "$project_dir" ls-files --others --exclude-standard \
        -- scenes/ reference/ 2>/dev/null)
    if [[ -n "$untracked" ]]; then
        log "  New untracked files detected."
        return 0
    fi

    log "  WARNING: No changes detected from revision pass."
    return 1
}
