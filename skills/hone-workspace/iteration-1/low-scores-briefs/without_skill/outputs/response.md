# Brief Quality Analysis -- The Cartographer's Silence

You asked about low prose naturalness scores, and the briefs are a good place to look. After reading through your scene-briefs.csv alongside the actual prose and the evaluation findings, I can see several patterns that would directly push drafting toward stiff, over-determined writing.

## The Core Problem: Briefs That Over-Specify Beats

Your briefs for the two fully-specified scenes (act1-sc01 and act1-sc02) are extremely prescriptive in `key_actions` and `key_dialogue`. When Claude drafts against a brief that says:

> key_actions: Reviews maps;Finds anomaly;Consults Tessa;Files as error;Makes private note

...it tends to mechanically march through that checklist. The result reads like someone ticking boxes rather than a character living a scene. Your act1-sc01 prose is actually a single long paragraph -- it reads like it's trying to compress all five beats into a flowing passage, but the underlying structure is still "do thing 1, then thing 2, then thing 3."

Similarly, when `key_dialogue` prescribes exact lines:

> "The eastern readings are within acceptable variance"

...the drafter builds the scene around delivering that line rather than letting dialogue emerge from the dramatic situation. The line itself is good -- it fits the voice guide's "sparse and functional" mandate -- but locking it into the brief makes the surrounding prose contort to reach it.

## Specific Issues by Scene

### act1-sc01 (The Finest Cartographer)
- **5 key_actions for a 2,500-word scene** -- that's one mandatory beat every 500 words, leaving almost no breathing room for the "longer, winding sentences for description" your voice guide calls for.
- **Emotional arc is a 4-beat sequence** (competence;unease;self-doubt;resolve) -- this is a lot of emotional transitions for a single scene. The drafter tries to hit all four, which creates an artificial escalation-and-recovery pattern that reads as mechanical.
- **The crisis/decision pair is strong** but the goal ("Complete the quarterly pressure audit on schedule") is procedural, not dramatic. A drafter seeing that goal will front-load bureaucratic detail before getting to the actual story.

### act1-sc02 (The Missing Village)
- **key_actions again force a specific investigation sequence** (Cross-references maps; Discovers missing village; Searches removal logs; Finds nothing). This is detective-novel beat structure, and it makes the scene read like a procedural checklist.
- **physical_state_out references two states** (archive-key-dorren; exhaustion-tessa) but Tessa is not on_stage in this scene according to scene-intent.csv. The brief is asking the drafter to account for a character who isn't present -- this creates confusion or forced mention.
- **continuity_deps on act1-sc01** is correct and useful.

### new-x1 (The Archivist's Warning)
- **The brief is almost entirely empty.** Goal, conflict, outcome, crisis, decision, key_actions, key_dialogue, emotions, motifs -- all blank. Only physical_state_in and physical_state_out are populated (both "archive-key-dorren").
- The scene-intent.csv has good data for this scene, but without a brief, the drafter is flying blind on dramatic structure. The existing prose has Tessa as POV, but scenes.csv says Kael Maren is POV and intent has both Kael and Dorren on stage. The prose doesn't match the metadata at all.

### act2-sc01 and act2-sc02
- **No briefs exist at all** for these scenes. act2-sc01 has status "architecture" and act2-sc02 has status "spine" -- they haven't reached the briefing stage yet. This is expected and not a problem.

### act2-sc03 (The Warning Ignored)
- This scene has a solid brief. The key_actions are more narrative ("Presents evidence; Council dismisses; Dorren argues; Is overruled; Meets Kael after") and the dialogue quote captures institutional tone well. This is actually your best brief.
- One issue: physical_state_in references "archive-key-dorren;exhaustion-tessa" but the scene is Dorren's POV and exhaustion-tessa should have resolved before this scene (it's acquired in act1-sc02, set to resolve at act2-sc03, but Tessa isn't the POV character here).

## Recommendations

Here's what I'd suggest to improve brief quality and, downstream, prose naturalness:

### 1. Reduce key_actions to 3 per scene (max)
Keep only the structurally essential beats. Instead of "Reviews maps; Finds anomaly; Consults Tessa; Files as error; Makes private note," try: "Finds an anomaly in the eastern maps; Files it as instrument error; Keeps a private record." The drafter gets the story spine without the step-by-step choreography.

### 2. Move key_dialogue from exact quotes to dialogue direction
Instead of prescribing the line, describe what the dialogue needs to accomplish: "Dorren rationalizes the anomaly aloud, using institutional language." This lets the drafter find a natural voice for the moment.

### 3. Trim emotional arcs to 2 beats (start and end)
"Controlled competence to buried unease" is already in the scene-intent emotional_arc -- and it's better than the brief's 4-stage version. Let the drafter find the middle ground organically.

### 4. Fill the empty brief for new-x1
This scene has good intent data but zero brief data. At minimum it needs goal, conflict, outcome, and crisis. The POV mismatch between scenes.csv (Kael) and the existing prose (Tessa) also needs resolving.

### 5. Audit physical_state references across POV boundaries
The exhaustion-tessa state appearing in scenes where Tessa isn't POV or on-stage creates drafting confusion. Physical states should only appear in briefs for scenes where that character is present.

### 6. Make goals dramatic, not procedural
"Complete the quarterly pressure audit" is a task. "Prove the maps are accurate before the quarterly review deadline" puts the character's professional identity at stake. The goal shapes how the drafter opens the scene.

## Next Steps

You have two paths:

**Option A: I can draft revised briefs** for act1-sc01, act1-sc02, and new-x1 right now, applying these principles. You'd review them, and then we could re-draft those scenes against the improved briefs.

**Option B: Run storyforge-hone** with the briefs domain to get automated concretization and structural fixes:
```bash
cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && \
  /Users/cadencedev/Developer/storyforge/scripts/storyforge-hone --domain briefs
```
This would apply systematic fixes, though the judgment calls (like goal reframing and dialogue direction vs. exact quotes) would still need your input.

I'd recommend Option A first -- manual revision of the three problem briefs -- followed by Option B to catch any remaining structural issues. The prose naturalness improvement will come from giving the drafter more room to breathe within each scene's dramatic structure.
