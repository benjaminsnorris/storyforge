---
name: cleanup
description: Project health check and cleanup — run diagnostics, fix CSV schema issues, strip scene artifacts, normalize data, and resolve structural drift. Use when the author wants to check project health, clean up their project, fix CSV issues, or when starting work on a project that may have drifted.
---

# Storyforge Cleanup

You are helping an author diagnose and fix structural issues in their Storyforge novel project. This skill runs the cleanup report, works through action items, and delegates to other skills/scripts as needed.

**When to use cleanup vs. other tools:**
- **Cleanup** — project structure health: missing CSVs, wrong columns, scene artifacts, CRLF, orphan files
- **Hone** — CSV data *content* quality: abstract briefs, overspecified beats, registry normalization
- **Elaborate** — building new structure from scratch

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory (this skill's directory → `skills/` → plugin root).

Store this resolved plugin path for use throughout the session.

## Step 1: Check for Existing Report

Look for `working/cleanup-report.csv` in the project directory.

- **If it exists and has pending items:** Read it and resume from where the last session left off. Skip to Step 3.
- **If it exists but all items are done:** Delete it, commit, and tell the author the project is clean.
- **If it doesn't exist:** Proceed to Step 2.

## Step 2: Generate the Report

Run the cleanup check:

```bash
cd <project_dir> && <plugin_path>/storyforge cleanup --csv
```

This writes `working/cleanup-report.csv` with columns:
`category|type|severity|file|detail|action|command|status`

Read the generated report. Commit it so the report is in git history:

```bash
git add working/cleanup-report.csv && git commit -m "Cleanup: generate health report" && git push
```

## Step 3: Present the Summary

Read `working/cleanup-report.csv`. Present a summary to the author:

**Errors** (severity=error) — these break the pipeline and must be fixed:
- List each error with its detail and action

**Warnings** (severity=warning, status=pending) — these should be fixed:
- List each warning with its detail and action

**Info** (severity=info) — informational, no action needed:
- Mention the count but don't list them unless asked

If there are no errors or warnings, tell the author the project is clean, delete the report file, commit, and you're done.

## Step 4: Work Through Action Items

Process action items in priority order: errors first, then warnings.

For each action item, determine how to handle it:

### Actions You Execute Directly

These are CSV edits you can make in this session:

| Type | What to Do |
|------|-----------|
| `rename_column` | Read the CSV file, rename the column in the header, write it back |
| `missing_column` | Read the CSV file, add the column to the header and empty values to all rows |
| `empty_csv` | Copy the header from the plugin's `templates/` directory |

After each fix, update the `status` field in `working/cleanup-report.csv` from `pending` to `done`, then commit:

```bash
git add <fixed_file> working/cleanup-report.csv && git commit -m "Cleanup: <what was fixed>" && git push
```

### Actions That Delegate to Scripts

These require running a Storyforge command. Present the command to the author using the Script Delegation Pattern:

| Type | Command |
|------|---------|
| `scene_artifacts` | `storyforge cleanup --scenes` |
| `crlf_line_endings` | `find reference working -name '*.csv' -exec sed -i '' $'s/\r$//' {} +` |
| `seq_needs_renumber` | `storyforge scenes-setup --renumber` |

After the command runs, update status to `done` and commit.

### Actions That Delegate to Skills

These need interactive work:

| Type | Skill |
|------|-------|
| `missing_csv` (reference/) | Invoke `elaborate` to build the missing data |
| `orphan_file` | Invoke `extract` to extract metadata from the scene |
| `missing_intent` / `extra_intent` | Invoke `hone --domain gaps` |
| `unknown_character` | Invoke `hone --domain registries` |

Mark status as `delegated` and note which skill was invoked. The delegated skill will handle the actual fix.

### Actions That Need Author Decision

These can't be automated:

| Type | What to Ask |
|------|------------|
| `orphan_meta` | "Scene {id} has metadata but no file. Should I remove the metadata rows, or create the scene file?" |
| `bad_chapter_ref` | "Chapter map references scene {id} which doesn't exist. Should I remove it from the chapter map?" |
| `extra_column` | "CSV has unexpected column {col}. Is this intentional?" |

Wait for the author's answer, then act and update status.

## Step 5: Clean Up

When all action items are `done`, `delegated`, or `skipped`:

1. Delete `working/cleanup-report.csv`
2. Commit: `git add -A && git commit -m "Cleanup: complete — all issues resolved" && git push`
3. Tell the author what was fixed

## Script Delegation Pattern

When delegating to an autonomous script, offer two options:

> **Option A: Run it here**
> I'll launch the command in this conversation.
>
> **Option B: Run it yourself**
> Copy this command and run it in a separate terminal:
> ```bash
> cd <project_dir> && <plugin_path>/storyforge <command> [flags]
> ```

Wait for the author's choice.

## Coaching Level Adaptation

Read the coaching level from `storyforge.yaml` (default: `full`).

- **full:** Execute fixes directly, explain what you're doing as you go.
- **coach:** Present each finding and ask if the author wants you to fix it or wants to do it themselves.
- **strict:** Present the full report and list of commands. Don't execute anything — let the author run each command.

## Commit After Every Fix

Every individual fix gets its own commit and push. Don't batch fixes — the git history should show each cleanup step clearly.
