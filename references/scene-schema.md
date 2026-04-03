# Scene Data Schema

Scenes are the atomic unit of a Storyforge project. Scene files are **pure prose** (no YAML frontmatter) — the filename is the scene ID. All metadata lives in pipe-delimited CSV files in `reference/`.

## Data Model

Scene data is split across three CSV files, each with a clear purpose:

- **`reference/scenes.csv`** — structural identity and position (POV, location, timeline, status, word counts)
- **`reference/scene-intent.csv`** — narrative dynamics and tracking (function, value shifts, characters, MICE threads)
- **`reference/scene-briefs.csv`** — drafting contracts (goal, conflict, outcome, knowledge states, key actions/dialogue)

All three files use pipe (`|`) as the field delimiter, semicolon (`;`) for array values within a column, and `id` as the join key. The first row is always the header.

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

### scenes.csv — structural identity

| Column | Type | Populated at | Description |
|--------|------|-------------|-------------|
| `id` | string | spine | Unique scene identifier — a descriptive slug (e.g., `hidden-canyon`). Also the filename (`scenes/{id}.md`). |
| `seq` | integer | spine | Reading order. Scenes are sorted by `seq`. |
| `title` | string | spine | Scene title — evocative, used for reference. |
| `part` | integer | architecture | Which act/part this scene belongs to. |
| `pov` | string | architecture | POV character's full name. Must match the character bible. |
| `location` | string | map | Physical location — a short, reusable label. Normalized against `reference/locations.csv` if it exists. |
| `timeline_day` | integer/string | map | Chronological position (day number, date, or relative marker). |
| `time_of_day` | string | map | One of: `morning`, `afternoon`, `evening`, `night`, `dawn`, `dusk`. |
| `duration` | string | map | In-story duration (e.g., "2 hours", "30 minutes"). |
| `type` | string | map | Narrative purpose. One of: `character`, `plot`, `world`, `action`, `transition`, `confrontation`, `dialogue`, `introspection`, `revelation`. |
| `status` | string | all | Elaboration depth: `spine`, `architecture`, `mapped`, `briefed`, `drafted`, `polished`. |
| `word_count` | integer | draft | Actual word count (0 until drafted). |
| `target_words` | integer | map | Target word count for the scene. |

### scene-intent.csv — narrative dynamics

| Column | Type | Populated at | Description |
|--------|------|-------------|-------------|
| `id` | string | spine | Matches scenes.csv. |
| `function` | string | spine | Why this scene exists — must be specific and testable. Not "advance the plot" but "she discovers he kept the letter." |
| `action_sequel` | string | architecture | Action/sequel pattern (Swain): `action` (goal/conflict/outcome) or `sequel` (reaction/dilemma/decision). |
| `emotional_arc` | string | architecture | Emotional journey: start → end (e.g., "controlled competence to buried unease"). |
| `value_at_stake` | string | architecture | The abstract value being tested: safety, love, justice, truth, freedom, etc. (McKee). |
| `value_shift` | string | architecture | Polarity change: `+/-`, `-/+`, `+/++`, `-/--` (Story Grid). A scene that doesn't shift a value is a nonevent. |
| `turning_point` | string | architecture | `action` or `revelation` — vary these to prevent monotony (Story Grid). |
| `characters` | array | map | All characters present or referenced. Semicolon-separated. Normalized against `reference/characters.csv`. |
| `on_stage` | array | map | Characters physically present (subset of characters). |
| `mice_threads` | array | map | MICE thread operations: `+milieu:canyon` (open), `-inquiry:who-killed` (close). FILO nesting order (Kowal). |

### scene-briefs.csv — drafting contracts

| Column | Type | Populated at | Description |
|--------|------|-------------|-------------|
| `id` | string | brief | Matches scenes.csv. |
| `goal` | string | brief | POV character's concrete objective entering the scene (Swain). |
| `conflict` | string | brief | What specifically opposes the goal. |
| `outcome` | string | brief | How the scene ends: `yes`, `no`, `yes-but`, `no-and` (Weiland). |
| `crisis` | string | brief | The dilemma: best bad choice or irreconcilable goods (Story Grid Five Commandments). |
| `decision` | string | brief | What the character actively chooses. |
| `knowledge_in` | array | brief | Facts the POV character knows entering. Semicolon-separated. Must use **exact wording** matching prior scenes' `knowledge_out`. |
| `knowledge_out` | array | brief | Facts the POV character knows leaving. Includes `knowledge_in` plus anything new learned. |
| `key_actions` | array | brief | Concrete things that happen. Semicolon-separated. |
| `key_dialogue` | array | brief | Specific lines or exchanges that must appear. |
| `emotions` | array | brief | Emotional beats in sequence. |
| `motifs` | array | brief | Recurring images/symbols deployed. |
| `continuity_deps` | array | brief | Scene IDs this scene depends on (for parallel drafting). |
| `has_overflow` | boolean | brief | Whether `briefs/{id}.md` exists for extended detail. |

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

Run `./storyforge validate` to check structural integrity:

- **Identity:** Every ID in intent/briefs exists in scenes.csv
- **Completeness:** Required columns for the scene's status are populated
- **Timeline:** No backwards jumps without explicit markers
- **Knowledge flow:** knowledge_in references match prior scenes' knowledge_out
- **Thread management:** MICE threads nest in valid FILO order
- **Pacing:** No flat polarity stretches (3+ scenes); action/sequel rhythm varied; turning point types varied

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
