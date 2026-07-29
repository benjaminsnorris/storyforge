# Illustration state matrix, contradiction audit, and handoff packet

**Date:** 2026-07-28
**Status:** design, approved in conversation
**Implements for:** prose books (`project.medium: novel`)
**Designs toward:** a reference model shared by both mediums. GN adoption is a follow-up issue.

## Why

Twenty rendered interior illustrations for *The Lantern Folk* were reviewed against the
manuscript. Ten findings, three of them blockers. Sorting them by cause rather than by
severity says something the severity ordering hides:

| Cause | Findings |
|---|---|
| No record of what visual state is true when | pajamas two chapters past the line where the prose dresses them; Ch12 rendered lit when the prose has no light in it; the Great Lamp lit or dark; the surviving-lantern count |
| No per-image check against the governing prose | an image of an event that does not happen in the book; children beaming during the grimmest turn |
| No check across the set | three of the last four images are the same shot, so the emotional peak reads as a lull |
| A contradiction in the prose itself | Ch10 kills every lantern, Ch11 confirms it, Ch13 finds four still burning |

The existing flow cannot catch any of these. `--review` is a set-level checklist a human
fills in after the fact. Continuity anchors hold what must never change and have nowhere
to put what changes on schedule. Nothing reads a render against its scene.

## The shared three-tier model

Both mediums want the same structure, and GN got there first in #260:

1. **Reference tier** — the world, the style, the entities. Stated once.
2. **Per-unit direction** — what this page or this illustration is doing, and how much page it gets.
3. **Leaf prompt** — thin, because the tiers above it are present.

GN already implements all three: `reference/canon/` typed files, `## Page architecture`, and
a prompts stage that passes canon as *distillation* context with an explicit
`do NOT paste` instruction (`prompts_page_prompt.py:416`). `script-package` aggregates the
leaves into book-level documents.

Prose illustrations implement a weaker version of tier 1 (one `illustration-direction.md`
with `### Name` subsections), have tier 2 on the plan row, and have a tier-3 prompt that is
*not* thin — it is standalone and self-contained, because each one is pasted alone.

This spec moves prose onto GN's tier-1 mechanism and adds the four things neither medium
has: a state matrix, a contradiction audit, per-unit acceptance criteria, and cross-set
contrast checking.

## What changes about the handoff

Today `--prompts` writes a standalone 250–400 word prompt per illustration, each pasted
into an image model on its own. The author's lived experience — in both mediums — is that
hyper-detailed leaf prompts underperform, and that a session working from shared reference
material does better. GN reached this conclusion first: per-panel generation failed, so it
moved to a page at a time with canon distilled rather than pasted.

This narrows a documented principle, so the narrowing is recorded here rather than left to
look like drift. CLAUDE.md's #260/#263 principles — five-section template, 250–400 words,
structure over brevity — were validated when the prompt was the model's **only** context.
Where the reference tier is present, a thin leaf is not losing information; it is declining
to restate it. What stays: verbatim-identical anchor strings, positive framing for content,
explicit orientation, no text. What moves to the reference tier: house style, palette
logic, content limits, and the generic acceptance checks.

## The reference tier: `reference/canon/`

Prose illustrations adopt GN's canon files rather than keeping a parallel mechanism. One
mechanism, one drift story, and GN convergence becomes mostly configuration.

`reference/illustration-direction.md` maps onto canon types with no leftovers:

| Direction document section | Canon file | `canon_type` |
|---|---|---|
| Format + Visual promise | `visual-foundation.md` | `foundation` |
| Recurring visual language | `visual-vocabulary.md` | `vocabulary` |
| Content limits | `content-limits.md` | `rules` |
| Continuity anchors (`### Name` each) | one file per entity under `characters/`, `locations/`, `motifs/` | `character` / `location` / `motif` |

An entity canon file's `## Embeddable block` **is** the continuity anchor — the string
reused verbatim wherever that entity appears. canon.py already models exactly this, which
is the core reason to adopt it rather than reinvent it.

