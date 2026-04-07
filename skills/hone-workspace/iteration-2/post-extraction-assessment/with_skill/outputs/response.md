# Post-Extraction Data Quality Assessment

**The Cartographer's Silence** -- 6 scenes, 14,000 target words

Good timing to check. Extraction populated a lot of your CSVs, but there are clear quality issues to address before you draft. Here is what I found across the four hone domains:

---

## 1. Gaps -- Missing Fields

This is the biggest issue. Two scenes have significant gaps:

**new-x1 (The Archivist's Warning)** -- almost entirely empty in scene-briefs.csv:
- Missing: goal, conflict, outcome, crisis, decision, knowledge_in, knowledge_out, key_actions, key_dialogue, emotions, motifs, continuity_deps
- This scene has only `physical_state_in` and `physical_state_out` populated
- In scene-intent.csv it looks better (function, action_sequel, emotional_arc, value_at_stake, value_shift, turning_point, characters, on_stage, mice_threads are all filled)

**act2-sc01 (Into the Blank)** and **act2-sc02 (First Collapse)** -- entirely missing from scene-briefs.csv:
- No rows at all for these two scenes
- They exist in scenes.csv and scene-intent.csv, but briefs were never extracted or created

**Summary:** 3 of 6 scenes have no usable briefs. You cannot draft those scenes without briefs.

## 2. Brief Quality Issues (3 scenes with briefs)

### Abstract Language

Several fields use narrator-voice descriptions instead of concrete physical action:

- **act1-sc01** `emotions`: "competence;unease;self-doubt;resolve" -- this is a 4-beat arc (see below)
- **act1-sc02** `emotions`: "routine;confusion;dread;determination" -- another 4-beat arc
- **act2-sc03** `emotions`: "resolve;frustration;bitter-resignation;quiet-defiance" -- 4-beat arc

### Over-Specified Beats

- **act1-sc01** has 5 key_actions ("Reviews maps;Finds anomaly;Consults Tessa;Files as error;Makes private note") for a 2,500-word scene. That is one mandatory beat every 500 words -- too tight. No room for atmosphere or interiority. Should be 2-3 actions.
- **act1-sc02** has 4 key_actions for 3,000 words -- borderline acceptable but still prescriptive.
- **act2-sc03** has 5 key_actions for 2,200 words -- even worse ratio than act1-sc01. One beat every 440 words.

### Prescriptive Dialogue

- **act1-sc01** has exact quoted dialogue: `"The eastern readings are within acceptable variance"` and `"Acceptable is not the same as explained"`. These will force the drafter to contort prose around specific lines.
- **act1-sc02** has an exact quote: `"It was there forty years ago. It isn't there now. There is no note."` -- evocative, but prescriptive.
- **act2-sc03** has exact quotes from the Council and Dorren-to-Kael.

Better to use dialogue direction (e.g., "Dorren rationalizes the anomaly using institutional language") than exact lines.

### Emotional Arc Granularity

All three populated briefs have 4-beat emotional arcs:
- act1-sc01: competence -> unease -> self-doubt -> resolve
- act1-sc02: routine -> confusion -> dread -> determination
- act2-sc03: resolve -> frustration -> bitter-resignation -> quiet-defiance

Four beats force artificial escalation-and-recovery. A 2-beat arc (start state -> end state) lets the drafter find the emotional middle ground organically. Recommended: trim each to 2 beats (e.g., "competence;unease" for act1-sc01).

### Procedural Goals

- **act1-sc01**: "Complete the quarterly pressure audit on schedule" -- this is a task, not a dramatic question. It will produce a bureaucratic scene opening. Better: "Prove the maps are accurate before the review deadline" or "Maintain her reputation by delivering clean results."

## 3. Registries -- In Good Shape

Registries exist and look reasonable:
- **characters.csv**: 4 entries with aliases -- looks clean
- **locations.csv**: 4 entries with aliases -- looks clean
- **values.csv**: 4 entries (truth, safety, life, justice)
- **knowledge.csv**: 5 knowledge items with aliases
- **mice-threads.csv**: 3 threads
- **motif-taxonomy.csv**: 5 motifs with tiers
- **physical-states.csv**: 4 states with gating info

One normalization issue: scenes.csv uses "Pressure Cartography Office" but locations.csv has it as an alias (canonical name is also "Pressure Cartography Office") -- that is fine. However, scenes.csv location for act2-sc01 is "The Uncharted Reaches" while the canonical name in locations.csv is "Uncharted Reaches" (without "The"). Minor inconsistency to clean up.

Also: `physical_state_in` for act2-sc03 lists "archive-key-dorren;exhaustion-tessa" but exhaustion-tessa resolves at act2-sc03 per the physical-states registry. The `physical_state_out` only shows "archive-key-dorren", which is correct. This looks consistent.

However, new-x1's briefs row has `physical_state_in` = "archive-key-dorren" and `physical_state_out` = "archive-key-dorren", but new-x1 is seq 3 and archive-key-dorren is acquired at act1-sc02 (seq 2). The gating flag is true, so this should carry forward -- but new-x1 lists archive-key-dorren as physical_state_in, meaning Dorren has the key when she enters the Archivist scene. That seems intentional.

## 4. Structural Issues

- **act2-sc01** and **act2-sc02** have early pipeline statuses ("architecture" and "spine" respectively). These scenes have intent data but no briefs at all. Extraction may not have reached them, or they were added after the scene map stage.
- **new-x1** is at "mapped" status with nearly empty briefs -- it needs elaboration or a second extraction pass.

---

## Recommendations

Here is what I would prioritize, in order:

1. **Fill gaps first** -- The 3 scenes without briefs are the critical blocker. Run `storyforge-elaborate --gap-fill` or the hone gaps domain to populate them.

2. **Concretize the 3 existing briefs** -- Fix abstract language, trim key_actions to 2-3 per scene, replace exact dialogue with dialogue direction, and compress emotional arcs to 2 beats.

3. **Registry normalization** -- Minor. Clean up the "The Uncharted Reaches" vs "Uncharted Reaches" inconsistency in scenes.csv.

Want me to run hone on a specific domain? I would suggest starting with gaps to get the missing briefs populated, then following up with briefs concretization. Here are the commands:

**Option A: Run it here**
I will launch the hone script in this conversation to fill gaps first, then concretize briefs. This requires Claude API calls.

**Option B: Run it yourself**
```bash
# Step 1: Fill gaps
cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && /Users/cadencedev/Developer/storyforge/scripts/storyforge-hone --domain gaps

# Step 2: Concretize briefs (after gaps are filled)
cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && /Users/cadencedev/Developer/storyforge/scripts/storyforge-hone --domain briefs

# Or do everything at once:
cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && /Users/cadencedev/Developer/storyforge/scripts/storyforge-hone
```
