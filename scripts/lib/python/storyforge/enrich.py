"""Metadata enrichment helpers for Storyforge.

Replaces the data-heavy functions from ``scripts/storyforge-enrich`` --
response parsing, field extraction, alias normalization, validation, and
CSV manipulation.  Designed to be called from bash via the CLI interface
or imported directly by other Python modules.
"""

import json
import os
import re
import sys
import tempfile

from .prompts import (
    _read_csv_header_and_rows,
    read_csv_field,
    _resolve_scenes_csv,
    _resolve_intent_csv,
    _resolve_briefs_csv,
)


# ============================================================================
# Constants
# ============================================================================

#: Fields stored in scenes.csv (enrichable via enrich)
METADATA_FIELDS = frozenset({
    'pov', 'location', 'time_of_day', 'duration', 'type',
})

#: Fields stored in scene-intent.csv
INTENT_FIELDS = frozenset({
    'action_sequel', 'emotional_arc', 'value_at_stake', 'value_shift',
    'turning_point', 'characters', 'on_stage', 'mice_threads',
})

#: Fields stored in scene-briefs.csv
BRIEFS_FIELDS = frozenset({
    'goal', 'conflict', 'outcome', 'crisis', 'decision',
    'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
    'emotions', 'motifs',
})

#: All enrichable fields
ALL_FIELDS = METADATA_FIELDS | INTENT_FIELDS | BRIEFS_FIELDS

#: Valid scene type values
VALID_TYPES = frozenset({
    'action', 'character', 'confrontation', 'dialogue', 'introspection',
    'plot', 'revelation', 'transition', 'world',
})

#: Valid time_of_day values
VALID_TIMES = frozenset({
    'morning', 'afternoon', 'evening', 'night', 'dawn', 'dusk',
})

#: Maps response label to dict key
_LABEL_TO_KEY = {
    'TYPE': 'type',
    'POV': 'pov',
    'LOCATION': 'location',
    'TIME_OF_DAY': 'time_of_day',
    'DURATION': 'duration',
    'ACTION_SEQUEL': 'action_sequel',
    'EMOTIONAL_ARC': 'emotional_arc',
    'VALUE_AT_STAKE': 'value_at_stake',
    'VALUE_SHIFT': 'value_shift',
    'TURNING_POINT': 'turning_point',
    'CHARACTERS': 'characters',
    'ON_STAGE': 'on_stage',
    'MICE_THREADS': 'mice_threads',
    'GOAL': 'goal',
    'CONFLICT': 'conflict',
    'OUTCOME': 'outcome',
    'CRISIS': 'crisis',
    'DECISION': 'decision',
    'KNOWLEDGE_IN': 'knowledge_in',
    'KNOWLEDGE_OUT': 'knowledge_out',
    'KEY_ACTIONS': 'key_actions',
    'KEY_DIALOGUE': 'key_dialogue',
    'EMOTIONS': 'emotions',
    'MOTIFS': 'motifs',
}


# ============================================================================
# Response Parsing
# ============================================================================

def parse_enrich_response(response: str, scene_id: str) -> dict:
    """Parse Claude's enrichment response to extract field values.

    The response contains labeled lines like ``TYPE: action``.  Parsing is
    forgiving -- missing fields are omitted from the result, and minor
    formatting variations (extra whitespace, mixed case labels) are handled.

    Args:
        response: Raw text response from Claude.
        scene_id: Scene identifier (used for context in warnings, not
            otherwise referenced).

    Returns:
        Dict with keys from :data:`ALL_FIELDS`.  Only fields that were
        successfully extracted are included.  An additional ``'_status'``
        key is set to ``'ok'`` or ``'fail'``.
    """
    result: dict[str, str] = {}

    if not response or not response.strip():
        result['_status'] = 'fail'
        return result

    for line in response.splitlines():
        line = line.strip()
        if not line or ':' not in line:
            continue

        # Split on the first colon
        label, _, value = line.partition(':')
        label = label.strip().upper()
        value = value.strip()

        key = _LABEL_TO_KEY.get(label)
        if key and value:
            result[key] = value

    result['_status'] = 'ok' if result else 'fail'
    return result


# ============================================================================
# Alias Normalization
# ============================================================================

