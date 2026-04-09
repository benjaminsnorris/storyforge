# Dashboard to Supabase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store manuscript dashboards in the Supabase `books` table instead of copying static HTML files to the bookshelf repo.

**Architecture:** Add a `dashboard_html text` column to `books`. The publish script reads `working/dashboard.html` from the book repo and upserts it with the book row. A new route handler serves the raw HTML for the admin page. The publish skill drops its manual dashboard copy step.

**Tech Stack:** Supabase (Postgres), Next.js App Router (route handler), TypeScript

**Repos:** Changes span two repos — `bookshelf` (database, script, app) and `storyforge` (publish skill).

---

### Task 1: Database Migration

**Files:**
- Create: `bookshelf/supabase/migrations/00003_dashboard_html.sql`

- [ ] **Step 1: Write the migration**

```sql
-- =============================================================================
-- Dashboard HTML: store manuscript dashboard in the books table
-- =============================================================================

ALTER TABLE books ADD COLUMN dashboard_html text;
```

- [ ] **Step 2: Apply the migration to local Supabase**

Run from the bookshelf repo:
```bash
cd ~/Developer/bookshelf && npx supabase db push
```

If local Supabase is not running, apply directly to production via the Supabase dashboard SQL editor.

- [ ] **Step 3: Commit**

```bash
cd ~/Developer/bookshelf && git add supabase/migrations/00003_dashboard_html.sql && git commit -m "Add dashboard_html column to books table" && git push
```

---

### Task 2: Update TypeScript Types

**Files:**
- Modify: `bookshelf/src/types/database.ts:39-47` (books Row), `bookshelf/src/types/database.ts:49-58` (books Insert), `bookshelf/src/types/database.ts:59-68` (books Update)

- [ ] **Step 1: Add `dashboard_html` to books Row type**

In `src/types/database.ts`, in the `books.Row` type, add after the `updated_at` field (line 47):

```typescript
          dashboard_html: string | null
```

- [ ] **Step 2: Add `dashboard_html` to books Insert type**

In the `books.Insert` type, add after `updated_at` (line 58):

```typescript
          dashboard_html?: string | null
```

- [ ] **Step 3: Add `dashboard_html` to books Update type**

In the `books.Update` type, add after `updated_at` (line 68):

```typescript
          dashboard_html?: string | null
```

- [ ] **Step 4: Commit**

```bash
cd ~/Developer/bookshelf && git add src/types/database.ts && git commit -m "Add dashboard_html to Book type" && git push
```

---

### Task 3: Update Publish Script to Store Dashboard

**Files:**
- Modify: `bookshelf/scripts/publish-book.ts:210-233` (book upsert section)

The script already receives `bookPath` as an argument. After building `bookRecord`, check for a dashboard file and include it.

- [ ] **Step 1: Add dashboard reading after the bookRecord construction**

After line 215 (`slug,`) and before the `if (Object.keys(bookMetadata)...` block at line 216, add dashboard reading. Replace the block from line 211 to line 223:

```typescript
  const bookRecord: Record<string, unknown> = {
    title: bookTitle,
    author: bookAuthor,
    slug,
  }
  if (Object.keys(bookMetadata).length > 0) {
    // Legacy mode: include metadata from YAML
    bookRecord.metadata = {
      genre: bookMetadata.subject || '',
      language: bookMetadata.lang || 'en',
      copyright: bookMetadata.rights || '',
    }
  }

  // Read dashboard HTML if available
  if (bookPath) {
    const dashboardPath = join(bookPath, 'working', 'dashboard.html')
    if (existsSync(dashboardPath)) {
      bookRecord.dashboard_html = readFileSync(dashboardPath, 'utf-8')
      console.log(`  Dashboard: ${dashboardPath} (${Math.round(bookRecord.dashboard_html.length / 1024)}KB)`)
    }
  }
```

- [ ] **Step 2: Add dashboard status to summary output**

After line 533 (`  ${orphanedCount} orphaned`), add:

```typescript
  if (bookRecord.dashboard_html) {
    console.log(`\nDashboard: published (${Math.round((bookRecord.dashboard_html as string).length / 1024)}KB)`)
  } else {
    console.log(`\nDashboard: none found`)
  }
```

Note: `bookRecord` needs to be accessible in the summary section. It's declared at line 211 in the same `main()` function scope, so it's already accessible.

- [ ] **Step 3: Test manually**

Run from a book project that has `working/dashboard.html`:
```bash
cd ~/Developer/bookshelf && npx tsx scripts/publish-book.ts ~/Developer/meridian-line --manifest ~/Developer/meridian-line/working/publish-manifest.json
```

Expected: Output includes a "Dashboard: published (NNNkB)" line. Verify in Supabase dashboard that the `books` row for that slug now has `dashboard_html` populated.

- [ ] **Step 4: Commit**

```bash
cd ~/Developer/bookshelf && git add scripts/publish-book.ts && git commit -m "Store dashboard HTML in Supabase during publish" && git push
```

---

### Task 4: Add Dashboard Route Handler

**Files:**
- Create: `bookshelf/src/app/(admin)/admin/dashboards/[slug]/route.ts`

- [ ] **Step 1: Create the route handler**

```typescript
import { createClient } from "@/lib/supabase/server"

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params
  const supabase = await createClient()

  const { data: book } = await supabase
    .from("books")
    .select("dashboard_html")
    .eq("slug", slug)
    .single()

  if (!book?.dashboard_html) {
    return new Response("Not found", { status: 404 })
  }

  return new Response(book.dashboard_html, {
    headers: { "Content-Type": "text/html; charset=utf-8" },
  })
}
```

