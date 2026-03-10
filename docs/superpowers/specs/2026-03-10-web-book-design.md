# Web Book Format — Design Spec

## Overview

Replace the single-file HTML output with a multi-file web book: a self-contained directory of HTML pages that reads like a beautifully typeset book in the browser. Each chapter is its own page, parts get interstitial title pages, and the landing page remembers where you left off.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Visual direction | Literary (light/sepia) + Atmospheric (dark) | Three themes, two moods in one design system via theme toggle |
| OS dark mode | Respected automatically | `prefers-color-scheme: dark` triggers atmospheric dark theme |
| Parts handling | Interstitial title pages | Mirrors print book experience; part label on chapter pages |
| TOC style | Modal overlay with part dividers | Simple, works on mobile, stays out of the way |
| Landing page | Resume-aware | Shows "Continue Reading" on return; clean title page on first visit |
| Typography | Web fonts with system fallback | Good serif body font (Literata or Crimson Pro) + display heading font |
| Font loading | Shipped in plugin repo | woff2 files committed to `templates/production/web-book/fonts/`; copied to output at generation time. No network dependency. |

## File Structure

```
manuscript/output/web/
├── index.html              # Landing page (cover, metadata, resume link)
├── contents.html           # Full TOC with part groupings
├── fonts/                  # Web font files (woff2)
│   ├── literata-regular.woff2
│   ├── literata-italic.woff2
│   └── ...
├── cover.png               # Cover image (copied from assets)
├── chapters/
│   ├── part-01.html        # Part One: The Wick (interstitial)
│   ├── chapter-01.html     # Chapter 1: The Wick
│   ├── chapter-02.html     # Chapter 2: Current Numbers
│   ├── ...
│   ├── chapter-08.html     # Chapter 8: The East Wing (last in Part One)
│   ├── part-02.html        # Part Two: What Burns (interstitial)
│   ├── chapter-09.html     # Chapter 9: What She Carried
│   ├── ...
│   └── chapter-29.html     # Chapter 29: The Weight of Burning
└── (all CSS and JS are inlined in each HTML file — fully self-contained pages)
```

Every HTML file is self-contained: CSS and JS inlined in `<style>` and `<script>` tags. No external stylesheet or script files. This means the directory works when opened directly from the filesystem (`file://`) with zero setup. Font files are the one external dependency (referenced via relative `url()` paths in inlined `@font-face` rules).

## Pages

### Landing Page (`index.html`)

- Cover image (if available)
- Book title, author name, logline
- "Start Reading" button → first part interstitial or first chapter
- "Table of Contents" link → `contents.html`
- Copyright line
- **Resume-aware**: An empty `<div id="resume-link">` sits above the "Start Reading" button. On load, JS checks localStorage for `storyforge-last-chapter`. If found, it looks up the chapter title from a `CHAPTER_MAP` JS object (baked in at generation time — see Assembly Integration) and populates the div with a "Continue Reading: Chapter N — Title" link. When no history exists, the div stays empty and invisible.
- Theme toggle in corner

### Contents Page (`contents.html`)

- Top nav bar with book title and theme toggle
- "Contents" heading
- Chapters grouped under part headings. The HTML structure uses `<h3>` elements as part dividers within the `<ol>`:
  ```html
  <h3 class="toc-part">Part One: The Wick</h3>
  <ol class="toc-list" start="1">
    <li><a href="chapters/chapter-01.html">The Wick</a></li>
    <li><a href="chapters/chapter-02.html">Current Numbers</a></li>
    ...
  </ol>
  <h3 class="toc-part">Part Two: What Burns</h3>
  <ol class="toc-list" start="9">
    <li><a href="chapters/chapter-09.html">What She Carried</a></li>
    ...
  </ol>
  ```
- When no parts exist, the TOC is a single flat `<ol>` (no part headings)
- "Back to cover" link at bottom

### Part Interstitial Pages (`chapters/part-NN.html`)

- Centered part number and title on an otherwise empty page
- Atmospheric treatment: in dark theme, subtle accent line or gradient
- In light/sepia: clean, generous whitespace, understated typography
- Navigation:
  - **Part One (first part)**: ← links to `../contents.html` ("Contents"), → links to first chapter of this part
  - **Subsequent parts**: ← links to last chapter of the previous part, → links to first chapter of this part

### Chapter Pages (`chapters/chapter-NN.html`)

- Progress bar (thin accent-colored line at top, shows scroll position)
- Sticky nav bar: book title (links to contents), TOC toggle button, theme toggle
- Part label above chapter heading: `<div class="part-label">Part One: The Wick</div>` in small caps. Uses template variable `{{PART_LABEL}}` — empty string when no parts exist.
- Chapter heading: "Chapter 1: The Wick"
- Chapter content (converted from markdown via pandoc)
- Drop cap on first paragraph of each chapter
- Scene breaks rendered as asterism (⁂) or ornamental break
- Bottom navigation: prev/next chapter with titles. Navigation flow includes part interstitials:
  - Chapter 8 → next → Part Two interstitial
  - Part Two interstitial → next → Chapter 9
  - Chapter 1 → prev → Part One interstitial (or contents if Part One interstitial is the very first page)
