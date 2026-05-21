---
name: script-package
description: Assemble a graphic-novel project into an artist handoff bundle — panel script with global page numbering, visual references, chapter map, and a readme. Use when the GN author wants to package the book for an illustrator (human or AI).
---

# Storyforge Script Package — Graphic Novel Artist Handoff

You are guiding a graphic-novel author through packaging their panel scripts into a clean artist handoff bundle. This is the bridge between a folder of scene scripts and a numbered, organized delivery that a human illustrator or an AI image-generation pipeline can work from directly.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`,
templates live at `templates/`, and reference materials live at `references/`
relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Before doing anything else, orient yourself:

1. **Read `storyforge.yaml`** — title, medium, phase, coaching_level. **Critical: check `project.medium`.**
   - If `project.medium` is not `graphic-novel`, stop immediately and say:
     > "This skill is for graphic-novel projects. Your project is set to `{medium}`. Use the `produce` skill to assemble a prose book."
     Then invoke the `produce` skill instead.
2. **Read `reference/scenes.csv`** — scene IDs, statuses, page counts (target_words column holds page targets for GN projects), parts/acts, POV.
   - Note how many scenes are `drafted` (ready for handoff) versus `briefed` (not yet scripted — these will block assembly).
   - If any scenes are `briefed` but not yet scripted, surface this: "Scenes X, Y, Z are not yet scripted — they will be skipped or block assembly depending on your flags."
3. **Check for existing `reference/chapter-map.csv`** — does it exist?
   - Absent → First-Time Setup mode
   - Present → check if the author's request is an update or straight assembly
4. **Note `project.coaching_level`** — controls how proactively you propose chapter structure (see Coaching Level Behavior below).

## Step 2: Determine Mode

Based on the author's message and project state, pick one of three modes:

---

### First-Time Setup

The chapter map doesn't exist. Guide the author through creating one. **How you guide depends on coaching level** — see Coaching Level Behavior below.

**If given specific direction** (e.g., "group scenes by issue, 22 pages each"), skip analysis and execute it immediately at any coaching level.

**If no specific direction and coaching level is `full`**, proceed to Step 3: Propose Chapter Structure below.

**If coaching level is `coach`**, proceed to Step 3: Guided Analysis below.

**If coaching level is `strict`**, proceed to Step 3: Collect Breakdown below.

---

### Update Mode

The chapter map already exists. The author wants to modify it.

Possible modifications:
- **Reorder chapters** — move chapters up or down
- **Split a chapter** — divide a long chapter (e.g., split a 40-page arc into two issues)
- **Merge chapters** — combine two short chapters
- **Add/remove scenes** from a chapter
- **Rename chapters** — change issue titles
- **Update production settings** — change artist, trim size, or page format

Read the existing chapter map, make the requested changes, write the updated version, then commit and push.

After updating, ask if the author wants to run assembly now. If yes, proceed to Assembly Mode.

---

### Assembly Mode

The chapter map exists and the author wants to build the handoff bundle.

Check that the `./storyforge` runner script exists in the project. If not, tell the author to run `./storyforge init` first.

Tell the author:

> **Option A: Run it here**
> I'll launch the assembly in this conversation.
>
> **Option B: Run it yourself**
> Copy this command and run it in a separate terminal:
> ```bash
> cd {project_dir} && {plugin_path}/storyforge assemble
> ```

Available flags:
- `--dry-run` — show what would be assembled without writing files
- `--force` — bundle even if some scenes are not yet drafted

Wait for the author's choice. If Option B, provide the full command and end the skill session.

---

## Step 3: First-Time Chapter Mapping

How this step runs depends on coaching level.

### `full` — Propose Chapter Structure

Analyze the scene index and propose a chapter structure:

1. **Read all scene metadata** — IDs, titles, parts/acts, POV, page targets, status.
2. **Group scenes into chapters** using these heuristics for graphic novels:
   - Single-issue format: target 20–24 pages per chapter (standard monthly comic)
   - Graphic-novel section format: target 40–60 pages per chapter (book-style arc)
   - Natural breaks at POV shifts, location changes, time jumps, or cliffhangers
   - Avoid splitting a scene across chapters unless it's explicitly a cliffhanger
3. **Present the proposal** as a readable list:
   ```
   Chapter 1: "The Blank Page" (the-blank-page) — 6 pages
   Chapter 2: "Shadows Arrive" (shadows-arrive, the-first-mark) — 9 pages
   Chapter 3: "Into the Veil" (into-the-veil, cartographer-speaks) — 12 pages
   ```
   Include total page count and note any chapters that are unusually short or long.
4. **Ask for approval** before writing anything. Invite the author to rename chapters, move scenes, or split/merge.
5. **On approval**, write the chapter map and proceed to Step 4: Production Settings.

### `coach` — Guided Analysis

Do not generate a complete proposal. Instead:

- Present a scene inventory grouped by part/act: scene ID, title, estimated page count, POV.
- Surface natural break candidates: "Scenes 3–5 all follow the same POV in the same location — they may feel like one chapter."
- Ask guiding questions: "These seven scenes total about 40 pages — does that feel like one chapter to you, or two?" "Where do you feel the biggest tonal shift in Act 1?"
- When the author gives direction, help them refine it — flag potential issues ("Chapter 2 would be 32 pages, which is long for a single-issue format — want to split it?") — but let them make all grouping decisions.
- Once the author has decided the full structure, write the chapter map for them and proceed to Step 4.

### `strict` — Collect Breakdown

Do not propose or analyze. Ask directly:

> "How do you want to group your scenes into chapters? Please list them, e.g.:
> Chapter 1: scene-id-one, scene-id-two
> Chapter 2: scene-id-three"

Do not suggest groupings. Do not propose titles. Once the author provides their complete structure (titles and scene lists), write the chapter map and proceed to Step 4.

---

## Step 4: Production Settings

Production settings for GN projects live under `storyforge.yaml:script_package`. Ask **one question at a time**:

1. **Artist name** — "Who is illustrating this? Provide their name if known, or press Enter to skip for now."
   - Save to `script_package.artist_name` in `storyforge.yaml`.
   - If skipped, leave the field blank — it can be filled in before assembly.

2. **Trim size** — "What page format should the scripts target? Here are standard options:"
   - `6.625x10.25` — Standard US comic book (most common for monthly issues)
   - `7x10` — Graphic novel trade paperback (Dark Horse / Fantagraphics style)
   - `6.14x9.21` — Trade paperback (common for prose-format GN collections)
   - `8.5x11` — Full-bleed digital / webtoon (AI handoff standard)
   - Custom — author provides dimensions
   - Save to `script_package.trim_size` in `storyforge.yaml`.

3. **Page format** — "How should pages be delivered to the illustrator?"
   - `single` — Single-sided digital pages (best for AI/digital handoff, one page per file)
   - `spreads` — Print-ready two-page spreads (for print production or human illustrators working at spread scale)
   - Save to `script_package.page_format` in `storyforge.yaml`.

**After all three settings are answered**, proceed to Step 5: Branch + Commit + Assemble.

---

## Step 5: Branch, Commit, and Tell the Author to Assemble

**Do these steps in this exact order.**

**1. Ensure you are on a feature branch.** Check the current branch before writing any files:
```bash
git rev-parse --abbrev-ref HEAD
```
- If the output is `main` or `master`: create a new branch and switch to it:
  ```bash
  git checkout -b "storyforge/assemble-$(date '+%Y%m%d-%H%M')"
  ```
- If already on any other branch: stay on it — do not create a new branch.

**2. Write all files:**
- `reference/chapter-map.csv` — the approved chapter-to-scene mapping
- `storyforge.yaml` — updated with `script_package` settings

**3. Update project state:** set `chapter_map.exists: true` and `chapter_map.updated` to today's date in `storyforge.yaml`.

**4. Commit and push:**
```bash
git add -A && git commit -m "Produce: create chapter map and script-package settings" && git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
```

**5. Tell the author how to run assembly:**

> **Option A: Run it here**
> I'll launch the assembly in this conversation.
>
> **Option B: Run it yourself**
> Copy this command and run it in a separate terminal:
> ```bash
> cd {project_dir} && {plugin_path}/storyforge assemble
> ```

Wait for the author's choice. If Option B, provide the full command and end.

---

## Commit After Every Deliverable

Every artifact change gets its own commit before moving on:
- Created the chapter map? Commit and push.
- Updated production settings? Commit and push.
- Added or renamed a chapter? Commit and push.

```
git add -A && git commit -m "Produce: {what was done}" && git push
```

---

## The Chapter Map Format

The chapter map (`reference/chapter-map.csv`) is a pipe-delimited CSV that maps scenes to chapters. It is the same schema used for prose books — the `assemble` command reads it the same way.

```
chapter|title|heading|scenes
1|The Blank Page|numbered-titled|the-blank-page
2|Shadows Arrive|numbered-titled|shadows-arrive;the-first-mark
3|Into the Veil|numbered-titled|into-the-veil;cartographer-speaks
```

Each row has:
- `chapter` — chapter number (sequential integers)
- `title` — the chapter/issue title
- `heading` — heading format: `numbered`, `titled`, `numbered-titled`, or `none`
- `scenes` — semicolon-separated ordered list of scene IDs from `reference/scenes.csv`

### Production Settings in `storyforge.yaml`

GN production settings live under the `script_package` key (distinct from the `production` key used for prose):

```yaml
script_package:
  artist_name: "Illustrator Name"
  trim_size: "6.625x10.25"
  page_format: single