def load_alias_map(csv_file: str) -> dict[str, str]:
    """Build a case-insensitive alias lookup from a CSV with id|name|aliases columns.

    Reads a pipe-delimited CSV file.  When an ``id`` column is present the
    canonical value is the id (e.g. ``emmett-slade``); otherwise it falls
    back to the ``name`` column.  The ``aliases`` column holds semicolon-
    separated alternative names.  Returns a dict mapping each lowercased
    alias, name, and id to the canonical value.

    Args:
        csv_file: Path to the pipe-delimited CSV file.

    Returns:
        Dict mapping lowercase alias strings to canonical IDs (or names).
        Empty dict if the file is missing or has no relevant columns.
    """
    if not csv_file or not os.path.isfile(csv_file):
        return {}

    header, rows = _read_csv_header_and_rows(csv_file)
    if not header:
        return {}

    try:
        name_idx = header.index('name')
    except ValueError:
        return {}

    try:
        id_idx = header.index('id')
    except ValueError:
        id_idx = None

    try:
        alias_idx = header.index('aliases')
    except ValueError:
        alias_idx = None

    alias_map: dict[str, str] = {}

    for row in rows:
        if len(row) <= name_idx:
            continue
        name = row[name_idx].strip()
        if not name:
            continue

        # Use id as canonical value when available, otherwise name
        if id_idx is not None and len(row) > id_idx and row[id_idx].strip():
            canonical = row[id_idx].strip()
        else:
            canonical = name

        # Map name → canonical id
        alias_map[name.lower()] = canonical
        # Self-mapping for the id itself
        alias_map[canonical.lower()] = canonical

        # Alias mappings
        if alias_idx is not None and len(row) > alias_idx and row[alias_idx]:
            for alias in row[alias_idx].split(';'):
                alias = alias.strip()
                if alias:
                    alias_map[alias.lower()] = canonical

    return alias_map


def strip_parentheticals(value: str) -> str:
    """Strip parenthetical qualifiers from a string.

    Removes trailing parenthetical expressions like "(referenced)",
    "(implied)", "(not named in scene)" that Claude adds to character
    entries.  The ``on_stage`` column already captures presence vs
    reference, so these qualifiers just break alias lookup.

    Args:
        value: A single entry (not semicolon-separated).

    Returns:
        The value with parenthetical suffixes removed and whitespace trimmed.
    """
    return re.sub(r'\s*\([^)]*\)\s*$', '', value).strip()


def normalize_aliases(alias_map: dict[str, str], semicolon_string: str) -> str:
    """Resolve aliases in a semicolon-separated string.

    Each entry is looked up case-insensitively in *alias_map*.  Parenthetical
    qualifiers like "(referenced)" are stripped before lookup.  Matches are
    replaced with the canonical ID; unknowns pass through unchanged.  The
    result is deduplicated (first occurrence wins) and returned as a
    semicolon-separated string.

    Args:
        alias_map: Mapping from lowercase alias to canonical ID
            (as returned by :func:`load_alias_map`).
        semicolon_string: Semicolon-separated values to normalize.

    Returns:
        Normalized semicolon-separated string.
    """
    if not alias_map or not semicolon_string:
        return semicolon_string or ''

    seen: set[str] = set()
    result: list[str] = []

    for part in semicolon_string.split(';'):
        trimmed = strip_parentheticals(part.strip())
        if not trimmed:
            continue

        canonical = alias_map.get(trimmed.lower(), trimmed)
        lower_canonical = canonical.lower()

        if lower_canonical not in seen:
            seen.add(lower_canonical)
            result.append(canonical)

    return ';'.join(result)


# ============================================================================
# MICE Thread Normalization
# ============================================================================

#: Valid MICE thread types
VALID_MICE_TYPES = frozenset({'milieu', 'inquiry', 'character', 'event'})


def load_mice_registry(csv_file: str) -> tuple[dict[str, str], dict[str, str]]:
    """Load MICE thread registry from a CSV with id|name|type|aliases columns.

    Returns two dicts:
      - alias_map: lowercased name/alias → canonical id (like load_alias_map)
      - type_map: canonical id → registered type (milieu/inquiry/character/event)
    """
    if not csv_file or not os.path.isfile(csv_file):
        return {}, {}

    header, rows = _read_csv_header_and_rows(csv_file)
    if not header:
        return {}, {}

    try:
        name_idx = header.index('name')
    except ValueError:
        return {}, {}

    try:
        id_idx = header.index('id')
    except ValueError:
        id_idx = None

    try:
        type_idx = header.index('type')
    except ValueError:
        type_idx = None

    try:
        alias_idx = header.index('aliases')
    except ValueError:
        alias_idx = None

    alias_map: dict[str, str] = {}
    type_map: dict[str, str] = {}

    for row in rows:
        if len(row) <= name_idx:
            continue
        name = row[name_idx].strip()
        if not name:
            continue

        if id_idx is not None and len(row) > id_idx and row[id_idx].strip():
            canonical = row[id_idx].strip()
        else:
            canonical = name

        alias_map[name.lower()] = canonical
        alias_map[canonical.lower()] = canonical

        if type_idx is not None and len(row) > type_idx:
            type_map[canonical] = row[type_idx].strip().lower()

        if alias_idx is not None and len(row) > alias_idx and row[alias_idx]:
            for alias in row[alias_idx].split(';'):
                alias = alias.strip()
                if alias:
                    alias_map[alias.lower()] = canonical

    return alias_map, type_map


