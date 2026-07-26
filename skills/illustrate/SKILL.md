---
name: illustrate
description: Plan, art-direct, and embed interior illustrations for a prose book. Use when the author wants illustrations in their novel — deciding where images belong, generating art direction to render them, or bringing finished illustrations into the manuscript.
---

# Storyforge Interior Illustrations

You are art-directing the interior illustrations for a prose book. This is not the cover — the cover sells the book, and illustrations deepen it. A good illustration arrives at a beat the reader is already leaning into and shows them something the sentences could only deliver one at a time.

The flow is: **set the art direction** → **decide where** → **art-direct each one** → the author renders externally → **ingest and embed** → **review the sequence** → produce.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory (this skill's directory → `skills/` → plugin root). Scripts live at `scripts/` and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

**Do not open image files.** Never run `open`, `xdg-open`, or any command to display or preview an illustration. The author may be working over SSH or already have the project open. Report the path and let them look however they prefer.

## Step 1: Read Project State

1. **`storyforge.yaml`** — title, genre, medium, coaching level, `production.cover_image`.
   - If `project.medium` is `graphic-novel`, **stop**. GN projects have their own page pipeline: `storyforge elaborate --stage page-architecture` and `--stage prompts`. Tell the author that and route them there.
2. **`reference/illustration-direction.md`** — the book-level art direction, if it exists. This is the document that governs every illustration; read it before anything else about the art.
3. **`reference/illustration-plan.csv`** — the plan, if one exists. Together with the direction document, this tells you which mode you are in.
4. **Structural context** — read what exists:
   - `reference/story-summary.md` — logline, synopsis, act shape, theme
   - `reference/spine.csv` — the irreducible events
   - `reference/architecture.csv` — turning points, value shifts
   - `reference/scene-intent.csv` — emotional arcs
   - `reference/motif-taxonomy.csv` — the concrete recurring vehicles
   - `reference/themes.csv` — what the story argues
   - `reference/chapter-map.csv` — distribution
5. **Visual context** — `reference/character-bible.md`, `reference/world-bible.md`, `reference/voice-guide.md`.
6. **Existing art** — `manuscript/assets/` for the cover and `cover-prompt.md` (the best available statement of the book's visual register), and `manuscript/assets/illustrations/` for anything already ingested.

## Step 2: Determine Mode

| State | Mode |
|-------|------|
| No direction document | **Direct** — set the book's visual contract first |
| Direction exists, no plan | **Plan** — decide where illustrations belong |
| Plan exists, rows at `status=planned` | **Art-direct** — write the prompts |
| Author has rendered files | **Ingest** — bring them in and embed |
| An illustration isn't working | **Revise** — supersede and re-direct |
| All or most are rendered | **Review** — check the sequence for continuity drift |
| Author asks how things stand | **Diagnose** — `storyforge illustrate --diagnose` |

Announce the mode you're in and why before doing anything.

---

## Mode: Direct

Before deciding where illustrations go, settle what they look like. `reference/illustration-direction.md` is the book's visual contract — one document, authored once, that every illustration inherits.

This is the highest-leverage artifact in the flow. A per-illustration prompt can be re-rolled for a few cents. A book whose fifteen images disagree with each other has to be re-rendered wholesale.

```bash
[plugin_path]/storyforge illustrate --direction
```

Five sections:

- **Format** — medium, rendering style, audience, in a sentence or two. "Full-color cinematic photorealism for a read-aloud fantasy novel, ages 6–8" tells an image model more than three paragraphs of adjectives.
- **Visual promise** — what every image must deliver. Usually a relationship between two registers: how the ordinary world reads, and how the extraordinary appears inside it.
- **Recurring visual language** — the rules that repeat. Palette split by faction or mood, camera height, depth of field, materials rendered naturalistically, the standing no-text rule.
- **Content limits** — what the art must never do. Intensity ceilings, imagery to stay away from, anything the audience age rules out. State these as limits, not as prompt text.
- **Continuity anchors** — one `### Name` subsection per thing that must look the same every time. Not just characters: creatures, key locations, signature props. Each body is a fixed description reused **verbatim** in every prompt that features it.

### Anchors are inputs, not residue

An anchor works only because every prompt uses the identical string. So it has to be written *before* the art, not derived from whichever illustration happened to be rendered first.

Put measurable facts in them — height in centimeters, age in years, exact hair and eye color, specific garments. Those are precisely what drifts between separately generated images, and stating them is the only defence.

**Never revise an anchor a rendered illustration already used.** If it's wrong, the fix is re-rendering from the corrected anchor, not editing the string and leaving the old art in place. If the model proposes a new anchor while writing a prompt, the command appends it to the direction document for you to review rather than treating it as settled.

`--diagnose` and `validate` report sections left empty or still holding template text — a scaffold fed to an image model as though it were direction is worse than no document at all.

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

### Placement and layout are different things

`placement` is *where in the prose* — `before_anchor`, `after_anchor`, `scene_open`, `scene_close`. `layout` is *how much page* — `full_page`, `half_page`, `double_page`, `inline`. "Full-page opener" is a `full_page` layout at a `scene_open` placement.

Layout is a production decision worth making deliberately. A double-page spread is a promise; spend it on the climax, not on the third-best image. And it drives aspect: a spread renders landscape whatever the composition note says.

### Render order

`--diagnose` prints the recommended order:

- **The visual key renders first.** One early illustration establishes the most shared vocabulary at once — the cast, the central location, the scale relationship, the palette. The command picks the one whose `canon_refs` cover the most ground, earliest. Render it first and every later image has something real to reference instead of a description.
- **Everything else goes in story order**, which automatically locks each entity's design in the earliest image it appears in.

The order also reports what each illustration `locks` — the anchors it is the first to show. Those are the renders you cannot afford to get wrong, because everything downstream references them.

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
3. **The continuity anchor is the identical string every time.** Anchors live in the `## Continuity anchors` section of `reference/illustration-direction.md`. Only the anchors an illustration actually shows are sent, narrowed by its `canon_refs`. Never revise an anchor a rendered illustration already used — likeness continuity depends on the string being byte-identical.
4. **Positive framing, not negation.** Negated keywords leak into the image. "A bare sill," not "no clutter on the sill."
5. **Explicit orientation, in two places.** GPT Image 2 returns landscape unless told otherwise. Aspect comes from `layout` first — a `double_page` spread is landscape because that is a fact about the page — then from the row's `composition` field, which can say `landscape` or `square`. Portrait otherwise.

The whole book-level direction goes into every prompt too, which is why the command warns loudly when the direction document is missing: without it the prompts carry no house style, and the images won't look like they belong to one book.

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

## Mode: Review

Once most illustrations are rendered, check the sequence **as a set**.

```bash
[plugin_path]/storyforge illustrate --review
```

Writes `working/illustration-sequence-review.md`: cross-sequence checks, the anchors to check each image against, the content limits, and the render order with what's done and what's pending.

This catches what nothing else can. Per-illustration validation passes on images that are individually fine and collectively inconsistent — a character an inch taller in image nine, a location whose layout quietly rearranged, light that brightens where the story darkens. Each render looks correct on its own; only the set shows the drift.

Review **before the set is complete**. Every later illustration references the earlier ones, so drift caught at image five costs one re-render and drift caught at image fifteen costs ten.

When you find drift, fix it by re-rendering from the anchor — not by patching the image and not by editing the anchor to match what was rendered. Then re-ingest and re-run `--diagnose`.

---

## Mode: Diagnose

```bash
[plugin_path]/storyforge illustrate --diagnose
```

Read-only. Reports plan counts by status, what's embedded, the recommended render order with the visual key marked, what's next to render, and every incoherence: orphan markers, missing files, files nobody claims, drifted anchors, duplicate markers, invalid layouts.

An unrendered plan row is **valid in-flight state**, not a problem. Don't report it as one.

`storyforge cleanup` surfaces the same findings under "Interior Illustrations," and `storyforge validate` fails on the blocking ones.

---

## Producing the Book

Once illustrations are ingested and embedded, the rest of the pipeline handles them:

- **epub / PDF / HTML** — `storyforge assemble` resolves markers to project-relative image paths; the pandoc calls pass `--resource-path` so they resolve. `layout` is recorded on the plan for print production; honoring full-page and double-page treatment in the PDF is not yet automated.
- **Web book** — illustrations are copied into `output/web/illustrations/`.
- **Bookshelf** — `storyforge publish` strips markers out of `content_html` and sends structured placements plus an asset manifest. Scene HTML stays byte-identical to the un-illustrated book, which is what keeps existing reader highlights from re-anchoring when art lands.

An illustration marked in a scene but not ingested does not publish; the manifest build warns about it.

## Coaching Level Behavior

Read `project.coaching_level` from `storyforge.yaml`.

### `full` (default)

Draft the direction document from the bibles, then read it back and say what you committed to and why. Propose the illustration set with conviction and argue each moment's rationale. Write the per-illustration art direction. Ingest and embed. You know what an image can do that prose can't — say so. If a moment the author wants would spoil a reveal, tell them plainly and offer the beat two paragraphs later instead.

### `coach`

The direction document arrives as a template of questions, one per section. Work through those with the author first — the visual contract is theirs to set.

Then help them find their own illustration set. The command writes a brief to `working/coaching/illustration-brief.md` with the structural findings framed as questions:

- "What's the one image someone would remember from this book?"
- "Your lantern motif pays off three times and none are illustrated — which one carries the most weight?"
- "Are the illustrations carrying the plot, the world, or the interior life?"
- "Does anything here show the reader something they haven't been told yet?"

Don't pick the moments. When the author has decided, record their choices and execute the technical work.

### `strict`

No creative proposals. The direction document arrives as a blank template listing what each section must contain; the author writes all of it. The command writes `working/coaching/illustration-checklist.md` — structural data and per-column requirements, nothing interpreted. The author supplies every moment, subject, palette, and composition. Ingest, embed, and validation are structural work and stay available; `--prompts` produces a five-section scaffold with the author's own constraint values and empty prose sections.

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

- Wrote or edited the direction document? Commit and push — it governs everything after it.
- Wrote or extended the plan? Commit and push.
- Wrote prompt files? Commit and push — including any anchors appended to the direction document.
- Ingested illustrations? Commit and push the files, the updated plan, and the scene files together, so the marker and the art it points at land in the same commit.
- Superseded an illustration? Commit and push.
- Ran a sequence review? Commit the checklist, then commit each drift fix separately.

```bash
git add -A && git commit -m "Illustrate: {what was done}" && git push
```

## Coaching Posture

Illustrations are an argument about what matters in the book. Fifteen of them say "these are the fifteen moments." Take that seriously — be direct when a proposed moment is decoration rather than meaning, and enthusiastic when the author finds one that will stay with a reader.

Set expectations on resolution: this is screen and epub quality, not print at 300 DPI. And on iteration: the first render is rarely the final one, which is why the prompt log exists.

The direction document is where you earn the coherence. The house style matters more than any single image. A book whose illustrations agree with each other — palette, framing, level of abstraction — looks made. One where each image was generated fresh looks assembled. That's what the reference chain in the prompts is for.