- TOC overlay (modal): triggered by hamburger button or `t` key. Shows full part/chapter structure with current chapter highlighted. Same HTML structure as contents page TOC, with `.toc-current` class on the active chapter's `<li>`.
- Book-style paragraphs: first-line indent, no vertical gaps between paragraphs
- First paragraph after headings/breaks: no indent
- On load, JS writes current chapter slug to `localStorage.setItem('storyforge-last-chapter', slug)` for resume tracking.

## Visual Design

### Light Theme (Literary)

- Background: warm off-white (`#faf8f4`)
- Text: deep brown-black (`#2c2420`)
- Accent: saddle brown (`#8b4513`)
- Maximum whitespace, 36em text column
- Chapter headings: uppercase, letterspaced, centered, subtle rule underneath
- Drop cap in accent color
- Blockquotes: left border, italic, dimmed

### Dark Theme (Atmospheric)

- Background: near-black with warmth (`#0f0e0d` or similar, darker than current `#1a1816`)
- Text: warm light gray (`#d4cec6`)
- Accent: warm gold (`#c4956a`)
- Same text column width, but with atmospheric enhancements:
  - Subtle accent line (horizontal gradient) below the nav bar
  - Part interstitials: accent-colored part title, darker background
  - Slightly increased line-height for the darker background (improves readability)
  - Drop cap in gold accent
- The dark theme should feel cinematic and immersive, not just "inverted colors"

### Sepia Theme (Literary, warm)

- Background: parchment (`#f4ecd8`)
- Text: dark brown (`#3b2e1e`)
- Accent: warm brown (`#8b5e3c`)
- Warmest, most book-like feel
- Same literary treatment as light theme

### OS Dark Mode

- If no theme is stored in localStorage, check `prefers-color-scheme: dark`
- If OS is dark → apply dark (atmospheric) theme automatically
- If OS is light → apply light (literary) theme
- Once the user manually toggles, their choice is stored and takes precedence

## Typography

### Font Loading

Web font files (woff2) are committed to the plugin repository at `templates/production/web-book/fonts/`. At generation time, the assembly script copies them into the output `fonts/` directory. No network requests during generation. Literata is OFL-licensed (free to redistribute).

Font stack with graceful fallback:
- Body: `'Literata', Georgia, 'Iowan Old Style', 'Palatino Linotype', Palatino, serif`
- Headings/nav: same family or a complementary display face
- UI elements (buttons, labels): system sans-serif stack

```css
@font-face {
  font-family: 'Literata';
  src: url('../fonts/literata-regular.woff2') format('woff2');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
@font-face {
  font-family: 'Literata';
  src: url('../fonts/literata-italic.woff2') format('woff2');
  font-weight: 400;
  font-style: italic;
  font-display: swap;
}
```

`font-display: swap` ensures text is visible immediately with fallback fonts, then swaps to the web font when loaded. No invisible text.

Note: Since CSS is inlined per-page, `@font-face` `url()` paths must be relative to the HTML file's location. Chapter and part pages (in `chapters/`) use `../fonts/`, top-level pages (`index.html`, `contents.html`) use `fonts/`. The assembly script handles this by substituting `{{FONT_PATH}}` in the inlined CSS — set to `../fonts` for chapter/part pages, `fonts` for top-level pages.

### Text Sizing

- Body: `clamp(18px, 1.15rem + 0.25vw, 21px)` (current approach, good)
- Line height: 1.58 (light/sepia), 1.65 (dark — slightly more generous for readability)
- Text column: `max-width: 36em` (~65-75 characters per line)

## JavaScript Features

All existing features carry forward, plus enhancements:

### Existing (keep as-is)
- **Theme switching**: cycle through light → dark → sepia
- **Reading position persistence**: saves scroll position per chapter to localStorage
- **Chapter completion tracking**: marks chapters read at 90% scroll, shows checkmarks in TOC
- **Progress bar**: thin accent line showing scroll position
- **Auto-hiding nav**: hides on scroll down, shows on scroll up
- **Keyboard navigation**: left/right arrows for prev/next, `t` for TOC, `Escape` to close
- **Reduced motion**: respects `prefers-reduced-motion`

### New
- **Resume tracking**: On each chapter page load, store the current chapter slug in `localStorage.setItem('storyforge-last-chapter', slug)`. The landing page reads this value, looks up the chapter title from a `CHAPTER_MAP` object (a slug→title JS object baked into the landing page at generation time via `{{CHAPTER_MAP_JSON}}`), and populates the `#resume-link` div.
- **Current chapter highlight in TOC**: when the TOC overlay opens on a chapter page, add `.toc-current` to the active chapter's `<li>` and scroll it into view.
- **Part groupings in TOC overlay**: the TOC overlay HTML (baked into each chapter page at generation time via `{{TOC_ENTRIES}}`) uses the same part-grouped structure as the contents page — `<h3 class="toc-part">` dividers between `<ol>` blocks.

