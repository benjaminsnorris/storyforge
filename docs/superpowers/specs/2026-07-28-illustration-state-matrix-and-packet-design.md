# Illustration state matrix, contradiction audit, and handoff packet

**Date:** 2026-07-28
**Status:** design, approved in conversation
**Scope:** prose books only (`project.medium: novel`). Graphic-novel projects keep the page pipeline.

## Why

Twenty rendered interior illustrations for *The Lantern Folk* were reviewed against the
manuscript. Ten findings, three of them blockers. Sorting them by cause rather than by
severity says something the severity ordering hides:

| Cause | Findings |
|---|---|
| No record of what visual state is true when | pajamas two chapters past the line where the prose dresses them; Chapter 12 rendered lit when the prose has no light in it; the Great Lamp lit or dark; the surviving-lantern count |
| No per-image check against the governing prose | an image of an event that does not happen in the book; children beaming during the grimmest turn |
| No check across the set | three of the last four images are the same shot, so the emotional peak reads as a lull |
| A contradiction in the prose itself | Ch10 kills every lantern, Ch11 confirms it, Ch13 finds four still burning |

The existing flow cannot catch any of these. `--review` is a set-level checklist a human
fills in after the fact. Continuity anchors hold what must never change and have nowhere
to put what changes on schedule. Nothing reads a render against its scene.

This spec adds the missing data (a state matrix), the missing pre-generation check (a
contradiction audit), and changes the handoff from fifteen separate pastes to one packet.

## What changes about the handoff

Today `--prompts` writes a standalone 250–400 word prompt per illustration, each pasted
into an image model on its own. The author's lived experience is that hyper-detailed
per-image prompts underperform, and that a long-running session working from a shared
packet does better.

This narrows a documented principle, so the narrowing is recorded here rather than left
to look like drift. CLAUDE.md's #260/#263 principles — five-section template, 250–400
words, structure over brevity — were validated for **graphic-novel pages rendered one at
a time**, where the prompt was the only context the model had. In a packet the shared
context is present, so a thin per-illustration entry is not losing information; it is
declining to restate it fifteen times. What stays: verbatim-identical anchor strings,
positive framing for content, explicit orientation, no text. What changes: house style,
anchors, palette logic, and content limits move to packet-level sections and are stated
once.

The per-illustration prompt files remain the editable source and `--package` aggregates
them, following the GN precedent where page files hold sections and `script-package`
aggregates them into book-level documents.

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
  different set from the continuity anchors (things whose *design must not change*). They
  overlap: the Great Lamp has both an invariant design and a changing lit/dark state.
- `from_scene` — references `scenes.csv:id`. The transition takes effect here.
- `state` — one short phrase describing what is visibly true.
- `evidence` — a verbatim quote from `from_scene`'s prose that establishes it.

**Resolution.** The state of entity `E` at scene `S` is the transition for `E` with the
greatest `scenes.csv:seq` among those whose `from_scene` seq is `<= S`'s seq. No matching
transition means the state is unspecified, which is reportable when an illustration in
that scene names `E` in its `canon_refs`.

**Why sparse rather than a dense scene × entity grid.** Three reasons. It matches the
`reference/outline.md` precedent, where a CSV is the source and a rendered view is
derived. It survives revision — our scene-map operations insert, merge, split, and
reorder, and a transition keyed "from `s04` onward" still means something after a scene
lands at `s05`, where a dense grid would have no row and fall silently blank. And one
authorial decision ("from Chapter 4 they arrive dressed") is recorded once instead of
restated in every illustrated scene from 4 to 15, each restatement being a cell that can
go stale on its own.

The trade: sparse can reference a scene that has since been cut, which is why
`illus_state_unknown_scene` is an error rather than a warning. A dense grid cannot have
that bug because it never names a scene it is not keyed by.

### `illustration-plan.csv` gains three columns

