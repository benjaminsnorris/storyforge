# Web Book Format Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-file web book output format with per-chapter pages, part interstitials, resume-aware landing, and atmospheric dark theme.

**Architecture:** The web format extends the existing `generate_web_book()` function in `scripts/lib/assembly.sh`, which reads chapter markdown files and stamps them into HTML templates. New part-reading functions, a `part.html` template, updated CSS/JS, and font files are added to the plugin. The assembly script builds a navigation chain (parts interleaved with chapters) and generates all pages with inlined CSS/JS.

**Tech Stack:** Bash (assembly), HTML/CSS/JS (templates), pandoc (markdown→HTML conversion), woff2 fonts (Literata, OFL-licensed)

**Spec:** `docs/superpowers/specs/2026-03-10-web-book-design.md`

---

## Chunk 1: Part-Reading Functions and Tests

### Task 1: Add parts to test fixture

**Files:**
- Modify: `tests/fixtures/test-project/reference/chapter-map.yaml`

- [ ] **Step 1: Add parts array and part fields to the test fixture chapter map**

```yaml
# Chapter Map — The Cartographer's Silence
# Maps scenes to chapters for manuscript assembly.

parts:
  - number: 1
    title: "The Expedition"
  - number: 2
    title: "The Blank"

chapters:
  - title: "The Finest Cartographer"
    heading: numbered-titled
    part: 1
    scenes:
      - act1-sc01
      - act1-sc02

  - title: "Into the Blank"
    heading: numbered-titled
    part: 2
    scenes:
      - act2-sc01

production:
  author: "Test Author"
  language: en
  scene_break: ornamental
  default_heading: numbered-titled
  include_toc: true
  cover_image:
  genre_preset: fantasy
  copyright:
    year: 2026
    isbn: "978-0-000000-00-0"
    license: "All rights reserved."
  front_matter:
    dedication:
    epigraph:
  back_matter:
    acknowledgments:
    about-the-author:
    also-by:
```

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/test-project/reference/chapter-map.yaml
git commit -m "Test fixture: add parts to chapter map"
```

### Task 2: Write tests for part-reading functions

**Files:**
- Modify: `tests/test-assembly.sh`

- [ ] **Step 1: Add tests for count_parts, read_part_field, get_chapter_part_title**

Append to `tests/test-assembly.sh`:

```bash
# ============================================================================
# count_parts
# ============================================================================

result=$(count_parts "$PROJECT_DIR")
assert_equals "2" "$result" "count_parts: finds 2 parts in fixture"

result=$(count_parts "/nonexistent/path")
assert_equals "0" "$result" "count_parts: returns 0 for missing project"

# ============================================================================
# read_part_field
# ============================================================================

result=$(read_part_field 1 "$PROJECT_DIR" "title")
assert_equals "The Expedition" "$result" "read_part_field: reads title from part 1"

result=$(read_part_field 2 "$PROJECT_DIR" "title")
assert_equals "The Blank" "$result" "read_part_field: reads title from part 2"

result=$(read_part_field 1 "$PROJECT_DIR" "number")
assert_equals "1" "$result" "read_part_field: reads number from part 1"

# ============================================================================
# get_chapter_part_title
# ============================================================================

result=$(get_chapter_part_title 1 "$PROJECT_DIR")
assert_equals "The Expedition" "$result" "get_chapter_part_title: chapter 1 belongs to part 'The Expedition'"

result=$(get_chapter_part_title 2 "$PROJECT_DIR")
assert_equals "The Blank" "$result" "get_chapter_part_title: chapter 2 belongs to part 'The Blank'"

# ============================================================================
# read_chapter_field: part field
# ============================================================================

result=$(read_chapter_field 1 "$PROJECT_DIR" "part")
assert_equals "1" "$result" "read_chapter_field: reads part number from chapter 1"

result=$(read_chapter_field 2 "$PROJECT_DIR" "part")
assert_equals "2" "$result" "read_chapter_field: reads part number from chapter 2"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/bennorris/Developer/storyforge && ./tests/run-tests.sh
```

Expected: failures for `count_parts`, `read_part_field`, `get_chapter_part_title` (functions don't exist yet)

- [ ] **Step 3: Commit**

```bash
git add tests/test-assembly.sh
git commit -m "Tests: add part-reading function tests (red)"
```

### Task 3: Implement part-reading functions

**Files:**
- Modify: `scripts/lib/assembly.sh` (add after `read_chapter_field` function, around line 64)

- [ ] **Step 1: Add count_parts function**

Add after the `read_chapter_field` function block (after line ~64):

```bash
# Count the number of parts defined in chapter-map.yaml
# Usage: count_parts "/path/to/project"
count_parts() {
    local project_dir="$1"
    local chapter_map="${project_dir}/reference/chapter-map.yaml"

    if [[ ! -f "$chapter_map" ]]; then
        echo "0"
        return 0
    fi

    # Count lines matching "- number:" under the parts: section
    awk '
        /^parts:/ { in_parts=1; next }
        in_parts && /^[^ ]/ { exit }
        in_parts && /^[[:space:]]*- number:/ { count++ }
        END { print count+0 }
    ' "$chapter_map"
}
```

- [ ] **Step 2: Add get_part_block and read_part_field functions**

```bash
# Get the Nth part block (1-indexed) from chapter-map.yaml
# Usage: get_part_block 1 "/path/to/project"
get_part_block() {
    local part_num="$1"
    local project_dir="$2"
    local chapter_map="${project_dir}/reference/chapter-map.yaml"

    if [[ ! -f "$chapter_map" ]]; then
        return 1
    fi

    awk -v num="$part_num" '
        /^parts:/ { in_parts=1; next }
        in_parts && /^[^ ]/ { exit }
        in_parts && /^[[:space:]]*- number:/ { count++ }
        in_parts && count == num { print }
        in_parts && count > num { exit }
    ' "$chapter_map"
}