- [ ] **Step 2: Test manually**

After Task 3 has published a dashboard, visit `http://localhost:3000/admin/dashboards/<slug>` in the browser.

Expected: The full manuscript dashboard renders as a standalone HTML page.

- [ ] **Step 3: Commit**

```bash
cd ~/Developer/bookshelf && git add src/app/\(admin\)/admin/dashboards/[slug]/route.ts && git commit -m "Add route handler to serve dashboard from Supabase" && git push
```

---

### Task 5: Update Admin Book Detail Page

**Files:**
- Modify: `bookshelf/src/app/(admin)/admin/books/[slug]/page.tsx:1-3` (imports), `bookshelf/src/app/(admin)/admin/books/[slug]/page.tsx:92` (hasDashboard check), `bookshelf/src/app/(admin)/admin/books/[slug]/page.tsx:129-137` (dashboard link)

- [ ] **Step 1: Remove filesystem imports**

Replace lines 1-2:

```typescript
import { existsSync } from "fs"
import { join } from "path"
```

with:

```typescript
```

(Delete both lines entirely — they are no longer used.)

- [ ] **Step 2: Replace the filesystem dashboard check**

Delete line 92:

```typescript
  const hasDashboard = existsSync(join(process.cwd(), "public", "dashboards", `${slug}.html`))
```

Replace with:

```typescript
  const hasDashboard = !!book.dashboard_html
```

- [ ] **Step 3: Update the dashboard link URL**

Replace the link at line 133:

```typescript
                href={`/dashboards/${slug}.html`}
```

with:

```typescript
                href={`/admin/dashboards/${slug}`}
```

- [ ] **Step 4: Verify in browser**

Visit `http://localhost:3000/admin/books/<slug>`.

Expected: "Manuscript Dashboard" link appears if the book has a dashboard in Supabase. Clicking it opens the dashboard in a new tab via the route handler.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/bookshelf && git add src/app/\(admin\)/admin/books/[slug]/page.tsx && git commit -m "Serve dashboard link from Supabase instead of filesystem" && git push
```

---

### Task 6: Delete Static Dashboard Files

**Files:**
- Delete: `bookshelf/public/dashboards/` (entire directory)

- [ ] **Step 1: Verify all books have dashboards in Supabase**

Before deleting, confirm that re-publishing has populated `dashboard_html` for all books. Check in Supabase:

```sql
SELECT slug, dashboard_html IS NOT NULL AS has_dashboard FROM books;
```

If any books are missing dashboards, re-publish them first (Task 3's publish script will populate the column).

- [ ] **Step 2: Delete the static dashboards directory**

```bash
cd ~/Developer/bookshelf && rm -rf public/dashboards/
```

- [ ] **Step 3: Commit**

```bash
cd ~/Developer/bookshelf && git add -A public/dashboards/ && git commit -m "Remove static dashboard files (now served from Supabase)" && git push
```

---

### Task 7: Update Publish Skill

**Files:**
- Modify: `storyforge/skills/publish/SKILL.md:78-86` (Step 6), `storyforge/skills/publish/SKILL.md:102-108` (Step 8), `storyforge/skills/publish/SKILL.md:114-117` (summary)

- [ ] **Step 1: Remove Step 6 (Copy Dashboard)**

Replace lines 78-86:

```markdown
If a dashboard is available (pre-existing or just generated):

1. **Derive the slug** from the project title in `storyforge.yaml`. Use the same logic as `publish-book.ts`:
   - Lowercase
   - Replace `[^a-z0-9]+` with `-`
   - Trim leading/trailing hyphens
2. **Copy** `working/dashboard.html` to `<bookshelf_path>/public/dashboards/<slug>.html`.

If no dashboard is available, skip this step.
```

with:

```markdown
Dashboard publishing is automatic. The publish script (Step 5) reads `working/dashboard.html` from the project directory and stores it in Supabase alongside the book content. No manual copy is needed.

If the dashboard was not generated in Step 4 and no pre-existing `working/dashboard.html` exists, the publish script skips the dashboard — no error.
```

- [ ] **Step 2: Simplify Step 8 (Commit in Bookshelf)**

Replace lines 102-108:

```markdown
## Step 8: Commit and Push in Bookshelf

If any files were copied to the bookshelf repo (dashboard, cover):

1. Stage the new/changed files.
2. Commit with message: `Publish <book-title>` (include what was copied, e.g. "dashboard", "dashboard and cover").
3. Push to remote.

Skip this step only if the author explicitly asks not to commit, or if no files were copied.
```

with:

```markdown
## Step 7: Commit and Push in Bookshelf

If any files were copied to the bookshelf repo (cover with `--cover` flag):

1. Stage the new/changed files.
2. Commit with message: `Publish <book-title> cover`.
3. Push to remote.

Skip this step if no `--cover` flag was used (all content including dashboards goes to Supabase, no filesystem changes).
```

- [ ] **Step 3: Update the summary section**

Replace line 117:

```markdown
- Whether the dashboard was copied
```

with:

```markdown
- Whether the dashboard was published (from publish script output)
```

- [ ] **Step 4: Renumber steps**

The old Steps 7-9 become Steps 7-8 (Step 6 was removed, Step 7/Cover stays, Step 8/Commit renumbered, Step 9/Summary renumbered). Update any step numbers and cross-references in the skill.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/storyforge && git add skills/publish/SKILL.md && git commit -m "Update publish skill: dashboard goes to Supabase" && git push
```
