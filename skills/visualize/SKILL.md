---
name: visualize
description: Generate the manuscript dashboard — 10 interconnected visualizations showing POV distribution, character presence, thread weaving, emotional terrain, craft scores, and more. Use when the author wants to see their book visually.
---

# Storyforge Visualize Skill

You are helping an author generate and explore their manuscript visualization dashboard.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory (this skill's directory -> `skills/` -> plugin root). Scripts live at `scripts/` and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Read the following files to assess readiness:

- `storyforge.yaml` — project configuration
- `scenes/metadata.csv` — check field completeness (id, title, pov, setting, part, type, word_count, timeline_day, time_of_day)
- `scenes/intent.csv` — check field completeness (characters, threads, motifs, emotional_arc)
- `working/scores/latest/scene-scores.csv` — if scoring data exists
- `working/dashboard.html` — if a dashboard already exists

## Step 2: Assess Data Quality

The dashboard's 10 visualizations need different data:

| Visualization | Required Fields | Optional |
|---|---|---|
| Manuscript Spine | word_count, type | part |
| POV River | pov, word_count | part |
| Character Presence Grid | characters (intent.csv) | pov |
| Thread Weave | threads (intent.csv) | |
| Emotional Terrain | emotional_arc (intent.csv) | |
| Scene Type Sequence | type | |
| Setting Map | setting | |
| Craft Score Heatmap | scene-scores.csv | craft-weights.csv |
| Motif Constellation | motifs (intent.csv) | |
| Timeline vs Reading Order | timeline_day | |

Report which visualizations will be populated vs empty based on current data:
- "POV River and Setting Map are ready (pov and setting are fully populated)."
- "Character Presence, Thread Weave, and Motif Constellation will be empty — those fields haven't been enriched yet."

If many fields are missing, suggest running enrichment first: "Would you like to run `/storyforge:enrich` first to fill in the missing metadata? The dashboard will be much richer."

## Step 3: Generate Dashboard

Present the author with two options:

> **Option A: Generate it here**
> I'll run the visualization script in this conversation. This is fast (no API calls — it just reads CSVs and generates HTML).
>
> ```bash
> [plugin_path]/scripts/storyforge-visualize
> ```
>
> **Option B: Generate it yourself**
> Copy this command and run it in a terminal:
> ```bash
> cd [project_dir] && [plugin_path]/scripts/storyforge-visualize --open
> ```
> The `--open` flag opens the dashboard in your default browser.

Wait for the author's choice.

### If Option A:

1. Run the script:
   ```bash
   [plugin_path]/scripts/storyforge-visualize
   ```
   Note: This script does NOT invoke Claude, so `unset CLAUDECODE` is NOT needed. It only reads CSV files and generates HTML.

2. Report the result:
   - File location: `working/dashboard.html`
   - Which visualizations are populated
   - Suggest opening it: "Open `working/dashboard.html` in a browser to explore, or run with `--open` to open automatically."

### If Option B:

Provide the command. Note that `--open` works if they have a browser available (won't work over SSH — they can download/view the committed file on GitHub instead).

## Step 4: Explore Results

If the author wants to discuss what they see in the dashboard:

- Help interpret visualizations: "Your POV River shows Maren has 65% of scenes — is that the balance you want?"
- Connect observations to action: "The Thread Weave shows your 'family_secret' thread goes dormant for 20 scenes in Act 3. Consider adding a callback."
- Suggest scoring for deeper analysis: "The Craft Score Heatmap is empty — run `/storyforge:score` to see how each scene performs against craft principles."

## Step 5: Commit After Every Deliverable

After generating the dashboard or making any changes:
```
git add -A && git commit -m "Visualize: generate manuscript dashboard" && git push
```

## Coaching Level Behavior

### `full` (default)
Proactively assess data quality, suggest enrichment if needed, generate the dashboard, and walk through key observations. Offer to help interpret what they see.

### `coach`
Generate the dashboard and highlight 2-3 notable patterns as questions: "I notice your character presence shows X — is that deliberate?" Let the author lead the exploration.

### `strict`
Generate the dashboard. Report which visualizations are populated. Don't interpret or suggest.
