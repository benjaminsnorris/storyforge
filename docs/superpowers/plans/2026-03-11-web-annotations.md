# Web Annotation System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a client-side annotation overlay to Storyforge web books that lets authors highlight, comment, and add margin notes while reading, then export annotations as JSON/markdown files that feed into the revision pipeline.

**Architecture:** A separate `annotations.js` + `annotations.css` overlay injected into web book output via `--annotate` flag. Scene boundaries are preserved through HTML comment markers in assembled chapter markdown, post-processed into `<section data-scene>` wrappers. Annotations stored in localStorage per-chapter, exported as downloadable files. A new `storyforge:annotate` skill imports exports and generates revision plans.

**Tech Stack:** Vanilla JS, CSS (no dependencies). Bash for build integration. Storyforge skill (SKILL.md markdown) for import.

**Spec:** `docs/superpowers/specs/2026-03-11-web-annotations-design.md`

---

## Chunk 1: Scene Boundary Markers & Build Integration

### Task 1: Inject scene ID markers into assembled chapter markdown

The `assemble_chapter()` function in `assembly.sh` concatenates scene prose but discards scene IDs. We need to inject HTML comment markers so scene boundaries survive pandoc conversion.

**Files:**
- Modify: `scripts/lib/assembly.sh:254-279` (scene concatenation loop in `assemble_chapter()`)
- Test: `tests/test-assembly.sh`

- [ ] **Step 1: Write failing test for scene markers in assembled output**

Add to `tests/test-assembly.sh` after the existing `assemble_chapter` tests (around line 120):

```bash
# ============================================================================
# assemble_chapter — scene markers
# ============================================================================

result=$(assemble_chapter 1 "$PROJECT_DIR" "ornamental")
assert_contains "$result" "<!-- scene:act1-sc01 -->" "assemble_chapter: includes scene marker for first scene"
assert_contains "$result" "<!-- scene:act1-sc02 -->" "assemble_chapter: includes scene marker for second scene"

result=$(assemble_chapter 2 "$PROJECT_DIR" "ornamental")
assert_contains "$result" "<!-- scene:act2-sc01 -->" "assemble_chapter: includes scene marker for single scene"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tests/run-tests.sh tests/test-assembly.sh`
Expected: 3 new FAILs — scene markers not found in output.

- [ ] **Step 3: Add scene markers to assemble_chapter()**

In `scripts/lib/assembly.sh`, modify the scene concatenation loop (lines 259-278). Add an HTML comment before each scene's prose:

```bash
    while IFS= read -r scene_id; do
        [[ -z "$scene_id" ]] && continue

        local scene_file="${project_dir}/scenes/${scene_id}.md"
        if [[ ! -f "$scene_file" ]]; then
            log "WARNING: Scene file not found: ${scene_file}"
            continue
        fi

        if [[ "$first" == true ]]; then
            first=false
        else
            # Scene break between scenes
            echo ""
            echo "$break_marker"
            echo ""
        fi

        # Scene boundary marker (preserved through pandoc as HTML comment)
        echo "<!-- scene:${scene_id} -->"
        echo ""
        extract_scene_prose "$scene_file"
    done <<< "$scene_ids"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tests/run-tests.sh tests/test-assembly.sh`
Expected: All tests PASS, including the 3 new scene marker assertions.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/assembly.sh tests/test-assembly.sh
git commit -m "Add scene boundary markers to assembled chapter markdown"
git push
```

---

### Task 2: Add `--annotate` flag to storyforge-assemble

**Files:**
- Modify: `scripts/storyforge-assemble:102-137` (flag parsing block)
- Test: `tests/test-dry-run.sh` (or inline verification)

- [ ] **Step 1: Write failing test for --annotate flag**

Add to `tests/test-dry-run.sh` (which tests CLI flags):

```bash
# ============================================================================
# --annotate flag
# ============================================================================

result=$(cd "$PROJECT_DIR" && "${PLUGIN_DIR}/scripts/storyforge-assemble" --dry-run --annotate --format web 2>&1)
assert_contains "$result" "annotate" "storyforge-assemble: --annotate flag recognized in dry-run"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-dry-run.sh`
Expected: FAIL — flag not recognized.

- [ ] **Step 3: Add --annotate flag parsing**

In `scripts/storyforge-assemble`, add to the flag parsing block (after `--skip-validation`, around line 122):

```bash
        --annotate)
            ANNOTATE=true
            shift
            ;;
```

And initialize the variable near the other defaults (around line 66, after `INTERACTIVE=false`):

```bash
ANNOTATE=false
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-dry-run.sh`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/storyforge-assemble tests/test-dry-run.sh
git commit -m "Add --annotate flag to storyforge-assemble"
git push
```

---

### Task 3: Post-process scene markers into `<section>` wrappers in generate_web_book()

When `--annotate` is active, convert `<!-- scene:ID -->` comments in the pandoc HTML output into `<section data-scene="ID">` wrappers.

**Files:**
- Modify: `scripts/lib/assembly.sh:1278-1324` (chapter HTML generation in `generate_web_book()`)
- Modify: `scripts/storyforge-assemble` (pass ANNOTATE to generate_web_book)
- Test: `tests/test-assembly.sh`

- [ ] **Step 1: Write a helper function for scene section wrapping**

Add a new function `_wrap_scene_sections()` to `scripts/lib/assembly.sh` as a top-level function before `generate_web_book()` (around line 905, before the function header comment). Note: the `_web_stamp` and `_web_cleanup` helpers are nested inside `generate_web_book()`, but this function should be standalone since it's also used in tests:

```bash
# _wrap_scene_sections — convert scene HTML comments into <section> wrappers
# Input: HTML on stdin containing <!-- scene:ID --> comments
# Output: HTML with scene comments replaced by <section data-scene="ID"> wrappers
_wrap_scene_sections() {
    awk '
    BEGIN { open = 0 }
    /^<!-- scene:/ {
        if (open) print "</section>"
        # Extract scene ID from <!-- scene:SCENE_ID -->
        gsub(/<!-- scene:/, "")
        gsub(/ -->/, "")
        printf "<section data-scene=\"%s\">\n", $0
        open = 1
        next
    }
    { print }
    END { if (open) print "</section>" }
    '
}
```

- [ ] **Step 2: Write failing test for scene section wrapping**

Add to `tests/test-assembly.sh`:

```bash
# ============================================================================
# _wrap_scene_sections
# ============================================================================

input='<!-- scene:act1-sc01 -->
<p>First scene prose.</p>
<!-- scene:act1-sc02 -->
<p>Second scene prose.</p>'

result=$(echo "$input" | _wrap_scene_sections)
assert_contains "$result" '<section data-scene="act1-sc01">' "_wrap_scene_sections: wraps first scene"
assert_contains "$result" '<section data-scene="act1-sc02">' "_wrap_scene_sections: wraps second scene"
assert_contains "$result" '</section>' "_wrap_scene_sections: closes sections"
assert_not_contains "$result" '<!-- scene:' "_wrap_scene_sections: removes comment markers"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-assembly.sh`
Expected: FAIL — function not found.

- [ ] **Step 4: Implement and run tests**

Add the `_wrap_scene_sections` function from Step 1 to `assembly.sh`. Run tests:

Run: `./tests/run-tests.sh tests/test-assembly.sh`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/assembly.sh tests/test-assembly.sh
git commit -m "Add _wrap_scene_sections helper for annotation scene wrapping"
git push
```

- [ ] **Step 6: Wire up scene wrapping in generate_web_book()**

In `scripts/lib/assembly.sh`, modify the chapter HTML generation block (around line 1293). When annotation mode is active, pipe pandoc output through `_wrap_scene_sections`:

The `generate_web_book()` function needs to accept an annotate parameter. Modify its signature and the caller in `storyforge-assemble`.

In `storyforge-assemble`, where `generate_web_book` is called (line 383), pass the ANNOTATE flag. The `all` format branch delegates through `generate_format "web"` which hits the same call site, so only one change is needed:

```bash
generate_web_book "$PROJECT_DIR" "$PLUGIN_DIR" "$ANNOTATE"
```

In `assembly.sh` `generate_web_book()`, add at the start (after line 910):

```bash
    local annotate="${3:-false}"
