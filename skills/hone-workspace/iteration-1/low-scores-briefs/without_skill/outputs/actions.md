# Files Read

## Project Configuration
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/storyforge.yaml` -- project metadata, phase, parts

## CSV Data (Reference)
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/scenes.csv` -- 6 scenes, structural identity
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/scene-briefs.csv` -- 4 briefs (2 fully populated, 1 empty, 1 solid; 2 scenes have no brief rows)
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/scene-intent.csv` -- 6 scenes, narrative dynamics
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/characters.csv` -- 4 characters
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/locations.csv` -- 4 locations
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/knowledge.csv` -- 5 knowledge tokens
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/values.csv` -- 4 values
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/physical-states.csv` -- 4 physical states
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/mice-threads.csv` -- 3 MICE threads
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/motif-taxonomy.csv` -- 5 motifs
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/voice-guide.md` -- voice and prose style guide

## Scene Prose
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/scenes/act1-sc01.md` -- 1 paragraph, single block of prose
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/scenes/act1-sc02.md` -- short scene with dialogue
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/scenes/act2-sc01.md` -- short scene, pending status
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/scenes/new-x1.md` -- short scene, POV mismatch with metadata

## Evaluations
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/working/evaluations/eval-test/findings.yaml` -- 4 findings
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/working/evaluations/eval-test/synthesis.md` -- evaluation summary

# Issues Identified

1. **Over-specified key_actions** -- act1-sc01 has 5 mandatory beats for 2,500 words; act1-sc02 has 4. This forces mechanical beat-by-beat drafting.
2. **Exact dialogue in key_dialogue** -- prescribing lines rather than dialogue direction constrains the drafter's voice.
3. **4-stage emotional arcs** -- too many emotional transitions for single scenes; creates artificial escalation patterns.
4. **Empty brief for new-x1** -- scene has intent data but zero brief data; POV mismatch between scenes.csv (Kael) and prose (Tessa).
5. **Cross-POV physical state references** -- exhaustion-tessa appears in briefs for scenes where Tessa isn't POV or on-stage.
6. **Procedural goals** -- "Complete the quarterly pressure audit on schedule" is a task, not a dramatic goal.
7. **Missing briefs for act2-sc01 and act2-sc02** -- expected (not yet at briefing stage), but noted.

# Proposed Actions

1. **Reduce key_actions to max 3 per scene** -- keep only structurally essential beats
2. **Convert key_dialogue from exact quotes to dialogue direction** -- describe what dialogue must accomplish, not exact lines
3. **Trim emotional arcs to 2 beats** (start state, end state) -- let drafter find the middle
4. **Fill the empty new-x1 brief** -- at minimum: goal, conflict, outcome, crisis
5. **Resolve new-x1 POV mismatch** -- scenes.csv says Kael, prose has Tessa
6. **Audit physical_state references** -- remove states for characters not present in scene
7. **Reframe procedural goals as dramatic goals** -- put character identity/stakes in the goal statement
8. **Option A (recommended): Manual brief revision** for act1-sc01, act1-sc02, new-x1
9. **Option B: Run storyforge-hone --domain briefs** for automated structural fixes
