Here is what I found looking at Act 2 briefs for **The Cartographer's Silence**.

Act 2 ("The Blank") has three scenes: `act2-sc01`, `act2-sc02`, and `act2-sc03`.

---

## Missing Briefs

Two of the three Act 2 scenes have **no brief data at all**:

| Scene | Title | Status | Brief Row? |
|-------|-------|--------|------------|
| act2-sc01 | Into the Blank | architecture | Missing entirely |
| act2-sc02 | First Collapse | spine | Missing entirely |
| act2-sc03 | The Warning Ignored | briefed | Present |

`act2-sc01` and `act2-sc02` have no rows in `scene-briefs.csv`. Before we can hone their briefs, we need to create them. Their statuses (`architecture` and `spine`) confirm they have not yet reached the briefing stage of the elaboration pipeline.

**What this means:** These two scenes need to go through elaboration (architecture through briefs) before hone can do anything useful with them. You could either elaborate them forward through the pipeline, or -- since `act2-sc01` already has draft prose in `scenes/act2-sc01.md` -- you could extract briefs from the existing prose instead.

---

## act2-sc03: Brief Quality Analysis

This is the only Act 2 scene with brief data. Here is what I found:

### Abstractness Check (key_actions, crisis, decision)

**key_actions:** `Presents evidence;Council dismisses;Dorren argues;Is overruled;Meets Kael after`

This is moderately abstract. "Presents evidence" and "Meets Kael after" lack physical specificity -- what does Dorren physically do when presenting? Does she unroll a map, point at coordinates, slide documents across a table? "Is overruled" is purely procedural. However, the beats are structurally sound -- five clear story events in the right sequence.

**crisis:** `Accept the council's dismissal and work within channels, or go outside the institution entirely`

This reads as a thematic summary rather than a dramatized moment. What does Dorren physically experience at the point of decision? Where is she standing? What is she looking at? What does she do with her hands?

**decision:** `Goes outside -- shares findings with Kael privately after the meeting`

Same issue -- this describes the outcome in narrative terms, not a physical beat.

Both `crisis` and `decision` would likely be flagged by hone's abstractness detector. They contain indicators like "accept" (abstract framing) and lack concrete physical indicators.

### Other Brief Fields

- **goal/conflict/outcome** are solid. The goal is specific ("Convince the council"), the conflict is concrete and interpersonal, the outcome is `no` (clean enum).
- **knowledge_in/knowledge_out** chain correctly from prior scenes: takes in `village-vanished;archive-erasure`, produces `council-dismisses-evidence`. All three are valid knowledge registry entries.
- **key_dialogue** is strong -- two concrete lines that carry the scene's tension.
- **emotions** (`resolve;frustration;bitter-resignation;quiet-defiance`) are well-sequenced and match the emotional arc in scene-intent.csv.
- **motifs** (`governance-as-weight;blindness/seeing`) match the motif taxonomy, though the canonical aliases are slightly different from the taxonomy IDs. `governance-as-weight` is an alias of the `governance` motif; `blindness/seeing` is an alias of the `blindness` motif. Hone's registry domain would normalize these to canonical IDs.
- **physical_state_in** (`archive-key-dorren;exhaustion-tessa`) -- `exhaustion-tessa` references Tessa, but this scene's POV is Dorren. This is valid if Tessa is on stage, but the `on_stage` column in scene-intent lists only `Dorren Hayle;Council Members`. Tessa is not present. This looks like a continuity error.
- **physical_state_out** (`archive-key-dorren`) -- drops the exhaustion-tessa state, which is correct if Tessa is not in the scene.
- **continuity_deps** (`act1-sc02;new-x1`) -- correct, these are the prior scenes that feed knowledge into this one.

---

## Recommended Next Steps

Since you asked for coaching mode, here are your options rather than my doing the work:

1. **Elaborate act2-sc01 and act2-sc02 through briefs first.** These scenes need goal/conflict/outcome/crisis/decision before hone can assess brief quality. Consider running `storyforge elaborate` targeted at these two scenes, or write the briefs manually.

2. **For act2-sc03, concretize the abstract fields.** The `crisis` and `decision` fields would benefit from rewriting as physical beats. Think about:
   - What is Dorren physically doing at the moment of decision? Is she still in the council chamber, or has she already left?
   - What does she see or hear that tips the scale?
   - What is the physical action that signals "I'm going outside channels" -- does she turn away from the chamber door, walk toward the archive wing, find Kael at his desk?

3. **Investigate the physical_state_in issue.** `exhaustion-tessa` is listed as a physical state entering act2-sc03, but Tessa does not appear to be on stage. Either:
   - Tessa should be added to the `on_stage` column in scene-intent.csv, or
   - `exhaustion-tessa` should be removed from physical_state_in for this scene.

4. **Normalize motif references.** `governance-as-weight` and `blindness/seeing` are aliases rather than canonical IDs. The registries domain of hone would fix these to `governance` and `blindness`.

Would you like to work on any of these?
