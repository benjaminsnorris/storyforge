# Project Cleanup — Design Spec

## Problem

Storyforge novel projects accumulate structural drift over time:
- Working directories bloat with logs (300MB+), stale intermediate files, and batch API payloads
- Log files get committed to git, permanently inflating the repo
- Config and CSV schemas fall behind the current plugin version (missing columns, misplaced keys, absent sections)
- Legacy files from earlier plugin versions linger and confuse Claude's context
- Reference CSVs drift out of sync (characters in scenes not in characters.csv, metadata/intent mismatches)
- CLAUDE.md accumulates orchestration state that belongs in pipeline.csv and storyforge.yaml

## Approach

**Skill + script, Approach A:** An interactive skill (`/storyforge:cleanup`) handles diagnostic presentation and judgment-call items. A deterministic script (`storyforge-cleanup`) handles all safe, automated fixes. The script is also useful standalone via `./storyforge cleanup`.

## Script: `storyforge-cleanup`

### Flags

- `--dry-run` — report what would change without modifying anything
- `--verbose` — detailed output for each step

### Execution Order

#### 1. Gitignore

Ensures the following entries exist in `.gitignore`, adding any that are missing:

```
# macOS
.DS_Store

# Logs (debugging output, value extracted at write time)
working/logs/

# Batch API payloads (keep only latest for debugging)
working/scores/**/.batch-requests.jsonl

# Intermediate scoring/eval state
working/evaluations/**/.status-*
working/scores/**/.markers-*

# Temporary flag files
working/.autopilot
working/.interactive
```

After updating `.gitignore`, runs `git rm --cached` on any files that are now gitignored but still tracked in git. This stops the bleeding without rewriting history.

Also updates the plugin's `templates/gitignore` to match, so new projects get the full gitignore from init.

#### 2. Missing Directories

Creates expected directories if absent:
- `manuscript/press-kit/`
- `working/recommendations/`
- `working/logs/`
- `working/evaluations/`
- `working/plans/`

#### 3. storyforge.yaml Migration

**Missing sections** — adds with sensible defaults if absent:
- `production:` — added commented-out, matching the template structure
- `parts:` — added commented-out
- `scene_extensions:` — added as empty array
- `evaluation:` — added with empty `custom_evaluators`

**Misplaced keys** — moves to correct location:
- `chapter_map` as top-level key → nested under `artifacts`

**Artifact flag sync:**
- Compares `exists:` flags against files on disk; fixes mismatches in both directions
- Updates `updated:` dates from git log where available
- Adds missing artifact entries for files that exist on disk but aren't tracked in the artifacts section (e.g., `characters.csv`, `scene-intent.csv`, `locations.csv`)

#### 4. Pipeline.csv Columns

Adds missing columns (`scoring`, `review`, `recommendations`) with empty values for existing rows. Preserves all existing data.

#### 5. Junk File Cleanup

Deletes:
- `.status-*` files in evaluation dirs (2-byte completion flags)
- `.markers-*` files in score dirs (intermediate scoring state)
- `.batch-requests.jsonl` in score dirs, except in `latest/` (build artifacts, never re-read)
- All contents of `working/logs/` (value already extracted to scenes + cost ledger at write time)
- Empty working subdirectories (`working/enrich/`, `working/coaching/`, etc.)

#### 6. Legacy File Deletion

Deletes known-stale legacy files without asking:
- `working/pipeline.yaml` (superseded by pipeline.csv)
- `working/assemble.py` (superseded by `./storyforge assemble`)

#### 7. Loose File Reorganization

Moves `working/recommendations-*.md` files into `working/recommendations/`.

#### 8. Pipeline Review Dedup

Keeps only the last pipeline review file per cycle. Pipeline reviews are named `pipeline-review-YYYYMMDD-HHMMSS.md`. Reviews from the same date (same YYYYMMDD prefix) are from the same cycle — keep only the latest timestamp per date. Standalone `review-YYYYMMDD.md` files are always kept (these are cycle summaries, not pipeline reviews).

#### 9. CSV Integrity Report

Reports findings without fixing. Output uses prefixed lines on stdout for the skill to parse:
- `ORPHAN_FILE:<scene-id>` — scene file exists without metadata row
- `ORPHAN_META:<scene-id>` — metadata row exists without scene file
- `MISSING_INTENT:<scene-id>` — in metadata but not in scene-intent
- `EXTRA_INTENT:<scene-id>` — in scene-intent but not in metadata
- `BAD_CHAPTER_REF:<scene-id>` — chapter-map references nonexistent scene
- `SEQ_GAP:<from>-<to>` — gap in sequence numbers
- `UNKNOWN_CHARACTER:<name>` — in scene-intent but not in characters.csv

