# Publish Skill Design

## Purpose

A Storyforge skill that publishes a book to the Bookshelf app — pushes chapter/scene content to Supabase via the existing `publish-book.ts` script and copies the dashboard HTML to the bookshelf's public directory.

## Artifacts Published

| Artifact | Source (book repo) | Destination (bookshelf) | When |
|----------|-------------------|------------------------|------|
| Content (chapters/scenes) | `manuscript/output/web/chapters/` | Supabase via `publish-book.ts` | Always |
| Dashboard | `working/dashboard.html` | `public/dashboards/{slug}.html` | Always (prompts to generate if missing) |
| Cover image | `manuscript/assets/cover.*` | TBD (bookshelf cover handling) | Only when user explicitly requests |

## Flow

### 1. Locate bookshelf

Check for `~/Developer/bookshelf/scripts/publish-book.ts`. If the file does not exist at that path, ask the user where their bookshelf project lives. Do not store the path in config — just use the smart default each time.

### 2. Validate book project

Confirm the current project has `manuscript/output/web/chapters/` with at least one `chapter-*.html` file. If not, tell the user they need to assemble the web book first (`/storyforge:produce`) and stop.

### 3. Check dashboard

Look for `working/dashboard.html` in the book project:
- If it exists, proceed.
- If it does not exist, ask the user if they want to generate it now. If yes, invoke the visualize skill. If no, proceed without the dashboard.

### 4. Publish content

Run from the bookshelf directory:
```bash
cd <bookshelf_path> && npx tsx scripts/publish-book.ts <book_repo_path>
```

Display the script's output to the user (chapter count, scene count, word count).

### 5. Copy dashboard

If a dashboard is available (either pre-existing or just generated):
- Derive the slug from the book title using the same logic as `publish-book.ts`: lowercase, replace non-alphanumeric with hyphens, trim leading/trailing hyphens.
- Copy `working/dashboard.html` to `<bookshelf_path>/public/dashboards/{slug}.html`.

### 6. Copy cover (only if requested)

When the user explicitly asks to publish the cover:
- Locate the cover image in the book project (e.g., `manuscript/assets/cover.png` or similar).
- Copy or upload it to wherever bookshelf expects covers.
- This step is never performed automatically.

### 7. Commit and push in bookshelf

After copying files to the bookshelf repo:
- Stage the new/changed files (dashboard, cover if applicable).
- Commit with message: `Publish {book-title} dashboard` (or similar).
- Push to remote.
- Skip this step only if the user explicitly asks not to commit.

### 8. Summary

Report what was published:
- Chapter and scene counts (from publish script output)
- Whether dashboard was copied
- Whether cover was copied
- Bookshelf commit hash

## Slug Derivation

The slug must match what `publish-book.ts` generates so the dashboard filename aligns with the book's URL slug. Logic:
```
lowercase → replace [^a-z0-9] with hyphen → collapse consecutive hyphens → trim leading/trailing hyphens
```

Read the book title from `storyforge.yaml` (`project.title`).

## Error Handling

- **Bookshelf not found:** Ask user for path. Do not proceed without it.
- **Web chapters missing:** Stop with clear message pointing to `/storyforge:produce`.
- **Publish script fails:** Show the error output. Do not copy dashboard or commit.
- **Dashboard missing:** Ask user if they want to generate. Not a blocking error.
- **No changes in bookshelf:** Skip the commit step.

## What This Skill Does NOT Do

- No config in `storyforge.yaml` — bookshelf path is a smart default with fallback prompt.
- No API endpoint — runs the existing script directly.
- No changes to `publish-book.ts` — reuses it as-is.
- No coaching level adaptation — this is mechanical work, not creative.
- No epub/PDF publishing — only the web content and dashboard.

## Skill File Structure

`skills/publish/SKILL.md` — single skill file following standard Storyforge skill conventions.
