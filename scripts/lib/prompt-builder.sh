#!/bin/bash
# prompt-builder.sh — Generate drafting prompts from project config
#
# Source this file from your script; do not execute it directly.
# Requires common.sh to be sourced first (for read_yaml_field, log, etc.).

# ============================================================================
# Scene metadata extraction
# ============================================================================

# Extract the YAML block for a given scene ID from scene-index.yaml.
# Prints the raw YAML lines (indented block under the scene entry).
#
# Usage: get_scene_metadata "act1-sc05" "/path/to/project"
get_scene_metadata() {
    local scene_id="$1"
    local project_dir="$2"
    local index_file="${project_dir}/scene-index.yaml"

    if [[ ! -f "$index_file" ]]; then
        echo ""
        return 1
    fi

    # Find the line with this scene ID and extract its block.
    # Scene entries look like:
    #   - id: act1-sc05
    #     title: "The Descent"
    #     ...
    # We grab from the matching "- id:" line until the next "- id:" or EOF.
    sed -n "/^[[:space:]]*- id:[[:space:]]*${scene_id}[[:space:]]*$/,/^[[:space:]]*- id:/p" "$index_file" \
        | sed '${ /^[[:space:]]*- id:/d }'
}

# ============================================================================
# Scene ordering
# ============================================================================

# Get the ID of the scene immediately before the given scene in scene-index.yaml.
# Prints the previous scene ID, or empty string if this is the first scene.
#
# Usage: get_previous_scene "act1-sc05" "/path/to/project"
get_previous_scene() {
    local scene_id="$1"
    local project_dir="$2"
    local index_file="${project_dir}/scene-index.yaml"

    if [[ ! -f "$index_file" ]]; then
        echo ""
        return 0
    fi

    # Extract all scene IDs in order
    local ids
    ids=$(grep -E '^[[:space:]]*- id:[[:space:]]*' "$index_file" \
        | sed 's/^[[:space:]]*- id:[[:space:]]*//' \
        | sed 's/[[:space:]]*$//')

    local prev=""
    while IFS= read -r id; do
        if [[ "$id" == "$scene_id" ]]; then
            echo "$prev"
            return 0
        fi
        prev="$id"
    done <<< "$ids"

    # Scene not found in index
    echo ""
    return 0
}

# ============================================================================
# Reference file discovery
# ============================================================================

# List all existing reference files in the project's reference/ directory.
# Returns one path per line (relative to project root).
#
# Usage: list_reference_files "/path/to/project"
list_reference_files() {
    local project_dir="$1"
    local ref_dir="${project_dir}/reference"

    if [[ ! -d "$ref_dir" ]]; then
        return 0
    fi

    # Find all files in reference/, sorted for deterministic ordering.
    # Return paths relative to project root for use in prompts.
    find "$ref_dir" -type f -name '*.md' -o -name '*.yaml' -o -name '*.yml' -o -name '*.txt' \
        | sort \
        | while IFS= read -r f; do
            echo "${f#${project_dir}/}"
        done
}

# ============================================================================
# Scene status helpers
# ============================================================================

# Read a field from a scene's YAML metadata block.
# Usage: read_scene_field "act1-sc05" "/path/to/project" "title"
read_scene_field() {
    local scene_id="$1"
    local project_dir="$2"
    local field="$3"

    get_scene_metadata "$scene_id" "$project_dir" \
        | grep -E "^[[:space:]]+${field}:" \
        | head -1 \
        | sed 's/^[[:space:]]*'"${field}"':[[:space:]]*//' \
        | sed 's/^["'"'"']//' \
        | sed 's/["'"'"']$//' \
        | sed 's/[[:space:]]*$//'
}

# Get the status of a scene (from scene-index.yaml or scene file frontmatter).
# Returns: "pending", "drafted", "revised", or "outlined"
# Usage: get_scene_status "act1-sc05" "/path/to/project"
get_scene_status() {
    local scene_id="$1"
    local project_dir="$2"

    # First check if the scene file exists and has frontmatter status
    local scene_file="${project_dir}/scenes/${scene_id}.md"
    if [[ -f "$scene_file" ]]; then
        local file_status
        file_status=$(sed -n '/^---$/,/^---$/p' "$scene_file" \
            | grep -E '^status:' \
            | head -1 \
            | sed 's/^status:[[:space:]]*//' \
            | sed 's/[[:space:]]*$//')
        if [[ -n "$file_status" ]]; then
            echo "$file_status"
            return 0
        fi
    fi

    # Fall back to scene-index.yaml status
    local index_status
    index_status=$(read_scene_field "$scene_id" "$project_dir" "status")
    if [[ -n "$index_status" ]]; then
        echo "$index_status"
        return 0
    fi

    # No status found — if file exists with content, assume drafted
    if [[ -f "$scene_file" ]]; then
        local wc
        wc=$(wc -w < "$scene_file" 2>/dev/null | tr -d ' ')
        if (( wc > 100 )); then
            echo "drafted"
            return 0
        fi
    fi

    echo "pending"
}

# ============================================================================
# Prompt builder
# ============================================================================

