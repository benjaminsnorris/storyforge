"""CSV schema validation for Storyforge scene data.

Defines allowed values for every column across the three scene CSV files
and provides a fast validation function that checks all non-empty cells.
"""

import os
import re

from .elaborate import _read_csv, _FILE_MAP
from .enrich import load_alias_map, load_mice_registry, VALID_MICE_TYPES


# ============================================================================
# Enum definitions — allowed values for constrained columns
# ============================================================================

VALID_TYPES = frozenset({
    'action', 'character', 'confrontation', 'dialogue', 'introspection',
    'plot', 'revelation', 'transition', 'world',
})

VALID_TIMES = frozenset({
    'morning', 'afternoon', 'evening', 'night', 'dawn', 'dusk',
})

VALID_ACTION_SEQUEL = frozenset({'action', 'sequel'})

VALID_OUTCOMES = frozenset({'yes', 'no', 'yes-but', 'no-and'})

VALID_STATUSES = frozenset({
    'spine', 'architecture', 'mapped', 'briefed', 'drafted', 'polished',
})

VALID_VALUE_SHIFTS = frozenset({
    '+/-', '-/+', '+/++', '-/--', '+/+', '-/-',
})

VALID_TURNING_POINTS = frozenset({'action', 'revelation'})


# ============================================================================
# Column schema — constraint type and config for every column
# ============================================================================

# Constraint types:
#   enum      — value must be in a fixed set
#   registry  — each semicolon-separated value must exist in a registry CSV
#   mice      — MICE thread format (+/-type:name) with registry validation
#   integer   — must parse as int
#   boolean   — must be true, false, or empty
#   free_text — no value constraint
#
# Each entry also carries:
#   file        — which CSV file owns this column
#   stage       — elaboration stage that populates it
#   description — human-readable description

