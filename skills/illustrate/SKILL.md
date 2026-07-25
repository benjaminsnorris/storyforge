---
name: illustrate
description: Plan, art-direct, and embed interior illustrations for a prose book. Use when the author wants illustrations in their novel — deciding where images belong, generating art direction to render them, or bringing finished illustrations into the manuscript.
---

# Storyforge Interior Illustrations

You are art-directing the interior illustrations for a prose book. This is not the cover — the cover sells the book, and illustrations deepen it. A good illustration arrives at a beat the reader is already leaning into and shows them something the sentences could only deliver one at a time.

The flow is: **decide where** → **art-direct** → the author renders externally → **ingest and embed** → produce.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory (this skill's directory → `skills/` → plugin root). Scripts live at `scripts/` and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

**Do not open image files.** Never run `open`, `xdg-open`, or any command to display or preview an illustration. The author may be working over SSH or already have the project open. Report the path and let them look however they prefer.

## Step 1: Read Project State

1. **`storyforge.yaml`** — title, genre, medium, coaching level, `production.cover_image`.
   - If `project.medium` is `graphic-novel`, **stop**. GN projects have their own page pipeline: `storyforge elaborate --stage page-architecture` and `--stage prompts`. Tell the author that and route them there.
2. **`reference/illustration-plan.csv`** — the plan, if one exists. This tells you which mode you are in.
3. **Structural context** — read what exists:
   - `reference/story-summary.md` — logline, synopsis, act shape, theme
   - `reference/spine.csv` — the irreducible events
   - `reference/architecture.csv` — turning points, value shifts
   - `reference/scene-intent.csv` — emotional arcs
   - `reference/motif-taxonomy.csv` — the concrete recurring vehicles
   - `reference/themes.csv` — what the story argues
   - `reference/chapter-map.csv` — distribution
4. **Visual context** — `reference/character-bible.md`, `reference/world-bible.md`, `reference/voice-guide.md`.
5. **Existing art** — `manuscript/assets/` for the cover and `cover-prompt.md` (the best available statement of the book's visual register), and `manuscript/assets/illustrations/` for anything already ingested.

## Step 2: Determine Mode

| State | Mode |
|-------|------|
| No plan | **Plan** — decide where illustrations belong |
| Plan exists, rows at `status=planned` | **Art-direct** — write the prompts |
| Author has rendered files | **Ingest** — bring them in and embed |
| An illustration isn't working | **Revise** — supersede and re-direct |
| Author asks how things stand | **Diagnose** — `storyforge illustrate --diagnose` |

Announce the mode you're in and why before doing anything.

---

## Mode: Plan

Deciding *where* illustrations belong is the part that matters most. An illustration in the wrong place is worse than no illustration — it reads as a mistake the author made on purpose.

### How many

Propose a count rather than assuming one. Roughly one illustration every two to three chapters reads as designed; more than that and the art starts competing with the prose. The command's pre-pass recommends a count from chapter and spine-event counts — start there and discuss.

### What earns an illustration

Work through these with the author (or decide, in `full` coaching):

- **The image does something the prose cannot.** A composition, a scale, a spatial relationship. Sentences deliver those sequentially; a picture holds them at once.
- **The beat is already carrying weight.** A turning point, a value shift, the third appearance of a motif the book has been building. The image inherits that accumulated meaning for free.
- **It doesn't spoil the facing page.** This is the failure mode you cannot fix later — a reader sees an illustration before they read past it. An image that reveals what the next paragraph is about to reveal has broken the scene.
- **It's distributed.** Illustrations bunched into three chapters follow the author's enthusiasm rather than the book's shape.
- **It's renderable.** A specific subject in a specific space. Not an abstraction, not a montage.

### Running it

Delegate to the command. Offer both options:

> **Option A: Run it here**
> I'll run the planning pass in this conversation.
>
> **Option B: Run it yourself**
> ```bash
> cd [project_dir] && [plugin_path]/storyforge illustrate --plan
> ```

Add `--count N` to override the recommended count. Wait for the author's choice; if Option B, give them the command and stop.

Read the resulting plan back to the author in prose — the moment, why it earns the image, what it shows. A CSV dump is not a conversation. Then commit.

### Anchors

Every plan row carries an `anchor` — a short verbatim quote from its scene marking where the image lands. Anchors are what let the plan survive revision: when prose changes, a drifted anchor is *reported* rather than silently placing art at the wrong offset.

An anchor must be **unique within its scene**. A generic phrase that recurs is worse than useless — the command refuses to insert on an ambiguous anchor. If the planning pass produces one, lengthen it.

---

## Mode: Art-direct

Turn planned rows into prompts the author can paste into an image model.

```bash
[plugin_path]/storyforge illustrate --prompts
```

Add `--ids one,two` to limit it to specific illustrations.

This writes `manuscript/assets/illustrations/prompts/{id}.md` per illustration, and sets `status=prompted`. Each prompt file carries the reference list, the prompt body in OpenAI's five-section template, the constraints, and a log table.

### What the prompts encode

These come from lived iteration (benjaminsnorris/ashes PR #9, tracked as #260 and #263). Do not paraphrase them away when you edit a prompt by hand:

1. **Five-section template** — Scene / Subject / Important details / Use case / Constraints. Structure beats brevity.
2. **Reference images carry style and likeness**, so prompt prose stays short (~250–400 words). The references are the cover art plus prior ingested illustrations — that chain is what keeps a book's interior art visually of a piece instead of fifteen unrelated pictures.
3. **The character anchor is the identical string every time.** Anchors persist in `manuscript/assets/illustrations/character-anchors.md`. Never revise an anchor a rendered illustration already used — likeness continuity depends on the string being byte-identical.
4. **Positive framing, not negation.** Negated keywords leak into the image. "A bare sill," not "no clutter on the sill."
5. **Explicit orientation, in two places.** GPT Image 2 returns landscape unless told otherwise. Portrait is the default; put `landscape` or `square` in the row's `composition` field to change it.

Plus: no text, no letters, no words, no typography. Image models render text unreliably, and an illustration doesn't need any.

### Author reviews before spending credits

Present the prompt to the author before they render. This is their money and their book. Common adjustments: tone, tightness of crop, level of abstraction, how much of the scene to show.

Tell them to record each attempt in the prompt file's log table. The prompt plus its settings is the reproducible seed for the art — it is the only way back to a result they liked two weeks ago.

Commit the prompt files.

---

## Mode: Ingest

The author has rendered files. Bring them in.

```bash
[plugin_path]/storyforge illustrate --ingest path/to/renders/
```

Files are matched to plan rows **by filename stem** — `lantern-vigil.png` matches the row with id `lantern-vigil`. A file matching nothing is reported and skipped, never guessed at. If the author's filenames don't match, have them rename, or ingest one file at a time.

Ingest normalizes each file to `manuscript/assets/illustrations/{id}.png`, records `sha256` / `width` / `height`, sets `status=ingested`, and then embeds the marker in the scene file.

Empty files and unreadable images are rejected with a warning rather than recorded.

### Markers

Embedding inserts `![[illus:{id}]]` on its own line in `scenes/{scene_id}.md`, at the paragraph boundary the anchor and `placement` select.

The marker is intentionally not a markdown image. One marker resolves three ways: to a local path for epub and PDF, to a copied asset for the web book, and to structured placement data for Bookshelf. A literal `![](path)` would be correct for one of those and wrong for the other two.

**Never hand-edit a marker into a scene without a matching plan row** — `cleanup` reports that as an orphan. Use `--embed` instead.

If an anchor has drifted after a revision, the command reports it with the nearest candidate line and refuses to insert. Fix the anchor in the plan, then re-run `--embed`.

Commit after ingest.

---

## Mode: Revise

An illustration isn't working.

1. Set its `status` to `superseded` in the plan.
2. Remove its marker from the scene (or run `--embed` after, which skips superseded rows).
3. Add a fresh row with a new id, or re-prompt the existing one with `--ids`.

Keep the superseded row. It records what was tried and why it didn't land, which is exactly what you want when the third attempt is also not working.

---

## Mode: Diagnose

```bash
[plugin_path]/storyforge illustrate --diagnose
```

Read-only. Reports plan counts by status, what's embedded, what's next to render, and every incoherence: orphan markers, missing files, files nobody claims, drifted anchors, duplicate markers.

An unrendered plan row is **valid in-flight state**, not a problem. Don't report it as one.

`storyforge cleanup` surfaces the same findings under "Interior Illustrations," and `storyforge validate` fails on the blocking ones.

---

## Producing the Book

Once illustrations are ingested and embedded, the rest of the pipeline handles them:

- **epub / PDF / HTML** — `storyforge assemble` resolves markers to project-relative image paths; the pandoc calls pass `--resource-path` so they resolve.
- **Web book** — illustrations are copied into `output/web/illustrations/`.
- **Bookshelf** — `storyforge publish` strips markers out of `content_html` and sends structured placements plus an asset manifest. Scene HTML stays byte-identical to the un-illustrated book, which is what keeps existing reader highlights from re-anchoring when art lands.

An illustration marked in a scene but not ingested does not publish; the manifest build warns about it.

## Coaching Level Behavior

Read `project.coaching_level` from `storyforge.yaml`.

### `full` (default)

Propose the illustration set with conviction and argue each moment's rationale. Write the art direction. Ingest and embed. You know what an image can do that prose can't — say so. If a moment the author wants would spoil a reveal, tell them plainly and offer the beat two paragraphs later instead.

### `coach`

Help the author find their own illustration set. The command writes a brief to `working/coaching/illustration-brief.md` with the structural findings framed as questions. Work through them:

- "What's the one image someone would remember from this book?"
- "Your lantern motif pays off three times and none are illustrated — which one carries the most weight?"
- "Are the illustrations carrying the plot, the world, or the interior life?"
- "Does anything here show the reader something they haven't been told yet?"

Don't pick the moments. When the author has decided, record their choices and execute the technical work.

### `strict`

No creative proposals. The command writes `working/coaching/illustration-checklist.md` — structural data and per-column requirements, nothing interpreted. The author supplies every moment, subject, palette, and composition. Ingest, embed, and validation are structural work and stay available; `--prompts` produces a five-section scaffold with the author's own constraint values and empty prose sections.

## Ensure Feature Branch

Before making any changes:
```bash
git rev-parse --abbrev-ref HEAD
```
- If on `main` or `master`, create a feature branch:
  ```bash
  git checkout -b "storyforge/illustrate-$(date '+%Y%m%d-%H%M')"
  ```
- If on any other branch, stay on it.

## Commit After Every Deliverable

Every artifact gets its own commit:

- Wrote or extended the plan? Commit and push.
- Wrote prompt files? Commit and push — including `character-anchors.md`.
- Ingested illustrations? Commit and push the files, the updated plan, and the scene files together, so the marker and the art it points at land in the same commit.
- Superseded an illustration? Commit and push.

```bash
git add -A && git commit -m "Illustrate: {what was done}" && git push
```

## Coaching Posture

Illustrations are an argument about what matters in the book. Fifteen of them say "these are the fifteen moments." Take that seriously — be direct when a proposed moment is decoration rather than meaning, and enthusiastic when the author finds one that will stay with a reader.

Set expectations on resolution: this is screen and epub quality, not print at 300 DPI. And on iteration: the first render is rarely the final one, which is why the prompt log exists.

The house style matters more than any single image. A book whose illustrations agree with each other — palette, framing, level of abstraction — looks made. One where each image was generated fresh looks assembled. That's what the reference chain in the prompts is for.
