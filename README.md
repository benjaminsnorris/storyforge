# Storyforge

A novel-writing toolkit for authors, powered by Claude Code. Build structural integrity before writing prose — progressive elaboration catches continuity errors, knowledge violations, and pacing problems when they're CSV edits, not prose rewrites.

Interactive skills guide creative development. Autonomous scripts handle execution. Deep craft knowledge throughout — grounded in McKee, Swain, Story Grid, Kowal, Weiland, and Sanderson.

## Installation

In any Claude Code session:

```
/plugin marketplace add benjaminsnorris/storyforge
/plugin install storyforge@storyforge-marketplace
```

Skills are available as `/storyforge:forge`, `/storyforge:elaborate`, `/storyforge:extract`, `/storyforge:develop`, `/storyforge:voice`, `/storyforge:scenes`, and more. Updates are automatic.

### For development

```bash
git clone https://github.com/benjaminsnorris/storyforge.git ~/Developer/storyforge
claude --plugin-dir ~/Developer/storyforge
```

## Quick Start

### New project

```
/storyforge:init
```

Creates the project scaffold and asks whether to use the **elaboration pipeline** (recommended) or the **traditional pipeline**. The elaboration pipeline builds structural integrity before drafting; the traditional pipeline drafts first and revises after.

### Existing project — with manuscript

```
/storyforge:extract
```

Extracts structural data from existing prose into the three-file CSV model. Four phases: characterize the manuscript, extract skeleton metadata, extract narrative intent, extract drafting contracts with knowledge tracking. Produces a validated structural picture of the manuscript that reveals continuity issues, pacing problems, and expansion opportunities.

### Existing project — returning to work

```
/storyforge:forge
```

The hub reads your project state and suggests what to work on, or you can direct it.

## The Elaboration Pipeline

The core innovation: build the story's structural skeleton before writing prose, with validation at each stage.

```
Seed → Spine → Architecture → Scene Map → Briefs → Draft → Evaluate → Polish → Produce
```

**Spine** — the 5-10 irreducible story events. What must happen, and why.

**Architecture** — expand to 15-25 scenes. Assign POV, acts, value shifts (McKee), scene types (Swain action/sequel), turning points (Story Grid), and thread structure.

**Scene Map** — full scene count (40-60). Locations, timeline, characters present, MICE thread tracking (Kowal FILO nesting).

**Briefs** — the drafting contract per scene. Goal, conflict, outcome, crisis, decision (Story Grid Five Commandments). Knowledge entering and leaving. Key actions and dialogue. Continuity dependencies for parallel drafting.

**Validate** — structural checks run automatically: timeline consistency, knowledge flow, MICE nesting, pacing (flat polarity stretches, action/sequel rhythm, turning point variety), completeness.

**Draft** — scenes written in parallel waves from validated briefs. Each scene gets its brief + dependency context + voice guide + craft principles. No full manuscript in context — the brief is the contract.

**Evaluate** — six expert perspectives (developmental editor, line editor, genre expert, literary agent, first reader, writing coach). Findings categorized by fix location: brief, intent, structural, or craft. Structural findings route back upstream; craft findings go to polish.

**Polish** — one targeted prose pass on scenes with low craft scores. Voice, rhythm, naturalness. Not structural — that's already handled.

## Skills

| Skill | Purpose |
|-------|---------|
| `/storyforge:forge` | Hub — reads project state, recommends next action, routes to the right skill |
| `/storyforge:elaborate` | All creative development: spine → architecture → voice → map → briefs. Also character, world, and story architecture work. |
| `/storyforge:extract` | Reverse elaboration — extract structure from existing prose |
| `/storyforge:revise` | Plan + execute revision (upstream CSV fixes + prose polish). Absorbs planning, execution, and review. `--polish` for craft-only. |
| `/storyforge:score` | Craft + fidelity scoring |
| `/storyforge:publish` | Assemble web book + generate dashboard + push to bookshelf |
| `/storyforge:produce` | Epub, PDF, print formats |
| `/storyforge:init` | Initialize a new project |
| `/storyforge:cover` | Cover design |
| `/storyforge:title` | Title development |
| `/storyforge:press-kit` | Marketing materials |

## Scripts

Run from your project root via the `./storyforge` runner:

