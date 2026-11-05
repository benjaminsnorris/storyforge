# Source Fidelity Evaluation

This novel adapts a source. You are comparing one scene's {TARGET_KIND} against the source scene(s) it adapts, to find every place it departs from the source and to say whether each departure was authorized.

This is not a quality judgment, and a departure is not a fault. An adaptation is meant to depart where its plan says so: a compressed scene drops beats, a POV shift changes whose eyes we see through, and the version rules may soften or cut what the source shows. What this evaluation catches is **drift**: a departure nothing authorized.

Names differ from the source on purpose (the adaptation's name map); a renamed person or place is not a departure. Judge substance, not wording.

## The source scene(s)

{SOURCE_DATA}

## How this scene adapts them

**Treatment:** {TREATMENT}
**Note:** {NOTE}
**Mode:** {MODE} (`faithful`: every source event is kept unless the treatment, its note or a version rule says otherwise; `free`: the source is a starting point, but a departure is still `deliberate` only when one of those authorizes it)

Treatments: `dramatize` (the source scene played as a scene), `compress` (several source scenes, or a long one, in less: dropped beats are expected), `expand` (more than the source gives: added beats are expected), `pov-shift` (told from another character: a different POV and what it can know are expected), `reorder` (moved out of the source's order).

## Version rules

{RULES}

## The adaptation's {TARGET_KIND}

{TARGET_DATA}

## Instructions

For each element, compare the adaptation's {TARGET_KIND} with the source scenes':

- **goal:** what the POV character is after
- **outcome:** how the scene ends (who gets what, what is lost)
- **key_actions:** the events that happen
- **key_dialogue:** the substance of what is said (not the wording)
- **on_stage:** who is present
- **knowledge_out:** what characters learn in the scene. Both sides show only the facts each scene adds (`knowledge_out (new in this scene)`); facts carried in from earlier scenes are left out, so a fact missing here is not a departure

List every departure: something the source has that the adaptation drops or changes, or something the adaptation adds that the source doesn't have. Tag each one:

- `deliberate`: the treatment or its note explains it, or a version rule calls for it. Name which in `authority` (e.g. `treatment: compress`, `note`, `rule: the YA version softens the killing`)
- `drift`: nothing above authorizes it. `authority` is `none`

A departure belongs to one of those six elements. If it is only in the brief's `title`, `pov`, `conflict`, `crisis` or `decision`, name that field as its element: it is listed, not scored.

Then score each element 1-5 on **drift only**. A deliberate departure never lowers a score.

- **5:** no drift
- **4:** minor drift that changes nothing downstream
- **3:** drift a reader of the source would notice
- **2:** drift that changes what the scene means or what later scenes can rely on
- **1:** the element no longer adapts the source at all

## Output Format

Output ONLY these two blocks, pipe-delimited, with the block names `SCORES` and `DEPARTURES` on lines of their own (no markdown headings, no code fences). Each score is a whole number from 1 to 5. Write exactly one SCORES row. Leave the DEPARTURES block with just its header when there are none. Never use `|` inside a field; `authority` is `none` for every drift.

SCORES
id|goal|outcome|key_actions|key_dialogue|on_stage|knowledge_out
{SCENE_ID}|score|score|score|score|score|score

DEPARTURES
id|element|tag|departure|authority
{SCENE_ID}|element|deliberate or drift|one sentence: what the source has and what the adaptation does instead|what authorizes it, or none
