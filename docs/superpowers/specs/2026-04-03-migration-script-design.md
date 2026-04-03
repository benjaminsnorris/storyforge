# Migration Script Design

**Date:** 2026-04-03
**Status:** Approved

## Problem

Existing Storyforge projects have scene CSVs with:
- `scene_type` column (renamed to `action_sequel`)
- `threads` column (removed — MICE threads replace it)
- Free-text values in `value_at_stake`, `knowledge_in`/`knowledge_out`, `mice_threads`
- No registry files for values, knowledge facts, or MICE threads

These projects need to be upgraded to the normalized registry model without re-running full extraction.

## Design

### Script: `scripts/storyforge-migrate`

A one-time migration script that upgrades existing projects. Idempotent — safe to run multiple times.

### Steps (in order):

1. **Column rename**: `scene_type` → `action_sequel` in scene-intent.csv header and all data rows
2. **Column removal**: strip `threads` column from scene-intent.csv header and all data rows
3. **Seed registries** from existing CSV data (only creates files that don't exist):
   - Scan unique `value_at_stake` values → create `reference/values.csv` (id=slugified, name=original)
   - Scan unique `mice_threads` thread names → create `reference/mice-threads.csv` (id=name, type parsed from +type:name entries)
   - Scan unique `knowledge_in`/`knowledge_out` facts → create `reference/knowledge.csv` (id=slugified, name=original)
   - Skip characters.csv, locations.csv, motif-taxonomy.csv (should already exist)
4. **Normalize all fields**: load registries via `load_registry_alias_maps`, run `normalize_fields` on every row in all three scene CSVs, write back
5. **Validate**: run `validate_schema` and print the report showing remaining issues
6. **Commit**: git add + commit the migration changes

### Flags

- `--dry-run` — show what would change without writing any files
- `--no-commit` — make changes but don't git commit
- `-h` — help

### Safety

- Idempotent: checks for `scene_type` before renaming (skips if already `action_sequel`), checks for `threads` before removing (skips if already gone)
- Won't overwrite existing registry files — only seeds missing ones
- Slug generation for registry IDs: lowercase, replace spaces with hyphens, strip non-alphanumeric except hyphens

### Implementation

Python-heavy script (inline Python blocks following the existing script pattern). Uses:
- `elaborate._read_csv`, `elaborate._write_csv`, `elaborate._FILE_MAP` for CSV I/O
- `enrich.load_registry_alias_maps`, `enrich.normalize_fields` for normalization
- `schema.validate_schema` for validation report

### Output

Human-readable progress log:
```
Migration: project-name
  [1/5] Rename scene_type → action_sequel: done (66 rows)
  [2/5] Remove threads column: done (66 rows)
  [3/5] Seed registries:
    values.csv: created (8 values)
    mice-threads.csv: created (12 threads)
    knowledge.csv: created (34 facts)
  [4/5] Normalize fields: 198 cells updated
  [5/5] Schema validation: 340 passed, 3 failed, 82 skipped
    scenes.csv:
      hidden-canyon | location: "The Harbor" — not in locations.csv
    ...
```

### Files

| File | Action |
|------|--------|
| `scripts/storyforge-migrate` | Create |
