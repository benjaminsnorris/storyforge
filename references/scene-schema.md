# Scene Data Schema

Scenes are the atomic unit of a Storyforge project. Scene files are **pure prose** (no YAML frontmatter) — the filename is the scene ID. All metadata lives in pipe-delimited CSV files in `reference/`.

## Data Model

Scene data is split across three CSV files, each with a clear purpose:

- **`reference/scenes.csv`** — structural identity and position (POV, location, timeline, status, word counts)
- **`reference/scene-intent.csv`** — narrative dynamics and tracking (function, value shifts, characters, MICE threads)
- **`reference/scene-briefs.csv`** — drafting contracts (goal, conflict, outcome, knowledge states, key actions/dialogue)

All three files use pipe (`|`) as the field delimiter, semicolon (`;`) for array values within a column, and `id` as the join key. The first row is always the header. The `id` column in intent and briefs matches scenes.csv.

### Python Helpers

The `storyforge.elaborate` module provides a unified interface over all three files:

```python
from storyforge.elaborate import get_scene, get_scenes, update_scene, add_scenes

scene = get_scene('hidden-canyon', 'reference/')           # All columns merged
scenes = get_scenes('reference/', columns=['id', 'pov', 'value_shift'])  # Selective
scenes = get_scenes('reference/', filters={'pov': 'Lena Callis'})       # Filtered
update_scene('hidden-canyon', 'reference/', {'status': 'drafted', 'word_count': '2400'})
```

### Legacy Format

Projects created before v0.40.0 used a two-file model with fewer columns. Run `./storyforge extract` to populate the three-file model from existing prose. The write and score scripts auto-detect which model is in use.

## Column Reference

**Source of truth:** `scripts/lib/python/storyforge/schema.py` — the `COLUMN_SCHEMA` dict defines every column's constraint type, allowed values, registry mappings, pipeline stage, and description. The tables below are generated from that schema. To regenerate:

```python
from storyforge.schema import dump_schema_markdown
print(dump_schema_markdown())
```

### Constraint Types

| Type | Validation | Normalization |
|------|-----------|---------------|
| `enum` | Value must be in a fixed set | N/A — values are already canonical |
| `registry` | Each value must exist as id, name, or alias in a registry CSV | Resolved to canonical id via alias map |
| `mice` | Format `+/-type:name`, valid type, name in registry | Name resolved via alias map, type corrected |
| `integer` | Must parse as int | N/A |
| `boolean` | Must be `true`, `false`, or empty | N/A |
| `free_text` | No constraint | N/A |

### Registry Files

| Registry | Columns | Used by |
|----------|---------|---------|
| `characters.csv` | id, name, aliases, role | pov, characters, on_stage |
| `locations.csv` | id, name, aliases | location |
| `values.csv` | id, name, aliases | value_at_stake |
| `motif-taxonomy.csv` | id, name, aliases, tier | motifs |
| `mice-threads.csv` | id, name, type, aliases | mice_threads |

### scenes.csv — structural identity

| Column | Constraint | Stage | Description |
|--------|-----------|-------|-------------|
| `id` | free_text | spine | Unique scene identifier — a descriptive slug (e.g., hidden-canyon). Also the filename (scenes/{id}.md). |
| `seq` | integer | spine | Reading order. Scenes are sorted by seq. |
| `title` | free_text | spine | Scene title — evocative, used for reference. |
| `part` | integer | architecture | Which act/part this scene belongs to. |
| `pov` | registry: characters.csv | architecture | POV character. Normalized against reference/characters.csv. |
| `location` | registry: locations.csv | map | Physical location. Normalized against reference/locations.csv. |
| `timeline_day` | integer | map | Chronological position (day number within the story). |
| `time_of_day` | enum: afternoon, dawn, dusk, evening, morning, night | map | Time of day when the scene takes place. |
| `duration` | free_text | map | In-story duration (e.g., "2 hours", "30 minutes"). |
| `type` | enum: action, character, confrontation, dialogue, introspection, plot, revelation, transition, world | map | Narrative purpose of the scene. |
| `status` | enum: architecture, briefed, drafted, mapped, polished, spine | all | Elaboration depth — tracks how far the scene has progressed through the pipeline. |
| `word_count` | integer | draft | Actual word count (0 until drafted). |
| `target_words` | integer | map | Target word count for the scene. |

### scene-intent.csv — narrative dynamics

| Column | Constraint | Stage | Description |
|--------|-----------|-------|-------------|
| `id` | free_text | spine | Join key — matches scenes.csv. |
| `function` | free_text | spine | Why this scene exists — must be specific and testable. |
| `action_sequel` | enum: action, sequel | architecture | Action/sequel pattern (Swain): action = goal/conflict/outcome, sequel = reaction/dilemma/decision. |
| `emotional_arc` | free_text | architecture | Emotional journey: start to end (e.g., "controlled competence to buried unease"). |
| `value_at_stake` | registry: values.csv | architecture | The abstract value being tested. Normalized against reference/values.csv (McKee). |
| `value_shift` | enum: +/+, +/++, +/-, -/+, -/-, -/-- | architecture | Polarity change (Story Grid). A scene that doesn't shift a value is a nonevent. |
| `turning_point` | enum: action, revelation | architecture | What turns the scene — action (character does something) or revelation (new information). |
| `characters` | registry: characters.csv (array) | map | All characters present or referenced. Normalized against reference/characters.csv. |
| `on_stage` | registry: characters.csv (array) | map | Characters physically present (subset of characters). |
| `mice_threads` | mice: mice-threads.csv | map | MICE thread operations: +type:name (open) or -type:name (close). FILO nesting order (Kowal). |

