# Plugin Restructure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure Storyforge as a proper Claude Code plugin with root-level `skills/`, plugin-system installation, and a single project runner script replacing per-project script copies.

**Architecture:** Move skills from `.claude/skills/` to `skills/` at the repo root (plugin convention). Skills reference scripts via `./storyforge <command>` instead of hardcoded paths. A thin runner script in each project discovers the plugin installation and delegates. No changes to script logic or skill behavior — only where things live and how they're found.

**Tech Stack:** Bash, Claude Code plugin system, SKILL.md format

---

### Task 1: Move skills to root-level directory

**Files:**
- Move: `.claude/skills/storyforge/SKILL.md` → `skills/storyforge/SKILL.md`
- Move: `.claude/skills/storyforge-init/SKILL.md` → `skills/storyforge-init/SKILL.md`
- Move: `.claude/skills/storyforge-develop/SKILL.md` → `skills/storyforge-develop/SKILL.md`
- Move: `.claude/skills/storyforge-voice/SKILL.md` → `skills/storyforge-voice/SKILL.md`
- Move: `.claude/skills/storyforge-scenes/SKILL.md` → `skills/storyforge-scenes/SKILL.md`
- Move: `.claude/skills/storyforge-plan-revision/SKILL.md` → `skills/storyforge-plan-revision/SKILL.md`
- Delete: `.claude/skills/` (empty after moves)
- Delete: `.claude/` (empty after skills removed)

**Step 1: Create destination and move files**

```bash
cd ~/Developer/storyforge
mkdir -p skills
mv .claude/skills/storyforge skills/
mv .claude/skills/storyforge-init skills/
mv .claude/skills/storyforge-develop skills/
mv .claude/skills/storyforge-voice skills/
mv .claude/skills/storyforge-scenes skills/
mv .claude/skills/storyforge-plan-revision skills/
```

**Step 2: Clean up empty directories**

```bash
rmdir .claude/skills
rmdir .claude
```

**Step 3: Update plugin.json version**

Modify `.claude-plugin/plugin.json` — bump version to `0.2.0`:

```json
{
  "name": "storyforge",
  "description": "A novel-writing toolkit for Claude Code: interactive skills for creative development, autonomous scripts for execution, and deep craft knowledge throughout.",
  "version": "0.2.0",
  "author": {
    "name": "Ben Norris"
  },
  "license": "MIT",
  "keywords": ["writing", "novel", "fiction", "creative-writing", "storytelling"]
}
```

**Step 4: Verify directory structure**

```bash
ls skills/*/SKILL.md
```

Expected: six SKILL.md files listed.

```bash
ls .claude 2>/dev/null
```

Expected: error (directory should not exist).

**Step 5: Commit**

```bash
git add -A
git commit -m "Move skills to root-level skills/ directory (plugin convention)"
```

---

### Task 2: Create project runner script

**Files:**
- Create: `templates/storyforge-runner.sh`

**Step 1: Write the runner template**

Create `templates/storyforge-runner.sh` with this content:

```bash
#!/usr/bin/env bash
# Storyforge — delegates to installed plugin scripts
# Created by /storyforge:init. Do not edit.
set -euo pipefail

find_plugin() {
  # 1. Environment variable (set by claude --plugin-dir)
  if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
    echo "$CLAUDE_PLUGIN_ROOT"
    return 0
  fi
  # 2. Plugin cache (installed via marketplace)
  local cache_dir="$HOME/.claude/plugins/cache"
  if [[ -d "$cache_dir" ]]; then
    local found
    found=$(find "$cache_dir" -maxdepth 3 -name "plugin.json" \
      -path "*/storyforge/*" 2>/dev/null | sort -V | tail -1)
    if [[ -n "$found" ]]; then
      dirname "$(dirname "$found")"
      return 0
    fi
  fi
  # 3. Development checkout (common location)
  local dev_dir="$HOME/Developer/storyforge"
  if [[ -f "$dev_dir/.claude-plugin/plugin.json" ]]; then
    echo "$dev_dir"
    return 0
  fi
  echo "Error: Storyforge plugin not found." >&2
  echo "Install via: claude --plugin-dir /path/to/storyforge" >&2
  return 1
}

PLUGIN_ROOT="$(find_plugin)"
COMMAND="${1:?Usage: ./storyforge <write|evaluate|revise> [options]}"
shift

SCRIPT="$PLUGIN_ROOT/scripts/storyforge-$COMMAND"
if [[ ! -x "$SCRIPT" ]]; then
  echo "Error: Unknown command '$COMMAND'. Available: write, evaluate, revise" >&2
  exit 1
fi

exec "$SCRIPT" "$@"
```

