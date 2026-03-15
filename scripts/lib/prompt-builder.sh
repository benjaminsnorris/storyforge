#!/bin/bash
# prompt-builder.sh — Generate drafting prompts from project config
#
# Source this file from your script; do not execute it directly.
# Requires common.sh to be sourced first (for read_yaml_field, log, csv.sh, etc.).

# ============================================================================
# Scene metadata extraction
# ============================================================================

# Extract metadata for a given scene ID from reference/scene-metadata.csv.
# Formats as "key: value" pairs.
#
# Usage: get_scene_metadata "scene-id" "/path/to/project"
get_scene_metadata() {
    local scene_id="$1"
    local project_dir="$2"
    local csv_file="${project_dir}/reference/scene-metadata.csv"
    # Fallback to old location
    [[ ! -f "$csv_file" ]] && csv_file="${project_dir}/scenes/metadata.csv"

    if [[ ! -f "$csv_file" ]]; then
        echo ""
        return 1
    fi

    local row
    row=$(get_csv_row "$csv_file" "$scene_id")
    if [[ -n "$row" ]]; then
        local header
        header=$(head -1 "$csv_file")
        local IFS='|'
        local -a fields=($header)
        local -a values=($row)
        local i
        for (( i=0; i<${#fields[@]}; i++ )); do
            echo "${fields[$i]}: ${values[$i]:-}"
        done
        return 0
    fi

    echo ""
    return 1
}

# ============================================================================
# Scene intent extraction
# ============================================================================

# Read intent data for a given scene from reference/scene-intent.csv.
# Returns key-value pairs, or empty if file/row doesn't exist.
#
# Usage: get_scene_intent "scene-id" "/path/to/project"
get_scene_intent() {
    local scene_id="$1"
    local project_dir="$2"
    local csv_file="${project_dir}/reference/scene-intent.csv"
    # Fallback to old location
    [[ ! -f "$csv_file" ]] && csv_file="${project_dir}/scenes/intent.csv"

    if [[ ! -f "$csv_file" ]]; then
        return 0
    fi

    local row
    row=$(get_csv_row "$csv_file" "$scene_id")
    if [[ -z "$row" ]]; then
        return 0
    fi

    local header
    header=$(head -1 "$csv_file")
    local IFS='|'
    local -a fields=($header)
    local -a values=($row)
    local i
    for (( i=0; i<${#fields[@]}; i++ )); do
        # Skip id column and empty values
        [[ "${fields[$i]}" == "id" ]] && continue
        [[ -z "${values[$i]:-}" ]] && continue
        echo "${fields[$i]}: ${values[$i]}"
    done
}

# ============================================================================
# Scene ordering
# ============================================================================

# Get the ID of the scene immediately before the given scene by seq order.
# Prints the previous scene ID, or empty string if this is the first scene.
#
# Usage: get_previous_scene "scene-id" "/path/to/project"
get_previous_scene() {
    local scene_id="$1"
    local project_dir="$2"
    local csv_file="${project_dir}/reference/scene-metadata.csv"
    [[ ! -f "$csv_file" ]] && csv_file="${project_dir}/scenes/metadata.csv"

    if [[ ! -f "$csv_file" ]]; then
        echo ""
        return 0
    fi

    # Get all IDs sorted by seq
    local prev=""
    while IFS= read -r id; do
        [[ -z "$id" ]] && continue
        if [[ "$id" == "$scene_id" ]]; then
            echo "$prev"
            return 0
        fi
        prev="$id"
    done < <(awk -F'|' '
        NR == 1 {
            for (i = 1; i <= NF; i++) {
                if ($i == "seq") seq_col = i
            }
            next
        }
        seq_col { print $1 "|" $seq_col }
    ' "$csv_file" | sort -t'|' -k2 -n | cut -d'|' -f1)

    # Scene not found
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

    find "$ref_dir" -type f -name '*.md' -o -name '*.yaml' -o -name '*.yml' -o -name '*.txt' -o -name '*.csv' \
        | sort \
        | while IFS= read -r f; do
            echo "${f#${project_dir}/}"
        done
}

# ============================================================================
# Scene status helpers
# ============================================================================

# Read a field from a scene's metadata CSV.
# Usage: read_scene_field "scene-id" "/path/to/project" "title"
read_scene_field() {
    local scene_id="$1"
    local project_dir="$2"
    local field="$3"
    local csv_file="${project_dir}/reference/scene-metadata.csv"
    [[ ! -f "$csv_file" ]] && csv_file="${project_dir}/scenes/metadata.csv"

    if [[ -f "$csv_file" ]]; then
        get_csv_field "$csv_file" "$scene_id" "$field"
        return 0
    fi

    echo ""
}

# Get the status of a scene from metadata CSV.
# Returns: "pending", "drafted", "revised", "cut", etc.
# Usage: get_scene_status "scene-id" "/path/to/project"
get_scene_status() {
    local scene_id="$1"
    local project_dir="$2"
    local csv_file="${project_dir}/reference/scene-metadata.csv"
    [[ ! -f "$csv_file" ]] && csv_file="${project_dir}/scenes/metadata.csv"

    if [[ -f "$csv_file" ]]; then
        local csv_status
        csv_status=$(get_csv_field "$csv_file" "$scene_id" "status")
        if [[ -n "$csv_status" ]]; then
            echo "$csv_status"
            return 0
        fi
    fi

    # If no CSV status, check if file exists with content — assume drafted
    local scene_file="${project_dir}/scenes/${scene_id}.md"
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
# Weighted craft directives
# ============================================================================

# Build a token-efficient weighted summary of craft principles for injection
# into drafting/revision prompts. Uses working/craft-weights.csv.
# Returns 0 with output if weights file exists, 1 otherwise.
#
# Usage: craft_text=$(build_weighted_directive "$project_dir")
build_weighted_directive() {
    local project_dir="$1"
    local weights_file="${project_dir}/working/craft-weights.csv"

    [[ -f "$weights_file" ]] || return 1

    echo "## Craft Priorities"
    echo ""

    local has_high=false
    while IFS='|' read -r section principle weight author_weight notes; do
        [[ "$section" == "section" ]] && continue
        local eff_w="$weight"
        [[ -n "$author_weight" ]] && eff_w="$author_weight"
        if (( eff_w >= 7 )); then
            if [[ "$has_high" == false ]]; then
                echo "Pay particular attention to these principles:"
                echo ""
                has_high=true
            fi
            echo "- **${principle//_/ }** (priority: ${eff_w}/10)"
        fi
    done < "$weights_file"

    if [[ "$has_high" == true ]]; then
        echo ""
    fi

    echo "Also maintain awareness of: "
    local medium_list=""
    while IFS='|' read -r section principle weight author_weight notes; do
        [[ "$section" == "section" ]] && continue
        local eff_w="$weight"
        [[ -n "$author_weight" ]] && eff_w="$author_weight"
        if (( eff_w >= 4 && eff_w < 7 )); then
            [[ -n "$medium_list" ]] && medium_list="${medium_list}, "
            medium_list="${medium_list}${principle//_/ }"
        fi
    done < "$weights_file"
    echo "$medium_list"
    echo ""
    echo "Follow all craft principles, but weight your attention toward the priorities listed above."

    return 0
}

# Get scene-specific overrides from the current evaluation cycle.
# Prints override instructions for the given scene, or nothing if no overrides.
#
# Usage: overrides=$(get_scene_overrides "scene-id" "/path/to/project")
get_scene_overrides() {
    local scene_id="$1" project_dir="$2"
    local latest="${project_dir}/working/scores/latest/overrides.csv"
    [[ -f "$latest" ]] || return 0
    awk -F'|' -v id="$scene_id" 'NR>1 && $1 == id { print "- " $3 }' "$latest"
}

# ============================================================================
# Prompt builder
# ============================================================================

# Build the complete prompt for drafting a single scene.
# Prints the prompt to stdout.
#
# Usage: build_scene_prompt "scene-id" "/path/to/project"
#
# Respects coaching level:
#   full   — drafts the scene (current behavior)
#   coach  — produces a scene brief, no prose
#   strict — produces a constraint list, no prose
build_scene_prompt() {
    local scene_id="$1"
    local project_dir="$2"
    local coaching_level
    coaching_level=$(get_coaching_level)

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
    local csv_file="${project_dir}/reference/scene-metadata.csv"
    [[ ! -f "$csv_file" ]] && csv_file="${project_dir}/scenes/metadata.csv"

    local scene_metadata
    scene_metadata=$(get_scene_metadata "$scene_id" "$project_dir")

    local scene_title target_words
    scene_title=$(get_csv_field "$csv_file" "$scene_id" "title")
    target_words=$(get_csv_field "$csv_file" "$scene_id" "target_words")
    if [[ -z "$target_words" ]]; then
        target_words=$(get_csv_field "$csv_file" "$scene_id" "word_count")
    fi

    # --- Scene intent ---
    local scene_intent=""
    scene_intent=$(get_scene_intent "$scene_id" "$project_dir")

    # --- Previous scene ---
    local prev_scene
    prev_scene=$(get_previous_scene "$scene_id" "$project_dir")

    # --- Voice guide ---
    local voice_guide
    voice_guide=$(read_yaml_field "reference.voice_guide")
    if [[ -z "$voice_guide" ]]; then
        voice_guide=$(read_yaml_field "voice_guide")
    fi
    if [[ -z "$voice_guide" ]]; then
        if [[ -f "${project_dir}/reference/voice-guide.md" ]]; then
            voice_guide="reference/voice-guide.md"
        elif [[ -f "${project_dir}/reference/persistent-prompt.md" ]]; then
            voice_guide="reference/persistent-prompt.md"
        fi
    fi

    # --- Detect API mode ---
    local api_mode=false
    [[ -n "${ANTHROPIC_API_KEY:-}" ]] && api_mode=true

    # --- Collect existing reference files ---
    local ref_files
    ref_files=$(list_reference_files "$project_dir")

    local ref_list=""
    local ref_inline=""
    while IFS= read -r rf; do
        [[ -z "$rf" ]] && continue
        ref_list="${ref_list}
- ${rf}"
        # In API mode, inline the file content
        if [[ "$api_mode" == true && -f "${project_dir}/${rf}" ]]; then
            ref_inline="${ref_inline}
=== FILE: ${rf} ===
$(cat "${project_dir}/${rf}")
=== END FILE ===
"
        fi
    done <<< "$ref_files"

    # --- Previous scene content (for API mode) ---
    local prev_scene_content=""
    if [[ "$api_mode" == true && -n "$prev_scene" && -f "${project_dir}/scenes/${prev_scene}.md" ]]; then
        prev_scene_content=$(cat "${project_dir}/scenes/${prev_scene}.md")
    fi

    # --- Craft principles ---
    local craft_sections=""
    if craft_sections=$(build_weighted_directive "$project_dir"); then
        :
    else
        craft_sections=$(extract_craft_sections 2 3 4 5 2>/dev/null) || true
    fi

    local overrides
    overrides=$(get_scene_overrides "$scene_id" "$project_dir")
    if [[ -n "$overrides" ]]; then
        craft_sections="${craft_sections}

## Scene-Specific Notes
${overrides}"
    fi

    # --- Assemble the prompt ---
    cat <<PROMPT_EOF
You are drafting scene ${scene_id}${scene_title:+ ("${scene_title}")} of "${title:-Untitled}"${genre:+, a ${genre}}. Follow these steps exactly and completely. Do not skip any step.

===== STEP 1: REFERENCE MATERIALS =====
$(if [[ "$api_mode" == true ]]; then
    echo ""
    echo "The following reference materials contain the world bible, character bible, story architecture, timeline, and all other reference material for the project. Internalize them before writing."
    echo ""
    echo "${ref_inline}"
else
    echo ""
    echo "Read every one of these files. Do not skip any:"
    echo "${ref_list}"
    echo ""
    echo "These files contain the world bible, character bible, story architecture, timeline, and all other reference material for the project. Internalize them before writing."
fi)
${voice_guide:+
Pay special attention to the voice guide — this is the voice and style guide. Follow it exactly.}
${craft_sections:+

===== CRAFT PRINCIPLES =====

The following craft principles govern how you write this scene. Internalize them — do not recite them, embody them in the prose.

${craft_sections}
}
===== STEP 2: PREVIOUS SCENE =====
$(if [[ -n "$prev_scene" ]]; then
    if [[ "$api_mode" == true && -n "$prev_scene_content" ]]; then
        echo ""
        echo "Here is the previous scene (${prev_scene}) — understand where the story left off, the emotional state, scene transitions, and narrative momentum:"
        echo ""
        echo "${prev_scene_content}"
    else
        echo ""
        echo "Read scenes/${prev_scene}.md to understand where the story left off — the emotional state, scene transitions, and narrative momentum."
    fi
else
    echo ""
    echo "This is the first scene. There is no previous scene to read. Begin the story."
fi)

===== STEP 3: SCENE METADATA =====

Here is the metadata for the scene you are drafting:

${scene_metadata}
${scene_intent:+
Scene intent:
${scene_intent}
}${target_words:+
Target word count: ${target_words} words (stay within ~500 words of this target).}

PROMPT_EOF

    # Coaching-level-specific steps
    if [[ "$coaching_level" == "coach" ]]; then
        cat <<COACH_EOF
===== PRODUCE SCENE BRIEF =====

You are in COACH mode. Do NOT write prose. Do NOT create the scene file.

Instead, produce a detailed scene brief covering:
- Voice considerations: which voice rules apply, POV-specific patterns to deploy, emotional register
- Continuity constraints: locked details that must be honored, character states entering the scene, active threads
- Emotional arc targets: where the scene starts emotionally, where it must arrive, the turn
- Craft guidance: pacing recommendations, dialogue density, sensory priorities, scene structure advice
- Specific suggestions the author can use when writing this scene themselves
$(if [[ "$api_mode" == true ]]; then
    echo ""
    echo "Output your scene brief directly as markdown."
else
    cat <<COACH_SAVE


Save to: working/coaching/brief-${scene_id}.md

Then commit:
  mkdir -p working/coaching
  git add "working/coaching/brief-${scene_id}.md"
  git commit -m "Coach: scene brief for ${scene_id}${scene_title:+: ${scene_title}}"
  git push
COACH_SAVE
fi)

===== IMPORTANT NOTES =====
- Do NOT write the scene. Your job is to prepare the author to write it.
- Be specific. "Use sensory detail" is not useful. "Ground the opening in the smell of wet stone and the sound of dripping water — Kael notices environmental details before people" is useful.
- Reference the voice guide, continuity tracker, and craft principles concretely.
COACH_EOF

    elif [[ "$coaching_level" == "strict" ]]; then
        cat <<STRICT_EOF
===== PRODUCE CONSTRAINT LIST =====

You are in STRICT mode. Do NOT write prose.

Produce a constraint list covering:
- Voice rules: which voice guide rules apply to this scene and POV character
- Continuity requirements: locked details, character states, thread obligations
- Structural obligations: what must turn in this scene, what the scene must set up for later scenes
- Metadata: target word count, scene type, emotional arc endpoints
$(if [[ "$api_mode" == true ]]; then
    echo ""
    echo "Output your constraint list directly as markdown."
else
    cat <<STRICT_SAVE


**Create the scene file** — an empty file (metadata is tracked in CSV, not frontmatter):
Save to: scenes/${scene_id}.md

**Save constraints to:** working/coaching/constraints-${scene_id}.md

Then commit:
  mkdir -p working/coaching
  git add "scenes/${scene_id}.md"
  git add "working/coaching/constraints-${scene_id}.md"
  git commit -m "Strict: constraints for ${scene_id}${scene_title:+: ${scene_title}}"
  git push
STRICT_SAVE
fi)

===== IMPORTANT NOTES =====
- Do NOT write prose. List facts and requirements only.
- Do NOT provide editorial suggestions or craft guidance.
STRICT_EOF

    else
        # full mode (default)
        if [[ "$api_mode" == true ]]; then
            cat <<FULL_API_EOF
===== DRAFT THE SCENE =====

Write the complete scene following these rules:

VOICE AND STYLE:
- Follow the voice guide exactly
- Maintain the POV character's distinct voice throughout
- Let the style rules govern every sentence — word choice, rhythm, metaphor, dialogue density

CONTINUITY:
- Do not contradict ANY locked details in the continuity tracker (provided in reference materials above)
- Respect all current character states (physical, emotional, relational)
- Advance active threads as appropriate per the scene outline
- Maintain consistency with the previous scene's ending

Write ONLY the scene prose. Do not include any YAML frontmatter or metadata.

===== OUTPUT FORMAT =====

Output the complete scene using this exact format:

=== SCENE: ${scene_id} ===
[Your complete scene prose here]
=== END SCENE: ${scene_id} ===

**CRITICAL:** Output the COMPLETE scene. Do not truncate, summarize, or use placeholders.

===== IMPORTANT NOTES =====
- Focus entirely on writing the best possible scene.
- Let the craft principles, voice guide, and continuity tracker guide every sentence.
FULL_API_EOF
        else
            cat <<FULL_CLAUDE_EOF
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

Write ONLY the scene prose. Do not include any YAML frontmatter or metadata.

===== STEP 5: QUALITY REVIEW =====

Launch an Agent to review the draft. The agent should:
1. Read scenes/${scene_id}.md
2. Read the continuity tracker (reference/continuity-tracker.md if it exists)
3. Read the scene metadata from reference/scene-metadata.csv
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
FULL_CLAUDE_EOF
        fi
    fi
}
