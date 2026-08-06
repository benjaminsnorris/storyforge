---
name: illustrate
description: Plan, art-direct, and embed interior illustrations for a prose book. Use when the author wants illustrations in their novel — deciding where images belong, generating art direction to render them, or bringing finished illustrations into the manuscript.
---

# Storyforge Interior Illustrations

You are art-directing the interior illustrations for a prose book. This is not the cover — the cover sells the book, and illustrations deepen it. A good illustration arrives at a beat the reader is already leaning into and shows them something the sentences could only deliver one at a time.

The flow is: **set the art direction** → **decide where** → **record what changes** → **audit the prose against it** → **stage the sequence** → **art-direct each one** → **package the handoff** → the author renders the anchor batch, then the rest → **ingest and embed** → **review the sequence** → produce.

The handoff is two phases, and the order is the point: a small **anchor batch** is rendered and approved first, so the long run that follows references four real images instead of four descriptions.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory (this skill's directory → `skills/` → plugin root). Scripts live at `scripts/` and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

**Do not open image files.** Never run `open`, `xdg-open`, or any command to display or preview an illustration. The author may be working over SSH or already have the project open. Report the path and let them look however they prefer.

## Step 1: Read Project State

1. **`storyforge.yaml`** — title, genre, medium, coaching level, `production.cover_image`.
   - If `project.medium` is `graphic-novel`, **stop**. GN projects have their own page pipeline: `storyforge elaborate --stage page-architecture` and `--stage prompts`. Tell the author that and route them there.
2. **`reference/canon/`** — the reference tier that governs every illustration; read it before anything else about the art. Three book-level files at the root (`visual-foundation.md`, `visual-vocabulary.md`, `content-limits.md`) plus one per-entity file per character/creature/location/prop under `characters/`, `locations/`, `motifs/`. If `reference/illustration-direction.md` still exists too, it's the pre-canon document one project hand-edited from — read it only to spot a transcription slip against the canon anchors (`illus_direction_anchor_mismatch` reports these in `cleanup`); it is not itself an input to a prompt anymore.
3. **`reference/illustration-plan.csv`** — the plan, if one exists. Together with the reference tier, this tells you which mode you are in.
4. **`reference/visual-state.csv`** — the visual-state transition log, if one exists: what changes on schedule, as opposed to the canon tier for what must never change. `working/illustration-audit-provenance.csv` records which scenes the contradiction audit has read.
5. **Structural context** — read what exists:
   - `reference/story-summary.md` — logline, synopsis, act shape, theme
   - `reference/spine.csv` — the irreducible events
   - `reference/architecture.csv` — turning points, value shifts
   - `reference/scene-intent.csv` — emotional arcs
   - `reference/motif-taxonomy.csv` — the concrete recurring vehicles
   - `reference/themes.csv` — what the story argues
   - `reference/chapter-map.csv` — distribution
6. **Visual context** — `reference/character-bible.md`, `reference/world-bible.md`, `reference/voice-guide.md`.
7. **Existing art** — `manuscript/assets/` for the cover and `cover-prompt.md` (the best available statement of the book's visual register), and `manuscript/assets/illustrations/` for anything already ingested.

## Step 2: Determine Mode

| State | Mode |
|-------|------|
| Reference tier missing or incomplete | **Direct** — set the book's visual contract first |
| Reference tier complete, no plan | **Plan** — decide where illustrations belong |
| Plan exists, no state matrix | **State** — record what changes on schedule |
| Matrix exists, audit unrun or stale | **Audit** — read the prose against the matrix |
| Plan exists, rows with no `treatment` | **Sequence** — stage the set so it doesn't converge |
| Plan exists, rows at `status=planned` | **Art-direct** — write the prompts |
| Prompts written, no packet or packet stale | **Package** — assemble the handoff bundle |
| Packet built, any anchor-batch row not ingested, or ingested from canon since rewritten | **Anchor** — render and approve those N first |
| Every anchor-batch row ingested from the current canon | **Churn** — hand the packet over |
| Non-anchor files on disk | **Ingest** — bring them in and embed |
| An illustration isn't working | **Revise** — supersede and re-direct |
| All or most are rendered | **Review** — check the sequence for continuity drift |
| Author asks how things stand | **Diagnose** — `storyforge illustrate --diagnose` |

Announce the mode you're in and why before doing anything.

**The flags are output, not vocabulary the author has to learn.** Detect the rung, say which mode that puts them in, and offer the command. `storyforge illustrate --diagnose` reports every rung in this table — the reference tier, the state matrix, the audit, the sequence staging, the packet, and which anchor-batch rows still need a render — so when you are unsure, run it and read the answer rather than guessing from file mtimes.

---

## Mode: Direct

Before deciding where illustrations go, settle what they look like. `reference/canon/` is the book's visual contract — a canon file per concern, authored once, that every illustration inherits.

This is the highest-leverage artifact in the flow. A per-illustration prompt can be re-rolled for a few cents. A book whose fifteen images disagree with each other has to be re-rendered wholesale.

> **Option A: Run it here**
> I'll write the canon files in this conversation.
>
> **Option B: Run it yourself**
> ```bash
> cd [project_dir] && [plugin_path]/storyforge illustrate --direction
> ```

Wait for the author's choice; if Option B, give them the command and stop. `--direction` never overwrites a canon file that already exists — a rendered illustration may already depend on its exact text — so running it again after the first pass only fills what's still missing. In `full` coaching, the three book-level files below are drafted by one Opus synthesis call, so it costs real money; per-entity anchor files are always written as TODO stubs for you (or, later, the model proposing a new one while it writes a prompt) to fill in by hand.

Three book-level files, at the root of `reference/canon/`:

- **`visual-foundation.md`** — medium, rendering style, audience, in a sentence or two. "Full-color cinematic photorealism for a read-aloud fantasy novel, ages 6–8" tells an image model more than three paragraphs of adjectives.
- **`visual-vocabulary.md`** — the rules that repeat. Palette split by faction or mood, camera height, depth of field, materials rendered naturalistically, the standing no-text rule.
- **`content-limits.md`** — what the art must never do. Intensity ceilings, imagery to stay away from, anything the audience age rules out. State these as limits, not as prompt text.

Plus one **continuity anchor** file per thing that must look the same every time, one file per entity: `reference/canon/characters/{id}.md` for characters and creatures, `locations/{id}.md`, `motifs/{id}.md` for signature props. `--direction` proposes a stub for every row already in `characters.csv` and `locations.csv`; add creatures and props by hand (each anchor's filename stem must match its registry row's `id`, or `cleanup` reports `canon_missing_registry_entry`). Each anchor's `## Embeddable block` is reused **verbatim** in every prompt that features it.

### Anchors are inputs, not residue

An anchor works only because every prompt uses the identical string. So it has to be written *before* the art, not derived from whichever illustration happened to be rendered first.

Put measurable facts in them — height in centimeters, age in years, exact hair and eye color, specific garments. Those are precisely what drifts between separately generated images, and stating them is the only defence.

**Do not sub-head the anchor with `##`.** A `##` line inside `## Embeddable block` *ends* the section, so everything below it silently drops out of the string every prompt embeds — including a second `## Embeddable block` pasted in by accident. Use `###` if you want structure inside the anchor; `cleanup` reports the mistake as `canon_truncated_embeddable_block`, but by then the prompts may already be written.

**Never revise an anchor a rendered illustration already used.** If it's wrong, the fix is re-rendering from the corrected anchor, not editing the string and leaving the old art in place. If the model proposes a new anchor while writing a prompt, the command writes it as a new canon file for you to review — it does not create the registry row, so `cleanup` will flag the gap rather than the model's guess becoming canonical unreviewed.

`--direction` reports book-level files left empty or still holding TODO text, and `--prompts` warns before it spends anything — a scaffold fed to an image model as though it were direction is worse than no canon file at all.

---

## Mode: Plan

Deciding *where* illustrations belong is the part that matters most. An illustration in the wrong place is worse than no illustration — it reads as a mistake the author made on purpose.

### How many

Propose a count rather than assuming one. Roughly one illustration every two to three chapters reads as designed; more than that and the art starts competing with the prose. The command's pre-pass recommends a count from chapter and spine-event counts — start there and discuss.

### What earns an illustration

Work through these with the author (or decide, in `full` coaching):

- **The image does something the prose cannot.** A composition, a scale, a spatial relationship. Sentences deliver those sequentially; a picture holds them at once.
- **The beat is already carrying weight.** A turning point, a value shift, the third appearance of a motif the book has been building. The image inherits that accumulated meaning for free.
- **It doesn't spoil the facing page.** A reader sees an illustration before they read past it, so an image that reveals what the next paragraph is about to reveal has broken the scene. Generation now defends this rather than leaving it to placement judgment: `--prompts` splits the scene at the illustration's reading position, sends the following paragraphs as prose the image must not contain, and writes the next sentence into the prompt file's `## Accept only if` block so a bad render is caught in review.

  Three things are still yours. The **choice** of anchor: placing an image immediately in front of the scene's most vivid sentence puts the guard under maximum pressure, and the beat two paragraphs later is usually the better image anyway. An illustration at a scene's **open or close** on a scene where something *changes* cannot know which side of that change it is on — `state_mid_scene_change` says so per row, and a `state_override` on the plan row is the answer. And a row whose **anchor does not resolve** gets no guard at all: the split is unknown, so there is no forbidden block and no quoted sentence, only a note saying the check could not be made. `--prompts` warns before it spends, grouped by cause; `--diagnose` names those rows too.

  A `scene_open` opener is a deliberate exception to all of this — its job *is* to establish the prose that follows it, so the following paragraphs are what it should depict and nothing about it is treated as a spoiler.
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

## Mode: Sequence

Before writing any prompts, stage the set.

Each illustration is generated by a separate call that cannot see the others, so left alone they converge. On the last real book, four of twenty images were the same shot of the same two figures at the same distance — every prompt individually good, the set monotonous, and the emotional peak reading as a lull because three of the last four images looked alike.

> **Option A: Run it here**
> I'll stage the sequence in this conversation. This requires unsetting CLAUDECODE.
>
> **Option B: Run it yourself**
> ```bash
> cd [project_dir] && [plugin_path]/storyforge illustrate --sequence
> ```

**One cheap call** for the whole set — it reads beats, layouts and registers, never the scene prose, because this pass is about how the set is staged and not about any single image. It writes a `treatment` per row: camera distance, camera height, time of day, how much of the frame the subject occupies, interior versus environmental.

Do **not** ask for all the prompts in one call instead. That was tried in design and rejected: one failure becomes twenty, a long response gets terser and more formulaic toward the end so the last illustrations get the worst prompts, and one malformed heading eats several prompts.

Two things to tell the author:

- **A `treatment` they wrote is never overwritten.** The model stages the others around it. If a proposal disagrees with the author's, the log says so and keeps theirs.
- **Repeated treatments are reported.** Variety is the entire point, so two rows with the same staging defeat the pass while both prompts still look fine. If the echo is deliberate, say so in the treatment ("deliberate echo of `x`, from the opposite side") rather than leaving it looking like an accident.

`treatment` becomes an input to `--prompts` and is rendered in the packet's entry, so stage before you prompt. If you prompt first, every prompt file is built from staging that did not exist yet.

---

## Mode: Art-direct

Turn planned rows into prompts the author can paste into an image model.

> **Option A: Run it here**
> I'll write the art direction in this conversation.
>
> **Option B: Run it yourself**
> ```bash
> cd [project_dir] && [plugin_path]/storyforge illustrate --prompts
> ```

Wait for the author's choice. This is **one creative API call per illustration**, so it is the most expensive phase in the flow — a fifteen-illustration book means fifteen calls. The calls run five at a time, so wall-clock is roughly a fifth of the call count, not the sum; every write (canon stubs, prompt files, plan rows) still happens sequentially in plan order afterwards.

**Author the anchors before you prompt.** Because every request is built before the first call goes out, a canon stub the model proposes mid-run is written *after* all of them — it does not reach the other prompts in the same run. So if a character has no anchor and twenty rows are prompted at once, all twenty invent her independently: the first stub wins the canon file and the other nineteen prompt files describe her differently, which is exactly the likeness drift the identical-anchor-string rule exists to prevent. Anchors are inputs to the art, not residue from it. The command warns up front, naming the rows and the missing ids, *before* spending anything — take that warning seriously: run `--direction`, fill the new canon files, then prompt. If stubs do get written mid-run, the log names the re-run (`--prompts --ids <the other ids>`) that rebuilds the prompts which missed them.

Add `--ids one,two` to limit it to specific illustrations, or to re-prompt ones already written after editing their plan row.

**Re-prompting never un-publishes finished art.** `prompt_file` is always written, but `status` only moves forward: `planned` / `prompted` / `superseded` advance to `prompted`, while a `rendered` or `ingested` row **keeps its status** and the command logs that a re-render is pending. That matters because `ingested` is what every consumer gates on — Bookshelf publishing, the epub, the PDF, and the web book — so a demotion silently drops the illustration from the build while leaving the file on disk. Naming a `superseded` row in `--ids` revives it as far as `prompted`; render and `--ingest` bring it the rest of the way.

Add `--no-prior-refs` to reference the cover only. Use it when re-rendering a set whose existing art no longer matches the canon — see "The reference chain" below.

This writes `reference/illustration-prompts/{id}.md` per illustration, and sets `status=prompted`. Each prompt file carries the reference list, the prompt body (Scene / Subject / Important details / Use case), a deterministic Constraints block, an **Accept only if** block, and a log table.

**The resolved visual state goes into the request, and it outranks the anchors.** An anchor necessarily describes an entity across the whole book — "navy pajamas on the first two nights, and from a04 onward a rust-red jacket" — so no anchor can tell a generation call which night *this* image is. That is what `reference/visual-state.csv` answers, resolved forward to the row's scene with the plan row's `state_override` laid on top: the same resolution the handoff packet renders, so a prompt file and a packet entry built from one row cannot describe different costumes. It is stated as a requirement rather than context because an emphatic anchor clause actively pulls the other way — "the jacket is how the reader finds him in a dark image" is exactly why a dark night-one image came back in the night-two coat.

The state also lands twice in the prompt *file*, the way the orientation directive does: as a Constraints bullet the image model reads, and in `## Accept only if` — the per-image acceptance lines, checked against the row rather than against the render you happen to like. Hand-editing a prompt body to fix a costume works once and makes the file no longer reproducible from the plan; fix the transition log or the row's `state_override` instead and re-run.

If an entity the row names has no stated state at that scene, the command says so **before** the calls go out, grouped by finding rather than repeated per row, with a closing count of how many rows carry no resolved state at all. That is the free moment to add the transition. `--prompts --dry-run` reports the same thing and spends nothing.

A row whose state does not resolve still gets a prompt — the file says so, in Constraints and in `## Accept only if`, rather than quietly omitting the line. Take that at face value: it means the costume and lighting in that prompt are the model's inference, not a read of the matrix.

**`## Accept only if` is not part of the prompt.** It is marked so, and it sits below the pasted region — it is what you check the render against, and via `contrast` it can name another illustration by id.

**An illustration id must never reach the image model, and two places enforce that** (#305). The model cannot see your other images, so naming one is an instruction it can only guess at. The source prompt file keeps ids because it is author-facing and never uploaded; the packet's `image-prompts/<id>.md` is uploaded whole, so it carries an id-free phrasing instead — "the illustration immediately before it". A comparison *you* wrote that names an id (`darker than \`LF-05\``) cannot be rewritten without losing its meaning, so it is withheld from the upload entirely and listed in `illustrations.md` under **Check against its neighbours**: it is a check on the render, not a direction for it. If you find an id in a file you are about to upload, that is a bug — a test asserts no upload file names any illustration but its own.

### What the prompts encode

These come from lived iteration (benjaminsnorris/ashes PR #9, tracked as #260 and #263). Do not paraphrase them away when you edit a prompt by hand:

1. **Five-section template** — Scene / Subject / Important details / Use case / Constraints. Structure beats brevity. The model writes the first four; the **Constraints section is appended deterministically** (orientation, the no-text rule, reference fidelity, anchor consistency) and is deliberately not requested from the model. Asking for both produced a file with `## Constraints` and a nested `### Constraints` saying different things.
2. **Reference images carry style and likeness**, so prompt prose stays short (~250–400 words). The references are the cover art plus prior ingested illustrations — that chain is what keeps a book's interior art visually of a piece instead of fifteen unrelated pictures. See "The reference chain" for when a prior illustration is *excluded*.
3. **The continuity anchor is the identical string every time.** Anchors are canon files under `reference/canon/characters/`, `locations/`, `motifs/` — each file's `## Embeddable block` *is* the anchor. Only the anchors an illustration actually shows are sent, narrowed by matching its `canon_refs` against each anchor's `canon_id` (the canon file's slug, not a display name). If `canon_refs` is empty, or if none of its entries match a `canon_id`, the full set is sent instead — an unfiltered anchor set is a smaller failure than a missing one, but it means a plan row still carrying a pre-canon display name (e.g. "Great Lamp" instead of "great-lamp") sends the whole cast at full token cost, with a WARNING rather than narrowing correctly. Never revise an anchor a rendered illustration already used — likeness continuity depends on the string being byte-identical.
   The anchor is *labeled* in the prompt with a display name — `display_name:` in the canon file's frontmatter, else the registry's `name` for that id, else the title-cased slug (and the command names the ids it had to guess at). `canon_id` stays the matching key; only the label changes, because a slug-labeled anchor gets the slug echoed back in the model's prose ("kneeling are leo — ten, warm light-brown skin…").
4. **Positive framing for content, not negation.** Negated content keywords leak into the image. "A bare sill," not "no clutter on the sill." Orientation and the no-text rule are the two exceptions about form — both are failure modes positive phrasing has not been observed to prevent — and `absent` plus the colour logic are the two about content. Four in total; do not widen the list.
5. **Explicit orientation, in two places.** GPT Image 2 returns landscape unless told otherwise. Aspect comes from `layout` first — a `double_page` spread is landscape because that is a fact about the page — then from the row's `composition` field, which can say `landscape` or `square`. Portrait otherwise.
6. **The scene arrives split at the illustration's reading position** (#308). The model sees the prose the reader has read, labeled as such, and the next few paragraphs in a separate block it must steer away from *silently* — not name, not even to exclude, because a negated phrase in an image prompt puts the thing in the picture. Sent rather than omitted, because a model that cannot see the next page still invents toward it: the beat the anchor was placed in front of is the one the scene has been building to, and "a beat the reader is already leaning into" is what the planning guidance asks for. Before this the request was a window straddling the anchor with nothing marking the split, and three of three rows checked by hand on a real book described the beat immediately after it.

   What the model is told depends on where the image sits. A `scene_open` opener is asked to illustrate the prose it opens, with no forbidden block — an opener establishes what follows, and forbidding it told the model to avoid the only description of the image it was drawing. An image at a scene's end gets no forbidden block either, there being nothing after it. And if the anchor does not resolve, the request says the position is unknown and that the prose it carries is the scene's *opening*, not the lead-up — the command warns before the fan-out, grouped by cause, and that row's `## Accept only if` says the check could not be made rather than implying it passed.

The whole book-level direction — the three root canon files — goes into every prompt too, which is why the command warns before it spends anything when the reference tier is incomplete: a canon file that's simply absent tells you to run `--direction`, one that exists but is still a TODO placeholder tells you to edit it directly (re-running `--direction` is a no-op once the file exists). Either way, without it the prompts carry no house style, and the images won't look like they belong to one book.

Plus: no text, no letters, no words, no typography. Image models render text unreliably, and an illustration doesn't need any.

### The reference chain

**The cover artwork is the first reference in every list, and the only one under `--no-prior-refs`** — so which file it is matters more than any other single choice in this phase. Resolution order:

1. `production.cover_artwork` in `storyforge.yaml` — set this when the book holds several cover variations and only one is the selected art. Without it, the convention filename wins silently even when every other consumer points elsewhere, which is how twenty interior prompts once inherited a cover the author had explicitly rejected.
2. `manuscript/assets/cover-illustration.{png,jpg,jpeg,webp}` — the convention, so existing projects resolve as before.

It is the *artwork*, deliberately not `production.cover_image`: that key names the file that ships, which on most books is the composite with the title typeset into the raster. Feeding baked-in lettering to a prompt whose own constraints say "no text, no letters, no words" is a wasted generation.

The command names the resolved file **once per run, before any call is made**, with its symlink target if it is a symlink — and `--diagnose` and `--prompts --dry-run` report it too, so you never have to start a paid run to find out which cover is about to direct it.

If `production.cover_artwork` names a file that does not exist, `--prompts` **refuses** rather than falling back to the convention and spending the run. A path that isn't there is unambiguous — you meant that path — where staleness is a judgment call. Fix the path, or remove the key to use the convention deliberately. It is also staleness-checked on the same footing as a prior render — an mtime older than the newest `canon_updated` is a WARNING — but never *excluded* for it, because dropping it would leave the highest-stakes run with no style signal at all. If you see that warning, re-render the cover artwork or point `production.cover_artwork` at art that postdates the canon.

Two more cases get their own warning, and both mean the check did not run rather than that it passed: no canon file carries a parseable `canon_updated`, and the file's modification time could not be read. Unknown freshness is not freshness. A file an image model cannot read — an SVG compositing source, say — is warned about and still listed, because the one reference that is sometimes the only one is never dropped silently.

A prior illustration is used as a style reference only if it was ingested **on or after** the newest `canon_updated` date in `reference/canon/`. Art rendered before the canon that now governs it was directed by rules that no longer apply, and feeding it back in teaches the new render exactly the drift the canon was rewritten to remove — which is how a whole set inherits a mistake through the visual key.

- An **empty `ingested_at`** counts as pre-canon. The column postdates the plan schema, so "unknown" means the render predates even the bookkeeping. A plan CSV with no `ingested_at` column at all is legal; the next write adds it, and every ingest stamps today's date.
- Every exclusion is a WARNING naming the file and the reason. Silent staleness is what made this hard to notice — the prompts looked fine, they just pointed at the wrong images.
- With **no canon dates at all**, nothing can be judged stale and the chain is unfiltered (said plainly in the log).
- `--no-prior-refs` is the explicit rebuild switch: cover only, nothing inherited.

When the chain ends up cover-only or empty, the log says so rather than quietly emitting a short reference list.

### Author reviews before spending credits

Present the prompt to the author before they render. This is their money and their book. Common adjustments: tone, tightness of crop, level of abstraction, how much of the scene to show.

Read the `## Accept only if` block back to them — it is the per-image check list, it is never pasted into the image model, and its spoiler line quotes the next sentence the reader reads. If a render shows that sentence, it needs re-rendering, not a re-prompt. For prompts written before this guard existed, `--diagnose` reports `prompt_spoils_unread` per row: art direction whose prose shares distinctive language with the part of the scene the reader has not read yet.

Tell them to record each attempt in the prompt file's log table. The prompt plus its settings is the reproducible seed for the art — it is the only way back to a result they liked two weeks ago.

Commit the prompt files.

---

## Mode: Package

Assemble the handoff bundle. This is what the author (or a long-running generation session) actually works from.

```bash
[plugin_path]/storyforge illustrate --package
```

_(No API calls — assembly only, safe to run here without asking.)_

Why a bundle rather than fifteen prompt pastes: hyper-detailed standalone prompts underperform in practice, and a session working from shared reference material does better. Graphic-novel mode reached the same conclusion first when per-panel generation failed. So the shared files carry the house style, the anchors, the state matrix, and every acceptance check that is the same for every image — uploaded **once**, at the top of the session.

```
manuscript/illustration-packet/
  README.md          # the runbook, the two phases, and what the packet cannot tell you
  canon.md           # the reference tier — house style plus every continuity anchor
  visual-state.md    # scene x entity: what is visibly true when
  illustrations.md   # the index the author works down, and everything addressed to them
  acceptance.md      # the checks identical across the set
  image-prompts/     # one upload file per illustration
```

**The session is three steps, and they are in README.** Upload the reference images it lists (project-relative paths, uploaded once). Upload `canon.md`. Then, **one illustration at a time**, upload `image-prompts/<id>.md` and ask for the image.

**One at a time is not fussiness.** A single small file is read into context whole; twenty at once is the case where the model retrieves and paraphrases instead — and a paraphrased continuity anchor is not an anchor, because the entire mechanism is the *identical string* arriving in every prompt that features that entity.

**Everything in an image prompt is for the model. Everything for the author is in `illustrations.md`.** That split is the point of the file layout, and it matters because the author uploads the file rather than pasting a region out of it: anything in it reaches the image model. So `image-prompts/<id>.md` carries the title line, the model-authored body, and a Constraints block — no staleness notes, no provenance, no checklists. Before uploading a row's prompt, read that row in `illustrations.md`.

`illustrations.md` is an index table — reading order, scene, aspect, art state, staging, beat — followed by a **Before you upload** section carrying only the rows that have something to say. Read those aloud to the author:

- **Re-render** — the row is `ingested`, and its art predates the canon now governing it.
- **Art direction** — the body is thinner than it looks (no prompt file, an unreadable one, or one whose own `Constraints` heading truncated it).
- **Uploaded references** — this row's own earlier render is among the images uploaded at the top of the session. It is a re-render, not a match.
- **No visual state resolved** — the costume and lighting in that prompt are the model's inference, not a read of the book's schedule.

**The packet is a render. Never hand-edit it.** It is regenerated wholesale on every run, so an edit is lost and never reaches the plan. Changes belong in `reference/illustration-plan.csv`, `reference/visual-state.csv`, `reference/canon/`, or the prompt bodies in `reference/illustration-prompts/`. `cleanup` reports a packet older than any of those (`illus_packet_stale`) and an anchor copy that no longer matches its canon file (`illus_anchor_copy_drift`) — for both, the fix is to regenerate.

**Anchors in the packet are byte-identical to their canon files**, wrapped in `<!-- canon-embed: id -->` markers so that can be checked mechanically. Likeness continuity across separately generated images is nothing but the same string arriving every time, so if the packet's wording is the one you want, put it in the canon file and regenerate — do not edit the packet, and never revise an anchor a rendered illustration already used.

**Read the README's "What this packet cannot tell you" section aloud to the author.** It lists every gap in the data the packet was built from: a row with no beat or no subject, a `canon_refs` entry with no canon file, an entity whose visual state nobody stated at that scene, a book-level canon file still holding TODO text, rows whose art direction was never written, and whether the contradiction audit has ever run. Those are the places the packet is thinner than it looks, and the moment to fix them is before a generation session spends money on them.

**Reference images are never copied** — README lists project-relative paths and the author uploads from disk. A copy would be a second thing to invalidate on every re-render, and it would be the one part of the bundle that does not travel to another machine. README's upload step also carries a **Read this before you upload** block whenever the list is shorter than the ingested art suggests: renders excluded as pre-canon, a `--no-prior-refs` build, or the cap. A cover-only list is not the same thing as having nothing to reference, and uploading the cover alone generates the rest of the set with no likeness reference.

**The upload list leads with the anchor batch.** The four approved images are ranked ahead of the rest and labeled with their slot (`anchor batch: darkest`), so the four renders phase 1 exists to sign off are the four the churn actually references. The cap is four *prior illustrations* and the cover is additive, so a full batch fits.

Three things to read out loud when the notes carry them:

- **A batch member whose art cannot be used**, named with its slot. Either it predates the current canon — being approved does not make it safe to reference, so re-render it — or the plan says `ingested` and the file is not on disk, which the batch table cannot see and still reports as `Rendered: yes`. Either way the chain is not what the author signed off on, and fixing it beats generating against the substitutes.
- **A count instead of a reassurance.** "N of M anchor-batch image(s) are in this list" means the batch is not all there; only a complete one says "what is listed is what was approved". Do not read the shorter form as the longer one.
- **`, guessed` on a slot label.** Nothing populates `register` on most projects, so the darkest and brightest slots fall back to the first and last illustration in reading order. A guessed extreme is a decision waiting on the author, not one already made — and a prompt file carries no batch table to check it against.

**The Constraints block carries the state in force now, not the prompt file's memory of it.** The body comes from `reference/illustration-prompts/<id>.md`; the state, `absent`, and `contrast` lines are re-derived from the plan and the transition log every time `--package` runs. So a packet built after you edited `reference/visual-state.csv` is correct even though the prompt body's own file is not — there is no `prompt_stale`. If you want that file right too, re-run `--prompts --ids <id>`.

**A row with no prompt file still gets an upload file, and says so.** Its body is assembled from the plan row alone — beat, subject, composition — with none of the scene-specific prose `--prompts` writes. `illustrations.md` says which rows those are and README aggregates the count. Tell the author plainly: it reads like a complete prompt and it is a thinner one. Run `--prompts --ids <those ids>` first if the image matters.

The index's `Art` column reads `done` for a row whose art exists and follows the current canon, `to render` for one that does not have art yet, and **`re-render`** for a row that still says `ingested` but whose art predates the canon now governing it. Say that third one out loud: the art exists and ships, and it was directed by canon that has since been rewritten, so it is not a usable reference for anything rendered now. Its `**Re-render.**` note says why. **Never fix this by demoting `status`** — that is what an author reaches for, and it drops the illustration from Bookshelf while the epub, the PDF, and the web book keep shipping it, so the editions disagree about a book nobody re-rendered. Re-render it and `--ingest` the new file; the status is already right.

If `--diagnose` says *no file under `reference/canon/` carries a parseable `canon_updated`*, treat every "current" signal in the packet as unverified rather than confirmed: nothing can be shown to predate a canon with no date, so the batch table's `yes` means only "nothing could show otherwise". Set `canon_updated: YYYY-MM-DD` in the canon files you have edited and re-run before trusting a hand-over.

### Two columns you write by hand

`absent` and `contrast` are plan columns nothing populates automatically — no command proposes them — but `write_plan` preserves any column an author adds, and the packet reads both:

- **`absent`** — named entities that must **not** appear in this image. It is one of only two *content* exceptions to positive framing (the other is the colour logic; the orientation directive and the no-text rule are exceptions about form), and it exists because a positively-framed instruction did not stop a real book rendering a character who was elsewhere in the story at that point. Name entities, not qualities: "Ember. A second Great Lamp."
- **`contrast`** — anything you want said about how this image must differ from its neighbours, beyond the register and predecessor sentence the packet derives for you.

Offer to add them when the author says an image keeps coming back with something that should not be in it.

---

## Mode: Anchor

The packet is built and the anchor batch is not rendered yet. This is phase one of the handoff, and skipping it is expensive: a long generation run that references *descriptions* drifts, and one that references four approved images does not.

`--diagnose` and the packet's README both name the batch. Four slots:

1. **Establisher** — the visual key: the illustration whose `canon_refs` cover the most ground, earliest.
2. **Darkest register** — the first row marked `register=darkest`.
3. **Brightest register** — the first row marked `register=brightest`.
4. **Later-state exemplar** — the illustration that shows the most entities in a state later than their first, earliest. It locks a changed wardrobe or a broken object before the churn needs one.

The batch is **derived, never stored**, so it cannot disagree with the plan.

**`Rendered: yes` is a claim about the current canon, not about `status`.** A slot reading `re-render` has art that predates the newest `canon_updated`, so phase 1 is not done for it — and `--diagnose` will not say "ready to hand over" while any slot is in that state. Rebuilding a book's canon after the art was made puts the *whole* set in this position; that is normal, and the right response is to re-render the batch first, exactly as if nothing had been made yet, because everything after it references these four.

**Take the disclosures seriously.** Nothing populates `register` automatically, so on most projects the darkest and brightest slots are *guesses* — the first and last illustration in reading order — and the batch says so in both the log and the README. A silent guess about which image is the darkest in the book is how an author finds out at image twenty that nothing in the book is. If the author knows which images are the extremes, have them mark `register` and re-run `--package`. Same for an unfilled later-state slot: either the book really has no later state to lock, or `reference/visual-state.csv` is thinner than the story.

Tell the author to render those, look at them together as a set, and only then `--ingest` them. Approving the batch is an authorial act — the rest of the book inherits it.

Then re-run `--package`, so the entries after them list the newly ingested images as references.

---

## Mode: Churn

Every anchor-batch row is ingested. Hand the packet over.

Point the author (or the generation session) at `manuscript/illustration-packet/README.md` and let them work `illustrations.md` top to bottom: read `canon.md` once and keep it in context, upload the reference images and `canon.md` once at the top, then upload `image-prompts/<id>.md` one row at a time, generating and checking each against `acceptance.md` before accepting it.

Tell them to re-run `--ingest` and `--package` in batches rather than at the very end. Each ingest adds a reference image for the illustrations after it, and a re-roll caught at image five costs one render while the same drift caught at image fifteen costs ten.

---

## Mode: Ingest

The author has rendered files. Bring them in.

```bash
[plugin_path]/storyforge illustrate --ingest path/to/renders/
```

_(No API calls — safe to run here without asking.)_

Files are matched to plan rows **by filename stem** — `lantern-vigil.png` matches the row with id `lantern-vigil`. A file matching nothing is reported and skipped, never guessed at. If the author's filenames don't match, have them rename, or ingest one file at a time.

Ingest copies each file to `manuscript/assets/illustrations/{id}{.ext}`, keeping the source extension (png, jpg, jpeg, or webp), records `sha256` / `width` / `height` / `ingested_at` (today's date), sets `status=ingested`, and then embeds the marker in the scene file. The `ingested_at` stamp is what lets a later `--prompts` run tell a render directed by the current canon from one that predates it.

A truncated file is refused before anything is written — an aborted render download leaves a header-valid stub whose dimensions parse fine, and overwriting good art with it is unrecoverable. A legitimate replacement is logged with both shapes.

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
2. Run `--embed`, which removes the markers of superseded rows. A superseded illustration also stops rendering into the epub, PDF, and web book even if its file is still on disk.
3. Add a fresh row with a new id, or re-prompt the existing one with `--ids` — naming a superseded row explicitly revives it to `prompted`, so it is waiting on a render rather than retired. (A bulk `--prompts` with no `--ids` never touches a superseded row.)
4. Consider `--no-prior-refs`, or hardening the canon first: a re-render whose references are the art you are replacing inherits the problem you are trying to fix.

Keep the superseded row. It records what was tried and why it didn't land, which is exactly what you want when the third attempt is also not working.

---

## Mode: State

`reference/canon/` says what must **never** change. Nothing in the flow said what changes **on schedule** — wardrobe by chapter, a lamp lit or dark, how many village lights are still burning. Four of ten real findings on a real illustrated book traced to that gap.

`reference/visual-state.csv` is a **sparse transition log**. A row records the moment a tracked entity's visible state changes; the state persists forward until the next row for that entity, so the state at any scene is a forward walk.

Three things about it are non-obvious and each has a test pinning it:

- **A transition takes effect at its own scene, not after it.** If a character arrives dressed for travel in the scene where the journey begins, the transition is keyed to *that* scene.
- **One track per independently-changing aspect, not one per entity.** `nora-clothing`, not `nora` — clothing and injury change on different schedules, and a single track would force restating one to change the other. The convention is `{canon_id}-{aspect}` where an entity has several tracks and a bare `canon_id` where it has one. A bare `canon_refs` of `nora` on a plan row is satisfied by any `nora-*` track.
- **A state true in one image only is not a transition.** A tear-streaked face, arms raised against a light — those go in `state_override` on the plan row, because a pure log would have to record a change and then a change back.

Every row needs an `evidence` quote: a short verbatim phrase from `from_scene`'s prose that establishes the state. That is what makes the row checkable against the manuscript later. A state the prose does not establish is a state an illustration would be inventing.

> **Option A: Run it here**
> I'll propose the transitions in this conversation. This requires unsetting CLAUDECODE.
>
> **Option B: Run it yourself**
> ```bash
> cd [project_dir] && [plugin_path]/storyforge illustrate --state
> ```

Existing rows are **never revised** — a transition the author wrote is an authorial decision about the book. Proposals that collide with one on `(entity, from_scene)` are discarded and reported, as is any proposal naming a scene that is not active in `scenes.csv`: that row is the model's, not the author's, so nothing protects it. A model that proposes nothing at all is answering, not failing — the run says so and writes nothing.

---

## Mode: Audit

Once the matrix exists, read the prose against it before any art is paid for.

> **Option A: Run it here**
> I'll run the contradiction pass in this conversation. This requires unsetting CLAUDECODE.
>
> **Option B: Run it yourself**
> ```bash
> cd [project_dir] && [plugin_path]/storyforge illustrate --audit
> ```

Read-only with respect to the prose and the log. Writes `working/illustration-contradictions.md` and `working/illustration-audit-provenance.csv`.

**Why a model is needed here at all**, which is worth explaining to the author: two transitions never disagree with each other, because things are allowed to change. Village lights dark at chapter ten and four still burning at chapter thirteen is a story, not an error. The contradiction is a scene *between* them asserting a state the span cannot support. Only reading prose against the resolved matrix finds it.

A deterministic pre-pass runs first and narrows the read to the scenes that mention a tracked entity inside its span. When the pre-pass finds no problems **and** no candidate scenes, no model is called and the report says so — a clean report that skipped the pass is not the same as a clean pass.

**Read the report's Coverage section before you trust its findings.** It names every gap: scenes with no prose yet, scenes long enough that only part was sent to the model, and scenes that are drafted and active in `scenes.csv` but absent from `reference/chapter-map.csv` — those have no reading position, so nothing in this pass ever looks at them. Any gap downgrades the result to "None found in the prose that was read". If the report names unexamined scenes, add them to the chapter map and re-run before believing anything.

**`--audit` always exits 0 when it produces a report, even over a broken log.** It is a report, not a gate — `--diagnose` and `storyforge validate` are the gates, and they exit 1 on the same finding. So if the report's Deterministic findings section contains `state_unknown_scene`, the log is broken: that transition names a scene that does not exist, never applies, and every scene after it resolves to the wrong state — which means the contradiction pass read the prose against a matrix that is wrong, and its conclusions are unreliable until you fix it. Tell the author that plainly. A zero exit code from `--audit` is not a pass.

A contradiction is usually a **missing transition**, not bad prose: the book changed something the log never recorded. Where the prose is wrong instead, fix the prose — the audit records a digest per scene it read, so a revised scene reports as stale on the next `--diagnose`.

Never revise a transition an already-rendered illustration used. Correct the log and re-render from the corrected state.

---

## Mode: Review

Once most illustrations are rendered, check the sequence **as a set**.

```bash
[plugin_path]/storyforge illustrate --review
```

_(No API calls — safe to run here without asking.)_

Writes `working/illustration-sequence-review.md`: cross-sequence checks, the anchors to check each image against, the content limits, and the render order with what's done and what's pending.

This catches what nothing else can. Per-illustration validation passes on images that are individually fine and collectively inconsistent — a character an inch taller in image nine, a location whose layout quietly rearranged, light that brightens where the story darkens. Each render looks correct on its own; only the set shows the drift.

Review **before the set is complete**. Every later illustration references the earlier ones, so drift caught at image five costs one re-render and drift caught at image fifteen costs ten.

When you find drift, fix it by re-rendering from the anchor — not by patching the image and not by editing the anchor to match what was rendered. Then re-ingest and re-run `--diagnose`.

---

## Mode: Diagnose

```bash
[plugin_path]/storyforge illustrate --diagnose
```

_(No API calls — safe to run here without asking.)_

Read-only. Reports plan counts by status, what's embedded, the recommended render order with the visual key marked (and `~` on any ingested row whose art predates the current canon), what's next to render, every ingested illustration that needs re-rendering because the canon moved under it, the anchor batch with every guessed slot disclosed, the visual-state rung (whether the transition log exists, how many entities it tracks, and whether the audit is unrun, current, or stale), the sequence-staging rung (how many rows carry a `treatment`), the packet rung (not built, built and current, or built and stale, plus which anchor-batch rows are still unrendered and which are ingested but canon-stale — "ready to hand over" is only said when neither is true), and every incoherence: orphan markers, missing files, files nobody claims, drifted anchors, duplicate markers, invalid layouts, a stale packet, a drifted anchor copy.

This is the gate for plan health, deliberately rather than the packet: `--package` is assembly and reports only what it could not cover, so problems with the plan itself surface here.

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

Write the canon files from the bibles, then read them back and say what you committed to and why. Propose the illustration set with conviction and argue each moment's rationale. Propose the visual-state transitions from the prose, each with its evidence quote. Stage the sequence and say what each treatment is doing for the set. Write the per-illustration art direction. Assemble the packet, read its gaps back, and name the anchor batch. Ingest and embed. You know what an image can do that prose can't — say so. If a moment the author wants would spoil a reveal, tell them plainly and offer the beat two paragraphs later instead.

### `coach`

Every canon file `--direction` writes arrives with a guiding question in its TODO block, one per file. Work through those with the author first — the visual contract is theirs to set.

Then help them find their own illustration set. The command writes a brief to `working/coaching/illustration-brief.md` with the structural findings framed as questions:

- "What's the one image someone would remember from this book?"
- "Your lantern motif pays off three times and none are illustrated — which one carries the most weight?"
- "Are the illustrations carrying the plot, the world, or the interior life?"
- "Does anything here show the reader something they haven't been told yet?"

Don't pick the moments. When the author has decided, record their choices and execute the technical work.

`--state` writes `working/coaching/visual-state-brief.md` and makes **no API call** in this mode. Deciding that a character changes clothes in chapter four is a decision about the book, not an extraction from it, so the brief asks per-entity questions instead of proposing transitions. `--audit` is unchanged at every level — it reports contradictions, it never decides anything.

`--sequence` proposes treatments but writes them to `working/coaching/illustration-sequence-brief.md` rather than to the plan, so the staging of the set stays the author's call — copying an accepted treatment into the `treatment` column is a one-line edit either way. `--package` is unchanged at every level: it is assembly, and it reports what it could not cover rather than deciding anything.

### `strict`

No creative proposals. Every canon file `--direction` writes arrives as a bare `TODO` line under the required section skeleton (`## Embeddable block`, `## Clauses`, `## Related canon`, `## Iteration history`); the author writes all of it. The command writes `working/coaching/illustration-checklist.md` — structural data and per-column requirements, nothing interpreted. `--state` writes `working/coaching/visual-state-checklist.md` plus `reference/visual-state.csv` itself (header and any existing rows, so the author has the file the checklist describes) and makes no API call. `--sequence` writes `working/coaching/illustration-sequence-checklist.md` — the sequence laid out in reading order with the five staging axes and an empty `treatment` cell per row — and makes no API call. `--package` still assembles the packet, since that is structural work. The author supplies every moment, subject, palette, composition, entity, and state. Ingest, embed, and validation are structural work and stay available; `--prompts` produces a four-section scaffold (Scene / Subject / Important details / Use case) with the author's own constraint values and empty prose sections; the Constraints block is appended deterministically.

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

- Wrote or edited canon files? Commit and push — they govern everything after them.
- Wrote or extended the plan? Commit and push.
- Wrote or extended the visual-state log? Commit and push — every later prompt reads it.
- Ran the contradiction audit? Commit the report and the provenance file, then commit each transition or prose fix separately.
- Staged the sequence? Commit and push the plan — every later prompt and the packet read `treatment`.
- Wrote prompt files? Commit and push — including any new canon anchor stubs the model proposed while writing them.
- Assembled the packet? Commit and push it. It is a render, so it belongs in the same commit as whatever it was rendered from when both moved.
- Ingested illustrations? Commit and push the files, the updated plan, and the scene files together, so the marker and the art it points at land in the same commit.
- Superseded an illustration? Commit and push.
- Ran a sequence review? Commit the checklist, then commit each drift fix separately.

```bash
git add -A && git commit -m "Illustrate: {what was done}" && git push
```

## Coaching Posture

Illustrations are an argument about what matters in the book. Fifteen of them say "these are the fifteen moments." Take that seriously — be direct when a proposed moment is decoration rather than meaning, and enthusiastic when the author finds one that will stay with a reader.

Set expectations on resolution: this is screen and epub quality, not print at 300 DPI. And on iteration: the first render is rarely the final one, which is why the prompt log exists.

The reference tier is where you earn the coherence. The house style matters more than any single image. A book whose illustrations agree with each other — palette, framing, level of abstraction — looks made. One where each image was generated fresh looks assembled. That's what the reference chain in the prompts is for.
