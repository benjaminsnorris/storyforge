# Epub Preparation — Design

**Date:** 2026-03-03
**Status:** Implemented (Phases 1–3), Phase 4 partial
**Version:** 0.5.1
**Scope:** Adding book production capabilities to Storyforge — assembling scenes into chapters, generating front/back matter, formatting for epub/PDF, cover integration, and genre-appropriate layout.

## Why This Belongs in Storyforge

The writing process doesn't end when the prose is done. The book isn't a book until it's packaged. Storyforge already knows the scene index, the chapter structure, the genre, the voice, and the author's creative decisions. All of that informs formatting and assembly choices. A separate tool would lose this context.

That said, book production is a different domain from prose craft. It involves visual design, typography, metadata standards, and toolchain dependencies (pandoc, epubcheck, possibly LaTeX). It should live in Storyforge as a distinct phase with its own skill and script, sharing project context but not trying to reuse the writing/revision infrastructure.

## Phase Model

Add a `production` phase after `complete` (or after `review` if the author wants to produce while still revising):

```
... → review → complete → production
```

Or allow production to run in parallel with revision — the author might want to produce a proof copy for beta readers while revision is ongoing.

## What It Includes

### 1. Chapter Assembly

The bridge between scenes and a book. The scene index defines scene order; chapter assembly groups scenes into chapters.

- **Chapter mapping** — a new artifact (`reference/chapter-map.yaml` or an extension to scene-index.yaml) that defines which scenes belong to which chapter, with chapter titles.
- **Assembly script** — `./storyforge assemble` reads the chapter map, concatenates scene files in order, produces chapter files in `manuscript/`.
- **Scene break markers** — configurable (blank line, ornamental break `* * *`, custom symbol).
- **Chapter heading format** — configurable (numbered, titled, numbered + titled, no heading).

### 2. Front Matter

- Title page (title, author, copyright year)
- Copyright page (with configurable license text, ISBN if provided)
- Dedication (author provides text)
- Epigraph (author provides text)
- Table of contents (auto-generated from chapter map)
- Optional: author's note, content warnings, maps/illustrations

### 3. Back Matter

- Acknowledgments
- About the author
- Also by (other books)
- Optional: glossary, appendices, reading group guide, excerpt from next book

### 4. Typography and Layout

- **Genre presets** — literary fiction (serif, generous margins, elegant chapter headings), thriller (tighter layout, bolder headings), romance (specific industry conventions), fantasy (ornamental breaks, map support).
- **Font selection** — the author picks from a curated set of open-source fonts suitable for ebooks.
- **Scene break style** — blank line, ornamental, custom.
- **Drop caps** — optional first-letter styling on chapter openings.
- **CSS stylesheet** — generated per project, stored in the project.

### 5. Cover Integration

- The author provides a cover image (front cover at minimum).
- Storyforge handles metadata embedding (cover image referenced in OPF manifest).
- Optional: generate a simple typographic cover from title + author name if no image is provided.

### 6. Output Formats

- **epub3** — primary target. Validates with epubcheck.
- **PDF** — via weasyprint or LaTeX. Useful for proof copies and print-on-demand.
- **HTML** — single-file or multi-file HTML as an intermediate format and for web publication.
- **Kindle (KFX/mobi)** — if tooling allows (Kindle Previewer or kindlegen).

### 7. Validation

- **epubcheck** — run automatically after epub generation, report errors.
- **Metadata validation** — ensure required fields (title, author, language, ISBN) are present.
- **Image validation** — cover meets minimum resolution requirements.
- **Structural validation** — all chapters have content, TOC links resolve, no orphaned files.

## Storyforge Integration Points

### New Artifacts in storyforge.yaml

```yaml
artifacts:
  chapter_map:
    exists: false
    path: reference/chapter-map.yaml
    updated:
  manuscript:
    exists: false
    path: manuscript/
    updated:
```

### New Script

`./storyforge assemble` — reads chapter map + scene files, produces manuscript files and epub/PDF.

Options:
- `./storyforge assemble` — full assembly + epub generation
- `./storyforge assemble --format epub` — epub only
- `./storyforge assemble --format pdf` — PDF only
- `./storyforge assemble --draft` — quick assembly without full formatting (for proofing)

