# Visual Style — Index

This is the top of the visual-canon tree for the project. Authority for
any specific block lives in the canon file linked below. This page is
the map.

The architecture is **canonical-source-with-inline-propagation**: each
visual block lives in exactly one canon file, and per-page panel prompts
embed verbatim copies of the blocks they need. The canon files are
ground truth; the inline copies are working artifacts. Changing a canon
block means re-propagating its embedded copies to every page that uses
it.

## Canon files

**Foundations** (universal — embed in every panel prompt):

- [Style Foundation](canon/style-foundation.md) — palette, medium,
  register, readability constraints
- [Lighting Laws](canon/lighting-laws.md) — value hierarchy, edge
  control, source conventions

**Vocabulary** (controlled terms cited by per-panel prompts):

- [Panel Registers](canon/panel-registers.md) — dominant, transitional,
  rhythmic, silent, splash

**Rules** (page-level conventions):

- [Page Rhythm Rules](canon/page-rhythm-rules.md) — detail-density
  differential, spread logic, page-turn beats

**Characters** — one canon file per on-page character in
[canon/characters/](canon/characters/). Each file's `canon_id` must
match a row in `reference/characters.csv`.

**Locations** — one canon file per recurring set in
[canon/locations/](canon/locations/). Cross-references
`reference/locations.csv`.

**Motifs** — one canon file per recurring visual motif in
[canon/motifs/](canon/motifs/). Cross-references
`reference/motif-taxonomy.csv`.

## Panel-prompt structure

Per-panel prompts are assembled from the canon blocks that apply,
embedded inline. The section layout is the artist's contract — when a
canon block changes, the embedded copy in each affected panel prompt
needs to be updated. (Phase 2, future RFC: automate that propagation.)

A typical panel prompt has the following sections, each populated from
the canon file linked above:

1. **Style Foundation** ← `canon/style-foundation.md`
2. **Lighting** ← `canon/lighting-laws.md` (or scene-specific override)
3. **Panel Register** ← `canon/panel-registers.md` (citation only)
4. **Characters present** ← `canon/characters/<slug>.md` for each
5. **Location** ← `canon/locations/<slug>.md` (if applicable)
6. **Motifs** ← `canon/motifs/<slug>.md` for each carried motif
7. **Panel-specific action and composition** (drafted per panel)

Per-page files (issue #251) are the unit that holds these assembled
prompts.

## Workflow per page

1. Determine which characters, locations, and motifs are on stage from
   the scene brief.
2. For each, locate the canon file under `canon/<subdir>/<slug>.md`.
3. Copy the "Embeddable block" from each applicable canon file into the
   page file's panel prompts.
4. Add panel-specific action, blocking, and dialogue.

## Validating canon

Run `storyforge cleanup --csv` to validate the canon tree:

- Frontmatter is present and complete on every canon file
- `canon_id` matches the filename
- `canon_type` is one of the allowed values
- All four required H2 sections are present
- Files under `characters/`, `locations/`, `motifs/` cross-reference
  the matching registry CSV

## Project-wide iteration history

Per-canon iteration lives inside each canon file's `## Iteration
history` section. Use this section here for changes that touch the
whole visual system — register shifts, palette overhauls, structural
changes to the canon layout itself.

- TODO — record the first project-wide iteration here.
