---
name: scenes
description: Design, review, and manage the novel's scene index. Use when the user wants to plan scenes, review scene structure, check pacing, reorder scenes, add or remove scenes, split or merge scenes, or work with the scene index in any way.
---

# Storyforge Scenes Skill

**Scene philosophy:** A scene is a single continuous pass of experience — one camera angle. Not a mini-chapter. Scenes can be a single paragraph or many pages. They are designed to be reshuffled freely; order lives in the index, not the filename.

You are helping an author design, review, and manage the scene-level architecture of their novel. Scenes are the fundamental unit of fiction — every scene must turn something, must change the state of the story. Your job is to ensure every scene earns its place.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`
and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Read the following files to understand the full context before doing any scene work:

- `storyforge.yaml` — project configuration, active extensions, current state. **Note the `project.coaching_level` field** — it controls how proactive you should be (see Coaching Level Behavior below).
- `scenes/metadata.csv` — the existing scene metadata (pipe-delimited CSV: `id|seq|title|pov|setting|part|type|timeline_day|time_of_day|status|word_count|target_words`). If this does not exist, fall back to `scene-index.yaml` for legacy projects.
- `scenes/intent.csv` — scene intent data (pipe-delimited CSV: `id|function|emotional_arc|characters|threads|motifs|notes`). Array fields use `;` (semicolon) as the internal separator.
- `reference/story-architecture.md` — structural context: acts, parts, arcs, turning points.
- `reference/character-bible.md` — character arcs, relationships, and motivations.
- `reference/voice-guide.md` — voice and POV rules (if it exists), especially POV-specific voice rules that affect scene assignment.

## Step 2: Read Craft References

From the Storyforge plugin directory:

- Read `references/craft-engine.md` — internalize principles on scene construction, pacing, and thread management.
- Read `references/scene-schema.md` — understand the full scene metadata schema, including any project-specific extensions.

## Step 3: Determine Mode

**If invoked with specific direction** (e.g., "design scenes for Act 2" or "review pacing in Act 1"), go directly to the appropriate mode and execute. Do not ask clarifying sub-questions — make the creative calls and produce work.

**If invoked without direction** (e.g., via hub routing or "surprise me"), assess the scene index state and execute the highest-impact work: if no scenes exist, enter Design mode for the opening act; if scenes exist but have gaps, enter Review mode and identify what needs attention; if the author has flagged specific changes, enter Edit mode.

Based on the direction (given or self-determined), operate in one of three modes:

---

## Design Mode: Creating New Scenes

Use this when the author wants to plan new scenes for a section of the novel.

### Gather Context

- Identify where in the story architecture these scenes fall (which act, which part, what structural purpose).
- Determine what needs to happen in this section — what must be true by the end that isn't true at the beginning. Use the story architecture, character arcs, and thread requirements to answer this yourself.
- Identify which threads need to advance, which characters need to appear, and what the emotional trajectory should be.

### Propose Scene Breakdowns

For each proposed scene, present the full core metadata. Scene data is stored in two CSV files:

**`scenes/metadata.csv`** — one row per scene (pipe-delimited):
```
id|seq|title|pov|setting|part|type|timeline_day|time_of_day|status|word_count|target_words
geometry-of-dying|1|The Geometry of Dying|Character Name|Location|1|character|1|morning|pending|0|2500
```

**`scenes/intent.csv`** — one row per scene (pipe-delimited, arrays use `;`):
```
id|function|emotional_arc|characters|threads|motifs|notes
geometry-of-dying|Specific function description|Emotional start to end|Char A;Char B|thread-1;thread-2|motif-1;motif-2|
```

**Scene files are pure prose** — no YAML frontmatter. The filename is the scene ID (e.g., `scenes/geometry-of-dying.md`). All metadata lives in the CSV files, not in the scene files.

**Scene ID naming:** Generate slugs from the scene title — e.g., "The Geometry of Dying" → `geometry-of-dying`. Never use numeric or positional IDs like `act1-sc01` or `scene-07`. Keep slugs to 2–5 hyphenated words. Slugs are permanent identifiers; order lives in `metadata.csv` (the `seq` column), not the filename.

Include any project-specific extensions defined in `storyforge.yaml` as additional columns in `metadata.csv`.

### Challenge Rigorously

**Challenge vague functions.** A scene's function must be specific and testable. Push back on categorical descriptions:
- "Advance the romance" — that is a category, not a function. What specifically changes between these two people? What does one of them learn, reveal, or lose?
- "Establish the world" — what specific aspect of the world, and why does the reader need it now? What decision or action does this worldbuilding enable later?
- "Build tension" — tension toward what? What is the reader afraid of, and what in this scene makes that fear sharper?

A good function statement can be tested: after reading the scene, you can ask "Did this happen?" and get a yes or no.

**Challenge pacing.** Read the proposed sequence as a whole:
- Five rising-action scenes in a row — where is the breath? Where does the reader metabolize?
- Three character scenes back-to-back — the reader needs something to happen.
- An action scene immediately after another action scene — adrenaline has diminishing returns.
- Vary scene types deliberately. The rhythm of types IS the pacing.

**Ensure thread coverage.** Check all major threads against the proposed scenes:
- Are all active threads being advanced across the sequence?
- Is any thread going dormant for too long? (More than 8-10 scenes without a touch risks the reader forgetting.)
- Are threads being introduced too close together? (Give each thread room to establish before the next arrives.)

**Check POV distribution:**
- Is one POV dominating the sequence? Is that intentional?
- Is the POV rotation serving the story, or is it mechanical? (Rotating for rotation's sake is not a reason.)
- Does each POV shift earn its cut? The reader should want to be in the new POV, not resent leaving the old one.

---

## Review Mode: Analyzing Existing Scenes

Use this when the author wants to understand the current state of their scene index.

### Display Stats

Present a clear statistical overview:
- Total scene count
- Scenes by part/act
- Total target word count (and by part/act)
- POV distribution (scenes per POV character, word count per POV)
- Scene type distribution (character / plot / world / action / transition)
- Status breakdown (pending / drafted / revised / polished / cut)

### Analyze Pacing

- Map scene types over time — show the rhythm of the novel as a sequence.
- Identify the emotional arc shape: where are the peaks, valleys, and sustained tensions?
- Flag monotonous stretches: too many scenes of the same type in a row.
- Check act/part boundaries: do they fall at natural turning points?

### Check Thread Coverage

- For each major thread, list every scene where it appears.
- Flag threads that go dormant for 10+ scenes without being touched.
- Flag threads that appear only once or twice — are they real threads or abandoned ideas?
- Identify which threads converge and where — are the convergence points strong enough?

### Flag Issues

Identify and report:
- Scenes without a clear, specific function.
- POV imbalances that do not appear intentional.
- Timeline gaps or inconsistencies.
- Scenes marked as a type that does not match their function.
- Clusters of very short or very long scenes that may indicate pacing problems.
- Characters who appear in the character bible but never appear in scenes (or appear too rarely for their stated importance).

---

## Edit Mode: Modifying Scenes

Use this when the author wants to change the scene index.

### Reorder

- Move scenes within the index.
- After reordering, check: Does the new order preserve causality? Does the timeline still work? Does the emotional arc still build correctly?

### Split

- Break one scene into two (or more).
- Guide the split: Where is the natural break point? Usually where the scene's energy shifts — a new character enters, the location changes, the emotional register pivots.
- Ensure both resulting scenes have clear, distinct functions. If you cannot articulate two separate functions, the scene should not be split.

### Merge

- Combine adjacent scenes into one.
- Guide the merge: What is the unified function? Which scene's opening is stronger? Which scene's closing is stronger?
- Watch for bloated scenes — if the merged scene exceeds 4,000-5,000 target words, consider whether a merge is the right move.

### Add

- Insert new scenes at any position in the index.
- Full metadata required (same as Design mode).
- Validate that the new scene does not duplicate an existing scene's function.

### Remove

- **Never delete scenes from the index.** Mark their status as `"cut"` and add a `cut_reason` field.
- Cut scenes are valuable — they record what the author considered and rejected, which prevents re-litigating the same ideas.

### Post-Edit Validation

After any edit, run validation checks:
- No orphaned threads (a thread introduced in a scene that was cut but never picked up elsewhere).
- No POV gaps (a POV character who disappears from the rotation unexpectedly).
- Reasonable pacing (no new monotonous stretches created by the edit).
- Timeline consistency (especially after reordering).
- Scene IDs remain unique and use descriptive slugs (e.g., `geometry-of-dying`), never numeric or positional IDs.
- The `seq` column in `metadata.csv` is consistent with the intended scene order.

---

## Step 4: Commit After Every Deliverable

**This step happens repeatedly throughout the session, not once at the end.**

Every time you add, modify, or remove scenes — an act designed, scenes reordered, a split or merge applied — you must commit and push before moving on to the next piece of work. The repo is the source of truth. If the session crashes or the author checks from another machine, the repo must reflect every scene decision that has been made.

**After each deliverable:**

1. Write the updated `scenes/metadata.csv` and `scenes/intent.csv`. If the project still has a legacy `scene-index.yaml`, you may update it for backward compatibility, but the CSV files are the canonical source.
2. Update `storyforge.yaml` with the current scene count, last-modified date, and any structural changes. If scenes were added and the project phase is still `development`, advance it to `scene-design`.
3. Regenerate relevant sections of `CLAUDE.md` to reflect the current scene state (active scenes, next scenes to draft, thread status).
4. **Commit and push immediately:**
   ```
   git add -A && git commit -m "Scenes: {what was done}" && git push
   ```
   Examples: `"Scenes: design Act 1 scene breakdown (8 scenes)"`, `"Scenes: split geometry-of-dying into two scenes"`, `"Scenes: reorder Act 2 for better pacing"`.

5. Then continue to the next piece of scene work.

**Commit cadence:** If designing scenes for a full novel, commit after each act's scenes are designed. If doing a review, commit after each batch of edits. If splitting/merging, commit after each structural change. Do not wait until all scene work is complete.

## Step 5: Create Drafting Branch When Scene Design Is Complete

When scene design is finished and the author is ready to start drafting, create a feature branch so that all drafting work lives on a branch. Execute these steps **in this exact order**. Do not write any files before step 2 is complete.

**1. Create the feature branch.** This must happen first, before any file is written or modified:
```bash
git checkout -b "storyforge/write-$(date '+%Y%m%d-%H%M')"
```

**2. Verify you are on the new branch** before proceeding:
```bash
git rev-parse --abbrev-ref HEAD
```
The output must start with `storyforge/write-`. If it does not, stop and fix the branch before writing any files.

**3. Commit the scene index on the branch:**
```bash
git add -A && git commit -m "Scenes: ready for drafting" && git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
```

Tell the author: the scene index is ready and a drafting branch has been created. Run `./storyforge write` to begin autonomous drafting, or `./storyforge write --interactive` to draft with hands-on supervision.

**When to create the branch:** Only when the author signals they are done with scene design and ready to draft. Do not create the branch during iterative scene design work — those commits belong on main. The branch is created at the transition from design to drafting.

## Coaching Level Behavior

Adapt your approach based on `project.coaching_level` in storyforge.yaml:

### `full` (default)
Proactively design scene breakdowns — propose full metadata for each scene including function, emotional arc, threads, and motifs. Make creative decisions about POV assignment, scene ordering, and type distribution. Present complete scene cards and let the author refine. When designing an act, generate the full set of scenes with all metadata filled in.

### `coach`
Ask what needs to happen in each section and help the author work through scene design, but don't generate full scene cards unprompted. Ask: "What needs to be true by the end of this act?" "Which character's perspective serves this moment best?" Help them structure their thinking, then let them fill in the scene metadata. Offer options when the author is stuck, but frame them as questions, not proposals.

### `strict`
Ask structural questions — do not propose creative content. Ask: "How many scenes do you think this section needs?" "What is the function of each scene?" "Which threads need to advance here?" Do not propose scene breakdowns, POV assignments, or type distributions. The author makes every creative decision.

You CAN do the menial work: once the author decides on a scene's function, POV, threads, etc., you create the scene entry in `metadata.csv` and `intent.csv`, fill in the metadata, and commit. You handle the files — they handle the ideas.

---

## Craft Coaching Throughout

Reference craft engine principles actively during scene work:

- **Enter late, leave early.** Every scene should start as close to the action as possible and end the moment its turn is complete. If a scene needs a paragraph of setup, it is starting too early.
- **Every scene turns.** Something must be different at the end of the scene than at the beginning. A character learns something, a relationship shifts, a plan fails, a secret is revealed. If nothing turns, it is not a scene — it is an interlude, and interludes must be rare and deliberate.
- **Scenes are promises.** A scene that raises a question promises the reader an answer. Track these promises. Do not let them go unpaid.
- **The scene's emotion is not the character's emotion.** The scene has its own emotional work to do on the reader, which may differ from what the POV character feels. A calm character in a scene of mounting dread is more effective than a frightened character in the same scene.
- **Thread management is rhythm.** Threads should weave — appear, submerge, resurface. A thread that is always present becomes wallpaper. A thread that surfaces at the right moment becomes revelation.
- **Pacing is controlled by variety.** The sequence of scene types, lengths, and intensities creates the novel's tempo. Plan it as deliberately as a composer plans dynamics.
