# Web Annotation System Design

## Problem

Author reads published web books on iPad/phone and needs to capture notes (highlights, comments, margin notes) tied to specific chapters and scenes. Current workflow — reading epubs in Books, manually commenting, then reverse-mapping page numbers to scenes — is fragile and tedious.

## Solution

A client-side annotation overlay for Storyforge web books, with file-based export that feeds back into the Storyforge revision pipeline.

## Architecture: Separate Overlay (Approach B)

Annotation logic lives in dedicated `annotations.js` + `annotations.css` files, injected into web book output at build time via an `--annotate` flag. The reading experience (`reading.js` / `reading.css`) remains untouched. This separation enables toggling annotations on/off and supporting different modes (author vs. beta reader) later.

## Annotation UX

### Text Selection (Inline Comments & Highlights)

- **Desktop:** Select text, popover appears with "Highlight" and "Comment" buttons. "Highlight" saves immediately. "Comment" expands to text input.
- **Mobile:** Persistent bottom toolbar. When text is selected, toolbar shows Highlight / Comment / Cancel actions. Avoids fighting native iOS selection UI.
- Tap any existing highlight to view, edit, or delete.

### Margin Notes

- **Desktop:** "+" button appears in the left margin on paragraph hover. Click to open a note input anchored to that paragraph.
- **Mobile:** Margin note button is always visible in the bottom toolbar. Tap to add a note anchored to the paragraph closest to the viewport center at the time of tap.

### Visual Treatment

- Highlights: subtle background color, theme-aware (yellow on light, muted on dark, warm on sepia).
- Comment indicators: small colored dot at end of highlight.
- Margin notes: small icon in left gutter (desktop) or inline marker (mobile).
- Annotation count badge in the nav bar per chapter.

## Data Model

Each annotation:

```json
{
  "id": "uuid",
  "type": "highlight | comment | margin-note",
  "chapter": "chapter-03",
  "scene": "scene-12",
  "anchor": {
    "paragraphIndex": 5,
    "startOffset": 23,
    "endOffset": 87,
    "selectedText": "the exact highlighted words"
  },
  "comment": "This feels rushed — expand the beat",
  "createdAt": "2026-03-11T14:30:00Z"
}
```

- `anchor` is null for margin notes (attached to `paragraphIndex` only).
- `scene` derived from `data-scene` attributes embedded in chapter HTML at build time.
- `selectedText` stored for fuzzy-matching when text changes between builds.
- `paragraphIndex` counts all block-level elements within the scene's `<section>` (`<p>`, `<blockquote>`, etc.), not just `<p>` tags.

### Anchor Re-validation on Load

When the annotation layer loads on a rebuilt web book, it checks each stored annotation's `selectedText` against the text at the stored `paragraphIndex` + offsets. If the text doesn't match, it scans nearby paragraphs for a substring match. Annotations that can't be re-anchored are shown in a "stale annotations" panel at the bottom of the chapter with their original quoted text, so the user can manually re-anchor or delete them.

### Storage

localStorage, keyed by `storyforge-annotations-{book-slug}`. Per-device, per-browser. Annotations are stored per-chapter (separate keys) to stay well within mobile Safari's 5MB localStorage limit, even for heavily annotated long novels.

## Export

Two formats, both download as files:

### JSON (for Storyforge skill)

```json
{
  "book": "The Novel Title",
  "exportedAt": "2026-03-11T14:45:00Z",
  "annotator": "author",
  "annotations": [...]
}
```

### Markdown (human-readable)

```markdown
# Annotations: The Novel Title
Exported: 2026-03-11

## Chapter 3: The Turning Point

### Scene: scene-12
> "the exact highlighted words"
This feels rushed — expand the beat

### Scene: scene-13 (margin note)
The pacing in this whole section drags after the reveal.
```

Grouped by chapter, then scene, in reading order. Export available per-chapter and "export all" from the TOC page.

## Prerequisites

- Fix: `--format web` is missing from the format validation case in `storyforge-assemble` (line 141). The `web` format must be accepted alongside `epub|pdf|html|markdown|all` before annotation work can begin.

## Build Integration

### New Template Files

- `templates/production/web-book/annotations.js` — selection handling, popover/toolbar, localStorage, export
- `templates/production/web-book/annotations.css` — highlights, popover, toolbar, margin notes (theme-aware)

### Assembly Changes

`storyforge-assemble --annotate` flag:

- Only applies to `--format web` output. Ignored for epub/pdf/html/markdown. When used with `--format all`, applies only to the web output.
- Injects annotation JS/CSS into chapter HTML template
- Adds `data-scene` attributes to scene sections in chapter output (see Scene Boundary Injection below)
- Without the flag, web book output is unchanged

### Scene Boundary Injection

Scene boundaries are currently lost during chapter assembly — `assemble_chapter()` concatenates scene prose with scene-break markers but discards scene IDs. To preserve them for annotations:

- During `assemble_chapter()`, inject HTML comment markers into the assembled markdown before pandoc conversion: `<!-- scene:scene-12 -->` before each scene's content.
- Pandoc passes HTML comments through to output unchanged.
- In `generate_web_book()`, post-process the pandoc HTML: replace each `<!-- scene:scene-XX -->` comment with `<section data-scene="scene-XX">` and close the previous section. This wraps each scene's paragraphs in a data-attributed section element.
- This approach requires no changes to pandoc invocation or template structure.

### Optional Config

```yaml
production:
  annotations:
    enabled: true
    mode: author  # or "beta" later
```

In `chapter-map.yaml` as alternative to CLI flag. Precedence: `--annotate` flag > YAML config. No `--no-annotate` override needed — just omit the flag or set `enabled: false`.

## Storyforge Import: `storyforge:annotate` Skill

1. User drops export file into `working/` (e.g., `working/annotations-{book-slug}.json`)
2. Skill parses JSON, groups annotations by scene
3. Reads referenced scene files, verifies anchors by checking if `selectedText` appears as a substring in the scene content. If exact substring isn't found, falls back to longest common substring matching. Annotations that can't be matched (< 50% overlap) are flagged with a warning in the summary rather than silently dropped.
4. Categorizes notes (content changes, pacing, cuts, continuity, etc.)
5. Presents summary: annotation count, most-annotated scenes
6. Generates revision plan feeding into `storyforge:plan-revision`

Markdown export works too — skill parses it, or user pastes directly into a conversation.

## Future: Beta Readers

- Annotation layer injected with `mode: beta` config
- Beta readers annotate and export their own files
- `storyforge:annotate` merges multiple export files
- Flags conflicting feedback, surfaces consensus (e.g., "3 of 5 readers flagged this passage")
- No backend required — each reader downloads their own export file and sends it to the author

## Constraints

- Purely client-side (GitHub Pages hosting)
- No backend, no database, no user accounts
- Cross-device via file export/transfer (AirDrop, email, etc.)
- Must work on mobile Safari (iPad, iPhone)
- BSD sed compatibility for any script changes
