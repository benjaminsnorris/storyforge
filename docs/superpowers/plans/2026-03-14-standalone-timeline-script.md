# Standalone Timeline Script Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract timeline analysis from `storyforge-enrich` into a standalone `storyforge-timeline` script with two-phase Haiku→Sonnet architecture, interactive/autonomous mode, progress feedback, and proper signal handling.

**Architecture:** Phase 1 sends each scene's prose to Haiku in parallel to extract temporal indicators. Phase 2 sends the compact indicator list to Sonnet in a single pass to assign `timeline_day` values. Interactive mode adds review checkpoints after each phase. An `--embedded` flag lets enrich call it as a subprocess without branch/PR overhead.

**Tech Stack:** Bash (set -eo pipefail, BSD sed compat), Claude CLI, pipe-delimited CSV, common.sh shared libraries.

**Spec:** `docs/superpowers/specs/2026-03-13-standalone-timeline-script-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `scripts/storyforge-timeline` | Create | Standalone timeline script (two-phase Haiku→Sonnet) |
| `scripts/lib/common.sh` | Modify | Add `"extraction"` task type to `select_model` |
| `scripts/storyforge-enrich` | Modify | Remove `run_timeline_pass()`, replace with subprocess call, add `--skip-timeline` |
| `tests/test-timeline.sh` | Create | Tests for timeline argument parsing, indicator parsing, CSV updates |
| `.claude-plugin/plugin.json` | Modify | Bump version to 0.22.2 |

---

## Chunk 1: Foundation — select_model + script skeleton

### Task 1: Add extraction task type to select_model

**Files:**
- Modify: `scripts/lib/common.sh:753-761` (select_model case statement)
- Test: `tests/test-common.sh` (existing)

- [ ] **Step 1: Write the failing test**

Add to `tests/test-common.sh`:

```bash
# select_model: extraction returns haiku
RESULT=$(select_model "extraction")
assert_equals "claude-haiku-4-5-20251001" "$RESULT" "select_model: extraction returns haiku"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-common.sh`
Expected: FAIL on "select_model: extraction returns haiku"

- [ ] **Step 3: Add extraction case to select_model**

In `scripts/lib/common.sh`, in the `select_model()` case statement (between the `review` and `*` cases), add:

```bash
        extraction)  echo "claude-haiku-4-5-20251001" ;;
```

Also update the comment block above the function to document it:

```
#   extraction   — lightweight signal extraction (low cost, high speed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-common.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/common.sh tests/test-common.sh
git commit -m "Add extraction task type to select_model (Haiku)"
git push
```

### Task 2: Create script skeleton with argument parsing

**Files:**
- Create: `scripts/storyforge-timeline`

- [ ] **Step 1: Write the script skeleton**

Create `scripts/storyforge-timeline` with:

```bash
#!/bin/bash
set -eo pipefail

# ============================================================================
# storyforge-timeline — Timeline day assignment for Storyforge projects
#
# Two-phase architecture:
#   Phase 1 (Haiku): Extract temporal indicators from each scene in parallel
#   Phase 2 (Sonnet): Assign timeline_day values via multi-scene analysis
#
# Usage:
#   ./storyforge-timeline                     # All scenes, autonomous
#   ./storyforge-timeline --interactive       # Interactive with review checkpoints
#   ./storyforge-timeline --act 2             # Scenes in act 2 only
#   ./storyforge-timeline --embedded          # Called from enrich (no branch/PR)
#   ./storyforge-timeline --dry-run           # Show plan without invoking Claude
# ============================================================================

# --- Locate script directory and source libraries ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/lib"

if [[ ! -f "${LIB_DIR}/common.sh" ]]; then
    echo "ERROR: Cannot find lib/common.sh at ${LIB_DIR}" >&2
    exit 1
fi

# shellcheck source=lib/common.sh
source "${LIB_DIR}/common.sh"

# --- Default options ---
DRY_RUN=false
FORCE=false
INTERACTIVE=false
EMBEDDED=false
SKIP_PHASE1=false
FILTER_MODE="all"
FILTER_SCENES=""
FILTER_ACT=""
FILTER_FROM_SEQ=""
PARALLEL=${STORYFORGE_TIMELINE_PARALLEL:-6}

usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Assign timeline_day values to scenes via two-phase Claude analysis.
Phase 1 (Haiku): Extract temporal indicators from scene prose.
Phase 2 (Sonnet): Assign timeline_day via multi-scene analysis.

Scene selection:
  --scenes ID,ID,...  Specific scenes only (comma-separated)
  --act N             Scenes in part N
  --from-seq N        From sequence N onward
  --from-seq N-M      Sequence range N through M

Options:
  --interactive, -i   Interactive mode with review checkpoints
  --parallel N        Haiku extraction workers (default: 6, env: STORYFORGE_TIMELINE_PARALLEL)
  --force             Overwrite existing timeline_day values
  --dry-run           Show what would happen without invoking Claude
  --skip-phase1       Skip Haiku extraction; reuse cached indicators or fall back to raw metadata
  --embedded          Called as subprocess (skip branch/PR/commit)
  -h, --help          Show this help