def normalize_mice_threads(mice_string: str, alias_map: dict[str, str],
                           type_map: dict[str, str] | None = None) -> str:
    """Normalize a semicolon-separated mice_threads value.

    Each entry should be ``{+|-}{type}:{name}``.  The name portion is
    resolved against *alias_map*.  If *type_map* is provided and the
    resolved name has a registered type, the type in the entry is
    corrected to match.

    Entries that don't match the expected format pass through unchanged.

    Args:
        mice_string: Raw mice_threads value (semicolon-separated).
        alias_map: Name/alias → canonical id mapping.
        type_map: Optional canonical id → registered type mapping.

    Returns:
        Normalized semicolon-separated string.
    """
    if not mice_string or not alias_map:
        return mice_string or ''

    result = []
    for entry in mice_string.split(';'):
        entry = entry.strip()
        if not entry:
            continue

        # Determine prefix (+/-/none) and the rest
        prefix = ''
        rest = entry
        if len(entry) > 1 and entry[0] in ('+', '-'):
            prefix = entry[0]
            rest = entry[1:]

        # Split type:name if colon present
        if ':' in rest:
            type_part, _, name_part = rest.partition(':')
            type_part = type_part.strip().lower()
            name_part = name_part.strip()
        else:
            # Bare name — no type prefix
            type_part = ''
            name_part = rest.strip()

        # Normalize the name via alias map
        canonical = alias_map.get(name_part.lower(), name_part)

        # Output bare canonical name — type lives in registry, not in references
        result.append(f'{prefix}{canonical}')

    return ';'.join(result)


# Fields that hold character references (semicolon-separated or single)
_CHAR_FIELDS = ('pov', 'characters', 'on_stage')
# Fields that hold location references
_LOCATION_FIELDS = ('location',)
# Fields that hold motif references
_MOTIF_FIELDS = ('motifs',)
# Fields that hold value references
_VALUE_FIELDS = ('value_at_stake',)
# Fields that hold knowledge fact references
_KNOWLEDGE_FIELDS = ('knowledge_in', 'knowledge_out')


def format_registries_for_prompt(project_dir: str) -> str:
    """Format registry CSV contents as a prompt section.

    Reads all registry files and returns a formatted string showing
    canonical IDs that Claude should use in its output.  Registries
    whose files don't exist or contain only a header row are skipped.

    Args:
        project_dir: Root directory of the novel project.

    Returns:
        Formatted markdown string, or empty string if no registries exist.
    """
    ref_dir = os.path.join(project_dir, 'reference')

    # Registry definitions: (filename, section_title, extra_columns)
    # extra_columns are additional columns to show alongside id and name
    registries = [
        ('characters.csv', 'Characters', []),
        ('locations.csv', 'Locations', []),
        ('values.csv', 'Values', []),
        ('mice-threads.csv', 'MICE Threads', ['type']),
        ('motif-taxonomy.csv', 'Motifs', []),
        ('knowledge.csv', 'Knowledge Facts', []),
    ]

    sections: list[str] = []

    for filename, title, extra_cols in registries:
        csv_path = os.path.join(ref_dir, filename)
        if not os.path.isfile(csv_path):
            continue

        header, rows = _read_csv_header_and_rows(csv_path)
        if not header or not rows:
            continue

        try:
            id_idx = header.index('id')
        except ValueError:
            continue
        try:
            name_idx = header.index('name')
        except ValueError:
            continue

        # Resolve extra column indices
        extra_idxs: list[tuple[str, int]] = []
        for col in extra_cols:
            try:
                extra_idxs.append((col, header.index(col)))
            except ValueError:
                pass

        entries: list[str] = []
        for row in rows:
            if len(row) <= max(id_idx, name_idx):
                continue
            rid = row[id_idx].strip()
            rname = row[name_idx].strip()
            if not rid:
                continue

            # Build the display line
            extra_parts = []
            for col_name, col_idx in extra_idxs:
                if len(row) > col_idx and row[col_idx].strip():
                    extra_parts.append(f'[{row[col_idx].strip()}]')

            extra_str = ' '.join(extra_parts)
            if extra_str:
                entries.append(f'- {rid} {extra_str} ({rname})')
            else:
                entries.append(f'- {rid} ({rname})')

        if entries:
            sections.append(f'### {title} (reference/{filename})\n' +
                            '\n'.join(entries))

    if not sections:
        return ''

    return ('## Canonical Registries — use these IDs in your output\n\n' +
            '\n\n'.join(sections))


