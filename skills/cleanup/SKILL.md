---
name: cleanup
description: Clean up and migrate a novel project — fix structural drift, prune working directory bloat, and resolve integrity issues interactively. Use when the author wants to tidy up their project, fix config drift, or bring the project in line with the current plugin version.
---

# Storyforge Cleanup Skill

You are helping an author clean up and migrate their Storyforge novel project. This skill handles structural drift, working directory bloat, config migration, and data integrity issues.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`
relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Read the following files to understand the current project:

- `storyforge.yaml` — project configuration
- `reference/scenes.csv (or legacy scene-metadata.csv)` — scene metadata
- `reference/scene-intent.csv` — scene intent data (if it exists)
- `reference/characters.csv` — character reference (if it exists)
- `reference/chapter-map.csv` — chapter mapping (if it exists)
- `working/pipeline.csv` — pipeline state (if it exists)
- `.gitignore` — current gitignore rules (if it exists)
- `CLAUDE.md` — project orientation file

Also scan:
- `ls scenes/` — scene files on disk
- `ls working/` — working directory contents
- `ls -d */` — top-level directories

## Step 2: Run the Cleanup Script in Dry-Run Mode

Present the author with two options:

> **Option A: Run it here**
> I'll run the cleanup script in this conversation to see what needs fixing.
>
> **Option B: Run it yourself**
> ```bash
> cd [project_dir] && [plugin_path]/scripts/storyforge-cleanup --dry-run
> ```

If Option A, run:
```bash
cd [project_dir] && [plugin_path]/scripts/storyforge-cleanup --dry-run
```

## Step 3: Present Findings

Summarize the script's dry-run output in two groups:

### Auto-fixable (the script handles these)
- Gitignore updates
- Missing directories
- storyforge.yaml migration
- Pipeline CSV columns
- Junk file cleanup (log files, status files, markers, batch payloads)
- Legacy file deletion
- Loose file reorganization
- Pipeline review deduplication

Present the count and nature of each fix. Ask the author for a go-ahead:

> "The script will [summary of changes]. Want me to run it?"

### Needs Your Input
Parse the report lines from the script output and present these interactively:

**Unexpected directories/files** (`UNEXPECTED_DIR:`, `UNEXPECTED_FILE:`):
For each one, ask: "I found `[path]` which isn't part of the standard Storyforge structure. Keep it or remove it?"

**Orphan scenes** (`ORPHAN_FILE:`, `ORPHAN_META:`):
- `ORPHAN_FILE`: "Scene file `[id].md` exists but has no metadata row. Add a row to scene-metadata.csv, or delete the file?"
- `ORPHAN_META`: "Metadata row for `[id]` exists but there's no scene file. Remove the row, or create a placeholder scene file?"

**Character drift** (`UNKNOWN_CHARACTER:`):
Present the full list of characters found in scenes but not in characters.csv. Ask: "These characters appear in your scenes but aren't in characters.csv. Want me to add entries for them?"

**Missing intent** (`MISSING_INTENT:`, `EXTRA_INTENT:`):
- `MISSING_INTENT`: "These scenes have metadata but no intent row: [list]. Add placeholder intent rows?"
- `EXTRA_INTENT`: "These intent rows have no matching metadata: [list]. Remove them?"

**Bad chapter references** (`BAD_CHAPTER_REF:`):
"Chapter map references these scenes that don't exist: [list]. These need manual attention in the chapter map."

**Sequence needs renumbering** (`SEQ_NEEDS_RENUMBER:`):
"Scene sequence numbers have gaps or non-integer values. Want me to renumber all scenes sequentially from 1? This preserves the current reading order — only the seq numbers change, not scene IDs or file names."

## Step 4: Run the Script

After the author approves, run the script without `--dry-run`:

```bash
cd [project_dir] && [plugin_path]/scripts/storyforge-cleanup
```

## Step 5: Handle Interactive Items

Apply the author's decisions from Step 3:
- Delete or keep unexpected files/dirs
- Add/remove CSV rows as directed
- Add character entries if requested
- Renumber sequences if requested (call `renumber_scenes` from csv.sh on `reference/scenes.csv (or legacy scene-metadata.csv)`)

After all interactive fixes, commit:
```bash
git add -A && git commit -m "Cleanup: resolve integrity issues" && git push
```

## Step 6: CLAUDE.md Check

Read the current `CLAUDE.md` and compare it to the template structure. If it contains orchestration state (cycle counts, scoring deltas, word count tracking, pipeline status), offer to regenerate:

> "Your CLAUDE.md contains orchestration state that should live in pipeline.csv and storyforge.yaml. I can regenerate it from the template while preserving your custom sections [list any detected custom sections]. Want me to do that?"

If the author agrees:
1. Read the CLAUDE.md template from the plugin's `templates/CLAUDE.md.template`
2. Populate with current project data from storyforge.yaml
3. Append any custom sections from the old CLAUDE.md
4. Write and commit

## Coaching Level

Cleanup is structural/mechanical work, not creative. Behavior is the same at all coaching levels.

## Step 7: Git History Note

If the script untracked previously-committed log files (via `git rm --cached`), mention:

> "I've stopped tracking log files in git going forward. Your repo history still contains the old log data, which adds [estimated size] to the repo. You can purge this with `git filter-repo` if you want to shrink it, but that rewrites history and requires force-pushing. This is optional and only matters if repo size bothers you."
