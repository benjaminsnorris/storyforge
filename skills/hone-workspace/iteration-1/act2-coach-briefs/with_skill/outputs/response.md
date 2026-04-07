# Hone: Briefs for Act 2 Scenes (Coach Mode)

## Project State

**The Cartographer's Silence** -- fantasy, secondary world. Currently in drafting phase.

Act 2 ("The Blank") contains three scenes:

| ID | Seq | Title | Status | Brief? |
|----|-----|-------|--------|--------|
| act2-sc01 | 4 | Into the Blank | architecture | Missing |
| act2-sc02 | 5 | First Collapse | spine | Missing |
| act2-sc03 | 6 | The Warning Ignored | briefed | Present |

## Assessment

Two of your three Act 2 scenes have **no briefs at all**. Before we can concretize anything, those briefs need to exist. Here is what I found:

### act2-sc01 ("Into the Blank")
- **No row in scene-briefs.csv.** Status is "architecture" -- this scene hasn't reached the briefs stage yet.
- Intent data exists: Tessa and Pell explore the eastern damage, professional detachment gives way to visceral shock. Value at stake is safety, shifting from positive to negative.
- This scene needs elaboration through the briefs stage before hone can work on it.

### act2-sc02 ("First Collapse")
- **No row in scene-briefs.csv.** Status is "spine" -- this scene is even earlier in the pipeline.
- Intent data exists: the ridge collapses, Tessa barely escapes. Determination to terror. Life at stake.
- This scene needs elaboration through architecture and then briefs before hone can touch it.

### act2-sc03 ("The Warning Ignored")
- **Brief exists and is fairly concrete.** Let me walk through the fields:
  - **goal:** "Convince the council that the eastern anomalies require investigation" -- clear and specific.
  - **conflict:** "Council members see the anomaly as Dorren's procedural fixation, not evidence of erasure" -- good, names the specific dismissal.
  - **outcome:** "no" -- clean outcome type.
  - **crisis:** "Accept the council's dismissal and work within channels, or go outside the institution entirely" -- concrete fork.
  - **decision:** "Goes outside -- shares findings with Kael privately after the meeting" -- specific action.
  - **knowledge_in:** "village-vanished;archive-erasure" -- registry tokens, good.
  - **knowledge_out:** "council-dismisses-evidence" -- clean.
  - **key_actions:** "Presents evidence;Council dismisses;Dorren argues;Is overruled;Meets Kael after" -- five concrete beats, nicely sequenced.
  - **key_dialogue:** Two lines, both grounded and character-specific.
  - **emotions:** "resolve;frustration;bitter-resignation;quiet-defiance" -- four-beat arc, no abstract filler.
  - **motifs:** "governance-as-weight;blindness/seeing" -- thematic, tied to the scene's content.
  - **physical_state_in:** "archive-key-dorren;exhaustion-tessa" -- note that Tessa is not on_stage for this scene (only Dorren, Council Members), so "exhaustion-tessa" is tracking offstage state, which is fine for continuity but worth being aware of.
  - **physical_state_out:** "archive-key-dorren" -- Dorren retains the key, exhaustion-tessa drops (she's not present).

**This brief is already reasonably concrete.** The key_actions are physical beats, the crisis is a genuine fork, and the dialogue samples are grounded. I would not flag this as needing concretization.

## Recommendation

Here is what I'd suggest, and I want your input on how to proceed:

1. **act2-sc01 and act2-sc02 need briefs first.** Hone works on existing briefs -- it cannot create them. These scenes need to go through the elaboration pipeline. Would you like to run `elaborate` on these two scenes to generate their briefs?

2. **act2-sc03's brief looks solid.** There are no abstract indicators I'd flag (no vague "explores themes" or "character development occurs" language). The five key_actions are physical beats, the crisis is a real fork, the dialogue is specific.

   If you want, I can look more closely at any specific field -- for example, whether the motifs could be grounded in more physical imagery, or whether the emotional arc could be sharpened.

3. **One small continuity note on act2-sc03:** The physical_state_in includes "exhaustion-tessa" but Tessa is not on_stage for this scene. This is likely tracking offstage state for continuity purposes (she was just in act2-sc01 and act2-sc02), but if you intended it to describe Dorren's physical state going in, that field is currently empty for Dorren.

## Available Commands

If you decide to elaborate the missing briefs first, then come back for hone:

```bash
cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && /Users/cadencedev/Developer/storyforge/scripts/storyforge-elaborate --stage briefs --scenes act2-sc01,act2-sc02
```

If you want to run hone on act2-sc03 specifically (the one scene with a brief):

```bash
cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && /Users/cadencedev/Developer/storyforge/scripts/storyforge-hone --domain briefs --scenes act2-sc03 --coaching coach --dry-run
```

The `--dry-run` flag will show what would be flagged without making changes. Remove it when you are ready to proceed.

What would you like to do?
