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
- `reference/scenes.csv` (elaboration) or `reference/scene-metadata.csv` (legacy) — scene structural data
- `reference/scene-intent.csv` — narrative dynamics (function, value_shift, scene_type, threads, characters)
- `reference/scene-briefs.csv` — drafting contracts (goal, conflict, outcome, knowledge states, motifs)
- `working/scores/latest/scene-scores.csv` — craft scores (if scoring has run)
- `working/scores/latest/fidelity-scores.csv` — brief fidelity scores (if scoring has run)
- `working/dashboard.html` — if a dashboard already exists

## Step 2: Assess Data Quality

The multi-page dashboard has three pages with different data needs:

**Overview page:**

| Visualization | Required Fields | Source |
|---|---|---|
| Manuscript Spine | word_count, type | scenes.csv |
| POV River | pov, word_count | scenes.csv |
| Value Shift Arc | value_shift | scene-intent.csv |
| Scene Rhythm | scene_type, turning_point | scene-intent.csv |

**Structure page:**

| Visualization | Required Fields | Source |
|---|---|---|
| Character Presence Grid | characters | scene-intent.csv |
| Thread Weave | threads | scene-intent.csv |
| Emotional Terrain | emotional_arc | scene-intent.csv |
| Scene Type Sequence | type | scenes.csv |
| Location Map | location | scenes.csv |
| Motif Constellation | motifs | scene-briefs.csv |
| Timeline vs Reading Order | timeline_day | scenes.csv |

**Scores page:**

| Visualization | Required Fields | Source |
|---|---|---|
| Craft Score Heatmap | scene-scores.csv | working/scores/latest/ |
| Brief Fidelity | fidelity-scores.csv | working/scores/latest/ |
| Genre Scores | genre-scores.csv | working/scores/latest/ |
| Character Scores | character-scores.csv | working/scores/latest/ |
| Act Scores | act-scores.csv | working/scores/latest/ |
| Narrative Radar | narrative-scores.csv | working/scores/latest/ |

Report which pages will be populated:
- "Overview is ready — scenes.csv has pov, word_count, and intent has value_shift."
- "Structure page needs enrichment — threads and characters are empty."
- "Scores page needs a scoring cycle — run `./storyforge score` first."

If intent/brief data is missing, suggest extraction: "Would you like to run `./storyforge extract` to populate the scene data from prose? The dashboard will be much richer."

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
