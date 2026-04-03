# Extract Cleanup & Elaborate Auto-Advance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make extract clean up after itself and make elaborate auto-advance to the right stage without waiting for user direction.

**Architecture:** Extract gets a cleanup block at the end that removes intermediate and legacy files, plus a better next-step message. Elaborate's SKILL.md gets a new auto-advance section in Step 3 that acts on state detection based on coaching level instead of waiting for user input.

**Tech Stack:** Bash (storyforge-extract), Markdown (SKILL.md)

---

### Task 1: Add cleanup step to extract script

**Files:**
- Modify: `scripts/storyforge-extract` (~line 762, after validation, before expansion analysis)

- [ ] **Step 1: Add file cleanup block**

In `scripts/storyforge-extract`, insert the following block after the validation section (after line 761 `update_pr_task "Validate"...`) and before the expansion analysis section (line 763 `# Expansion analysis`):

```bash
# ============================================================================
# File cleanup (remove intermediates and legacy files)
# ============================================================================

if [[ "$DRY_RUN" != true ]]; then
    log ""
    log "--- Cleaning up ---"

    CLEANED=0

    # Remove intermediate extraction files
    for f in \
        "${LOG_DIR}/.knowledge-state.json" \
        "${LOG_DIR}/.scene-summaries.txt" \
        "${LOG_DIR}/extract-phase0.log" \
        "${LOG_DIR}/extract-phase1-batch.jsonl" \
        "${LOG_DIR}/extract-phase2-batch.jsonl" \
        "${LOG_DIR}/extract-phase3a-batch.jsonl" \
    ; do
        if [[ -f "$f" ]]; then
            rm -f "$f"
            CLEANED=$((CLEANED + 1))
        fi
    done

    # Remove batch output/log directories from extraction phases
    for d in \
        "${LOG_DIR}/phase1-output" \
        "${LOG_DIR}/phase1-logs" \
        "${LOG_DIR}/phase2-output" \
        "${LOG_DIR}/phase2-logs" \
        "${LOG_DIR}/phase3a-output" \
        "${LOG_DIR}/phase3a-logs" \
    ; do
        if [[ -d "$d" ]]; then
            rm -rf "$d"
            CLEANED=$((CLEANED + 1))
        fi
    done

    # Remove legacy files (only if three-file model is populated)
    if [[ -f "${REF_DIR}/scenes.csv" ]]; then
        for f in \
            "${REF_DIR}/scene-metadata.csv" \
            "${REF_DIR}/scenes/intent.csv" \
            "${PROJECT_DIR}/working/pipeline.yaml" \
            "${PROJECT_DIR}/working/assemble.py" \
        ; do
            if [[ -f "$f" ]]; then
                log "  Removing legacy file: $(basename "$f")"
                rm -f "$f"
                CLEANED=$((CLEANED + 1))
            fi
        done
    fi

    if (( CLEANED > 0 )); then
        log "  Removed ${CLEANED} intermediate/legacy file(s)"
    fi
fi
```

- [ ] **Step 2: Update the summary message at the end of the script**

Replace the existing summary block (lines 793-798):

```bash
log ""
log "============================================"
log "Extraction complete."
log "  scenes.csv, scene-intent.csv, scene-briefs.csv populated"
log "  Run /storyforge:validate to verify, then review and correct the extracted data"
log "============================================"
```

with:

```bash
log ""
log "============================================"
log "Extraction complete."
if [[ "${VALIDATE_PASSED:-}" == "True" ]]; then
    log "  All validation checks pass."
    log "  Next: run /storyforge:elaborate to continue development."
else
    log "  ${VALIDATE_FAILURES:-0} validation issue(s) remain."
    log "  Next: run /storyforge:elaborate to fill structural gaps."
fi
log "============================================"
```

- [ ] **Step 3: Verify the script parses correctly**

Run: `bash -n scripts/storyforge-extract`
Expected: No output (no syntax errors).

- [ ] **Step 4: Commit**

