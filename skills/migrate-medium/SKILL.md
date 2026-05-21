---
name: migrate-medium
description: Convert a project from novel to graphic-novel mode (or vice versa). Archives the old data, updates schema, and tells you what to populate next. Use when an author wants to change their project's delivery medium.
---

# Storyforge Medium Migration

You are helping an author convert their Storyforge project between novel and graphic-novel mode. This is a structural, mechanical operation — not a creative one. All coaching levels are treated identically for this skill.

**What this migration does:**
- Archives the current `scenes/`, CSVs, and `storyforge.yaml` to `working/migration/`
- Updates `project.medium` in `storyforge.yaml`
- Resets all scene statuses to `mapped` (prose or panel scripts are archived, not deleted)
- Clears the medium-specific numeric columns from `scenes.csv`
- For GN→novel: clears GN-specific brief columns (`page_layout`, `panel_breakdown`, etc.)
- For novel→GN: appends visual migration notes to `character-bible.md` and `world-bible.md`

**What it preserves:**
- `reference/scene-intent.csv` (medium-agnostic)
- `reference/voice-profile.csv` (voice carries between mediums)
- `reference/story-architecture.md`, `character-bible.md`, `world-bible.md` content
- All registry CSVs (`characters.csv`, `locations.csv`, etc.)

---

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory:
`skills/migrate-medium/` → `skills/` → plugin root.

Resolve the plugin path and store it for commands below.

---

## Step 1: Read Project State

Read the project's current state before asking any questions:

1. Read `storyforge.yaml` — find `project.medium` (defaults to `novel` if absent)
2. Read `reference/scenes.csv` — count scenes, note their current statuses
3. Note whether `scenes/` has any drafted `.md` files

Summarize to the author:

> This project is currently in **{current_medium}** mode.
> It has **{N} scene(s)** — **{X}** drafted, **{Y}** at mapped/briefed.
> {If scenes/ has files: "**{count} scene file(s)** in `scenes/` will be archived."}

---

## Step 2: Determine Target Medium

Ask the author what they want to convert to:

> What medium do you want to convert this project to?
>
> **A.** Graphic novel (panel scripts, page-based pacing)
> **B.** Novel (prose, word-based pacing)

Wait for their choice. If they chose the medium the project is already in, tell them:

> This project is already in **{medium}** mode. Nothing to migrate.
>
> If you want to create an archive snapshot anyway, run:
> ```bash
> cd <project_dir> && <plugin_path>/storyforge migrate-medium --to {medium} --force --no-commit
> ```

---

## Step 3: Explain the Migration

Before running anything, explain clearly what will happen:

**Novel → Graphic Novel:**

> **What changes:**
> - `storyforge.yaml`: `project.medium` set to `graphic-novel`
> - `reference/scenes.csv`: `target_words` and `word_count` cleared; all scenes reset to `status=mapped`
> - `scenes/`: all `.md` files moved to `working/migration/{timestamp}-novel-to-graphic-novel/scenes/`
> - `reference/character-bible.md` and `reference/world-bible.md`: a visual migration note is appended if they lack `### Visual` sections
>
> **What stays the same:**
> - `reference/scene-intent.csv` (narrative intent is medium-agnostic)
> - `reference/voice-profile.csv` (voice carries across mediums)
> - `reference/story-architecture.md` (story structure is unchanged)
> - All registry CSVs (characters, locations, values, etc.)
> - Brief text columns in `scene-briefs.csv` (goal, conflict, outcome, etc.) — the GN-specific columns are already empty; they get filled via `./storyforge elaborate --stage briefs`
>
> **After migration, you'll need to:**
> 1. Add `### Visual` subsections to `reference/character-bible.md` per character
> 2. Add `### Visual` subsections to `reference/world-bible.md` per location
> 3. Set `target_pages` for each scene in `reference/scenes.csv`
> 4. Run `./storyforge elaborate --stage briefs` to fill GN-specific brief columns
> 5. Run `./storyforge write` to draft panel scripts scene by scene