# Read a field from a part block
# Usage: read_part_field 1 "/path/to/project" "title"
read_part_field() {
    local part_num="$1"
    local project_dir="$2"
    local field="$3"

    local block
    block=$(get_part_block "$part_num" "$project_dir")
    if [[ -z "$block" ]]; then
        return 1
    fi

    echo "$block" \
        | grep -E "[[:space:]](-[[:space:]]+)?${field}:" \
        | head -1 \
        | sed "s/^.*${field}:[[:space:]]*//" \
        | sed 's/^["'"'"']//' \
        | sed 's/["'"'"']$//' \
        | sed 's/[[:space:]]*$//'
}
```

- [ ] **Step 3: Add get_chapter_part_title helper**

```bash
# Get the part title for a given chapter number
# Usage: get_chapter_part_title 1 "/path/to/project"
get_chapter_part_title() {
    local chapter_num="$1"
    local project_dir="$2"

    local part_num
    part_num=$(read_chapter_field "$chapter_num" "$project_dir" "part")
    if [[ -z "$part_num" ]]; then
        echo ""
        return 0
    fi

    read_part_field "$part_num" "$project_dir" "title"
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/bennorris/Developer/storyforge && ./tests/run-tests.sh
```

Expected: all new part-related tests PASS, existing tests still PASS

- [ ] **Step 5: Commit and push**

```bash
git add scripts/lib/assembly.sh tests/test-assembly.sh
git commit -m "Add part-reading functions for chapter map (count_parts, read_part_field, get_chapter_part_title)"
git push
```

---

## Chunk 2: Font Files and Templates

### Task 4: Download and add Literata font files

**Files:**
- Create: `templates/production/web-book/fonts/literata-regular.woff2`
- Create: `templates/production/web-book/fonts/literata-italic.woff2`
- Create: `templates/production/web-book/fonts/literata-bold.woff2`

- [ ] **Step 1: Download Literata woff2 files from Google Fonts**

```bash
mkdir -p /Users/bennorris/Developer/storyforge/templates/production/web-book/fonts
cd /Users/bennorris/Developer/storyforge/templates/production/web-book/fonts

# Download from google-webfonts-helper or Google Fonts API
# Literata is OFL-licensed — free to redistribute
curl -L -o literata-regular.woff2 "https://fonts.gstatic.com/s/literata/v37/or3PQ6P12-iJxAIgLa78DkrbXsDgk0oVDaDPYLanFLHpPf2TbJG_F_bcTWCWp8g.woff2"
curl -L -o literata-italic.woff2 "https://fonts.gstatic.com/s/literata/v37/or3NQ6P12-iJxAIgLYT1PLs1Zd0nfUwAbeGVKoRYzNiCp1OUedn8f7XWSUKTt8iVow.woff2"
curl -L -o literata-bold.woff2 "https://fonts.gstatic.com/s/literata/v37/or3PQ6P12-iJxAIgLa78DkrbXsDgk0oVDaDPYLanFLHpPf2TbBe4F_bcTWCWp8g.woff2"
```

Note: If the Google Fonts URLs change or fail, download Literata from https://fonts.google.com/specimen/Literata and extract the woff2 files manually. The exact URLs may need updating at implementation time.

- [ ] **Step 2: Verify files are non-empty**

```bash
ls -la /Users/bennorris/Developer/storyforge/templates/production/web-book/fonts/
```

Each file should be 20-80KB.

- [ ] **Step 3: Commit**

```bash
git add templates/production/web-book/fonts/
git commit -m "Add Literata web font files (OFL licensed)"
```

### Task 5: Create part.html template

**Files:**
- Create: `templates/production/web-book/part.html`

- [ ] **Step 1: Write the part interstitial template**

```html
<!DOCTYPE html>
<html lang="{{LANG}}" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{PART_TITLE}} — {{BOOK_TITLE}}</title>
<meta name="author" content="{{AUTHOR}}">
{{CANONICAL}}
<script>{{HEAD_SCRIPT}}</script>
<style>
{{CSS}}
</style>
</head>
<body class="part-page">

<nav class="book-nav">
  <a href="../contents.html" class="nav-title">{{BOOK_TITLE}}</a>
  <div class="nav-controls">
    <button class="theme-toggle" aria-label="Change theme">
      <span class="icon-light">&#9788;</span>
      <span class="icon-dark">&#9790;</span>
      <span class="icon-sepia">&#9782;</span>
    </button>
  </div>
</nav>

<main class="part-interstitial">
  <div class="part-number">Part {{PART_NUMBER}}</div>
  <h1 class="part-title">{{PART_TITLE}}</h1>
  <div class="part-ornament"></div>
</main>

<nav class="chapter-nav">
  {{PREV_LINK}}
  {{NEXT_LINK}}
</nav>