Two frontmatter keys the illustration flow currently derives ad hoc become recorded data:
`appears_in` (which illustrations feature this entity) and `first_appearance` (the earliest,
which is what `render_order()`'s `locks` computes today by walking `canon_refs`).

### Three things adoption requires

1. **The novel-project guard must become medium-aware, not deleted.**
   `cmd_cleanup.py:1284` currently emits `canon_present_in_novel_project` (warning) and
   **skips canon validation entirely** when medium is not `graphic-novel`. Deleting the
   finding without making validation medium-neutral would leave prose canon files
   unvalidated and silent. Both halves change together.

2. **Creature and prop anchors need a registry home.**
   `canon_missing_registry_entry` requires every canon file under `characters/`,
   `locations/`, `motifs/` to have a matching row in `characters.csv`, `locations.csv`, or
   `motif-taxonomy.csv`. Recommendation: **creatures go under `characters/`** with a
   `characters.csv` row — a creature whose design must stay consistent is a character for
   continuity purposes — and **signature props go under `motifs/`**, which
   `motif-taxonomy.csv` already describes as concrete recurring vehicles. This adds no new
   subdirectories or registries. If a prop genuinely isn't a motif, that is the signal it
   doesn't need an anchor.

3. **`embeds_as` needs a decision.** It is a required frontmatter key whose purpose is the
   inline-embed convention. Neither medium's current prompt stage inlines canon (see
   Staleness below), so for prose it would be write-only. Make it optional rather than
   required when medium is `novel`, and let the staleness issue decide its fate.

### No migration mechanism

Exactly one project has an `illustration-direction.md`, and it is hand-edited into canon
files rather than migrated by code. A `storyforge migrate` step for a population of one is
not worth building or maintaining.

Consequences, stated because nothing enforces them:

- **The code reads canon files only.** `illustration-direction.md` stops being an input;
  there is no dual-path fallback. The hand-edit is a prerequisite for the new flow, not an
  optional upgrade. `--diagnose` reports the direction document's presence alongside absent
  canon files so the situation is legible rather than silent.
- **Anchor bodies must be copied byte-identically.** An anchor whose string changes during
  the hand-edit invalidates every illustration already rendered from it — likeness
  continuity depends on the string, not on its meaning. This is the one part of the hand-edit
  that cannot be eyeballed, so `--diagnose` warns when a canon file's `## Embeddable block`
  differs from a same-named `### Name` section in a still-present direction document. That
  check is cheap, catches the only unrecoverable mistake, and costs nothing once the old file
  is deleted.

The section-to-canon mapping above is the guide for that hand-edit.

## Artifacts

### `reference/visual-state.csv` — the state matrix

Sparse transition log. A row records the moment a tracked entity's visual state changes;
the state persists forward until the next transition for that entity.

```
entity|from_scene|state|evidence
nora-clothing|s01-moving-night|mustard-yellow nightclothes, barefoot|padded to the window in bare feet
nora-clothing|s04-the-great-lamp|moss-green cardigan, trousers, brown ankle boots|Nora was standing at his door with her jacket zipped
great-lamp|s04-the-great-lamp|lit, steady gold, multiple wicks in an open bowl|cradled in a bowl of living wood
great-lamp|s10-extinguished|dark and cold, wicks stiff|The Great Lamp was out.
village-lights|s13-the-long-walk|four or five weak lanterns still burning|four. Maybe five.
```

- `entity` — kebab-case slug. Names a thing whose *visible state changes*, which is a
  different set from the canon entities, whose *design must not change*. They overlap: the
  Great Lamp has both an invariant design (a canon file) and a changing lit/dark state
  (rows here). Where an entity has a canon file, the slug must match its `canon_id`.
- `from_scene` — references `scenes.csv:id`. The transition takes effect here.
- `state` — one short phrase describing what is visibly true.
- `evidence` — a verbatim quote from `from_scene`'s prose that establishes it.

**Granularity: one track per independently-changing aspect, not one per entity.**
`nora-clothing` rather than `nora`, because clothing and, say, injury state change on
different schedules and a single track would force restating one to change the other. The
convention is `{canon_id}-{aspect}` where an entity has multiple tracks, and a bare
`canon_id` where it has one.

**Resolution.** The state of entity `E` at scene `S` is the transition for `E` with the
greatest `scenes.csv:seq` among those whose `from_scene` seq is `<= S`'s seq. No matching
transition means the state is unspecified, which is reportable when an illustration in that
scene names `E`.

**Why sparse rather than a dense scene × entity grid.** It matches the
`reference/outline.md` precedent, where a CSV is the source and a rendered view is derived.
It survives revision — scene-map operations insert, merge, split, and reorder, and a
transition keyed "from `s04` onward" still means something after a scene lands at `s05`,
where a dense grid would have no row and fall silently blank. And one authorial decision
("from Chapter 4 they arrive dressed") is recorded once instead of restated in every
illustrated scene from 4 to 15, each restatement being a cell that can go stale alone.

