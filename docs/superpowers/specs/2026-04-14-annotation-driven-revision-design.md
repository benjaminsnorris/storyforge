# Annotation-Driven Revision Design

**Date:** 2026-04-14
**Motivation:** Reader annotations in the Bookshelf app are valuable revision feedback that currently has no path back into the writing pipeline. This feature fetches annotations, tracks their status, and routes them into the revision and hone commands as findings.

**Related:** benjaminsnorris/bookshelf#5 (add color_label to annotations API response)

## Context

The Bookshelf app lets readers highlight text and leave notes. Each highlight has a color with semantic meaning:

| Color | Label | Revision Intent |
|-------|-------|-----------------|
| pink | Needs Revision | Craft problem — the prose isn't working |
| orange | Cut / Reconsider | Structural problem — this content may not belong |
| blue | Research Needed | Something to verify or deepen (not a revision finding) |
| green | Strong Passage | Positive signal — protect during revision, exemplar candidate |
| yellow | Important | Ambiguous without a note — skip unless note present |

The Bookshelf API (`/api/books/[slug]/annotations`) returns annotations with scene slugs that map directly to storyforge scene IDs. The existing `bookshelf.py` module already has `get_annotations()` and `authenticate()`.

The revision pipeline already has a mechanism for external findings: `cmd_hone.py --findings FILE` accepts a pipe-delimited CSV. The revision plan CSV has a `protection` field for passages that should not be changed.

## New Command: `storyforge annotations`

Fetches annotations from the Bookshelf API, reconciles against a stateful CSV, and routes new annotations by color intent. No Claude API calls — pure data processing.

### CLI Interface

```
storyforge annotations                    # Fetch and reconcile
storyforge annotations --status new       # Show only unaddressed
storyforge annotations --color pink       # Filter by color
storyforge annotations --scene arrival    # Filter by scene
storyforge annotations --dry-run          # Show what would be fetched without writing
```

Requires the same env vars as `storyforge publish`: BOOKSHELF_URL, BOOKSHELF_EMAIL, BOOKSHELF_PASSWORD, BOOKSHELF_SUPABASE_URL, BOOKSHELF_SUPABASE_ANON_KEY.

### Reconciliation Logic

On each run:
1. Authenticate with Supabase (reuses `bookshelf.authenticate()`)
2. Fetch all active annotations via `bookshelf.get_annotations()`
3. Load existing `working/annotations.csv` if present
4. New annotations (ID not in CSV) get `status: new` with color-derived `fix_location`
5. Existing annotations retain their status (addressed/skipped/protected/exemplar)
6. Annotations no longer returned by the API get `status: removed` (row preserved — the author may have addressed it)
7. Print summary: N new, N previously addressed, N total

### Color-to-Intent Mapping