```

Then modify the pandoc conversion (around line 1293):

```bash
            if [[ "$annotate" == "true" ]]; then
                pandoc --from markdown --to html5 "$ch_md" 2>/dev/null | _wrap_scene_sections > "$ch_html_file"
            else
                pandoc --from markdown --to html5 "$ch_md" > "$ch_html_file" 2>/dev/null
            fi
```

- [ ] **Step 7: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All PASS. No regressions.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/assembly.sh scripts/storyforge-assemble
git commit -m "Wire scene section wrapping into web book generation"
git push
```

---

### Task 4: Inject annotation JS/CSS into chapter template when --annotate is active

**Files:**
- Modify: `scripts/lib/assembly.sh:1306-1321` (chapter template stamping in `generate_web_book()`)
- Create: `templates/production/web-book/annotations.css` (placeholder — will be filled in Chunk 2)
- Create: `templates/production/web-book/annotations.js` (placeholder — will be filled in Chunk 2)

- [ ] **Step 1: Create placeholder annotation files**

Create `templates/production/web-book/annotations.css`:

```css
/* Storyforge Annotation Overlay — styles loaded when --annotate is active */
```

Create `templates/production/web-book/annotations.js`:

```js
// Storyforge Annotation Overlay — loaded when --annotate is active
(function() {
  'use strict';
  console.log('[Storyforge Annotations] Overlay loaded');
})();
```

- [ ] **Step 2: Inject annotation assets in generate_web_book()**

In the `generate_web_book()` function, alongside where CSS and JS are cached (around lines 971-975), add conditional loading of annotation assets:

```bash
    local ann_css_content=""
    local ann_js_content=""
    if [[ "$annotate" == "true" ]]; then
        local ann_css_file="${template_dir}/annotations.css"
        local ann_js_file="${template_dir}/annotations.js"
        if [[ -f "$ann_css_file" ]]; then
            ann_css_content=$(<"$ann_css_file")
        fi
        if [[ -f "$ann_js_file" ]]; then
            ann_js_content=$(<"$ann_js_file")
        fi
    fi
```

Then in the template stamping for chapters (around line 1310-1311), when writing `{{CHAPTER_CONTENT}}`, also append annotation CSS/JS. The cleanest approach: append annotation CSS after the main CSS in the `<style>` block, and annotation JS after the main JS in the `<script>` block.

Modify the `_web_stamp` helper or the chapter generation loop to append annotation assets. The simplest approach: after writing the chapter HTML file, use sed to inject the annotation CSS before `</style>` and annotation JS before `</script>`:

```bash
            if [[ "$annotate" == "true" && -n "$ann_css_content" ]]; then
                # Write annotation CSS and JS to temp files for injection
                local ann_css_tmp ann_js_tmp
                ann_css_tmp=$(mktemp "${TMPDIR:-/tmp}/sf-ann-css.XXXXXX")
                ann_js_tmp=$(mktemp "${TMPDIR:-/tmp}/sf-ann-js.XXXXXX")
                printf '%s\n' "$ann_css_content" > "$ann_css_tmp"
                printf '%s\n' "$ann_js_content" > "$ann_js_tmp"

                local ch_out="${output_dir}/chapters/${page_slug}.html"
                # Inject annotation CSS BEFORE </style> (BSD sed 'r' inserts after, so use awk)
                awk -v file="$ann_css_tmp" '
                    /<\/style>/ { while ((getline line < file) > 0) print line; close(file) }
                    { print }
                ' "$ch_out" > "${ch_out}.tmp" && mv "${ch_out}.tmp" "$ch_out"
                # Inject annotation JS BEFORE </script>
                awk -v file="$ann_js_tmp" '
                    /<\/script>/ && !done { while ((getline line < file) > 0) print line; close(file); done=1 }
                    { print }
                ' "$ch_out" > "${ch_out}.tmp" && mv "${ch_out}.tmp" "$ch_out"

                rm -f "$ann_css_tmp" "$ann_js_tmp"
            fi
```

Also, when `--annotate` is active, inject a `data-book` attribute on the `<body>` tag so the JS can build a book-specific localStorage key. In the chapter template stamping loop (around line 1314), add after the `CHAPTER_SLUG` substitution:

```bash
                        if [[ "$annotate" == "true" ]]; then
                            _line="${_line//data-chapter=/data-book=\"${book_slug}\" data-chapter=}"
                        fi
```

Where `book_slug` is derived from the book title earlier in `generate_web_book()`:

```bash
    local book_slug
    book_slug=$(echo "$title" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')
```

- [ ] **Step 3: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All PASS. No regressions.

- [ ] **Step 4: Commit**

```bash
git add templates/production/web-book/annotations.css templates/production/web-book/annotations.js scripts/lib/assembly.sh
git commit -m "Inject annotation overlay assets into web book when --annotate is active"
git push
```

---

## Chunk 2: Annotation CSS

### Task 5: Annotation styles — highlights, popovers, toolbar, margin notes

All styles must be theme-aware (light/dark/sepia), mobile-responsive, and non-conflicting with `reading.css`.

**Files:**
- Create (overwrite placeholder): `templates/production/web-book/annotations.css`

**Reference:** `templates/production/web-book/reading.css` for theme variable names (`--bg`, `--text`, `--text-dim`, `--accent`, `--surface`, `--border`), breakpoints (639px mobile, 640-1024px tablet), and class naming conventions.

- [ ] **Step 1: Write highlight styles**

```css
/* ============================================================================
   Annotation Overlay Styles
   Theme-aware: uses CSS variables from reading.css
   ============================================================================ */

/* --- Highlights --- */
.sf-highlight {
  background-color: rgba(255, 220, 80, 0.35);
  border-radius: 2px;
  cursor: pointer;
  position: relative;
  transition: background-color 0.2s;
}
.sf-highlight:hover {
  background-color: rgba(255, 220, 80, 0.55);
}
.sf-highlight.has-comment::after {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  background: var(--accent);
  border-radius: 50%;
  margin-left: 2px;
  vertical-align: super;
}

/* Dark theme highlights */
[data-theme="dark"] .sf-highlight {
  background-color: rgba(255, 200, 60, 0.2);
}
[data-theme="dark"] .sf-highlight:hover {
  background-color: rgba(255, 200, 60, 0.35);
}

/* Sepia theme highlights */
[data-theme="sepia"] .sf-highlight {
  background-color: rgba(200, 160, 60, 0.25);
}
[data-theme="sepia"] .sf-highlight:hover {
  background-color: rgba(200, 160, 60, 0.4);
}
```

- [ ] **Step 2: Write popover styles (desktop)**

```css
/* --- Popover (desktop text selection) --- */
.sf-popover {
  position: absolute;
  z-index: 100;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px;
  display: flex;
  gap: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  animation: sf-fade-in 0.15s ease;
}
.sf-popover button {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 10px;
  font-size: 0.85rem;
  cursor: pointer;
  white-space: nowrap;
}
.sf-popover button:hover {
  background: var(--accent);
  color: var(--bg);
}

/* --- Comment input (expands from popover) --- */
.sf-comment-input {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 240px;
}
.sf-comment-input textarea {
  font-family: inherit;
  font-size: 0.85rem;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
  color: var(--text);
  resize: vertical;
  min-height: 60px;
}
.sf-comment-input .sf-actions {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
}

@keyframes sf-fade-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
```

- [ ] **Step 3: Write mobile toolbar styles**