The trade: sparse can reference a scene that has since been cut, which is why
`illus_state_unknown_scene` is an error rather than a warning. A dense grid cannot have
that bug because it never names a scene it is not keyed by.

### `illustration-plan.csv` gains three columns

- `state_override` — `;`-delimited `entity:state` pairs for visual state true in *this image
  only* and not persisting. Tear-streaked faces, arms raised against a light. A pure
  transition log would have to write a change and then a change back, which is nonsense.
  Split on the **first** colon, so a state may itself contain one.
- `register` — optional, `darkest` or `brightest`, marking the book's lighting extremes.
  Feeds anchor-batch selection. Populated by `--plan` under `full` coaching.
- `scene_digest` — recorded at ingest. The normalized digest of the scene prose the render
  was made from, so "the prose changed under this image" becomes detectable.

### `working/illustration-contradictions.md`

Read-only audit report, written by `--audit`.

### `manuscript/illustration-packet/` — the handoff bundle

```
manuscript/illustration-packet/
├── README.md            two phases, how to work the packet, what to return
├── canon.md             the reference tier, assembled from reference/canon/
├── visual-state.md      derived dense view: scene × entity
├── illustrations.md     per-illustration entries
├── reference-images.md  which files to upload, in what order, what each is for
└── acceptance.md        global acceptance criteria and sequence-contrast rules
```

Regenerated wholesale by `--package`, so it is a render and never hand-edited. The derived
state view lives here rather than in `reference/` specifically so there is no second file to
keep fresh.

Reference images are **not copied**; `reference-images.md` carries project-relative paths
into `manuscript/assets/illustrations/`. The author uploads from disk, and a copy would be a
second thing to invalidate.

**The load-bearing invariant:** every anchor string in `canon.md` and in every entry in
`illustrations.md` is **byte-identical** to the `## Embeddable block` of its canon file.
Likeness continuity is the whole reason anchors exist and it depends on the string not
varying. A test asserts this, in the same spirit as the existing assertion that publish
`content_html` is byte-identical with and without illustrations.

### Per-illustration entry shape

Thin — 80–120 words, against today's 250–400 — because the reference tier carries the rest.
Only what is specific to *this image* appears here.

```markdown
### lamp-relit

- Scene: `s14-the-keepers-flame` · Layout: double_page · Aspect: landscape

**Beat.** The Great Lamp catches and the light drives outward through the woods.

**In frame.** Wide elevated view of the village. The Lamp blowing out the centre of the
frame as the light source. Gold visibly travelling between the trunks. Both children small
and together, arms up against the glare.

**State.** Nora: filthy moss-green cardigan, brown ankle boots. Leo: filthy rust-red hooded
jacket. Great Lamp: erupting, gold. Village lights: a few weak survivors.

**Absent.** Ember. A second Great Lamp.

**Contrast.** Much wider and brighter than `lamp-embers-choice`, which precedes it. The
brightest image in the book.

**This image also.** Faces and Lamp clear of the centre gutter.
```

`State` stays in the entry because it is a *resolution* of the matrix for one scene, not a
duplication of it. What moved out to `acceptance.md`: the colour-logic prohibitions, the
orientation rule, no-lettering, palette adherence, and every other check that is identical
across the set. What stays: image-specific absences, image-specific contrast, image-specific
composition notes.

`State` lists only the entities in the row's `canon_refs`, resolved from the matrix and then
overlaid with `state_override`. Sending the whole cast wastes tokens and invites the model to
include people who are not in the frame.

**`Absent` and the colour rules in `acceptance.md` are a deliberate exception to positive
framing.** #263 established that negated content keywords leak into the render, and that
rule stands for description. But the Lantern Folk set produced magenta lanterns in a book
whose entire colour logic is gold-is-life / blue-is-death, and the positively-framed
instruction ("Folk lanterns in warm amber and gold") did not prevent it. The exception is
narrow and enumerable: **named entities that must be absent, and violations of stated colour
logic.** Orientation and no-text remain the other two exceptions.

## Commands

All flags on `illustrate`. The author types none of them: the skill's mode table detects
state and offers the command, and `--diagnose` reports which rung the project is on. Flags
are output, not vocabulary to memorize.

