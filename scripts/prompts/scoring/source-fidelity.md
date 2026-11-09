# Source Fidelity Evaluation

This novel adapts a source. You are comparing one scene's {TARGET_KIND} against the source scene(s) it adapts, to find every place it departs from the source and to say whether each departure was authorized.

**The scene you are checking is `{SCENE_ID}`.** Every row of your output starts with `{SCENE_ID}`, never with a source scene's id.

This is not a quality judgment, and a departure is not a fault. An adaptation is meant to depart where its plan says so: a compressed scene drops beats, a POV shift changes whose eyes we see through, and the version rules may soften or cut what the source shows. What this evaluation catches is **drift**: a departure nothing authorized.

Names differ from the source on purpose (the adaptation's name map); a renamed person or place is not a departure. Judge substance, not wording.

## The source scene(s)

{SOURCE_DATA}

## The neighbouring book scenes' sources

The adaptation often moves material between neighbouring scenes: a beat the source tells in this scene may be told in the book scene before or after it, and a beat this scene tells may come from a neighbour's source scene. These are the book scenes either side of `{SCENE_ID}` (the nearest before and after it in reading order that adapt a source scene) and the source scenes they adapt. They are context only: you are not checking them.

{NEIGHBOURS}

## How this scene adapts them

**Treatment:** {TREATMENT}
**Note:** {NOTE}
**Mode:** {MODE} (`faithful`: every source event is kept unless the treatment, its note or a version rule says otherwise; `free`: the source is a starting point, but a departure is still `deliberate` only when one of those authorizes it)

Treatments: `dramatize` (the source scene played as a scene), `compress` (several source scenes, or a long one, in less: dropped beats are expected), `expand` (more than the source gives: added beats are expected), `pov-shift` (told from another character: a different POV and what it can know are expected), `reorder` (moved out of the source's order).

## Version rules

{RULES}

## The adaptation's {TARGET_KIND}: `{SCENE_ID}`

{TARGET_DATA}

## Instructions

For each element, compare the adaptation's {TARGET_KIND} with the source scenes':

- **goal:** what the POV character is after
- **outcome:** how the scene ends (who gets what, what is lost)
- **key_actions:** the events that happen
- **key_dialogue:** the substance of what is said (not the wording)
- **on_stage:** who is present
- **knowledge_out:** what characters learn in the scene. Both sides show only the facts each scene adds (`knowledge_out (new in this scene)`); facts carried in from earlier scenes are left out, so a fact missing here is not a departure

An adaptation's brief may leave goal and key_dialogue out: they are optional notes its author writes by hand, never its facts. One left out is not a departure (score it 5); compare what the brief does give.

List every departure: something the source has that the adaptation drops or changes, or something the adaptation adds that the source doesn't have. Tag each one:

- `deliberate`: the treatment or its note explains it, or a version rule calls for it. Name which in `authority` (e.g. `treatment: compress`, `note`, `rule: the YA version softens the killing`)
- `moved`: the beat is not lost or invented, only moved between this scene and a neighbour. Either this scene tells something from a neighbour's source scene, or a beat of this scene's source is told in a neighbour instead (its map note or its source says so). Name the neighbour in `authority`: its book scene id, or the id of the source scene it adapts (e.g. `from: <neighbour id>`, `to: <neighbour id>`). Use `moved` only when a neighbour is shown above
- `staging`: connective invention that changes no event, fact or outcome of the source: physical business, a character's interiority, a transition, a setting detail, an ending extended past the source's last beat without adding an event. Never on `outcome` or `knowledge_out`: a changed outcome or a new fact is not staging. {STAGING}
- `drift`: nothing above authorizes it. `authority` is `none`, and only a drift has `none`

A departure belongs to one of those six elements. If it is only in the brief's `title`, `pov`, `conflict`, `crisis` or `decision`, name that field as its element: it is listed, not scored.

Then score each element 1-5 on **drift only**. A `deliberate`, `moved` or `staging` departure never lowers a score.

- **5:** no drift
- **4:** minor drift that changes nothing downstream
- **3:** drift a reader of the source would notice
- **2:** drift that changes what the scene means or what later scenes can rely on
- **1:** the element no longer adapts the source at all

## Output Format

Output ONLY these two blocks, pipe-delimited, with the block names `SCORES` and `DEPARTURES` on lines of their own (no markdown headings, no code fences). Each score is a whole number from 1 to 5. Write exactly one SCORES row. Leave the DEPARTURES block with just its header when there are none. Never use `|` inside a field; `authority` is `none` for every drift and only for a drift.

SCORES
id|goal|outcome|key_actions|key_dialogue|on_stage|knowledge_out
{SCENE_ID}|score|score|score|score|score|score

DEPARTURES
id|element|tag|departure|authority
{SCENE_ID}|element|deliberate, moved, staging or drift|one sentence: what the source has and what the adaptation does instead|what authorizes it (for moved, the neighbour's book scene id), or none