def load_registry_alias_maps(project_dir: str) -> dict[str, dict[str, str]]:
    """Load alias maps from all registry CSVs in a project.

    Returns a dict with keys 'characters', 'locations', 'motifs', 'values',
    'knowledge', 'mice_threads', and 'mice_types' mapping to their respective
    dicts.  Missing registry files produce empty dicts.

    The 'mice_threads' key holds a name→id alias map.  The 'mice_types' key
    holds an id→type map for MICE type correction.
    """
    ref_dir = os.path.join(project_dir, 'reference')
    mice_alias, mice_types = load_mice_registry(
        os.path.join(ref_dir, 'mice-threads.csv'))
    return {
        'characters': load_alias_map(os.path.join(ref_dir, 'characters.csv')),
        'locations': load_alias_map(os.path.join(ref_dir, 'locations.csv')),
        'motifs': load_alias_map(os.path.join(ref_dir, 'motif-taxonomy.csv')),
        'values': load_alias_map(os.path.join(ref_dir, 'values.csv')),
        'knowledge': load_alias_map(os.path.join(ref_dir, 'knowledge.csv')),
        'mice_threads': mice_alias,
        'mice_types': mice_types,
    }


def normalize_fields(result: dict[str, str],
                     alias_maps: dict[str, dict[str, str]]) -> dict[str, str]:
    """Normalize all registry-backed fields in a result dict.

    Applies alias maps to resolve free-text names to canonical IDs.
    Works with any dict that has scene-CSV field names (pov, characters,
    on_stage, location, motifs, value_at_stake, mice_threads).

    Args:
        result: Parsed result dict (from any extraction, enrichment, or
            elaboration response parser).
        alias_maps: Registry alias maps (from :func:`load_registry_alias_maps`).

    Returns:
        The result dict, modified in place and returned for convenience.
    """
    if not alias_maps:
        return result

    char_map = alias_maps.get('characters', {})
    loc_map = alias_maps.get('locations', {})
    motif_map = alias_maps.get('motifs', {})
    value_map = alias_maps.get('values', {})
    knowledge_map = alias_maps.get('knowledge', {})
    mice_map = alias_maps.get('mice_threads', {})
    mice_types = alias_maps.get('mice_types', {})

    for field in _CHAR_FIELDS:
        if field in result and char_map:
            result[field] = normalize_aliases(char_map, result[field])
    for field in _LOCATION_FIELDS:
        if field in result and loc_map:
            result[field] = normalize_aliases(loc_map, result[field])
    for field in _MOTIF_FIELDS:
        if field in result and motif_map:
            result[field] = normalize_aliases(motif_map, result[field])
    for field in _VALUE_FIELDS:
        if field in result and value_map:
            result[field] = normalize_aliases(value_map, result[field])
    for field in _KNOWLEDGE_FIELDS:
        if field in result and knowledge_map:
            result[field] = normalize_aliases(knowledge_map, result[field])
    if 'mice_threads' in result and mice_map:
        result['mice_threads'] = normalize_mice_threads(
            result['mice_threads'], mice_map, mice_types)

    return result


# ============================================================================
# Field Validation
# ============================================================================

def validate_type(value: str) -> str:
    """Validate a scene type value against the allowed set.

    Args:
        value: Raw type string from Claude's response.

    Returns:
        Cleaned value if valid, empty string otherwise.
    """
    if not value:
        return ''
    cleaned = value.strip().lower()
    return cleaned if cleaned in VALID_TYPES else ''


def validate_time_of_day(value: str) -> str:
    """Validate a time-of-day value against the allowed set.

    Args:
        value: Raw time-of-day string from Claude's response.

    Returns:
        Cleaned value if valid, empty string otherwise.
    """
    if not value:
        return ''
    cleaned = value.strip().lower()
    return cleaned if cleaned in VALID_TIMES else ''


# ============================================================================
# CSV Update Helpers
# ============================================================================

