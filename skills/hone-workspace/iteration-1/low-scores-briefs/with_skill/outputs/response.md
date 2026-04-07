Good question. Let me look at what's going on with your briefs data. Since you don't have scoring data saved yet, I'll run the abstract detection analysis directly on your briefs and cross-reference with your intent data.

## What I Found

### 1. Your briefed scenes are actually not bad on abstract language

Looking at the three concretizable fields (key_actions, crisis, decision) for your briefed scenes (act1-sc01, act1-sc02, act2-sc03), the language is mostly verb-first and action-oriented:

- **act1-sc01 key_actions:** "Reviews maps;Finds anomaly;Consults Tessa;Files as error;Makes private note" -- these are physical actions, which is good.
- **act1-sc02 key_actions:** "Cross-references maps;Discovers missing village;Searches removal logs;Finds nothing" -- same pattern, concrete verbs.
- **act2-sc03 key_actions:** "Presents evidence;Council dismisses;Dorren argues;Is overruled;Meets Kael after" -- concrete, though "Is overruled" is passive.

The crisis and decision fields are framed as dilemmas and choices, which is appropriate. No major abstract language flags here.

### 2. The real problem: massive gaps in your data

This is almost certainly what's hurting your prose naturalness. Three of your six scenes have serious data gaps:

| Scene | Status | Problem |
|-------|--------|---------|
| **new-x1** (The Archivist's Warning) | mapped | Brief row exists but is almost entirely empty -- no goal, conflict, outcome, crisis, decision, key_actions, key_dialogue, or emotions. Only physical_state fields have data. |
| **act2-sc01** (Into the Blank) | architecture | No brief row at all. Intent row exists but no drafting contract. |
| **act2-sc02** (First Collapse) | spine | No brief row at all. Intent row exists but no drafting contract. |

When scenes lack briefs, the drafting model has no concrete contract to work from. It improvises, which produces generic, thematic prose -- exactly the kind of writing that scores low on prose naturalness.

### 3. Emotional arcs are thematic, not physical

Your scene-intent emotional_arc values are all written as abstract state transitions:

- "Controlled competence to buried unease"
- "Routine giving way to dread"
- "Professional detachment to visceral shock"

These aren't concretizable fields in the current hone detection (it focuses on key_actions, crisis, decision), but they do influence how Claude drafts the emotional beats. When the arc says "giving way to dread," the drafting model tends to write thematic narration rather than showing physical behavior changes. This is a secondary contributor to low naturalness scores.

## My Recommendation

The biggest bang for your buck is filling the gaps, then concretizing. Here's the priority order:

1. **Fill gaps first.** Scenes new-x1, act2-sc01, and act2-sc02 need briefs before anything else. Without a drafting contract, no amount of concretization on the other scenes will fix overall naturalness.

2. **Concretize after filling.** Once all six scenes have briefs, run hone's briefs domain to catch any abstract language in the new briefs (Claude-generated briefs sometimes slip into thematic language).

3. **Consider making emotional arcs more physical.** This is a manual edit -- change "Routine giving way to dread" to something like "Efficient cross-referencing slowing to frozen stillness as the gap becomes undeniable." That gives the drafting model physical behavior to anchor to.

## Next Steps

Would you like to:

**A) Fill the gaps first?** I can run the gap-fill domain of hone, which will use your existing intent data and scene metadata to generate concrete briefs for the three scenes that are missing them.

> **Option A: Run it here**
> I'll launch the hone script targeting gaps. This invokes Claude API calls to generate the missing brief fields.
>
> **Option B: Run it yourself**
> ```bash
> cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && /Users/cadencedev/Developer/storyforge/scripts/storyforge-hone --domain gaps
> ```

**B) Focus on the three briefed scenes?** If those are the ones with low naturalness scores, I can run the briefs concretization domain on just those scenes:

> ```bash
> cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && /Users/cadencedev/Developer/storyforge/scripts/storyforge-hone --domain briefs --scenes act1-sc01,act1-sc02,act2-sc03
> ```

**C) Walk through the briefs interactively?** I can go scene by scene, show you what each brief says, and we can rewrite abstract language together. This is the most hands-on option and gives you the most control.

Which approach works best for you?