```css
/* --- Mobile bottom toolbar --- */
.sf-toolbar {
  display: none;
}

@media (max-width: 639px) {
  .sf-popover {
    display: none !important;
  }
  .sf-toolbar {
    display: flex;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 100;
    background: var(--surface);
    border-top: 1px solid var(--border);
    padding: 8px 12px;
    padding-bottom: max(8px, env(safe-area-inset-bottom));
    gap: 8px;
    align-items: center;
    justify-content: center;
  }
  .sf-toolbar button {
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 14px;
    font-size: 0.9rem;
    cursor: pointer;
    min-height: 44px;
  }
  .sf-toolbar button:active {
    background: var(--accent);
    color: var(--bg);
  }
  .sf-toolbar button.sf-hidden {
    display: none;
  }
  /* Add bottom padding to reading column so toolbar doesn't cover text */
  .reading-column {
    padding-bottom: 70px;
  }
}
```

- [ ] **Step 4: Write margin note styles**

```css
/* --- Margin notes --- */
.sf-margin-trigger {
  position: absolute;
  left: -32px;
  width: 24px;
  height: 24px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  color: var(--text-dim);
  opacity: 0;
  transition: opacity 0.2s;
}
/* Desktop: show on paragraph hover */
@media (min-width: 640px) {
  [data-scene] > *:hover > .sf-margin-trigger,
  .sf-margin-trigger:hover {
    opacity: 1;
  }
}

.sf-margin-indicator {
  position: absolute;
  left: -28px;
  width: 18px;
  height: 18px;
  background: var(--accent);
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.6rem;
  color: var(--bg);
}

/* Margin note panel */
.sf-note-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
  margin: 8px 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  animation: sf-fade-in 0.15s ease;
}
.sf-note-panel textarea {
  width: 100%;
  font-family: inherit;
  font-size: 0.85rem;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
  color: var(--text);
  resize: vertical;
  min-height: 60px;
  box-sizing: border-box;
}

/* Annotation count badge in nav */
.sf-badge {
  background: var(--accent);
  color: var(--bg);
  font-size: 0.65rem;
  padding: 1px 5px;
  border-radius: 8px;
  margin-left: 6px;
}
```

- [ ] **Step 5: Write comment viewer styles**

```css
/* --- Comment viewer (tap on highlight) --- */
.sf-comment-viewer {
  position: absolute;
  z-index: 101;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
  max-width: 300px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  animation: sf-fade-in 0.15s ease;
}
.sf-comment-viewer p {
  margin: 0 0 8px;
  font-size: 0.85rem;
  color: var(--text);
}
.sf-comment-viewer .sf-actions {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
}
.sf-comment-viewer button {
  background: var(--surface);
  color: var(--text-dim);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 0.8rem;
  cursor: pointer;
}
.sf-comment-viewer button.sf-delete {
  color: #c0392b;
  border-color: #c0392b;
}

/* --- Stale annotations panel --- */
.sf-stale-panel {
  margin-top: 3rem;
  padding: 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  border-left: 3px solid #e67e22;
}
.sf-stale-panel h3 {
  margin: 0 0 12px;
  font-size: 0.9rem;
  color: var(--text-dim);
}
.sf-stale-panel details {
  margin-bottom: 8px;
}
.sf-stale-panel summary {
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--text);
}
.sf-stale-panel blockquote {
  margin: 4px 0 4px 12px;
  padding-left: 8px;
  border-left: 2px solid var(--border);
  font-style: italic;
  font-size: 0.8rem;
  color: var(--text-dim);
}
.sf-stale-panel button {
  background: var(--surface);
  color: var(--text-dim);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 0.75rem;
  cursor: pointer;
  margin-top: 4px;
}

/* --- Print: hide all annotation UI --- */
@media print {
  .sf-highlight { background: none !important; }
  .sf-highlight.has-comment::after { display: none; }
  .sf-popover, .sf-toolbar, .sf-margin-trigger,
  .sf-margin-indicator, .sf-note-panel, .sf-comment-viewer,
  .sf-badge, .sf-stale-panel { display: none !important; }
}

/* --- Reduced motion --- */
@media (prefers-reduced-motion: reduce) {
  .sf-popover, .sf-note-panel, .sf-comment-viewer {
    animation: none;
  }
}
```

- [ ] **Step 6: Assemble all CSS into annotations.css**

Combine all sections from Steps 1-5 into `templates/production/web-book/annotations.css` as a single file.

- [ ] **Step 7: Commit**

```bash
git add templates/production/web-book/annotations.css
git commit -m "Add annotation overlay CSS with theme-aware highlights, popovers, toolbar"
git push
```

---

## Chunk 3: Annotation JS — Core Logic

### Task 6: Annotation data model and localStorage persistence

**Files:**
- Create (overwrite placeholder): `templates/production/web-book/annotations.js`

Build the JS incrementally. This task covers: UUID generation, data model, localStorage read/write, per-chapter keying.

- [ ] **Step 1: Write the IIFE shell and data model**

```js
// Storyforge Annotation Overlay
(function() {
  'use strict';

  // --- Config ---
  var bookSlug = document.body.dataset.book || 'unknown';
  var chapterSlug = document.body.dataset.chapter || 'unknown';
  var STORAGE_PREFIX = 'storyforge-annotations-' + bookSlug + '-';

  // --- UUID ---
  function uuid() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      var r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });
  }

  // --- Storage ---
  function storageKey() {
    return STORAGE_PREFIX + chapterSlug;
  }

  function loadAnnotations() {
    try {
      var data = localStorage.getItem(storageKey());
      return data ? JSON.parse(data) : [];
    } catch (e) {
      return [];
    }
  }

  function saveAnnotations(annotations) {
    try {
      localStorage.setItem(storageKey(), JSON.stringify(annotations));
    } catch (e) {
      console.warn('[Annotations] Storage full or unavailable');
    }
  }

  function addAnnotation(annotation) {
    var annotations = loadAnnotations();
    annotations.push(annotation);
    saveAnnotations(annotations);
    return annotation;
  }

  function updateAnnotation(id, updates) {
    var annotations = loadAnnotations();
    for (var i = 0; i < annotations.length; i++) {
      if (annotations[i].id === id) {
        for (var key in updates) {
          annotations[i][key] = updates[key];
        }
        break;
      }
    }
    saveAnnotations(annotations);
  }

  function deleteAnnotation(id) {
    var annotations = loadAnnotations();
    saveAnnotations(annotations.filter(function(a) { return a.id !== id; }));
  }
```

- [ ] **Step 2: Commit partial JS (data model + storage)**

```bash
git add templates/production/web-book/annotations.js
git commit -m "Add annotation data model and localStorage persistence"
git push
```

---

### Task 7: Text selection and highlight creation

**Files:**
- Modify: `templates/production/web-book/annotations.js`

- [ ] **Step 1: Add DOM helper functions**

Append to annotations.js inside the IIFE:

```js
  // --- DOM Helpers ---
  function getSceneForNode(node) {
    var el = node.nodeType === 3 ? node.parentElement : node;
    var section = el.closest('[data-scene]');
    return section ? section.dataset.scene : null;
  }

  function getParagraphIndex(node, scene) {
    var el = node.nodeType === 3 ? node.parentElement : node;
    var section = el.closest('[data-scene]');
    if (!section) return 0;
    var blocks = section.querySelectorAll('p, blockquote, ul, ol, h1, h2, h3, h4, h5, h6');
    var block = el.closest('p, blockquote, ul, ol, h1, h2, h3, h4, h5, h6');
    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i] === block) return i;
    }
    return 0;
  }

  function getBlockByIndex(scene, index) {
    var section = document.querySelector('[data-scene="' + scene + '"]');
    if (!section) return null;
    var blocks = section.querySelectorAll('p, blockquote, ul, ol, h1, h2, h3, h4, h5, h6');
    return blocks[index] || null;
  }
```

- [ ] **Step 2: Add highlight rendering**

