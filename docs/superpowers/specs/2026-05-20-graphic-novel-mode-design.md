# Graphic Novel Mode — Design

**Status:** Draft (approved through design phase 2026-05-20)
**Scope:** v1 — branches at the briefs stage; planning stages stay shared
**Out of scope for v1:** evaluation, scoring, revision, extract, annotations, publish — each tracked as a followup

## Summary

Add a parallel "graphic novel" medium to Storyforge. Structural development (spine, architecture, scene map) stays shared with novel mode because the bones of the story don't care about delivery format. The pipeline branches at the briefs stage: graphic-novel briefs add page-layout and panel-breakdown fields, drafting produces a panel script instead of prose, and production assembles an artist-ready handoff package instead of an epub.

The author commits to a medium at project init. A graphic-novel project and a prose adaptation of the same story are separate projects.

## Motivation

Storyforge's existing pipeline does the structural work that makes a story land — value shifts, MICE threads, character arcs, scene-level goal/conflict/outcome contracts. That work pays off regardless of whether the final delivery is prose, panels, or panels-and-prose-together. The current bottleneck for graphic-novel authors using Storyforge is the drafting stage: there's nowhere to put panel composition, page layout, or page-turn beats; the prose-craft scoring isn't relevant; and the produce skill assumes an epub deliverable.

Adding graphic-novel mode lets authors take a story through the same structural rigor and hand off a clean panel script plus visual references to an artist (human or AI-assisted). The author keeps authorial control over the layout decisions that affect pacing — panel rhythm, splash placement, page-turn reveals — because those are story decisions, not just art decisions.

## Design Principles

- **One medium per project.** Set at init, durable. No mid-project switching. If you want both a novel and a graphic novel of the same story, those are separate projects.
- **Branch late.** Spine, architecture, scene-map, voice, hone, validate, cleanup are shared. The pipeline diverges at briefs and stays divergent through drafting and production.
- **Add columns, don't replace.** Every existing brief field (goal/conflict/outcome, key_actions, key_dialogue, continuity_deps, physical_state_in/out, etc.) keeps its meaning in graphic-novel mode. Graphic-novel-specific fields are added alongside.
- **Authorial layout, artist composition.** The script specifies page layout, panel count per page, panel size hints, and page-turn beats (authorial). Composition inside the panel is described in prose; the artist interprets (Marvel-style for art, Full Script for layout).
- **Existing novel-mode code stays pristine.** New graphic-novel logic lives in parallel `cmd_*_gn.py` modules and parallel `prompts_*_gn.py` files. Shared modules add medium-aware branches only where genuinely needed.

## Architecture

Approach B from brainstorming: parallel command modules with a shared planning core.

```
                  ┌─────────────────────────────────────────┐
                  │             Shared planning             │
                  │  (medium-aware where they need to be)   │
                  │                                         │
                  │  elaborate (spine, architecture,        │
                  │             scene-map, voice)           │
                  │  hone, validate, cleanup                │
                  └────────────────┬────────────────────────┘
                                   │
                              briefs stage
                                   │
                ┌──────────────────┴───────────────────┐
                │                                      │
       project.medium = novel              project.medium = graphic-novel
                │                                      │
                ▼                                      ▼
       ┌────────────────┐                    ┌──────────────────┐
       │ cmd_write      │                    │ cmd_write_gn     │
       │ cmd_evaluate   │                    │ (v1 stops here   │
       │ cmd_score      │                    │  for evaluation; │
       │ cmd_revise     │                    │  no GN scoring   │
       │ cmd_assemble   │                    │  in v1)          │
       │ cmd_publish    │                    │ cmd_script_      │
       │ cmd_annotations│                    │   package        │
       └────────────────┘                    └──────────────────┘
                │                                      │
                ▼                                      ▼
            epub/PDF                        manuscript/script.md,
            web book                        script.pdf,
                                            visual-references.md,
                                            handoff-readme.md
```