The mapping is maintained on the storyforge side. When the Bookshelf API adds `color_label` to the response (benjaminsnorris/bookshelf#5), the label is stored directly. Until then, storyforge maps color names to labels.

```python
COLOR_LABELS = {
    'pink': 'Needs Revision',
    'orange': 'Cut / Reconsider',
    'blue': 'Research Needed',
    'green': 'Strong Passage',
    'yellow': 'Important',
}

COLOR_TO_FIX_LOCATION = {
    'pink': 'craft',
    'orange': 'structural',
    'blue': 'research',
    'green': 'protection',
    'yellow': 'craft',  # only when note is present
}
```

Yellow annotations without notes get `status: skipped` (no actionable signal).

## Stateful CSV: `working/annotations.csv`

Pipe-delimited, one row per annotation, keyed by Bookshelf annotation ID.

### Columns

```
id|scene_id|chapter|color|color_label|text|note|reader|created_at|status|fix_location|fetched_at
```

| Column | Description |
|--------|-------------|
| `id` | Bookshelf annotation UUID (primary key) |
| `scene_id` | Scene slug from the API (maps to storyforge scene ID) |
| `chapter` | Chapter number |
| `color` | Color name (pink, orange, blue, green, yellow) |
| `color_label` | Semantic label (Needs Revision, Cut / Reconsider, etc.) |
| `text` | The highlighted text |
| `note` | Reader's note (empty if none) |
| `reader` | Reader display name |
| `created_at` | ISO timestamp from the API |
| `status` | Storyforge status: `new`, `addressed`, `skipped`, `protected`, `exemplar`, `removed` |
| `fix_location` | Where the fix routes: `craft`, `structural`, `research`, `exemplar`, `protection` |
| `fetched_at` | ISO timestamp of when this row was last fetched/reconciled |

### Status Transitions

- `new` → `addressed` (revision pass touched the scene)
- `new` → `skipped` (author chose to ignore)
- `new` → `protected` (green annotation applied as revision protection)
- `new` → `exemplar` (green annotation promoted to exemplar file)
- `new` → `removed` (annotation deleted in Bookshelf)
- Any status → author can manually change by editing the CSV

## Revision Pipeline Integration

### cmd_revise.py

When generating any revision plan (polish, naturalness, or custom), check for `working/annotations.csv`. If unaddressed annotations exist with `status: new`:

**Craft findings (pink annotations):** Aggregated per scene. Each annotated scene gets one finding in the revision plan. The finding's `guidance` field includes the highlighted text and reader notes as context:

```
Scene "arrival" — 3 reader annotations (Needs Revision):
  1. "the wagon lurched forward and the dust rose" — Reader note: "pacing drags here"
  2. "she counted the stakes again" — Reader note: "repetitive"
  3. "the sun was merciless" — (no note)
```

**Structural findings (orange annotations):** Aggregated per scene, routed to the plan with `fix_location: structural`. These produce structural revision passes (cut/reconsider content) rather than craft polish.

**Protection constraints (green annotations):** Injected into the `protection` field of relevant revision passes. The revision LLM is told: "Protect these reader-validated passages — do not rewrite them."

**Research annotations (blue):** Not included in revision plans. Listed in the command summary for the author's reference.

**Skip flag:** `--no-annotations` on revise excludes annotations from the plan.

### cmd_hone.py

When hone checks for external findings, it also loads `working/annotations.csv`. Pink annotations whose notes suggest brief-level or intent-level issues are surfaced alongside auto-detected quality issues. This uses the existing `load_external_findings()` mechanism — annotations are converted to the same pipe-delimited findings format that hone already consumes.

### Status Updates After Revision

When a revision pass addresses a scene that has annotations:
- Pink/orange annotations for that scene get `status: addressed`
- Green annotations that were used as protection get `status: protected`
- The annotations CSV is updated and committed with the revision results

## Exemplar Integration (Coaching-Level Aware)

Green annotations with notes that explain *why* the passage is strong are candidates for the exemplar file. The `storyforge annotations` command flags these as `fix_location: exemplar`.

**Full coaching level:** The annotations command adds the passage to the project's exemplar file automatically and sets `status: exemplar`. The summary reports what was added so the author can review.

**Coach coaching level:** The annotations command saves a brief to `working/coaching/exemplar-candidates.md` explaining each candidate — the passage, the reader's note, and why it would serve as an effective few-shot example for drafting prompts. The author decides whether to add it. Status stays `new` until the author acts.

**Strict coaching level:** The annotations command lists the candidates in its summary output (passage, reader, note). No file written, no interpretation. Status stays `new`.

## Skills Awareness

### Forge skill
Routes "annotations", "reader feedback", "what did my readers say" to the annotations command. Checks for `working/annotations.csv` with `status: new` entries when assessing project state.

### Revise skill
When presenting revision options, notes if unaddressed annotations exist and offers to include them. Explains what each color means and how they route.

### Hone skill
When running data quality checks, surfaces pink annotations that suggest brief-level issues (e.g., notes mentioning unclear conflict or goal).

### Score skill
After scoring, if annotations exist, notes the correlation: "Scenes with reader 'Needs Revision' annotations scored X on average vs Y for unannotated scenes." Informational only — does not change scores.

## What This Does NOT Do

- No Claude API calls. The annotations command is pure data processing (HTTP fetch + CSV write).
- No automatic revision execution. Annotations go into the plan; the author decides when to run it.
- No annotation creation from storyforge. Annotations flow one way: Bookshelf → storyforge.
- No modification of Bookshelf data. Storyforge reads annotations but never writes back.

## Files Created/Modified

### New
- `scripts/lib/python/storyforge/cmd_annotations.py` — command module
- `scripts/lib/python/storyforge/annotations.py` — annotation processing logic (fetch, reconcile, route, exemplar)
- `tests/test_reader_annotations.py` — tests for reconciliation, routing, exemplar integration (named to avoid collision with existing `test_annotations.py` which tests web annotation HTML injection)

### Modified
- `scripts/lib/python/storyforge/__main__.py` — register `annotations` command
- `scripts/lib/python/storyforge/bookshelf.py` — add color label mapping (until API returns it)
- `scripts/lib/python/storyforge/cmd_revise.py` — check for annotations CSV, incorporate into revision plans, update status after passes
- `scripts/lib/python/storyforge/cmd_hone.py` — check for annotations CSV, convert to findings format
- `scripts/lib/python/storyforge/schema.py` — add annotations.csv validation
- `skills/forge/SKILL.md` — add annotation routing
- `skills/revise/SKILL.md` — document annotation awareness
- `skills/hone/SKILL.md` — document annotation awareness
- `CLAUDE.md` — add annotations command, annotations.py module, annotations.csv to CSV files section