```js
  // --- Highlight Rendering ---
  function renderHighlight(annotation) {
    if (annotation.type === 'margin-note') return;
    var anchor = annotation.anchor;
    if (!anchor) return;

    var block = getBlockByIndex(anchor.scene || annotation.scene, anchor.paragraphIndex);
    if (!block) return;

    // Walk text nodes to find the offset range
    var walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
    var charCount = 0;
    var startNode = null, startOff = 0, endNode = null, endOff = 0;

    while (walker.nextNode()) {
      var node = walker.currentNode;
      var nodeLen = node.textContent.length;
      if (!startNode && charCount + nodeLen > anchor.startOffset) {
        startNode = node;
        startOff = anchor.startOffset - charCount;
      }
      if (!endNode && charCount + nodeLen >= anchor.endOffset) {
        endNode = node;
        endOff = anchor.endOffset - charCount;
        break;
      }
      charCount += nodeLen;
    }

    if (!startNode || !endNode) return;

    try {
      var range = document.createRange();
      range.setStart(startNode, startOff);
      range.setEnd(endNode, endOff);

      var span = document.createElement('span');
      span.className = 'sf-highlight' + (annotation.comment ? ' has-comment' : '');
      span.dataset.annotationId = annotation.id;
      range.surroundContents(span);
    } catch (e) {
      // Range may cross element boundaries — skip gracefully
    }
  }

  function renderAllHighlights() {
    var annotations = loadAnnotations();
    annotations.forEach(function(a) {
      if (a.type !== 'margin-note') renderHighlight(a);
    });
  }
```

- [ ] **Step 3: Commit**

```bash
git add templates/production/web-book/annotations.js
git commit -m "Add text selection helpers and highlight rendering"
git push
```

---

### Task 8: Desktop popover for text selection

**Files:**
- Modify: `templates/production/web-book/annotations.js`

- [ ] **Step 1: Add popover creation and selection handler**

```js
  // --- Popover ---
  var activePopover = null;

  function removePopover() {
    if (activePopover) {
      activePopover.remove();
      activePopover = null;
    }
  }

  function showPopover(x, y, range) {
    removePopover();
    var div = document.createElement('div');
    div.className = 'sf-popover';

    var highlightBtn = document.createElement('button');
    highlightBtn.textContent = 'Highlight';
    highlightBtn.onclick = function() {
      createHighlightFromRange(range, null);
      removePopover();
    };

    var commentBtn = document.createElement('button');
    commentBtn.textContent = 'Comment';
    commentBtn.onclick = function() {
      showCommentInput(div, range);
    };

    div.appendChild(highlightBtn);
    div.appendChild(commentBtn);
    document.body.appendChild(div);

    // Position near selection
    div.style.left = Math.min(x, window.innerWidth - div.offsetWidth - 10) + 'px';
    div.style.top = (y - div.offsetHeight - 8) + 'px';
    activePopover = div;
  }

  function showCommentInput(popover, range) {
    popover.innerHTML = '';
    var container = document.createElement('div');
    container.className = 'sf-comment-input';

    var textarea = document.createElement('textarea');
    textarea.placeholder = 'Add a note...';
    textarea.rows = 3;

    var actions = document.createElement('div');
    actions.className = 'sf-actions';

    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.onclick = removePopover;

    var saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save';
    saveBtn.onclick = function() {
      createHighlightFromRange(range, textarea.value || null);
      removePopover();
    };

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    container.appendChild(textarea);
    container.appendChild(actions);
    popover.appendChild(container);
    textarea.focus();
  }

  function createHighlightFromRange(range, comment) {
    var scene = getSceneForNode(range.startContainer);
    var pIndex = getParagraphIndex(range.startContainer, scene);
    var block = range.startContainer.nodeType === 3
      ? range.startContainer.parentElement.closest('p, blockquote, ul, ol, h1, h2, h3, h4, h5, h6')
      : range.startContainer.closest('p, blockquote, ul, ol, h1, h2, h3, h4, h5, h6');

    // Calculate offsets relative to block text content
    var walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
    var charCount = 0;
    var startOffset = 0, endOffset = 0;
    while (walker.nextNode()) {
      var node = walker.currentNode;
      if (node === range.startContainer) startOffset = charCount + range.startOffset;
      if (node === range.endContainer) { endOffset = charCount + range.endOffset; break; }
      charCount += node.textContent.length;
    }

    var annotation = {
      id: uuid(),
      type: comment ? 'comment' : 'highlight',
      chapter: chapterSlug,
      scene: scene,
      anchor: {
        paragraphIndex: pIndex,
        startOffset: startOffset,
        endOffset: endOffset,
        selectedText: range.toString()
      },
      comment: comment,
      createdAt: new Date().toISOString()
    };

    addAnnotation(annotation);
    renderHighlight(annotation);
    updateBadge();
    window.getSelection().removeAllRanges();
  }

  // Desktop: listen for mouseup to show popover
  if (window.innerWidth >= 640) {
    document.addEventListener('mouseup', function(e) {
      var sel = window.getSelection();
      if (!sel.rangeCount || sel.isCollapsed) { removePopover(); return; }
      var range = sel.getRangeAt(0);
      // Only annotate within reading content
      if (!range.startContainer.parentElement.closest('.chapter-content')) return;
      var rect = range.getBoundingClientRect();
      showPopover(rect.left + window.scrollX, rect.top + window.scrollY, range.cloneRange());
    });

    document.addEventListener('mousedown', function(e) {
      if (activePopover && !activePopover.contains(e.target)) removePopover();
    });
  }
```

- [ ] **Step 2: Commit**

```bash
git add templates/production/web-book/annotations.js
git commit -m "Add desktop popover for text selection annotations"
git push
```

---

### Task 9: Mobile bottom toolbar

**Files:**
- Modify: `templates/production/web-book/annotations.js`

- [ ] **Step 1: Add mobile toolbar creation and selection handler**

```js
  // --- Mobile Toolbar ---
  var toolbar = null;
  var pendingRange = null;

  function createToolbar() {
    if (window.innerWidth >= 640) return;

    toolbar = document.createElement('div');
    toolbar.className = 'sf-toolbar';

    var highlightBtn = document.createElement('button');
    highlightBtn.textContent = 'Highlight';
    highlightBtn.className = 'sf-hidden';
    highlightBtn.dataset.action = 'highlight';
    highlightBtn.onclick = function() {
      if (pendingRange) {
        createHighlightFromRange(pendingRange, null);
        clearMobileSelection();
      }
    };

    var commentBtn = document.createElement('button');
    commentBtn.textContent = 'Comment';
    commentBtn.className = 'sf-hidden';
    commentBtn.dataset.action = 'comment';
    commentBtn.onclick = function() {
      if (pendingRange) showMobileCommentInput(pendingRange);
    };

    var marginBtn = document.createElement('button');
    marginBtn.textContent = '+ Note';
    marginBtn.dataset.action = 'margin';
    marginBtn.onclick = function() {
      showMobileMarginInput();
    };

    toolbar.appendChild(highlightBtn);
    toolbar.appendChild(commentBtn);
    toolbar.appendChild(marginBtn);
    document.body.appendChild(toolbar);

    // Listen for selection changes on mobile
    document.addEventListener('selectionchange', function() {
      var sel = window.getSelection();
      if (sel.rangeCount && !sel.isCollapsed) {
        var range = sel.getRangeAt(0);
        if (range.startContainer.parentElement.closest('.chapter-content')) {
          pendingRange = range.cloneRange();
          highlightBtn.classList.remove('sf-hidden');
          commentBtn.classList.remove('sf-hidden');
        }
      } else {
        // Delay hiding to allow button taps to register
        setTimeout(function() {
          if (!document.querySelector('.sf-comment-input')) {
            highlightBtn.classList.add('sf-hidden');
            commentBtn.classList.add('sf-hidden');
            pendingRange = null;
          }
        }, 200);
      }
    });
  }

  function clearMobileSelection() {
    window.getSelection().removeAllRanges();
    pendingRange = null;
    if (toolbar) {
      toolbar.querySelectorAll('[data-action="highlight"], [data-action="comment"]')
        .forEach(function(btn) { btn.classList.add('sf-hidden'); });
    }
  }

  function showMobileCommentInput(range) {
    // Replace toolbar with comment input
    toolbar.innerHTML = '';
    var container = document.createElement('div');
    container.className = 'sf-comment-input';
    container.style.width = '100%';

    var textarea = document.createElement('textarea');
    textarea.placeholder = 'Add a note...';
    textarea.rows = 2;

    var actions = document.createElement('div');
    actions.className = 'sf-actions';

    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.onclick = function() { rebuildToolbar(); clearMobileSelection(); };

    var saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save';
    saveBtn.onclick = function() {
      createHighlightFromRange(range, textarea.value || null);
      rebuildToolbar();
      clearMobileSelection();
    };

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    container.appendChild(textarea);
    container.appendChild(actions);
    toolbar.appendChild(container);
    textarea.focus();
  }

  function rebuildToolbar() {
    if (toolbar) toolbar.remove();
    toolbar = null;
    createToolbar();
  }
```