# Build the complete prompt for drafting a single scene.
# Prints the prompt to stdout.
#
# Usage: build_scene_prompt "act1-sc05" "/path/to/project"
build_scene_prompt() {
    local scene_id="$1"
    local project_dir="$2"

    # --- Read project config ---
    local title
    title=$(read_yaml_field "project.title")
    if [[ -z "$title" ]]; then
        title=$(read_yaml_field "title")
    fi

    local genre
    genre=$(read_yaml_field "project.genre")
    if [[ -z "$genre" ]]; then
        genre=$(read_yaml_field "genre")
    fi

    # --- Scene metadata ---
    local scene_metadata
    scene_metadata=$(get_scene_metadata "$scene_id" "$project_dir")

    local scene_title
    scene_title=$(read_scene_field "$scene_id" "$project_dir" "title")

    local target_words
    target_words=$(read_scene_field "$scene_id" "$project_dir" "target_words")
    if [[ -z "$target_words" ]]; then
        target_words=$(read_scene_field "$scene_id" "$project_dir" "word_count")
    fi

    # --- Previous scene ---
    local prev_scene
    prev_scene=$(get_previous_scene "$scene_id" "$project_dir")

    # --- Voice guide ---
    local voice_guide
    voice_guide=$(read_yaml_field "reference.voice_guide")
    if [[ -z "$voice_guide" ]]; then
        voice_guide=$(read_yaml_field "voice_guide")
    fi
    # Default path if not specified in config
    if [[ -z "$voice_guide" ]]; then
        if [[ -f "${project_dir}/reference/voice-guide.md" ]]; then
            voice_guide="reference/voice-guide.md"
        elif [[ -f "${project_dir}/reference/persistent-prompt.md" ]]; then
            voice_guide="reference/persistent-prompt.md"
        fi
    fi

    # --- Collect existing reference files ---
    local ref_files
    ref_files=$(list_reference_files "$project_dir")

    # --- Build the reference file list for the prompt ---
    local ref_list=""
    while IFS= read -r rf; do
        [[ -z "$rf" ]] && continue
        ref_list="${ref_list}
- ${rf}"
    done <<< "$ref_files"

    # --- Extract relevant craft engine sections ---
    # Scene Craft (2) + Prose Craft (3) + Character Craft (4) + Rules (5)
    local craft_sections=""
    craft_sections=$(extract_craft_sections 2 3 4 5 2>/dev/null) || true

    # --- Assemble the prompt ---
    cat <<PROMPT_EOF
You are drafting scene ${scene_id}${scene_title:+ ("${scene_title}")} of "${title:-Untitled}"${genre:+, a ${genre}}. Follow these steps exactly and completely. Do not skip any step.

===== STEP 1: READ ALL REFERENCE MATERIALS =====

Read every one of these files. Do not skip any:
${ref_list}

These files contain the world bible, character bible, story architecture, timeline, and all other reference material for the project. Internalize them before writing.
${voice_guide:+
Pay special attention to ${voice_guide} — this is the voice and style guide. Follow it exactly.}
${craft_sections:+

===== CRAFT PRINCIPLES =====

The following craft principles govern how you write this scene. Internalize them — do not recite them, embody them in the prose.

${craft_sections}
}
===== STEP 2: READ THE PREVIOUS SCENE =====
$(if [[ -n "$prev_scene" ]]; then
    echo ""
    echo "Read scenes/${prev_scene}.md to understand where the story left off — the emotional state, scene transitions, and narrative momentum."
else
    echo ""
    echo "This is the first scene. There is no previous scene to read. Begin the story."
fi)

===== STEP 3: SCENE METADATA =====

Here is the metadata for the scene you are drafting:

${scene_metadata}
${target_words:+
Target word count: ${target_words} words (stay within ~500 words of this target).}

===== STEP 4: DRAFT THE SCENE =====

Write the complete scene following these rules:

VOICE AND STYLE:
- Follow the voice guide${voice_guide:+ (${voice_guide})} exactly
- Maintain the POV character's distinct voice throughout
- Let the style rules govern every sentence — word choice, rhythm, metaphor, dialogue density

CONTINUITY:
- Do not contradict ANY locked details in the continuity tracker
- Respect all current character states (physical, emotional, relational)
- Advance active threads as appropriate per the scene outline
- Maintain consistency with the previous scene's ending

Save the scene to: scenes/${scene_id}.md

The file should begin with YAML frontmatter:
---
id: ${scene_id}
title: "${scene_title:-}"
status: drafted
word_count: <actual count>
drafted_at: "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
---

Then the scene content.

===== STEP 5: QUALITY REVIEW =====

Launch an Agent to review the draft. The agent should:
1. Read scenes/${scene_id}.md
2. Read the continuity tracker (reference/continuity-tracker.md if it exists)
3. Read the scene-index.yaml entry for this scene
4. Check for:
   - Contradictions with locked details
   - Active threads that should advance but don't (or advance incorrectly)
   - POV voice consistency
   - Word count vs. target
   - Continuity breaks with the previous scene (character locations, emotional states, time progression)
5. Report any issues found

===== STEP 6: REVISE IF NEEDED =====

If the quality review found significant continuity errors, contradicted locked details, or voice breaks, fix them in the scene file now. Minor style notes can be logged but do not require immediate fixes.

===== STEP 7: UPDATE CONTINUITY =====

If a continuity tracker exists (reference/continuity-tracker.md), update it:
- Add a summary for this scene (2-3 sentences)
- Update character states to reflect this scene's events
- Add any new locked details established in this scene
- Update active threads: advance existing ones, add new ones opened, move fully resolved ones to a resolved section
- Update any motif tracking

===== STEP 8: GIT COMMIT =====

Stage and commit using the Bash tool:

  git add "scenes/${scene_id}.md"
  git add reference/ 2>/dev/null || true
  git commit -m "Draft scene ${scene_id}${scene_title:+: ${scene_title}}"
  git push

===== IMPORTANT NOTES =====
- Complete ALL eight steps. The next scene's drafting depends on accurate continuity state.
- If you encounter an issue with the draft, fix it before updating continuity files.
- The continuity updates are as important as the scene itself — future scenes rely on them.
PROMPT_EOF
}
