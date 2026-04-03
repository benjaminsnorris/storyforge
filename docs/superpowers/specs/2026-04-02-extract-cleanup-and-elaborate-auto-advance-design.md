# Extract Cleanup & Elaborate Auto-Advance

**Date:** 2026-04-02

## Problem

After running `storyforge extract`, intermediate files linger (`.knowledge-state.json`, batch logs, phase logs) and legacy files from pre-extraction state remain (`scene-metadata.csv`). The user gets no clear signal of what to do next.

When the user then invokes `elaborate` without specifying a stage, the skill presents a menu of 10 possible modes and waits for direction — even when the obvious next action is clear from project state.

## Design

### Extract Cleanup

At the end of the extract script, after the existing validation/deterministic-cleanup phase, add a cleanup step:

**Remove intermediate files:**
- `working/.knowledge-state.json`
- `working/.scene-summaries.txt`
- `working/logs/extract-*.log` (phase logs)
- Batch JSONL/output files from the extraction working directory

**Remove legacy files (only if the three-file model is populated — scenes.csv exists with rows):**
- `reference/scene-metadata.csv` (replaced by `scenes.csv`)
- `reference/scenes/intent.csv` (old path, replaced by `scene-intent.csv`)
- `working/pipeline.yaml`
- `working/assemble.py`

**Print next step:**
After cleanup, print a clear next-step message:
> "Extraction complete. N validation issues remain. Next: run `/storyforge:elaborate` to fill structural gaps."

If validation passes clean (0 issues), adjust the message:
> "Extraction complete. All validation checks pass. Next: run `/storyforge:elaborate` to continue development."

### Elaborate Auto-Advance

When someone invokes elaborate without specifying a stage or mode (just "elaborate", "what's next", "keep going"), the skill reads project state and auto-advances based on coaching level.

**State detection and action mapping:**

| Detected State | Action |
|---|---|
| No scenes.csv | Start spine |
| Spine done (5-10 rows, function only) | Run architecture |
| Architecture done (has value_shift, threads) | Run scene map |
| Map done (has characters, on_stage) | Run briefs |
| Briefs done, validation passes | Announce ready for drafting, redirect to forge |
| Drafted with validation failures > 0 | Run gap-fill |
| Everything passes | Redirect to forge |

**Coaching level behavior:**

- **full:** Announce what's needed. Do it immediately. "Your scenes are at architecture stage. I'll expand to the full scene map now."
- **coach:** Present the recommendation. Wait for approval. "Your scenes are at architecture stage. The next step is expanding to a full scene map — locations, timeline, characters, MICE threads. Ready to go?"
- **strict:** Report state data only. "Current state: 22 scenes at architecture depth. 0 mapped. Next stage: scene-map. Run `./storyforge elaborate --stage map` or work through it here."

**What does NOT change:**

- Specific mode requests still work: "develop the voice", "work on characters", "build the world" — these bypass auto-advance and route directly to the requested mode.
- Auto-advance only applies to unspecified invocations ("elaborate", "what's next", "keep going").
- The state detection table from Step 2 is unchanged — auto-advance just acts on it instead of reporting it.

### Integration

**Extract → Elaborate flow:** Extract prints the next-step message. When the user invokes elaborate, it auto-detects the post-extraction gap-fill state and runs gap-fill (in full mode) or recommends it (in coach/strict mode).

**Forge interaction:** Forge's priority 1.5 (post-extraction gaps) continues to work as before. The improvement is that elaborate itself is now smart enough to do the same thing when invoked directly, without going through forge first.
