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

1. **Read `storyforge.yaml`** — title, genre, target word count, phase, artifact status. **Note the `project.coaching_level` field** — it controls how proactive you should be with chapter creation (see Coaching Level Behavior below).
2. **Read `scenes/scene-index.yaml`** — how many scenes, their status (drafted/revised/pending), groupings (acts/parts).
3. **Check for existing production artifacts:**
   - `reference/chapter-map.yaml` — does it exist? How many chapters?
   - `manuscript/` directory — has assembly been run before?
4. **Read the key decisions file** — check for any production-related decisions already made.
5. **Count scene files** in `scenes/` — verify that referenced scenes have actual content.

## Step 1.5: Title Check

Before proceeding to chapter mapping or assembly, check whether the title is finalized:

1. Read the key decisions file. If a title decision is recorded there, the title is settled — use it and move on.
2. If no title decision exists, ask the author: "Your current title is '{title}'. Is this final, or would you like to explore alternatives before we assemble?"
   - If final: record as a key decision and continue.
   - If not sure: invoke the `title` skill. Return to produce when title is settled.

## Step 2: Determine Mode

Based on the author's message and project state, operate in one of these modes:

---

### First-Time Setup

The chapter map doesn't exist yet. Guide the author through creating it. **How you guide depends on coaching level** — see Coaching Level Behavior below.

**If given specific direction** (e.g., "make each act a part, with scenes grouped into chapters of 2-3 scenes each"), skip assessment and execute the direction immediately at any coaching level.

**If no specific direction and coaching level is `full`**, analyze the scene index and propose a chapter structure:

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

7. **Cover image** — "Do you have a cover image?"
   - Provide file path (will be embedded in the epub)
   - Design one interactively (invoke the `cover` skill for Claude-designed SVG artwork or AI-generated illustrations — return to produce when the cover is complete)
   - Generate one automatically (basic typographic cover from title and genre — preview with `./storyforge cover --svg-only`)
   - Skip for now (can be added later)

   If the author chooses interactive design: invoke the `cover` skill. Return to produce when the cover is complete.
   If generating automatically: ask about an optional subtitle/tagline for the cover. Save to `production.cover.subtitle` in the chapter map.

8. **Copyright** — "Copyright details:"
   - Year (default: current year)
   - ISBN (if available, otherwise skip)
   - License text (default: "All rights reserved.")

Update `reference/chapter-map.yaml` with all production settings after each answer.

**After all settings are configured**, execute these steps **in this exact order**. Do not write any files before step 2 is complete.

**1. Create the feature branch.** This must happen first, before any file is written or modified:
```bash
git checkout -b "storyforge/assemble-$(date '+%Y%m%d-%H%M')"
```

**2. Verify you are on the new branch** before proceeding:
```bash
git rev-parse --abbrev-ref HEAD
```
The output must start with `storyforge/assemble-`. If it does not, stop and fix the branch before writing any files.

**3. Write the chapter map** to `reference/chapter-map.yaml` with all production settings.

**4. Update project state:** set `chapter_map.exists: true` and `chapter_map.updated` to today's date in `storyforge.yaml`.

**5. Commit and push** all changes to the new branch:
```bash
git add -A && git commit -m "Produce: create chapter map and production settings" && git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
```

**6. Tell the author** how to run the assembly: `./storyforge assemble`. The script will detect this branch, create a draft PR, and track progress there.

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
- `--format web` — generate multi-page web book for hosting (beautiful reading experience with dark mode, reading position, chapter navigation)
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

## Decisions Are Recorded Selectively

Only record genuine creative decisions in the key decisions file — not configuration or routine choices. Chapter structure (how scenes group into chapters, pacing, flow) is a creative decision worth recording. Typography presets, scene break style, and format choices are configuration saved in the chapter map — they do not belong in key decisions.

**Record:** "15 chapters following act breaks, with the midpoint cliffhanger isolated as its own short chapter" (creative/structural)
**Don't record:** "Fantasy genre preset with ornamental scene breaks" (configuration — already in chapter-map.yaml)

## Coaching Level Behavior

Read `project.coaching_level` from storyforge.yaml. Chapter creation — deciding which scenes group into which chapters, setting pacing and flow — is a **creative endeavor**. Coaching levels apply to it.

### `full` (default)
Proactively propose a complete chapter structure. Analyze the scene index, group scenes into chapters based on narrative logic, and present the full proposal for approval. Create the chapter map on approval. Be opinionated about typography and formatting — you know what works for the genre.

### `coach`
Help the author think through chapter structure, but **do not generate a complete chapter proposal unprompted**. Instead:
- Present analysis: scene count per act, word counts, natural break points, POV shifts
- Ask guiding questions: "These three scenes share POV and setting — do they feel like one chapter to you?" "This act has 12 scenes — how many chapters feels right for the pacing you want?"
- When the author gives direction (e.g., "chapters of 2-3 scenes"), help them refine it — flag potential issues ("Chapter 4 would be 8,000 words — split it?") but let them make the grouping decisions
- Once the author has decided the structure, create the chapter map file for them

Production settings (typography, scene breaks, front/back matter) are **not** creative decisions — ask and execute as normal at all coaching levels.

### `strict`
**Do not propose chapter structure, groupings, or pacing decisions.** The author provides their chapter breakdown; you handle the files.
- Ask: "How do you want to group your scenes into chapters?" "What should each chapter be called?"
- Do not analyze or suggest groupings. Do not propose titles.
- Once the author provides their complete chapter structure, create the chapter map file and handle all file/metadata work
- Production settings (typography, scene breaks, front/back matter) are structural/mechanical — ask and execute as normal

## Coaching Posture

Production is exciting — the book is becoming a book. Be enthusiastic but practical. The author has done the hard creative work; this is about packaging it beautifully.

Be opinionated about typography and formatting — you know what works for the genre (in `full` and `coach` modes). But respect the author's taste. If they want sans-serif headings in their literary novel, that's their choice.

Don't over-explain technical details about epub structure or pandoc flags. The author cares about what their book looks like, not how it's built. Surface the creative choices; hide the plumbing.