COLUMN_SCHEMA = {
    # scenes.csv
    'id': {
        'type': 'free_text', 'file': 'scenes.csv', 'stage': 'spine',
        'description': 'Unique scene identifier — a descriptive slug (e.g., hidden-canyon). Also the filename (scenes/{id}.md).',
    },
    'seq': {
        'type': 'integer', 'file': 'scenes.csv', 'stage': 'spine',
        'description': 'Reading order. Scenes are sorted by seq.',
    },
    'title': {
        'type': 'free_text', 'file': 'scenes.csv', 'stage': 'spine',
        'description': 'Scene title — evocative, used for reference.',
    },
    'part': {
        'type': 'integer', 'file': 'scenes.csv', 'stage': 'architecture',
        'description': 'Which act/part this scene belongs to.',
    },
    'pov': {
        'type': 'registry', 'registry': 'characters.csv', 'array': False,
        'file': 'scenes.csv', 'stage': 'architecture',
        'description': 'POV character. Normalized against reference/characters.csv.',
    },
    'location': {
        'type': 'registry', 'registry': 'locations.csv', 'array': False,
        'file': 'scenes.csv', 'stage': 'map',
        'description': 'Physical location. Normalized against reference/locations.csv.',
    },
    'timeline_day': {
        'type': 'integer', 'file': 'scenes.csv', 'stage': 'map',
        'description': 'Chronological position (day number within the story).',
    },
    'time_of_day': {
        'type': 'enum', 'values': VALID_TIMES,
        'file': 'scenes.csv', 'stage': 'map',
        'description': 'Time of day when the scene takes place.',
    },
    'duration': {
        'type': 'free_text', 'file': 'scenes.csv', 'stage': 'map',
        'description': 'In-story duration (e.g., "2 hours", "30 minutes").',
    },
    'type': {
        'type': 'enum', 'values': VALID_TYPES,
        'file': 'scenes.csv', 'stage': 'map',
        'description': 'Narrative purpose of the scene.',
    },
    'status': {
        'type': 'enum', 'values': VALID_STATUSES,
        'file': 'scenes.csv', 'stage': 'all',
        'description': 'Elaboration depth — tracks how far the scene has progressed through the pipeline.',
    },
    'word_count': {
        'type': 'integer', 'file': 'scenes.csv', 'stage': 'draft',
        'description': 'Actual word count (0 until drafted).',
    },
    'target_words': {
        'type': 'integer', 'file': 'scenes.csv', 'stage': 'map',
        'description': 'Target word count for the scene.',
    },

    # scene-intent.csv
    'function': {
        'type': 'free_text', 'file': 'scene-intent.csv', 'stage': 'spine',
        'description': 'Why this scene exists — must be specific and testable.',
    },
    'action_sequel': {
        'type': 'enum', 'values': VALID_ACTION_SEQUEL,
        'file': 'scene-intent.csv', 'stage': 'architecture',
        'description': 'Action/sequel pattern (Swain): action = goal/conflict/outcome, sequel = reaction/dilemma/decision.',
    },
    'emotional_arc': {
        'type': 'free_text', 'file': 'scene-intent.csv', 'stage': 'architecture',
        'description': 'Emotional journey: start to end (e.g., "controlled competence to buried unease").',
    },
    'value_at_stake': {
        'type': 'registry', 'registry': 'values.csv', 'array': False,
        'file': 'scene-intent.csv', 'stage': 'architecture',
        'description': 'The abstract value being tested. Normalized against reference/values.csv (McKee).',
    },
    'value_shift': {
        'type': 'enum', 'values': VALID_VALUE_SHIFTS,
        'file': 'scene-intent.csv', 'stage': 'architecture',
        'description': 'Polarity change (Story Grid). A scene that doesn\'t shift a value is a nonevent.',
    },
    'turning_point': {
        'type': 'enum', 'values': VALID_TURNING_POINTS,
        'file': 'scene-intent.csv', 'stage': 'architecture',
        'description': 'What turns the scene — action (character does something) or revelation (new information).',
    },
    'characters': {
        'type': 'registry', 'registry': 'characters.csv', 'array': True,
        'file': 'scene-intent.csv', 'stage': 'map',
        'description': 'All characters present or referenced. Normalized against reference/characters.csv.',
    },
    'on_stage': {
        'type': 'registry', 'registry': 'characters.csv', 'array': True,
        'file': 'scene-intent.csv', 'stage': 'map',
        'description': 'Characters physically present (subset of characters).',
    },
    'mice_threads': {
        'type': 'mice', 'registry': 'mice-threads.csv',
        'file': 'scene-intent.csv', 'stage': 'map',
        'description': 'MICE thread operations: +type:name (open) or -type:name (close). FILO nesting order (Kowal).',
    },

    # scene-briefs.csv
    'goal': {
        'type': 'free_text', 'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'POV character\'s concrete objective entering the scene (Swain).',
    },
    'conflict': {
        'type': 'free_text', 'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'What specifically opposes the goal.',
    },
    'outcome': {
        'type': 'enum', 'values': VALID_OUTCOMES,
        'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'How the scene ends for the POV character (Weiland).',
    },
    'crisis': {
        'type': 'free_text', 'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'The dilemma: best bad choice or irreconcilable goods (Story Grid).',
    },
    'decision': {
        'type': 'free_text', 'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'What the character actively chooses in response to the crisis.',
    },
    'knowledge_in': {
        'type': 'registry', 'registry': 'knowledge.csv', 'array': True,
        'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'Fact IDs the POV character knows entering. Normalized against reference/knowledge.csv.',
    },
    'knowledge_out': {
        'type': 'registry', 'registry': 'knowledge.csv', 'array': True,
        'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'Fact IDs the POV character knows leaving. Includes knowledge_in plus anything new learned.',
    },
    'key_actions': {
        'type': 'free_text', 'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'Concrete things that happen in this scene.',
    },
    'key_dialogue': {
        'type': 'free_text', 'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'Specific lines or exchanges that must appear.',
    },
    'emotions': {
        'type': 'free_text', 'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'Emotional beats in sequence as they occur through the scene.',
    },
    'motifs': {
        'type': 'registry', 'registry': 'motif-taxonomy.csv', 'array': True,
        'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'Recurring images/symbols deployed. Normalized against reference/motif-taxonomy.csv.',
    },
    'continuity_deps': {
        'type': 'scene_ids', 'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'Scene IDs this scene depends on (for parallel drafting). Each entry must exist in scenes.csv.',
    },
    'has_overflow': {
        'type': 'boolean', 'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'Whether briefs/{id}.md exists for extended detail.',
    },
}


# ============================================================================
# Validation
# ============================================================================

def _check_enum(value: str, allowed: frozenset) -> bool:
    """Check if a value is in the allowed enum set (case-insensitive)."""
    return value.strip().lower() in allowed


