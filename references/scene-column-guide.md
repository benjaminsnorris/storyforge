# Scene Column Guide

This document explains **why** each column in the scene CSV files matters and **how** to check and improve the values. For column definitions and data types, see `scene-schema.md`.

---

## Structural Identity (scenes.csv)

### seq — Reading Order
**Why it matters:** Controls how the reader experiences the story. Reordering scenes changes pacing, information reveal, and emotional rhythm without touching the prose.
**How to check:** Read the `function` column in seq order. Does each scene build on what came before? Are there jumps that feel unmotivated?
**How to improve:** If a scene feels out of place, check whether moving it changes the reader's knowledge state. Use the timeline scatter chart to spot where reading order and chronology diverge.

### part — Act/Part Assignment
**Why it matters:** Defines the story's macro structure. Parts should hit roughly: Act 1 ~25% of word count, midpoint ~50%, climax ~75-85%.
**How to check:** Sum `target_words` by part. Are the proportions right? Does the midpoint fall where it should?
**How to improve:** If Act 2 is too long, look for scenes that could move to Act 1 (setup) or Act 3 (escalation).

### pov — Point of View Character
**Why it matters:** POV distribution shapes whose story this is. Unintentional imbalance (one character gets 80% of scenes) reduces other characters to supporting roles.
**How to check:** Count scenes per POV. Compare with the character's narrative importance. Check the POV River chart.
**How to improve:** If a character has too few scenes, consider whether their arc needs more space. If too many, look for scenes that could shift to another POV without losing story function.

### location — Physical Place
**Why it matters:** Repeated locations build familiarity; too many unique locations feels scattered. Location changes signal scene transitions.
**How to check:** Count scenes per location. Flag locations that appear only once (might be consolidation opportunities).
**How to improve:** Normalize names (is "the office" and "sheriff's office" the same place?). Consider whether scenes in unique locations could happen in established ones.

### timeline_day — Chronological Position
**Why it matters:** Validates that the story's internal clock is consistent. Characters can't reference Tuesday's events on Monday.
**How to check:** Run `./storyforge validate` — it flags backwards timeline jumps. Check the Timeline scatter chart.
**How to improve:** If validation finds gaps, determine whether the gap is intentional (time skip) or an extraction error.

### type — Narrative Purpose
**Why it matters:** A balanced manuscript has a mix of types. Five consecutive plot scenes with no character development creates pace without depth. Five character scenes with no plot creates depth without momentum.
**How to check:** Look at the Scene Type Sequence chart. Flag stretches of 4+ same type.
**How to improve:** Scenes can serve multiple purposes. If you have a run of plot scenes, look for opportunities to add character depth within the existing plot action.

### status — Elaboration Depth
**Why it matters:** Tracks progress and controls which validation checks apply. A scene at `mapped` won't be checked for brief completeness.
**How to check:** Count scenes by status. Are any stuck at a lower depth than expected?
**How to improve:** Advance scenes through stages using `/storyforge:elaborate`.

---

## Narrative Dynamics (scene-intent.csv)

### function — Why This Scene Exists
**Why it matters:** The most important column. A scene without a testable function should be cut or merged. If you can't state what changes because of this scene, the scene isn't earning its place.
**How to check:** Read each function. Can you verify from the prose that this actually happens? Is it specific ("she discovers the letter was forged") or vague ("develops the relationship")?
**How to improve:** Rewrite vague functions to be testable. If you can't make it specific, the scene may lack a clear purpose.

### action_sequel — Action/Sequel Pattern
**Why it matters:** The action/sequel rhythm controls pacing. Action scenes (goal → conflict → outcome) create tension. Sequel scenes (reaction → dilemma → decision) process that tension. Too many consecutive action scenes is breathless. Too many sequels is a slog.
**How to check:** Look at the Scene Rhythm chart. Flag 4+ consecutive same type.
**How to improve:** If you have a run of action scenes, insert a sequel where a character processes what happened. If all sequels, find a scene where a character makes an active choice and hits opposition.

### value_at_stake — What's Being Tested
**Why it matters:** Readers stay engaged when something they care about is at risk. Naming the value (safety, love, justice, truth) makes the stakes concrete and checkable.
**How to check:** Does the value feel right for the scene? Is it the same value for too many consecutive scenes (reader fatigue)?
**How to improve:** Vary values across sequences. If the whole middle is about "safety," consider shifting some scenes to test "trust" or "loyalty."

### value_shift — Polarity Change
**Why it matters:** If a value doesn't shift, nothing happened — it's a nonevent (McKee). The shift direction (+/-, -/+, etc.) creates the story's emotional shape.
**How to check:** Look at the Value Shift Arc chart. Flag flat stretches (3+ scenes of +/+ or -/-). Check that the overall trajectory makes sense for the story's arc.
**How to improve:** If a scene has a flat value shift, ask: what changes for the character by the end? If nothing, the scene needs a turn — something that shifts the character's situation.