<script>
{{JS}}
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/production/web-book/part.html
git commit -m "Add part interstitial page template"
```

### Task 6: Update reading.css

**Files:**
- Modify: `templates/production/web-book/reading.css`

- [ ] **Step 1: Add font-face declarations at the top of the file (after the theme variables)**

Insert after the `:root` and `@media (prefers-color-scheme: dark)` blocks (after current line ~34):

```css
/* --- FONT LOADING ------------------------------------------------------- */

@font-face {
  font-family: 'Literata';
  src: url('{{FONT_PATH}}/literata-regular.woff2') format('woff2');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
@font-face {
  font-family: 'Literata';
  src: url('{{FONT_PATH}}/literata-italic.woff2') format('woff2');
  font-weight: 400;
  font-style: italic;
  font-display: swap;
}
@font-face {
  font-family: 'Literata';
  src: url('{{FONT_PATH}}/literata-bold.woff2') format('woff2');
  font-weight: 700;
  font-style: normal;
  font-display: swap;
}
```

- [ ] **Step 2: Update body font-family to use Literata**

Change the `body` rule's `font-family` from:
```css
font-family: Georgia, 'Iowan Old Style', 'Palatino Linotype', Palatino, serif;
```
to:
```css
font-family: 'Literata', Georgia, 'Iowan Old Style', 'Palatino Linotype', Palatino, serif;
```

- [ ] **Step 3: Darken the dark theme background and add atmospheric line-height**

Change the dark theme variables from:
```css
[data-theme="dark"] {
  --bg: #1a1816; --text: #d4cec6; --text-dim: #8a8078;
  --accent: #c4956a; --surface: #252220; --border: rgba(255,255,255,0.06);
}
```
to:
```css
[data-theme="dark"] {
  --bg: #0f0e0d; --text: #d4cec6; --text-dim: #8a8078;
  --accent: #c4956a; --surface: #1a1816; --border: rgba(255,255,255,0.06);
}
```

And add atmospheric line-height override:
```css
[data-theme="dark"] .reading-column,
[data-theme="dark"] .chapter-content { line-height: 1.65; }
```

- [ ] **Step 4: Add atmospheric accent line for dark theme nav**

```css
[data-theme="dark"] .book-nav::after {
  content: "";
  position: absolute;
  bottom: -1px;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent) 30%, var(--accent) 70%, transparent);
  opacity: 0.3;
}
```

- [ ] **Step 5: Add part label styles**

```css
/* --- PART LABEL (above chapter heading) --------------------------------- */

.part-label {
  text-align: center;
  font-size: 0.72em;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--text-dim);
  margin-top: 3em;
  margin-bottom: 0.5em;
  transition: color 0.4s ease;
}

/* When part label is present, reduce chapter h1 top margin */
.part-label + h1 {
  margin-top: 0.5em;
}
```

- [ ] **Step 6: Add part interstitial page styles**

```css
/* --- PART INTERSTITIAL PAGE --------------------------------------------- */

.part-interstitial {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 70vh;
  text-align: center;
  padding: 2em 1.5rem;
}

.part-number {
  font-size: 0.75em;
  letter-spacing: 0.25em;
  text-transform: uppercase;
  color: var(--text-dim);
  margin-bottom: 1em;
}

.part-title {
  font-size: 2em;
  font-weight: normal;
  letter-spacing: 0.08em;
  color: var(--text);
  line-height: 1.3;
  margin: 0;
}

.part-ornament {
  width: 3em;
  height: 1px;
  background: var(--border);
  margin-top: 2em;
}

[data-theme="dark"] .part-number { color: var(--accent); }
[data-theme="dark"] .part-ornament {
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: 0.4;
}
```

- [ ] **Step 7: Add TOC part heading and current chapter styles**

```css
/* --- TOC PART HEADINGS -------------------------------------------------- */

.toc-part {
  font-size: 0.72em;
  font-weight: normal;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--text-dim);
  margin: 1.5em 0 0.5em;
  padding: 0 0.25em;
}

.toc-part:first-child { margin-top: 0; }

/* Current chapter highlight */
.toc-panel li.toc-current a,
.toc-list li.toc-current a {
  color: var(--accent);
  font-weight: 700;
}

.toc-panel li.toc-current a::before {
  color: var(--accent);
}
```

- [ ] **Step 8: Add resume link styles for landing page**

```css
/* --- RESUME LINK -------------------------------------------------------- */

.resume-link {
  display: block;
  margin-bottom: 1.5em;
  font-size: 0.9em;
  color: var(--accent);
  text-decoration: none;
  transition: color 0.3s ease;
}

.resume-link:hover { filter: brightness(1.2); }

.resume-label {
  display: block;
  font-size: 0.75em;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-dim);
  margin-bottom: 0.3em;
}
```

- [ ] **Step 9: Commit**

```bash
git add templates/production/web-book/reading.css
git commit -m "CSS: add Literata font, atmospheric dark theme, part/resume styles"
```

### Task 7: Update reading.js

**Files:**
- Modify: `templates/production/web-book/reading.js`

- [ ] **Step 1: Add resume tracking — store last-read chapter**

Add at the end of the IIFE, before the closing `})();`:

```javascript
  // ---------------------------------------------------------------------------
  // 9. Resume tracking — store last-visited chapter
  // ---------------------------------------------------------------------------

  var currentSlug = getChapterSlug();
  if (currentSlug && currentSlug !== 'index' && currentSlug !== 'contents') {
    localStorage.setItem('storyforge-last-chapter', currentSlug);
  }
