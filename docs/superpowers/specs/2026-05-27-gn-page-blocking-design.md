# GN Page-Blocking Pass Design

**Issue:** #252 — Graphic novel mode: page-blocking pass (page architecture + blocking image) before per-panel rendering

**Status:** Approved 2026-05-27 — ready for implementation plan.

**Dependencies (already merged):**
- #251 — per-page files (`pages/<prefix>-pN.md`, `pages.py` module)
- #254 — graphic-novel canon files (`reference/canon/*.md`, including `panel-registers.md` and `page-rhythm-rules.md`)

---

## 1. Motivation

AI image generators rendered panel-by-panel in isolation produce visually uniform pages — every panel becomes a "feature image" at the same fidelity. Professional sequential art relies on **per-panel modulation**: dominant panels, transitional beats, atmospheric pauses. This rhythm must be specified at the **page level** before any panel renders.

Validated in benjaminsnorris/ashes PR #8: introducing a monochrome storyboard-thumbnail page-blocking pass — which locks panel geometry, panel weights, and eye flow before any per-panel render — produced the single largest quality jump in the iteration history. Pages stopped feeling like "four independent illustrations on the same page" and started feeling like "one page event."

This spec adds that page-blocking pass as a first-class elaboration stage and propagates the artifact into the artist handoff bundle.

---

## 2. Design Principles

- **Page is the unit.** Panel rhythm is a page-level decision; no individual panel can carry it.
- **Reuse `elaborate` scaffolding.** Branch/PR/coaching/parallelism already exist there; don't duplicate.
- **Page files are source-of-truth.** Both the design (page architecture) and the renderer artifact (blocking prompt) live in the page file. The artist bundle is a projection.
- **Separate readable script from renderer instructions.** Blocking prompts are rendering instructions, not story content — they get their own bundle file, not inlined into `script.md`.
- **Light validation in v1.** Section-presence only. Deeper structural checks (clause presence, register citation, geometry specificity) are #253's job.

---

## 3. Architecture

### 3.1 Page-file body additions

A new elaboration stage writes two body sections into each page file:

```
## Page architecture

### Intent
- Narrative purpose, emotional arc, visual rhythm, dominant motif

### Panel hierarchy
- Panel 1 — <register>: <one-line role>
- Panel 2 — <register>: <one-line role>
- …

### Book-level placement
- Spread context: verso of N–N+1 | recto of N–1–N | opening recto | closing verso
- Page-turn beat: yes/no — what reveals on the turn

## Page-blocking prompt

<monochrome storyboard-thumbnail prompt — locks panel geometry, panel
weights, eye flow. Pure compositional blocking; no surface texture,
no rendered detail, no faces, no fine line work. Cites panel-registers
vocabulary by name.>
```

The blocking prompt sits between `## Page architecture` and `## Panel script`. Order in the page file becomes:

1. (frontmatter)
2. `## Scene context`
3. `## Page architecture` (← new)
4. `## Page-blocking prompt` (← new)
5. `## Panel script`
6. `## Image-generation prompts`
7. `## Page-specific notes`

Neither new section is required by the parser — they are body conventions, like the other body sections. Cleanup surfaces their absence as a warning (see §6).

### 3.2 Extractors in `pages.py`

Add `extract_page_architecture(path) -> str` and `extract_blocking_prompt(path) -> str`, mirroring the existing `extract_panel_script` pattern. Both reuse the `_NEXT_SECTION_HEADER` lookahead and the `## Page N — …` em-dash carveout.

### 3.3 Frontmatter

No new required or recommended frontmatter fields. The existing `canonical_blocks_embedded` list (already collected into `extra_lists` by `_parse_frontmatter`) is populated by full-mode drafting as an audit trail of which canon files were cited.

---

## 4. Authoring command

`storyforge elaborate --stage page-architecture` — extends the existing elaborate stage taxonomy.

### 4.1 Stage registration

- Add `'page-architecture'` to `VALID_STAGES` in `cmd_elaborate.py`
- Add a per-stage handler `_page_architecture_handler_gn(project_dir, ref_dir, dry_run, stage_model, system, args)` modeled on `_briefs_handler_gn`
- Medium-gate: graphic-novel only; novel-mode projects get a clear error

### 4.2 Flags

