# Elaboration levels and artifact shapes

Research design doc for issue [#225](https://github.com/benjaminsnorris/storyforge/issues/225), under the umbrella [#224](https://github.com/benjaminsnorris/storyforge/issues/224).

Status: **revised after review pass** (2026-05-24). The big revisions: the structural tier is now *three* sub-tiers (spine / anchors / manuscript) with discrete artifacts at each, not one CSV with status flags; story-summary.md gains a Theme section and a themes registry; story-architecture.md now points to story-summary.md rather than duplicating content. See the synthesis doc for full context.

---

## TL;DR

The proposal is **eight levels in three tiers**, with each tier holding its own discrete artifacts so a reader can point at "the spine" or "the architecture" as a single thing.

**Prose tier (free-form, LLM-scored):** all in one file
- 0. Logline (1 sentence)
- 1. Synopsis (1 paragraph)
- 2. Act-shape (3 paragraphs)
- *Theme* (2–4 sentences) — what the story argues, paired with a themes registry

**Structural-anchor tier (discrete CSVs, each a thing you can read):**
- 3. Spine — `reference/spine.csv` (5–10 irreducible events)
- 4. Architecture — `reference/architecture.csv` (15–25 anchor scenes with dramatic-skeleton metadata)

**Manuscript tier (existing pipeline, scene rows + companions):**
- 5. Scene map — `reference/scenes.csv` (40–60 scenes — anchors plus interstitial scenes)
- 6. Briefs — `reference/scene-briefs.csv` (same scene IDs, status `briefed`)
- 7. Draft — `scenes/{id}.md` files (same scene IDs, prose)

Two new reference columns make the level boundaries explicit:
- `spine_event` on `architecture.csv` — each architecture scene names its parent spine event.
- `architecture_scene` on `scenes.csv` (optional) — each manuscript scene either is, or sits adjacent to, an architecture anchor; or it's purely interstitial.

The bibles, registries, and voice profile sit **alongside** the hierarchy as cross-cutting reference data. The themes registry joins them.

---

## Why eight levels in three tiers

A boundary is worth a level only if it has a real semantic discontinuity — a question that the level below can answer and the level above cannot. The eight boundaries each pass that test.

The **three tiers** come from a different observation: levels within a tier share artifact identity, but levels across tiers expand the row count.

- Prose tier: three levels, one file, three sections. No row expansion (it's prose).
- Structural-anchor tier: two levels, two CSVs. Spine has 5–10 events; architecture has 15–25 anchor scenes. Each architecture row names its parent spine event.
- Manuscript tier: three levels, shared row identity. The scene map has 40–60 rows; briefs and drafts attach more data to the same rows. No further row expansion within the tier.

The tier boundaries are where new artifacts get created and rows multiply. Within a tier, rows can be enriched without being duplicated.

The boundary I considered hardest is still **1 → 2 (synopsis → act-shape)**. They're both prose summaries. The argument for keeping them separate: a one-paragraph synopsis answers "what kind of story is this?" while a three-paragraph act-shape answers "where are the turning points and how does each act bear its load?" Two different questions, two different levels — but they live in the same artifact.

The boundary I had wrong in the original draft was **4 → 5 (architecture → scene map)**. The original said scene-map "adds operational metadata, not new structural decisions." That was incomplete. The scene map *expands* the scene count — it adds interstitial scenes (transitions, breathers, B-story, character moments) that aren't on the architectural skeleton. Architecture is the dramatic skeleton; scene map is the full manuscript inventory. They belong to different tiers because the row counts differ.

---

## The level taxonomy

### Prose tier (all in `reference/story-summary.md`)

| Level | Name | Scope | Question it answers | What it can't answer |
|---|---|---|---|---|
| 0 | Logline | 1 sentence | Who is this about and what's the central tension? | Act-shape, character arcs, world specifics |
| 1 | Synopsis | 1 paragraph (~5–7 sentences) | How does the story open, escalate, and resolve thematically? | Where the turning points land; the dramatic shape |
| 2 | Act-shape | 3 paragraphs (one per act) | What's the load-bearing structure of each act? Where are the major turns? | The specific events; who is on stage |

A fourth section, **Theme** (2–4 sentences), names what the story argues. It's not a numbered level (it doesn't elaborate downward in the same way), but it sits in the same file alongside the prose-tier sections and is queryable for scoring.

### Structural-anchor tier (each its own CSV)

| Level | Name | Artifact | Scope | Question it answers |
|---|---|---|---|---|
| 3 | Spine | `reference/spine.csv` | 5–10 rows | What are the load-bearing events of the story? |
| 4 | Architecture | `reference/architecture.csv` | 15–25 rows, each with `spine_event` → spine.csv | What's the dramatic skeleton — value shifts, action/sequel, POV at each anchor? |

The architecture scenes are *not* a subset of manuscript scenes — they're a separate artifact representing the dramatic skeleton. When the author advances to scene map, the architecture rows seed scenes.csv (each architecture scene becomes a manuscript scene with an `architecture_scene` self-reference) and the author elaborates from there.

### Manuscript tier (shared scene-row identity)

| Level | Name | Artifact | Scope | Question it answers |
|---|---|---|---|---|
| 5 | Scene map | `reference/scenes.csv` + `reference/scene-intent.csv` | 40–60 rows, each with optional `architecture_scene` → architecture.csv | What's the full plot inventory with operational metadata? |
| 6 | Briefs | `reference/scene-briefs.csv` | Same row IDs as scenes.csv, status `briefed` | What is the drafting contract for each scene? |
| 7 | Draft | `scenes/{id}.md` | Same row IDs, prose | How does it actually read? |

The status column on scenes.csv (`mapped | briefed | drafted | polished`) tracks per-scene level within this tier. No row expansion within the manuscript tier.

### What changes vs. today

- **Prose tier**: entirely new as first-class artifacts. `project.logline` exists in `storyforge.yaml` today but isn't elaborated/scored as a level; no synopsis, act-shape, or theme artifact exists.
- **Structural-anchor tier**: spine and architecture get their own CSVs. Today both are tracked as `status` flags on `scenes.csv`, which conflates "5-10 spine events" and "15-25 architecture beats" into the same row set. This change separates them into discrete artifacts.
- **Manuscript tier**: existing pipeline, no structural change. The `architecture_scene` column on scenes.csv is new; it's optional (purely interstitial map scenes leave it empty).

Migration for existing projects: a one-time `cmd_migrate` step extracts spine events from the current `status=spine` rows into `spine.csv`, copies architecture-status rows into `architecture.csv` (and removes them from scenes.csv if they aren't yet at map stage), and rewrites `spine_event` / `architecture_scene` references where derivable. For Ashes specifically, this is mechanical because the project has 24 architecture-status scenes — the author or migrate identifies the 5–10 that should be the spine and the rest become architecture rows.

---

## Artifact shapes and storage

### Prose tier — single file with three sections

The three prose-tier levels live together in `reference/story-summary.md`. One file rather than three because:

- They're conceptually one thinking unit (story-as-prose at varying granularity).
- Reviewing them side-by-side is more useful than reviewing them apart.
- A single file is a single git diff target, simpler to sync, simpler to score.
- Each section can still be queried/scored independently — the boundary between levels is the `##` heading, not the file boundary.

Proposed format:

```markdown
# Story summary

<!--
Edit this file freely. `storyforge sync` keeps the structural tier
aligned. Each section corresponds to an elaboration level (#225).
-->

## Logline

One sentence: protagonist + want + obstacle + stakes.

## Synopsis

One paragraph, ~5–7 sentences. Opens, escalates, resolves.

## Act-shape

### Act 1
What this act bears. Where the inciting incident lands.

### Act 2
What this act bears. Where the midpoint shifts.

### Act 3
What this act bears. The climax demand and the resolution.

## Theme

Two to four sentences naming what the story is arguing — its
central question or claim. Internal use, not pitch material.
Themes that recur as concrete imagery should be registered in
`reference/themes.csv` and tagged per-scene via the `theme_threads`
column on `scene-intent.csv`.
```

The `## Logline`, `## Synopsis`, `## Act-shape`, `## Theme` headers are load-bearing for parsing. Within each section, prose is free-form (no required sub-structure for logline / synopsis / theme; act-shape gets `### Act N` sub-sections).

### Structural-anchor tier — two new CSVs

| Level | Artifact | Columns | Notes |
|---|---|---|---|
| 3 Spine | `reference/spine.csv` | `id, seq, title, function, part` | 5–10 rows. Each row is an irreducible story event. `part` partitions events into acts so the architecture tier can spread anchors proportionally. |
| 4 Architecture | `reference/architecture.csv` | `id, seq, title, part, pov, spine_event, action_sequel, emotional_arc, value_at_stake, value_shift, turning_point` | 15–25 rows. `spine_event` references `spine.csv.id` (every architecture row names its parent spine event). Carries the dramatic-skeleton metadata that today lives on scenes.csv at status `architecture`. |

A derived human-readable view is rendered as `reference/spine.md` and `reference/architecture.md` by `scenes-export`, just as `scenes-review.md` is rendered today. The CSV is the substrate; the .md is the pointable artifact.

### Manuscript tier — existing files, one new column

| Level | Files | Columns added at this level |
|---|---|---|
| 5 Scene map | `reference/scenes.csv` + `reference/scene-intent.csv` | All non-anchor columns on scenes.csv (`location, timeline_day, time_of_day, duration`, etc.); MICE / characters / on_stage on intent; new column `architecture_scene` on scenes.csv references `architecture.csv.id` (optional — interstitial scenes leave it empty) |
| 6 Briefs | + `reference/scene-briefs.csv` | Full brief schema (goal, conflict, outcome, etc.); GN columns when applicable. Same row IDs as scenes.csv. |
| 7 Draft | + `scenes/{id}.md` | `word_count` on scenes.csv; prose in scene files. Same row IDs. |

The status column on scenes.csv tracks per-scene progress within the manuscript tier: `mapped | briefed | drafted | polished`. The earlier statuses (`spine`, `architecture`) are no longer used — those rows live in their own CSVs now.

### Relationship of `project.logline` (yaml) to `## Logline` (md)

Today the logline lives in `storyforge.yaml`. Proposal: **`reference/story-summary.md § Logline` becomes canonical**; `project.logline` is deprecated as an input. A one-time migration on first run copies the yaml value into the new md if the md is absent. Code that currently reads `project.logline` can be updated incrementally to read from the md, or a small helper in `common.py` can resolve from whichever is present.

This is a backward-compat concern but a small one — `project.logline` is used in only a few places (init, prompt building for elaboration). It's a clean migration.

### Relationship to `reference/story-architecture.md`

This file already exists and contains premise + theme + three-level conflict + ending. Most of that content overlaps with what now belongs in `story-summary.md` (premise ≈ synopsis; theme moves into the Theme section). The bits unique to story-architecture.md are the three-level conflict framing and the ending.

**Revision: story-architecture.md becomes a thin pointer + the unique content.** Specifically:

- At the top, link to `story-summary.md` as the canonical source for logline / synopsis / act-shape / theme.
- Keep only the content that doesn't live anywhere else: the three-level conflict structure and the ending.
- Do not duplicate content. When the synopsis changes, the architecture file is unaffected (because the architecture file doesn't carry the synopsis anymore).

This drops the "two files describe the same content" maintenance burden and makes each file's role clear.

---

## Cross-cutting reference artifacts

Bibles, registries, and the voice profile are **not** levels. They are reference data that every level should be consistent with. They live alongside the hierarchy as a separate graph dimension.

The cross-cutting set, as it stands today:

| Artifact | Format | Role |
|---|---|---|
| `reference/character-bible.md` | free-form md | Full character documentation |
| `reference/world-bible.md` | free-form md | Setting + systems |
| `reference/voice-guide.md` | free-form md | Authorial voice and tone fingerprint |
| `reference/voice-profile.csv` | pipe-csv | Structured voice constraints (banned words, preferred patterns) |
| `reference/characters.csv` | pipe-csv | Character registry |
| `reference/locations.csv` | pipe-csv | Location registry |
| `reference/mice-threads.csv` | pipe-csv | MICE thread registry |
| `reference/motif-taxonomy.csv` | pipe-csv | Motif registry — concrete recurring elements (images, objects, sounds, phrases) that carry thematic weight |
| `reference/themes.csv` | pipe-csv (new) | Theme registry — abstract questions/arguments the story makes. Referenced by `theme_threads` on scene-intent.csv. See note below on themes vs motifs. |
| `reference/knowledge.csv` | pipe-csv | Story-fact registry |
| `reference/values.csv` | pipe-csv | Value registry (for value_at_stake) |
| `reference/physical-states.csv` | pipe-csv | Per-character physical state |
| `reference/timeline.md` | free-form md | Chronological reference |
| `reference/key-decisions.md` | free-form md | Author constraints |

**Relationship to levels (for the future scoring design, #227):**

- **Registries** (the `.csv` files) become the deterministic check against any level's structural data: every `value_at_stake` in scene-intent must be in `values.csv`; every `characters` entry in scene-intent must be in `characters.csv`; every motif in scene-briefs must be in `motif-taxonomy.csv`.
- **Bibles** (the `.md` files) feed the LLM faithfulness checks: does this scene's brief honor the character voice and constraints in the bible?
- These checks apply at *every level*, not just one. The logline should respect the character bible's notion of the protagonist; the briefs should respect the voice guide; the draft should respect both.

The bibles and registries themselves can become richer / drift over time — they're living documents. The scoring design (#227) needs to be honest about that: the bibles are reference data *now*, but a discovery at level 7 (draft) might reasonably propagate back to the bible. That's a cascade case (#226), and it crosses the prose/reference boundary in addition to the level boundaries.

**Themes vs motifs** — a note since this is a new registry. Themes are *abstract* questions or claims the story is making ("what does it mean to remember?", "power corrupts"). Motifs are *concrete* recurring elements that carry thematic weight (a specific image, object, phrase, sound). The relationship is many-to-many: one theme can be carried by several motifs; one motif can serve several themes. They're kept as separate registries because conflating them loses information — `legibility` is a theme but not a motif; `wire spectacles` is a motif that might serve `legibility` as one of its themes. Per-scene tracking lives in two columns: `theme_threads` on scene-intent.csv (which abstract concerns this scene engages) and `motifs` on scene-briefs.csv (which concrete recurring elements appear in this scene).

---

## Common metadata

The prose tier benefits from a small amount of explicit metadata so the cascade machinery can detect what's derived from what. I propose YAML frontmatter on `story-summary.md`:

```yaml
---
logline_updated: 2026-05-24
synopsis_updated: 2026-05-24
act_shape_updated: 2026-05-24
theme_updated: 2026-05-24
---
```

A timestamp per section, not per-file. That gives the cascade enough signal to ask "the logline changed after the synopsis — does the synopsis still hold?"

For the structural tiers, the discrete artifacts (`spine.csv`, `architecture.csv`, `scenes.csv` + companions) carry their own git timestamps. The cascade combines mtime with a content-hash cache (see the cascade synthesis) to distinguish typo fixes from semantic edits.

---

## What's deliberately not in this doc

- **Cascade mechanics** — how a change at one level propagates to others. That's #226.
- **Scoring** — per-level quality rubrics and cross-level fidelity. That's #227.
- **Prompts** — how each level is generated or expanded. Implementation, after all three research issues land.
- **CLI surface** — whether `storyforge elaborate logline` becomes a thing, or whether the prose tier is author-only. Cascade design (#226) will surface this.

---

## Open questions / things to push back on

1. **Is the prose tier really three levels, or one?** The proposal treats logline / synopsis / act-shape as three separate scored levels but one artifact. If in practice they always move together (you can't change one without re-doing the others), they might be one level with three views. Test this assumption with real iterations on Ashes once implemented.

2. **~~Should story-architecture.md be absorbed into story-summary.md?~~** *Resolved: architecture file becomes a thin pointer to summary + only the unique content (three-level conflict, ending). No duplication.*

3. **What about projects that start with a beat sheet, treatment, or outline instead of a logline?** Real-world authoring rarely starts at level 0. The system needs to be hospitable to entering at any level. Implementation concern, not a taxonomy concern — flag and revisit.

4. **~~Is the spine really a separate level from architecture, or just architecture with fewer scenes?~~** *Resolved: separate. They live in different artifacts (`spine.csv` and `architecture.csv`) and the architecture rows explicitly reference their parent spine event.*

5. **GN mode and the prose tier.** The prose tier as proposed makes no medium distinction — a logline is a logline whether the medium is novel or graphic novel. GN-specific structure (page-turn beats, panel rhythm) starts at the structural tier. Confirm with a GN project iteration.

---

## How each level supports iteration

Defining the levels alone doesn't make the system useful for iteration — the author also needs ways to (a) tell whether *this version* of a level is any good and (b) decide between *multiple candidates* at the same level. The scoring doc handles both, but worth noting the contract here so the levels make sense:

- **Per-level scoring is split into floor and ceiling.** Floor checks ask "is this level complete and consistent?" — they're mostly deterministic and they're what `storyforge score --level N` reports. Ceiling sketches name what separates passable from excellent at the level; they inform LLM prompts and give the author shared language for what iteration is reaching for. The floor catches broken; the ceiling targets great. Full per-level rubrics live in the [scoring doc](2026-05-24-elaboration-scoring-design.md).

- **`storyforge score --compare` lets the author iterate across alternatives.** When the author drafts three loglines, two competing synopses, or alternative spines, the comparison primitive renders a multi-axis report showing what each candidate does best — without declaring a winner. The author decides; the system surfaces. Most useful at the prose tier and at the spine level; less common at the manuscript-tier levels where full-artifact alternatives are rare.

- **Boundaries between levels use diff + verdict, not score.** Per the synthesis: when an upper level changes and the lower level may be out of date, the LLM produces a structured diff, and the verdict is recorded (proposed by the LLM in `full` coaching, by the author in `strict`). The verdict persists; the boundary isn't re-flagged unless content changes materially.

These three mechanisms together — floor/ceiling at each level, comparison across alternatives, diff+verdict across boundaries — are what the level taxonomy is in service of. The taxonomy without those scoring mechanisms is just an organizational chart.

---

## Implementation sketch (informational only)

For when the three research docs converge and we move to building:

- New file templates: `templates/reference/story-summary.md`, `templates/reference/themes.csv`, `templates/reference/spine.csv`, `templates/reference/architecture.csv`.
- `storyforge init` writes story-summary.md with the project's seed logline, and creates empty spine.csv / architecture.csv / themes.csv with their headers.
- A small `parse_story_summary(project_dir)` helper parses the four sections (Logline / Synopsis / Act-shape / Theme) via `## ` headers, returns a dict.
- `storyforge sync` extended to render derived markdown for the new structural-anchor artifacts: `reference/spine.md` and `reference/architecture.md` (sibling of the existing `scenes-review.md`).
- Migrations:
  - On first run, if story-summary.md is absent and `storyforge.yaml:project.logline` is present, scaffold the file with the logline filled in and synopsis/act-shape/theme empty.
  - For existing projects whose spine and architecture rows currently live as `status=spine` / `status=architecture` on scenes.csv: `cmd_migrate` extracts spine rows into spine.csv (preserving IDs), copies architecture rows into architecture.csv, and rewrites references where derivable. The author confirms or adjusts the spine event count.

Nothing here is committed; this section is just to confirm the taxonomy maps cleanly to an implementation plan when it's time.
