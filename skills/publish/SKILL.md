---
name: publish
description: Publish a book to the Bookshelf app — push content to Supabase and copy the dashboard. Use when the author wants to publish, deploy, or push their book to bookshelf for test readers.
---

# Storyforge Publish Skill

You are helping an author publish their assembled book to the Bookshelf app. This is mechanical work — locate the bookshelf project, run the existing publish script, copy the dashboard, and commit.

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

## Step 3: Validate Readiness

**Web chapters are required.** Check that `manuscript/output/web/chapters/` contains at least one `chapter-*.html` file.

If no web chapters exist, stop and tell the author:
> "The assembled web book doesn't exist yet. Run `/storyforge:produce` to assemble your manuscript first."

Do not proceed without web chapters.

## Step 4: Check Dashboard

Look for `working/dashboard.html`:

- **If it exists:** Note it for copying in Step 6.
- **If it does not exist:** Ask the author: "The manuscript dashboard hasn't been generated yet. Would you like to create it before publishing?" If yes, invoke the `visualize` skill and return here when done. If no, proceed without the dashboard.

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

## Step 7: Cover (Automatic)

The publish script automatically handles the cover:
- It looks for `manuscript/assets/cover.png` (or `.jpg`) in the book project
- If found, it copies to `<bookshelf_path>/public/covers/<slug>.png` and sets `cover_image_url` in the database
- If not found, it reports "none found" — no action needed

You do not need to copy the cover manually. The script output will confirm whether a cover was published.

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

## Commit After Every Deliverable

After all steps complete, if any files changed in the **book project** (unlikely in normal flow, but possible if the visualize skill was invoked), commit and push those changes too.

```bash
git add -A && git commit -m "Publish: update artifacts" && git push
```
