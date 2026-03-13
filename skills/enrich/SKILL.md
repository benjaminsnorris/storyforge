---
name: enrich
description: Enrich scene metadata automatically. Use when the author wants to populate missing metadata (characters, threads, motifs, emotional arcs, scene types) or when the dashboard shows empty visualizations.
---

# Storyforge Enrich Skill

You are helping an author enrich their scene metadata — filling in missing fields that power the manuscript dashboard and scoring system.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory (this skill's directory -> `skills/` -> plugin root). Scripts live at `scripts/` and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Read the following files to understand the current state:

- `storyforge.yaml` — project configuration
- `scenes/metadata.csv` — check which fields are populated vs empty (type, timeline_day, time_of_day, word_count)
- `scenes/intent.csv` — check which fields are populated vs empty (characters, threads, motifs, emotional_arc)
- `scenes/scene-index.yaml` — if it exists, thread data can be recovered for free

Count and report the gaps: "Your metadata has 100 scenes. 95 are missing scene type, 80 are missing characters, etc."

## Step 2: Explain What Will Happen

Describe the two-phase approach:

**Phase 1 (Free — no API cost):**
- Update word_count from actual file sizes
- Infer time_of_day from keywords in prose and setting fields
- Recover threads from scene-index.yaml if available

**Phase 2 (Claude — targeted):**
- Only runs for scenes that still have gaps after Phase 1
- Builds per-scene prompts asking only for the specific missing fields
- Runs in parallel batches of 6 for speed
- Uses Sonnet (analytical task — fast and cheap)

Provide an estimated cost: "Phase 2 will need Claude for approximately N scenes at ~$X."

## Step 3: Confirm and Launch

Present the author with two options:

> **Option A: Run it here**
> I'll launch the enrichment script in this conversation. This will take approximately N minutes. Note: this invokes Claude sessions, so I need to unset the CLAUDECODE variable first.
>
> **Option B: Run it yourself**
> Copy this command and run it in a separate terminal:
> ```bash
> cd [project_dir] && [plugin_path]/scripts/storyforge-enrich
> ```
> You can add flags: `--dry-run` to preview, `--fields type,characters` for specific fields, `--act 2` for one act, `--parallel 8` for more workers.

Wait for the author's choice.

### If Option A:

1. Show the dry-run first:
   ```bash
   unset CLAUDECODE && [plugin_path]/scripts/storyforge-enrich --dry-run
   ```
2. If the author approves, run the full enrichment:
   ```bash
   unset CLAUDECODE && [plugin_path]/scripts/storyforge-enrich
   ```
3. After completion, read the updated CSVs and report what was enriched.
4. Suggest regenerating the dashboard: "Run `./storyforge visualize` to see the updated dashboard."

### If Option B:

Provide the full command with any flags the author wants. Remind them about `--dry-run`. End the conversation so they can run it.

## Step 4: Review Results

After enrichment completes (whether Option A or in a later conversation):

- Read the updated metadata.csv and intent.csv
- Report what was filled in: "Enriched 95 scenes. Characters populated for 92, threads for 88, motifs for 90, scene types for 95."
- Flag any scenes that failed enrichment
- Suggest next steps: scoring (`/storyforge:score`) or dashboard (`/storyforge:visualize`)

## Step 5: Commit After Every Deliverable

Every time you make changes (even just reviewing and noting results), commit and push:
```
git add -A && git commit -m "Enrich: {what was done}" && git push
```

## Coaching Level Behavior

### `full` (default)
Proactively recommend enrichment when gaps are detected. Offer to run immediately. After completion, suggest the dashboard and scoring as next steps.

### `coach`
Report the gaps and explain options. Let the author decide. Frame it as: "Your dashboard will be much more useful with this data — want to fill it in?"

### `strict`
Report gaps only. Provide the commands. Don't recommend or offer to run.