```

- [ ] **Step 2: Add TOC current chapter highlight**

Add after the `applyReadClasses()` call:

```javascript
  // ---------------------------------------------------------------------------
  // 10. TOC current chapter highlight
  // ---------------------------------------------------------------------------

  function highlightCurrentChapter() {
    var slug = getChapterSlug();
    if (!slug) return;
    var links = document.querySelectorAll('.toc-overlay a, .toc-list a');
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute('href') || '';
      var linkSlug = href.replace(/^.*\//, '').replace(/\.html?$/, '');
      if (linkSlug === slug) {
        var li = links[i].closest('li');
        if (li) {
          li.classList.add('toc-current');
        }
      }
    }
  }

  highlightCurrentChapter();
```

- [ ] **Step 3: Scroll current chapter into view when TOC opens**

Update the `toggleToc` function:

```javascript
  function toggleToc() {
    if (!tocOverlay) return;
    tocOverlay.classList.toggle('active');
    // Scroll current chapter into view when opening
    if (tocOverlay.classList.contains('active')) {
      var current = tocOverlay.querySelector('.toc-current');
      if (current) {
        setTimeout(function () {
          current.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }, 100);
      }
    }
  }
```

- [ ] **Step 4: Commit**

```bash
git add templates/production/web-book/reading.js
git commit -m "JS: add resume tracking, TOC current chapter highlight"
```

### Task 8: Update index.html template (resume-aware landing)

**Files:**
- Modify: `templates/production/web-book/index.html`

- [ ] **Step 1: Add resume link div and chapter map JSON**

Update the landing page body. Add `<div id="resume-link"></div>` before the "Start Reading" link, and add resume JS after the main script block:

```html
<!DOCTYPE html>
<html lang="{{LANG}}" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{BOOK_TITLE}} by {{AUTHOR}}</title>
<meta name="author" content="{{AUTHOR}}">
<meta name="description" content="{{DESCRIPTION}}">
{{CANONICAL}}
<script>{{HEAD_SCRIPT}}</script>
<style>
{{CSS}}
</style>
</head>
<body>

<div class="book-landing">

  {{COVER_IMG}}

  <div class="book-meta">
    <h1 class="book-title">{{BOOK_TITLE}}</h1>
    <p class="book-author">{{AUTHOR}}</p>
    {{LOGLINE}}
    {{SERIES}}
  </div>

  <div id="resume-link"></div>
  <a href="chapters/{{FIRST_PAGE}}" class="start-reading">Start Reading</a>
  <a href="contents.html" class="toc-link">Table of Contents</a>

  {{COPYRIGHT}}
</div>