def update_csv_field(csv_file: str, row_id: str, field: str, value: str,
                     key_column: str = 'id') -> bool:
    """Update a single cell in a pipe-delimited CSV file.

    Performs an atomic write (write to temp, then rename) to avoid
    partial-write corruption.

    Args:
        csv_file: Path to the CSV file.
        row_id: Value to match in the key column.
        field: Column name to update.
        value: New value to write.
        key_column: Column used to locate the row (default ``id``).

    Returns:
        True if the field was updated, False if the row or column was not
        found.
    """
    if not os.path.isfile(csv_file):
        return False

    header, rows = _read_csv_header_and_rows(csv_file)
    if not header:
        return False

    try:
        key_idx = header.index(key_column)
        field_idx = header.index(field)
    except ValueError:
        return False

    updated = False
    for row in rows:
        if len(row) > key_idx and row[key_idx] == row_id:
            # Extend the row if needed
            while len(row) <= field_idx:
                row.append('')
            row[field_idx] = value
            updated = True
            break

    if not updated:
        return False

    # Atomic write: temp file then rename
    dir_name = os.path.dirname(csv_file)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.csv.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write('|'.join(header) + '\n')
            for row in rows:
                f.write('|'.join(row) + '\n')
        os.replace(tmp_path, csv_file)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return True


# ============================================================================
# Enrichment Pipeline
# ============================================================================

def apply_enrich_result(scene_id: str, result: dict,
                        metadata_csv: str, intent_csv: str,
                        force: bool = False,
                        briefs_csv: str = '') -> int:
    """Write enrichment values to the project CSV files.

    Routes each field to the correct CSV file based on field membership
    in METADATA_FIELDS, INTENT_FIELDS, or BRIEFS_FIELDS.

    Existing non-empty values are skipped unless *force* is True.

    Args:
        scene_id: The scene identifier.
        result: Dict as returned by :func:`parse_enrich_response`, with
            optional alias normalization and validation already applied.
        metadata_csv: Path to scenes.csv.
        intent_csv: Path to scene-intent.csv.
        force: If True, overwrite existing non-empty values.
        briefs_csv: Path to scene-briefs.csv.

    Returns:
        Number of fields actually updated.
    """
    if result.get('_status') != 'ok':
        return 0

    updated = 0

    for field in ALL_FIELDS:
        new_val = result.get(field, '')
        if not new_val:
            continue

        # Determine which CSV holds this field
        if field in METADATA_FIELDS:
            csv_file = metadata_csv
        elif field in INTENT_FIELDS:
            csv_file = intent_csv
        elif field in BRIEFS_FIELDS:
            csv_file = briefs_csv
        else:
            continue

        if not csv_file or not os.path.isfile(csv_file):
            continue

        # Skip if already populated (unless force)
        if not force:
            current = read_csv_field(csv_file, scene_id, field)
            if current:
                continue

        if update_csv_field(csv_file, scene_id, field, new_val):
            updated += 1

    return updated


def build_enrich_prompt(scene_id: str, project_dir: str,
                        fields: list[str] | None = None,
                        force: bool = False) -> str:
    """Build the enrichment prompt for a single scene.

    Reads the scene prose file and constructs a prompt asking Claude to
    extract the specified metadata fields.  Only fields that are currently
    empty (or all fields if *force* is True) are requested.

    Args:
        scene_id: The scene identifier.
        project_dir: Root directory of the novel project.
        fields: List of field names to extract.  Defaults to all enrichable
            fields.
        force: If True, request all specified fields regardless of current
            values.

    Returns:
        The assembled prompt string, or empty string if the scene file
        does not exist.
    """
    if fields is None:
        fields = sorted(ALL_FIELDS)

    scene_file = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    if not os.path.isfile(scene_file):
        return ''

    with open(scene_file) as f:
        scene_text = f.read()

    # Read existing metadata for context
    metadata_csv = _resolve_scenes_csv(project_dir)
    intent_csv = _resolve_intent_csv(project_dir)

    title = ''
    pov = ''
    setting = ''

    if metadata_csv:
        title = read_csv_field(metadata_csv, scene_id, 'title')
        pov = read_csv_field(metadata_csv, scene_id, 'pov')
        setting = read_csv_field(metadata_csv, scene_id, 'location')

    briefs_csv = _resolve_briefs_csv(project_dir)

    # Build field instructions -- only for fields still needed
    field_instructions = []
    for field in fields:
        if not force:
            current_val = ''
            if field in METADATA_FIELDS and metadata_csv:
                current_val = read_csv_field(metadata_csv, scene_id, field)
            elif field in INTENT_FIELDS and intent_csv:
                current_val = read_csv_field(intent_csv, scene_id, field)
            elif field in BRIEFS_FIELDS and briefs_csv:
                current_val = read_csv_field(briefs_csv, scene_id, field)
            if current_val:
                continue

        instruction = _field_instruction(field)
        if instruction:
            field_instructions.append(instruction)

    if not field_instructions:
        return ''

    # Include registry contents for registry-backed fields
    registries_text = format_registries_for_prompt(project_dir)

    prompt_parts = [
        'Analyze this scene and extract the requested metadata. '
        'Respond with ONLY the labeled lines below, nothing else. '
        'For registry-backed fields, use the canonical IDs from the '
        'registries listed below.',
        '',
        f'Title: {title or "Unknown"} | POV: {pov or "Unknown"} '
        f'| Setting: {setting or "Unknown"}',
        '',
        scene_text,
    ]

    if registries_text:
        prompt_parts.append('')
        prompt_parts.append(registries_text)

    for instruction in field_instructions:
        prompt_parts.append(instruction)

    return '\n'.join(prompt_parts)


