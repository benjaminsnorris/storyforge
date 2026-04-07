Good question -- low prose naturalness often traces back to brief quality rather than drafting skill. Let me look at what's going on with your briefs.

I read through your scene-briefs.csv, scene-intent.csv, and scenes.csv. Here's what I found:

## Brief Quality Assessment

You have briefs for 4 of 6 scenes (new-x1, act2-sc01, and act2-sc02 are missing or empty). Of the scenes that do have briefs, I'm seeing several patterns that would directly hurt prose naturalness:

### 1. Over-Specified Beats

This is probably the biggest driver of your low naturalness scores. Your key_actions lists are too long for the word counts:

- **act1-sc01** (target: 2,500 words) has 5 key_actions: "Reviews maps; Finds anomaly; Consults Tessa; Files as error; Makes private note." That's one mandatory beat every 500 words -- the drafter has no room for atmosphere, interiority, or organic transitions. It reads like a checklist.
- **act2-sc03** (target: 2,200 words) has 5 key_actions: "Presents evidence; Council dismisses; Dorren argues; Is overruled; Meets Kael after." Same problem -- every 440 words, the prose has to hit a required beat.
- **act1-sc02** (target: 3,000 words) has 4 key_actions. This is borderline -- at 750 words per beat, there's some breathing room, but it's tight.

Rule of thumb: 2-3 key_actions per 2,500 words. You want enough structure to anchor the scene, but not so much that the drafter is just connecting mandatory dots.

### 2. Prescriptive Dialogue

All three briefed scenes have exact quoted dialogue in their key_dialogue fields:

- act1-sc01: "The eastern readings are within acceptable variance"
- act1-sc02: "It was there forty years ago. It isn't there now. There is no note."
- act2-sc03: "We appreciate your diligence, Cartographer." and "They won't look."

When the brief includes exact lines, the drafted prose has to contort itself to deliver them. The sentences before and after the quote bend unnaturally to set up and land the specific phrasing. This is one of the most reliable causes of prose that feels stilted.

Better approach: use dialogue direction instead of exact lines. For example, instead of the exact quote, act1-sc01 could say: "Dorren rationalizes the anomaly using institutional language -- framing it as within acceptable parameters." The drafter gets the intent and the voice without being locked into specific words.

### 3. Emotional Arc Granularity

Every briefed scene has a 4-beat emotional arc:

- act1-sc01: competence -> unease -> self-doubt -> resolve
- act1-sc02: routine -> confusion -> dread -> determination
- act2-sc03: resolve -> frustration -> bitter-resignation -> quiet-defiance

Four-beat arcs force artificial escalation and recovery. The drafter has to hit each emotional beat in sequence, which creates a mechanical feeling -- rise, dip, rise, land. A 2-beat arc (start state to end state, like "competence -> unease" or "routine -> dread") lets the drafter find the emotional middle ground organically. The journey between two points is where naturalness lives.

### 4. Procedural Goal (act1-sc01)

The goal for act1-sc01 is: "Complete the quarterly pressure audit on schedule." That's a task, not a dramatic question. Procedural goals produce bureaucratic openings because the drafter frames the scene around completing a procedure rather than a character navigating tension.

A dramatic reframe: "Prove the maps are accurate before the review deadline -- while an anomaly she can't explain stares back from the eastern sector." Same scene, same events, but the goal creates tension rather than a to-do list.

### 5. Gaps

Two scenes (act2-sc01, act2-sc02) have no briefs at all, and new-x1 is essentially empty. These scenes will either be drafted without guidance (producing generic prose) or can't be drafted at all.

## Recommendation

The briefs domain of hone is exactly what you need. It will concretize abstract language, trim over-specified beats, convert prescriptive dialogue to direction, and simplify emotional arcs. I'd focus on the three scenes that have full briefs first (act1-sc01, act1-sc02, act2-sc03), then fill the gaps for the others.

**Option A: Run it here**
I'll launch the hone script in this conversation. This invokes Claude API calls for brief concretization, so I need to unset the CLAUDECODE variable. Estimated cost depends on scene count -- roughly $0.50-1.00 for 3 scenes.

**Option B: Run it yourself**
Copy this command and run it in a separate terminal:
```bash
cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && /Users/cadencedev/Developer/storyforge/scripts/storyforge-hone --domain briefs
```

To do just the three briefed scenes:
```bash
cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && /Users/cadencedev/Developer/storyforge/scripts/storyforge-hone --domain briefs --scenes act1-sc01,act1-sc02,act2-sc03
```

After hone rewrites the briefs, you'll want to re-draft the affected scenes to pick up the new concrete briefs. That's where you should see naturalness scores improve.

Which option works for you?
