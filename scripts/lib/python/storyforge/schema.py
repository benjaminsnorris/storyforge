"""CSV schema validation for Storyforge scene data.

Defines allowed values for every column across the three scene CSV files
and provides a fast validation function that checks all non-empty cells.
"""

import os

from .elaborate import _read_csv, _FILE_MAP
from .enrich import load_alias_map


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
#   integer   — must parse as int
#   boolean   — must be true, false, or empty
#   free_text — no value constraint

COLUMN_SCHEMA = {
    # scenes.csv
    'id':           {'type': 'free_text'},
    'seq':          {'type': 'integer'},
    'title':        {'type': 'free_text'},
    'part':         {'type': 'integer'},
    'pov':          {'type': 'registry', 'registry': 'characters.csv', 'array': False},
    'location':     {'type': 'registry', 'registry': 'locations.csv', 'array': False},
    'timeline_day': {'type': 'integer'},
    'time_of_day':  {'type': 'enum', 'values': VALID_TIMES},
    'duration':     {'type': 'free_text'},
    'type':         {'type': 'enum', 'values': VALID_TYPES},
    'status':       {'type': 'enum', 'values': VALID_STATUSES},
    'word_count':   {'type': 'integer'},
    'target_words': {'type': 'integer'},

    # scene-intent.csv
    'function':       {'type': 'free_text'},
    'action_sequel':  {'type': 'enum', 'values': VALID_ACTION_SEQUEL},
    'emotional_arc':  {'type': 'free_text'},
    'value_at_stake': {'type': 'registry', 'registry': 'values.csv', 'array': False},
    'value_shift':    {'type': 'enum', 'values': VALID_VALUE_SHIFTS},
    'turning_point':  {'type': 'enum', 'values': VALID_TURNING_POINTS},
    'characters':     {'type': 'registry', 'registry': 'characters.csv', 'array': True},
    'on_stage':       {'type': 'registry', 'registry': 'characters.csv', 'array': True},
    'mice_threads':   {'type': 'free_text'},

    # scene-briefs.csv
    'goal':            {'type': 'free_text'},
    'conflict':        {'type': 'free_text'},
    'outcome':         {'type': 'enum', 'values': VALID_OUTCOMES},
    'crisis':          {'type': 'free_text'},
    'decision':        {'type': 'free_text'},
    'knowledge_in':    {'type': 'free_text'},
    'knowledge_out':   {'type': 'free_text'},
    'key_actions':     {'type': 'free_text'},
    'key_dialogue':    {'type': 'free_text'},
    'emotions':        {'type': 'free_text'},
    'motifs':          {'type': 'registry', 'registry': 'motif-taxonomy.csv', 'array': True},
    'continuity_deps': {'type': 'free_text'},
    'has_overflow':    {'type': 'boolean'},
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
    if project_dir:
        reg_dir = os.path.join(project_dir, 'reference')
        for col_schema in COLUMN_SCHEMA.values():
            if col_schema['type'] == 'registry':
                csv_name = col_schema['registry']
                if csv_name not in registries:
                    path = os.path.join(reg_dir, csv_name)
                    registries[csv_name] = load_alias_map(path)

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

    return {
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'errors': errors,
    }