```bash
# Elaboration pipeline
./storyforge elaborate --stage spine         # Build the story spine
./storyforge elaborate --stage architecture  # Expand to full structure
./storyforge elaborate --stage map           # Complete scene map
./storyforge elaborate --stage briefs        # Write drafting contracts
./storyforge validate                        # Check structural integrity

# Extraction (for existing manuscripts)
./storyforge extract                         # Full extraction (all phases)
./storyforge extract --cleanup-only          # Normalize extracted data
./storyforge extract --expand                # Identify expansion opportunities

# Drafting and revision
./storyforge write                           # Draft scenes (parallel from briefs)
./storyforge evaluate                        # Run evaluation panel
./storyforge revise                          # Execute revision passes
./storyforge polish                          # Targeted prose polish
./storyforge score                           # Craft + fidelity scoring

# Production
./storyforge assemble --format epub          # Generate epub
./storyforge assemble --format web           # Generate web book
./storyforge visualize                       # Generate dashboard
```

All scripts support `--interactive` for supervised execution, `--dry-run` for preview, and `--coaching coach|strict` for coaching level override.

## Scene Data Model

Three pipe-delimited CSV files in `reference/`, joined by scene ID:

| File | Purpose | Key columns |
|------|---------|-------------|
| `scenes.csv` | Structural identity | id, seq, title, part, pov, location, timeline, type, status, word_count |
| `scene-intent.csv` | Narrative dynamics | function, scene_type (action/sequel), value_shift, turning_point, threads, characters, MICE threads |
| `scene-briefs.csv` | Drafting contracts | goal, conflict, outcome, crisis, decision, knowledge_in/out, key_actions, key_dialogue |

Python helpers provide a unified interface:

```python
from storyforge.elaborate import get_scene, get_scenes, validate_structure
scene = get_scene('hidden-canyon', 'reference/')
report = validate_structure('reference/')
```

See `references/scene-schema.md` for the full column reference and `references/scene-column-guide.md` for usage guidance.

## Dashboard

Multi-page manuscript visualization with three views:

- **Overview** — spine, POV distribution, value shift arc, scene rhythm
- **Structure** — character presence, thread weave, emotional terrain, location map, motifs, timeline
- **Scores** — craft heatmap, genre/character/act scores, narrative radar, brief fidelity

Generate with `./storyforge visualize` or `/storyforge:visualize`.

## Coaching Levels

Control Claude's role via `project.coaching_level` in storyforge.yaml:

- **`full`** (default) — Claude as creative partner. Proposes, drafts, revises. Elaboration stages run autonomously with PR review gates.
- **`coach`** — Claude as dramaturg. Presents options, asks questions, never writes prose. Author makes all creative decisions.
- **`strict`** — Claude as continuity editor. Reports data, runs validation, produces constraint lists. The validation engine becomes the product — exhaustive structural checking that's genuinely hard for humans across 50+ scenes.

Override per-session: `--coaching coach` on any script, or `STORYFORGE_COACHING=coach` env var.

## Craft References

| Document | Content |
|----------|---------|
| `references/craft-engine.md` | Prose craft principles (scene craft, prose craft, character craft, rules to break) |
| `references/structural-craft.md` | Structural principles (value shifts, scene rhythm, Five Commandments, MICE threads, knowledge flow) |
| `references/scoring-rubrics.md` | 25 craft principles scored 1-5 with literary exemplars |
| `references/scene-schema.md` | Three-file CSV column reference |
| `references/scene-column-guide.md` | Why each column matters and how to improve it |

## Project Structure

```
my-novel/
├── storyforge.yaml          # Project config + state
├── storyforge               # Runner script
├── CLAUDE.md                # Project-specific instructions
├── reference/
│   ├── scenes.csv           # Structural identity
│   ├── scene-intent.csv     # Narrative dynamics
│   ├── scene-briefs.csv     # Drafting contracts
│   ├── character-bible.md
│   ├── world-bible.md
│   ├── story-architecture.md
│   ├── voice-guide.md
│   └── characters.csv, locations.csv, threads.csv, motif-taxonomy.csv
├── scenes/                  # Scene prose (pure markdown, no frontmatter)
├── briefs/                  # Extended briefs for complex scenes (optional)
├── manuscript/
│   └── press-kit/
└── working/
    ├── pipeline.csv         # Pipeline manifest
    ├── scores/              # Scoring cycles
    ├── evaluations/         # Evaluation reports
    ├── plans/               # Revision plans
    ├── reviews/             # Pipeline reviews
    ├── validation/          # Validation reports
    └── logs/
```
