---
canon_id: <character-slug>
canon_type: character
canon_updated: <YYYY-MM-DD>
appears_in: panels featuring <character name>
embeds_as: Character
first_appearance: <scene-id or page-id where they first appear>
---

<!--
This file is a starter template for character canon. Don't edit it in
place — copy it to a sibling file named after the character's slug:

    cp _template.md lucien-vey.md

The filename must match `canon_id`, and the character must exist as
an `id` row in `reference/characters.csv`.

Delete this comment from your copy.
-->

## Embeddable block

The canonical character description that embeds in every panel prompt
where this character appears. Cover: physique, face, hair, posture,
costume, signature accessories. Specific enough that a diffusion model
produces the same character across hundreds of panels.

## Clauses

One bullet per visual element above. For each, state the failure mode
the clause counters — what the model defaults to when the clause is
absent.

## Related canon

- [[style-foundation]]
- [[lighting-laws]]
- [[<location-slug>]] — if this character has a tightly-bound location
- [[<motif-slug>]] — if this character carries a recurring motif

## Iteration history

Date, what changed, why. Specific to this character; project-wide
iteration lives in `reference/visual-style.md`.