| State detected | Mode | Offered |
|---|---|---|
| No canon files | Direct | `--direction` |
| Canon exists, no plan | Plan | `--plan` |
| Plan exists, no state matrix | **State** | `--state` |
| Matrix exists, audit unrun or stale | **Audit** | `--audit` |
| Audit clean, rows at `planned` | Art-direct | `--prompts` |
| Prompts written, no packet or packet stale | **Package** | `--package` |
| Packet built, any anchor-batch row not `ingested` | **Anchor** | render these N, approve |
| Every anchor-batch row `ingested`, others not | **Churn** | hand the packet over |
| Non-anchor files on disk | Ingest | `--ingest PATH` |
| Most rows `ingested` | Review | `--review` |

"Audit clean" means **no error-severity findings**. Warnings do not gate the stage; they are
surfaced and the author decides, consistent with how `cleanup` treats warnings elsewhere.
Anchor and Churn are distinguished by whether every *anchor-batch* row has reached
`ingested`, not by whether any file exists, so ingesting the batch advances the stage rather
than looking like ordinary ingest.

Three surfaces learn the new stages: the skill's mode table, `--diagnose` as stage reporter,
and `status`/`forge`, which today cannot surface illustration work at all.

### `--direction`

Writes canon files rather than one direction document. Coaching-aware as today: `full`
drafts from the bibles, `coach` produces per-file question templates, `strict` produces
blank typed templates. Reports canon files whose `## Embeddable block` is empty or still
template text — a scaffold fed to an image model as though it were direction is worse than
no document.

### `--state`

Writes or refreshes `reference/visual-state.csv`. `full` proposes transitions by reading the
prose and reports each with its evidence quote; `coach` writes questions to
`working/coaching/visual-state-brief.md`; `strict` writes a blank template seeded with the
entity list drawn from canon files and the registries.

### `--audit`

The pre-generation contradiction pass. Read-only: never edits prose or the matrix.

**Deterministic pre-pass**, no API cost:

1. `from_scene` values that do not resolve to a scene → `illus_state_unknown_scene` (error).
2. `evidence` quotes not found in `from_scene`'s prose → `illus_evidence_not_found`
   (warning). Uses the existing whitespace-tolerant `find_anchor`, so a quote survives reflow.
3. Illustrations whose `canon_refs` name an entity with no resolved state at that scene →
   `illus_state_unspecified` (warning).
4. Scenes that mention a tracked entity and lie between that entity's transitions — the
   narrowed set the LLM reads.

**LLM pass** over the narrowed set only: reports prose that *asserts* a state contradicting
the derived matrix, each finding carrying the scene id, the quote, and which transition it
disagrees with. Sonnet; analytical, not creative.

This is what catches the Ch10/Ch11/Ch13 lantern conflict, and it is worth being precise
about why the matrix alone cannot. The author writes two transitions — village-lights goes
dark at s10, four survive at s13 — and nothing about them disagrees, because things are
allowed to change. The contradiction is that Ch11 *asserts* a state ("Are they all gone?" /
"Yes.") that the s10→s13 span cannot support. Only reading prose against the matrix finds it.

Records per-scene digests of everything it read to
`working/illustration-audit-provenance.csv`, so `illus_audit_stale` is detectable.

### `--package`

Assembles the bundle. No API calls. Warns loudly on unresolved audit findings and on a
never-run audit; does not block, because a warning the author has considered is theirs to
override and blocking would strand them behind a check they may have reason to skip.

Built medium-neutral where the cost is low, since GN adoption is the next consumer: the
assembler takes a reference-tier source, a unit list, and a leaf-entry renderer.

### `--prompts`

Unchanged entry point, thinner output, plus the per-image acceptance lines. Still writes
per-illustration files as the editable source, which `--package` aggregates — the GN
precedent where page files hold sections and `script-package` aggregates them.

## The anchor batch

Phase 1: a small set rendered and approved before the churn, so the long run has real images
to reference instead of descriptions.

Derived, not stored, so it cannot disagree with the plan. Four slots:

1. **Establisher** — the existing visual key: the illustration whose `canon_refs` cover the
   most ground, earliest.
2. **Darkest register** — first row with `register=darkest`.
3. **Brightest register** — first row with `register=brightest`.
4. **Later-state exemplar** — the illustration with the most resolved state entities whose
   governing transition is not the entity's first, ties broken by earliest `seq`. Where
   wardrobe and object state have moved furthest from opening conditions while still being
   early enough to lock them for everything after.