- (no flag) — process every page file missing `## Page architecture` (gap-fill default)
- `--page <page_id>` — single page (e.g., `s01-p1`)
- `--scene <scene_id>` — every page of one scene
- `--force` — overwrite existing sections (otherwise present sections are preserved)
- `--dry-run` — print one fully-rendered prompt and exit; no API call
- `--coaching {full|coach|strict}` — overrides project default (existing pattern)
- `--parallel N` — worker count (default per existing pattern)

### 4.3 Preconditions (warn-and-skip, do not abort)

For each page being processed, the handler verifies:

- Page file's `scene_id` resolves to a row in `reference/scenes.csv`
- Scene's brief has non-empty `panel_breakdown` in `reference/scene-briefs.csv`
- `reference/canon/panel-registers.md` has its `## Embeddable block` section populated (no leading `TODO`)
- `reference/canon/page-rhythm-rules.md` has its `## Embeddable block` section populated

If any precondition fails for a given page, the page is skipped with a logged WARN line citing which precondition failed. The stage continues with the remaining pages. Stage exits 0 if any page was processed; exits 1 only if zero pages were processed AND at least one precondition failed (so CI / scripted runs surface the unmet preconditions).

### 4.4 LLM context (full mode)

Per-page prompt contents:

- Scene brief row (full row from `scene-briefs.csv`, focus on `page_layout`, `panel_breakdown`, `page_turn_beats`, `visual_keywords`, `caption_strategy`)
- Scene intent row (function, emotional arc, value shift, characters, on_stage)
- Page frontmatter (page_within_scene, total_pages_in_scene, panel_count, spread_position, characters_present, location, timeline)
- Neighbor pages' frontmatter (previous + next page in the scene, for spread context)
- Embeddable blocks from: `panel-registers.md`, `page-rhythm-rules.md`, `style-foundation.md`, `lighting-laws.md`
- Per-character canon blocks for `characters_present`
- Per-location canon block for `location`
- Page-rhythm rules + panel-register vocabulary are repeated in the instructions (not just embedded), with the directive: "Every panel in the hierarchy must cite a register by name from panel-registers.md."

Output format the LLM is asked to produce: a single markdown block containing the two new sections in order, with no other text. The handler parses out the block, verifies it has both `## Page architecture` and `## Page-blocking prompt` headers, splices it into the page file, and updates `canonical_blocks_embedded` in the frontmatter to list the canon files cited.

### 4.5 Model selection

Uses `select_model('drafting')` (Opus) — page architecture is creative work (visual rhythm + composition), not analytical.

### 4.6 Cost tracking

Per-page invocations log to the ledger via `log_operation(project_dir, 'elaborate-page-architecture-gn', stage_model, ...)`. Existing batching / cost-summary pattern applies.

---

## 5. Coaching mode behavior

Following the established pattern (full / coach / strict are roles, not toggle levels):

### 5.1 full

LLM drafts both sections directly into the page file. Author can then edit. This is the default in newly-initialized projects.

### 5.2 coach

LLM produces a guidance brief at `working/coaching/page-architecture-<page_id>.md`:

```
# Page architecture brief: <page_id>

## What you need to decide

- Which panel is this page's emotional fulcrum (dominant register)?
- Which panels are transitional / rhythmic / atmospheric?
- Is there a page-turn beat? What reveals on the turn?
- What's the spread context (this page's relationship to its facing page)?

## Canon vocabulary to use

[panel-registers embedded inline]
[page-rhythm-rules embedded inline]

## Brief inputs

- panel_breakdown: <…>
- visual_keywords: <…>
- page_turn_beats: <…>

## Sibling pages

- Previous (page N-1): <frontmatter summary>
- Next (page N+1): <frontmatter summary>

## Write your page architecture into the page file at:

pages/<page_id>.md (between `## Scene context` and `## Panel script`)
```

No mutation of the page file. The author writes the sections themselves.

### 5.3 strict

Rule-based template renderer with no LLM call. Writes a skeleton with TODO blanks and a constraint checklist directly into the page file:

```
## Page architecture

### Intent
TODO — narrative purpose, emotional arc, visual rhythm, dominant motif.

### Panel hierarchy
- Panel 1 — TODO register: TODO role
- Panel 2 — TODO register: TODO role
- (one bullet per panel in panel_count)

### Book-level placement
- Spread context: TODO
- Page-turn beat: TODO (yes/no — what reveals)

