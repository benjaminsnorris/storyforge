# CSV Schema Validation Design

**Date:** 2026-04-03
**Status:** Approved
**Issue:** Part of extraction/elaboration CSV normalization work

## Problem

No single source of truth defines what values are allowed in each CSV column. Validation catches structural issues (thread nesting, knowledge flow) but not basic data quality (wrong enum values, free-text names instead of IDs, non-integer seq values). After extraction or elaboration, there's no fast way to check whether every cell contains a valid value.

## Design

### New module: `scripts/lib/python/storyforge/schema.py`

Single source of truth for column constraints across all three scene CSV files.

### Column Schema

Every column gets a constraint type:

| Constraint | Behavior | Columns |
|-----------|----------|---------|
| `enum` | Value must be in a fixed set | type, time_of_day, action_sequel, outcome, status, value_shift, turning_point |
| `registry` | Each value (semicolon-split for arrays) must exist as an id or alias in a registry CSV | pov, location, characters, on_stage, threads, motifs |
| `integer` | Must parse as int | seq, part, timeline_day, word_count, target_words |
| `boolean` | Must be true, false, or empty | has_overflow |
| `free_text` | No value constraint (only checked for non-empty when present) | id, title, function, emotional_arc, value_at_stake, duration, goal, conflict, crisis, decision, knowledge_in, knowledge_out, key_actions, key_dialogue, emotions, continuity_deps |

### Enum Allowed Values

| Column | Values | Source |
|--------|--------|--------|
| `type` | action, character, confrontation, dialogue, introspection, plot, revelation, transition, world | enrich.py VALID_TYPES |
| `time_of_day` | morning, afternoon, evening, night, dawn, dusk | enrich.py VALID_TIMES |
| `action_sequel` | action, sequel | Swain scene/sequel theory |
| `outcome` | yes, no, yes-but, no-and | Weiland scene outcomes |
| `status` | spine, architecture, mapped, briefed, drafted, polished | Elaboration pipeline stages |
| `value_shift` | +/-, -/+, +/++, -/--, +/+, -/- | Story Grid polarity notation (flat shifts included for diagnostic value) |
| `turning_point` | action, revelation | Story Grid turning point types |

### Registry Mappings

| Column | Registry CSV | Array? |
|--------|-------------|--------|
| `pov` | characters.csv | no (single value) |
| `location` | locations.csv | no (single value) |
| `characters` | characters.csv | yes (semicolon-separated) |
| `on_stage` | characters.csv | yes |
| `threads` | threads.csv | yes |
| `motifs` | motif-taxonomy.csv | yes |

Registry validation uses `load_alias_map()` — accepts ids, names, or aliases. Skipped gracefully when registry files don't exist (new projects).

### API

```python
def validate_schema(ref_dir: str, project_dir: str | None = None) -> dict:
    """Validate all scene CSV values against column schema.
    
    Args:
        ref_dir: Path to reference/ directory containing scene CSVs.
        project_dir: Project root (enables registry lookups). If None,
            registry constraints are skipped.
    
    Returns:
        {
            "passed": int,       # cells that passed validation
            "failed": int,       # cells that failed
            "skipped": int,      # empty cells (not checked)
            "errors": [          # one entry per failure
                {
                    "file": "scenes.csv",
                    "row": "hidden-canyon",     # scene id
                    "column": "type",
                    "value": "setup",
                    "constraint": "enum",
                    "allowed": ["action", "character", ...],
                }
            ]
        }
```

For registry errors, the `allowed` field is replaced with `"registry": "characters.csv"`.

### Integration

Add `--schema` flag to `storyforge-validate`:

```
./storyforge validate --schema          # Schema validation only
./storyforge validate --schema --json   # JSON output
./storyforge validate                   # Existing structural validation (unchanged)
./storyforge validate --all             # Both structural + schema
```

Human-readable output groups errors by file, then by constraint type:

```
Schema validation: 340 passed, 5 failed, 82 skipped

scenes.csv:
  hidden-canyon | type: "setup" — not in allowed values (action, character, ...)
  sheriffs-ledger | time_of_day: "midday" — not in allowed values (morning, afternoon, ...)

scene-intent.csv:
  hidden-canyon | pov: "Emmett Slade" — not in characters.csv (expected id like "emmett-slade")
  hidden-canyon | characters: "Cora (referenced)" — not in characters.csv
```

### Testing

Test file: `tests/test-schema.sh`

Tests cover:
- Each enum column accepts valid values, rejects invalid
- Registry columns accept ids, names, and aliases; reject unknowns
- Integer columns accept numbers, reject text
- Boolean column accepts true/false/empty
- Empty cells are skipped (not errors)
- Missing registry files cause graceful skip (not crash)
- End-to-end: validate_schema on test fixtures returns expected pass/fail counts

### Files to create/modify

| File | Action |
|------|--------|
| `scripts/lib/python/storyforge/schema.py` | Create — schema definition + validate_schema() |
| `scripts/storyforge-validate` | Modify — add --schema and --all flags |
| `tests/test-schema.sh` | Create — schema validation tests |
