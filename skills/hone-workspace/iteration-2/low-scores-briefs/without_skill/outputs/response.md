# Brief Quality Analysis -- The Cartographer's Silence

I looked at your briefs across all six scenes and found several patterns that would directly hurt prose naturalness scores. Here is what I see.

## The Big Picture

You have three briefed scenes (act1-sc01, act1-sc02, act2-sc03), one mapped scene (new-x1), and two earlier-stage scenes (act2-sc01 at architecture, act2-sc02 at spine). The problems cluster in two areas: **over-specification that forces mechanical prose** and **gaps that leave the drafter guessing**.

## Problem 1: Briefs That Read Like Checklists

**act1-sc01** is the clearest example. The brief packs in five key_actions (`Reviews maps;Finds anomaly;Consults Tessa;Files as error;Makes private note`), two pieces of key_dialogue, four emotions (`competence;unease;self-doubt;resolve`), and a specific crisis/decision structure -- all for a 2,500-word scene. That is roughly one mandated beat every 300 words.

When a drafter (human or Claude) tries to hit every one of these beats, the prose becomes a conveyor belt: action, then emotion, then dialogue, then next action. There is no room for the scene to breathe, for a moment to land before the next one arrives. Your voice guide calls for "longer, winding sentences for description and world-building" and "short declarative sentences for moments of realization" -- but the brief's density fights that rhythm.

**act2-sc03** has the same problem: five key_actions, specific council dialogue, four emotions, and a post-scene meeting with Kael, all in 2,200 words.

**What to do:** Trim key_actions to 2-3 essential beats per scene. Move the rest to a "texture" note that the drafter can draw on but is not obligated to hit. Reduce emotions to 1-2 per scene -- the emotional *trajectory* (e.g., "resolve eroding into bitter resignation") rather than a list of four discrete feelings the drafter must show.

## Problem 2: Dialogue Prescriptions Kill Natural Voice

Both act1-sc01 and act2-sc03 have specific key_dialogue lines. "The eastern readings are within acceptable variance" and "We appreciate your diligence, Cartographer" are essentially script lines. When these appear in the brief, the drafter builds the scene around delivering those lines, which makes the surrounding prose feel like scaffolding rather than story.

**What to do:** Replace literal dialogue with dialogue *goals*. Instead of the exact line, write: "Dorren minimizes the anomaly in official terms" or "Council delivers a patronizing dismissal." Let the drafter find the voice.

## Problem 3: The new-x1 Brief Is Nearly Empty

new-x1 ("The Archivist's Warning") has almost no brief data -- no goal, no conflict, no outcome, no crisis, no key_actions. The only fields populated are physical_state_in and physical_state_out (both `archive-key-dorren`). Yet this scene sits at a critical story junction: it is the bridge between Dorren's private discovery and the council confrontation.

The existing prose in new-x1.md also has a problem: it has Tessa as the POV character, but scenes.csv says Kael Maren is the POV. That mismatch suggests the scene was drafted without the brief and the structural data was filled in after, which is exactly the scenario where briefs need to be strongest.

**What to do:** Fill in the new-x1 brief before any redrafting happens. At minimum: goal, conflict, outcome, knowledge_in/knowledge_out, and 1-2 key_actions. This scene needs to earn the `archive-erasure` knowledge transition.

## Problem 4: Emotions Are Listed, Not Arced

Look at the scene-intent emotional_arc values versus the brief emotions:

| Scene | Intent emotional_arc | Brief emotions |
|-------|---------------------|----------------|
| act1-sc01 | "Controlled competence to buried unease" | competence;unease;self-doubt;resolve |
| act1-sc02 | "Routine giving way to dread" | routine;confusion;dread;determination |
| act2-sc03 | "Resolve to bitter resignation" | resolve;frustration;bitter-resignation;quiet-defiance |

The intent file gives a beautiful arc in plain language. The brief then atomizes it into a semicolon-separated list. The drafter sees both, and the list wins -- it is more specific, more checklistable. The result is prose that dutifully shows each emotion in sequence rather than letting the arc emerge from the action.

**What to do:** Either remove the emotions field from briefs entirely (rely on intent's emotional_arc) or rewrite brief emotions as a single trajectory phrase that matches the intent. Do not list 4 discrete emotions.

## Problem 5: Physical States and Continuity Deps Create Invisible Constraints

act2-sc03 requires `archive-key-dorren;exhaustion-tessa` as physical_state_in. But Tessa is not even in act2-sc03's character list (characters field in scene-intent is `Dorren Hayle;Council Members;Kael Maren`). The drafter has to either ignore the physical state or shoehorn Tessa into the scene, and either choice produces unnatural prose.

Similarly, act1-sc02's physical_state_out includes `archive-key-dorren;exhaustion-tessa`, but the scene is set in "Dorren's private study" with only Dorren on stage. How does Tessa acquire exhaustion in a scene she is not in?

**What to do:** Audit physical_state_in and physical_state_out against the scene's actual character list. Remove physical states for characters who are not on stage. If a state needs to transfer between scenes, make sure the character is actually present.

## Summary of Recommended Actions

1. **Reduce key_actions** to 2-3 per scene (act1-sc01, act2-sc03)
2. **Replace literal dialogue** with dialogue goals (act1-sc01, act2-sc03)
3. **Fill the new-x1 brief** -- it is nearly empty and the scene is structurally critical
4. **Collapse emotion lists** into trajectory phrases that match scene-intent emotional_arc
5. **Audit physical states** against on_stage characters -- remove states for absent characters (act1-sc02, act2-sc03)
6. **Fix the POV mismatch** in new-x1 -- prose has Tessa, scenes.csv says Kael Maren

These are all CSV-level fixes. None of them require touching prose yet. Fix the briefs first, then redraft the scenes that scored low on naturalness. The prose will come out better because the brief is no longer fighting the voice guide.