def _check_integer(value: str) -> bool:
    """Check if a value parses as an integer."""
    try:
        int(value.strip())
        return True
    except ValueError:
        return False


def _check_boolean(value: str) -> bool:
    """Check if a value is a valid boolean."""
    return value.strip().lower() in ('true', 'false', '')


def _check_mice(value: str, alias_map: dict, type_map: dict) -> list[dict]:
    """Check mice_threads entries for format, type, and name validity.

    Returns a list of error dicts, one per bad entry.  Each has keys
    'entry' (the raw text) and 'reason' (what's wrong).
    """
    problems = []
    for entry in value.split(';'):
        entry = entry.strip()
        if not entry:
            continue

        # Check format: must be +type:name or -type:name
        if len(entry) < 2 or entry[0] not in ('+', '-') or ':' not in entry[1:]:
            problems.append({'entry': entry, 'reason': 'invalid format (expected +type:name or -type:name)'})
            continue

        rest = entry[1:]
        type_part, _, name_part = rest.partition(':')
        type_part = type_part.strip().lower()
        name_part = name_part.strip()

        if not type_part or not name_part:
            problems.append({'entry': entry, 'reason': 'missing type or name'})
            continue

        if type_part not in VALID_MICE_TYPES:
            problems.append({'entry': entry, 'reason': f'invalid type "{type_part}" (expected: milieu, inquiry, character, event)'})
            continue

        # Check name against registry (if available)
        if alias_map and name_part.lower() not in alias_map:
            problems.append({'entry': entry, 'reason': f'thread name "{name_part}" not in mice-threads.csv'})
            continue

        # Check type matches registry (if available)
        if alias_map and type_map:
            canonical = alias_map.get(name_part.lower())
            if canonical and canonical in type_map:
                expected_type = type_map[canonical]
                if type_part != expected_type:
                    problems.append({'entry': entry, 'reason': f'type "{type_part}" doesn\'t match registered type "{expected_type}"'})
                    continue

    return problems


def _check_registry(value: str, alias_map: dict, is_array: bool) -> list[str]:
    """Check registry values. Returns list of unresolved entries."""
    if not alias_map:
        return []  # Skip when registry not available

    failures = []
    if is_array:
        entries = [e.strip() for e in value.split(';') if e.strip()]
    else:
        entries = [value.strip()] if value.strip() else []

    for entry in entries:
        if entry.lower() not in alias_map:
            failures.append(entry)

    return failures