Environment:
  STORYFORGE_MODEL              Override model for all invocations
  STORYFORGE_TIMELINE_PARALLEL  Override parallel workers (default: 6)
  STORYFORGE_REJOIN_TIMEOUT     Seconds to wait for 'i' keypress (default: 5)

Examples:
  $(basename "$0")                          # All scenes, autonomous
  $(basename "$0") --interactive            # Interactive with review gates
  $(basename "$0") --act 2                  # Act 2 only
  $(basename "$0") --from-seq 10-20         # Scenes 10 through 20
  $(basename "$0") --embedded --force       # Called from enrich
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --interactive|-i)
            INTERACTIVE=true
            shift
            ;;
        --embedded)
            EMBEDDED=true
            shift
            ;;
        --skip-phase1)
            SKIP_PHASE1=true
            shift
            ;;
        --scenes)
            FILTER_MODE="scenes"
            FILTER_SCENES="${2:?ERROR: --scenes requires comma-separated scene IDs}"
            shift 2
            ;;
        --act)
            FILTER_MODE="act"
            FILTER_ACT="${2:?ERROR: --act requires an act number}"
            shift 2
            ;;
        --from-seq)
            FILTER_MODE="from_seq"
            FILTER_FROM_SEQ="${2:?ERROR: --from-seq requires a sequence number or range}"
            shift 2
            ;;
        --parallel)
            PARALLEL="${2:?ERROR: --parallel requires a number}"
            shift 2
            ;;
        -*)
            echo "ERROR: Unknown option: $1" >&2
            usage
            ;;
        *)
            echo "ERROR: Unexpected argument: $1" >&2
            usage
            ;;
    esac
done

# ============================================================================
# Project setup
# ============================================================================

detect_project_root
PROJECT_TITLE=$(read_yaml_field "project.title" 2>/dev/null || read_yaml_field "title" 2>/dev/null || echo "Unknown")

# --- Resolve paths ---
METADATA_CSV="${PROJECT_DIR}/reference/scene-metadata.csv"
INTENT_CSV="${PROJECT_DIR}/reference/scene-intent.csv"
SCENES_DIR="${PROJECT_DIR}/scenes"
LOG_DIR="${PROJECT_DIR}/working/logs"
TIMELINE_DIR="${PROJECT_DIR}/working/timeline"

mkdir -p "$LOG_DIR" "$TIMELINE_DIR"

if [[ ! -f "$METADATA_CSV" ]]; then
    log "ERROR: reference/scene-metadata.csv not found."
    exit 1
fi

# --- Interactive mode file ---
INTERACTIVE_FILE="${PROJECT_DIR}/working/.interactive"
if [[ "$EMBEDDED" != true ]]; then
    rm -f "$INTERACTIVE_FILE"
    if [[ "$INTERACTIVE" == true ]]; then
        touch "$INTERACTIVE_FILE"
    fi
fi

# --- Build scene list ---
build_scene_list "$METADATA_CSV"

case "$FILTER_MODE" in
    all)       apply_scene_filter "$METADATA_CSV" "all" ;;
    scenes)    apply_scene_filter "$METADATA_CSV" "scenes" "$FILTER_SCENES" ;;
    act)       apply_scene_filter "$METADATA_CSV" "act" "$FILTER_ACT" ;;
    from_seq)  apply_scene_filter "$METADATA_CSV" "from_seq" "$FILTER_FROM_SEQ" ;;
esac

