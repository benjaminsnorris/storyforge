I looked at your Act 2 scenes and their brief data. Here is what I found.

## Act 2 Scenes

Your project has three scenes in Part 2 ("The Blank"):

| ID | Title | Status | Has Brief? |
|----|-------|--------|------------|
| act2-sc01 | Into the Blank | architecture | No |
| act2-sc02 | First Collapse | spine | No |
| act2-sc03 | The Warning Ignored | briefed | Yes |

## Brief Quality Analysis: act2-sc03

Only **act2-sc03** has brief data. The other two scenes have not reached the briefed stage yet (act2-sc01 is at architecture, act2-sc02 is at spine), so there is nothing to hone for those.

Here is what I found for act2-sc03:

### Abstract Language Detection

Checking `key_actions`, `crisis`, and `decision` for abstract vs. concrete indicators:

**key_actions:** "Presents evidence;Council dismisses;Dorren argues;Is overruled;Meets Kael after"
- This is mostly concrete action-level language. "Presents evidence" and "Dorren argues" are a bit abstract (what does presenting look like? what does arguing look like physically?) but the abstract indicator count is low. Not flagged by the automated detector.

**crisis:** "Accept the council's dismissal and work within channels, or go outside the institution entirely"
- Clean dilemma framing. No abstract indicators triggered.

**decision:** "Goes outside — shares findings with Kael privately after the meeting"
- Concrete enough. Describes a specific physical action.

**No fields meet the flagging threshold** (abstract_count >= 2 and abstract_count > concrete_count). The automated detection would not flag any fields for act2-sc03.

### Other Brief Quality Issues

Even though the abstract detector does not flag act2-sc03, there are other quality issues worth considering. Since you asked for coaching mode, I will present these as questions for you to decide on:

**1. Over-specified key_actions?**
The scene has 5 key_actions ("Presents evidence;Council dismisses;Dorren argues;Is overruled;Meets Kael after") with a target of 2,200 words. That is roughly one mandatory beat every 440 words. The rule of thumb is 2-3 actions per 2,500 words. Five actions in 2,200 words is tight — it may not leave enough room for atmosphere or interiority. Do you want to trim this to 3 beats?

**2. Prescriptive dialogue?**
The `key_dialogue` field contains exact quotes: `Council: "We appreciate your diligence, Cartographer.";Dorren to Kael: "They won't look."` Exact quotes force the drafter to contort surrounding prose to deliver specific lines. You might consider switching to dialogue direction instead — something like "Council uses patronizing institutional praise; Dorren confides her despair to Kael." Would you like to soften these to directions?

**3. Emotional arc granularity?**
The `emotions` field has 4 beats: "resolve;frustration;bitter-resignation;quiet-defiance". Four-beat arcs force artificial escalation-and-recovery cycles. A 2-beat arc (e.g., "resolve to quiet-defiance") would let the drafter find the middle ground organically. Want to simplify?

**4. Procedural goal?**
The goal is "Convince the council that the eastern anomalies require investigation" — this is actually a dramatic goal (convince = desire + obstacle), so it is fine. No change needed here.

## Gaps in Act 2

Two of three Act 2 scenes have significant gaps:

**act2-sc01** (status: architecture) — has intent data (function, value_at_stake, emotional_arc, etc.) but NO brief data at all. No goal, conflict, outcome, crisis, decision, or key_actions.

**act2-sc02** (status: spine) — has intent data but NO brief data at all. Same situation as act2-sc01.

These scenes are not yet at "briefed" status, so missing brief fields are expected. They need to go through the elaboration pipeline (scene map then briefs) before hone would apply to them.

## Recommended Next Steps

Since you are in coaching mode, here is what I would suggest — but it is your call:

1. **For act2-sc03** — Review the three quality issues above (over-specified actions, prescriptive dialogue, emotional arc granularity) and tell me which changes you want. I will save proposals to `working/hone/briefs-act2-sc03.md` for your review and apply whichever you approve.

2. **For act2-sc01 and act2-sc02** — These need elaboration before honing. Run the elaborate pipeline to get them to briefed status first:
   ```bash
   cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && \
   [plugin_path]/scripts/storyforge-elaborate --stage briefs --act 2
   ```

3. **To run the hone script directly** (coaching mode, act 2 briefs):
   ```bash
   cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && \
   /Users/cadencedev/Developer/storyforge/scripts/storyforge-hone --domain briefs --act 2 --coaching coach
   ```
   This will save proposals to `working/hone/` without modifying CSVs. You can then walk through the proposals with me here.

Which of the three issues on act2-sc03 would you like to address?
