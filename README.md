# Storyforge

A novel-writing toolkit for Claude Code. Interactive skills guide creative development — world building, character work, voice discovery, scene design. Autonomous scripts handle execution — scene-by-scene drafting, multi-agent evaluation, configurable revision passes. Deep craft knowledge throughout.

## Installation

In any Claude Code session:

```
/plugin marketplace add benjaminsnorris/storyforge
/plugin install storyforge@storyforge-marketplace
```

That's it. Skills are available as `/storyforge:forge`, `/storyforge:develop`, `/storyforge:voice`,
`/storyforge:scenes`, `/storyforge:plan-revision`, `/storyforge:recommend`, `/storyforge:title`,
`/storyforge:press-kit`, `/storyforge:cover`, and `/storyforge:init`. Updates are automatic.

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
/storyforge:forge
```

The hub reads your project state and suggests what to work on, or you can direct it.

## Skills

| Skill | Purpose |
|-------|---------|
| `/storyforge:forge` | Hub — orchestrator, status, routes to other skills |
| `/storyforge:init` | Initialize a new novel project |
| `/storyforge:develop` | World building, character development, story architecture, timeline |
| `/storyforge:voice` | Voice and style guide development |
| `/storyforge:scenes` | Scene index design, review, and editing |
| `/storyforge:plan-revision` | Plan custom revision passes from evaluation results |
| `/storyforge:review` | Review revision results, map findings to changes, assess gaps |
| `/storyforge:recommend` | Assess project state, recommend the highest-value next action |
| `/storyforge:produce` | Chapter mapping, production settings, book assembly |
| `/storyforge:title` | Title and subtitle development, refinement, assessment |
| `/storyforge:press-kit` | Blurbs, jacket copy, author bio, social media, marketing materials |
| `/storyforge:cover` | Cover design — Claude-designed SVG artwork or AI-generated illustrations |

## Project Setup

Run `/storyforge:init` in a new project directory. This creates:
- `storyforge.yaml` — project configuration
- `storyforge` — runner script for autonomous commands
- `reference/` — templates for world bible, character bible, etc.
- Standard directory structure (`scenes/`, `working/`)

Run autonomous scripts from your project root:

```bash
./storyforge write                    # Draft all remaining scenes
./storyforge write act1-sc01          # Draft a single scene
./storyforge evaluate                 # Run evaluation panel
./storyforge revise                   # Execute revision pipeline
./storyforge assemble --format epub   # Generate epub
./storyforge assemble --format web    # Generate hostable web book
./storyforge cover --svg-only         # Preview generated cover
```

All scripts support `--interactive` for supervised execution and `--dry-run` for preview.

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
├── manuscript/
│   └── press-kit/           # Marketing materials (blurbs, jacket copy, bios)
└── working/
    ├── pipeline.yaml        # Pipeline manifest — tracks eval/revision cycles
    ├── evaluations/         # Evaluation reports per cycle
    ├── plans/               # Revision plans per cycle
    ├── reviews/             # Pipeline review reports
    └── logs/                # Execution logs
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
9. **`/storyforge:review`** — Assess revision results
10. **`/storyforge:recommend`** — Get the recommended next action based on project state
11. **`/storyforge:title`** — Develop or finalize the book title
12. **`/storyforge:produce`** — Map scenes to chapters, configure production settings
13. **`/storyforge:cover`** — Design a custom cover (SVG artwork or AI illustration)
14. **`/storyforge:press-kit`** — Generate blurbs, marketing copy, and press materials
15. **`./storyforge assemble`** — Generate epub, PDF, HTML, or web book

Steps 6-10 are a **pipeline cycle** — evaluate, plan, revise, review, recommend — tracked in `working/pipeline.yaml`. Each cycle links its evaluation, revision plan, and review report. Run as many cycles as the manuscript needs.

Or skip the sequence entirely and just run `/storyforge:forge` — it reads your project state and routes to the right skill.

## Coaching Levels

Control how proactive Claude is with creative decisions via `project.coaching_level` in storyforge.yaml:

- **`full`** (default) — Claude proposes, drafts, and revises. Maximum creative partnership.
- **`coach`** — Claude analyzes and guides but never writes prose. You write everything.
- **`strict`** — Claude only asks questions and produces checklists. Purely Socratic.

Override per-session with `--coaching coach` on any script, or `STORYFORGE_COACHING=coach` env var.