```bash
git add scripts/storyforge-extract
git commit -m "Add post-extraction cleanup and next-step guidance"
git push
```

---

### Task 2: Add auto-advance to elaborate skill

**Files:**
- Modify: `skills/elaborate/SKILL.md` (Step 3, lines 43-56)

- [ ] **Step 1: Replace Step 3 with auto-advance logic**

In `skills/elaborate/SKILL.md`, replace the entire Step 3 section (from `## Step 3: Determine Mode` through the bullet list ending with `- **Status question** → Report current stage, scene count, validation state.`) with:

```markdown
## Step 3: Determine Mode

Based on the author's request, determine the mode:

### Specific requests (always honored, bypass auto-advance):

- **"Start a new novel"** / **"Let's begin"** → Start at spine. Ask for the seed (logline, genre, characters, themes, constraints). Whatever they give you is the seed.
- **"Work on the spine/architecture/map/briefs"** → Go to that specific stage.
- **"Develop the voice"** / **"Voice guide"** / **"Style"** → Voice development (see Voice Stage below). Typically happens after architecture and before briefs.
- **"Deepen characters"** / **"Work on [character name]"** → Character development. During elaboration, this deepens the character bible entries. The spine creates seed entries; this mode enriches them with wound/lie/need structure, voice fingerprints, and relationship dynamics.
- **"Build the world"** / **"World building"** → World bible development. During elaboration, world building supports the architecture and scene map stages.
- **"Story architecture"** / **"Theme"** / **"Structure"** → Story architecture refinement. The spine creates the initial architecture; this mode deepens thematic throughlines, conflict structure, and arc planning.
- **"Validate"** → Run validation on the current state.
- **Status question** → Report current stage, scene count, validation state.

### Auto-advance (unspecified requests — "elaborate", "what's next", "keep going"):

When the author doesn't specify a mode, detect the current stage from Step 2 and act based on coaching level:

| Detected State | Action |
|---|---|
| No scenes.csv (or 0 rows) | Start spine |
| Spine done (5-10 rows, function only) | Run architecture |
| Architecture done (has value_shift, threads) | Run scene map |
| Map done (has characters, on_stage) | Run briefs |
| Briefs done, validation passes | Announce ready for drafting, redirect to forge |
| Drafted with validation failures > 0 | Run gap-fill |
| Everything passes | Redirect to forge |

**Coaching level determines posture:**

**Full mode:** Announce the action and do it immediately.
- "No spine yet — let's build one. What's your logline or seed idea?"
- "Your scenes are at architecture stage. I'll expand to the full scene map now."
- "Post-extraction data has 47 gaps. I'll fill them — starting with the parallel batches."

**Coach mode:** Present the recommendation and wait for approval.
- "Your scenes are at architecture stage. The next step is expanding to a full scene map — locations, timeline, characters, MICE threads. Ready to go?"
- "I found 47 structural gaps in your extracted data. Want me to fill them?"

**Strict mode:** Report state data only. Author decides.
- "Current state: 22 scenes at architecture depth. 0 mapped. Next stage: scene-map. Run `./storyforge elaborate --stage map` or work through it here."
- "Validation: 47 failures across 5 gap groups. Run `./storyforge elaborate --stage gap-fill` to fill automatically."

After the author approves (or immediately in full mode), proceed to Step 4 to execute the appropriate stage.
```

- [ ] **Step 2: Verify the skill file is valid markdown**

Read back the file and confirm the table renders correctly and no sections are broken.

- [ ] **Step 3: Commit**

```bash
git add skills/elaborate/SKILL.md
git commit -m "Add auto-advance to elaborate skill based on coaching level"
git push
```

---

### Task 3: Bump version and verify

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Run the full test suite**

Run: `./tests/run-tests.sh`
Expected: All tests pass (no test changes needed — these are script/skill changes only).

- [ ] **Step 2: Bump version**

Read `.claude-plugin/plugin.json` and bump the minor version.

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 0.50.0"
git push
```
