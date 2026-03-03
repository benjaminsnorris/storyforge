# Scene Metadata Schema

Scenes are the atomic unit of a Storyforge project. Every scene has a YAML frontmatter block (in scene files) and a corresponding entry in `scenes/scene-index.yaml`.

## Core Fields

Every project uses these fields. They are not optional.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique scene identifier (e.g., `act1-sc01`, `p2-sc15`). Must be unique across the project. |
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
  - id: "act1-sc01"
    pov: "Character Name"
    words: 2500          # Actual word count (filled after drafting)
    function: "Specific function description"
    status: "drafted"
    action: null          # Revision action if applicable

  - id: "act1-sc02"
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
id: "act1-sc01"
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

## Naming Conventions

Scene IDs should follow the pattern `{grouping}-sc{number}`:
- `act1-sc01` — grouped by act
- `p1-sc01` — grouped by part
- `ch01-sc01` — grouped by chapter (if chapter structure is known early)

The grouping prefix should match the structural unit defined in the story architecture. Numbering is sequential within the group.