**Graphic Novel → Novel:**

> **What changes:**
> - `storyforge.yaml`: `project.medium` set to `novel`
> - `reference/scenes.csv`: `target_pages`, `panel_count`, `page_count` cleared; all scenes reset to `status=mapped`
> - `reference/scene-briefs.csv`: GN columns cleared (`page_layout`, `panel_breakdown`, `visual_keywords`, `page_turn_beats`, `caption_strategy`)
> - `scenes/`: all `.md` files moved to `working/migration/{timestamp}-graphic-novel-to-novel/scenes/`
>
> **What stays the same:**
> - `reference/scene-intent.csv`, `reference/voice-profile.csv`, `reference/story-architecture.md`
> - `reference/character-bible.md` and `reference/world-bible.md` — `### Visual` subsections are kept (they may still be useful as art reference for cover design or press kit)
> - All registry CSVs
>
> **After migration, you'll need to:**
> 1. Set `target_words` per scene in `reference/scenes.csv`
>    (or run `./storyforge elaborate --stage map` to repopulate word targets)
> 2. Run `./storyforge write` to draft prose scenes

---

## Step 4: Confirm

Ask once:

> Are you ready to proceed?
>
> **Yes** — run the migration now
> **No** — cancel

If they say no, end the session. No changes will have been made.

---

## Step 5: Run the Migration Command

This command does not invoke Claude (no API calls), so there are no `CLAUDECODE` concerns.

> **Option A: Run it here**
> I'll run the migration in this conversation.
>
> Run:
> ```bash
> cd <project_dir> && <plugin_path>/storyforge migrate-medium --to {target} --force
> ```
> (`--force` lets you re-run migration on a project that's already in the target medium.)
>
> **Option B: Run it yourself**
> Copy this command and run it in a separate terminal:
> ```bash
> cd <project_dir> && <plugin_path>/storyforge migrate-medium --to {target}
> ```

Wait for the author's choice. If Option B, provide the exact command (with the real paths filled in) and end the skill session.

If Option A, run the command and capture the output. The command will print a summary of what happened and what to do next.

---

## Step 6: Post-Migration Next Steps

After the command completes, present the author with their next actions depending on direction:

**Novel → Graphic Novel:**

> Migration complete. Here's what to do next:
>
> 1. **Add visual subsections to your bibles**
>    Open `reference/character-bible.md` and add a `### Visual` block for each character.
>    Open `reference/world-bible.md` and add a `### Visual` block for each key location.
>    (The migration appended a note with the exact format to follow if your bibles didn't have them yet.)
>
> 2. **Set target pages per scene**
>    Open `reference/scenes.csv` and fill in the `target_pages` column for each scene.
>    Typical graphic-novel pacing: 4–8 pages per scene for a standard 100-page book.
>
> 3. **Fill GN brief columns**
>    Run `/storyforge:elaborate` and choose the briefs stage.
>    This will populate `page_layout`, `panel_breakdown`, `visual_keywords`, `page_turn_beats`, and `caption_strategy` for each scene.
>
> 4. **Draft panel scripts**
>    Run `/storyforge:forge` or use `./storyforge write` to draft scenes as panel scripts.

**Graphic Novel → Novel:**

> Migration complete. Here's what to do next:
>
> 1. **Set target words per scene**
>    Open `reference/scenes.csv` and fill in the `target_words` column.
>    Alternatively, run `/storyforge:elaborate` and choose the map stage to have Claude suggest word targets.
>
> 2. **Draft prose scenes**
>    Run `/storyforge:forge` or use `./storyforge write` to begin drafting prose scenes.

---

## Reversibility Note

Remind the author:

> All changes are committed to git. If you need to undo the migration:
> ```bash
> git log --oneline -5   # find the commit before migration
> git revert HEAD        # revert the migration commit
> ```
>
> The full archive of your original files is also preserved at:
> `working/migration/{timestamp}-{from}-to-{to}/`
