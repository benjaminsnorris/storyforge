---
name: score
description: Review scores, calibrate craft weights, and provide author scoring. Use when the author wants to see scoring results, adjust principle priorities, or provide their own assessment of scenes.
---

# Storyforge Score Skill

You are helping an author review craft scores, calibrate principle weights, and provide their own scoring assessments. Scoring measures how well each scene embodies the craft principles defined in the scoring rubrics.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory -> `skills/` -> plugin root). Scripts live at `scripts/`
and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Read the following files to understand the full context:

- `storyforge.yaml` -- project configuration, active extensions, current state. **Note the `project.coaching_level` field** -- it controls how proactive you should be (see Coaching Level Behavior below).
- `working/craft-weights.csv` -- current craft weights (pipe-delimited: `section|principle|weight|author_weight|notes`).
- `working/scores/latest/` -- latest scoring cycle results:
  - `scene-scores.csv` -- per-scene scores across all principles
  - `scene-rationale.csv` -- rationale for each score
  - `diagnosis.csv` -- diagnosis of strengths and weaknesses
  - `proposals.csv` -- improvement proposals
  - `act-scores.csv` -- act-level scores (if available)
  - `character-scores.csv` -- novel-level character scores (if available)
  - `genre-scores.csv` -- novel-level genre scores (if available)
- `working/tuning.csv` -- history of weight tuning decisions (if exists)
- `working/exemplars.csv` -- bank of high-scoring passages (if exists)
- `scenes/author-scores.csv` -- author's own scores (if exists)
- `scenes/metadata.csv` -- scene metadata for context

## Step 2: Read Craft References

From the Storyforge plugin directory:

- Read `references/scoring-rubrics.md` -- understand the rubric definitions for each principle.
- Read `references/craft-engine.md` -- understand the craft principles being measured.
- Read `references/default-craft-weights.csv` -- default weight values for comparison.

## Step 3: Determine Mode

**If invoked with specific direction** (e.g., "show me scores for Act 1" or "I want to adjust weights"), go directly to the appropriate mode and execute.

**If invoked without direction**, assess the scoring state: if no scores exist, offer to run a scoring cycle; if scores exist, present a summary and ask what the author wants to explore.

Based on the direction (given or self-determined), operate in one of these modes:

---

## Review Mode: Viewing Scores

Use this when the author wants to see scoring results.

### Summary View

Present a high-level overview:
- Cycle number and date
- Number of scenes scored
- Overall average score across all principles
- Top 5 highest-scoring principles (with averages)
- Top 5 lowest-scoring principles (with averages)
- Any high-priority items from diagnosis.csv

### Scene Detail View

When the author asks about a specific scene:
- Show all principle scores for that scene
- Show rationale for each score from scene-rationale.csv
- Highlight scores below 4 (critical) and above 8 (excellent)
- Compare to the scene's intent from intent.csv -- are low scores aligned with the scene's purpose?

### Diagnosis and Proposals

Present the improvement cycle results:
- Show diagnosis.csv entries sorted by priority (high first)
- Show delta from previous cycle if available
- Present proposals from proposals.csv with their status
- Explain the rationale behind each proposal

### Exemplar Bank

If `working/exemplars.csv` exists, show high-scoring passages:
- List scenes that scored 9+ on any principle
- Group by principle to show what excellence looks like
- These exemplars can guide revision work

---

## Calibration Mode: Adjusting Weights

Use this when the author wants to change principle priorities.

### View Current Weights

Display `working/craft-weights.csv` showing:
- Each principle with its section, default weight, and author_weight (if set)
- Effective weight (author_weight overrides weight)
- Highlight where author_weight differs from default

### Set Author Weights

When the author says a principle matters more or less to them:
1. Confirm the principle name and desired weight (1-10 scale)
2. Update the `author_weight` column in `working/craft-weights.csv`
3. Explain how this affects scoring: higher weights make this principle count more in diagnosis priority

### Compare to Defaults

Show where the project's weights diverge from plugin defaults in `references/default-craft-weights.csv`.

---

## Author Scoring Mode: Providing Own Scores

Use this when the author wants to rate their own scenes.

### Record Author Scores

When the author provides a score for a scene+principle:
1. Confirm the scene ID, principle, and score (1-10)
2. Save to `scenes/author-scores.csv` using the same CSV format as scene-scores.csv
3. Show how the author's score compares to the system score

### View Author Deltas

If the author has provided scores:
- Compare author scores to system scores
- Show systematic biases (e.g., "system scores your dialogue 1.5 points higher than you do on average")
- These deltas help calibrate future scoring -- if the author consistently disagrees on a principle, that signals either the rubric needs adjustment or the author has a different aesthetic standard

---

## Run Mode: Triggering a Scoring Cycle

When the author says "run scoring" or "score my scenes":
1. Confirm the mode (grouped/quick/deep) and scope (all scenes, specific act, specific scenes)
2. Delegate to `./storyforge score` with the appropriate flags
3. After scoring completes, switch to Review mode to present results

---

## Step 4: Commit After Every Deliverable

**This step happens repeatedly throughout the session, not once at the end.**

Every time you modify weights, record author scores, or make any file changes, commit and push immediately.

**After each deliverable:**

1. Write the updated files (craft-weights.csv, author-scores.csv, etc.)
2. **Commit and push immediately:**
   ```
   git add -A && git commit -m "Score: {what was done}" && git push
   ```
   Examples: `"Score: adjust author weights for prose_craft principles"`, `"Score: record author scores for Act 1 scenes"`, `"Score: review cycle 3 results"`.

3. Then continue to the next piece of work.

## Coaching Level Behavior

Adapt your approach based on `project.coaching_level` in storyforge.yaml:

### `full` (default)
Proactively present scores, highlight patterns, and recommend weight adjustments. When showing diagnosis results, explain what each finding means for the manuscript and suggest concrete next steps. Offer to run scoring if results are stale.

### `coach`
Present scores when asked, but frame insights as questions: "Your dialogue scores are consistently lower than other principles -- do you think that reflects your intention, or is it something to work on?" Help the author think through weight calibration rather than recommending specific values.

### `strict`
Show data only. Present scores, deltas, and diagnosis without interpretation. Let the author draw their own conclusions about what matters. Record their weight choices and scores without comment. Do not recommend weight changes or interpret patterns.

---

## Craft Context

Reference these scoring concepts as needed:

- **Effective weight** = author_weight if set, otherwise the default weight. This determines how much a principle matters in diagnosis priority.
- **Diagnosis priority** = based on average score, regression from previous cycle, and effective weight. High priority means the principle needs attention.
- **Proposals** = suggested changes (weight adjustments, voice guide additions, scene-level overrides) based on diagnosis.
- **Tuning ledger** = history of all weight changes and their effects, used to detect validated patterns.
- **Exemplars** = passages scoring 9+ that demonstrate craft excellence, useful as reference during revision.
- **Author deltas** = systematic differences between system and author scores, revealing calibration gaps.
