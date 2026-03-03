# Storyforge

A novel-writing toolkit for Claude Code. Interactive skills guide creative development — world building, character work, voice discovery, scene design. Autonomous scripts handle execution — scene-by-scene drafting, multi-agent evaluation, configurable revision passes. Deep craft knowledge throughout.

## Installation

In any Claude Code session:

```
/plugin marketplace add benjaminsnorris/storyforge
/plugin install storyforge@storyforge-marketplace
```

That's it. Skills are available as `/storyforge`, `/storyforge:develop`, `/storyforge:voice`,
`/storyforge:scenes`, `/storyforge:plan-revision`, and `/storyforge:init`. Updates are
automatic.

### For development

If you're working on Storyforge itself, load from a local checkout:

```bash
git clone https://github.com/benjaminsnorris/storyforge.git ~/Developer/storyforge
claude --plugin-dir ~/Developer/storyforge
```

## Quick Start

### New project

In any directory, start a new Claude Code session and run:
```
/storyforge:init
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
| `/storyforge:init` | Initialize a new novel project |
| `/storyforge:develop` | World building, character development, story architecture, timeline |
| `/storyforge:voice` | Voice and style guide development |
| `/storyforge:scenes` | Scene index design, review, and editing |
| `/storyforge:plan-revision` | Plan custom revision passes from evaluation results |

## Project Setup

Run `/storyforge:init` in a new project directory. This creates:
- `storyforge.yaml` — project configuration
- `storyforge` — runner script for autonomous commands
- `reference/` — templates for world bible, character bible, etc.
- Standard directory structure (`scenes/`, `draft/`, `manuscript/`, `working/`)

Run autonomous scripts from your project root:

```bash
./storyforge write                    # Draft all remaining scenes
./storyforge write act1-sc01          # Draft a single scene
./storyforge evaluate                 # Run evaluation panel
./storyforge revise                   # Execute revision pipeline
```

## Project Structure

A Storyforge project looks like:

```
my-novel/
├── storyforge.yaml          # Project config + state
├── storyforge               # Runner script for autonomous commands
├── CLAUDE.md                # Auto-generated orchestration context
├── reference/               # World bible, character bible, voice guide, etc.
├── scenes/                  # Scene files with YAML frontmatter
│   └── scene-index.yaml     # Master scene sequence
├── draft/                   # Assembled chapter drafts
├── manuscript/              # Post-revision manuscript
└── working/                 # Logs, evaluations, plans
```

## Workflow

1. **`/storyforge:init`** — Create your project
2. **`/storyforge:develop`** — Build world, characters, story (any order, as many sessions as you need)
3. **`/storyforge:voice`** — Develop your voice and style guide
4. **`/storyforge:scenes`** — Design your scene index
5. **`./storyforge write`** — Draft scenes autonomously
6. **`./storyforge evaluate`** — Run the evaluation panel
7. **`/storyforge:plan-revision`** — Plan revision passes from evaluation findings
8. **`./storyforge revise`** — Execute revision passes

Or skip the sequence entirely and just run `/storyforge` — it knows where you are and what comes next.