When `register` is unpopulated, slots 2 and 3 fall back to the first and last illustration in
story order, **and the fallback is reported** rather than presented as a choice. A silent
guess about which image is the darkest in the book is how you discover at image twenty that
nothing is.

Approving the batch is an author action: `--ingest` those rows, and the mode table moves to
Churn.

## Staleness

`_normalize_for_drift` moves from `canon.py` to `common.py` as `normalize_for_comparison()`,
with `canon.py` importing it. One function, no contract touched, behavior byte-identical —
asserted by test.

**A finding that reframes the drift story.** Nothing in the codebase *writes* canon-embed
markers. `canon.py` only reads and validates them; the sole other mention is
`templates/reference/visual-style.md` instructing authors to hand-embed. The current GN
prompts stage explicitly tells the model `do NOT paste` canon. So `check_canon_drift` guards
a v2-era convention the pipeline no longer generates.

The packet restores a legitimate consumer for it. `canon.md` and every entry in
`illustrations.md` contain verbatim copies of canon blocks, and those copies can drift from
their sources — which is exactly what `illus_anchor_copy_drift` detects. Drift detection is
not vestigial; its subject moves from hand-embedded page prompts to generated packets.

The full unification across the repo — canon drift, `cmd_evaluate`'s word-count proxy, and
these illustration checks — stays out of scope and is filed separately. Generalizing
`check_canon_drift` means parameterizing where copies live, where sources live, how ids
resolve, and what findings are named, plus re-homing `CanonFindingKind`, which
`build_cleanup_report`'s severity filtering depends on. This work is the second consumer.

For one release the repo has two drift implementations sharing a normalizer.

## Findings added

Under cleanup's existing "Interior Illustrations" category, joining `illus_orphan_marker`
and friends.

| Finding | Severity | Meaning |
|---|---|---|
| `illus_state_unknown_scene` | error | A transition names a scene that does not exist |
| `illus_evidence_not_found` | warning | An evidence quote is not in its scene's prose |
| `illus_state_unspecified` | warning | An illustration names an entity with no state at its scene |
| `illus_prose_changed` | warning | Scene prose differs from what an ingested render was made from |
| `illus_audit_stale` | warning | Prose changed since the audit ran |
| `illus_packet_stale` | warning | The packet is older than the plan, matrix, or canon |
| `illus_anchor_copy_drift` | warning | A packet anchor copy differs from its canon file |

`validate` fails on the error-severity finding; `cleanup` reports all of them. An unrendered
plan row stays valid in-flight state and is not a finding, unchanged from today.

## Testing

- **Canon adoption** — canon validation runs for `novel` projects and
  `canon_present_in_novel_project` no longer fires; creature-under-`characters/` and
  prop-under-`motifs/` resolve their registries; `embeds_as` absent is valid for `novel`.
- **Hand-edit safety net** — `--diagnose` warns when a canon file's `## Embeddable block`
  differs from a same-named `### Name` section in a still-present `illustration-direction.md`,
  and stays silent once that file is gone. No migration code to test.
- **State resolution** — forward walk; boundary case where the illustration's scene *is* the
  transition scene; no-transition case; transition naming a cut scene.
- **Granularity** — `{canon_id}-{aspect}` tracks resolve independently; a bare `canon_id`
  track resolves.
- **Overrides** — apply to their own illustration and do not leak to the next scene.
- **Evidence matching** — tolerates reflow and whitespace; reports a genuinely absent quote.
- **Audit pre-pass** — narrowing selects exactly the scenes mentioning tracked entities; every
  finding type fires on a crafted fixture; zero findings means no LLM call is made.
- **Packet assembly** — every section present; anchor strings byte-identical to their canon
  files; regeneration idempotent.
- **Anchor batch** — all four slots with `register` populated; the reported fallback when not.
- **Staleness** — digest changes when prose changes and not when whitespace does;
  `normalize_for_comparison` byte-identical to the old `_normalize_for_drift` across existing
  canon fixtures.
- **Coaching** — `--state` produces prose proposals under `full`, questions under `coach`, a
  blank seeded template under `strict`, and makes no API call under `strict`.

Fixture work: `tests/fixtures/test-project` (a novel project) gains `reference/canon/` files,
a `visual-state.csv`, and two illustration rows carrying `state_override` and `register`.

## Robustness requirements found in first real use

Phase 1 shipped and was exercised against a real 20-illustration book. Five things the
design did not anticipate. These are **authoring-robustness requirements on the skill**, not
migration mechanics — each one bites an author working normally, not just one converting an
old project.