**Step 2: Commit**

```bash
git add templates/storyforge-runner.sh
git commit -m "Add project runner script template"
```

---

### Task 3: Update skill files — plugin path instructions

All six SKILL.md files contain a "Locating the Storyforge Plugin" section that says to navigate up from the skill directory. This navigation still works with the new structure (`skills/storyforge/` → `skills/` → plugin root), but the script reference instructions need to change.

**Files:**
- Modify: `skills/storyforge/SKILL.md`
- Modify: `skills/storyforge-init/SKILL.md`
- Modify: `skills/storyforge-develop/SKILL.md`
- Modify: `skills/storyforge-voice/SKILL.md`
- Modify: `skills/storyforge-scenes/SKILL.md`
- Modify: `skills/storyforge-plan-revision/SKILL.md`

**Step 1: Update the plugin path section in all skills**

In each SKILL.md, find the "Locating the Storyforge Plugin" section and replace it with:

```markdown
## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`
and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.
```

The wording is slightly cleaner but the navigation logic is the same.

**Step 2: Update script references in the hub skill (`skills/storyforge/SKILL.md`)**

Find all instances where the skill tells the user to run a script. Replace:

```
./scripts/storyforge-write [options]
```

with:

```
./storyforge write [options]
```

And replace:

```
./scripts/storyforge-evaluate [options]
```

with:

```
./storyforge evaluate [options]
```

And replace:

```
./scripts/storyforge-revise [options]
```

with:

```
./storyforge revise [options]
```

Also replace any mention of "provide the full path from the plugin directory" with:

```
If the project doesn't have a `./storyforge` runner script, offer to create one
by copying the template from the plugin's `templates/storyforge-runner.sh`.
```

**Step 3: Update script references in the plan-revision skill (`skills/storyforge-plan-revision/SKILL.md`)**

Same replacements as Step 2 — find `./scripts/storyforge-revise` and replace with `./storyforge revise`.

Replace the "full path from the plugin directory" fallback with the same runner-creation offer.

**Step 4: Verify no remaining hardcoded script paths**

```bash
grep -r "scripts/storyforge-" skills/
```

Expected: no matches (all references should now use `./storyforge <command>` format).

**Step 5: Commit**

```bash
git add skills/
git commit -m "Update skill files for plugin structure and runner script references"
```

---

### Task 4: Update storyforge-init skill

**Files:**
- Modify: `skills/storyforge-init/SKILL.md`

**Step 1: Read the current init skill**

Read `skills/storyforge-init/SKILL.md` in full.

**Step 2: Replace the script-copying step**

Find the step that copies scripts into the project (currently Step 5 or similar — look for references to copying `scripts/` directory). Replace it with a step that creates the runner:

The new step should say:

```markdown
### Create Project Runner

Copy the runner script from the plugin's `templates/storyforge-runner.sh` to the
project root as `storyforge`. Make it executable:

\`\`\`bash
chmod +x storyforge
\`\`\`

This is the only Storyforge executable in the project. It delegates to the
installed plugin for `./storyforge write`, `./storyforge evaluate`, and
`./storyforge revise`.
```