- [ ] **Step 2: Commit**

```bash
git add templates/production/web-book/annotations.js
git commit -m "Add mobile bottom toolbar for annotations"
git push
```

---

### Task 10: Margin notes

**Files:**
- Modify: `templates/production/web-book/annotations.js`

- [ ] **Step 1: Add margin note logic (desktop hover triggers + creation)**

```js
  // --- Margin Notes ---
  function setupMarginTriggers() {
    var sections = document.querySelectorAll('[data-scene]');
    sections.forEach(function(section) {
      var blocks = section.querySelectorAll('p, blockquote, ul, ol');
      blocks.forEach(function(block, index) {
        block.style.position = 'relative';

        // Desktop: hover trigger
        if (window.innerWidth >= 640) {
          var trigger = document.createElement('button');
          trigger.className = 'sf-margin-trigger';
          trigger.textContent = '+';
          trigger.setAttribute('aria-label', 'Add margin note');
          trigger.onclick = function(e) {
            e.stopPropagation();
            showMarginNoteInput(section.dataset.scene, index, block);
          };
          block.appendChild(trigger);
        }
      });
    });
  }

  function showMarginNoteInput(scene, paragraphIndex, block) {
    // Remove any existing note panel
    var existing = document.querySelector('.sf-note-panel');
    if (existing) existing.remove();

    var panel = document.createElement('div');
    panel.className = 'sf-note-panel';

    var textarea = document.createElement('textarea');
    textarea.placeholder = 'Add a margin note...';
    textarea.rows = 3;

    var actions = document.createElement('div');
    actions.className = 'sf-actions';
    actions.style.marginTop = '6px';
    actions.style.display = 'flex';
    actions.style.gap = '4px';
    actions.style.justifyContent = 'flex-end';

    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.style.cssText = 'background:var(--surface);color:var(--text-dim);border:1px solid var(--border);border-radius:4px;padding:3px 8px;font-size:0.8rem;cursor:pointer';
    cancelBtn.onclick = function() { panel.remove(); };

    var saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save';
    saveBtn.style.cssText = cancelBtn.style.cssText;
    saveBtn.onclick = function() {
      var text = textarea.value.trim();
      if (!text) { panel.remove(); return; }
      var annotation = {
        id: uuid(),
        type: 'margin-note',
        chapter: chapterSlug,
        scene: scene,
        anchor: { paragraphIndex: paragraphIndex, startOffset: 0, endOffset: 0, selectedText: '' },
        comment: text,
        createdAt: new Date().toISOString()
      };
      addAnnotation(annotation);
      panel.remove();
      renderMarginIndicator(annotation, block);
      updateBadge();
    };

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    panel.appendChild(textarea);
    panel.appendChild(actions);
    block.after(panel);
    textarea.focus();
  }

  function showMobileMarginInput() {
    // Find paragraph closest to viewport center
    var centerY = window.innerHeight / 2;
    var sections = document.querySelectorAll('[data-scene]');
    var bestBlock = null, bestScene = null, bestIndex = 0, bestDist = Infinity;

    sections.forEach(function(section) {
      var blocks = section.querySelectorAll('p, blockquote, ul, ol');
      blocks.forEach(function(block, index) {
        var rect = block.getBoundingClientRect();
        var blockCenter = rect.top + rect.height / 2;
        var dist = Math.abs(blockCenter - centerY);
        if (dist < bestDist) {
          bestDist = dist;
          bestBlock = block;
          bestScene = section.dataset.scene;
          bestIndex = index;
        }
      });
    });

    if (bestBlock && bestScene) {
      showMarginNoteInput(bestScene, bestIndex, bestBlock);
    }
  }

  function renderMarginIndicator(annotation, block) {
    if (!block) {
      block = getBlockByIndex(annotation.scene, annotation.anchor.paragraphIndex);
    }
    if (!block) return;
    block.style.position = 'relative';

    var indicator = document.createElement('span');
    indicator.className = 'sf-margin-indicator';
    indicator.textContent = '\u270E'; // pencil
    indicator.dataset.annotationId = annotation.id;
    indicator.onclick = function() {
      showCommentViewer(annotation, indicator);
    };
    block.appendChild(indicator);
  }

  function renderAllMarginNotes() {
    var annotations = loadAnnotations();
    annotations.forEach(function(a) {
      if (a.type === 'margin-note') renderMarginIndicator(a, null);
    });
  }
```

- [ ] **Step 2: Commit**

```bash
git add templates/production/web-book/annotations.js
git commit -m "Add margin note creation for desktop and mobile"
git push
```

---

### Task 11: Comment viewer (tap highlight to view/edit/delete) and badge

**Files:**
- Modify: `templates/production/web-book/annotations.js`

- [ ] **Step 1: Add comment viewer and highlight click handler**

```js
  // --- Comment Viewer ---
  var activeViewer = null;

  function removeViewer() {
    if (activeViewer) { activeViewer.remove(); activeViewer = null; }
  }

  function showCommentViewer(annotation, targetEl) {
    removeViewer();
    removePopover();

    var div = document.createElement('div');
    div.className = 'sf-comment-viewer';

    if (annotation.comment) {
      var p = document.createElement('p');
      p.textContent = annotation.comment;
      div.appendChild(p);
    }

    if (annotation.anchor && annotation.anchor.selectedText) {
      var quote = document.createElement('p');
      quote.style.fontStyle = 'italic';
      quote.style.color = 'var(--text-dim)';
      quote.textContent = '"' + annotation.anchor.selectedText.substring(0, 100) + (annotation.anchor.selectedText.length > 100 ? '...' : '') + '"';
      div.appendChild(quote);
    }

    var actions = document.createElement('div');
    actions.className = 'sf-actions';

    var editBtn = document.createElement('button');
    editBtn.textContent = 'Edit';
    editBtn.onclick = function() {
      removeViewer();
      showEditInput(annotation, targetEl);
    };

    var deleteBtn = document.createElement('button');
    deleteBtn.textContent = 'Delete';
    deleteBtn.className = 'sf-delete';
    deleteBtn.onclick = function() {
      deleteAnnotation(annotation.id);
      // Remove highlight span or margin indicator
      var el = document.querySelector('[data-annotation-id="' + annotation.id + '"]');
      if (el && el.classList.contains('sf-highlight')) {
        // Unwrap highlight span
        var parent = el.parentNode;
        while (el.firstChild) parent.insertBefore(el.firstChild, el);
        parent.removeChild(el);
      } else if (el) {
        el.remove();
      }
      removeViewer();
      updateBadge();
    };

    var closeBtn = document.createElement('button');
    closeBtn.textContent = 'Close';
    closeBtn.onclick = removeViewer;

    actions.appendChild(editBtn);
    actions.appendChild(deleteBtn);
    actions.appendChild(closeBtn);
    div.appendChild(actions);

    // Position near target
    var rect = targetEl.getBoundingClientRect();
    document.body.appendChild(div);
    div.style.left = Math.min(rect.left + window.scrollX, window.innerWidth - div.offsetWidth - 10) + 'px';
    div.style.top = (rect.bottom + window.scrollY + 4) + 'px';
    activeViewer = div;
  }

  function showEditInput(annotation, targetEl) {
    var div = document.createElement('div');
    div.className = 'sf-comment-viewer';

    var textarea = document.createElement('textarea');
    textarea.value = annotation.comment || '';
    textarea.rows = 3;
    textarea.style.cssText = 'width:100%;font-family:inherit;font-size:0.85rem;padding:6px 8px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--text);resize:vertical;min-height:60px;box-sizing:border-box';

    var actions = document.createElement('div');
    actions.className = 'sf-actions';
    actions.style.marginTop = '6px';

    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.onclick = function() { div.remove(); };

    var saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save';
    saveBtn.onclick = function() {
      var newComment = textarea.value.trim();
      updateAnnotation(annotation.id, {
        comment: newComment || null,
        type: newComment ? 'comment' : (annotation.type === 'margin-note' ? 'margin-note' : 'highlight')
      });
      var highlightEl = document.querySelector('.sf-highlight[data-annotation-id="' + annotation.id + '"]');
      if (highlightEl) {
        highlightEl.classList.toggle('has-comment', !!newComment);
      }
      div.remove();
    };

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    div.appendChild(textarea);
    div.appendChild(actions);

    var rect = targetEl.getBoundingClientRect();
    document.body.appendChild(div);
    div.style.left = Math.min(rect.left + window.scrollX, window.innerWidth - div.offsetWidth - 10) + 'px';
    div.style.top = (rect.bottom + window.scrollY + 4) + 'px';
    textarea.focus();
  }

  // Click handler for highlights
  document.addEventListener('click', function(e) {
    var highlight = e.target.closest('.sf-highlight');
    if (highlight) {
      var id = highlight.dataset.annotationId;
      var annotations = loadAnnotations();
      var annotation = annotations.find(function(a) { return a.id === id; });
      if (annotation) showCommentViewer(annotation, highlight);
      return;
    }
    // Close viewer on outside click
    if (activeViewer && !activeViewer.contains(e.target)) removeViewer();
  });

  // --- Badge ---
  function updateBadge() {
    var existing = document.querySelector('.sf-badge');
    if (existing) existing.remove();
    var count = loadAnnotations().length;
    if (count === 0) return;
    var badge = document.createElement('span');
    badge.className = 'sf-badge';
    badge.textContent = count;
    var nav = document.querySelector('.nav-controls');
    if (nav) nav.prepend(badge);
  }
```

