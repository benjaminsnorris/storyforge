# Files Read

## Project Configuration
- `storyforge.yaml` -- project settings, phase (drafting), parts

## Reference CSVs (core analysis targets)
- `reference/scenes.csv` -- 6 scenes, seq 1-6, statuses from spine to briefed
- `reference/scene-briefs.csv` -- briefs for 4 of 6 scenes (new-x1 nearly empty, act2-sc01/act2-sc02 absent)
- `reference/scene-intent.csv` -- narrative dynamics for all 6 scenes

## Registry CSVs
- `reference/characters.csv` -- 4 characters (Dorren, Tessa, Kael, Pell)
- `reference/knowledge.csv` -- 5 knowledge tokens
- `reference/locations.csv` -- 4 locations
- `reference/mice-threads.csv` -- 3 MICE threads
- `reference/values.csv` -- 4 values at stake
- `reference/physical-states.csv` -- 4 physical states
- `reference/motif-taxonomy.csv` -- 5 motifs across 3 tiers

## Scene Prose
- `scenes/act1-sc01.md` -- single long paragraph, 2400 words claimed
- `scenes/act1-sc02.md` -- short drafted scene
- `scenes/act2-sc01.md` -- short pending scene
- `scenes/new-x1.md` -- short scene, POV mismatch with CSV

## Supporting Files
- `reference/voice-guide.md` -- prose style guidelines
- `working/evaluations/eval-test/findings.yaml` -- dev editor findings
- `working/pipeline.csv` -- 3 evaluation cycles in progress

# Proposed Actions

## CSV Edits (scene-briefs.csv)
1. **act1-sc01**: Reduce key_actions from 5 to 2-3. Replace key_dialogue literals with dialogue goals. Reduce emotions from 4 items to a trajectory phrase.
2. **act1-sc02**: Remove `exhaustion-tessa` from physical_state_out (Tessa not on stage). Reduce emotions from 4 to trajectory phrase.
3. **new-x1**: Fill empty brief fields -- goal, conflict, outcome, crisis, decision, knowledge_in, knowledge_out, key_actions. Currently nearly blank.
4. **act2-sc03**: Reduce key_actions from 5 to 2-3. Replace council dialogue literal with dialogue goal. Remove `exhaustion-tessa` from physical_state_in (Tessa not in scene). Reduce emotions from 4 to trajectory phrase.

## CSV Edits (scenes.csv or scene prose)
5. **new-x1**: Resolve POV mismatch -- scenes.csv says Kael Maren, prose uses Tessa. Either update CSV or redraft.

## No Script Delegation Proposed
All recommended actions are manual CSV edits or could be run through `storyforge-hone --domain briefs` for the concretization pass. No autonomous script invocation needed for the analysis phase.