- `state_override` — `;`-delimited `entity:state` pairs for visual state true in *this
  image only* and not persisting. Tear-streaked faces, arms raised against a light. A
  pure transition log would have to write a change and then a change back, which is
  nonsense; this is where non-persisting state goes. Split on the **first** colon, so a
  state may itself contain one.
- `register` — optional, one of `darkest` / `brightest`, marking the lighting extremes of
  the book. Feeds anchor-batch selection. Populated by `--plan` under `full` coaching,
  empty otherwise.
- `scene_digest` — recorded at ingest. The normalized digest of the scene prose the render
  was made from, so "the prose changed under this image" becomes detectable.

### `working/illustration-contradictions.md` — the audit report

Read-only. Written by `--audit`.

### `manuscript/illustration-packet/` — the handoff bundle

```
manuscript/illustration-packet/
├── README.md            two phases, how to work the packet, what to return
├── art-direction.md     copy of reference/illustration-direction.md
├── anchors.md           continuity anchors, verbatim
├── visual-state.md      derived dense view: scene × entity
├── illustrations.md     per-illustration entries
├── reference-images.md  which files to upload, in what order, what each is for
└── acceptance.md        global acceptance criteria and sequence-contrast rules
```

Regenerated wholesale by `--package`, so it is a render and never hand-edited. The derived
state view lives here rather than in `reference/` specifically so there is no second file
to keep fresh.

Reference images are **not copied** into the packet; `reference-images.md` carries
project-relative paths into `manuscript/assets/illustrations/`. The author uploads from
disk, and a copy would be a second thing to invalidate.

**The load-bearing invariant:** anchor strings in `anchors.md` and in every entry in
`illustrations.md` must be **byte-identical** to their source in
`reference/illustration-direction.md`. Likeness continuity is the whole reason anchors
exist and it depends on the string not varying. A test asserts this equality, in the same
spirit as the existing assertion that publish `content_html` is byte-identical with and
without illustrations.

### Per-illustration entry shape

Thin. Target 120–180 words, against today's 250–400, because the packet carries the rest.

```markdown
### lamp-relit

- Scene: `s14-the-keepers-flame` · Layout: double_page · Aspect: landscape

**Beat.** The Great Lamp catches and the light drives outward through the woods.

**In frame.** Wide elevated view of the village. The Lamp blowing out the centre of the
frame as the light source. Gold visibly travelling between the trunks. Both children
small and together, arms up against the glare.

**State.** Nora: filthy moss-green cardigan, brown ankle boots. Leo: filthy rust-red
hooded jacket. Great Lamp: erupting, gold. Village lights: a few weak survivors.

**Must not appear.** Ember. A second Great Lamp. Blue, violet, or magenta life-flames.
Calm or modest illumination.

**Contrast.** Much wider and brighter than `lamp-embers-choice`, which precedes it. This
is the brightest image in the book.

**Self-check before delivering.**
- [ ] Nora and Leo in outdoor clothes, filthy
- [ ] Lamp is cooking-pot-sized, multi-wick, in its root cradle
- [ ] Light visibly reaches the background trunks
- [ ] Ember absent
- [ ] Flames amber or gold only (Pip alone is green)
- [ ] Unmistakably the brightest image in the set
- [ ] Landscape, faces and Lamp clear of the centre gutter, no lettering
```