SCENE_IDS=("${FILTERED_IDS[@]}")
SCENE_COUNT=${#SCENE_IDS[@]}

if (( SCENE_COUNT == 0 )); then
    log "No scenes match the filter. Nothing to do."
    exit 0
fi

# --- Model selection ---
HAIKU_MODEL=$(select_model "extraction")
SONNET_MODEL=$(select_model "evaluation")

log "============================================"
log "Storyforge Timeline"
log "============================================"
log "Project: ${PROJECT_TITLE}"
log "Scenes: ${SCENE_COUNT}"
log "Phase 1 model: ${HAIKU_MODEL}"
log "Phase 2 model: ${SONNET_MODEL}"
log "Mode: $(if [[ -f "$INTERACTIVE_FILE" ]]; then echo "interactive"; else echo "autonomous"; fi)"
if [[ "$EMBEDDED" == true ]]; then log "Running embedded (no branch/PR)"; fi
log "============================================"

# ============================================================================
# Dry-run mode
# ============================================================================

if [[ "$DRY_RUN" == true ]]; then
    log ""
    log "DRY RUN — would analyze these scenes:"
    for id in "${SCENE_IDS[@]}"; do
        title=$(get_csv_field "$METADATA_CSV" "$id" "title")
        seq_val=$(get_csv_field "$METADATA_CSV" "$id" "seq")
        existing=$(get_csv_field "$METADATA_CSV" "$id" "timeline_day")
        log "  SEQ ${seq_val}: ${id} — ${title:-untitled} (current day: ${existing:-unset})"
    done
    log ""
    log "Phase 1: ${SCENE_COUNT} Haiku calls (parallel, ${PARALLEL} workers)"
    log "Phase 2: 1 Sonnet call (all scenes)"
    exit 0
fi

# ============================================================================
# Cost forecast
# ============================================================================

TOTAL_WORDS=0
for id in "${SCENE_IDS[@]}"; do
    sf="${SCENES_DIR}/${id}.md"
    if [[ -f "$sf" ]]; then
        wc_val=$(wc -w < "$sf" | tr -d ' ')
        TOTAL_WORDS=$((TOTAL_WORDS + wc_val))
    fi
done

# Phase 1: Haiku reads full prose per scene
PHASE1_COST=$(estimate_cost "extraction" "$SCENE_COUNT" "$(( TOTAL_WORDS / (SCENE_COUNT > 0 ? SCENE_COUNT : 1) ))" "$HAIKU_MODEL")
# Phase 2: Sonnet reads compact indicators (~50 words per scene)
PHASE2_COST=$(estimate_cost "evaluation" "1" "$(( SCENE_COUNT * 50 ))" "$SONNET_MODEL")

log "Cost forecast: Phase 1 ~\$${PHASE1_COST}, Phase 2 ~\$${PHASE2_COST}"
check_cost_threshold "$PHASE1_COST" || { log "Cost threshold exceeded. Aborting."; exit 1; }

# ============================================================================
# Branch & PR (standalone mode only)
# ============================================================================

if [[ "$EMBEDDED" != true ]]; then
    create_branch "timeline" "$PROJECT_DIR"
    ensure_branch_pushed "$PROJECT_DIR"

    PR_BODY="## Timeline Assignment

**Project:** ${PROJECT_TITLE}
**Scenes:** ${SCENE_COUNT}

### Tasks
- [ ] Phase 1: Extract temporal indicators (Haiku)
- [ ] Phase 2: Assign timeline_day values (Sonnet)
"
    create_draft_pr "Enrich: timeline for ${PROJECT_TITLE}" "$PR_BODY" "$PROJECT_DIR" "enrichment"
fi

# ============================================================================
# Phase 1: Haiku temporal indicator extraction (parallel)
# ============================================================================

run_phase1() {
    log ""
    log "Phase 1: Extracting temporal indicators (${SCENE_COUNT} scenes, ${PARALLEL} workers)"
    log "--------------------------------------------"

    local batch_start=0
    local completed=0

    while (( batch_start < SCENE_COUNT )); do
        batch_pids=()
        batch_ids=()
        batch_end=$(( batch_start + PARALLEL ))
        (( batch_end > SCENE_COUNT )) && batch_end=$SCENE_COUNT

        for (( i=batch_start; i<batch_end; i++ )); do
            id="${SCENE_IDS[$i]}"
            batch_ids+=("$id")
            (
                scene_file="${SCENES_DIR}/${id}.md"
                indicator_file="${TIMELINE_DIR}/.indicators-${id}"
                log_file="${LOG_DIR}/timeline-phase1-${id}.log"

                # Read scene prose
                prose=""
                if [[ -f "$scene_file" ]]; then
                    prose=$(cat "$scene_file")
                fi

                if [[ -z "$prose" ]]; then
                    echo "(no prose)" > "$indicator_file"
                    echo "ok" > "${TIMELINE_DIR}/.status-${id}"
                    exit 0
                fi

                # Build Haiku prompt
                prompt="You are extracting temporal indicators from a scene in a novel. Read the prose below and list ONLY time-related signals. Do not interpret, analyze, or assign day numbers.

Extract these types of indicators:
- Explicit time references: \"the next morning\", \"three days later\", \"Tuesday\"
- Temporal transitions: \"later that evening\", \"by nightfall\"
- Sleep/wake cycles: \"she woke\", \"he went to bed\"
- Meal references: \"over breakfast\", \"dinner was cold\"
- Continuity cues: \"still wearing yesterday's clothes\", \"the wound had healed\"

Output format — one line of comma-separated indicators, or \"(none)\" if no temporal signals found:
INDICATORS: \"the next morning\", wakes up, breakfast

## Scene Prose
${prose}"

                _SF_INVOCATION_START=$(date +%s)
                export _SF_INVOCATION_START

                claude -p "$prompt" \
                    --model "$HAIKU_MODEL" \
                    --dangerously-skip-permissions \
                    --output-format stream-json \
                    --verbose \
                    > "$log_file" 2>&1 || true

                response=$(extract_claude_response "$log_file" 2>/dev/null || true)
                log_usage "$log_file" "timeline-phase1" "$id" "$HAIKU_MODEL"

                # Parse INDICATORS: line
                indicators=""
                if [[ -n "$response" ]]; then
                    indicators=$(echo "$response" | grep -i "^INDICATORS:" | sed 's/^INDICATORS:[[:space:]]*//' | head -1 || true)
                fi
                [[ -z "$indicators" ]] && indicators="(none)"

                echo "$indicators" > "$indicator_file"
                echo "ok" > "${TIMELINE_DIR}/.status-${id}"
            ) &
            batch_pids+=($!)
            register_child_pid $!
        done

        # Wait for batch
        for pid in "${batch_pids[@]}"; do
            wait "$pid" 2>/dev/null || true
            unregister_child_pid "$pid" 2>/dev/null || true
        done

        # Report progress for this batch
        for id in "${batch_ids[@]}"; do
            completed=$((completed + 1))
            indicator_file="${TIMELINE_DIR}/.indicators-${id}"
            if [[ -f "$indicator_file" ]]; then
                indicators=$(cat "$indicator_file")
                log "  [${completed}/${SCENE_COUNT}] ${id}: ${indicators}"
            else
                log "  [${completed}/${SCENE_COUNT}] ${id}: (extraction failed)"
            fi
        done

        batch_start=$batch_end
    done

    log "Phase 1 complete: ${completed} scenes processed"
}

# ============================================================================
# Phase 2: Sonnet timeline_day assignment (single pass)
# ============================================================================

run_phase2() {
    log ""
    log "Phase 2: Assigning timeline_day values (single Sonnet pass)"
    log "--------------------------------------------"

    # Build the scene summary from Phase 1 indicators + metadata
    local scene_summaries=""
    for id in "${SCENE_IDS[@]}"; do
        title=$(get_csv_field "$METADATA_CSV" "$id" "title")
        seq_val=$(get_csv_field "$METADATA_CSV" "$id" "seq")
        tod=$(get_csv_field "$METADATA_CSV" "$id" "time_of_day")
        existing_day=$(get_csv_field "$METADATA_CSV" "$id" "timeline_day")

        # Get indicators from Phase 1 (or fallback)
        indicator_file="${TIMELINE_DIR}/.indicators-${id}"
        if [[ -f "$indicator_file" ]]; then
            indicators=$(cat "$indicator_file")
        else
            # Fallback: raw metadata only
            indicators="(no extraction available)"
        fi

        scene_summaries="${scene_summaries}
SEQ ${seq_val}: ${title} (${id})
  Time of day: ${tod:-unknown}
  Existing timeline_day: ${existing_day:-unset}
  Temporal indicators: ${indicators}
"
    done

    # Build Sonnet prompt
    local timeline_prompt="You are assigning timeline_day values to scenes in a novel. Each scene happens on a specific day in the story's internal chronology. Day 1 is the first day of the story.

Read the scenes below IN ORDER (they are sorted by narrative sequence). Use the temporal indicators extracted from the prose, time-of-day cues, and narrative logic to determine which day each scene falls on. Scenes can share a day. Days can be skipped (e.g., day 1, day 1, day 3 if two days pass between scenes).

If a scene already has a timeline_day value, keep it unless your analysis strongly suggests it's wrong.

## Scenes (in narrative order)
${scene_summaries}

## Instructions

Assign a timeline_day (positive integer) to every scene. Output ONLY a pipe-delimited CSV block:

TIMELINE:
id|timeline_day"

    for id in "${SCENE_IDS[@]}"; do
        timeline_prompt="${timeline_prompt}
${id}|<day>"
    done

    local tl_log="${LOG_DIR}/timeline-phase2.log"

    log "Sending ${SCENE_COUNT} scene summaries to Sonnet..."

    # Background monitor for progress heartbeat
    (
        local ticks=0
        while true; do
            sleep 30
            ticks=$((ticks + 1))
            local elapsed=$(( $(date +%s) - _PHASE2_START ))
            local mins=$(( elapsed / 60 ))
            local secs=$(( elapsed % 60 ))
            log "  Phase 2: ${mins}m${secs}s elapsed..."
        done
    ) &
    local monitor_pid=$!
    register_child_pid $monitor_pid

    _PHASE2_START=$(date +%s)
    _SF_INVOCATION_START=$_PHASE2_START
    export _SF_INVOCATION_START

    begin_healing_zone "timeline phase 2 assignment"

    claude -p "$timeline_prompt" \
        --model "$SONNET_MODEL" \
        --dangerously-skip-permissions \
        --output-format stream-json \
        --verbose \
        > "$tl_log" 2>&1 || true

    end_healing_zone

    # Kill monitor
    kill "$monitor_pid" 2>/dev/null || true
    wait "$monitor_pid" 2>/dev/null || true
    unregister_child_pid "$monitor_pid" 2>/dev/null || true

    local response
    response=$(extract_claude_response "$tl_log" 2>/dev/null || true)
    log_usage "$tl_log" "timeline-phase2" "all" "$SONNET_MODEL"

    if [[ -z "$response" ]]; then
        log "WARNING: No response from Sonnet for timeline assignment"
        return 1
    fi

    # Parse TIMELINE: CSV block
    ASSIGNED=0
    SKIPPED=0
    local in_block=false
    while IFS= read -r line; do
        if [[ "$line" == "TIMELINE:" ]]; then
            in_block=true
            continue
        fi
        [[ "$in_block" != true ]] && continue
        [[ "$line" == "id|timeline_day" ]] && continue
        [[ -z "$line" ]] && continue
        [[ "$line" == *":"* && "$line" != *"|"* ]] && break

        local scene_id day_val
        scene_id=$(echo "$line" | cut -d'|' -f1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        day_val=$(echo "$line" | cut -d'|' -f2 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

        if [[ "$day_val" =~ ^[0-9]+$ ]] && (( day_val > 0 )); then
            local existing
            existing=$(get_csv_field "$METADATA_CSV" "$scene_id" "timeline_day")
            if [[ -n "$existing" && "$FORCE" != true ]]; then
                SKIPPED=$((SKIPPED + 1))
            else
                update_csv_field "$METADATA_CSV" "$scene_id" "timeline_day" "$day_val"
                ASSIGNED=$((ASSIGNED + 1))
            fi
        fi
    done <<< "$response"

    log "Phase 2 complete: ${ASSIGNED} assigned, ${SKIPPED} skipped (already set)"
}

# ============================================================================
# Interactive checkpoint helper
# ============================================================================

run_interactive_checkpoint() {
    local phase_label="$1"
    local display_content="$2"
    local work_unit="$3"

    show_interactive_banner "Timeline — ${phase_label}" "single"

    local interactive_system
    interactive_system=$(build_interactive_system_prompt "$PROJECT_DIR" "$work_unit")

    local checkpoint_prompt="Here are the results from ${phase_label}. Review them and let me know if you'd like any changes.

${display_content}

When you're satisfied, type /exit to continue."

    set +e
    claude "$checkpoint_prompt" \
        --model "$SONNET_MODEL" \
        --dangerously-skip-permissions \
        --append-system-prompt "$interactive_system"
    set -e
}

# ============================================================================
# Main execution flow
# ============================================================================

# --- Phase 1 ---
if [[ "$SKIP_PHASE1" == true ]]; then
    # Check for cached indicators
    cached_count=0
    for id in "${SCENE_IDS[@]}"; do
        [[ -f "${TIMELINE_DIR}/.indicators-${id}" ]] && cached_count=$((cached_count + 1))
    done
    if (( cached_count > 0 )); then
        log "Skipping Phase 1: using ${cached_count} cached indicator files"
    else
        log "Skipping Phase 1: no cached indicators, Phase 2 will use raw metadata"
    fi
else
    run_phase1
fi

# --- Interactive checkpoint 1 (after Phase 1) ---
if [[ -f "$INTERACTIVE_FILE" ]]; then
    # Build display of all indicators
    indicator_display=""
    for id in "${SCENE_IDS[@]}"; do
        seq_val=$(get_csv_field "$METADATA_CSV" "$id" "seq")
        title=$(get_csv_field "$METADATA_CSV" "$id" "title")
        indicator_file="${TIMELINE_DIR}/.indicators-${id}"
        indicators="(not extracted)"
        [[ -f "$indicator_file" ]] && indicators=$(cat "$indicator_file")
        indicator_display="${indicator_display}
SEQ ${seq_val}: ${title} (${id})
  Indicators: ${indicators}
"
    done

    run_interactive_checkpoint "Phase 1: Temporal Indicators" "$indicator_display" "review"
fi

# --- Offer interactive rejoin between phases (autonomous mode) ---
if [[ ! -f "$INTERACTIVE_FILE" && "$EMBEDDED" != true ]]; then
    offer_interactive "$PROJECT_DIR" "Phase 2: Sonnet timeline assignment" || true
fi

# Update PR task (standalone mode)
if [[ "$EMBEDDED" != true ]]; then
    update_pr_task "enrichment" "$PROJECT_DIR" 2>/dev/null || true
fi

# --- Phase 2 ---
run_phase2

# --- Interactive checkpoint 2 (after Phase 2) ---
if [[ -f "$INTERACTIVE_FILE" ]]; then
    # Build display of assignments
    assignment_display="Timeline assignments:
"
    for id in "${SCENE_IDS[@]}"; do
        seq_val=$(get_csv_field "$METADATA_CSV" "$id" "seq")
        title=$(get_csv_field "$METADATA_CSV" "$id" "title")
        day_val=$(get_csv_field "$METADATA_CSV" "$id" "timeline_day")
        assignment_display="${assignment_display}  SEQ ${seq_val}: Day ${day_val:-?} — ${title} (${id})
"
    done

    run_interactive_checkpoint "Phase 2: Timeline Assignments" "$assignment_display" "review"
fi

# ============================================================================
# Commit & cleanup
# ============================================================================

if [[ "$EMBEDDED" != true ]]; then
    (
        cd "$PROJECT_DIR"
        git add "reference/scene-metadata.csv" 2>/dev/null || true
        git add "working/logs/" 2>/dev/null || true
        git commit -m "Enrich: timeline_day assignment" 2>/dev/null || true
        git push 2>/dev/null || true
    )

    # Update PR task
    update_pr_task "enrichment" "$PROJECT_DIR" 2>/dev/null || true
fi

# Clean up temp files
rm -f "${TIMELINE_DIR}"/.indicators-* "${TIMELINE_DIR}"/.status-*

# Cleanup interactive file (standalone mode only)
if [[ "$EMBEDDED" != true ]]; then
    rm -f "$INTERACTIVE_FILE"
fi

# ============================================================================
# Summary
# ============================================================================

log ""
log "============================================"
log "Timeline assignment complete"
log "  Scenes analyzed: ${SCENE_COUNT}"
log "  Assigned: ${ASSIGNED:-0}"
log "  Skipped: ${SKIPPED:-0}"
log "============================================"

if [[ "$EMBEDDED" != true ]]; then
    print_cost_summary "timeline-phase1"
    print_cost_summary "timeline-phase2"
fi
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/storyforge-timeline
```

- [ ] **Step 3: Verify it parses arguments correctly**

Run: `scripts/storyforge-timeline --help`
Expected: Usage text printed, exit 0

Run: `scripts/storyforge-timeline --dry-run` (from a test project directory)
Expected: Dry-run output listing scenes

- [ ] **Step 4: Commit**

```bash
git add scripts/storyforge-timeline
git commit -m "Add storyforge-timeline script skeleton with two-phase architecture"
git push
```

---

## Chunk 2: Tests

### Task 3: Create test suite for timeline

**Files:**
- Create: `tests/test-timeline.sh`

- [ ] **Step 1: Write tests for argument parsing and indicator parsing**

Create `tests/test-timeline.sh`:

```bash
#!/bin/bash
# test-timeline.sh — Tests for storyforge-timeline

# ============================================================================
# Fixtures are already available via run-tests.sh:
#   $FIXTURE_DIR = tests/fixtures/test-project
#   $PLUGIN_DIR  = repo root
#   $TMPDIR      = temp directory (cleaned up automatically)
#   Libraries (common.sh, csv.sh, scene-filter.sh) are already sourced
# ============================================================================

METADATA_CSV="${FIXTURE_DIR}/reference/scene-metadata.csv"

# --- Make a working copy so we don't pollute fixtures ---
TEST_META="${TMPDIR}/scene-metadata.csv"
cp "$METADATA_CSV" "$TEST_META"

# ============================================================================
# Scene list integration
# ============================================================================

build_scene_list "$TEST_META"
assert_not_empty "${ALL_SCENE_IDS[*]}" "timeline: scene list is populated"

apply_scene_filter "$TEST_META" "all"
assert_equals "4" "${#FILTERED_IDS[@]}" "timeline: all filter returns all scenes"

apply_scene_filter "$TEST_META" "act" "1"
assert_equals "3" "${#FILTERED_IDS[@]}" "timeline: act 1 filter returns 3 scenes"

apply_scene_filter "$TEST_META" "act" "2"
assert_equals "1" "${#FILTERED_IDS[@]}" "timeline: act 2 filter returns 1 scene"

# ============================================================================
# Timeline CSV field operations
# ============================================================================

# Read existing timeline_day
RESULT=$(get_csv_field "$TEST_META" "act1-sc01" "timeline_day")
assert_equals "1" "$RESULT" "timeline: reads existing timeline_day"

# Update timeline_day
update_csv_field "$TEST_META" "act2-sc01" "timeline_day" "5"
RESULT=$(get_csv_field "$TEST_META" "act2-sc01" "timeline_day")
assert_equals "5" "$RESULT" "timeline: updates timeline_day in CSV"

# Overwrite existing
update_csv_field "$TEST_META" "act1-sc01" "timeline_day" "99"
RESULT=$(get_csv_field "$TEST_META" "act1-sc01" "timeline_day")
assert_equals "99" "$RESULT" "timeline: overwrites existing timeline_day"

# ============================================================================
# Indicator parsing
# ============================================================================

# Simulate Phase 2 response parsing
MOCK_RESPONSE='Some preamble text here.

TIMELINE:
id|timeline_day
act1-sc01|1
act1-sc02|1
new-x1|2
act2-sc01|3

Some trailing text.'

# Reset test CSV
cp "$METADATA_CSV" "$TEST_META"
# Clear timeline_day for act2-sc01 to test assignment
update_csv_field "$TEST_META" "act2-sc01" "timeline_day" ""

# Parse the mock response (same logic as the script)
ASSIGNED=0
SKIPPED=0
FORCE=true
in_block=false
while IFS= read -r line; do
    if [[ "$line" == "TIMELINE:" ]]; then
        in_block=true
        continue
    fi
    [[ "$in_block" != true ]] && continue
    [[ "$line" == "id|timeline_day" ]] && continue
    [[ -z "$line" ]] && continue
    [[ "$line" == *":"* && "$line" != *"|"* ]] && break

    scene_id=$(echo "$line" | cut -d'|' -f1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    day_val=$(echo "$line" | cut -d'|' -f2 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

    if [[ "$day_val" =~ ^[0-9]+$ ]] && (( day_val > 0 )); then
        existing=$(get_csv_field "$TEST_META" "$scene_id" "timeline_day")
        if [[ -n "$existing" && "$FORCE" != true ]]; then
            SKIPPED=$((SKIPPED + 1))
        else
            update_csv_field "$TEST_META" "$scene_id" "timeline_day" "$day_val"
            ASSIGNED=$((ASSIGNED + 1))
        fi
    fi
done <<< "$MOCK_RESPONSE"

assert_equals "4" "$ASSIGNED" "timeline: parses all 4 timeline entries"
assert_equals "0" "$SKIPPED" "timeline: skips 0 with --force"

RESULT=$(get_csv_field "$TEST_META" "act1-sc01" "timeline_day")
assert_equals "1" "$RESULT" "timeline: assigns day 1 to act1-sc01"

RESULT=$(get_csv_field "$TEST_META" "act2-sc01" "timeline_day")
assert_equals "3" "$RESULT" "timeline: assigns day 3 to act2-sc01"

# ============================================================================
# Indicator parsing — skip without force
# ============================================================================

cp "$METADATA_CSV" "$TEST_META"

ASSIGNED=0
SKIPPED=0
FORCE=false
in_block=false
while IFS= read -r line; do
    if [[ "$line" == "TIMELINE:" ]]; then
        in_block=true
        continue
    fi
    [[ "$in_block" != true ]] && continue
    [[ "$line" == "id|timeline_day" ]] && continue
    [[ -z "$line" ]] && continue
    [[ "$line" == *":"* && "$line" != *"|"* ]] && break

    scene_id=$(echo "$line" | cut -d'|' -f1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    day_val=$(echo "$line" | cut -d'|' -f2 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

    if [[ "$day_val" =~ ^[0-9]+$ ]] && (( day_val > 0 )); then
        existing=$(get_csv_field "$TEST_META" "$scene_id" "timeline_day")
        if [[ -n "$existing" && "$FORCE" != true ]]; then
            SKIPPED=$((SKIPPED + 1))
        else
            update_csv_field "$TEST_META" "$scene_id" "timeline_day" "$day_val"
            ASSIGNED=$((ASSIGNED + 1))
        fi
    fi
done <<< "$MOCK_RESPONSE"

assert_equals "0" "$ASSIGNED" "timeline: no-force skips existing values"
assert_equals "4" "$SKIPPED" "timeline: counts 4 skipped without force"

# ============================================================================
# Haiku indicator extraction parsing
# ============================================================================

# Simulate Haiku response
HAIKU_RESPONSE='Here is my analysis of the temporal indicators in this scene.

INDICATORS: "the next morning", wakes up, breakfast, "three days later"'

indicators=$(echo "$HAIKU_RESPONSE" | grep -i "^INDICATORS:" | sed 's/^INDICATORS:[[:space:]]*//' | head -1 || true)
assert_not_empty "$indicators" "timeline: parses INDICATORS line from Haiku response"
assert_contains "$indicators" "the next morning" "timeline: extracts quoted time reference"
assert_contains "$indicators" "wakes up" "timeline: extracts sleep/wake indicator"
assert_contains "$indicators" "breakfast" "timeline: extracts meal reference"

# No indicators
HAIKU_EMPTY='I found no temporal indicators in this scene.

INDICATORS: (none)'

indicators=$(echo "$HAIKU_EMPTY" | grep -i "^INDICATORS:" | sed 's/^INDICATORS:[[:space:]]*//' | head -1 || true)
assert_equals "(none)" "$indicators" "timeline: handles (none) indicator response"

# ============================================================================
# Model selection for extraction
# ============================================================================

RESULT=$(select_model "extraction")
assert_equals "claude-haiku-4-5-20251001" "$RESULT" "timeline: select_model extraction returns haiku"

RESULT=$(select_model "evaluation")
assert_contains "$RESULT" "sonnet" "timeline: select_model evaluation returns sonnet"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `./tests/run-tests.sh tests/test-timeline.sh`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test-timeline.sh
git commit -m "Add test suite for storyforge-timeline"
git push
```

---

## Chunk 3: Enrich integration

### Task 4: Modify storyforge-enrich to delegate to storyforge-timeline

**Files:**
- Modify: `scripts/storyforge-enrich`

- [ ] **Step 1: Add `--skip-timeline` flag to argument parsing**

In the argument parsing `while` loop (around line 97), add a new case:

```bash
        --skip-timeline)
            SKIP_TIMELINE=true
            shift
            ;;
```

Add the default at the top with the other defaults (around line 35):

```bash
SKIP_TIMELINE=false
```

Update the usage text (around line 68) to include:

```
  --skip-timeline     Skip the timeline_day analysis pass
```

- [ ] **Step 2: Remove `--timeline` flag and `TIMELINE_MODE`**

Remove from defaults (line 37):
```bash
TIMELINE_MODE=false
```

Remove from argument parsing (lines 101-104):
```bash
        --timeline)
            TIMELINE_MODE=true
            shift
            ;;
```

Remove the standalone timeline mode block (lines 521-536 approximately — the `if [[ "$TIMELINE_MODE" == true ]]; then` block through its `exit 0`).

Remove from the usage text the `--timeline` lines and the "Modes:" section.

- [ ] **Step 3: Remove `run_timeline_pass()` function**

Delete the entire `run_timeline_pass()` function (lines 382-515 approximately — from the comment block `# Timeline analysis function` through the closing `}`).

Also delete the standalone timeline mode section that called it.

- [ ] **Step 4: Replace Step 8 with subprocess call**

Replace the current Step 8 block (around lines 1112-1117):

```bash
# ============================================================================
# Step 8: Timeline pass (multi-scene analysis for timeline_day)
# ============================================================================

if [[ "$DRY_RUN" != true ]]; then
    run_timeline_pass "${FILTERED_IDS[*]}"
fi
```

With:

```bash
# ============================================================================
# Step 8: Timeline pass (delegated to storyforge-timeline)
# ============================================================================

if [[ "$SKIP_TIMELINE" != true && "$DRY_RUN" != true ]]; then
    log ""
    log "Step 8: Timeline analysis (delegating to storyforge-timeline)..."
    TIMELINE_SCRIPT="${SCRIPT_DIR}/storyforge-timeline"

    if [[ -x "$TIMELINE_SCRIPT" ]]; then
        TIMELINE_ARGS=(--embedded)
        [[ "$FORCE" == true ]] && TIMELINE_ARGS+=(--force)

        # Pass through scene filter
        case "$FILTER_MODE" in
            scenes)   TIMELINE_ARGS+=(--scenes "$FILTER_SCENES") ;;
            act)      TIMELINE_ARGS+=(--act "$FILTER_ACT") ;;
            from_seq) TIMELINE_ARGS+=(--from-seq "$FILTER_FROM_SEQ") ;;
        esac

        "$TIMELINE_SCRIPT" "${TIMELINE_ARGS[@]}" || {
            log "WARNING: Timeline analysis failed (non-fatal, continuing)"
        }
    else
        log "WARNING: storyforge-timeline not found at ${TIMELINE_SCRIPT}, skipping timeline"
    fi
elif [[ "$SKIP_TIMELINE" == true ]]; then
    log ""
    log "Step 8: Timeline analysis (skipped via --skip-timeline)"
fi
```

- [ ] **Step 5: Remove `timeline_day` from per-scene enrichment references**

Remove `timeline_day` from `VALID_FIELDS` (line 46) since it's now exclusively handled by the timeline script:

Change:
```bash
VALID_FIELDS="type,location,timeline_day,time_of_day,characters,emotional_arc,threads,motifs"
```
To:
```bash
VALID_FIELDS="type,location,time_of_day,characters,emotional_arc,threads,motifs"
```

Also remove the `timeline_day` case from `is_metadata_field()` (around line 548) and `validate_timeline_day()` function, and the `TIMELINE_DAY` parsing/writing in the per-scene worker.

Note: Be careful to remove ONLY the per-scene `timeline_day` handling. The `timeline_day` column still exists in the CSV — it's just now managed by `storyforge-timeline` instead of enrich's per-scene workers.

- [ ] **Step 6: Update the script header comment**

Update line 10 from:
```bash
# Enriches metadata.csv fields: type, timeline_day, time_of_day
```
To:
```bash
# Enriches metadata.csv fields: type, time_of_day
# (timeline_day is handled by storyforge-timeline, called as Step 8)
```

- [ ] **Step 7: Verify enrich still works with dry-run**

Run: `cd <test-project> && <plugin-path>/scripts/storyforge-enrich --dry-run`
Expected: Dry-run output without timeline mode references, Step 8 mentions delegation

- [ ] **Step 8: Commit**

```bash
git add scripts/storyforge-enrich
git commit -m "Remove inline timeline from enrich, delegate to storyforge-timeline"
git push
```

---

## Chunk 4: Version bump and final verification

### Task 5: Bump version and final checks

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Run all tests**

Run: `./tests/run-tests.sh`
Expected: All suites pass, including the new `test-timeline.sh`

- [ ] **Step 2: Bump version to 0.22.2**

In `.claude-plugin/plugin.json`, change:
```json
"version": "0.22.0"
```
To:
```json
"version": "0.22.2"
```

- [ ] **Step 3: Commit version bump**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 0.22.2"
git push
```

- [ ] **Step 4: Verify storyforge-timeline --help works**

Run: `scripts/storyforge-timeline --help`
Expected: Clean usage output with all options documented

- [ ] **Step 5: Verify storyforge-enrich --dry-run still works**

Run from a project directory: `<plugin-path>/scripts/storyforge-enrich --dry-run`
Expected: Normal output, Step 8 references storyforge-timeline delegation
