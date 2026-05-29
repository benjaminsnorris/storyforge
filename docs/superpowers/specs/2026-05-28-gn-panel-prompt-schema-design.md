# GN 13-Section Panel Prompt Schema Design

**Issue:** #253 — Graphic novel mode: 13-section modular panel prompt schema with separated render directives and low-weight emotional subtext

**Status:** Approved 2026-05-28 — ready for implementation plan.

**Dependencies (all merged on `main`):**
- #251 — per-page files (`pages/<prefix>-pN.md`, `pages.py` extractors)
- #254 — graphic-novel canon files (`reference/canon/*.md`)
- #252 — page-blocking pass (`## Page architecture` populates the per-panel register hierarchy that this PR's section 3 cites)

---

## 1. Motivation

First-attempt panel prompts that mash style, character, lighting, action, and atmospheric prose into a single paragraph get rendered as "beautiful gothic paintings" by diffusion models, not as **readable sequential panels**. Atmospheric prose gets converted into visual intensity. Every panel ends up at the same fidelity and the page loses rhythm.

Validated across six iterations on benjaminsnorris/ashes s01: a 13-section schema with explicit `(low weight)` labels on emotional sections, separated render directives, and verbatim canon embeds produces sequential-art output rather than concept art. Each of the 13 sections addresses a failure mode observed in prior iterations.

This spec ships the schema as a first-class authoring artifact (per-panel content inside each page file) plus the elaborate stage that drafts it and the cleanup validation that enforces presence and ordering.

---

## 2. Design Principles

- **Schema is the structure; canon is the content.** Five sections (1, 2, 5, 6, 10) embed verbatim from `reference/canon/*.md`. When canon updates, re-running the stage refreshes the embeds.
- **Render directives separate from atmospheric prose.** The schema's enforced ordering is what makes the separation legible to the renderer.
- **Per-page LLM grain.** One API call emits all panels for one page, so the model can think about the register hierarchy holistically and keep cross-panel continuity in a single context.
- **Reuse `elaborate` scaffolding.** Mirror the `page-architecture` pattern from #252 — same coaching modes, same handler shape, same precondition gating.
- **Page file is source-of-truth.** Both the authoring view and the audit trail (`canonical_blocks_embedded`) live in the page file. Bundle-file projections (`script-package`) are deferred to a sibling PR.
- **Light validation in v1.** Section presence and ordering only. Deeper canon-content drift checking goes through `hone` in a sibling PR.

---

## 3. Architecture

### 3.1 Schema (13 sections, fixed order)

| # | Title | Source | Notes |
|---|---|---|---|
| 1 | Style foundation | embed: `reference/canon/style-foundation.md` | universal — every panel |
| 2 | Lighting laws | embed: `reference/canon/lighting-laws.md` | universal — every panel |
| 3 | Pacing role | derived: page architecture's panel hierarchy | cites a register from `panel-registers.md`; states relative weight |
| 4 | Shot grammar | panel-specific | camera, framing, angle |
| 5 | Stage geography | embed: `reference/canon/locations/<location>.md` + panel-specific | location-canon block plus panel positioning |
| 6 | Character block | embed: `reference/canon/characters/<id>.md` per character on-frame | one embed per on-frame character |
| 7 | In this panel | panel-specific | character framing + what each is doing in this beat |
| 8 | Focal objects + render priorities | panel-specific | what gets detail, what dissolves |
| 9 | Lighting logic | panel-specific | which side catches the lamp, where shadows fall |
| 10 | Symbolic detail (low weight) | embed: `reference/canon/motifs/<id>.md` when motif on-frame | explicitly labeled "low weight" |
| 11 | Action | panel-specific | declarative, procedural ("lowers the inkpot"), not narrative |
| 12 | Emotional subtext (low weight) | panel-specific | single brief sentence, explicitly labeled "low weight" |
| 13 | Negative constraints | panel-specific | exclusions + motif-specific reinforcements |

### 3.2 Page-file body conventions