The `./storyforge` runner and `__main__.py` dispatcher are the single entry point. The dispatcher reads `project.medium` from `storyforge.yaml` and routes `write` and `assemble` to the appropriate cmd module. Graphic-novel-incompatible commands in v1 — `evaluate`, `score`, `revise`, `publish`, `annotations`, `extract`, `repetition`, `enrich` — return a clear error (e.g., `"score is not supported for graphic-novel projects in this version"`) rather than silently skipping. The shared-planning commands (`elaborate`, `hone`, `validate`, `cleanup`) work in both mediums. From the author's perspective, `./storyforge write` and `./storyforge assemble` always do the right thing; unsupported commands explain why up front.

## Medium Selection

A new field in `storyforge.yaml`:

```yaml
project:
  title: "..."
  medium: graphic-novel   # values: novel (default), graphic-novel
  genre: "..."
  ...
```

**Defaults and back-compat:**
- Projects without `project.medium` default to `novel`. Existing projects need no migration.
- The medium is durable. There is no command to flip it. Switching mediums means starting a new project.

**`init` skill changes:**
- New question after "Pipeline approach": "Are you writing prose or a graphic novel?"
- Graphic-novel mode requires the elaboration pipeline (the structural rigor matters more, not less, when art is the delivery vehicle). The "traditional" pipeline option is hidden when the author picks graphic novel.
- The skill writes `project.medium` into `storyforge.yaml` and routes the rest of init accordingly (e.g., shows different example targets — page count rather than word count — when applicable).

**`forge` skill:** reads `project.medium` and routes to graphic-novel skills where they exist; shared planning skills are used as-is.

## CSV Schema Changes

### `reference/scenes.csv` — add three nullable columns

```
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words|target_pages|panel_count|page_count
```

| Column | Purpose |
|---|---|
| `target_pages` | Author sets at scene-map stage (graphic-novel mode) |
| `page_count` | Populated by `cmd_write_gn` after drafting — counts `## Page N` headers |
| `panel_count` | Populated by `cmd_write_gn` after drafting — counts `**Panel N**` blocks |

In novel mode, the three new columns stay empty; `target_words` / `word_count` keep their roles. In graphic-novel mode, `target_words` / `word_count` stay empty.

### `reference/scene-intent.csv` — no changes

`function`, `action_sequel`, `emotional_arc`, `value_at_stake`, `value_shift`, `turning_point`, `characters`, `on_stage`, `mice_threads` all remain medium-agnostic.

### `reference/scene-briefs.csv` — add five columns

```
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out|page_layout|panel_breakdown|visual_keywords|page_turn_beats|caption_strategy
```

| Column | Purpose |
|---|---|
| `page_layout` | High-level rhythm intent for the scene: e.g., `"9-panel grid"`, `"splash p3, 6-panel grid after"`, `"double-spread climax p4-5"` |
| `panel_breakdown` | Per-page panel structure: `"p1:splash; p2:6-grid; p3:splash+3"` |
| `visual_keywords` | Visual beats that must appear, semicolon-separated: `"blank parchment close; trembling hand; shadow under door"` |
| `page_turn_beats` | Beats that must land on a page turn (recto-to-verso reveal) — verified against `panel_breakdown` at script-build time |
| `caption_strategy` | How narration is used: `"minimal"`, `"journal voiceover"`, `"omniscient narration"`, `"none"` |

All existing brief columns keep their full meaning. `key_dialogue` becomes more critical (every word balloon is real estate). `key_actions` reads as a panel-beat list. `continuity_deps` covers visual continuity (returning props, locations, character looks) in addition to story continuity. `has_overflow` is interpreted as page-overflow rather than word-overflow.

### Visual references — extend existing files

No new reference CSV files in v1. Visual references live in markdown:

- `reference/character-bible.md` gains a "Visual" subsection per character: silhouette, age look, signature elements (scar, cane, jewelry), costume continuity notes
- `reference/world-bible.md` gains visual-keyword notes on recurring locations
- `reference/voice-profile.csv` gains two fields on the `_project` row: `caption_voice` (narrator / omniscient / none / first-person-via-journal) and `lettering_style` (loose-natural / typeset / hand-lettered-feel)

