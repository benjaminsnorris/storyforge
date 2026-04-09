# Dashboard to Supabase

Store manuscript dashboards in the Supabase `books` table instead of copying static HTML files to the bookshelf repo.

## Motivation

The publish workflow currently copies `working/dashboard.html` to `bookshelf/public/dashboards/<slug>.html` and commits it to the bookshelf repo. This is the only part of publishing that requires the bookshelf repo to have filesystem changes committed. Moving the dashboard to Supabase makes the entire publish flow go through the database, eliminating static file management.

## Changes

### 1. Database — new column on `books`

New Supabase migration:

```sql
ALTER TABLE books ADD COLUMN dashboard_html text;
```

Nullable. Books without dashboards have `NULL`. Dashboard sizes range from 450KB to 2.6MB — well within Postgres TOAST compression limits.

### 2. Publish script (`bookshelf/scripts/publish-book.ts`)

The script already receives the book repo path as an argument. After upserting book/chapters/scenes, it now also:

1. Checks for `<book_repo_path>/working/dashboard.html`
2. If found, reads it as a UTF-8 string and includes `dashboard_html` in the book upsert
3. If not found, leaves `dashboard_html` unchanged (does not null it out — a previous publish may have set it)

Dashboard publishing is automatic, not flag-gated. No `--dashboard` flag needed.

### 3. Route handler — serve dashboard HTML

New file: `bookshelf/src/app/(admin)/admin/dashboards/[slug]/route.ts`

- `GET` handler
- Fetches `dashboard_html` from `books` where `slug` matches
- Returns `new Response(html, { headers: { 'Content-Type': 'text/html' } })`
- Returns 404 if no book found or `dashboard_html` is null

Admin-only for now (lives under the `(admin)` route group).

### 4. Admin book detail page

Update `bookshelf/src/app/(admin)/admin/books/[slug]/page.tsx`:

- Remove the `existsSync` filesystem check for `public/dashboards/<slug>.html`
- Remove the `fs` and `path` imports
- Check `book.dashboard_html` (truthy/null) from the existing Supabase query
- Update link href from `/dashboards/${slug}.html` to `/admin/dashboards/${slug}`

### 5. TypeScript types

Update `bookshelf/src/types/database.ts` to add `dashboard_html: string | null` to the `Book` type (or equivalent generated type).

### 6. Publish skill (`storyforge/skills/publish/SKILL.md`)

- Remove Step 6 (Copy Dashboard) entirely — the script handles it now
- Update Step 8 (Commit in Bookshelf) — remove dashboard references. Step only applies when `--cover` is used (cover still copies a file to `public/covers/`)
- Update the summary step to reflect that dashboard publishing is automatic

### 7. Cleanup

- Delete `bookshelf/public/dashboards/` directory and all its contents
- Existing dashboards are restored by re-publishing each book once

## Files changed

**Bookshelf repo:**
- `supabase/migrations/<next>_dashboard_column.sql` (new)
- `scripts/publish-book.ts` (modified — read and upsert dashboard)
- `src/app/(admin)/admin/dashboards/[slug]/route.ts` (new — serve dashboard)
- `src/app/(admin)/admin/books/[slug]/page.tsx` (modified — check DB instead of filesystem)
- `src/types/database.ts` (modified — add column type)
- `public/dashboards/` (deleted)

**Storyforge repo:**
- `skills/publish/SKILL.md` (modified — remove dashboard copy step)