### turning_point — Action or Revelation
**Why it matters:** Varying turning point types prevents reader fatigue. If every scene turns on a revelation (new information), the pattern becomes predictable. Alternating with action turns (a character does something) creates variety.
**How to check:** Flag 4+ consecutive same type. The Scene Rhythm chart shows this.
**How to improve:** If too many revelations, look for scenes where a character's action could be the turning point instead of new information arriving.

### characters / on_stage — Who's Present
**Why it matters:** Character presence drives the reader's sense of the story's world. Characters who are mentioned but never appear on-stage feel like they exist only in exposition.
**How to check:** Check the Character Presence Grid. Flag characters with many mentions but few on-stage appearances.
**How to improve:** If an important character is mostly off-stage, consider adding scenes where they appear in person. If a character is present in many scenes but doesn't affect the action, they may be filling space.

### mice_threads — MICE Thread Operations
**Why it matters:** MICE threads (Milieu, Inquiry, Character, Event) track the reader's open questions and spatial sense. They must close in reverse order of opening (FILO) — like closing HTML tags. Violation of this order creates a subconscious feeling that something is "off."
**How to check:** Run validation (flags FILO violations). The thread nesting is checked automatically.
**How to improve:** If nesting is wrong, determine which thread should close first. Sometimes the fix is reordering scenes; sometimes it's adding a brief resolution beat.

---

## Drafting Contracts (scene-briefs.csv)

### goal — What the Character Wants
**Why it matters:** The goal makes the scene active. A character without a goal is a passenger — they're in the scene but not driving it. The goal doesn't have to be dramatic ("escape the burning building") — it can be subtle ("understand why he's being evasive").
**How to check:** Is the goal concrete enough to succeed or fail at? Could you tell from the prose whether the character achieved it?
**How to improve:** If the goal is vague ("process her feelings"), make it active ("decide whether to confront him about the letter").

### conflict — What Opposes the Goal
**Why it matters:** Without opposition, there's no scene — just a character getting what they want. Conflict can be external (another character, physical obstacle) or internal (fear, loyalty, desire pulling in opposite directions).
**How to check:** Is the conflict specific? Does it directly oppose the goal? Is it present throughout the scene or mentioned once and forgotten?
**How to improve:** Strengthen conflict by making the opposition active and personal, not abstract.

### outcome — How It Ends
**Why it matters:** The outcome determines what the next scene inherits. "Yes" means the story advances; "no" means it's blocked; "yes-but" introduces a new complication; "no-and" makes things worse. Most scenes should end in "yes-but" or "no-and" to maintain forward momentum.
**How to check:** Does the prose actually deliver this outcome? A scene marked "no-and" that reads as a clean resolution has a fidelity problem.
**How to improve:** If too many scenes end "yes," the story lacks tension. Look for ways to add complications.

### crisis — The Dilemma
**Why it matters:** The crisis is the moment the scene earns its place. It forces a character to choose between two bad options (best bad choice) or two good options that conflict (irreconcilable goods). Without a genuine dilemma, the scene lacks dramatic weight.
**How to check:** Is this a real choice? Would a reasonable person agonize over it? If the "right" answer is obvious, it's not a crisis.
**How to improve:** Make both options costly. The character should lose something no matter what they choose.

### decision — What They Choose
**Why it matters:** The decision reveals character. Under pressure, what a person chooses tells you who they are. The decision must be active (the character does something) not passive (the character waits and something happens to them).
**How to check:** Does the character actively choose, or does the situation resolve itself? Does the choice cost them something?
**How to improve:** If the decision feels passive, restructure so the character must act — even if the action is choosing not to act.

### knowledge_in / knowledge_out — Information State
**Why it matters:** This is the continuity backbone. If a character acts on information they haven't received, or fails to act on information they have, the reader loses trust. Exact wording enables automated validation.
**How to check:** Run validation — it flags knowledge_in facts that don't match any prior knowledge_out. Check that knowledge_out includes everything the character learned during the scene.
**How to improve:** Ensure exact wording matches across scenes. If validation flags a mismatch, check whether it's a wording difference (fix the wording) or a genuine continuity error (fix the scene order or add a scene where the character learns the fact).

### key_actions / key_dialogue — Scene Contract
**Why it matters:** These are the specific beats that make the scene work. If the brief says a character "examines the body and notes the staged positioning" and the prose skips the examination, the scene hasn't delivered its promise.
**How to check:** Fidelity scoring compares these against the prose. Low `key_actions` or `key_dialogue` fidelity means the prose diverged from the brief.
**How to improve:** Either update the prose to include the contracted beats, or update the brief if the prose found something better.

### continuity_deps — Parallel Drafting Groups
**Why it matters:** Scenes with no dependencies can be drafted simultaneously. Minimizing deps maximizes parallelism and reduces drafting time/cost.
**How to check:** Run `compute_drafting_waves` to see the wave structure. Scenes in wave 1 have no deps; later waves depend on earlier ones.
**How to improve:** If a scene depends on many prior scenes, check whether all those dependencies are real. Sometimes a dependency can be replaced by including the relevant fact in knowledge_in without requiring the full prior scene.
