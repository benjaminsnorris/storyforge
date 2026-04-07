---
name: publish
description: Publish a book to the Bookshelf app — assemble web book, generate dashboard, push content to Supabase, and copy assets. Use when the author wants to publish, deploy, push their book to bookshelf, generate a dashboard, or update the web book.
---

# Storyforge Publish Skill

You are helping an author publish their book to the Bookshelf app. This handles the full publish pipeline: assemble the web book, generate the manuscript dashboard, push content to Supabase, and copy assets.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory (this skill's directory -> `skills/` -> plugin root).

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Read the following files to assess readiness:

- `storyforge.yaml` — project title (used to derive the slug)
- `manuscript/output/web/chapters/` — check that assembled web chapters exist

Check for optional artifacts:
- `working/dashboard.html` — manuscript visualization dashboard
- `manuscript/assets/cover.*` — cover image (only relevant if user requests cover publishing)

## Step 2: Locate Bookshelf

Check for the publish script at `~/Developer/bookshelf/scripts/publish-book.ts`.

- If found, store the bookshelf path (`~/Developer/bookshelf`) and continue.
- If not found, tell the author: "I couldn't find the Bookshelf project at `~/Developer/bookshelf`. Where is your bookshelf project?" Wait for the path, then verify `scripts/publish-book.ts` exists there.

## Step 3: Assemble Web Book

Check if `manuscript/output/web/chapters/` contains chapter files. If not (or if the author wants a fresh build), assemble:

```bash
cd <project_dir> && ./storyforge assemble --format web
```

If the runner script doesn't exist, offer to create one. If `reference/chapter-map.csv` doesn't exist, help the author create it first (invoke `produce` skill for chapter mapping).

## Step 4: Generate Dashboard

Generate or regenerate the manuscript dashboard:

```bash
cd <project_dir> && ./storyforge visualize
```

This creates `working/dashboard.html` with the multi-page visualization (overview, structure, scores). If scoring data exists, it will be included automatically.

## Step 5: Publish Content

Run the bookshelf publish script. The book repo path is the current project directory (where `storyforge.yaml` lives).

```bash
cd <bookshelf_path> && npx tsx scripts/publish-book.ts <book_repo_path>
```

Show the script's output to the author. It will report chapter count, scene count, and word count.

If the script fails, show the error and stop. Do not proceed to dashboard copy or commit.

## Step 6: Copy Dashboard

If a dashboard is available (pre-existing or just generated):

1. **Derive the slug** from the project title in `storyforge.yaml`. Use the same logic as `publish-book.ts`:
   - Lowercase
   - Replace `[^a-z0-9]+` with `-`
   - Trim leading/trailing hyphens
2. **Copy** `working/dashboard.html` to `<bookshelf_path>/public/dashboards/<slug>.html`.

If no dashboard is available, skip this step.

## Step 7: Cover

The cover is only published when the author asks for it (e.g. "publish the cover too", "include the cover", "update the cover").

When requested, add `--cover` to the publish command in Step 5:

```bash
cd <bookshelf_path> && npx tsx scripts/publish-book.ts <book_repo_path> --cover
```

The script handles everything: copies `manuscript/assets/cover.png` (or `.jpg`) to `public/covers/<slug>.png` and sets `cover_image_url` in the database.

If the author doesn't mention the cover, run the publish command without `--cover`.

## Step 8: Commit and Push in Bookshelf

If any files were copied to the bookshelf repo (dashboard, cover):

1. Stage the new/changed files.
2. Commit with message: `Publish <book-title>` (include what was copied, e.g. "dashboard", "dashboard and cover").
3. Push to remote.

Skip this step only if the author explicitly asks not to commit, or if no files were copied.

## Step 9: Summary

Report what was published:

- Chapters and scenes published (from script output)
- Whether the dashboard was copied
- Whether the cover was copied (if applicable)
- The bookshelf commit (if one was made)

## Ensure Feature Branch

Before making any changes, check the current branch:
```bash
git rev-parse --abbrev-ref HEAD
```
- If on `main` or `master`: create a feature branch first:
  ```bash
  git checkout -b "storyforge/publish-$(date '+%Y%m%d-%H%M')"
  ```
- If on any other branch: stay on it — do not create a new branch.

## Commit After Every Deliverable

After all steps complete, if any files changed in the **book project** (unlikely in normal flow, but possible if the visualize skill was invoked), commit and push those changes too.

```bash
git add -A && git commit -m "Publish: update artifacts" && git push
```
