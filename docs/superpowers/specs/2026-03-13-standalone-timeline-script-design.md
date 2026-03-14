# Standalone Timeline Script

## Problem

Timeline analysis (`timeline_day` assignment) is currently embedded in `storyforge-enrich` as `run_timeline_pass()`. It lacks:

- **Interactive mode**: No way to review/adjust assignments before commit
- **Progress feedback**: No indication of work during autonomous execution
- **Rich temporal context**: Only sends 1000 chars of opening text per scene to Sonnet, missing time cues buried later in the prose
- **Cancellation**: No graceful shutdown or partial-work commits
- **Script standards**: No branch/PR workflow, no `offer_interactive` rejoin

## Solution

A new standalone `scripts/storyforge-timeline` script with a two-phase Haiku→Sonnet architecture, full interactive/autonomous mode support, and integration back into `storyforge-enrich` as a subprocess call.

## Two-Phase Architecture

### Phase 1: Haiku Extraction (parallel, per-scene)

Each scene's full prose is sent to Haiku with a focused prompt: extract only temporal indicators. No interpretation, no day assignment — just signal extraction.

**Haiku output per scene** (compact, ~10-20 words):
```
SEQ 12: the-market-square
  "three days later", "morning", wakes up, breakfast
```

**Temporal indicator categories:**
- Explicit time references: "the next morning", "three days later", "Tuesday"
- Temporal transitions: "later that evening", "by nightfall"
- Sleep/wake cycles: "she woke", "he went to bed"
- Meal references: "over breakfast", "dinner was cold"
- Continuity cues: "still wearing yesterday's clothes", "the wound had healed"

**Execution:** Parallel workers (default 6, configurable via `--parallel` / `STORYFORGE_TIMELINE_PARALLEL`). Each worker reads one scene file, sends prose to Haiku, writes extracted indicators to a temp file.

**Progress feedback:** Log each scene as it completes: `"[12/60] the-market-square: 4 indicators extracted"`.

### Phase 2: Sonnet Assignment (single pass, all scenes)

The full ordered list of scene IDs + their Haiku-extracted temporal indicators is sent to Sonnet in a single call. Sonnet assigns `timeline_day` (positive integer, day 1 = first story day).

**Input to Sonnet:** The compact indicator list from Phase 1, plus minimal metadata per scene (seq, title, time_of_day if known, existing timeline_day if set).

**Progress feedback:** Log when the call starts. Since `claude -p` blocks in the foreground, use a background monitor (same pattern as `monitor_progress` in common.sh) that polls the log file size every 30s and logs elapsed time. Kill the monitor when the call returns.

**Output parsing:** Same `TIMELINE:` marker + `id|timeline_day` CSV format as the current implementation.

## Interactive Mode

Two review checkpoints, matching the two phases:

### Checkpoint 1: After Haiku Extraction

Invoke Claude interactively (via `--append-system-prompt`) with the extracted indicators displayed. The author can:
- Correct misread indicators ("that's not a time skip, it's a flashback")
- Add missing context ("scenes 11 and 12 are the same afternoon")
- Claude updates the indicators file based on feedback
- Author types `/exit` to proceed to Phase 2

### Checkpoint 2: After Sonnet Assignment

Invoke Claude interactively with the proposed `timeline_day` assignments displayed in a table. The author can:
- Adjust specific assignments ("scene 20 should be day 7, not 8")
- Claude updates the CSV directly based on feedback
- Author types `/exit` to commit

### Mode Switching

- `--interactive` / `-i`: Start in interactive mode with both checkpoints
- Default (autonomous): Both phases run without stopping, progress logged throughout
- `offer_interactive` between Phase 1 and Phase 2: press `i` within timeout to rejoin
- "Finish without me" / "go auto" in interactive mode switches to autonomous for remaining work

### Autopilot File

Uses `${PROJECT_DIR}/working/.interactive` toggle file, same pattern as `storyforge-write` and `storyforge-revise`.

## Script Interface