def _field_instruction(field: str) -> str:
    """Return the prompt instruction line for a given field."""
    instructions = {
        'pov': (
            'POV: <the POV character — use their canonical ID or full name>'
        ),
        'location': (
            'LOCATION: <the physical location — use a short, reusable label '
            '(the name of the place, not a description). If two scenes '
            'happen in the same place, use the same string.>'
        ),
        'time_of_day': (
            'TIME_OF_DAY: <one of: morning, afternoon, evening, night, '
            'dawn, dusk>'
        ),
        'duration': (
            'DURATION: <approximate in-story duration, e.g., "2 hours", '
            '"30 minutes", "an afternoon">'
        ),
        'type': (
            'TYPE: <one of: action, character, confrontation, dialogue, '
            'introspection, plot, revelation, transition, world>'
        ),
        'action_sequel': (
            'ACTION_SEQUEL: <action or sequel — action scenes have '
            'goal/conflict/outcome; sequel scenes have '
            'reaction/dilemma/decision>'
        ),
        'emotional_arc': (
            'EMOTIONAL_ARC: <one sentence: "[starting emotion] giving way '
            'to [ending emotion]">'
        ),
        'value_at_stake': (
            'VALUE_AT_STAKE: <the abstract value being tested in this scene '
            '— e.g., truth, safety, justice, loyalty, freedom>'
        ),
        'value_shift': (
            'VALUE_SHIFT: <polarity change using +/- notation: '
            '+/- means positive to negative, -/+ means negative to positive, '
            '+/++ means good to better, -/-- means bad to worse, '
            '+/+ or -/- means no change (flat)>'
        ),
        'turning_point': (
            'TURNING_POINT: <action or revelation — action means a character '
            'does something that changes the situation; revelation means new '
            'information changes the situation>'
        ),
        'characters': (
            'CHARACTERS: <semicolon-separated list of ALL characters present '
            'or referenced by name>'
        ),
        'on_stage': (
            'ON_STAGE: <semicolon-separated list of characters physically '
            'present in the scene — subset of CHARACTERS>'
        ),
        'mice_threads': (
            'MICE_THREADS: <semicolon-separated MICE thread operations — '
            '+milieu:location-name to open, -inquiry:question to close. '
            'Use + for opening, - for closing. '
            'Types: milieu, inquiry, character, event>'
        ),
        'goal': (
            'GOAL: <the POV character\'s concrete objective entering this '
            'scene — what are they trying to do?>'
        ),
        'conflict': (
            'CONFLICT: <what specifically opposes the goal?>'
        ),
        'outcome': (
            'OUTCOME: <how the scene ends for the POV character: '
            'yes / no / yes-but / no-and>'
        ),
        'crisis': (
            'CRISIS: <the key dilemma — a best bad choice or irreconcilable '
            'goods that the character faces>'
        ),
        'decision': (
            'DECISION: <what the character actively chooses in response '
            'to the crisis>'
        ),
        'knowledge_in': (
            'KNOWLEDGE_IN: <semicolon-separated STRUCTURALLY USEFUL facts '
            'the POV character knows entering — only facts that gate this '
            "scene's decisions. Categories: identity reveals, motive/intent "
            'reveals, capability/constraints, state changes, stakes/threats, '
            'relationship shifts. Omit ordinary plot details.>'
        ),
        'knowledge_out': (
            'KNOWLEDGE_OUT: <knowledge_in plus 0-2 NEW structurally useful '
            'facts learned during this scene. A fact is useful only if a '
            'character who knows it would make a different decision than one '
            'who does not, or a future scene requires it. Most scenes add '
            '0-1 new facts.>'
        ),
        'key_actions': (
            'KEY_ACTIONS: <semicolon-separated concrete things that happen '
            'in this scene>'
        ),
        'key_dialogue': (
            'KEY_DIALOGUE: <semicolon-separated specific lines or exchanges '
            'essential to the scene — quote directly from the text>'
        ),
        'emotions': (
            'EMOTIONS: <semicolon-separated emotional beats in sequence '
            'as they occur through the scene>'
        ),
        'motifs': (
            'MOTIFS: <semicolon-separated recurring images, symbols, or '
            'sensory details that carry thematic weight>'
        ),
    }
    return instructions.get(field, '')