**Step 3: Update the CLAUDE.md template generation**

Find where the init skill generates the project's CLAUDE.md. Update the scripts section from:

```
Scripts in `~/Developer/storyforge/scripts/`:
- `storyforge-write` — Autonomous scene drafting
- `storyforge-evaluate` — Multi-agent evaluation panel
- `storyforge-revise` — Execute revision pipeline
```

to:

```
Scripts (via project runner):
- `./storyforge write` — Autonomous scene drafting
- `./storyforge evaluate` — Multi-agent evaluation panel
- `./storyforge revise` — Execute revision pipeline
```

**Step 4: Remove any instructions about copying the scripts/ directory**

Search for and remove any language like "copy scripts", "cp -r scripts", or instructions to make scripts executable in the project.

**Step 5: Commit**

```bash
git add skills/storyforge-init/SKILL.md
git commit -m "Update init skill: create runner instead of copying scripts"
```

---

### Task 5: Update README.md

**Files:**
- Modify: `README.md`

**Step 1: Read current README**

Read `README.md` in full.

**Step 2: Replace installation instructions**

Replace the current symlink-based installation section with:

```markdown
## Installation

### For development (recommended while Storyforge is evolving)

```bash
claude --plugin-dir ~/Developer/storyforge
```

This loads Storyforge directly from your local checkout. Skills are available
as `/storyforge`, `/storyforge:develop`, etc. Edits to skills and scripts
take effect in your next Claude Code session.

### For distribution (future)

Storyforge can be distributed via a Claude Code marketplace. Users install with:

```bash
/plugin marketplace add benjaminsnorris/storyforge
/plugin install storyforge
```
```

**Step 3: Replace per-project scripts section**

Replace the "copy scripts to your project" instructions with:

```markdown
## Project Setup

Run `/storyforge:init` in a new project directory. This creates:
- `storyforge.yaml` — project configuration
- `storyforge` — runner script for autonomous commands
- `reference/` — templates for world bible, character bible, etc.
- Standard directory structure (`scenes/`, `draft/`, `manuscript/`, `working/`)

The runner script lets you invoke Storyforge's autonomous scripts from your project:

```bash
./storyforge write                    # Draft all remaining scenes
./storyforge write act1-sc01          # Draft a single scene
./storyforge evaluate                 # Run evaluation panel
./storyforge revise                   # Execute revision pipeline
```
```

**Step 4: Remove the manual symlink loop**

Delete the `for skill in storyforge storyforge-init...` shell loop and any references to symlinking skills into `~/.claude/skills/`.

**Step 5: Commit**

```bash
git add README.md
git commit -m "Update README for plugin-based installation"
```

---

### Task 6: Update CLAUDE.md template

**Files:**
- Modify: `templates/CLAUDE.md.template`

**Step 1: Read the current template**

Read `templates/CLAUDE.md.template` in full.

**Step 2: Update script references**

Replace any hardcoded script paths with runner commands:

- `~/Developer/storyforge/scripts/storyforge-write` → `./storyforge write`
- `~/Developer/storyforge/scripts/storyforge-evaluate` → `./storyforge evaluate`
- `~/Developer/storyforge/scripts/storyforge-revise` → `./storyforge revise`
- `./scripts/storyforge-write` → `./storyforge write`
- `./scripts/storyforge-evaluate` → `./storyforge evaluate`
- `./scripts/storyforge-revise` → `./storyforge revise`

Also update the scripts section to:

```markdown
## Scripts

Run autonomous scripts via the project runner:
- `./storyforge write` — Autonomous scene drafting
- `./storyforge evaluate` — Multi-agent evaluation panel
- `./storyforge revise` — Execute revision pipeline
```

**Step 3: Update skill references**

Replace skill invocation references if present:
- `/storyforge-develop` → `/storyforge:develop`
- `/storyforge-init` → `/storyforge:init`
- `/storyforge-voice` → `/storyforge:voice`
- `/storyforge-scenes` → `/storyforge:scenes`
- `/storyforge-plan-revision` → `/storyforge:plan-revision`