## Assembly Integration

### Function: `generate_web_book()`

The existing function in `scripts/lib/assembly.sh` handles web generation. Updates needed:

1. **Bug fix**: Pass `"$project_dir"` to `count_chapters` (line 862). Currently called without argument, returning 0.
2. **Part data reading**: Build a parts array by reading the `parts:` list from the chapter map. For each chapter, read its `part:` field via `read_chapter_field "$ch" "$project_dir" "part"` to determine which part it belongs to.
3. **Navigation chain**: Build an ordered list of all pages (part interstitials + chapters) to compute prev/next links. The sequence for a book with 2 parts and 4 chapters is: `[part-01, chapter-01, chapter-02, part-02, chapter-03, chapter-04]`. Each page's prev/next links point to its neighbors in this list. The first item's prev links to `../contents.html`.
4. **Part interstitial generation**: For each part, generate `part-NN.html` using the `part.html` template. Substitute `{{PART_NUMBER}}`, `{{PART_TITLE}}`, `{{PREV_LINK}}`, `{{NEXT_LINK}}`.
5. **Part label on chapters**: For each chapter, look up its part title and pass it as `{{PART_LABEL}}` — e.g., `Part One: The Wick`. Empty string if no parts exist.
6. **Chapter map JSON**: Build a JS object mapping chapter slugs to titles (e.g., `{"chapter-01": "The Wick", "chapter-02": "Current Numbers", ...}`) and inject it into the landing page template as `{{CHAPTER_MAP_JSON}}`.
7. **TOC entries with parts**: Build `{{TOC_ENTRIES}}` as part-grouped HTML (see Contents Page section above) rather than a flat list.
8. **Font bundling**: Copy woff2 files from `${plugin_dir}/templates/production/web-book/fonts/` to `${output_dir}/fonts/`.
9. **Font path substitution**: Replace `{{FONT_PATH}}` in inlined CSS — `../fonts` for pages in `chapters/`, `fonts` for top-level pages.

### Templates

Update existing templates and add new ones in `templates/production/web-book/`:

| Template file | Status | Generates | New variables |
|---|---|---|---|
| `index.html` | Update | `index.html` | `{{CHAPTER_MAP_JSON}}`, `{{FONT_PATH}}` |
| `toc.html` | Update | `contents.html` | `{{TOC_ENTRIES}}` (now part-grouped), `{{FONT_PATH}}` |
| `chapter.html` | Update | `chapters/chapter-NN.html` | `{{PART_LABEL}}`, `{{FONT_PATH}}` |
| `part.html` | **New** | `chapters/part-NN.html` | `{{PART_NUMBER}}`, `{{PART_TITLE}}`, `{{PREV_LINK}}`, `{{NEXT_LINK}}`, `{{FONT_PATH}}` |
| `reading.css` | Update | (inlined) | `{{FONT_PATH}}` in `@font-face` declarations; new styles for `.part-label`, `.toc-part`, `.toc-current`, `.part-page`, atmospheric dark enhancements |
| `reading.js` | Update | (inlined) | Resume tracking logic, TOC highlight logic |
| `fonts/` | **New** | `fonts/` | woff2 files (Literata regular, italic, bold at minimum) |

Note: The template source file `toc.html` generates the output file `contents.html`. This naming is inherited from the existing codebase.

### Chapter Map Requirements

The chapter map must have a `parts:` array for part interstitials to be generated. If no parts are defined, the web book generates without interstitials — just chapters, no part labels, flat TOC.

```yaml
parts:
  - number: 1
    title: "The Wick"
  - number: 2
    title: "What Burns"
```

Each chapter entry has a `part:` field referencing the part number.

## What's NOT Changing

- The epub, PDF, and single-file HTML formats are untouched
- The `--format web` flag and dispatch in `storyforge-assemble` already exist (just fixed the validation)
- The chapter assembly pipeline (scene → chapter markdown files) is unchanged
- The web book reads from the same `manuscript/chapters/` markdown files as other formats

## Testing Plan

1. Generate web book for Thornwall (29 chapters, 4 parts, cover image)
2. Verify all pages load and link correctly (including part interstitials in navigation chain)
3. Test theme switching across all three themes
4. Test OS dark mode auto-detection
5. Verify resume-aware landing page works after reading a chapter
6. Test keyboard navigation through part interstitials
7. Verify TOC overlay shows part groupings and current chapter highlight
8. Test on mobile viewport (responsive)
9. Test with `file://` protocol (no server needed)
10. Test with a project that has no parts (should generate without interstitials, flat TOC)
