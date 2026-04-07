Good question. Let me look at your CSV data quality after the extraction.

**Project:** The Cartographer's Silence (6 scenes, 2 parts)

Here is the post-extraction assessment across the four hone domains:

---

## 1. Gaps -- the most urgent issue

Your extraction left significant holes. Here is the breakdown:

**scene-briefs.csv:**
- **new-x1 ("The Archivist's Warning")** is almost entirely empty. It has no goal, conflict, outcome, crisis, decision, knowledge_in, knowledge_out, key_actions, key_dialogue, emotions, or motifs. Only `physical_state_in` and `physical_state_out` are populated (both with `archive-key-dorren`).
- **act2-sc01 ("Into the Blank")** and **act2-sc02 ("First Collapse")** have no rows at all in scene-briefs.csv. They exist in scenes.csv and scene-intent.csv but are completely missing from briefs.

That means 3 of your 6 scenes (50%) have no usable brief data. Drafting those scenes without briefs will produce loose, undirected prose.

**scene-intent.csv:**
- **act1-sc02** has an empty `mice_threads` field. Given that this scene opens the archive-erasure inquiry thread, that seems like a gap rather than an intentional omission.

**scenes.csv:**
- All scenes have `word_count: 0`, which is expected post-extraction if you have not yet drafted.
- **act2-sc01** has status `architecture` and **act2-sc02** has status `spine` -- these are earlier pipeline stages than the other scenes. They may not have been fully extracted.

## 2. Registries -- in decent shape

Your extraction built out the registries, and they look reasonably complete:

- **characters.csv:** 4 characters with aliases. Looks consistent with who appears in scenes.
- **locations.csv:** 4 locations with aliases. One note: `Eastern Ridge` (act2-sc02 location) does not appear in locations.csv. That is a normalization gap.
- **knowledge.csv:** 5 knowledge beats, well-structured with aliases.
- **values.csv:** 4 values with aliases.
- **mice-threads.csv:** 3 threads. Types look correct (2 inquiry, 1 milieu).
- **physical-states.csv:** 4 entries. Note: `exhaustion-tessa` has `acquired: act1-sc02` but Tessa is not listed as `on_stage` in act1-sc02's intent row (only Dorren is). This may be a data inconsistency from extraction.
- **motif-taxonomy.csv:** 5 motifs across 3 tiers.

The `acceptable-variance` alias under the `water` motif is odd -- "acceptable variance" is a phrase Dorren uses about map readings, not obviously water-related. Worth reviewing.

## 3. Structural issues

No scoring data exists yet (`working/scores/` is empty), and there are no structural proposals to act on. However, I can flag some structural concerns visible from the raw data:

- **Chapter map is incomplete.** Only 2 chapters are mapped, covering scenes act1-sc01, act1-sc02, and act2-sc01. Scenes new-x1, act2-sc02, and act2-sc03 are not assigned to any chapter.
- **Status inconsistency.** Scenes range from `spine` to `briefed` in status, which suggests the extraction pipeline did not complete uniformly across all scenes.

## 4. Brief quality (for scenes that have briefs)

Looking at the 3 scenes that do have brief data (act1-sc01, act1-sc02, act2-sc03):

These briefs are actually quite concrete. Key actions are physical verbs ("Reviews maps; Finds anomaly; Consults Tessa"), key dialogue has actual quoted lines, and the crisis/decision fields describe specific behavioral choices rather than abstract themes. I would not flag any of these for concretization.

---

## Recommendation

Given the state of things, I would prioritize in this order:

1. **Fill gaps first** -- the 3 scenes with missing/empty briefs are the critical problem. Without briefs, everything downstream (drafting, scoring, revision) suffers. Run `storyforge-hone --domain gaps` or, since these are substantial gaps rather than individual missing fields, it may be better to run the elaboration pipeline on just those scenes: `storyforge-elaborate --stages briefs --scenes new-x1,act2-sc01,act2-sc02`.

2. **Registries cleanup** -- add Eastern Ridge to locations.csv, verify the `exhaustion-tessa` acquisition scene, and review the `acceptable-variance` motif alias. You could run `storyforge-hone --domain registries` for this, or these are small enough to fix by hand.

3. **Chapter map** -- assign the unmapped scenes to chapters. This is a `storyforge-elaborate` or manual task, not a hone task.

4. **Scoring** -- once gaps are filled, run `storyforge-score` to establish a baseline, then hone can work from the scoring data for any brief concretization or structural fixes.

Want me to tackle the gap filling first? I can run the hone script or elaborate pipeline for the missing scenes.