## Page-blocking prompt

TODO — monochrome storyboard thumbnail. Must:
- Cite panel registers by name (dominant | transitional | rhythmic |
  climactic | atmospheric — see reference/canon/panel-registers.md)
- Specify panel geometry (grid? splash? irregular?)
- Specify eye flow (left-to-right, Z, F, vertical)
- Be pure compositional blocking — no surface texture, no faces,
  no fine line work
```

Strict mode never invokes the API. Authors fill the blanks themselves; the checklist is the contract.

---

## 6. Cleanup integration

`cmd_cleanup.py` page-file validation gains two new finding kinds in the `PageFindingKind` `Literal`:

- `missing_page_architecture` — page file has no `## Page architecture` section, or the section header is present but the body is empty / whitespace-only
- `missing_blocking_prompt` — page file has no `## Page-blocking prompt` section, or the section header is present but the body is empty / whitespace-only

Both are **warnings** (informational; included in the report but do not cause cleanup to exit non-zero). They represent gaps that the author should fill via `elaborate --stage page-architecture`.

A page populated by strict-mode (header + body with `TODO` placeholders) does **not** fire either finding — `TODO` is non-empty content, and the author is expected to fill it in. A page where the author has deleted just the body but left the header WILL fire the finding, which is the right behavior (signals a half-edited state).

`validate_page_file` in `pages.py` is extended with two body-content checks (using the new extractors) when called from cleanup. The existing parse-level findings (`missing_field`, etc.) keep their semantics.

Deeper structural checks (clause presence, register citation, geometry specificity, monochrome enforcement) are deliberately out of scope and tracked by #253.

---

## 7. Script-package integration

A new bundle file is added: **`manuscript/page-blocking-prompts.md`**.

Contents: concatenated blocking prompts in global page order, using the same global page numbering `script-package` already computes for `script.md`. Per-page entry format:

```
## Global page <N> (<page_id>) — <scene title>, page <within>/<total>

<blocking prompt body>
```

Behavior:

- The file is emitted only when at least one page file in the bundle has a non-empty `## Page-blocking prompt` section
- Pages with empty / missing blocking prompts are silently omitted (no placeholder)
- If zero pages have blocking prompts, the file is not created and `handoff-readme.md` does not reference it
- When the file is present, `handoff-readme.md` gains a paragraph explaining the recommended generation order:

> **Generation order.** Render the blocking layout for each page first
> (see `page-blocking-prompts.md`). Lock the page geometry — panel
> shapes, sizes, positions, eye flow — before iterating on any per-panel
> prompt. Per-panel art is then rendered against the locked blocking
> reference, which prevents the "every panel is a feature image" failure
> mode that uniform per-panel rendering produces.

`script.md` is **unchanged** — it remains the readable script. The page files in `pages/` are the working source of truth for both pieces; the bundle is a projection for the artist's read-once handoff.

---

## 8. File-by-file change inventory

### Create

- `scripts/lib/python/storyforge/prompts_page_architecture.py` — full-mode LLM prompt builder, coach-mode brief renderer, strict-mode template renderer
- `tests/test_pages_extractors.py` — unit tests for the two new section extractors
- `tests/test_cmd_elaborate_page_architecture.py` — stage handler tests (mocked API)
- `tests/fixtures/test-project-gn/pages/s01-p1.md` — fixture page (architecture + blocking populated)
- `tests/fixtures/test-project-gn/pages/s01-p2.md` — fixture page (sections absent, exercises cleanup findings)

### Modify

- `scripts/lib/python/storyforge/pages.py` — add `extract_page_architecture()`, `extract_blocking_prompt()`; extend `PageFindingKind` `Literal` with `missing_page_architecture` and `missing_blocking_prompt`
- `scripts/lib/python/storyforge/cmd_elaborate.py` — add `'page-architecture'` to `VALID_STAGES`; add `_page_architecture_handler_gn` + per-page parallel runner; wire flags
- `scripts/lib/python/storyforge/cmd_cleanup.py` — emit the two new finding kinds in the page-file validation pass
- `scripts/lib/python/storyforge/cmd_script_package.py` — assemble and write `manuscript/page-blocking-prompts.md` when any page has a blocking prompt; extend `HANDOFF_README` template with the generation-order paragraph (conditional on the file being present)
- `skills/elaborate/SKILL.md` — document the `page-architecture` stage, coaching behavior, preconditions
- `skills/forge/SKILL.md` — recommend page-architecture after briefs in GN mode
- `skills/script-package/SKILL.md` (if it exists) — note the new bundle file
- `CLAUDE.md` — add `page-architecture` to the elaborate stage table; update the GN pipeline ordering
- `.claude-plugin/plugin.json` — bump to **1.40.0** (new minor — additive feature)

