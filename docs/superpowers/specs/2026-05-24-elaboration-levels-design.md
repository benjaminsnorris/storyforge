# Elaboration levels and artifact shapes

Research design doc for issue [#225](https://github.com/benjaminsnorris/storyforge/issues/225), under the umbrella [#224](https://github.com/benjaminsnorris/storyforge/issues/224).

Status: **draft**, expects iteration. Implementation out of scope.

---

## TL;DR

The proposal is **eight levels in two tiers**, with two new artifacts at the top and the existing pipeline carrying the rest.

**Prose tier (free-form, LLM-scored):**
- 0. Logline (1 sentence)
- 1. Synopsis (1 paragraph)
- 2. Act-shape (3 paragraphs)

**Structural tier (CSV-backed, mostly deterministic):**
- 3. Spine (5–10 events)
- 4. Architecture (15–25 scenes)
- 5. Scene map (40–60 scenes with operational metadata)
- 6. Briefs (drafting contracts)
- 7. Draft (prose)

Levels 0–2 are new and live in a new file `reference/story-summary.md`. Levels 3–7 already exist; this design reframes them but adds no new schema.

The bibles, registries, and voice profile sit **alongside** the hierarchy as cross-cutting reference data, not above or within it.

---

## Why eight levels and not four, or twelve

A boundary is worth a level only if it has a real semantic discontinuity — a question that the level below can answer and the level above cannot. The eight proposed boundaries each pass that test; collapsing any of them would either hide a real gap (e.g., merging spine into architecture loses the irreducible-events question) or paper over a quality leap that needs its own scoring rubric.

The boundary I considered hardest is **1 → 2 (synopsis → act-shape)**. They're both prose summaries. The argument for keeping them separate: a one-paragraph synopsis answers "what kind of story is this?" while a three-paragraph act-shape answers "where are the turning points and how does each act bear its load?" The act-shape names the load-bearing structure that the synopsis only gestures at. Two different questions, two different levels.

A boundary I considered adding but rejected: between architecture and scene-map at "draft scene order." The current architecture stage already produces ordered scenes, so there's no real semantic gap there — the scene-map stage adds *operational* metadata (location, timeline, cast), not new structural decisions.

---

## The level taxonomy

### Prose tier

| Level | Name | Scope | Question it answers | What it can't answer |
|---|---|---|---|---|
| 0 | Logline | 1 sentence | Who is this about and what's the central tension? | Act-shape, character arcs, world specifics |
| 1 | Synopsis | 1 paragraph (~5–7 sentences) | How does the story open, escalate, and resolve thematically? | Where the turning points land; the dramatic shape |
| 2 | Act-shape | 3 paragraphs (one per act) | What's the load-bearing structure of each act? Where are the major turns? | The specific events; who is on stage |

### Structural tier

| Level | Name | Scope | Question it answers | What it can't answer |
|---|---|---|---|---|
| 3 | Spine | 5–10 irreducible events | What are the load-bearing events of the story? | Action/sequel rhythm; subplot weave |
| 4 | Architecture | 15–25 scenes | What's the dramatic rhythm — value shifts, action/sequel, character POV? | Where each scene happens, who's there, MICE thread weave |
| 5 | Scene map | 40–60 scenes | What's the full plot inventory with operational metadata (location, timeline, cast)? | Specific goals, conflicts, key dialogue, motifs |
| 6 | Briefs | All scenes | What is the drafting contract for each scene? | How the prose actually reads |
| 7 | Draft | All scenes | How does the prose actually read? | (terminal) |

### What changes vs. today

- Levels 0–2 are **new** as first-class artifacts. `project.logline` exists in `storyforge.yaml` today but isn't elaborated/scored as a level. No synopsis or act-shape artifact exists.
- Levels 3–7 already exist exactly as documented above. The existing `scene.status` column already tracks per-scene level: `spine | architecture | mapped | briefed | drafted | polished`.

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
```

The `## Logline`, `## Synopsis`, `## Act-shape` headers are load-bearing for parsing. Within each section, prose is free-form (no required sub-structure for logline and synopsis; act-shape gets `### Act N` sub-sections).

### Structural tier — already in CSVs

No new artifacts. The structural levels reuse the existing three-file CSV model:

| Level | Files | Columns added at this level |
|---|---|---|
| 3 Spine | `reference/scenes.csv`, `reference/scene-intent.csv`, `reference/story-architecture.md` | `id, seq, title` (scenes); `function` (intent); narrative framing (architecture md) |
| 4 Architecture | same | `part, pov` (scenes); `action_sequel, emotional_arc, value_at_stake, value_shift, turning_point` (intent) |
| 5 Scene map | same | `location, timeline_day, time_of_day, duration` (scenes); `characters, on_stage, mice_threads` (intent) |
| 6 Briefs | + `reference/scene-briefs.csv` | full brief schema (goal, conflict, outcome, etc.); GN columns when applicable |
| 7 Draft | + `scenes/{id}.md` | `word_count` (scenes); prose in scene files |

The `scenes.csv:status` column already records which level each scene has reached; no new tracking is needed.

### Relationship of `project.logline` (yaml) to `## Logline` (md)

Today the logline lives in `storyforge.yaml`. Proposal: **`reference/story-summary.md § Logline` becomes canonical**; `project.logline` is deprecated as an input. A one-time migration on first run copies the yaml value into the new md if the md is absent. Code that currently reads `project.logline` can be updated incrementally to read from the md, or a small helper in `common.py` can resolve from whichever is present.

This is a backward-compat concern but a small one — `project.logline` is used in only a few places (init, prompt building for elaboration). It's a clean migration.

### Relationship to `reference/story-architecture.md`

This file already exists and contains premise + theme + three-level conflict + ending. It's populated at the spine stage. Two options:

- **A. Keep as-is.** story-summary.md and story-architecture.md coexist. Some overlap in content (the architecture file's premise paragraph is essentially the synopsis), but each has a primary purpose.
- **B. Merge.** Restructure story-architecture.md to include the logline/synopsis/act-shape sections at the top, with premise/theme/conflict/ending at the bottom. One file.

**Recommendation: A.** Less migration risk, preserves existing code paths, and the conceptual split (summary vs. structural framing) is real — the synopsis tells you what kind of story this is; the architecture tells you how it works thematically. They can both exist.

If overlap becomes a problem in practice, B is straightforward to do later.

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
| `reference/motif-taxonomy.csv` | pipe-csv | Motif registry |
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

---

## Common metadata

The prose tier benefits from a small amount of explicit metadata so the cascade machinery can detect what's derived from what. I propose YAML frontmatter on `story-summary.md`:

```yaml
---
logline_updated: 2026-05-24
synopsis_updated: 2026-05-24
act_shape_updated: 2026-05-24
---
```

A timestamp per section, not per-file. That gives the cascade enough signal to ask "the logline changed after the synopsis — does the synopsis still hold?" without having to compute content hashes.

The structural tier doesn't need explicit metadata — `scenes.csv:status` plus git timestamps on the CSV files give the cascade enough to work with.

(Content hashes per section, derivation graphs, etc. were considered and rejected as over-engineering. The cascade design (#226) can revisit if needed.)

---

## What's deliberately not in this doc

- **Cascade mechanics** — how a change at one level propagates to others. That's #226.
- **Scoring** — per-level quality rubrics and cross-level fidelity. That's #227.
- **Prompts** — how each level is generated or expanded. Implementation, after all three research issues land.
- **CLI surface** — whether `storyforge elaborate logline` becomes a thing, or whether the prose tier is author-only. Cascade design (#226) will surface this.

---

## Open questions / things to push back on

1. **Is the prose tier really three levels, or one?** The proposal treats logline / synopsis / act-shape as three separate scored levels but one artifact. If in practice they always move together (you can't change one without re-doing the others), they might be one level with three views. Test this assumption with real iterations on Ashes once implemented.

2. **Should `story-architecture.md` be absorbed into `story-summary.md`?** Currently kept separate (Option A above). If the duplication between "synopsis" and "premise paragraph" becomes painful, merge.

3. **What about projects that start with a beat sheet, treatment, or outline instead of a logline?** Real-world authoring rarely starts at level 0. The system needs to be hospitable to entering at any level. Implementation concern, not a taxonomy concern — flag and revisit.

4. **Is the spine really a separate level from architecture, or just architecture with fewer scenes?** Today's pipeline treats them distinctly (`status=spine` vs `status=architecture`), and the survey confirmed they answer different questions (irreducible events vs. dramatic rhythm). Keep as separate levels.

5. **GN mode and the prose tier.** The prose tier as proposed makes no medium distinction — a logline is a logline whether the medium is novel or graphic novel. GN-specific structure (page-turn beats, panel rhythm) starts at the structural tier. Confirm with a GN project iteration.

---

## Implementation sketch (informational only)

For when the three research docs converge and we move to building:

- New file template at `templates/reference/story-summary.md`.
- `storyforge init` writes the file with the project's seed logline.
- A small `parse_story_summary(project_dir)` helper parses the three sections via `## Logline`, `## Synopsis`, `## Act-shape` headers, returns a dict.
- `storyforge sync` extended to include `story-summary.md` in its watched paths (though the prose tier doesn't round-trip through CSVs — it's the source of truth for its three levels).
- Migration: on first run after the change, if `story-summary.md` is absent and `storyforge.yaml:project.logline` is present, scaffold the file with the logline filled in and synopsis/act-shape empty.

Nothing here is committed; this section is just to confirm the taxonomy maps cleanly to an implementation plan when it's time.
