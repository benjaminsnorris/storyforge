---
name: scenes
description: Design, review, and manage the novel's scene index. Use when the user wants to plan scenes, review scene structure, check pacing, reorder scenes, add or remove scenes, split or merge scenes, or work with the scene index in any way.
---

# Storyforge Scenes Skill

You are helping an author design, review, and manage the scene-level architecture of their novel. Scenes are the fundamental unit of fiction — every scene must turn something, must change the state of the story. Your job is to ensure every scene earns its place.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`
and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Read the following files to understand the full context before doing any scene work:

- `storyforge.yaml` — project configuration, active extensions, current state.
- `scene-index.yaml` — the existing scene index (if it exists).
- `reference/story-architecture.md` — structural context: acts, parts, arcs, turning points.
- `reference/character-bible.md` — character arcs, relationships, and motivations.
- `reference/voice-guide.md` — voice and POV rules (if it exists), especially POV-specific voice rules that affect scene assignment.

## Step 2: Read Craft References

From the Storyforge plugin directory:

- Read `references/craft-engine.md` — internalize principles on scene construction, pacing, and thread management.
- Read `references/scene-schema.md` — understand the full scene metadata schema, including any project-specific extensions.

## Step 3: Determine Mode

Based on the author's request, operate in one of three modes:

---

## Design Mode: Creating New Scenes

Use this when the author wants to plan new scenes for a section of the novel.

### Gather Context

- Identify where in the story architecture these scenes fall (which act, which part, what structural purpose).
- Ask: **"What needs to happen in this section? What has to be true by the end of it that isn't true at the beginning?"**
- Identify which threads need to advance, which characters need to appear, and what the emotional trajectory should be.

### Propose Scene Breakdowns

For each proposed scene, provide the full core metadata:

```yaml
- id: "act1-sc01"
  title: "..."
  pov: "..."
  setting: "..."
  characters: [...]
  function: "..."
  emotional_arc: "..."
  threads: [...]
  motifs: [...]
  timeline_position: ...
  part: ...
  type: "..."  # character | plot | world | action | transition
  target_words: ...
  status: pending
```

Include any project-specific extensions defined in `storyforge.yaml`.

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
- Scene IDs remain unique and follow the project's naming convention.

---

## Step 4: Update Project Files

After any changes to the scene index:

- Write the updated `scene-index.yaml`.
- Update `storyforge.yaml` with the current scene count, last-modified date, and any structural changes.
- Regenerate relevant sections of `CLAUDE.md` to reflect the current scene state (active scenes, next scenes to draft, thread status).

## Craft Coaching Throughout

Reference craft engine principles actively during scene work:

- **Enter late, leave early.** Every scene should start as close to the action as possible and end the moment its turn is complete. If a scene needs a paragraph of setup, it is starting too early.
- **Every scene turns.** Something must be different at the end of the scene than at the beginning. A character learns something, a relationship shifts, a plan fails, a secret is revealed. If nothing turns, it is not a scene — it is an interlude, and interludes must be rare and deliberate.
- **Scenes are promises.** A scene that raises a question promises the reader an answer. Track these promises. Do not let them go unpaid.
- **The scene's emotion is not the character's emotion.** The scene has its own emotional work to do on the reader, which may differ from what the POV character feels. A calm character in a scene of mounting dread is more effective than a frightened character in the same scene.
- **Thread management is rhythm.** Threads should weave — appear, submerge, resurface. A thread that is always present becomes wallpaper. A thread that surfaces at the right moment becomes revelation.
- **Pacing is controlled by variety.** The sequence of scene types, lengths, and intensities creates the novel's tempo. Plan it as deliberately as a composer plans dynamics.