```
Usage: storyforge-timeline [options]

Scene selection (same as other scripts):
  --scenes ID,ID,...  Specific scenes
  --act N             Scenes in part N
  --from-seq N        From sequence N onward
  --from-seq N-M      Sequence range N through M

Options:
  --interactive, -i   Interactive mode with review checkpoints
  --parallel N        Haiku extraction workers (default: 6)
  --force             Overwrite existing timeline_day values
  --dry-run           Show what would happen without invoking Claude
  --skip-phase1       Skip Haiku extraction, reuse cached indicators from working/timeline/
                      Falls back to raw metadata (title, time_of_day, 1000-char opening) if no cache exists
  --embedded          Called as subprocess (skip branch/PR/commit, just do the work)
  -h, --help          Show help
```

## Signal Handling & Cancellation

- `trap INT TERM` via common.sh `_sf_handle_interrupt`
- Phase 1 parallel workers tracked with `register_child_pid` / `unregister_child_pid`
- On interrupt: kill all workers, commit any Phase 1 results already written
- Phase 2 Sonnet call wrapped in `begin_healing_zone` / `end_healing_zone`

## Branch & PR Workflow

**Standalone mode** (default when run directly):
- Creates branch: `storyforge/timeline-*`
- Draft PR with two-task checklist:
  - [ ] Phase 1: Extract temporal indicators (Haiku)
  - [ ] Phase 2: Assign timeline_day values (Sonnet)
- Updates PR tasks as phases complete
- Commits results and prints cost summary

**Embedded mode** (`--embedded`, used when called from enrich):
- No branch creation, no PR, no commits
- Just runs both phases and updates the CSV in place
- The parent script (enrich) owns the branch, PR, and commits

## Temporary Storage

Phase 1 Haiku results are written to temp files during parallel execution, then merged into a single ordered indicators file after the batch completes. This file is the input to Phase 2.

Location: `${PROJECT_DIR}/working/timeline/` directory, cleaned up after successful completion (or preserved on error for debugging). In `--embedded` mode, always clean up on success to avoid enrich committing temp files.

## Integration with `storyforge-enrich`

### Changes to `storyforge-enrich`

1. **Remove `run_timeline_pass()`** — the function moves to the standalone script
2. **Remove `--timeline` flag** — this was a standalone early-exit mode (line 420-435) that is now replaced by calling `storyforge-timeline` directly
3. **Replace unconditional `run_timeline_pass` call in Step 8** (line 1014) with the subprocess call below
4. **Add `--skip-timeline` flag** — skips the subprocess call in Step 8
4. **Step 8 becomes a subprocess call:**

```bash
if [[ "$SKIP_TIMELINE" != true && "$DRY_RUN" != true ]]; then
    log "Step 8: Timeline analysis (delegating to storyforge-timeline)..."
    TIMELINE_SCRIPT="${PLUGIN_DIR}/scripts/storyforge-timeline"

    # Build scene filter args to match what enrich is operating on
    TIMELINE_ARGS=(--embedded --force)
    # Pass through scene filter if specified
    # ... (reconstruct filter flags)

    "$TIMELINE_SCRIPT" "${TIMELINE_ARGS[@]}" || {
        log "WARNING: Timeline analysis failed (non-fatal)"
    }
fi
```

5. **Non-fatal**: Timeline failure in enrich context logs a warning but doesn't fail the enrichment run.

### Backwards Compatibility

- `storyforge-enrich` without flags still runs timeline (via subprocess) — no behavior change
- `storyforge-enrich --skip-timeline` opts out
- `storyforge-timeline` works standalone with all the same scene filtering flags
- `storyforge-timeline --interactive` provides the new review experience

## Model Selection

- **Phase 1 (Haiku):** Add `"extraction"` task type to `select_model` in common.sh, returning `claude-haiku-4-5-20251001`. This is a new task type — existing types map to opus or sonnet only.
- **Phase 2 (Sonnet):** Uses `select_model "evaluation"` (returns sonnet), same as the current `run_timeline_pass`.
- Both respect `STORYFORGE_MODEL` env var override.

## Cost Expectations

- **Phase 1 (Haiku):** ~$0.001-0.002 per scene (small prose input, tiny output). 60 scenes ≈ $0.10
- **Phase 2 (Sonnet):** Single call with ~1-2K words of indicators ≈ $0.01-0.02
- **Total for 60 scenes:** ~$0.12, significantly cheaper than sending full prose to Sonnet