def validate_schema(ref_dir: str, project_dir: str | None = None) -> dict:
    """Validate all scene CSV values against column schema.

    Args:
        ref_dir: Path to reference/ directory containing scene CSVs.
        project_dir: Project root (enables registry lookups). If None,
            registry constraints are skipped.

    Returns:
        Dict with keys: passed (int), failed (int), skipped (int),
        errors (list of error dicts).
    """
    # Load registry alias maps if project_dir provided
    registries: dict[str, dict] = {}
    mice_alias: dict[str, str] = {}
    mice_type_map: dict[str, str] = {}
    if project_dir:
        reg_dir = os.path.join(project_dir, 'reference')
        for col_schema in COLUMN_SCHEMA.values():
            if col_schema['type'] == 'registry':
                csv_name = col_schema['registry']
                if csv_name not in registries:
                    path = os.path.join(reg_dir, csv_name)
                    registries[csv_name] = load_alias_map(path)
            elif col_schema['type'] == 'mice':
                csv_name = col_schema['registry']
                if csv_name not in registries:
                    path = os.path.join(reg_dir, csv_name)
                    mice_alias, mice_type_map = load_mice_registry(path)
                    registries[csv_name] = mice_alias

    # Collect all scene IDs for continuity_deps validation
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    all_scene_ids: set[str] = set()
    if os.path.isfile(scenes_path):
        for row in _read_csv(scenes_path):
            sid = row.get('id', '').strip()
            if sid:
                all_scene_ids.add(sid)

    passed = 0
    failed = 0
    skipped = 0
    errors: list[dict] = []

    for filename, columns in _FILE_MAP.items():
        path = os.path.join(ref_dir, filename)
        if not os.path.isfile(path):
            continue

        rows = _read_csv(path)

        for row in rows:
            scene_id = row.get('id', '?')

            for col in columns:
                if col == 'id':
                    continue  # Don't validate the join key

                value = row.get(col, '').strip()
                if not value:
                    skipped += 1
                    continue

                schema = COLUMN_SCHEMA.get(col)
                if not schema:
                    skipped += 1
                    continue

                constraint = schema['type']

                if constraint == 'free_text':
                    passed += 1

                elif constraint == 'enum':
                    if _check_enum(value, schema['values']):
                        passed += 1
                    else:
                        failed += 1
                        errors.append({
                            'file': filename,
                            'row': scene_id,
                            'column': col,
                            'value': value,
                            'constraint': 'enum',
                            'allowed': sorted(schema['values']),
                        })

                elif constraint == 'integer':
                    if _check_integer(value):
                        passed += 1
                    else:
                        failed += 1
                        errors.append({
                            'file': filename,
                            'row': scene_id,
                            'column': col,
                            'value': value,
                            'constraint': 'integer',
                        })

                elif constraint == 'boolean':
                    if _check_boolean(value):
                        passed += 1
                    else:
                        failed += 1
                        errors.append({
                            'file': filename,
                            'row': scene_id,
                            'column': col,
                            'value': value,
                            'constraint': 'boolean',
                            'allowed': ['true', 'false'],
                        })

                elif constraint == 'registry':
                    csv_name = schema['registry']
                    alias_map = registries.get(csv_name, {})
                    if not alias_map:
                        skipped += 1
                        continue

                    bad = _check_registry(value, alias_map,
                                          schema.get('array', False))
                    if not bad:
                        passed += 1
                    else:
                        failed += 1
                        errors.append({
                            'file': filename,
                            'row': scene_id,
                            'column': col,
                            'value': value,
                            'constraint': 'registry',
                            'registry': csv_name,
                            'unresolved': bad,
                        })

                elif constraint == 'mice':
                    problems = _check_mice(value, mice_alias, mice_type_map)
                    if not problems:
                        passed += 1
                    else:
                        failed += 1
                        errors.append({
                            'file': filename,
                            'row': scene_id,
                            'column': col,
                            'value': value,
                            'constraint': 'mice',
                            'problems': problems,
                        })

                elif constraint == 'scene_ids':
                    bad = [s.strip() for s in value.split(';')
                           if s.strip() and s.strip() not in all_scene_ids]
                    if not bad:
                        passed += 1
                    else:
                        failed += 1
                        errors.append({
                            'file': filename,
                            'row': scene_id,
                            'column': col,
                            'value': value,
                            'constraint': 'scene_ids',
                            'unresolved': bad,
                        })

    return {
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'errors': errors,
    }


# ============================================================================
# Schema dump — generate human-readable reference
# ============================================================================

def dump_schema_markdown() -> str:
    """Generate a Markdown column reference from COLUMN_SCHEMA.

    Groups columns by file and renders each as a table with constraint
    info and description. This is the canonical reference — scene-schema.md
    should be generated from this, not maintained by hand.
    """
    from .elaborate import _FILE_MAP

    file_labels = {
        'scenes.csv': 'scenes.csv — structural identity',
        'scene-intent.csv': 'scene-intent.csv — narrative dynamics',
        'scene-briefs.csv': 'scene-briefs.csv — drafting contracts',
    }

    lines: list[str] = []

    for filename, columns in _FILE_MAP.items():
        label = file_labels.get(filename, filename)
        lines.append(f'### {label}')
        lines.append('')
        lines.append('| Column | Constraint | Stage | Description |')
        lines.append('|--------|-----------|-------|-------------|')

        for col in columns:
            schema = COLUMN_SCHEMA.get(col, {})
            constraint = schema.get('type', '?')
            stage = schema.get('stage', '?')
            desc = schema.get('description', '')

            # Build constraint display
            if constraint == 'enum':
                values = ', '.join(sorted(schema.get('values', [])))
                constraint_str = f'enum: {values}'
            elif constraint == 'registry':
                reg = schema.get('registry', '?')
                arr = ' (array)' if schema.get('array') else ''
                constraint_str = f'registry: {reg}{arr}'
            elif constraint == 'mice':
                constraint_str = f'mice: {schema.get("registry", "?")}'
            else:
                constraint_str = constraint

            lines.append(f'| `{col}` | {constraint_str} | {stage} | {desc} |')

        lines.append('')

    return '\n'.join(lines)