### Unchanged but load-bearing

- `templates/reference/canon/panel-registers.md` — the embeddable block content is now consumed by the stage
- `templates/reference/canon/page-rhythm-rules.md` — same

---

## 9. Testing strategy

### Unit

- `extract_page_architecture` — extracts the right section body, handles missing-section, handles adjacent sections, handles `## Page N — …` em-dash variants in body content
- `extract_blocking_prompt` — same coverage
- Strict template renderer — deterministic output for a given (page_id, panel_count) tuple; snapshot-tested
- `validate_page_file` — `missing_page_architecture` and `missing_blocking_prompt` fire when sections absent; do not fire when sections present (with text content); fire when section header is present but body is empty/whitespace

### Integration

- `elaborate --stage page-architecture --dry-run` on the fixture project produces a prompt that contains: scene brief, panel-registers block, page-rhythm-rules block, neighbor-page frontmatter
- Mocked-API end-to-end run: handler parses a canned response, splices both sections into the page file, populates `canonical_blocks_embedded` frontmatter
- Precondition: handler skips a page whose scene has empty `panel_breakdown`, logs WARN, processes remaining pages
- Precondition: handler skips all pages when `panel-registers.md` is still TODO; exits 1 with a clear message
- `cleanup` on the fixture surfaces both new findings for the page that has them missing, does not surface them for the page that has them populated
- `script-package` on the fixture emits `manuscript/page-blocking-prompts.md` with global page numbering when any page has a blocking prompt; omits the file when none do
- `script-package` `handoff-readme.md` contains the generation-order paragraph when blocking prompts exist, omits it when they don't

### Coverage discipline

Every new `PageFindingKind` Literal value has at least one trigger test, per the existing convention in `tests/test_pages.py`.

---

## 10. Out of scope (deferred to #253)

- 13-section modular panel-prompt schema
- Validation that the blocking prompt contains required clauses (monochrome, no-faces, geometry-only, register-citation)
- Cross-page scoring (does this page architecture fit alongside its neighbors?)
- LLM-assisted iteration on a page's architecture based on a generated blocking image
- Visual reference thumbnails that show the blocking-image renders side-by-side in `visualize` dashboards (tracked by #212)

---

## 11. Open questions resolved during design

- **Q: Inline blocking prompt in `script.md` or separate file?** — Separate file. Renderer instructions ≠ story content; the artist needs the blocking prompts as a single "render these first" artifact.
- **Q: One command or two (design vs render)?** — One. Blocking prompt is a derivative of the page architecture; splitting them doubles surface area for no creative benefit.
- **Q: Required frontmatter additions?** — None. `canonical_blocks_embedded` already exists as a forward-compatible list and gets populated as an audit trail.
- **Q: Hard or soft validation in cleanup?** — Soft (warnings). Authors may legitimately be mid-edit; failing hard would block normal workflow.
- **Q: Per-page or whole-project scope?** — Whole-project by default (gap-fill), with `--page` and `--scene` for targeted runs and `--force` for redo. Matches the other elaborate stages.

---

## 12. Acceptance criteria

The feature is complete when:

1. `storyforge elaborate --stage page-architecture` runs end-to-end on a GN project, populates both sections in every gap-fillable page, respects coaching levels, and logs costs to the ledger.
2. `cleanup` reports the two new finding kinds against page files missing the sections; report is informational, exit code unaffected.
3. `script-package` produces `manuscript/page-blocking-prompts.md` with correct global page numbering when blocking prompts exist anywhere in the bundle; `handoff-readme.md` describes the generation order.
4. The test suite passes with new coverage for both extractors, both finding kinds, the dry-run prompt shape, the mocked-API end-to-end, the script-package integration, and all three coaching modes (full / coach / strict).
5. Version bumped to 1.40.0 in `.claude-plugin/plugin.json` on the release commit.
6. `CLAUDE.md` documents the new stage in the elaborate table.
