# Epub Preparation — Design

**Date:** 2026-03-03
**Status:** Draft
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

## Open Questions

1. **Chapter mapping: separate file or extension to scene-index?** A separate `chapter-map.yaml` is cleaner but adds another artifact. Extending scene-index with `chapter:` fields keeps everything in one place but makes the index more complex.

2. **When does the `manuscript/` directory appear?** On first `./storyforge assemble` run? Or when the author enters the production phase? The init skill currently doesn't create it.

3. **Should assembly be idempotent?** If the author runs `./storyforge assemble` twice, should it overwrite or create a new timestamped output?

4. **How to handle illustrations/maps?** Some genres (fantasy, children's) include interior illustrations. This needs image handling beyond just the cover.

5. **Print formatting?** Print-on-demand (KDP, IngramSpark) has specific requirements for trim size, bleed, margins, gutter. Is this in scope or a separate concern?

6. **Series metadata?** If this is book 2 of a trilogy, the epub needs series metadata. Where does this live in storyforge.yaml?

## Implementation Approach

This is a larger feature that should be built incrementally:

1. **Phase 1: Chapter assembly.** The chapter map, the assembly script, and basic markdown output. No formatting, no epub. Just scenes → chapters → manuscript files.

2. **Phase 2: Epub generation.** Pandoc integration, CSS styling, cover embedding, epubcheck validation. Genre presets.

3. **Phase 3: The production skill.** Interactive skill that guides the author through all production decisions.

4. **Phase 4: PDF and additional formats.** LaTeX/weasyprint integration, print-ready output.

Each phase is independently useful. Phase 1 alone solves the "I have scenes but no book" problem.