Note: `/storyforge` stays as-is (hub skill, same name).

**Step 4: Commit**

```bash
git add templates/CLAUDE.md.template
git commit -m "Update CLAUDE.md template for runner and namespaced skills"
```

---

### Task 7: Verify plugin loads correctly

**Step 1: Test plugin loading**

```bash
cd ~/Developer/storyforge
claude --plugin-dir . --print "List the available storyforge skills you can see"
```

Expected: Claude should list the storyforge skills with the `storyforge:` namespace prefix.

**Step 2: Test from a project directory**

```bash
cd ~/Developer/governor
claude --plugin-dir ~/Developer/storyforge --print "What storyforge skills are available?"
```

Expected: Same skill listing, confirming the plugin loads from a different working directory.

**Step 3: If tests fail, debug**

Check that `plugin.json` is valid JSON:
```bash
python3 -c "import json; json.load(open('.claude-plugin/plugin.json'))"
```

Check skills directory structure:
```bash
find skills -name "SKILL.md" -type f
```

Expected: six files, one per skill directory.

---

### Task 8: Remove old symlinks and migrate Governor

**Files:**
- Delete: `~/.claude/skills/storyforge` (symlink)
- Delete: `~/.claude/skills/storyforge-init` (symlink)
- Delete: `~/.claude/skills/storyforge-develop` (symlink)
- Delete: `~/.claude/skills/storyforge-voice` (symlink)
- Delete: `~/.claude/skills/storyforge-scenes` (symlink)
- Delete: `~/.claude/skills/storyforge-plan-revision` (symlink)
- Create: `~/Developer/governor/storyforge` (runner script)
- Modify: `~/Developer/governor/CLAUDE.md`

**Step 1: Remove old symlinks**

```bash
rm ~/.claude/skills/storyforge
rm ~/.claude/skills/storyforge-init
rm ~/.claude/skills/storyforge-develop
rm ~/.claude/skills/storyforge-voice
rm ~/.claude/skills/storyforge-scenes
rm ~/.claude/skills/storyforge-plan-revision
```

**Step 2: Create runner in Governor project**

Copy the runner template:
```bash
cp ~/Developer/storyforge/templates/storyforge-runner.sh ~/Developer/governor/storyforge
chmod +x ~/Developer/governor/storyforge
```

**Step 3: Test the runner**

```bash
cd ~/Developer/governor
./storyforge write --help 2>&1 | head -5
```

Expected: either help output from storyforge-write, or the usage header. Should not show "plugin not found" error.

**Step 4: Update Governor CLAUDE.md**

In `~/Developer/governor/CLAUDE.md`, replace the Storyforge scripts section:

From:
```markdown
Scripts in `~/Developer/storyforge/scripts/`:
- `storyforge-write` — Autonomous scene drafting
- `storyforge-evaluate` — Multi-agent evaluation panel
- `storyforge-revise` — Execute revision pipeline
```

To:
```markdown
Scripts (via project runner):
- `./storyforge write` — Autonomous scene drafting
- `./storyforge evaluate` — Multi-agent evaluation panel
- `./storyforge revise` — Execute revision pipeline
```

Also update skill references if present:
- `/storyforge-develop` → `/storyforge:develop`
- `/storyforge-voice` → `/storyforge:voice`
- `/storyforge-scenes` → `/storyforge:scenes`
- `/storyforge-plan-revision` → `/storyforge:plan-revision`

**Step 5: Commit Governor changes**

```bash
cd ~/Developer/governor
git add storyforge CLAUDE.md
git commit -m "Migrate to Storyforge plugin: add runner, update script references"
```

**Step 6: Commit any remaining Storyforge repo changes**

```bash
cd ~/Developer/storyforge
git status
# If anything is unstaged, add and commit
```