**`Must not appear` is a deliberate exception to positive framing.** #263 established that
negated content keywords leak into the render, and that rule stands for description. But
the Lantern Folk set produced magenta lanterns in a book whose entire colour logic is
gold-is-life / blue-is-death, and the positively-framed instruction ("Folk lanterns in
warm amber and gold") did not prevent it. The exception is narrow and enumerable: **named
entities that must be absent, and violations of stated colour logic.** It is not a general
licence to write prohibitions, and orientation plus no-text remain the other two
exceptions.

**`State` lists only the entities in the row's `canon_refs`**, resolved from the matrix and
then overlaid with `state_override`. Sending the whole cast wastes tokens and invites the
model to include people who are not in the frame.

## Commands

All four are flags on `illustrate`. The author types none of them: the skill's mode table
detects state and offers the command, and `--diagnose` reports which rung the project is
on. Flags are output, not vocabulary to memorize.

| State detected | Mode | Offered |
|---|---|---|
| No direction document | Direct | `--direction` |
| Direction, no plan | Plan | `--plan` |
| Plan exists, no state matrix | **State** | `--state` |
| Matrix exists, audit unrun or stale | **Audit** | `--audit` |
| Audit clean, rows at `planned` | Art-direct | `--prompts` |
| Prompts written, no packet or packet stale | **Package** | `--package` |
| Packet built, any anchor-batch row not `ingested` | **Anchor** | render these N, approve |
| Every anchor-batch row `ingested`, others not | **Churn** | hand the packet over |
| Non-anchor files on disk | Ingest | `--ingest PATH` |
| Most rows `ingested` | Review | `--review` |

"Audit clean" means **no error-severity findings**. Warnings do not gate the stage; they
are surfaced and the author decides, consistent with how `cleanup` treats warnings
elsewhere. Anchor and Churn are distinguished by whether every *anchor-batch* row has
reached `ingested`, not by whether any file exists, so ingesting the batch advances the
stage rather than looking like ordinary ingest.

Three surfaces learn the new stages: the skill's mode table, `--diagnose` as stage
reporter, and `status`/`forge`, which today cannot surface illustration work at all.

### `--state`

Writes or refreshes `reference/visual-state.csv`. Coaching-aware, following the house
pattern: `full` proposes transitions by reading the prose and reports each with its
evidence quote; `coach` writes a questions template to
`working/coaching/visual-state-brief.md`; `strict` writes a blank template seeded with the
entity list drawn from the direction document's anchors and the character/location
registries.

### `--audit`

The pre-generation contradiction pass. Read-only: it never edits prose or the matrix.

**Deterministic pre-pass**, no API cost:

1. `from_scene` values that do not resolve to a scene → `illus_state_unknown_scene` (error).
2. `evidence` quotes not found in `from_scene`'s prose → `illus_evidence_not_found`
   (warning). Uses the existing whitespace-tolerant `find_anchor`, so a quote survives
   reflow.
3. Illustrations whose `canon_refs` name an entity with no resolved state at that scene →
   `illus_state_unspecified` (warning).
4. Scenes that mention a tracked entity and lie between that entity's transitions —
   the narrowed set the LLM reads.

**LLM pass** over the narrowed set only: reports prose that *asserts* a state
contradicting the derived matrix, each finding carrying the scene id, the quote, and which
transition it disagrees with. Sonnet; analytical work, not creative.

This is what catches the Ch10/Ch11/Ch13 lantern conflict, and it is worth being precise
about why the matrix alone cannot. The author writes two transitions — village-lights goes
dark at s10, four survive at s13 — and nothing about them disagrees, because things are
allowed to change. The contradiction is that Ch11 *asserts* a state ("Are they all gone?"
/ "Yes.") that the s10→s13 span cannot support. Only reading prose against the matrix
finds it.

Records per-scene digests of everything it read to
`working/illustration-audit-provenance.csv`, so `illus_audit_stale` is detectable.

### `--package`

Assembles the bundle. No API calls. Warns loudly on unresolved audit findings and on a
never-run audit; does not block, because a warning the author has considered is their call
to override and blocking would strand them behind a check they may have good reason to
skip.

### `--prompts`

Unchanged entry point, thinner output, plus the self-check section. Still writes
per-illustration files as the editable source.

## The anchor batch

Phase 1 of the two-phase flow: a small set rendered and approved before the churn, so the
long run has real images to reference instead of descriptions.

Derived, not stored, so it cannot disagree with the plan. Four slots:

1. **Establisher** — the existing visual key: the illustration whose `canon_refs` cover the
   most ground, earliest.
2. **Darkest register** — first row with `register=darkest`.
3. **Brightest register** — first row with `register=brightest`.
4. **Later-state exemplar** — the illustration with the most resolved state entities whose
   governing transition is not the entity's first, ties broken by earliest `seq`. That is
   the image where wardrobe and object state have moved furthest from opening conditions
   while still being early enough to lock them for everything after.

When `register` is unpopulated, slots 2 and 3 fall back to the first and last illustration
in story order, **and the fallback is reported** rather than presented as a choice. A
silent guess about which image is the darkest in the book is how you discover at image
twenty that nothing is.

Approving the batch is an author action: `--ingest` the four, then the mode table moves to
Churn.

## Staleness

`_normalize_for_drift` moves from `canon.py` to `common.py` as
`normalize_for_comparison()`, with `canon.py` importing it. One function, no contract
touched, behavior byte-identical — asserted by test.

Everything else stays put. The full unification of staleness detection across the repo —
`canon.py`'s drift check, `cmd_evaluate`'s word-count proxy, and these illustration checks
— is deliberately **not** in this spec. There is one well-understood consumer today, and
generalizing `check_canon_drift` means parameterizing where copies live, where sources
live, how ids resolve, and what findings are named, plus re-homing `CanonFindingKind`,
which is documented as the single source of truth for canon-category types and is consumed
by `build_cleanup_report`'s severity filtering. Designing that interface from one consumer
plus guesses about the second produces an abstraction that fits neither. This work is the
second consumer; the unification issue is filed to follow it, informed by what these three
checks actually turn out to need.

For one release the repo has two drift implementations sharing a normalizer. That is
cheaper than an abstraction designed blind.

## Findings added

All under cleanup's existing "Interior Illustrations" category, joining
`illus_orphan_marker` and friends.

| Finding | Severity | Meaning |
|---|---|---|
| `illus_state_unknown_scene` | error | A transition names a scene that does not exist |
| `illus_evidence_not_found` | warning | An evidence quote is not in its scene's prose |
| `illus_state_unspecified` | warning | An illustration names an entity with no state at its scene |
| `illus_prose_changed` | warning | Scene prose differs from what an ingested render was made from |
| `illus_audit_stale` | warning | Prose changed since the audit ran |
| `illus_packet_stale` | warning | The packet is older than the plan, matrix, or direction document |
| `illus_anchor_copy_drift` | warning | A packet anchor copy differs from the direction document |

`validate` fails on the error-severity finding; `cleanup` reports all of them. An
unrendered plan row stays valid in-flight state and is not a finding, unchanged from today.

## Testing

- **State resolution** — forward walk; boundary case where the illustration's scene *is*
  the transition scene; no-transition case; transition naming a cut scene.
- **Overrides** — apply to their own illustration and do not leak to the next scene.
- **Evidence matching** — tolerates reflow and whitespace; reports a genuinely absent quote.
- **Audit pre-pass** — narrowing selects exactly the scenes mentioning tracked entities;
  every finding type fires on a crafted fixture; zero findings means no LLM call is made.
- **Packet assembly** — every section present; anchor strings byte-identical to the
  direction document; regeneration is idempotent.
- **Anchor batch** — all four slots with `register` populated; the reported fallback when
  it is not.
- **Staleness** — digest changes when prose changes and not when whitespace does;
  `normalize_for_comparison` byte-identical to the old `_normalize_for_drift` across the
  existing canon fixtures.
- **Coaching** — `--state` produces prose proposals under `full`, questions under `coach`,
  a blank seeded template under `strict`, and makes no API call under `strict`.

Fixture work: the existing `tests/fixtures/test-project` gains a `visual-state.csv` and
two illustration rows carrying `state_override` and `register`.

## Out of scope

- Unified staleness across the repo — filed as a follow-up issue.
- Whether the `_updated` timestamps on `story-summary.md` survive; that follow-up decides.
- Automated per-image render inspection on our side. The packet's self-check moves that
  work to the generating session, which is where the author wants it.
- Print-layout honoring of `full_page` / `double_page` in PDF output, still unautomated.
- Graphic-novel mode, which keeps the page pipeline.