- [ ] **Step 2: Commit**

```bash
git add templates/production/web-book/annotations.js
git commit -m "Add comment viewer, edit/delete, and annotation badge"
git push
```

---

### Task 12: Initialization — wire everything together on page load

**Files:**
- Modify: `templates/production/web-book/annotations.js`

- [ ] **Step 1: Add init function and close the IIFE**

```js
  // --- Anchor Re-validation ---
  function revalidateAnchors() {
    var annotations = loadAnnotations();
    var valid = [];
    var stale = [];

    annotations.forEach(function(a) {
      if (a.type === 'margin-note') {
        // Margin notes just need the paragraph to exist
        var block = getBlockByIndex(a.scene, a.anchor ? a.anchor.paragraphIndex : 0);
        if (block) { valid.push(a); } else { stale.push(a); }
        return;
      }
      if (!a.anchor || !a.anchor.selectedText) { valid.push(a); return; }

      // Check if selectedText exists at the stored location
      var block = getBlockByIndex(a.anchor.scene || a.scene, a.anchor.paragraphIndex);
      if (block && block.textContent.indexOf(a.anchor.selectedText) !== -1) {
        valid.push(a);
        return;
      }

      // Scan nearby paragraphs (+/- 3)
      var section = document.querySelector('[data-scene="' + (a.anchor.scene || a.scene) + '"]');
      if (!section) { stale.push(a); return; }
      var blocks = section.querySelectorAll('p, blockquote, ul, ol, h1, h2, h3, h4, h5, h6');
      var found = false;
      var searchStart = Math.max(0, a.anchor.paragraphIndex - 3);
      var searchEnd = Math.min(blocks.length - 1, a.anchor.paragraphIndex + 3);

      for (var i = searchStart; i <= searchEnd; i++) {
        if (blocks[i] && blocks[i].textContent.indexOf(a.anchor.selectedText) !== -1) {
          // Re-anchor to new paragraph index
          a.anchor.paragraphIndex = i;
          // Recalculate offsets
          var textContent = blocks[i].textContent;
          a.anchor.startOffset = textContent.indexOf(a.anchor.selectedText);
          a.anchor.endOffset = a.anchor.startOffset + a.anchor.selectedText.length;
          valid.push(a);
          found = true;
          break;
        }
      }
      if (!found) stale.push(a);
    });

    // Save re-anchored valid annotations
    saveAnnotations(valid);
    return stale;
  }

  function renderStalePanel(staleAnnotations) {
    if (!staleAnnotations || staleAnnotations.length === 0) return;

    var panel = document.createElement('div');
    panel.className = 'sf-stale-panel';

    var h3 = document.createElement('h3');
    h3.textContent = 'Stale Annotations (' + staleAnnotations.length + ')';
    panel.appendChild(h3);

    staleAnnotations.forEach(function(a) {
      var details = document.createElement('details');
      var summary = document.createElement('summary');
      summary.textContent = (a.type === 'margin-note' ? 'Margin note' : (a.comment ? 'Comment' : 'Highlight'));
      details.appendChild(summary);

      if (a.anchor && a.anchor.selectedText) {
        var quote = document.createElement('blockquote');
        quote.textContent = a.anchor.selectedText;
        details.appendChild(quote);
      }
      if (a.comment) {
        var note = document.createElement('p');
        note.style.fontSize = '0.85rem';
        note.style.margin = '4px 0 4px 12px';
        note.textContent = a.comment;
        details.appendChild(note);
      }

      var deleteBtn = document.createElement('button');
      deleteBtn.textContent = 'Delete';
      deleteBtn.onclick = function() { details.remove(); if (!panel.querySelector('details')) panel.remove(); };
      details.appendChild(deleteBtn);

      panel.appendChild(details);
    });

    var main = document.querySelector('.chapter-content');
    if (main) main.appendChild(panel);
  }

  // --- Init ---
  function init() {
    var stale = revalidateAnchors();
    renderAllHighlights();
    renderAllMarginNotes();
    renderStalePanel(stale);
    setupMarginTriggers();
    createToolbar();
    updateBadge();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
```

- [ ] **Step 2: Commit**

```bash
git add templates/production/web-book/annotations.js
git commit -m "Add annotation overlay initialization"
git push
```

---

## Chunk 4: Export

### Task 13: JSON and Markdown export

**Files:**
- Modify: `templates/production/web-book/annotations.js`

This adds export functions that collect annotations from all chapters (by scanning localStorage keys) and produce downloadable files.

- [ ] **Step 1: Add export functions before the init block**

Insert before the `// --- Init ---` section:

