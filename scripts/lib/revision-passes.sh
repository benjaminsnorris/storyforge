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

# Read guidance entries for a specific pass from the revision plan.
#
# Guidance entries are YAML list items under the `guidance:` key within a pass
# block. Each entry has `decision` and `rationale` fields.
#
# Usage:
#   guidance=$(read_pass_guidance 2 "/path/to/project")
#
# Prints formatted guidance text, or empty string if no guidance exists.
read_pass_guidance() {
    local pass_num=$1
    local project_dir="$2"
    local plan_file="${project_dir}/working/plans/revision-plan.yaml"

    # Extract the Nth pass block
    local block
    block=$(awk '
        /^passes:/ { in_passes=1; next }
        !in_passes { next }
        /^[^ ]/ && !/^[[:space:]]/ { in_passes=0; next }
        /^[[:space:]]*-[[:space:]]*name:/ { count++; if (count == target) found=1; else found=0 }
        found { print }
        found && count > target { exit }
    ' target="$pass_num" "$plan_file")

    # Check if the block contains a guidance section
    if ! echo "$block" | grep -q 'guidance:'; then
        return 0
    fi

    # Extract guidance entries (decision + rationale pairs)
    echo "$block" | awk '
        /^[[:space:]]+guidance:/ { in_guidance=1; next }
        in_guidance && /^[[:space:]]+-[[:space:]]*decision:/ {
            gsub(/^[[:space:]]+-[[:space:]]*decision:[[:space:]]*/, "")
            gsub(/^["'"'"']/, ""); gsub(/["'"'"']$/, "")
            decision = $0
        }
        in_guidance && /^[[:space:]]+rationale:/ {
            gsub(/^[[:space:]]+rationale:[[:space:]]*/, "")
            gsub(/^["'"'"']/, ""); gsub(/["'"'"']$/, "")
            if (decision != "") {
                print "- " decision
                print "  Rationale: " $0
                print ""
                decision = ""
            }
        }
        in_guidance && /^[[:space:]]*[a-z_]+:/ && !/rationale:/ && !/decision:/ { in_guidance=0 }
        in_guidance && /^[[:space:]]*-[[:space:]]*name:/ { in_guidance=0 }
    '
}

# Build a prompt for a revision pass.
#
# The resulting prompt instructs Claude to:
#   1. Read the voice guide and continuity tracker for context
#   2. Read every in-scope scene file
#   3. Follow the full pass configuration (targets, guidance, protection lists)
#   4. Apply the stated revision purpose to each scene
#   5. Preserve the established voice
#   6. Maintain and update continuity
#   7. Commit and push changes
#   8. Produce a post-pass summary
#
# Usage:
#   prompt=$(build_revision_prompt "prose-tightening" \
#       "Cut filler, tighten sentences, reduce word count ~8%" \
#       "full" "/path/to/project" "$pass_block")
#
# Prints the assembled prompt to stdout.
build_revision_prompt() {
    local pass_name="$1"
    local purpose="$2"
    local scope="$3"
    local project_dir="$4"
    local pass_config="${5:-}"

    # --- Select craft engine sections based on pass purpose ---
    local craft_section_nums=""
    local pass_key
    pass_key="$(echo "$pass_name $purpose" | tr '[:upper:]' '[:lower:]')"

    if [[ "$pass_key" =~ (prose|voice|tighten|line.edit|sentence|rhythm|word.choice) ]]; then
        craft_section_nums="3 5"  # Prose Craft + Rules
    elif [[ "$pass_key" =~ (character|arc|deepen|motivation|relationship|dialogue) ]]; then
        craft_section_nums="4 5"  # Character Craft + Rules
    elif [[ "$pass_key" =~ (structure|pacing|reorder|scene.order|act.break|tempo) ]]; then
        craft_section_nums="1 2"  # Narrative Structure + Scene Craft
    elif [[ "$pass_key" =~ (continuity|timeline|consistency|fact.check) ]]; then
        craft_section_nums=""      # No craft sections — continuity is factual
    else
        craft_section_nums="2 3 5"  # Default: Scene Craft + Prose Craft + Rules
    fi

    local craft_sections=""
    if [[ -n "$craft_section_nums" ]]; then
        craft_sections=$(extract_craft_sections $craft_section_nums 2>/dev/null) || true
    fi

    # Resolve which files are in scope
    local file_list
    file_list=$(resolve_scope "$scope" "$project_dir") || return 1

    local file_count
    file_count=$(echo "$file_list" | wc -l | tr -d ' ')

    # Build the file list as a readable block for the prompt
    local file_block=""
    while IFS= read -r fpath; do
        local rel="${fpath#${project_dir}/}"
        file_block+="- ${rel}"$'\n'
    done <<< "$file_list"

    # Build the pass configuration section if provided
    local config_section=""
    if [[ -n "$pass_config" ]]; then
        config_section="
## Pass Configuration

The full configuration for this revision pass from the author's revision plan.
Follow all targets, guidance, and protection lists precisely:

\`\`\`yaml
${pass_config}
\`\`\`

**Protection list:** Any items marked \"do not touch\" must be preserved exactly as-is. Do not edit protected passages.

**Targets:** If specific reduction percentages or instance counts are given, aim for those numbers. Track your progress."
    fi

    # Assemble the prompt
    cat <<PROMPT_EOF
# Revision Pass: ${pass_name}

## Purpose

${purpose}

## Scope

This pass covers ${file_count} scene file(s):

${file_block}${config_section}
${craft_sections:+
## Craft Principles for This Pass

The following craft principles are relevant to this revision pass. Let them guide your edits — do not reproduce them in the output, but let them inform every editorial decision.

${craft_sections}
}
## Instructions

You are performing a revision pass on a novel manuscript. Follow these rules precisely:

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

If a pass configuration was provided above, follow its targets, guidance, and protection lists precisely. These represent the author's intent — execute on them, do not second-guess them.

Work through each file methodically. Make edits directly to the scene files.

### 4. Preserve Voice

Every edit must be consistent with the voice guide. Do not flatten distinctive character voices. Do not introduce vocabulary, rhythms, or registers that violate the established style. When in doubt, preserve the original phrasing.

### 5. Maintain Continuity

If your edits change any plot-relevant detail — character knowledge, physical state, timeline position, object presence, setting detail — update the continuity tracker to reflect the change. Do not create contradictions with other scenes (including those outside this pass's scope).

### 6. Commit and Push

After completing all edits for this pass, stage and commit your changes:

\`\`\`
git add scenes/ reference/ 2>/dev/null
git commit -m "Revision: ${pass_name}"
git push
\`\`\`

This is required — the author follows progress by pulling commits as you work.

### 7. Post-Pass Summary

After completing all edits, print a structured summary:
- **Files modified:** List each file that was changed
- **Changes made:** Brief description of the kinds of edits applied
- **Target progress:** For each target in the pass configuration, report how close you came (e.g., "architecture metaphor: reduced from ~85 to ~32 instances")
- **Protected passages:** Confirm all protected passages were left untouched
- **Continuity updates:** Any changes to the continuity tracker
- **Net word count change:** Approximate words added or removed (e.g., "+1,200" or "-800")
- **Issues discovered:** Anything that may need a separate pass
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