def enrich_and_apply(scene_id: str, response: str, project_dir: str,
                     alias_maps: dict[str, dict[str, str]] | None = None,
                     force: bool = False) -> dict:
    """Full pipeline: parse response, normalize, validate, apply to CSVs.

    Convenience function that chains :func:`parse_enrich_response`,
    alias normalization, field validation, and :func:`apply_enrich_result`.

    Args:
        scene_id: The scene identifier.
        response: Raw text response from Claude.
        project_dir: Root directory of the novel project.
        alias_maps: Optional dict with keys ``'characters'``, ``'motifs'``,
            ``'locations'`` mapping to alias dicts.
        force: If True, overwrite existing non-empty values.

    Returns:
        The parsed and normalized result dict (including ``'_status'``).
    """
    result = parse_enrich_response(response, scene_id)
    if result.get('_status') != 'ok':
        return result

    # Normalize aliases (characters, on_stage, pov, location, motifs)
    if alias_maps:
        normalize_fields(result, alias_maps)

    # Validate constrained fields
    if 'type' in result:
        result['type'] = validate_type(result['type'])
        if not result['type']:
            del result['type']
    if 'time_of_day' in result:
        result['time_of_day'] = validate_time_of_day(result['time_of_day'])
        if not result['time_of_day']:
            del result['time_of_day']

    # Apply to CSVs
    metadata_csv = _resolve_scenes_csv(project_dir)
    intent_csv = _resolve_intent_csv(project_dir)
    briefs_csv = _resolve_briefs_csv(project_dir)

    if metadata_csv and intent_csv:
        apply_enrich_result(scene_id, result, metadata_csv, intent_csv,
                            force=force, briefs_csv=briefs_csv)

    return result


# ============================================================================
# CLI Interface
# ============================================================================