```js
  // --- Export ---
  function getAllAnnotations() {
    var all = [];
    for (var i = 0; i < localStorage.length; i++) {
      var key = localStorage.key(i);
      if (key.indexOf(STORAGE_PREFIX) === 0) {
        try {
          var items = JSON.parse(localStorage.getItem(key));
          if (Array.isArray(items)) all = all.concat(items);
        } catch (e) { /* skip corrupt entries */ }
      }
    }
    // Sort by chapter, then scene, then paragraph index
    all.sort(function(a, b) {
      if (a.chapter !== b.chapter) return a.chapter < b.chapter ? -1 : 1;
      if (a.scene !== b.scene) return (a.scene || '') < (b.scene || '') ? -1 : 1;
      return (a.anchor ? a.anchor.paragraphIndex : 0) - (b.anchor ? b.anchor.paragraphIndex : 0);
    });
    return all;
  }

  function exportJSON(annotations) {
    var bookTitle = document.querySelector('.nav-title');
    var data = {
      book: bookTitle ? bookTitle.textContent : document.title,
      exportedAt: new Date().toISOString(),
      annotator: 'author',
      annotations: annotations
    };
    return JSON.stringify(data, null, 2);
  }

  function exportMarkdown(annotations) {
    var bookTitle = document.querySelector('.nav-title');
    var title = bookTitle ? bookTitle.textContent : document.title;
    var lines = ['# Annotations: ' + title];
    lines.push('Exported: ' + new Date().toISOString().split('T')[0]);
    lines.push('');

    var currentChapter = '';
    var currentScene = '';

    // Build a chapter title lookup from TOC links if available
    var chapterTitles = {};
    document.querySelectorAll('.toc-contents a').forEach(function(link) {
      var href = link.getAttribute('href') || '';
      var match = href.match(/chapters\/(chapter-\d+)\.html/);
      if (match) chapterTitles[match[1]] = link.textContent.trim();
    });

    annotations.forEach(function(a) {
      if (a.chapter !== currentChapter) {
        currentChapter = a.chapter;
        currentScene = '';
        var num = parseInt(currentChapter.replace('chapter-', ''), 10);
        var chTitle = chapterTitles[currentChapter];
        lines.push('## Chapter ' + num + (chTitle ? ': ' + chTitle : ''));
        lines.push('');
      }
      if (a.scene && a.scene !== currentScene) {
        currentScene = a.scene;
        lines.push('### Scene: ' + a.scene);
        lines.push('');
      }
      // Per-annotation type label for margin notes
      if (a.type === 'margin-note') {
        lines.push('*(margin note)*');
      }
      if (a.anchor && a.anchor.selectedText) {
        lines.push('> "' + a.anchor.selectedText + '"');
      }
      if (a.comment) {
        lines.push(a.comment);
      }
      lines.push('');
    });

    return lines.join('\n');
  }

  function downloadFile(content, filename, mimeType) {
    var blob = new Blob([content], { type: mimeType });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function doExport(format) {
    var annotations = format === 'chapter'
      ? loadAnnotations()
      : getAllAnnotations();

    if (annotations.length === 0) {
      alert('No annotations to export.');
      return;
    }

    var slug = chapterSlug || 'all';
    if (format === 'json' || format === 'chapter-json') {
      downloadFile(exportJSON(annotations), 'annotations-' + slug + '.json', 'application/json');
    } else {
      downloadFile(exportMarkdown(annotations), 'annotations-' + slug + '.md', 'text/markdown');
    }
  }

  // Add export button to nav controls
  function addExportButton() {
    var nav = document.querySelector('.nav-controls');
    if (!nav) return;

    var btn = document.createElement('button');
    btn.setAttribute('aria-label', 'Export annotations');
    btn.textContent = '\u2913'; // downwards arrow
    btn.style.cssText = 'background:none;border:none;color:var(--text);font-size:1.2rem;cursor:pointer;padding:4px';
    btn.onclick = function(e) {
      e.stopPropagation();
      showExportMenu(btn);
    };
    nav.prepend(btn);
  }

  function showExportMenu(anchorEl) {
    var existing = document.querySelector('.sf-export-menu');
    if (existing) { existing.remove(); return; }

    var menu = document.createElement('div');
    menu.className = 'sf-export-menu';
    menu.style.cssText = 'position:absolute;z-index:102;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:4px;box-shadow:0 2px 8px rgba(0,0,0,0.15)';

    var options = [
      { label: 'This chapter (JSON)', action: function() { doExport('chapter-json'); } },
      { label: 'This chapter (MD)', action: function() { doExport('chapter'); } },
      { label: 'All chapters (JSON)', action: function() { doExport('json'); } },
      { label: 'All chapters (MD)', action: function() { doExport('md'); } }
    ];

    options.forEach(function(opt) {
      var item = document.createElement('button');
      item.textContent = opt.label;
      item.style.cssText = 'display:block;width:100%;text-align:left;background:none;border:none;color:var(--text);padding:6px 10px;font-size:0.85rem;cursor:pointer;white-space:nowrap';
      item.onmouseenter = function() { item.style.background = 'var(--border)'; };
      item.onmouseleave = function() { item.style.background = 'none'; };
      item.onclick = function() { menu.remove(); opt.action(); };
      menu.appendChild(item);
    });

    var rect = anchorEl.getBoundingClientRect();
    document.body.appendChild(menu);
    menu.style.top = (rect.bottom + window.scrollY + 4) + 'px';
    menu.style.right = (window.innerWidth - rect.right) + 'px';

    // Close on outside click
    setTimeout(function() {
      document.addEventListener('click', function handler(e) {
        if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('click', handler); }
      });
    }, 0);
  }
```

- [ ] **Step 2: Add `addExportButton()` call to the init function**

Update init to include:

```js
  function init() {
    var stale = revalidateAnchors();
    renderAllHighlights();
    renderAllMarginNotes();
    renderStalePanel(stale);
    setupMarginTriggers();
    createToolbar();
    updateBadge();
    addExportButton();
  }
```

- [ ] **Step 3: Commit**

```bash
git add templates/production/web-book/annotations.js
git commit -m "Add JSON and Markdown export with download menu"
git push
```

---

## Chunk 5: Storyforge Annotate Skill

### Task 14: Create the `storyforge:annotate` skill

**Files:**
- Create: `skills/annotate/SKILL.md`

- [ ] **Step 1: Create the skill directory**

```bash
mkdir -p skills/annotate
```

- [ ] **Step 2: Write the skill file**

Create `skills/annotate/SKILL.md` following the established skill pattern (see `skills/review/SKILL.md` or `skills/produce/SKILL.md` for format):

```markdown
---
name: annotate
description: Import author annotations from web book export and generate a revision plan. Use when the user has an annotations JSON or markdown file from reading their web book, or when they paste annotation notes directly.
---

# Storyforge: Import Annotations

Import annotations exported from the Storyforge web book reader and convert them into an actionable revision plan.

## Plugin Root

The plugin root is two levels up from this skill file.

## Step 1: Locate the Annotation File

Check for annotation export files:
1. Look in `working/` for files matching `annotations-*.json` or `annotations-*.md`
2. If the user pasted annotation content directly, parse it from the conversation
3. If no file found and nothing pasted, ask the user to provide their export file

## Step 2: Parse Annotations

**JSON format:**
- Read the file, parse the `annotations` array
- Each annotation has: `id`, `type`, `chapter`, `scene`, `anchor` (with `paragraphIndex`, `startOffset`, `endOffset`, `selectedText`), `comment`, `createdAt`

**Markdown format:**
- Parse by `## Chapter` and `### Scene:` headings
- Blockquotes (`>`) are selected text
- Lines after blockquotes are comments
- `(margin note)` suffix indicates margin notes

## Step 3: Validate Against Scene Files

For each annotation:
1. Map `scene` field to `scenes/{scene-id}.md`
2. Verify the scene file exists
3. Check if `selectedText` appears as a substring in the scene prose
4. If exact match fails, check for longest common substring (fuzzy match)
5. Annotations below 50% text overlap: flag as **stale** with a warning

Report validation summary:
- Total annotations
- Matched annotations
- Stale annotations (with quoted text for manual review)
- Annotations per scene (sorted by density — most-annotated first)

## Step 4: Categorize Notes

Read each annotation's comment and selected text. Categorize into:
- **Content** — rewrite, expand, cut, rephrase requests
- **Pacing** — too fast, too slow, dragging, rushing
- **Character** — voice, motivation, consistency
- **Continuity** — timeline issues, contradictions
- **Craft** — prose quality, word choice, repetition
- **Structure** — scene order, chapter breaks, transitions

Present the categorized summary to the user.

## Step 5: Generate Revision Plan

Build a revision plan ordered by scene, with the most-annotated scenes first:

For each scene with annotations:
1. List the scene file path
2. List all annotations with their categories
3. Quote the relevant text
4. Include the author's comment

Save the revision plan to `working/annotation-revision-plan.md`.

Then invoke `storyforge:plan-revision` to convert this into an executable revision pipeline, passing the annotation revision plan as input context.

## Coaching Level Behavior

