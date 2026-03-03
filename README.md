# Storyforge

A novel-writing toolkit for Claude Code. Interactive skills guide creative development — world building, character work, voice discovery, scene design. Autonomous scripts handle execution — scene-by-scene drafting, multi-agent evaluation, configurable revision passes. Deep craft knowledge throughout.

## Installation

### Install Skills (global — available in all projects)

Symlink each skill into your Claude Code skills directory:

```bash
STORYFORGE=~/Developer/storyforge

for skill in storyforge storyforge-init storyforge-develop storyforge-voice storyforge-scenes storyforge-plan-revision; do
  ln -sf "$STORYFORGE/.claude/skills/$skill" ~/.claude/skills/"$skill"
done
```

To verify:
```bash
ls ~/.claude/skills/storyforge*/
```

You should see six directories, each containing a SKILL.md.

### Install Scripts (per-project)

The autonomous scripts (drafting, evaluation, revision) run from within a Storyforge project. `storyforge-init` copies them into new projects automatically.

To add scripts to an existing project:
```bash
cp -r ~/Developer/storyforge/scripts /path/to/your/project/
chmod +x /path/to/your/project/scripts/storyforge-*
```

### Uninstall

```bash
for skill in storyforge storyforge-init storyforge-develop storyforge-voice storyforge-scenes storyforge-plan-revision; do
  rm -f ~/.claude/skills/"$skill"
done
```

## Quick Start

### New project

In any directory, start a new Claude Code session and run:
```
/storyforge-init
```

This creates the project scaffold, reference doc templates, and storyforge.yaml config.

### Existing project

In a Storyforge project directory:
```
/storyforge
```

The hub reads your project state and suggests what to work on, or you can direct it.

## Skills

| Skill | Purpose |
|-------|---------|
| `/storyforge` | Hub — orchestrator, status, "surprise me" mode |
| `/storyforge-init` | Initialize a new novel project |
| `/storyforge-develop` | World building, character development, story architecture, timeline |
| `/storyforge-voice` | Voice and style guide development |
| `/storyforge-scenes` | Scene index design, review, and editing |
| `/storyforge-plan-revision` | Plan custom revision passes from evaluation results |

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/storyforge-write` | Autonomous scene-by-scene drafting |
| `scripts/storyforge-evaluate` | Multi-agent evaluation panel (6 evaluators + synthesis) |
| `scripts/storyforge-revise` | Execute revision passes from revision-plan.yaml |

## Project Structure

A Storyforge project looks like:

```
my-novel/
├── storyforge.yaml          # Project config + state
├── CLAUDE.md                # Auto-generated orchestration context
├── reference/               # World bible, character bible, voice guide, etc.
├── scenes/                  # Scene files with YAML frontmatter
│   └── scene-index.yaml     # Master scene sequence
├── draft/                   # Assembled chapter drafts
├── manuscript/              # Post-revision manuscript
├── scripts/                 # Autonomous execution scripts
│   └── prompts/evaluators/  # Evaluator personas
└── working/                 # Logs, evaluations, plans
```

## Workflow

1. **`/storyforge-init`** — Create your project
2. **`/storyforge-develop`** — Build world, characters, story (any order, as many sessions as you need)
3. **`/storyforge-voice`** — Develop your voice and style guide
4. **`/storyforge-scenes`** — Design your scene index
5. **`scripts/storyforge-write`** — Draft scenes autonomously
6. **`scripts/storyforge-evaluate`** — Run the evaluation panel
7. **`/storyforge-plan-revision`** — Plan revision passes from evaluation findings
8. **`scripts/storyforge-revise`** — Execute revision passes

Or skip the sequence entirely and just run `/storyforge` — it knows where you are and what comes next.