If reference handling outgrows markdown sections later, a `reference/visual-refs.csv` can be added then.

## Pipeline Stages

### Shared with novel mode

| Stage | Command | Skill | Graphic-novel changes |
|---|---|---|---|
| Spine | `cmd_elaborate.py --stage spine` | `elaborate` | Prompts mention graphic-novel framing |
| Architecture | `cmd_elaborate.py --stage architecture` | `elaborate` | Architecture doc gains a *Panel rhythm / visual language* section |
| Voice | `cmd_elaborate.py --stage voice` | `elaborate` | Voice stage asks for `caption_voice` and `lettering_style` and writes them to `voice-profile.csv` |
| Scene map | `cmd_elaborate.py --stage scene-map` | `elaborate` | Asks `target_pages` per scene instead of `target_words`; reports total page budget |
| Briefs | `cmd_elaborate.py --stage briefs` | `elaborate` | **Branch point** — graphic-novel briefs prompt populates the five new columns alongside the existing brief fields |
| Validate | `cmd_validate.py` | (via elaborate) | Medium-aware: validates `target_pages` and graphic-novel brief columns; skips word-based checks |
| Hone | `cmd_hone.py` | `hone` | Existing diagnostics still apply (abstract briefs, overspecified beats, vague intent). Adds graphic-novel-aware checks (missing `panel_breakdown`, `page_turn_beats` that don't land on page boundaries) |
| Cleanup | `cmd_cleanup.py` | `cleanup` | Medium-aware schema validation |
| Extract | `cmd_extract.py` | `extract` | Skipped for graphic-novel mode in v1 (extraction from existing graphic-novel scripts is a separate design problem) |

**Pattern:** each shared command reads `project.medium` once at the top of `main()` via `common.read_yaml_field('project.medium', ...)`, then branches at the precise points where behavior diverges. Most divergence is prompt selection: a new `prompts_elaborate_gn.py` sits alongside `prompts_elaborate.py`. Conditional logic is concentrated, not scattered.

### Graphic-novel-only (v1)

| Command | Skill | Purpose |
|---|---|---|
| `cmd_write_gn.py` | (drafting is autonomous; no dedicated skill) | Drafts panel scripts from briefs |
| `cmd_script_package.py` | `script-package` | Assembles the artist handoff bundle |

Novel-mode `cmd_write`, `cmd_assemble`, `cmd_publish`, `cmd_annotations`, `cmd_evaluate`, `cmd_score`, `cmd_revise` are not modified.

## Drafting: `cmd_write_gn`

Mirrors `cmd_write.py`:
- Same CLI surface: `./storyforge write [--scenes ...] [--act ...] [--from-seq ...] [--parallel N]`
- Same parallel wave drafting via `runner.run_parallel`
- Same `HealingZone` retry pattern
- Same brief-fidelity discipline (output must respect the brief)
- Same scene-status updates and CSV bookkeeping

**Prompts:** new `prompts_gn.py` alongside `prompts.py`. Each graphic-novel drafting prompt receives:
- The scene's intent row, brief row (all columns, including the five graphic-novel-specific ones)
- Character-bible visual sections for every character `on_stage`
- World-bible visual notes for the scene `location`
- `voice-profile.csv` including `_project.caption_voice` and `_project.lettering_style`
- The script-format system prompt that teaches the model the output structure

**Output:** `scenes/{id}.md`, structured as:

```markdown
# Scene: the-finest-cartographer

**Target pages:** 4 | **Layout intent:** Splash p1, 6-panel p2-3, splash p4 (page-turn reveal)

---

## Page 1 — SPLASH

**Panel 1** (full bleed)
The cartographer at his desk in the lamplit study, blank parchment
stretched before him. Bookshelves loom in shadow. He stares at the
paper as if it might speak.

- CAPTION: *The map remained blank.*
- CARTOGRAPHER: It always begins this way.

---

## Page 2 — 6-PANEL GRID

**Panel 1** (top-left, small)
Close on the cartographer's hand, trembling, holding the pen.

- CAPTION: *Forty years of practice...*

**Panel 2** (top-center, small)
...

---

## Page 4 — SPLASH ⟵ PAGE-TURN REVEAL

**Panel 1** (full bleed)
...
```

**Rules enforced by the prompt:**
- Every page header is `## Page N — LAYOUT` where `LAYOUT` is one of `SPLASH`, `6-PANEL GRID`, `9-PANEL GRID`, `DOUBLE-SPREAD`, `TIER`, `IRREGULAR`
- Every panel block starts with `**Panel N**` and an optional size/position hint in parentheses
- Dialogue and captions use a fixed prefix vocabulary (v1 set, extensible in followups): `CAPTION`, `{CHARACTER}` (uppercase character name from the on_stage list), `SFX`, `WHISPER`, `THOUGHT`, `OFF-PANEL`
- Panel composition is described in 1–3 sentences of prose (Marvel-style for the art, Full Script for the layout)
- A `⟵ PAGE-TURN REVEAL` marker appears on any page whose first panel was tagged in the brief's `page_turn_beats`

**Post-draft brief-fidelity check** (deterministic, runs after every drafted scene):
- Every entry in the brief's `key_dialogue` must appear in a word balloon
- Every entry in the brief's `visual_keywords` must appear in a panel's composition prose
- The script's actual page/panel structure (parseable regex) must match the brief's `panel_breakdown`
- Every brief `page_turn_beats` entry lands on a panel marked with the page-turn marker

Fidelity failures don't fail the run — they flag for the author and feed into `cmd_hone`'s graphic-novel-aware diagnostics.

**`scenes.csv` updates after drafting:** `panel_count`, `page_count`, `status` → `drafted`.

**Prose-craft scoring** (`repetition.py`, `scoring_passive.py`, `scoring_adverbs.py`, `scoring_weather.py`, `scoring_rhythm.py`, `scoring_economy.py`) skips scenes when `project.medium == 'graphic-novel'`. Graphic-novel scoring is its own design problem and is out of scope for v1.

## Production: `cmd_script_package` and the `script-package` skill

The graphic-novel analog to `cmd_assemble.py` / `produce`. Same CLI shape: `./storyforge assemble [--format ...]`. The `./storyforge` runner's dispatcher routes by `project.medium`.

**Skill flow** (`script-package` skill):
- Confirms chapter / issue structure — reuses `reference/chapter-map.csv` exactly as-is (`chapter|title|heading|scenes`). A "chapter" can mean a graphic-novel section or a serialized-comic issue; the author chooses semantics.
- Asks for production settings under a new `storyforge.yaml` key `script_package:`:
  - `artist_name` (optional, if known at handoff time)
  - `trim_size` (e.g., `6.625x10.25`, US standard)
  - `page_format` (single-sided digital, print-ready, etc.)
- Calls `./storyforge assemble`

**Output bundle** in `manuscript/`:

```
manuscript/
├── script.md              — assembled artist script, global page numbering
├── script.pdf             — PDF version (via weasyprint/pandoc)
├── visual-references.md   — character + location visual refs extracted from bibles
├── chapter-map.md         — readable chapter/issue breakdown with page ranges
├── handoff-readme.md      — auto-generated overview of script format conventions
└── cover/                 — placeholder; reuses the existing `cover` skill if invoked
```

**`script.md` structure:**
- Title page (project title, author, total pages, chapter count, target trim size)
- Per-chapter sections containing each chapter's scene scripts in order
- Global page numbering recomputed across scenes — each scene's local `## Page 1` becomes global `## Page 47` etc.
- Page-turn markers preserved

**`visual-references.md`:** extracts the "Visual" subsection from each character-bible character entry and the visual-keyword notes from each world-bible location entry. One reference card per recurring character (silhouette, age, signature elements, costume continuity), one per recurring location (visual keywords, mood). This is the document the artist pins above their drawing table.

**`handoff-readme.md`** is auto-generated and explains:
- Script format conventions (page header layout tags, panel hints, prefix vocabulary)
- How to read page-turn markers
- Where visual references live
- Contact info for questions (pulled from production settings)

The artist should be able to onboard from the bundle alone.

**Cover:** the existing `cover` skill works for v1. Graphic-novel-specific cover work (full illustration commission, variant covers) is a separate design problem.

**`cmd_assemble.py`** for novel mode is not modified.

## File-by-File Change Inventory

### New files

| Path | Purpose |
|---|---|
| `scripts/lib/python/storyforge/cmd_write_gn.py` | Graphic-novel drafting |
| `scripts/lib/python/storyforge/cmd_script_package.py` | Graphic-novel production |
| `scripts/lib/python/storyforge/prompts_gn.py` | Drafting prompts for graphic-novel mode |
| `scripts/lib/python/storyforge/prompts_elaborate_gn.py` | Elaboration-stage prompts for graphic-novel mode |
| `scripts/lib/python/storyforge/script_format.py` | Parsing/validation helpers for the panel-script format (regex, page-turn detection, panel counting) |
| `skills/script-package/SKILL.md` | Production skill for graphic-novel mode |
| `tests/fixtures/test-project-gn/` | Graphic-novel test fixture (full project through briefs stage) |
| `tests/test_cmd_write_gn.py` | Unit tests for graphic-novel drafting |
| `tests/test_cmd_script_package.py` | Unit tests for the production bundle |
| `tests/test_script_format.py` | Unit tests for script-format parsing helpers |
| `tests/test_medium_routing.py` | Tests verifying the dispatcher and shared commands route by medium |

### Modified files

| Path | Change |
|---|---|
| `templates/storyforge.yaml` | Add `project.medium` field with comment; add example `script_package:` block |
| `templates/reference/scenes.csv` | Add `target_pages`, `panel_count`, `page_count` columns to header |
| `templates/reference/scene-briefs.csv` | Add `page_layout`, `panel_breakdown`, `visual_keywords`, `page_turn_beats`, `caption_strategy` columns to header |
| `templates/reference/voice-profile.csv` | Document `caption_voice` and `lettering_style` fields on `_project` row |
| `skills/init/SKILL.md` | Add medium question; route to elaboration pipeline when medium is graphic-novel |
| `skills/forge/SKILL.md` | Read `project.medium` and route to graphic-novel skills where they exist |
| `skills/elaborate/SKILL.md` | Medium-aware behavior at scene-map (target_pages), voice (caption_voice/lettering_style), briefs (graphic-novel brief columns) |
| `skills/hone/SKILL.md` | Medium-aware diagnostics for graphic-novel brief columns |
| `scripts/lib/python/storyforge/__main__.py` | Dispatcher reads `project.medium` and routes `write` and `assemble` |
| `scripts/lib/python/storyforge/cmd_elaborate.py` | Medium-aware branches at scene-map / voice / briefs stages |
| `scripts/lib/python/storyforge/cmd_validate.py` | Medium-aware schema validation |
| `scripts/lib/python/storyforge/cmd_hone.py` | Add graphic-novel diagnostics (missing panel_breakdown, off-page page-turn beats) |
| `scripts/lib/python/storyforge/cmd_cleanup.py` | Medium-aware schema checks |
| `scripts/lib/python/storyforge/schema.py` | Add column definitions for the new scenes.csv / scene-briefs.csv columns |
| `scripts/lib/python/storyforge/common.py` | (No structural change; `read_yaml_field('project.medium', ...)` already works) |
| `scripts/lib/python/storyforge/repetition.py` | Skip graphic-novel scenes |
| `scripts/lib/python/storyforge/scoring_passive.py` | Skip graphic-novel scenes |
| `scripts/lib/python/storyforge/scoring_adverbs.py` | Skip graphic-novel scenes |
| `scripts/lib/python/storyforge/scoring_weather.py` | Skip graphic-novel scenes |
| `scripts/lib/python/storyforge/scoring_rhythm.py` | Skip graphic-novel scenes |
| `scripts/lib/python/storyforge/scoring_economy.py` | Skip graphic-novel scenes |
| `.claude-plugin/plugin.json` | Bump minor version (new feature) |
| `CLAUDE.md` | Add graphic-novel mode notes in the command and skill tables |

### Unchanged

`cmd_write.py`, `cmd_assemble.py`, `cmd_publish.py`, `cmd_annotations.py`, `cmd_evaluate.py`, `cmd_score.py`, `cmd_revise.py`, `cmd_repetition.py`, `cmd_enrich.py`, `cmd_timeline.py`, `cmd_extract.py`, and the corresponding skills (`revise`, `score`, `publish`, `produce`) are untouched.

## Testing Strategy

- **New fixture** `tests/fixtures/test-project-gn/`: small project with `project.medium: graphic-novel`, 3–5 scenes carried through the briefs stage with example values in every new column. Includes character-bible Visual sections and a voice-profile `_project` row with `caption_voice` / `lettering_style`.
- **Unit tests** for `cmd_write_gn`: API mocked via existing test patterns. Asserts script-format compliance, page/panel counting, brief-fidelity check correctness on both pass and fail.
- **Unit tests** for `cmd_script_package`: asserts the output bundle structure, global page renumbering across scenes, visual-reference extraction from character-bible/world-bible.
- **Unit tests** for `script_format.py`: regex correctness for page headers, panel blocks, page-turn markers, prefix vocabulary recognition.
- **Medium-routing tests** in `test_medium_routing.py`: confirms the dispatcher routes `./storyforge write` and `./storyforge assemble` correctly, and that shared commands (`elaborate`, `validate`, `hone`, `cleanup`) pick the right prompt module and schema branch.
- **Schema-validation tests** in `cmd_validate.py`'s test suite: graphic-novel projects must have `target_pages` (not `target_words`); novel projects must have the inverse.
- **Backward-compatibility tests**: the existing novel-mode fixture (`tests/fixtures/test-project/`) continues to pass every shared-command test unchanged.
- **Integration test**: run the full graphic-novel pipeline on the fixture — spine → architecture → scene-map → voice → briefs → write → script-package — and assert the bundle is produced with valid structure.

## Followups (Explicitly Out of Scope for v1)

Each is its own design problem and gets its own spec when prioritized:

- **Graphic-novel evaluation, scoring, and revision.** `cmd_evaluate_gn`, `cmd_score_gn`, `cmd_revise_gn` with a rubric appropriate to the medium (panel transitions, page-turn discipline, balloon economy, visual storytelling, dialogue compression). The first version of v1 explicitly skips scoring for graphic-novel scenes.
- **Canonical layout research.** Research and codify standards from established practitioners (Eisner's pacing, Kirby's splash logic, the nine-panel grid tradition from Watchmen / Sandman, modern indie conventions, Image house style). Feeds prompts and validation.
- **Style-guide document.** Standalone artist style guide with palette, line weight, tone of voice for the art, panel-rhythm philosophy. Currently deferred — visual references in `character-bible.md` and `world-bible.md` are the v1 substitute.
- **AI-generated visual reference thumbnails.** v1 uses text descriptions only.
- **Graphic-novel extraction.** Pulling structural data from an existing graphic-novel script back into the elaboration pipeline (the prose analog of `cmd_extract`).
- **Graphic-novel-specific cover workflows.** Variant covers, full illustration commissions, lettering specs.
- **Graphic-novel publish / reader annotations.** Bookshelf integration for graphic novels is a separate problem (the reader experience for panel scripts is different from prose).
- **Medium migration.** Converting an existing novel project into a graphic-novel project (or vice versa).

## Open Questions

None blocking implementation. Design is fully specified for v1.