Per-panel prompts live inside the existing `## Image-generation prompts` body section (already a convention from #251). Each panel becomes a `### Panel N` subsection containing exactly 13 `#### N. <Title>` sub-subsections in canonical order:

```
## Image-generation prompts

### Panel 1

#### 1. Style foundation

<verbatim embed from style-foundation.md>

#### 2. Lighting laws

<verbatim embed from lighting-laws.md>

#### 3. Pacing role

Register: dominant. Relative weight: page's emotional fulcrum.

#### 4. Shot grammar

Medium-close, slight low angle, two-shot.

#### 5. Stage geography

<verbatim embed from locations/archive-studio.md>

Panel-specific: Lucien at desk frame-right; Mirelle in doorway frame-left.

#### 6. Character block

<verbatim embed from characters/lucien-vey.md>

<verbatim embed from characters/mirelle-ash.md>

#### 7. In this panel

Lucien sets down the inkpot, eyes still on the page. Mirelle has paused
mid-step, one hand on the door frame.

#### 8. Focal objects + render priorities

Detail: the inkpot, Lucien's hands, the lamp. Dissolve: background shelves,
ceiling, distant clutter.

#### 9. Lighting logic

Single lamp, frame-right of Lucien. Mirelle in chiaroscuro shadow.

#### 10. Symbolic detail (low weight)

<verbatim embed from motifs/inkpot.md> (low weight)

#### 11. Action

Lucien lowers the inkpot to the desk. Mirelle pauses in the doorway.

#### 12. Emotional subtext (low weight)

A small private ritual interrupted. (low weight)

#### 13. Negative constraints

No supernatural luminosity. No reflections in the inkpot. No glamour
lighting on Mirelle's face.

### Panel 2

<another 13-section block>
```

The `### Panel N` and `#### N. <Title>` headers are the parseable anchors. Bodies vary. The canonical section titles are fixed strings (case-insensitive on header line; whitespace tolerant).

### 3.3 Extractors

Add to `pages.py`:

- `extract_panel_prompts(path: str) -> dict[int, str]` — returns `{panel_index: panel_body}` mapping. Panel index is the integer parsed from `### Panel N`. Panel body is everything AFTER the `### Panel N` header up to (but not including) the next `### Panel M` header, the next `## ...` header, or EOF — header line itself is stripped, body is whitespace-trimmed. Returns `{}` when the page file is missing, has no `## Image-generation prompts` section, or has the section but no `### Panel N` subsections.
- `extract_panel_sections(panel_body: str) -> dict[int, str]` — operates on the body string returned by `extract_panel_prompts` for a single panel. Returns `{section_index: section_body}` mapping. Section index is the integer parsed from `#### N. <Title>`. Section body is everything AFTER the `#### N. <Title>` header up to the next `#### M. ...` header or EOF — header stripped, body whitespace-trimmed. Used by `validate_page_file` to detect missing sections and wrong-order sections.
- Module-level constant `PANEL_SECTION_TITLES: Final[tuple[str, ...]]` — the 13 canonical titles, fixed order.

### 3.4 Frontmatter audit trail

The existing `canonical_blocks_embedded:` field (#252) is extended on each run to record every canon file path that the panel prompts embed (style-foundation, lighting-laws, per-location, per-character, per-motif). Duplicates are skipped (the helper from #252 already handles this).

---

## 4. Authoring command

`storyforge elaborate --stage panel-prompts` — extends the existing stage taxonomy. Mirrors `page-architecture` (#252) at every structural level.

### 4.1 Stage registration

- Add `'panel-prompts'` to `VALID_STAGES` in `cmd_elaborate.py`
- Add `_run_panel_prompts_handler_gn(project_dir, *, dry_run, coaching, page, scene, force) -> Literal[0, 1]` handler
- Medium-gate: graphic-novel only
- Short-circuit in `_run_main_stage` before standard scaffolding (mirrors page-architecture short-circuit)

### 4.2 Flags

- (no flag) — process every page missing panel prompts
- `--page <page_id>` — single page
- `--scene <scene_id>` — every page of one scene
- `--force` — overwrite existing panel prompts
- `--dry-run` — print one full prompt and exit; no API calls
- `--coaching {full|coach|strict}` — overrides project default
- The existing `--page` / `--scene` / `--force` argparse flags from #252 are **reused** (no new argparse work).

### 4.3 Preconditions (warn-and-skip)

For each page being processed:
- Page file's `## Page architecture` is populated (needed because section 3 cites the register from the panel hierarchy)
- Scene brief has `panel_breakdown` populated
- Required canon populated (not TODO): `style-foundation`, `lighting-laws`
- Optional canon present for `location` and each `characters_present` (logged as NOTE, not WARN, when absent — degraded output but not blocking)

Same warn-and-skip semantics as page-architecture: skip with WARN, continue with remaining pages. Exit 1 only when zero pages processed AND at least one was skipped on precondition or LLM failure.

### 4.4 LLM grain

**One API call per page.** The LLM receives:
- Page architecture body (canonical register-per-panel hierarchy from #252)
- Page frontmatter (panel_count, characters_present, location, timeline)
- Scene brief row (panel_breakdown, visual_keywords, key_actions, key_dialogue, motifs)
- Scene intent row (function, emotional_arc, value_at_stake, on_stage)
- Canon embeds: style-foundation, lighting-laws, location, each on-frame character, each motif on visual_keywords

Output contract: emit `### Panel 1` through `### Panel N` where N is `panel_count`, each containing exactly the 13 `#### N. <Title>` subsections in canonical order, and nothing else. Sections 1, 2, 5, 6, 10 must contain the canon embed verbatim (the LLM is given the embed text and instructed to paste it).

### 4.5 Coaching modes

- **full** — LLM drafts all panels for the page directly into `## Image-generation prompts`
- **coach** — Writes `working/coaching/panel-prompts-<page_id>.md` with the 13-section template per panel, embedded canon blocks, brief inputs, and a question list per section. No mutation of the page file.
- **strict** — Stamps a deterministic 13-section template per panel directly into the page file. Sections 1, 2, 5, 6, 10 contain the canon embeds verbatim (no LLM call); sections 3, 4, 7, 8, 9, 11, 12, 13 contain `TODO — <constraint>` placeholders. No LLM call.

### 4.6 Model + cost tracking

`select_model('drafting')` (Opus). Per-page invocations log to ledger under operation `elaborate-panel-prompts-gn`.

### 4.7 Splice behavior

- If `## Image-generation prompts` doesn't exist in the page file, insert it after `## Page-blocking prompt` (or `## Page architecture` if no blocking prompt) and before `## Panel script`.
- If the section exists with panel content and `--force` is not set, the precondition filter excludes this page (gap-fill default).
- If the section exists with panel content and `--force` is set, replace its body wholesale (drop existing panel content, splice new).

---

## 5. Cleanup integration

Three new finding kinds added to `PageFindingKind` Literal in `pages.py`:

- `missing_panel_prompts` — `## Image-generation prompts` section is absent OR present but contains zero `### Panel N` subsections
- `panel_prompt_section_missing` — a `### Panel N` block is missing one or more of the 13 required `#### N. <Title>` subsections. `detail` names the panel index and which sections are missing.
- `panel_prompt_wrong_section_order` — sections present but out of canonical order. `detail` names the panel index and where the order broke.

All three are **warnings** (informational; do not affect cleanup exit code). They surface gaps that the author should fill via `elaborate --stage panel-prompts` or by hand.

Cleanup output finding types are prefixed with `page_` per existing convention: `page_missing_panel_prompts`, `page_panel_prompt_section_missing`, `page_panel_prompt_wrong_section_order`. Each finding's `action` message names the exact command to populate the missing content.

---

## 6. Hone integration (deferred — sibling PR)

Deeper validation that doesn't fit cleanup's "structural-only" remit:
- Does section 1's body actually match the verbatim canon embed from `style-foundation.md`?
- Does section 3 cite a register that exists in `panel-registers.md`?
- Does section 13 reinforce motif-specific exclusions?

These are content-drift checks. They live in `hone` because hone is the data-quality command. Tracking as a sibling issue; out of scope for v1.

---

## 7. Script-package integration (deferred — sibling PR)

A future `manuscript/panel-prompts.md` bundle file (analogous to `page-blocking-prompts.md` from #252) is **out of scope for v1**. The artist reads panel prompts from `pages/<page_id>.md` directly. The bundle file can be added in a follow-up once the schema stabilizes.

---

## 8. File-by-file inventory

### Create

- `scripts/lib/python/storyforge/prompts_panel_prompts.py` — strict template + coach brief + full LLM prompt builders (mirrors `prompts_page_architecture.py`)
- `tests/test_pages_panel_prompt_extractors.py` — extractor unit tests
- `tests/test_pages_panel_prompt_validation.py` — finding-kind unit + integration tests
- `tests/test_prompts_panel_prompts.py` — prompt-builder unit tests
- `tests/test_cmd_elaborate_panel_prompts.py` — handler unit + mocked-API e2e tests

### Modify

- `scripts/lib/python/storyforge/pages.py` — add `extract_panel_prompts`, `extract_panel_sections`, `PANEL_SECTION_TITLES`; extend `PageFindingKind` Literal with the three new values; extend `validate_page_file` body-section checks
- `scripts/lib/python/storyforge/cmd_elaborate.py` — add `'panel-prompts'` to `VALID_STAGES`; add `_run_panel_prompts_handler_gn` per-page dispatcher; add short-circuit in `_run_main_stage`
- `scripts/lib/python/storyforge/cmd_cleanup.py` — wire the three new finding kinds in `_check_page_files`
- `skills/elaborate/SKILL.md` — document the new stage + coaching behavior
- `skills/forge/SKILL.md` — recommend `panel-prompts` after `page-architecture` in GN pipeline
- `CLAUDE.md` — add `panel-prompts` to elaborate stage table; add a GN-section paragraph describing the 13-section schema and where prompts live
- `.claude-plugin/plugin.json` — bump to **1.41.0** (additive feature)

### Unchanged but load-bearing

- `templates/reference/canon/style-foundation.md` — embed source for section 1
- `templates/reference/canon/lighting-laws.md` — embed source for section 2
- `templates/reference/canon/panel-registers.md` — section 3 cites the register vocabulary
- `templates/reference/canon/page-rhythm-rules.md` — informs the prompt's pacing guidance

---

## 9. Testing strategy

### Unit

- `extract_panel_prompts` — single panel, multiple panels, missing section, header variants, em-dash robustness
- `extract_panel_sections` — all 13 present, some missing, wrong order, body extraction
- `PANEL_SECTION_TITLES` is `Final[tuple[str, ...]]` with exactly 13 entries in canonical order
- Strict template renderer — deterministic output for `(page_id, panel_count, canon_blocks, panel_registers)`; snapshot-tested
- Coach brief renderer — embeds canon, lists questions per section, identifies write target
- Full prompt builder — assembles canon embeds, page architecture, brief, intent; output contract is in the prompt
- `validate_page_file` — three new finding kinds fire when expected, do not fire when content is well-formed and ordered

### Integration

- Mocked-API end-to-end: handler parses canned page-level response, splices into page file, updates `canonical_blocks_embedded` audit trail
- Preconditions: skip pages whose `## Page architecture` is empty; skip pages whose `panel_breakdown` is empty; skip when required canon is TODO
- `cleanup` on a fixture with one well-formed page and one malformed page surfaces the expected finding kinds
- Coaching modes: strict writes deterministic template with canon embedded but TODO bodies for sections 3/4/7/8/9/11/12/13; coach writes brief; full mocked-API drafts both panels

### Coverage discipline

Every new `PageFindingKind` value has at least one trigger test. Mirrors the convention from #252.

---

## 10. Out of scope (deferred to sibling PRs)

- `hone` deeper validation (canon-content drift detection)
- `script-package` bundle file (`manuscript/panel-prompts.md`)
- Per-character / per-location canon embed in the page-architecture stage (separate issue noted on #252's spec)
- LLM-grounded content quality scoring of panel prompts (would belong in `score`)

---

## 11. Open questions resolved during design

- **One stage or extend briefs?** New stage. Briefs produces CSV cells; panel prompts produce multi-line markdown. Conflating them would couple unrelated artifacts.
- **Per-panel or per-page LLM calls?** Per-page. Keeps cross-panel continuity in one context and halves cost.
- **Where do panel prompts live?** Inside the page file's existing `## Image-generation prompts` section, as `### Panel N` subsections. No new file, no new convention beyond what #251 already established.
- **Strict-mode canon embedding?** Yes — strict still embeds sections 1, 2, 5, 6, 10 verbatim from canon. Only sections 3, 4, 7, 8, 9, 11, 12, 13 are TODO scaffolding. This means strict mode performs file I/O (canon reads) but no LLM call.
- **Validation depth in v1?** Section presence + ordering only. Body-content checks go through `hone` later.

---

## 12. Acceptance criteria

1. `storyforge elaborate --stage panel-prompts` runs end-to-end on a GN project with populated page architecture, drafts 13-section prompts for every panel on every gap-fillable page, respects coaching levels, logs costs.
2. `cleanup` reports the three new finding kinds against malformed page files; report is informational.
3. Test suite passes with the new coverage above (~40 new tests).
4. Version bumped to **1.41.0** in `.claude-plugin/plugin.json`.
5. `CLAUDE.md` documents the new stage in the elaborate table.