### scene-briefs.csv — drafting contracts

| Column | Constraint | Stage | Description |
|--------|-----------|-------|-------------|
| `id` | free_text | brief | Join key — matches scenes.csv. |
| `goal` | free_text | brief | POV character's concrete objective entering the scene (Swain). |
| `conflict` | free_text | brief | What specifically opposes the goal. |
| `outcome` | enum: no, no-and, yes, yes-but | brief | How the scene ends for the POV character (Weiland). |
| `crisis` | free_text | brief | The dilemma: best bad choice or irreconcilable goods (Story Grid). |
| `decision` | free_text | brief | What the character actively chooses in response to the crisis. |
| `knowledge_in` | free_text | brief | Facts the POV character knows entering. Must use exact wording matching prior knowledge_out. |
| `knowledge_out` | free_text | brief | Facts the POV character knows leaving. Includes knowledge_in plus anything new learned. |
| `key_actions` | free_text | brief | Concrete things that happen in this scene. |
| `key_dialogue` | free_text | brief | Specific lines or exchanges that must appear. |
| `emotions` | free_text | brief | Emotional beats in sequence as they occur through the scene. |
| `motifs` | registry: motif-taxonomy.csv (array) | brief | Recurring images/symbols deployed. Normalized against reference/motif-taxonomy.csv. |
| `continuity_deps` | free_text | brief | Scene IDs this scene depends on (for parallel drafting). |
| `has_overflow` | boolean | brief | Whether briefs/{id}.md exists for extended detail. |

## Elaboration Stages

The `status` field tracks how deeply a scene has been elaborated:

| Status | What's populated | Pipeline stage |
|--------|-----------------|---------------|
| `spine` | id, seq, title, function | Stage 1: irreducible story events |
| `architecture` | + part, pov, action_sequel, emotional_arc, value_shift, turning_point | Stage 2: structure |
| `mapped` | + location, timeline_day, time_of_day, duration, type, characters, on_stage, mice_threads | Stage 3: full scene map |
| `briefed` | + goal, conflict, outcome, crisis, decision, knowledge_in/out, key_actions, key_dialogue, emotions, motifs, continuity_deps | Stage 4: drafting contracts |
| `drafted` | + word_count (prose exists in scenes/{id}.md) | After drafting |
| `polished` | Prose has been through craft polish | After polish pass |

## Validation

Run `./storyforge validate` to check both structural integrity and schema compliance:

**Structural checks:**
- **Identity:** Every ID in intent/briefs exists in scenes.csv
- **Completeness:** Required columns for the scene's status are populated
- **Timeline:** No backwards jumps without explicit markers
- **Knowledge flow:** knowledge_in references match prior scenes' knowledge_out
- **Thread management:** MICE threads nest in valid FILO order
- **Pacing:** No flat polarity stretches (3+ scenes); action/sequel rhythm varied; turning point types varied

**Schema checks:**
- **Enum values:** Constrained columns contain only allowed values
- **Registry references:** Character, location, value, motif, and MICE thread names resolve against their registry CSVs
- **Integers:** Numeric columns contain valid integers
- **MICE format:** Thread operations match `+/-type:name` format with valid types

Use `--no-schema` to skip schema validation. Use `--json` for machine-readable output.

## Scoring

Two types of scoring reference scene data:

- **Structural scoring** (`score_structure`): Pre-draft check on brief quality (0-5 per scene). Checks goal/conflict/outcome completeness, value shift, crisis, knowledge flow.
- **Brief fidelity scoring** (`fidelity-scores.csv`): Post-draft check — did the prose deliver what the brief promised? Scores 9 elements: goal, conflict, outcome, crisis, decision, key_actions, key_dialogue, emotions, knowledge.

## CSV Format Conventions

- **Delimiter:** `|` (pipe character)
- **Array separator:** `;` (semicolon) within a single column
- **Header row:** Always present, always the first line
- **No quoting:** Values should not contain pipe characters
- **Empty values:** Leave the field empty between delimiters
- **Encoding:** UTF-8

## Scene File Format

Scene files live in `scenes/` as **pure Markdown with no frontmatter**:

```
scenes/hidden-canyon.md → id is "hidden-canyon"
```

The file contains only prose. All metadata lives in the CSV files.

## Scene ID Convention

- **Format:** lowercase, hyphen-separated words (e.g., `hidden-canyon`, `sheriffs-ledger`)
- **Length:** 2-5 words — specific enough to identify, short enough to type
- **Content-based:** Describes what happens or the key image, not sequence position
- **No numbers:** Ordering lives in the `seq` column
- **Also the filename:** `scenes/{id}.md`

## What Is a Scene?

A scene is a single continuous pass of experience — one camera angle before the lens shifts. The moment the POV changes, or time jumps, or location shifts, that's a new scene.

Scenes are designed to be **reshuffled**. The `seq` column is a working sequence, not a permanent assignment.