### A canon file's name is constrained by its registry, and nothing says so up front

`canon_missing_registry_entry` matches the canon **filename stem** against the registry `id`
column, so `characters/keeper.md` is required when `characters.csv` says `keeper|Ember`, even
though the author thinks of that character as "Ember." Authors do not know this until a
finding tells them, and the finding arrives after the file is written.

**Requirement:** `--direction` derives entity canon ids from the registries, which is correct
and must stay. But a hand-added canon file must fail fast and legibly. Add a
`canon_id_not_in_registry` check that names the expected filename, and have the skill state
the constraint in Mode: Direct — the canon file is named for the registry id, not the
character's name.

### One anchor may legitimately describe two coupled entities

The real book had a single anchor covering the village *and* the Great Lamp at its center —
they are one visual subject, and describing them apart is artificial. The canon model is one
entity per file with a registry row, so the anchor had to be split.

**Requirement:** don't force the split silently. Splitting is defensible — each entity gets
its own row, `Related canon` links them, and `canon_refs` names both — but the *skill* must
say so, and `--prompts` must send coupled anchors together and adjacently so a model reads
them as one subject. A design decision worth recording rather than leaving to whoever hits it
next: **coupled entities stay separate files linked through `Related canon`**, because a joint
file would have no single registry row and could not be referenced independently by an
illustration that shows only one of them.

### Fresh entity stubs generate warning-severity noise proportional to cast size

A 14-file canon tree produced 28 `canon_missing_key` warnings — `appears_in` and
`first_appearance`, two per file — and `build_cleanup_report` counts every non-`info` finding
as an action item. That is the documented first step of the illustration flow filling the
cleanup report with work the author cannot usefully do yet, because neither field is knowable
before the plan exists.

**Requirement:** `appears_in` and `first_appearance` are `info` severity on an entity canon
file whose Embeddable block is populated but which no plan row references yet. Better still,
have `--plan` and `--prompts` **populate** them from `canon_refs` — the plan is the authority
on which illustrations feature an entity, and `render_order` already derives `first_appearance`
in effect when it computes `locks`. Deriving beats nagging.

### Findings must name their file

The canon findings printed 28 identical `missing required frontmatter key: appears_in` lines
with no filename. The `file` field is in the report CSV, but the console output is what an
author reads. **Requirement:** every canon finding's console line names its file.

### The direction-document safety net is nearly spent

`direction_anchor_mismatch` compares a slugified `### Name` heading against canon ids, so it
verifies only anchors whose display name already slugifies to its registry id — 7 of 10 on the
real book, skipping exactly the three that had to be renamed. The mechanism works (perturbing a
covered anchor fires the finding); its coverage is structurally thin precisely where risk is
highest.

Since there is no migration code and one project has now converted by hand, **this check
should be retired** rather than deepened. Keep it for one release, then delete it along with
`read_direction`, `find_section`, `direction_path`, `DIRECTION_SECTIONS`, and `ANCHORS_SECTION`
— it is the only remaining consumer of all five.

## Forward compatibility for asset transport

`storyforge publish` cannot upload illustration bytes at all (issue #284), which is being
fixed before Phases 2 and 3. Two constraints so that work does not have to be redone:

- **Asset transport is role-generic, not illustration-shaped.** The client function takes an
  asset list and a digest→local-path mapping supplied by its caller; it must not read
  `illustration-plan.csv` itself. The cover already needs a second source path into the same
  array, and Phase 3's packet will want to publish reference images the same way.
- **`ManifestAsset.role` widens to a Literal that can grow.** Today `illustration`; the cover
  fix adds `cover`. Phase 3 may add a packet or reference role. Keep the digest-diff logic
  indifferent to the role's value.

## Out of scope

- **GN convergence** — adopting the state matrix, contradiction audit, per-page acceptance
  criteria, and cross-page contrast checking into the page pipeline. Filed as a follow-up;
  the packet assembler is built medium-neutral in anticipation, and GN has a live book
  mid-production whose page files need a migration path.
- **Unified staleness** across the repo, and the fate of `embeds_as` and
  `story-summary.md`'s `_updated` timestamps.
- Automated per-image render inspection on our side. The packet's acceptance criteria move
  that work to the generating session, which is where the author wants it.
- Print-layout honoring of `full_page` / `double_page` in PDF output, still unautomated.
