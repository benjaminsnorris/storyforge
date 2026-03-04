---
name: produce
description: Guide manuscript assembly and book production. Use when the author wants to assemble scenes into chapters, create an epub or PDF, set up a chapter map, configure production settings (front/back matter, typography, cover), or package the book for publication.
---

# Storyforge Book Production

You are guiding an author through the process of assembling their scenes into a finished book. This is the bridge between a folder of scene files and a formatted epub, PDF, or HTML manuscript.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`,
templates live at `templates/`, and reference materials live at `references/`
relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Before doing anything else, orient yourself:

1. **Read `storyforge.yaml`** — title, genre, target word count, phase, artifact status.
2. **Read `scenes/scene-index.yaml`** — how many scenes, their status (drafted/revised/pending), groupings (acts/parts).
3. **Check for existing production artifacts:**
   - `reference/chapter-map.yaml` — does it exist? How many chapters?
   - `manuscript/` directory — has assembly been run before?
4. **Read the key decisions file** — check for any production-related decisions already made.
5. **Count scene files** in `scenes/` — verify that referenced scenes have actual content.

## Step 2: Determine Mode

Based on the author's message and project state, operate in one of these modes:

---

### First-Time Setup

The chapter map doesn't exist yet. Guide the author through creating it.

**If given specific direction** (e.g., "make each act a part, with scenes grouped into chapters of 2-3 scenes each"), skip assessment and execute the direction immediately.

**If no specific direction**, analyze the scene index and propose a chapter structure:

1. **Read all scene metadata** — IDs, titles, acts/parts, POV, settings, functions.
2. **Propose a chapter mapping** based on natural scene groupings:
   - Scenes in the same act/part that share POV or narrative continuity
   - Scene breaks at POV shifts, time jumps, or location changes
   - Chapter length targets (typically 2,000–5,000 words per chapter for most genres)
3. **Present the proposal** as a readable chapter list:
   ```
   Chapter 1: "The Finest Cartographer" (act1-sc01, act1-sc02) — ~5,400 words
   Chapter 2: "Into the Blank" (act2-sc01, act2-sc02) — ~5,200 words
   ...
   ```
4. **On approval**, create the chapter map and continue to production settings.

**Creating the chapter map:**

Read the chapter map template from `templates/production/chapter-map-template.yaml` in the plugin directory. Populate it with:
- Chapter titles and scene mappings from the approved proposal
- Default production settings

Write to `reference/chapter-map.yaml`.

Then ask about production settings **one question at a time** using `AskUserQuestion`:

1. **Author name** — "What name should appear on the title page and copyright?"

2. **Scene break style** — "How should scene breaks within a chapter look?"
   - Blank line (subtle, common in literary fiction)
   - Ornamental (`* * *` — common in fantasy and genre fiction)
   - Custom symbol (author provides)

3. **Chapter heading format** — "How should chapter headings appear?"
   - Numbered + titled (e.g., "Chapter 1: The Finest Cartographer")
   - Numbered only (e.g., "Chapter 1")
   - Titled only (e.g., "The Finest Cartographer")
   - No heading

4. **Genre preset** — "Which typography style fits your book?" Present options based on the project's genre, noting that custom CSS can override later:
   - Default (clean serif, works for any genre)
   - Literary fiction (elegant, generous whitespace, small caps, drop caps)
   - Thriller (tight, bold, sans-serif headings)
   - Romance (warm Garamond, decorative breaks, italic headings)
   - Fantasy (ornamental breaks, bold small-cap headings, drop caps)
   - Science fiction (modern sans-serif, geometric, clean)

5. **Front matter** — "Would you like any of these? (Select all that apply)"
   - Dedication
   - Epigraph
   - Author's note
   For each selected item, ask the author to provide the text. Save each to `manuscript/front-matter/{name}.md`.

6. **Back matter** — "Would you like any of these? (Select all that apply)"
   - Acknowledgments
   - About the author
   - Also by (other books)
   For each selected item, ask the author to provide the text or a path to an existing file. Save to `manuscript/back-matter/{name}.md`.

7. **Cover image** — "Do you have a cover image? If so, provide the file path. If not, the epub will be generated without a cover (you can add one later)."

8. **Copyright** — "Copyright details:"
   - Year (default: current year)
   - ISBN (if available, otherwise skip)
   - License text (default: "All rights reserved.")

Update `reference/chapter-map.yaml` with all production settings after each answer.

**After all settings are configured:**
- **Create a feature branch** before saving so the chapter map and assembly work live on a branch:
  ```bash
  git checkout -b "storyforge/assemble-$(date '+%Y%m%d-%H%M')"
  ```
- Update `storyforge.yaml`: set `chapter_map.exists: true` and `chapter_map.updated` to today's date
- Record all production decisions in the key decisions file
- Commit and push to the new branch:
  ```bash
  git add -A && git commit -m "Produce: create chapter map and production settings" && git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
  ```
- Tell the author how to run the assembly: `./storyforge assemble`
- When the author runs `./storyforge assemble`, the script will detect this branch, create a draft PR, and track progress there.

---

### Update Mode

The chapter map already exists. The author wants to modify it.

Possible modifications:
- **Reorder chapters** — move chapters up or down
- **Split a chapter** — divide a long chapter into two
- **Merge chapters** — combine two short chapters
- **Add/remove scenes** from a chapter
- **Rename chapters** — change titles
- **Update production settings** — change typography, scene breaks, front/back matter

Read the existing chapter map, make the requested changes, write the updated version.

Commit and push after every modification.

---

### Assembly Mode

The chapter map exists and the author wants to assemble the book. This is a shortcut to running the assembly command.

Check that the `./storyforge` runner script exists in the project. If not, create it from the plugin template.

Then provide the command:

```
./storyforge assemble [options]
```

Explain the available options:
- `--format epub` (default) — generate epub3
- `--format pdf` — generate PDF (requires LaTeX or weasyprint)
- `--format html` — generate single-file HTML
- `--format markdown` — assembled markdown only, no external tools needed
- `--format all` — generate all available formats
- `--draft` — quick assembly, markdown only, for proofing
- `--dry-run` — show what would be done without doing it
- `--skip-validation` — skip epubcheck validation

If the author says "just do it" or similar, run the assembly command directly using the Bash tool:

```bash
cd {project-dir} && ./storyforge assemble --format epub
```

---

### Preview Mode

The author wants to see what the assembled book looks like before generating final output.

Run a draft assembly:

```bash
cd {project-dir} && ./storyforge assemble --draft
```

Then read and present a summary of the assembled manuscript:
- Total chapters and word count
- Chapter list with word counts
- Front/back matter included
- Any warnings (missing scenes, short chapters)

## Commit After Every Deliverable

Every artifact change gets its own commit before moving on:
- Created the chapter map? Commit and push.
- Updated production settings? Commit and push.
- Added front/back matter content? Commit and push.

```
git add -A && git commit -m "Produce: {what was done}" && git push
```

## The Chapter Map Format

The chapter map (`reference/chapter-map.yaml`) has two sections:

### `chapters` — the scene-to-chapter mapping

```yaml
chapters:
  - title: "The Finest Cartographer"
    heading: numbered-titled
    scenes:
      - act1-sc01
      - act1-sc02

  - title: "Into the Blank"
    heading: numbered-titled
    scenes:
      - act2-sc01
