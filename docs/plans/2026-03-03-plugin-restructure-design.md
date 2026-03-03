# Storyforge Plugin Restructure

**Date:** 2026-03-03
**Status:** Approved
**Goal:** Restructure Storyforge as a proper Claude Code plugin using the official plugin system, with clean script access from projects via a single runner script.

## Problem

Storyforge currently uses a non-standard installation model:

- Skills live at `.claude/skills/` instead of the plugin-standard `skills/`
- Installation is via manual symlinks from `~/.claude/skills/` to the repo
- Autonomous scripts are copied into each project's `scripts/` directory
- Projects hardcode the script path in CLAUDE.md
- No marketplace registration, no auto-updates, no standard discovery

This creates friction: users must know where Storyforge is installed, projects accumulate stale script copies, and updates require manual re-symlinking.

## Design

### Repo Structure

Restructure to follow Claude Code plugin conventions:

```
storyforge/
  .claude-plugin/
    plugin.json                    # Plugin manifest (name, version, etc.)
  skills/                          # Root-level (plugin convention)
    storyforge/SKILL.md            # Hub — status, routing, "surprise me"
    storyforge-init/SKILL.md       # Project initialization
    storyforge-develop/SKILL.md    # World, character, story, timeline
    storyforge-voice/SKILL.md      # Voice and style
    storyforge-scenes/SKILL.md     # Scene index management
    storyforge-plan-revision/SKILL.md  # Revision planning
  scripts/
    storyforge-write               # Autonomous scene drafting
    storyforge-evaluate            # Multi-agent evaluation
    storyforge-revise              # Revision execution
    lib/
      common.sh                    # Project root detection, YAML parsing, logging
      prompt-builder.sh            # Prompt construction helpers
      revision-passes.sh           # Revision orchestration
    prompts/                       # Evaluator personas
  references/
    craft-engine.md                # Foundational craft reference
  templates/
    reference/                     # Project reference doc templates
  docs/
    plans/                         # Design documents
  README.md
  .gitignore
```

### Installation

**Development workflow** (current user):
```bash
claude --plugin-dir ~/Developer/storyforge
```
This loads the plugin directly from the repo. Edits to skills and scripts are immediately available in the next Claude session.

**Distribution** (future users):

Create a marketplace (Git repo with `.claude-plugin/marketplace.json`) pointing to the Storyforge repo. Users install via:
```bash
/plugin marketplace add benjaminsnorris/storyforge-marketplace
/plugin install storyforge
```

The plugin gets cached to `~/.claude/plugins/cache/` and auto-updates when the marketplace is refreshed.

### Skill Namespacing

After installation, skills are invoked with the plugin namespace:

| Before | After |
|---|---|
| `/storyforge` | `/storyforge` |
| `/storyforge-develop` | `/storyforge:develop` |
| `/storyforge-init` | `/storyforge:init` |
| `/storyforge-voice` | `/storyforge:voice` |
| `/storyforge-scenes` | `/storyforge:scenes` |
| `/storyforge-plan-revision` | `/storyforge:plan-revision` |

The hub skill (`/storyforge`) remains the primary entry point. It routes to sub-skills as before.

### Project Runner Script

When `/storyforge:init` sets up a new project, it creates a single `storyforge` shell script at the project root. This is the only Storyforge file that lives in the project (besides `storyforge.yaml` and the author's content).

```bash
#!/usr/bin/env bash
# Storyforge — delegates to installed plugin scripts
# Created by /storyforge:init. Do not edit.
set -euo pipefail

find_plugin() {
  # 1. Check CLAUDE_PLUGIN_ROOT (set when running via --plugin-dir or plugin system)
  if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
    echo "$CLAUDE_PLUGIN_ROOT"
    return 0
  fi
  # 2. Search plugin cache
  local cache_dir="$HOME/.claude/plugins/cache"
  if [[ -d "$cache_dir" ]]; then
    local found
    found=$(find "$cache_dir" -maxdepth 3 -name "plugin.json" \
      -path "*/storyforge/*" 2>/dev/null | head -1)
    if [[ -n "$found" ]]; then
      dirname "$(dirname "$found")"
      return 0
    fi
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

Usage:
```bash
./storyforge write
./storyforge evaluate
./storyforge revise --pass prose-pattern-reduction
```

### Script Reference from Skills

Skills that need to tell the user to run a script use the runner command:

```
./storyforge write
```

If the runner doesn't exist in the project (pre-migration project or manual setup), the skill offers to create it or falls back to providing the direct path.

### Changes to `common.sh`

`get_plugin_dir()` currently resolves by walking up from `scripts/lib/` via symlink resolution. The logic works unchanged after restructuring — it still walks up from the script's real location to the repo/plugin root. The only difference is that the root is now the plugin cache directory instead of the git repo, but the relative structure (`scripts/lib/` is two levels below root) is preserved.

`detect_project_root()` is unchanged — walks up from `$PWD` looking for `storyforge.yaml`.

### Changes to `storyforge-init` Skill

When initializing a new project:

1. Creates directory structure, `storyforge.yaml`, reference templates — same as current
2. Creates the `storyforge` runner script at project root (**new**)
3. Sets runner as executable (`chmod +x`)
4. **Does not copy scripts** into the project
5. CLAUDE.md references `./storyforge write`, `./storyforge evaluate`, `./storyforge revise` — no hardcoded paths
6. Optionally adds `storyforge` to `.gitignore` (author's choice — the runner is generated and can be recreated, but committing it means collaborators can use it without init)

### Migration for Existing Projects

For The Governor and other existing Storyforge projects:

1. Delete local `scripts/` copies of Storyforge scripts (keep any project-specific scripts)
2. Add the `storyforge` runner script to project root
3. Update CLAUDE.md to reference `./storyforge write` instead of `~/Developer/storyforge/scripts/storyforge-write`
4. Remove old symlinks from `~/.claude/skills/` (the plugin system replaces them)

### What Stays the Same

- `storyforge.yaml` format and semantics
- Scene index, reference docs, manuscript structure
- Skill behavior (SKILL.md content) — same instructions, different location in repo
- Script logic — same code, accessed from plugin cache instead of local copy
- `detect_project_root()` and project-level file resolution

## Summary

| Component | Before | After |
|---|---|---|
| Skills in repo | `.claude/skills/` | `skills/` |
| Skills installation | Manual symlinks to `~/.claude/skills/` | Plugin system (`--plugin-dir` or marketplace) |
| Skills invocation | `/storyforge-develop` | `/storyforge:develop` |
| Scripts source | Copied per-project | Single source in plugin |
| Scripts invocation | `~/Developer/storyforge/scripts/storyforge-write` | `./storyforge write` |
| References/templates | Found via symlink resolution | Found via `get_plugin_dir()` from plugin install |
| Project footprint | `scripts/` dir + `storyforge.yaml` | `storyforge` runner + `storyforge.yaml` |
| Updates | Manual re-symlink | `--plugin-dir` auto-loads; marketplace auto-updates |
| Distribution | Clone repo + run symlink script | `/plugin install` from marketplace |

## Future Considerations

- **Marketplace creation**: When ready to distribute, create a marketplace repo with `marketplace.json` pointing to the Storyforge GitHub repo. Could also submit to the official Anthropic marketplace.
- **npm packaging**: The marketplace system supports npm as a plugin source. Could package Storyforge as an npm module for broader distribution.
- **Hooks**: Could add a `SessionStart` hook that detects `storyforge.yaml` in the project and automatically loads project context, similar to how superpowers loads its session hook.