<script>
{{JS}}
</script>
<script>
// Resume-aware landing page
(function() {
  var CHAPTER_MAP = {{CHAPTER_MAP_JSON}};
  var lastChapter = localStorage.getItem('storyforge-last-chapter');
  if (lastChapter && CHAPTER_MAP[lastChapter]) {
    var el = document.getElementById('resume-link');
    if (el) {
      el.innerHTML = '<a href="chapters/' + lastChapter + '.html" class="resume-link">' +
        '<span class="resume-label">Continue Reading</span>' +
        CHAPTER_MAP[lastChapter] + '</a>';
    }
  }
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/production/web-book/index.html
git commit -m "Landing page: add resume-aware link and chapter map JSON slot"
```

### Task 9: Update toc.html template (part groupings)

**Files:**
- Modify: `templates/production/web-book/toc.html`

- [ ] **Step 1: Replace flat TOC with part-grouped TOC**

The `{{TOC_ENTRIES}}` variable will now contain part-grouped HTML (generated by the assembly function). Update the template to use a `<div>` wrapper instead of a single `<ol>`:

```html
<!DOCTYPE html>
<html lang="{{LANG}}" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Contents — {{BOOK_TITLE}}</title>
<meta name="author" content="{{AUTHOR}}">
{{CANONICAL}}
<script>{{HEAD_SCRIPT}}</script>
<style>
{{CSS}}
</style>
</head>
<body>

<nav class="book-nav">
  <a href="index.html" class="nav-title">{{BOOK_TITLE}}</a>
  <div class="nav-controls">
    <button class="theme-toggle" aria-label="Change theme">
      <span class="icon-light">&#9788;</span>
      <span class="icon-dark">&#9790;</span>
      <span class="icon-sepia">&#9782;</span>
    </button>
  </div>
</nav>

<main class="reading-column" style="padding-top: 4em;">
  <h1 style="text-align: center; margin-bottom: 1.5em;">Contents</h1>

  <div class="toc-contents">
{{TOC_ENTRIES}}
  </div>

  {{BACK_MATTER_LINKS}}
</main>

<nav class="chapter-nav" style="justify-content: center;">
  <a href="index.html" class="nav-link">&larr; Back to cover</a>
</nav>

<script>
{{JS}}
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/production/web-book/toc.html
git commit -m "TOC template: support part-grouped chapter listings"
```

### Task 10: Update chapter.html template (part label)

**Files:**
- Modify: `templates/production/web-book/chapter.html`

- [ ] **Step 1: Add part label and update reading-column class usage**

```html
<!DOCTYPE html>
<html lang="{{LANG}}" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{CHAPTER_TITLE}} — {{BOOK_TITLE}}</title>
<meta name="author" content="{{AUTHOR}}">
{{CANONICAL}}
<script>{{HEAD_SCRIPT}}</script>
<style>
{{CSS}}
</style>
</head>
<body data-chapter="{{CHAPTER_SLUG}}" data-chapter-num="{{CHAPTER_NUM}}" data-total-chapters="{{TOTAL_CHAPTERS}}">

<div class="progress-bar"></div>

<nav class="book-nav">
  <a href="../contents.html" class="nav-title">{{BOOK_TITLE}}</a>
  <div class="nav-controls">
    <button class="toc-toggle" aria-label="Table of contents">&#9776;</button>
    <button class="theme-toggle" aria-label="Change theme">
      <span class="icon-light">&#9788;</span>
      <span class="icon-dark">&#9790;</span>
      <span class="icon-sepia">&#9782;</span>
    </button>
  </div>
</nav>

<main class="reading-column drop-cap">
{{PART_LABEL}}
{{CHAPTER_CONTENT}}
</main>

<nav class="chapter-nav">
  {{PREV_LINK}}
  {{NEXT_LINK}}
</nav>

<!-- TOC Overlay -->
<div class="toc-overlay">
  <div class="toc-panel">
    <h2>Contents</h2>
    <div class="toc-contents">
{{TOC_ENTRIES}}
    </div>
  </div>
</div>

<script>
{{JS}}
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/production/web-book/chapter.html
git commit -m "Chapter template: add part label, part-grouped TOC overlay"
```

- [ ] **Step 3: Push all template changes**

```bash
git push
```

---

## Chunk 3: Assembly Function Rewrite

### Task 11: Rewrite generate_web_book() in assembly.sh

This is the largest task. The existing function is ~220 lines. The rewrite adds part interstitial generation, the navigation chain, part-grouped TOC, chapter map JSON, and font bundling.

**Files:**
- Modify: `scripts/lib/assembly.sh` (function `generate_web_book`, starting at line ~819)

- [ ] **Step 1: Fix count_chapters bug — pass project_dir**

In `generate_web_book()`, change line ~862 from:
```bash
total_chapters=$(count_chapters)
```
to:
```bash
total_chapters=$(count_chapters "$project_dir")
```

- [ ] **Step 2: Add template check for part.html**

Update the template existence check (line ~832) to include `part.html`:
```bash
for tmpl in reading.css reading.js index.html toc.html chapter.html part.html; do
```

- [ ] **Step 3: Add font bundling**

After the `mkdir -p "${output_dir}/chapters"` line, add:
```bash
    # Copy font files
    local font_src="${template_dir}/fonts"
    if [[ -d "$font_src" ]]; then
        mkdir -p "${output_dir}/fonts"
        cp "${font_src}"/*.woff2 "${output_dir}/fonts/" 2>/dev/null || true
        log "  Fonts copied to ${output_dir}/fonts/"
    fi
```

- [ ] **Step 4: Read parts data and build navigation chain**

After reading metadata and before generating pages, add the navigation chain logic:

```bash
    # --- Read parts data ---
    local total_parts
    total_parts=$(count_parts "$project_dir")

    # Build ordered list of part titles indexed by part number
    local -a part_titles=()
    for (( p=1; p<=total_parts; p++ )); do
        local pt
        pt=$(read_part_field "$p" "$project_dir" "title")
        part_titles+=("$pt")
    done

    # Build navigation chain: ordered list of [type, slug, title, part_num]
    # This interleaves part interstitials with chapters
    local -a nav_types=()
    local -a nav_slugs=()
    local -a nav_titles=()
    local current_part=0

    for (( ch=1; ch<=total_chapters; ch++ )); do
        local ch_part
        ch_part=$(read_chapter_field "$ch" "$project_dir" "part" 2>/dev/null || echo "")

        # Insert part interstitial when entering a new part
        if [[ -n "$ch_part" && "$ch_part" != "$current_part" ]]; then
            current_part="$ch_part"
            local part_slug
            part_slug=$(printf 'part-%02d' "$ch_part")
            local part_idx=$(( ch_part - 1 ))
            nav_types+=("part")
            nav_slugs+=("$part_slug")
            nav_titles+=("${part_titles[$part_idx]:-Part $ch_part}")
        fi

        local ch_title="${ch_titles[$((ch-1))]}"
        local ch_slug="${ch_slugs[$((ch-1))]}"
        nav_types+=("chapter")
        nav_slugs+=("$ch_slug")
        nav_titles+=("$ch_title")
    done

    local nav_total=${#nav_types[@]}
```

- [ ] **Step 5: Separate chapter array population from TOC building**

The existing code populates `ch_titles` and `ch_slugs` arrays AND builds `toc_entries` in the same loop. Split this: keep the array population loop as-is (it feeds the navigation chain in Step 4), then build `toc_entries` in a separate pass below it.

Keep the existing array population loop unchanged:
```bash
    local ch_titles=()
    local ch_slugs=()
    for (( ch=1; ch<=total_chapters; ch++ )); do
        local ch_title
        ch_title=$(read_chapter_field "$ch" "$project_dir" "title")
        local ch_slug
        ch_slug=$(printf 'chapter-%02d' "$ch")
        ch_titles+=("$ch_title")
        ch_slugs+=("$ch_slug")
    done
```

Then build the part-grouped TOC entries as a separate block:

```bash
    # --- Build part-grouped TOC entries ---
    local toc_entries=""
    local toc_current_part=""
    local ch_counter=0

    for (( ch=1; ch<=total_chapters; ch++ )); do
        local ch_part
        ch_part=$(read_chapter_field "$ch" "$project_dir" "part" 2>/dev/null || echo "")
        local ch_title="${ch_titles[$((ch-1))]}"
        local ch_slug="${ch_slugs[$((ch-1))]}"

        # Insert part heading when entering a new part
        if [[ -n "$ch_part" && "$ch_part" != "$toc_current_part" ]]; then
            # Close previous list if open
            if [[ -n "$toc_current_part" ]]; then
                toc_entries="${toc_entries}  </ol>
"
            fi
            toc_current_part="$ch_part"
            local part_idx=$(( ch_part - 1 ))
            local pt="${part_titles[$part_idx]:-Part $ch_part}"
            toc_entries="${toc_entries}  <h3 class=\"toc-part\">Part ${ch_part}: ${pt}</h3>
  <ol class=\"toc-list\" start=\"${ch}\">
"
        elif [[ -z "$toc_current_part" && "$ch" -eq 1 ]]; then
            # No parts — start a flat list
            toc_entries="${toc_entries}  <ol class=\"toc-list\">
"
        fi

        toc_entries="${toc_entries}    <li><a href=\"chapters/${ch_slug}.html\" data-chapter=\"${ch_slug}\">${ch_title}</a></li>
"
    done
    # Close final list
    toc_entries="${toc_entries}  </ol>
"
```

- [ ] **Step 6: Build chapter map JSON for resume feature**

```bash
    # --- Build chapter map JSON for resume feature ---
    local chapter_map_json="{"
    for (( ch=1; ch<=total_chapters; ch++ )); do
        local ch_title="${ch_titles[$((ch-1))]}"
        local ch_slug="${ch_slugs[$((ch-1))]}"
        if (( ch > 1 )); then
            chapter_map_json="${chapter_map_json},"
        fi
        chapter_map_json="${chapter_map_json}\"${ch_slug}\":\"Chapter ${ch}: ${ch_title}\""
    done
    chapter_map_json="${chapter_map_json}}"
```

- [ ] **Step 7: Replace _web_sub helper with new version**

Delete the existing `_web_sub` function and replace it with this version that adds font path and chapter map substitutions:

```bash
    _web_sub() {
        local content="$1"
        local font_path="${2:-fonts}"
        content="${content//\{\{BOOK_TITLE\}\}/$title}"
        content="${content//\{\{AUTHOR\}\}/$author}"
        content="${content//\{\{LANG\}\}/$language}"
        content="${content//\{\{DESCRIPTION\}\}/$description}"
        content="${content//\{\{TOTAL_CHAPTERS\}\}/$total_chapters}"
        content="${content//\{\{CSS\}\}/${css_content//\{\{FONT_PATH\}\}/$font_path}}"
        content="${content//\{\{JS\}\}/$js_content}"
        content="${content//\{\{HEAD_SCRIPT\}\}/$head_script}"
        content="${content//\{\{TOC_ENTRIES\}\}/$toc_entries}"
        content="${content//\{\{FONT_PATH\}\}/$font_path}"
        content="${content//\{\{CHAPTER_MAP_JSON\}\}/$chapter_map_json}"

        if [[ -n "$base_url" ]]; then
            content="${content//\{\{CANONICAL\}\}/<link rel=\"canonical\" href=\"${base_url}\">}"
        else
            content="${content//\{\{CANONICAL\}\}/}"
        fi

        echo "$content"
    }
```

- [ ] **Step 8: Update index.html generation to use FIRST_PAGE**

Determine the first page (part interstitial or chapter 1):

```bash
    # --- Determine first page ---
    local first_page="${nav_slugs[0]}.html"

    # --- Generate index.html ---
    local index_tmpl
    index_tmpl=$(cat "${template_dir}/index.html")

    # Cover image
    local cover_html=""
    if [[ -n "$cover_image" && -f "${project_dir}/${cover_image}" ]]; then
        cp "${project_dir}/${cover_image}" "${output_dir}/cover.png" 2>/dev/null || \
        cp "${project_dir}/${cover_image}" "${output_dir}/cover.jpg" 2>/dev/null || true
        local cover_ext="${cover_image##*.}"
        cover_html="<img src=\"cover.${cover_ext}\" alt=\"${title}\" class=\"book-cover\">"
    fi

    # Logline
    local logline_html=""
    if [[ -n "$logline" ]]; then
        logline_html="<p class=\"book-logline\">${logline}</p>"
    fi

    # Series
    local series_html=""
    if [[ -n "$series_name" ]]; then
        series_html="<p class=\"book-series\">${series_name}"
        if [[ -n "$series_pos" ]]; then
            series_html="${series_html} &middot; Book ${series_pos}"
        fi
        series_html="${series_html}</p>"
    fi

    # Copyright
    local copyright_html="<p class=\"book-copyright\">&copy; ${copyright_year} ${author}</p>"

    local index_content
    index_content=$(_web_sub "$index_tmpl" "fonts")
    index_content="${index_content//\{\{COVER_IMG\}\}/$cover_html}"
    index_content="${index_content//\{\{LOGLINE\}\}/$logline_html}"
    index_content="${index_content//\{\{SERIES\}\}/$series_html}"
    index_content="${index_content//\{\{COPYRIGHT\}\}/$copyright_html}"
    index_content="${index_content//\{\{FIRST_PAGE\}\}/$first_page}"
    echo "$index_content" > "${output_dir}/index.html"
```

- [ ] **Step 9: Update contents.html generation**

```bash
    local toc_content
    toc_content=$(_web_sub "$toc_tmpl" "fonts")
    toc_content="${toc_content//\{\{BACK_MATTER_LINKS\}\}/$back_matter_html}"
    echo "$toc_content" > "${output_dir}/contents.html"
```

- [ ] **Step 10: Generate part interstitial pages and chapter pages using nav chain**

Replace the existing chapter generation loop with a nav-chain-aware loop:

```bash
    # --- Read part template ---
    local part_tmpl
    part_tmpl=$(cat "${template_dir}/part.html")

    # --- Generate all pages using navigation chain ---
    for (( i=0; i<nav_total; i++ )); do
        local page_type="${nav_types[$i]}"
        local page_slug="${nav_slugs[$i]}"
        local page_title="${nav_titles[$i]}"

        # Build prev/next links
        local prev_link=""
        local next_link=""

        if (( i > 0 )); then
            local prev_slug="${nav_slugs[$((i-1))]}"
            local prev_title="${nav_titles[$((i-1))]}"
            local prev_label="&larr; Previous"
            if [[ "${nav_types[$((i-1))]}" == "part" ]]; then
                prev_label="&larr; ${prev_title}"
            fi
            prev_link="<a href=\"${prev_slug}.html\" class=\"prev-chapter nav-link\"><span class=\"nav-label\">${prev_label}</span><span class=\"nav-chapter-title\">${prev_title}</span></a>"
        else
            prev_link="<a href=\"../contents.html\" class=\"prev-chapter nav-link\"><span class=\"nav-label\">&larr; Contents</span></a>"
        fi

        if (( i < nav_total - 1 )); then
            local next_slug="${nav_slugs[$((i+1))]}"
            local next_title="${nav_titles[$((i+1))]}"
            local next_label="Next &rarr;"
            if [[ "${nav_types[$((i+1))]}" == "part" ]]; then
                next_label="${next_title} &rarr;"
            fi
            next_link="<a href=\"${next_slug}.html\" class=\"next-chapter nav-link\"><span class=\"nav-label\">${next_label}</span><span class=\"nav-chapter-title\">${next_title}</span></a>"
        else
            next_link="<a href=\"../index.html\" class=\"next-chapter nav-link\"><span class=\"nav-label\">Finished &rarr;</span><span class=\"nav-chapter-title\">Back to cover</span></a>"
        fi

        if [[ "$page_type" == "part" ]]; then
            # --- Part interstitial page ---
            local part_num="${page_slug#part-}"
            part_num=$((10#$part_num))  # remove leading zero

            local page_content
            page_content=$(_web_sub "$part_tmpl" "../fonts")
            page_content="${page_content//\{\{PART_NUMBER\}\}/$part_num}"
            page_content="${page_content//\{\{PART_TITLE\}\}/$page_title}"
            page_content="${page_content//\{\{PREV_LINK\}\}/$prev_link}"
            page_content="${page_content//\{\{NEXT_LINK\}\}/$next_link}"

            echo "$page_content" > "${output_dir}/chapters/${page_slug}.html"

        elif [[ "$page_type" == "chapter" ]]; then
            # --- Chapter page ---
            local ch_num="${page_slug#chapter-}"
            ch_num=$((10#$ch_num))  # remove leading zero
            local ch_num_fmt
            ch_num_fmt=$(printf '%02d' "$ch_num")
            local ch_md="${chapters_dir}/chapter-${ch_num_fmt}.md"

            if [[ ! -f "$ch_md" ]]; then
                log "WARNING: Chapter file missing: ${ch_md}"
                continue
            fi

            local ch_html_fragment
            ch_html_fragment=$(pandoc --from markdown --to html5 "$ch_md" 2>/dev/null)

            # Part label
            local part_label_html=""
            local ch_part_title
            ch_part_title=$(get_chapter_part_title "$ch_num" "$project_dir")
            if [[ -n "$ch_part_title" ]]; then
                local ch_part_num
                ch_part_num=$(read_chapter_field "$ch_num" "$project_dir" "part" 2>/dev/null || echo "")
                part_label_html="<div class=\"part-label\">Part ${ch_part_num}: ${ch_part_title}</div>"
            fi

            local page_content
            page_content=$(_web_sub "$ch_tmpl" "../fonts")
            page_content="${page_content//\{\{CHAPTER_TITLE\}\}/$page_title}"
            page_content="${page_content//\{\{CHAPTER_SLUG\}\}/$page_slug}"
            page_content="${page_content//\{\{CHAPTER_NUM\}\}/$ch_num}"
            page_content="${page_content//\{\{CHAPTER_CONTENT\}\}/$ch_html_fragment}"
            page_content="${page_content//\{\{PREV_LINK\}\}/$prev_link}"
            page_content="${page_content//\{\{NEXT_LINK\}\}/$next_link}"
            page_content="${page_content//\{\{PART_LABEL\}\}/$part_label_html}"

            echo "$page_content" > "${output_dir}/chapters/${page_slug}.html"
        fi
    done
```

- [ ] **Step 11: Update summary log**

```bash
    local total_files=$(( nav_total + 2 ))  # nav chain pages + index + contents
    log "Web book generated: ${total_files} pages at ${output_dir}/"
    log "  Landing: ${output_dir}/index.html"
    log "  Contents: ${output_dir}/contents.html"
    log "  Chapters: ${output_dir}/chapters/ (${total_chapters} chapters, ${total_parts} parts)"
```

- [ ] **Step 12: Commit and push**

```bash
git add scripts/lib/assembly.sh
git commit -m "Rewrite generate_web_book: parts, nav chain, fonts, resume, grouped TOC"
git push
```

---

## Chunk 4: Integration Test with Thornwall

### Task 12: Generate and verify web book for Thornwall

**Files:** None modified — this is a manual verification task.

- [ ] **Step 1: Generate web book for Thornwall using dev plugin**

```bash
cd /Users/bennorris/Developer/rend
CLAUDE_PLUGIN_ROOT=/Users/bennorris/Developer/storyforge ./storyforge assemble --format web
```

If the branch/PR creation is problematic, call the function directly:
```bash
cd /Users/bennorris/Developer/rend
source /Users/bennorris/Developer/storyforge/scripts/lib/common.sh
source /Users/bennorris/Developer/storyforge/scripts/lib/assembly.sh
generate_web_book "/Users/bennorris/Developer/rend" "/Users/bennorris/Developer/storyforge"
```

- [ ] **Step 2: Verify file structure**

```bash
find /Users/bennorris/Developer/rend/manuscript/output/web -type f | sort
```

Expected: `index.html`, `contents.html`, `cover.png`, `fonts/*.woff2`, `chapters/part-01.html` through `part-04.html`, `chapters/chapter-01.html` through `chapter-29.html` (33 chapter-dir files + 3 top-level + fonts)

- [ ] **Step 3: Open in browser and verify**

Open `manuscript/output/web/index.html` in a browser. Check:
- Landing page renders with cover, title, author, logline
- "Start Reading" links to `chapters/part-01.html`
- Part One interstitial shows "Part 1 / The Wick" centered
- Chapter 1 shows part label "Part 1: The Wick" above chapter heading
- Navigation flows: Part 1 → Ch 1 → Ch 2 → ... → Ch 8 → Part 2 → Ch 9 → ...
- Theme toggle cycles through light/dark/sepia
- Dark theme has atmospheric feel (darker background, accent line)
- TOC overlay shows part groupings with current chapter highlighted
- Literata font loads (compare to Georgia fallback — Literata has distinctive serifs)
- Resume: read a chapter, go back to index, see "Continue Reading" link

- [ ] **Step 4: Fix any issues found during verification**

Iterate on the templates, CSS, JS, or assembly function as needed.

- [ ] **Step 5: Commit any fixes**

```bash
cd /Users/bennorris/Developer/storyforge
git add -A && git commit -m "Web book: fixes from Thornwall integration test" && git push
```

### Task 13: Test no-parts fallback with test fixture

- [ ] **Step 1: Create a temporary no-parts test project**

```bash
NOPARTS_DIR=$(mktemp -d)
mkdir -p "${NOPARTS_DIR}/reference" "${NOPARTS_DIR}/manuscript/chapters" "${NOPARTS_DIR}/scenes"

# Chapter map with no parts
cat > "${NOPARTS_DIR}/reference/chapter-map.yaml" << 'YAML'
chapters:
  - title: "First Chapter"
    heading: numbered-titled
    scenes:
      - s01
  - title: "Second Chapter"
    heading: numbered-titled
    scenes:
      - s02

production:
  author: "Test Author"
  language: en
  scene_break: ornamental
  default_heading: numbered-titled
  include_toc: true
YAML

# Minimal storyforge.yaml
cat > "${NOPARTS_DIR}/storyforge.yaml" << 'YAML'
project:
  title: "No Parts Test"
  genre: "fantasy"
  target_words: 10000
  logline: "A test book."
phase: production
YAML

# Minimal chapter markdown files
echo "# Chapter 1: First Chapter\n\nSome prose." > "${NOPARTS_DIR}/manuscript/chapters/chapter-01.md"
echo "# Chapter 2: Second Chapter\n\nMore prose." > "${NOPARTS_DIR}/manuscript/chapters/chapter-02.md"
```

- [ ] **Step 2: Generate web book for the no-parts project**

```bash
cd "${NOPARTS_DIR}"
source /Users/bennorris/Developer/storyforge/scripts/lib/common.sh
source /Users/bennorris/Developer/storyforge/scripts/lib/assembly.sh
generate_web_book "${NOPARTS_DIR}" "/Users/bennorris/Developer/storyforge"
```

- [ ] **Step 3: Verify no-parts output**

```bash
# Should have NO part-*.html files
ls "${NOPARTS_DIR}/manuscript/output/web/chapters/"
# Expected: chapter-01.html chapter-02.html (no part files)

# Contents page should have flat list (no toc-part headings)
grep "toc-part" "${NOPARTS_DIR}/manuscript/output/web/contents.html"
# Expected: no matches

# Chapter pages should have no part label
grep "part-label" "${NOPARTS_DIR}/manuscript/output/web/chapters/chapter-01.html"
# Expected: no matches (or empty div)

# Navigation should go chapter-to-chapter
grep "chapter-02" "${NOPARTS_DIR}/manuscript/output/web/chapters/chapter-01.html"
# Expected: match (next link points to chapter-02)
```

- [ ] **Step 4: Clean up**

```bash
rm -rf "${NOPARTS_DIR}"
```

- [ ] **Step 5: Fix any issues and commit if needed**

### Task 14: Bump version and final commit

- [ ] **Step 1: Bump patch version**

Update `"version"` in `.claude-plugin/plugin.json` to the next patch version.

- [ ] **Step 2: Commit and push**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version for web book format"
git push
```
