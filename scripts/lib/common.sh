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

    git -C "$project_dir" checkout -b "$STORYFORGE_BRANCH" 2>/dev/null
    if [[ $? -ne 0 ]]; then
        log "ERROR: Failed to create branch ${STORYFORGE_BRANCH}"
        return 1
    fi

    log "Created branch: ${STORYFORGE_BRANCH}"
    return 0
}

# Push the current branch with -u to set up upstream tracking.
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

# Run the review phase at the end of an autonomous process.
#
# Sequence:
#   1. PR state change (start): remove in-progress, add reviewing, convert draft to ready
#   2. Run Claude review: assess changed files, save review to working/reviews/
#   3. Commit and push the review file
#   4. PR state change (end): post review as comment, remove reviewing, add ready-to-merge
#   5. Check off the "Review" task in the PR body
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

4. Save the review to: ${review_file}

5. Commit and push:
   git add working/reviews/
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

    if [[ "${INTERACTIVE:-false}" == true ]]; then
        # Interactive review — user can discuss findings with Claude
        show_interactive_banner "Pipeline Review (${review_type})"

        log "Invoking interactive claude for review..."

        set +e
        claude "$review_prompt" \
            --model claude-opus-4-6 \
            --dangerously-skip-permissions \
            --append-system-prompt "You are in interactive mode for the pipeline review. Complete the review, then wait for the user. They may ask questions about findings or request adjustments. Type /exit when done."
        local review_exit=$?
        set -e
    else
        log "Invoking claude for review..."

        set +e
        claude -p "$review_prompt" \
            --model claude-opus-4-6 \
            --dangerously-skip-permissions \
            --output-format stream-json \
            --verbose \
            > "$review_log" 2>&1
        local review_exit=$?
        set -e
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
            git add working/reviews/ 2>/dev/null || true
            git commit -m "Review: pipeline review (${review_type})" 2>/dev/null || true
            git push 2>/dev/null || true
        )
    fi

    # --- Step 4: PR state change (end of review) ---
    if has_gh && [[ -n "$pr_number" ]]; then
        # Post review as PR comment
        if [[ -f "$review_file" ]]; then
            log "Posting review to PR #${pr_number}..."
            (cd "$project_dir" && gh pr comment "$pr_number" --body-file "$review_file" 2>/dev/null) || {
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
#
# Usage: show_interactive_banner "Scene 3 of 12"
show_interactive_banner() {
    local subtitle="$1"
    local banner_width=60

    local lines=(
        "INTERACTIVE MODE - ${subtitle}"
        ""
        "You can watch, give feedback, or redirect Claude."
        "When done with this step, type /exit to continue."
        'Say "finish without me" to run the rest autonomously.'
    )

    echo ""
    printf '╔%*s╗\n' "$banner_width" '' | tr ' ' '═'
    for line in "${lines[@]}"; do
        printf '║  %-*s  ║\n' "$((banner_width - 4))" "$line"
    done
    printf '╚%*s╝\n' "$banner_width" '' | tr ' ' '═'
    echo ""
}

# Check if the user wants to rejoin interactive mode between autopilot steps.
# Pauses for STORYFORGE_REJOIN_TIMEOUT seconds (default 5) and listens for 'i'.
# If pressed, removes the autopilot file and returns 0 (switched to interactive).
# Otherwise returns 1 (stay in autopilot).
#
# Usage:
#   if check_rejoin_interactive "$PROJECT_DIR" "Scene 5 (5/12)"; then
#       # switched to interactive
#   fi
check_rejoin_interactive() {
    local project_dir="$1"
    local step_label="$2"
    local autopilot_file="${project_dir}/working/.autopilot"
    local timeout="${STORYFORGE_REJOIN_TIMEOUT:-5}"

    if [[ ! -f "$autopilot_file" ]]; then
        return 1
    fi

    echo ""
    echo -n "[AUTOPILOT] Next: ${step_label}. Press 'i' for interactive, or wait ${timeout}s... "
    local key=""
    read -t "$timeout" -n 1 key 2>/dev/null || true
    echo ""

    if [[ "$key" == "i" || "$key" == "I" ]]; then
        rm -f "$autopilot_file"
        echo "[AUTOPILOT] Switching to interactive mode."
        return 0
    fi

    return 1
}

# Build the system prompt appendix for interactive mode.
# Contains the rules (single-step scope, autopilot trigger phrases)
# that the user should not see but Claude must follow.
#
# Usage: system_prompt=$(build_interactive_system_prompt "$AUTOPILOT_FILE" "scene")
build_interactive_system_prompt() {
    local autopilot_file="$1"
    local work_unit="${2:-step}"  # "scene", "pass", "evaluator", "step"

    cat <<SYSPROMPT_EOF
You are in interactive mode, managed by a script that loops over ${work_unit}s one at a time.

RULES:
- Complete THIS ${work_unit} ONLY. Do not proceed to the next ${work_unit} — the script handles sequencing.
- When this ${work_unit} is done, tell the user it is complete and wait for them to respond.
- The user may give you feedback, ask for changes, or say they are satisfied.
- When the user is done with this ${work_unit}, they will type /exit to move on.

AUTOPILOT:
- If the user says 'autopilot the rest', 'go autonomous', 'finish without me', 'go auto', 'auto mode', or similar:
  1. Run: touch ${autopilot_file}
  2. Tell them: 'Autopilot enabled — the remaining ${work_unit}s will run autonomously. Type /exit to continue.'
- Do NOT exit on your own. The user types /exit when ready.
SYSPROMPT_EOF
}
