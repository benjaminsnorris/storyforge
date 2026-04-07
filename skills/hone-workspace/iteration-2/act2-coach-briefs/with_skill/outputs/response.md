# Hone: Briefs Domain -- Act 2 (Coach Mode)

I read your project state for **The Cartographer's Silence**. You want to hone briefs for act 2 scenes in coaching mode. Let me walk you through what I found.

## Act 2 Scenes

Your act 2 has three scenes:

| ID | Seq | Title | Status |
|----|-----|-------|--------|
| act2-sc01 | 4 | Into the Blank | architecture |
| act2-sc02 | 5 | First Collapse | spine |
| act2-sc03 | 6 | The Warning Ignored | briefed |

## Findings

### Critical: act2-sc01 and act2-sc02 have no briefs at all

These two scenes are missing entirely from `scene-briefs.csv`. They have intent data (function, emotional arc, value shifts) but no drafting contracts -- no goal, conflict, outcome, crisis, decision, key_actions, or any other brief fields.

This is expected given their status (`architecture` and `spine` respectively) -- they haven't reached the briefing stage yet. Before honing briefs, these scenes need briefs written via the elaboration pipeline.

**Recommendation:** Run `storyforge-elaborate --briefs --scenes act2-sc01,act2-sc02` to generate briefs for these scenes before honing.

### act2-sc03: "The Warning Ignored" -- Multiple Brief Quality Issues

This is the only act 2 scene with briefs. Here is what I found:

#### 1. Procedural Goal

**Current value:**
> Convince the council that the eastern anomalies require investigation

This frames the scene as a task to complete rather than a dramatic question. It will produce a scene that reads like a meeting agenda. A stronger goal would center the dramatic stakes.

**Suggested rewrite:**
> Force the council to acknowledge what Dorren knows they would rather ignore

**Reasoning:** This reframes from "complete a persuasion task" to "confront institutional denial," which is the real dramatic engine of the scene. The drafter opens with Dorren walking into a room where the outcome is almost certainly against her, rather than Dorren preparing a presentation.

#### 2. Over-Specified Key Actions (5 beats for 2,200 words)

**Current value:**
> Presents evidence;Council dismisses;Dorren argues;Is overruled;Meets Kael after

That is 5 key_actions for a 2,200-word scene -- one mandatory beat every 440 words. This leaves almost no room for atmosphere, interiority, or the kind of slow institutional suffocation that makes council scenes land.

**Suggested rewrite:**
> Presents evidence to skeptical council;Meets Kael privately after the dismissal

**Reasoning:** Two beats give the drafter room to find the scene's rhythm. The council dismissal and Dorren arguing are implicit in "skeptical council" -- the drafter will naturally dramatize that tension. The post-meeting Kael beat is the actual turning point and needs to stay explicit.

#### 3. Prescriptive Dialogue

**Current value:**
> Council: "We appreciate your diligence, Cartographer.";Dorren to Kael: "They won't look."

Both lines are exact quotes. The council line is particularly risky -- it forces a specific tone of polite dismissal that the drafter may need to arrive at differently depending on how the scene's argument unfolds.

**Suggested rewrite:**
> Council responds with institutional courtesy that reframes Dorren's evidence as procedural concern;Dorren tells Kael the council has chosen not to see

**Reasoning:** Dialogue direction preserves the emotional beats (patronizing dismissal, bitter resolve) without forcing exact wording. The drafter can find lines that emerge naturally from the scene's flow rather than contorting prose to deliver predetermined quotes.

#### 4. Emotional Arc Granularity (4 beats)

**Current value:**
> resolve;frustration;bitter-resignation;quiet-defiance

Four emotional beats force an artificial escalation-and-recovery pattern: Dorren enters resolved, gets frustrated, resigns herself, then defies. This is a full character arc compressed into a single scene.

**Suggested rewrite:**
> resolve;bitter-defiance

**Reasoning:** A two-beat arc (start state to end state) lets the drafter find the middle ground organically. Dorren walks in resolved and walks out bitterly defiant -- how she gets there is the craft of the scene.

#### 5. Physical State Tracking

**Current physical_state_in:** `archive-key-dorren;exhaustion-tessa`
**Current physical_state_out:** `archive-key-dorren`

Tessa's exhaustion is listed in the input state but Tessa is not in this scene (only Dorren, Council Members, and Kael). This looks like a data error carried forward. The physical state should only track characters who appear on stage.

**Suggested rewrite for physical_state_in:** `archive-key-dorren`
**Suggested rewrite for physical_state_out:** `archive-key-dorren`

---

## What Happens Next

Since we are in coach mode, I would save these proposals to `working/hone/briefs-act2-sc03.md` and walk through each one with you interactively:

- For each issue, I show you the current value and proposed change
- You tell me: accept, modify, or skip
- I apply only what you approve
- Then commit and push the changes

For act2-sc01 and act2-sc02, the right next step is elaboration (writing briefs), not honing (improving existing briefs). I can hand you off to the elaborate skill for that, or you can run:

```bash
cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && /Users/cadencedev/Developer/storyforge/scripts/storyforge-elaborate --briefs --scenes act2-sc01,act2-sc02
```

## Script Delegation

To run hone on act2-sc03's briefs in coaching mode:

**Option A: Run it here**
I'll walk through the proposals interactively in this conversation. For each field, you decide what lands. No API calls needed for coach mode -- I have the analysis ready.

**Option B: Run it yourself**
Copy this command and run it in a separate terminal:
```bash
cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && /Users/cadencedev/Developer/storyforge/scripts/storyforge-hone --domain briefs --act 2 --coaching coach
```
The script will save proposals to `working/hone/` without modifying CSVs. You can then review and apply them.

Which would you prefer?