- **full**: Parse annotations, validate, categorize, generate revision plan, invoke plan-revision
- **coach**: Parse and validate annotations, present categorized summary with recommendations, save analysis to `working/coaching/annotation-analysis.md`. Do not auto-generate revision plan — let the author decide what to revise
- **strict**: Parse and validate only. Present raw validated annotation list with stale warnings. Save to `working/coaching/annotation-checklist.md`. No categorization, no recommendations
```

- [ ] **Step 3: Commit**

```bash
git add skills/annotate/SKILL.md
git commit -m "Add storyforge:annotate skill for importing web book annotations"
git push
```

---

## Chunk 6: Integration Testing & Documentation

### Task 15: Add annotation-specific tests

**Files:**
- Create: `tests/test-annotations.sh`
- Modify: `tests/run-tests.sh` (only if needed — runner auto-discovers `test-*.sh` files)

- [ ] **Step 1: Write test file for scene marker injection and wrapping**

```bash
#!/bin/bash
# test-annotations.sh — Tests for annotation build integration
#
# Run via: ./tests/run-tests.sh tests/test-annotations.sh
# Tests scene marker injection, section wrapping, and annotation flag behavior.
#
# Depends on: FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, assertion functions (from run-tests.sh)

# ============================================================================
# Scene markers in assembled chapters
# ============================================================================

result=$(assemble_chapter 1 "$PROJECT_DIR" "ornamental")
assert_contains "$result" "<!-- scene:act1-sc01 -->" "annotations: chapter 1 has scene marker for act1-sc01"
assert_contains "$result" "<!-- scene:act1-sc02 -->" "annotations: chapter 1 has scene marker for act1-sc02"

# Scene markers appear before scene prose
first_marker=$(echo "$result" | grep -n "scene:act1-sc01" | head -1 | cut -d: -f1)
first_prose=$(echo "$result" | grep -n "Dorren Hayle" | head -1 | cut -d: -f1)
if [[ "$first_marker" -lt "$first_prose" ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: annotations: scene marker appears before scene prose"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: annotations: scene marker should appear before scene prose"
fi

# Single-scene chapter also gets marker
result=$(assemble_chapter 2 "$PROJECT_DIR" "ornamental")
assert_contains "$result" "<!-- scene:act2-sc01 -->" "annotations: single-scene chapter has scene marker"

# ============================================================================
# _wrap_scene_sections
# ============================================================================

input='<h2>Chapter 1</h2>
<!-- scene:act1-sc01 -->
<p>First scene paragraph.</p>
<p>Second paragraph.</p>
<!-- scene:act1-sc02 -->
<p>Second scene paragraph.</p>'

result=$(echo "$input" | _wrap_scene_sections)
assert_contains "$result" '<section data-scene="act1-sc01">' "wrap_sections: creates section for first scene"
assert_contains "$result" '<section data-scene="act1-sc02">' "wrap_sections: creates section for second scene"
assert_contains "$result" '</section>' "wrap_sections: closes section tags"
assert_not_contains "$result" '<!-- scene:' "wrap_sections: removes HTML comment markers"

# Heading before first scene marker should not be wrapped
assert_contains "$result" '<h2>Chapter 1</h2>' "wrap_sections: preserves content before first scene marker"

# Single scene wrapping
input_single='<!-- scene:sc01 -->
<p>Only scene.</p>'
result=$(echo "$input_single" | _wrap_scene_sections)
assert_contains "$result" '<section data-scene="sc01">' "wrap_sections: works with single scene"
assert_contains "$result" '</section>' "wrap_sections: closes single scene section"
```

- [ ] **Step 2: Add --annotate flag integration tests (requires pandoc)**

These tests verify the full build pipeline. Skip if pandoc is unavailable.

```bash
# ============================================================================
# --annotate flag integration (requires pandoc)
# ============================================================================

if command -v pandoc &>/dev/null && [[ -d "${PROJECT_DIR}/scenes" ]]; then
    # Build web book WITH --annotate
    ann_out=$(mktemp -d "${TMPDIR:-/tmp}/sf-ann-test.XXXXXX")
    (cd "$PROJECT_DIR" && "${PLUGIN_DIR}/scripts/storyforge-assemble" --format web --annotate 2>/dev/null)
    if [[ -f "${PROJECT_DIR}/manuscript/output/web/chapters/chapter-01.html" ]]; then
        ch1=$(cat "${PROJECT_DIR}/manuscript/output/web/chapters/chapter-01.html")
        assert_contains "$ch1" 'data-scene=' "annotate flag: chapter HTML contains data-scene attributes"
        assert_contains "$ch1" 'Annotation Overlay' "annotate flag: chapter HTML contains annotation JS"
        assert_contains "$ch1" 'sf-highlight' "annotate flag: chapter HTML contains annotation CSS"
        assert_contains "$ch1" 'data-book=' "annotate flag: chapter HTML contains data-book attribute"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: annotate flag: web book chapter-01.html not generated"
    fi

    # Build web book WITHOUT --annotate
    (cd "$PROJECT_DIR" && "${PLUGIN_DIR}/scripts/storyforge-assemble" --format web 2>/dev/null)
    if [[ -f "${PROJECT_DIR}/manuscript/output/web/chapters/chapter-01.html" ]]; then
        ch1_clean=$(cat "${PROJECT_DIR}/manuscript/output/web/chapters/chapter-01.html")
        assert_not_contains "$ch1_clean" 'sf-highlight' "no annotate flag: chapter HTML does not contain annotation CSS"
        assert_not_contains "$ch1_clean" 'data-scene=' "no annotate flag: chapter HTML does not contain data-scene attributes"
    fi
fi
```

- [ ] **Step 3: Run the new test suite**

Run: `./tests/run-tests.sh tests/test-annotations.sh`
Expected: All PASS.

- [ ] **Step 4: Run full test suite for regression check**

Run: `./tests/run-tests.sh`
Expected: All suites PASS, no regressions.

- [ ] **Step 4: Commit**

```bash
git add tests/test-annotations.sh
git commit -m "Add annotation integration tests for scene markers and section wrapping"
git push
```

---

### Task 16: Add annotations config to chapter-map template

The spec defines a YAML config alternative to the `--annotate` CLI flag. For this release, the YAML config is documented but not wired into `storyforge-assemble` — it's parsed only by the skill for mode detection. Reading YAML config in the assembly script is deferred to when beta reader mode is implemented.

**Files:**
- Modify: `templates/production/chapter-map-template.yaml` (add annotations config section)

- [ ] **Step 1: Add annotations config to chapter-map template**

Read `templates/production/chapter-map-template.yaml` and add under the `production:` section:

```yaml
  # Annotations (for web book --annotate mode)
  # annotations:
  #   enabled: false
  #   mode: author  # or "beta"
```

- [ ] **Step 2: Commit**

```bash
git add templates/production/chapter-map-template.yaml
git commit -m "Add annotations config to chapter-map template"
git push
```

---

### Task 17: End-to-end manual verification

This task is not automated — it verifies the full workflow works on a real project.

- [ ] **Step 1: Build a web book with --annotate flag**

On a test project (or the fixture project with enough content):

```bash
./scripts/storyforge-assemble --format web --annotate
```

Verify:
- `manuscript/output/web/chapters/` contains HTML files
- Chapter HTML files contain `<section data-scene="...">` wrappers
- Chapter HTML files contain annotation CSS and JS
- Opening a chapter in a browser shows the annotation UI

- [ ] **Step 2: Test annotation workflow**

In a browser:
1. Select text → popover appears (desktop) or toolbar shows options (mobile)
2. Create a highlight — verify yellow highlight renders
3. Create a comment — verify highlight with dot indicator
4. Add a margin note — verify pencil icon appears
5. Tap highlight → viewer shows comment, edit/delete work
6. Export JSON and Markdown — verify files download with correct content
7. Close and reopen page — verify annotations persist from localStorage

- [ ] **Step 3: Build without --annotate and verify clean output**

```bash
./scripts/storyforge-assemble --format web
```

Verify:
- No annotation JS/CSS in chapter HTML
- No `<section data-scene>` wrappers
- Reading experience unchanged
