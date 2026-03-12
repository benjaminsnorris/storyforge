# Scene Metadata Schema

Scenes are the atomic unit of a Storyforge project. Every scene has a YAML frontmatter block (in scene files) and a corresponding entry in `scenes/scene-index.yaml`.

## Core Fields

Every project uses these fields. They are not optional.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique scene identifier — a descriptive slug (e.g., `geometry-of-dying`, `sheriffs-ledger`). Must be unique across the project. |
| `title` | string | Scene title — evocative but not spoilery. Used for reference, not necessarily reader-facing. |
| `pov` | string | POV character's full name. Must match a character in the character bible. |
| `setting` | string | Where the scene takes place. Specific enough to visualize. |
| `characters` | list of strings | All characters present or referenced in the scene. |
| `function` | string | Why this scene exists for the story. Must be specific — not "advance the plot" but "she discovers he kept the letter." A scene without a clear function should be cut or merged. |
| `emotional_arc` | string | The emotional journey within the scene. Where does the reader start and end emotionally? |
| `threads` | list of strings | Story threads this scene touches. Must match threads tracked in the continuity tracker. |
| `motifs` | list of strings | Motifs or recurring elements that appear in this scene. |
| `timeline_position` | string or number | Position in the story's chronology. Can be a day number, a date, or a relative marker like "three weeks later." |
| `part` | number | Which part or act this scene belongs to. |
| `type` | string | Scene type. One of: `character`, `plot`, `world`, `action`, `transition`. Most scenes blend types — pick the dominant one. |
| `target_words` | number | Target word count for the scene. |
| `status` | string | One of: `pending`, `drafted`, `revised`, `cut`, `merged`. |

## Project Extensions

Defined in `storyforge.yaml` under `scene_extensions`. Each extension adds a custom field to the scene schema for project-specific tracking.

```yaml
# In storyforge.yaml:
scene_extensions:
  - name: tension_level
    type: integer
    description: "1-10 tension rating for pacing analysis"
  - name: magic_cost
    type: string
    description: "What the magic system costs in this scene"
```

These fields then appear in scene-index.yaml entries alongside the core fields.

## Scene Index Format

The master scene sequence lives in `scenes/scene-index.yaml`:

```yaml
# Scene Index — {Title}
# Scenes are the atomic unit. Chapters are assembled from scenes later.

scenes:
  - id: "geometry-of-dying"
    pov: "Character Name"
    words: 2500          # Actual word count (filled after drafting)
    function: "Specific function description"
    status: "drafted"
    action: null          # Revision action if applicable

  - id: "sheriffs-ledger"
    pov: "Other Character"
    words: null
    function: "Another specific function"
    status: "pending"
    action: null
```

The scene index is a lean tracking document — it has a subset of the metadata. The full metadata lives in the scene file's YAML frontmatter.

## Scene File Format

Individual scene files live in `scenes/` as Markdown with YAML frontmatter:

```markdown
---
id: "geometry-of-dying"
title: "The Finest Cartographer"
pov: "Dorren Hayle"
setting: "Pressure Cartography Office"
characters:
  - "Dorren Hayle"
  - "Tessa Merrin"
  - "Pell"
time_of_day: "morning"
timeline_position: 1
part: 1
type: "character"
function: "Establishes Dorren as institutional gatekeeper; introduces the assignment"
emotional_arc: "Controlled competence giving way to buried unease"
threads:
  - "institutional failure"
  - "chosen blindness"
motifs:
  - "maps/cartography"
  - "governance-as-weight"
status: "drafted"
---

Scene prose goes here...
```

## Scene ID Convention

Scene IDs are descriptive slugs that identify the scene by its content, not its position:

- **Format:** lowercase, hyphen-separated words (e.g., `geometry-of-dying`, `sheriffs-ledger`, `hidden-canyon`)
- **Length:** 2-5 words — specific enough to identify, short enough to type
- **Content-based:** Name describes what happens or the key image, not sequence
- **No numbers:** Avoid numeric IDs or positional prefixes — ordering lives in `scene-index.yaml` and `chapter-map.yaml`

Good: `geometry-of-dying`, `first-meridian`, `woman-in-cellars-light`
Bad: `1`, `scene-01`, `ch3-sc2`, `act1-opening`

For new scenes without clear content yet, use a working slug: `opening-chase`, `bridge-confrontation`, `quiet-morning`. Rename later if the scene evolves.

## What Is a Scene?

A scene is a single continuous pass of experience — one camera angle before the lens shifts. The moment the POV changes, or time jumps, or location shifts, that's a new scene.

Scenes are **not mini-chapters**. They may be extremely short (a single paragraph) or long (several pages). Length is dictated by the experience, not by structural convention.

Scenes are designed to be **reshuffled**. The ordering in `scene-index.yaml` is a working sequence, not a permanent assignment. If the story is better served by moving a scene, move it — that's what the index is for.
