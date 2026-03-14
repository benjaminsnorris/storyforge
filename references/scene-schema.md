# Scene Metadata Schema

Scenes are the atomic unit of a Storyforge project. Scene files are **pure prose** (no YAML frontmatter) — the filename is the scene ID. All metadata lives in two canonical CSV files: `reference/scene-metadata.csv` and `reference/scene-intent.csv`.

## Data Storage

Scene data is split across two pipe-delimited CSV files:

- **`reference/scene-metadata.csv`** — structural and tracking metadata (POV, setting, part, status, word counts)
- **`reference/scene-intent.csv`** — creative intent data (function, emotional arc, characters, threads, motifs)

Both files use pipe (`|`) as the field delimiter. Array values within a single column use semicolon (`;`) as the separator. The first row is always the header. The `id` column appears first in both files and is the join key.

### Legacy Format

If a project has `scenes/scene-index.yaml` but no `scene-metadata.csv`, it is using the legacy YAML format. Run `./storyforge migrate --execute` to convert to CSV. As of v0.22.0, all scripts require CSV — YAML fallbacks have been removed.

## Core Fields

### metadata.csv columns

| Column | Type | Description |
|--------|------|-------------|
| `id` | string | Unique scene identifier — a descriptive slug (e.g., `geometry-of-dying`, `sheriffs-ledger`). Must be unique across the project. Also the scene filename (`scenes/{id}.md`). |
| `seq` | integer | Sequence number controlling scene order. Scenes are sorted by `seq` for reading order. |
| `title` | string | Scene title — evocative but not spoilery. Used for reference, not necessarily reader-facing. |
| `pov` | string | POV character's full name. Must match a character in the character bible. |
| `location` | string | The physical location where this scene takes place. Use a short, reusable label — the name of the place, not a description. If two scenes happen in the same place, they should have the same location string. When `reference/locations.csv` exists, values are normalized against canonical entries during enrichment and visualization. |
| `part` | integer | Which part or act this scene belongs to. |
| `type` | string | Scene type. One of: `character`, `plot`, `world`, `action`, `transition`. Most scenes blend types — pick the dominant one. |
| `timeline_day` | integer or string | Position in the story's chronology. Can be a day number, a date, or a relative marker. |
| `time_of_day` | string | Time of day (e.g., `morning`, `afternoon`, `evening`, `night`). |
| `status` | string | One of: `pending`, `drafted`, `revised`, `cut`, `merged`. |
| `word_count` | integer | Actual word count (filled after drafting, 0 if not yet drafted). |
| `target_words` | integer | Target word count for the scene. |

### intent.csv columns

| Column | Type | Description |
|--------|------|-------------|
| `id` | string | Scene ID — must match the `id` in metadata.csv. |
| `function` | string | Why this scene exists for the story. Must be specific — not "advance the plot" but "she discovers he kept the letter." A scene without a clear function should be cut or merged. |
| `emotional_arc` | string | The emotional journey within the scene. Where does the reader start and end emotionally? |
| `characters` | array | All characters present or referenced in the scene. Semicolon separated (e.g., `Dorren Hayle;Tessa Merrin;Pell`). When `reference/characters.csv` exists, names are normalized against canonical entries during enrichment and visualization. |
| `threads` | array | Story threads this scene touches. Semicolon separated. Must match threads tracked in the continuity tracker. |
| `motifs` | array | Motifs or recurring elements that appear in this scene. Semicolon separated. |
| `notes` | string | Free-form notes about the scene. |

## CSV Format Conventions

- **Delimiter:** `|` (pipe character)
- **Array separator:** `;` (semicolon) within a single column — e.g., `thread-a;thread-b;thread-c`
- **Header row:** Always present, always the first line
- **No quoting:** Values should not contain pipe characters; if unavoidable, rephrase the value
- **Empty values:** Leave the field empty between delimiters (e.g., `id||title` means the second field is empty)
- **Encoding:** UTF-8

### Example metadata.csv

```
id|seq|title|pov|location|part|type|timeline_day|time_of_day|status|word_count|target_words
geometry-of-dying|1|The Geometry of Dying|Dorren Hayle|Pressure Cartography Office|1|character|1|morning|drafted|2400|2500
sheriffs-ledger|2|The Sheriff's Ledger|Kael Maren|Deep Archive|1|plot|2|afternoon|pending|0|1500
```

### Example intent.csv

```
id|function|emotional_arc|characters|threads|motifs|notes
geometry-of-dying|Establishes Dorren as institutional gatekeeper|Controlled competence to buried unease|Dorren Hayle;Tessa Merrin;Pell|institutional failure;chosen blindness|maps/cartography;governance-as-weight|
sheriffs-ledger|Kael discovers archive inconsistencies|Scholarly calm to urgent alarm|Kael Maren;Dorren Hayle|the anomaly;archive corruption|blindness/seeing|
```

## Project Extensions

Defined in `storyforge.yaml` under `scene_extensions`. Each extension adds a custom column to `metadata.csv` for project-specific tracking.

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

These fields appear as additional columns in `metadata.csv` after the core columns.

## Scene File Format

Individual scene files live in `scenes/` as **pure Markdown with no frontmatter**:

```markdown
Scene prose goes here. The filename is the scene ID.

No YAML frontmatter block. All metadata lives in metadata.csv and intent.csv.
The file `scenes/geometry-of-dying.md` contains only the prose for that scene.
```

The filename (minus the `.md` extension) is the scene ID. For example, the file `scenes/geometry-of-dying.md` corresponds to the row with `id=geometry-of-dying` in both CSV files.

## Scene ID Convention

Scene IDs are descriptive slugs that identify the scene by its content, not its position:

- **Format:** lowercase, hyphen-separated words (e.g., `geometry-of-dying`, `sheriffs-ledger`, `hidden-canyon`)
- **Length:** 2-5 words — specific enough to identify, short enough to type
- **Content-based:** Name describes what happens or the key image, not sequence
- **No numbers:** Avoid numeric IDs or positional prefixes — ordering lives in the `seq` column of `metadata.csv` and in `chapter-map.csv`
- **Also the filename:** The scene ID is the filename in `scenes/` (e.g., `geometry-of-dying` → `scenes/geometry-of-dying.md`)

Good: `geometry-of-dying`, `first-meridian`, `woman-in-cellars-light`
Bad: `1`, `scene-01`, `ch3-sc2`, `act1-opening`

For new scenes without clear content yet, use a working slug: `opening-chase`, `bridge-confrontation`, `quiet-morning`. Rename later if the scene evolves.

## What Is a Scene?

A scene is a single continuous pass of experience — one camera angle before the lens shifts. The moment the POV changes, or time jumps, or location shifts, that's a new scene.

Scenes are **not mini-chapters**. They may be extremely short (a single paragraph) or long (several pages). Length is dictated by the experience, not by structural convention.

Scenes are designed to be **reshuffled**. The ordering in `metadata.csv` (the `seq` column) is a working sequence, not a permanent assignment. If the story is better served by moving a scene, move it — that's what the sequence number is for.