def main():
    """CLI entry point.

    Usage::

        python3 -m storyforge.enrich parse-response <response_file> <scene_id>
        python3 -m storyforge.enrich load-aliases <csv_file>
        python3 -m storyforge.enrich normalize <alias_map_json> <semicolon_string>
        python3 -m storyforge.enrich build-prompt <scene_id> <project_dir> [--fields type,location,characters] [--force]
    """
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.enrich <command> [args]',
              file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'parse-response':
        if len(sys.argv) < 4:
            print('Usage: parse-response <response_file> <scene_id>',
                  file=sys.stderr)
            sys.exit(1)

        response_file = sys.argv[2]
        scene_id = sys.argv[3]

        with open(response_file) as f:
            response_text = f.read()

        result = parse_enrich_response(response_text, scene_id)

        # Output as pipe-delimited key|value pairs (matches bash format)
        for label, key in _LABEL_TO_KEY.items():
            val = result.get(key, '')
            print(f'{label}|{val}')
        print(f'STATUS|{result.get("_status", "fail")}')

    elif command == 'load-aliases':
        if len(sys.argv) < 3:
            print('Usage: load-aliases <csv_file>', file=sys.stderr)
            sys.exit(1)

        csv_file = sys.argv[2]
        alias_map = load_alias_map(csv_file)

        # Output as JSON for consumption by other commands
        json.dump(alias_map, sys.stdout)
        print()

    elif command == 'normalize':
        if len(sys.argv) < 4:
            print('Usage: normalize <alias_map_json> <semicolon_string>',
                  file=sys.stderr)
            sys.exit(1)

        alias_map_arg = sys.argv[2]

        # Accept either a JSON string or a file path
        if os.path.isfile(alias_map_arg):
            with open(alias_map_arg) as f:
                alias_map = json.load(f)
        else:
            alias_map = json.loads(alias_map_arg)

        semicolon_string = sys.argv[3]
        print(normalize_aliases(alias_map, semicolon_string))

    elif command == 'build-prompt':
        if len(sys.argv) < 4:
            print('Usage: build-prompt <scene_id> <project_dir> '
                  '[--fields type,location,characters] [--force]',
                  file=sys.stderr)
            sys.exit(1)

        scene_id = sys.argv[2]
        project_dir = sys.argv[3]
        fields = None
        force = False

        i = 4
        while i < len(sys.argv):
            if sys.argv[i] == '--fields' and i + 1 < len(sys.argv):
                fields = [f.strip() for f in sys.argv[i + 1].split(',')]
                i += 2
            elif sys.argv[i] == '--force':
                force = True
                i += 1
            else:
                print(f'Unknown flag: {sys.argv[i]}', file=sys.stderr)
                sys.exit(1)

        prompt = build_enrich_prompt(scene_id, project_dir, fields=fields,
                                     force=force)
        if prompt:
            print(prompt)
        else:
            print('(no fields need enrichment)', file=sys.stderr)
            sys.exit(0)

    elif command == 'apply-response':
        # Full pipeline: parse response, normalize aliases, validate, optionally apply to CSVs
        # Usage: apply-response <response_file> <scene_id> <project_dir> [--aliases <json_file>] [--force] [--result-file <path>] [--parse-only]
        if len(sys.argv) < 5:
            print('Usage: apply-response <response_file> <scene_id> <project_dir> '
                  '[--aliases <json_file>] [--force] [--result-file <path>] '
                  '[--parse-only]',
                  file=sys.stderr)
            sys.exit(1)

        response_file = sys.argv[2]
        scene_id = sys.argv[3]
        project_dir = sys.argv[4]
        alias_file = ''
        force = False
        result_file = ''
        parse_only = False

        i = 5
        while i < len(sys.argv):
            if sys.argv[i] == '--aliases' and i + 1 < len(sys.argv):
                alias_file = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--force':
                force = True
                i += 1
            elif sys.argv[i] == '--result-file' and i + 1 < len(sys.argv):
                result_file = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--parse-only':
                parse_only = True
                i += 1
            else:
                i += 1

        with open(response_file) as f:
            response_text = f.read()

        # Load alias maps if provided
        alias_maps = None
        if alias_file and os.path.isfile(alias_file):
            with open(alias_file) as f:
                alias_maps = json.load(f)

        if parse_only:
            # Parse + normalize + validate only, no CSV writes
            result = parse_enrich_response(response_text, scene_id)
            if result.get('_status') == 'ok' and alias_maps:
                if 'characters' in alias_maps and 'characters' in result:
                    result['characters'] = normalize_aliases(
                        alias_maps['characters'], result['characters'])
                if 'motifs' in alias_maps and 'motifs' in result:
                    result['motifs'] = normalize_aliases(
                        alias_maps['motifs'], result['motifs'])
                if 'locations' in alias_maps and 'location' in result:
                    result['location'] = normalize_aliases(
                        alias_maps['locations'], result['location'])
            if 'type' in result:
                result['type'] = validate_type(result['type'])
                if not result['type']:
                    del result['type']
            if 'time_of_day' in result:
                result['time_of_day'] = validate_time_of_day(
                    result['time_of_day'])
                if not result['time_of_day']:
                    del result['time_of_day']
        else:
            result = enrich_and_apply(scene_id, response_text, project_dir,
                                      alias_maps=alias_maps, force=force)

        # Write result file in pipe-delimited format (for bash compat)
        if result_file:
            with open(result_file, 'w') as f:
                for label, key in _LABEL_TO_KEY.items():
                    val = result.get(key, '')
                    f.write(f'{label}|{val}\n')
                f.write(f'STATUS|{result.get("_status", "fail")}\n')
            print(result.get('_status', 'fail'))
        else:
            # Print status to stdout
            status = result.get('_status', 'fail')
            print(status)

    elif command == 'load-alias-maps':
        # Load all alias maps from a project directory, output as JSON
        # Usage: load-alias-maps <project_dir>
        if len(sys.argv) < 3:
            print('Usage: load-alias-maps <project_dir>', file=sys.stderr)
            sys.exit(1)

        project_dir = sys.argv[2]
        maps = load_registry_alias_maps(project_dir)

        json.dump(maps, sys.stdout)
        print()

    elif command == 'validate-type':
        if len(sys.argv) < 3:
            print('Usage: validate-type <value>', file=sys.stderr)
            sys.exit(1)
        print(validate_type(sys.argv[2]))

    elif command == 'validate-time':
        if len(sys.argv) < 3:
            print('Usage: validate-time <value>', file=sys.stderr)
            sys.exit(1)
        print(validate_time_of_day(sys.argv[2]))

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        print('Available commands: parse-response, load-aliases, normalize, '
              'build-prompt, validate-type, validate-time, apply-response, '
              'load-alias-maps', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