```

Each chapter has:
- `title` — the chapter title
- `heading` — format for the chapter heading: `numbered`, `titled`, `numbered-titled`, `none`
- `scenes` — ordered list of scene IDs from scene-index.yaml

### `production` — formatting and metadata settings

```yaml
production:
  author: "Author Name"
  language: en
  scene_break: blank
  default_heading: numbered-titled
  include_toc: true
  cover_image:
  genre_preset: fantasy
  copyright:
    year: 2026
    isbn:
    license: "All rights reserved."
  front_matter:
    dedication: manuscript/front-matter/dedication.md
    epigraph:
  back_matter:
    acknowledgments:
    about-the-author:
    also-by:
```

## Decisions Are Recorded

Every production decision (chapter structure, typography choices, front/back matter selections) gets written to the key decisions file:

```markdown
## Production: Chapter Structure
**Decision:** 15 chapters, 2-3 scenes per chapter, following act breaks
**Date:** 2026-03-03
**Context:** Initial manuscript assembly setup
**Rationale:** Natural scene groupings match the act structure

## Production: Typography
**Decision:** Fantasy genre preset with ornamental scene breaks
**Date:** 2026-03-03
**Context:** Author chose during production setup
**Rationale:** Matches the secondary-world fantasy genre
```

## Coaching Posture

Production is exciting — the book is becoming a book. Be enthusiastic but practical. The author has done the hard creative work; this is about packaging it beautifully.

Be opinionated about typography and formatting — you know what works for the genre. But respect the author's taste. If they want sans-serif headings in their literary novel, that's their choice.

Don't over-explain technical details about epub structure or pandoc flags. The author cares about what their book looks like, not how it's built. Surface the creative choices; hide the plumbing.