```

These three fields are the minimum required for assembly. The `assemble` command will use them to format the handoff bundle.

---

## Decisions Are Recorded Selectively

Only record genuine creative decisions in the key decisions file — not configuration. Chapter structure (which scenes group into which issues/chapters, pacing, the shape of each act) is a creative decision worth recording. Artist name, trim size, and page format are configuration saved in `storyforge.yaml` — they do not belong in key decisions.

**Record:** "Split Act 2 into two issues at the cliffhanger — tighter pacing per issue."
**Don't record:** "Using 6.625x10.25 standard comic trim." (configuration — already in storyforge.yaml)

---

## Coaching Level Behavior

Read `project.coaching_level` from `storyforge.yaml`. Chapter mapping — deciding which scenes group into which issues, what each chapter is named, how the pacing flows — is a **creative endeavor**. Coaching levels apply to it.

### `full` (default)
Proactively propose a complete chapter structure. Analyze the scene index, group scenes into issues or GN sections based on page counts and narrative logic, and present the full proposal for approval. Be opinionated about issue format and page targets — you know what makes a satisfying single issue versus a dragging one.

### `coach`
Help the author think through chapter structure, but **do not generate a complete proposal unprompted**. Surface page-count analysis and natural break candidates; ask guiding questions; let the author make all grouping decisions. Once the author decides, create the chapter map for them.

### `strict`
**Do not propose chapter structure, issue groupings, or pacing decisions.** The author provides the breakdown; you handle the file.
- Ask for the chapter breakdown, then create the chapter map.
- Do not suggest titles, groupings, or pacing adjustments.

Production settings (`artist_name`, `trim_size`, `page_format`) are configuration, not creative decisions — ask and execute at all coaching levels without waiting for the author to specify.

---

## Cover

The `cover` skill works for graphic novels too. If the author wants a cover image before assembling, invoke it. Return to `script-package` when the cover is complete.

---

## Coaching Posture

This is a handoff moment — the scripts are done and it's time to put them in an illustrator's hands. The author may be sending work to a human illustrator they've hired, or setting up an AI image-generation pipeline. Either way, the goal is a clean, numbered, self-contained bundle.

Be practical and clear. Don't over-explain panel script format or image-generation pipelines — focus on what the author needs to decide (chapter groupings, settings) and what they need to do (run the command). Surface the meaningful choices; hide the file-packaging mechanics.