Findings reported:
- Scene files without metadata rows (orphan files)
- Metadata rows without scene files (orphan metadata)
- scene-metadata.csv IDs not in scene-intent.csv (and vice versa)
- chapter-map.csv referencing scenes not in metadata
- Sequence gaps in scene-metadata.csv
- Characters in scene-intent.csv not found in characters.csv (name or alias)

#### 10. Unexpected Files Report

Flags directories and files at the project root or in `working/` that aren't part of the expected Storyforge structure. Uses prefixed lines:
- `UNEXPECTED_DIR:<path>` — directory not in expected structure
- `UNEXPECTED_FILE:<path>` — file not in expected structure

Expected top-level: `scenes/`, `reference/`, `working/`, `manuscript/`, `storyforge/`, `storyforge.yaml`, `CLAUDE.md`, `.gitignore`, `.git/`
Expected in `working/`: `logs/`, `evaluations/`, `plans/`, `scores/`, `costs/`, `reviews/`, `recommendations/`, `coaching/`, `enrich/`, `timeline/`, `backups/`, `scenes-setup/`, `pipeline.csv`, `craft-weights.csv`, `overrides.csv`, `exemplars.csv`, `dashboard.html`

Examples of unexpected: `draft/`, `docs/plans/`, `working/diagrams/`, `working/worldbuilding-decisions.md`

#### 11. Commit and Push

Unless `--dry-run`, commits all changes with message `Cleanup: project structure and working files` and pushes.

## Skill: `/storyforge:cleanup`

### Flow

1. **Read project state** — storyforge.yaml, CSVs, directory structure
2. **Run `storyforge-cleanup --dry-run`** — capture the structured report
3. **Present findings** to the author:
   - Summary of what the script will auto-fix
   - List of items needing author input
4. **Get approval** — run the script for real
5. **Handle interactive items** from the script's report:
   - **Unexpected dirs/files** — present each, ask keep or delete
   - **Character drift** — show characters in scenes not in characters.csv, ask whether to add entries
   - **Orphan scenes** — scene files without metadata or metadata without files, ask what to do for each
   - **CLAUDE.md regeneration** — if CLAUDE.md has scope creep (orchestration state, cycle tracking), offer to regenerate from template while preserving custom sections the author added
6. **Commit and push** any interactive changes

### CLAUDE.md Regeneration

When the skill detects CLAUDE.md content that doesn't match the current template structure:
1. Read current CLAUDE.md, identify custom sections (anything not in the template)
2. Show the author what would change vs what custom content would be preserved
3. Regenerate from template + preserved custom sections if approved

The script does not touch CLAUDE.md — too much judgment involved.

### No Coaching Level Adaptation

Cleanup is structural/mechanical work, not creative. The skill behaves the same regardless of coaching level.

## Gitignore Strategy

The `.gitignore` template has evolved over time but older projects didn't get updates. Key insight: **logs are write-once, never-read-back** — scripts extract response text and cost data immediately, then never touch the log files again. The 200MB+ of drafting and revision logs in each project are pure debugging artifacts.

For projects that already have log files committed to git, the script:
1. Updates `.gitignore`
2. Runs `git rm --cached` to untrack them
3. Commits the removal

This doesn't rewrite history. The repo stays large from old commits. A full `git filter-repo` to purge history is a separate, destructive operation — the skill should mention this option to the author but the script never does it.

## Data from Real Projects

Analysis of four active novel projects (night-watch, meridian-line, governor, rend):

| Project | Scenes | Working Dir | Log Files | Tracked in Git |
|---------|--------|-------------|-----------|----------------|
| night-watch | 100 | 313MB | 1,083 | Yes (1,088 files) |
| meridian-line | 64 | 168MB | 493 | No |
| governor | 97 | 98MB | 511 | Yes (511 files) |
| rend | 60 | 187MB | 463 | No |

**Log file breakdown (night-watch):**
- `drafting-*.log`: 101 files, 200MB (stream-json from scene writing)
- `revision-pass-*.log`: 46 files, 43MB
- `score-*.log`: 224 files, 22MB
- `review-*.log`: 53 files, 13MB
- `enrich-*.log`: 107 files, 4.7MB
- Scene `.txt`/`.json`: 427 files, 4.2MB

All log types are write-once. Value is extracted at creation time into scene files, cost ledger, score CSVs, and evaluation reports.

**Other findings:**
- All 4 projects missing `working/recommendations/` dir
- All 4 pipeline.csv files missing `scoring`, `review`, `recommendations` columns
- 3 of 4 have legacy `pipeline.yaml`
- 2 of 4 missing `.gitignore` or have incomplete one
- night-watch: 1 scene-intent entry without matching metadata, 1 seq gap
- night-watch: 74 characters in scenes vs 56 in characters.csv
- meridian-line: 42 characters in scenes vs 28 in characters.csv
- governor/rend: characters.csv barely populated (1 entry each)