### New Skill

`/storyforge:produce` (or `/storyforge:publish` or `/storyforge:assemble`) — interactive skill that walks the author through production decisions:
- Chapter mapping (grouping scenes into chapters)
- Front/back matter content
- Typography and layout choices
- Cover setup
- Format selection

The skill saves all decisions to project config and then provides the assembly command.

### Directory Changes

The `manuscript/` directory (currently removed from init) comes back as a production output directory:

```
manuscript/
├── chapters/           # Assembled chapter files
├── front-matter/       # Title page, copyright, dedication, etc.
├── back-matter/        # Acknowledgments, about, also-by
├── assets/             # Cover image, CSS, fonts
└── output/             # Generated epub, PDF files
```

This directory is created by the assembly script, not by init. It appears only when the author enters production.

## Dependencies

This is the first Storyforge feature that requires external tools:
- **pandoc** — markdown to epub/HTML conversion (widely available, cross-platform)
- **epubcheck** — epub validation (Java-based, optional but recommended)
- **weasyprint** or **LaTeX** — for PDF generation (optional)

The skill should detect available tools and adjust capabilities accordingly. Core assembly (scenes → chapters → markdown manuscript) requires no external tools. Epub generation requires pandoc. PDF is optional.

## Open Questions — Resolved

1. **Chapter mapping: separate file or extension to scene-index?** ✅ **Decided: separate file.** `reference/chapter-map.yaml` keeps a clean separation between the atomic scene index (used by drafting/evaluation/revision) and the chapter structure (used only for production). Added as a tracked artifact in `storyforge.yaml`.

2. **When does the `manuscript/` directory appear?** ✅ **Decided: on first `./storyforge assemble` run.** The init skill does not create it. It appears only when the author enters production.

3. **Should assembly be idempotent?** ✅ **Decided: yes, overwrite.** The output is deterministic from the inputs (chapter map + scene files + production settings). No timestamped copies.

4. **How to handle illustrations/maps?** ⏳ **Deferred.** The `manuscript/assets/` directory exists for images, but no illustration pipeline is implemented yet. Cover images are supported via pandoc's `--epub-cover-image`.

5. **Print formatting?** ⏳ **Deferred.** PDF generation works via weasyprint or LaTeX, but print-on-demand trim/bleed/gutter settings are not yet implemented. A future phase.

6. **Series metadata?** ⏳ **Partially addressed.** Added optional `series` fields to `storyforge.yaml` project section (`series_name`, `series_position`). Epub metadata generation includes these when present. Full EPUB 3 series metadata (calibre:series) is a future refinement.

## Implementation Approach

This is a larger feature that should be built incrementally:

1. **Phase 1: Chapter assembly.** ✅ The chapter map (`reference/chapter-map.yaml`), the assembly library (`scripts/lib/assembly.sh`), and the `storyforge-assemble` script. Scenes → chapters → manuscript markdown files.

2. **Phase 2: Epub generation.** ✅ Pandoc integration, 6 genre CSS presets (default, literary-fiction, thriller, romance, fantasy, science-fiction), cover embedding, epubcheck validation, epub metadata with ISBN/series support.

3. **Phase 3: The production skill.** ✅ `/storyforge:produce` — interactive skill that guides the author through chapter mapping, typography choices, front/back matter, cover setup, and copyright. Integrated with forge hub routing.

4. **Phase 4: PDF and additional formats.** 🔶 Partial. PDF generation via weasyprint or LaTeX is implemented in the assembly library. Kindle (KFX/mobi) is not implemented. Print-on-demand formatting (trim, bleed, gutter) is deferred.

Each phase is independently useful. Phase 1 alone solves the "I have scenes but no book" problem.

## Implementation Notes

- 252 tests across 6 suites (87 new for assembly/production)
- All autonomous agents (write, evaluate, revise, assemble) commit and push after completing their work
- Genre CSS presets live in `templates/production/css/` in the plugin
- Chapter map template at `templates/production/chapter-map-template.yaml`
- The `production` phase was added to the phase enum in storyforge.yaml
