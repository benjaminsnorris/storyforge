# Scenes Review Markdown Export/Import

**Date:** 2026-04-12
**Status:** Approved

## Problem

Reviewing and editing scene structural data across three separate CSV files is tedious. The author needs to open each file, find the scene by ID, cross-reference fields, and edit pipe-delimited values. A single markdown file per review session would make it easy to read all data for each scene, make edits inline, and push changes back.

## Solution

Two new storyforge commands:

- **`storyforge scenes-export`** — reads all three CSVs, merges by scene ID, writes a single markdown file
- **`storyforge scenes-import`** — parses edited markdown, diffs against current CSVs, updates only changed fields

## Markdown Format

One `## heading` per scene (the heading IS the scene ID), ordered by `seq`. Fields grouped under `### Structural`, `### Intent`, `### Brief` as `key: value` lines.

```markdown
## the-finest-cartographer

### Structural
seq: 1
title: The Finest Cartographer
part: 1
pov: Elara
location: The Observatory
timeline_day: 1
time_of_day: morning
duration: 2 hours
type: character
status: briefed
word_count: 2450
target_words: 2500

### Intent
function: Introduce protagonist and central mystery
action_sequel: action
emotional_arc: Controlled competence to buried unease
value_at_stake: truth
value_shift: +/-
turning_point: revelation
characters: Elara;Fen
on_stage: Elara;Fen
mice_threads: +inquiry:map-anomaly

### Brief
goal: Establish Elara's expertise and hint at anomaly
conflict: The map shows something that shouldn't exist
outcome: no
crisis: Whether to report the anomaly or investigate alone
decision: Investigate alone
knowledge_in: Standard cartographic methods
knowledge_out: Map contains an impossible feature
key_actions: Examines the map;Discovers the anomaly
key_dialogue: The coast doesn't match any survey
emotions: curiosity;unease
motifs: maps;precision
subtext: The tension between official truth and observed reality
continuity_deps:
has_overflow: false
physical_state_in:
physical_state_out:
```

### Field-to-file mapping

| Section | CSV file | Columns (excluding `id`) |
|---------|----------|-------------------------|
| Structural | `reference/scenes.csv` | seq, title, part, pov, location, timeline_day, time_of_day, duration, type, status, word_count, target_words |
| Intent | `reference/scene-intent.csv` | function, action_sequel, emotional_arc, value_at_stake, value_shift, turning_point, characters, on_stage, mice_threads |
| Brief | `reference/scene-briefs.csv` | goal, conflict, outcome, crisis, decision, knowledge_in, knowledge_out, key_actions, key_dialogue, emotions, motifs, subtext, continuity_deps, has_overflow, physical_state_in, physical_state_out |

### Design decisions

- **`id` is the heading, not a field.** It's the join key across all three CSVs and should not be edited through this tool.
- **All fields included even when empty.** The author can fill them in during review.
- **Empty markdown value = empty string in CSV.** No distinction between "missing" and "blank."

## Export Command

```
storyforge scenes-export [--scenes ID,...] [--act N] [--from-seq N[-M]] [--output PATH]
```

- Reads `reference/scenes.csv`, `reference/scene-intent.csv`, `reference/scene-briefs.csv`
- Uses `build_scene_list` + `apply_scene_filter` for filtering (excludes cut/merged scenes)
- Orders scenes by `seq`
- Default output: `working/scenes-review.md`

## Import Command

```
storyforge scenes-import [--input PATH] [--dry-run]
```

- Reads the markdown file (default: `working/scenes-review.md`)
- Parses into per-scene field dictionaries, keyed by section (Structural/Intent/Brief)
- For each scene + field, compares against the current CSV value via `get_field`
- Only calls `update_field` for values that differ
- Prints a change summary: `scene-id: field "old" -> "new"`
- `--dry-run` prints the summary without writing

### Parsing rules

1. `## scene-id` — starts a new scene (text after `## ` is the scene ID)
2. `### Structural` / `### Intent` / `### Brief` — switches the active section (determines target CSV)
3. `known_field: value` — sets a field (matched against the column list for the active section)
4. Lines without a recognized `field:` prefix — joined to the previous field's value with a space (handles accidental line wraps)
5. Blank lines — ignored

### Out of scope

- **Reordering scenes** — changing `seq` updates the field but doesn't reorder CSV rows. Use `renumber-seq` separately.
- **Adding/deleting scenes** — this is a review/edit tool, not a structural tool. Scenes not in the markdown are left untouched. Scenes in the markdown but not in the CSV are warned about and skipped.

## Implementation

Two new modules:

- `scripts/lib/python/storyforge/cmd_scenes_export.py`
- `scripts/lib/python/storyforge/cmd_scenes_import.py`

Register in `__main__.py` as `scenes-export` and `scenes-import`.

Both modules use:
- `storyforge.common.detect_project_root`, `log`
- `storyforge.csv_cli.get_field`, `update_field`
- `storyforge.scene_filter.build_scene_list`, `apply_scene_filter`
- `storyforge.cli.add_scene_filter_args`, `resolve_filter_args` (export only)

No new dependencies. All stdlib.
