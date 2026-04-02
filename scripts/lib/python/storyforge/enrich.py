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
)


# ============================================================================
# Constants
# ============================================================================

#: Fields stored in scenes.csv
METADATA_FIELDS = frozenset({'type', 'location', 'time_of_day'})

#: Fields stored in scene-intent.csv
INTENT_FIELDS = frozenset({'emotional_arc', 'characters', 'threads', 'motifs'})

#: All enrichable fields
ALL_FIELDS = METADATA_FIELDS | INTENT_FIELDS

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
    'LOCATION': 'location',
    'TIME_OF_DAY': 'time_of_day',
    'CHARACTERS': 'characters',
    'EMOTIONAL_ARC': 'emotional_arc',
    'THREADS': 'threads',
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
    """Build a case-insensitive alias lookup from a CSV with name|aliases columns.

    Reads a pipe-delimited CSV file where the ``name`` column holds the
    canonical name and the ``aliases`` column holds semicolon-separated
    alternative names.  Returns a dict mapping each lowercased alias (and
    the lowercased canonical name itself) to the canonical name.

    Args:
        csv_file: Path to the pipe-delimited CSV file.

    Returns:
        Dict mapping lowercase alias strings to canonical names.
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
        alias_idx = header.index('aliases')
    except ValueError:
        alias_idx = None

    alias_map: dict[str, str] = {}

    for row in rows:
        if len(row) <= name_idx:
            continue
        canonical = row[name_idx].strip()
        if not canonical:
            continue

        # Self-mapping
        alias_map[canonical.lower()] = canonical

        # Alias mappings
        if alias_idx is not None and len(row) > alias_idx and row[alias_idx]:
            for alias in row[alias_idx].split(';'):
                alias = alias.strip()
                if alias:
                    alias_map[alias.lower()] = canonical

    return alias_map


def normalize_aliases(alias_map: dict[str, str], semicolon_string: str) -> str:
    """Resolve aliases in a semicolon-separated string.

    Each entry is looked up case-insensitively in *alias_map*.  Matches
    are replaced with the canonical name; unknowns pass through unchanged.
    The result is deduplicated (first occurrence wins) and returned as a
    semicolon-separated string.

    Args:
        alias_map: Mapping from lowercase alias to canonical name
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
        trimmed = part.strip()
        if not trimmed:
            continue

        canonical = alias_map.get(trimmed.lower(), trimmed)
        lower_canonical = canonical.lower()

        if lower_canonical not in seen:
            seen.add(lower_canonical)
            result.append(canonical)

    return ';'.join(result)


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
                        force: bool = False) -> int:
    """Write enrichment values to the project CSV files.

    Updates ``metadata_csv`` for type, location, time_of_day.
    Updates ``intent_csv`` for emotional_arc, characters, threads, motifs.

    Existing non-empty values are skipped unless *force* is True.

    Args:
        scene_id: The scene identifier.
        result: Dict as returned by :func:`parse_enrich_response`, with
            optional alias normalization and validation already applied.
        metadata_csv: Path to scenes.csv.
        intent_csv: Path to scene-intent.csv.
        force: If True, overwrite existing non-empty values.

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
        else:
            csv_file = intent_csv

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

    # Build field instructions -- only for fields still needed
    field_instructions = []
    for field in fields:
        if not force:
            current_val = ''
            if field in METADATA_FIELDS and metadata_csv:
                current_val = read_csv_field(metadata_csv, scene_id, field)
            elif field in INTENT_FIELDS and intent_csv:
                current_val = read_csv_field(intent_csv, scene_id, field)
            if current_val:
                continue

        instruction = _field_instruction(field)
        if instruction:
            field_instructions.append(instruction)

    if not field_instructions:
        return ''

    prompt_parts = [
        'Analyze this scene and extract the requested metadata. '
        'Respond with ONLY the labeled lines below, nothing else.',
        '',
        f'Title: {title or "Unknown"} | POV: {pov or "Unknown"} '
        f'| Setting: {setting or "Unknown"}',
        '',
        scene_text,
    ]

    for instruction in field_instructions:
        prompt_parts.append(instruction)

    return '\n'.join(prompt_parts)


def _field_instruction(field: str) -> str:
    """Return the prompt instruction line for a given field."""
    instructions = {
        'type': (
            'TYPE: <one of: character, plot, world, action, transition, '
            'confrontation>'
        ),
        'location': (
            'LOCATION: <the physical location where this scene takes place '
            '-- use a short, reusable label (the name of the place, not a '
            'description of the scene). If two scenes happen in the same '
            'place, use the same location string. Do not include time of '
            'day, room-level detail, or character actions.>'
        ),
        'time_of_day': (
            'TIME_OF_DAY: <one of: morning, afternoon, evening, night, '
            'dawn, dusk>'
        ),
        'characters': (
            'CHARACTERS: <semicolon-separated list of ALL character names '
            'who appear or are mentioned by name>'
        ),
        'emotional_arc': (
            'EMOTIONAL_ARC: <one sentence: "[starting emotion] giving way '
            'to [ending emotion]">'
        ),
        'threads': (
            'THREADS: <semicolon-separated list of story threads, e.g. '
            '"investigation;family_secret">'
        ),
        'motifs': (
            'MOTIFS: <semicolon-separated list of recurring images/symbols, '
            'e.g. "hands;darkness;water">'
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
            ``'locations'``, ``'threads'`` mapping to alias dicts.
        force: If True, overwrite existing non-empty values.

    Returns:
        The parsed and normalized result dict (including ``'_status'``).
    """
    result = parse_enrich_response(response, scene_id)
    if result.get('_status') != 'ok':
        return result

    # Normalize aliases
    if alias_maps:
        if 'characters' in alias_maps and 'characters' in result:
            result['characters'] = normalize_aliases(
                alias_maps['characters'], result['characters'])
        if 'motifs' in alias_maps and 'motifs' in result:
            result['motifs'] = normalize_aliases(
                alias_maps['motifs'], result['motifs'])
        if 'locations' in alias_maps and 'location' in result:
            result['location'] = normalize_aliases(
                alias_maps['locations'], result['location'])
        if 'threads' in alias_maps and 'threads' in result:
            result['threads'] = normalize_aliases(
                alias_maps['threads'], result['threads'])

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

    if metadata_csv and intent_csv:
        apply_enrich_result(scene_id, result, metadata_csv, intent_csv,
                            force=force)

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
                if 'threads' in alias_maps and 'threads' in result:
                    result['threads'] = normalize_aliases(
                        alias_maps['threads'], result['threads'])
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
        maps = {}

        chars_csv = os.path.join(project_dir, 'reference', 'characters.csv')
        if os.path.isfile(chars_csv):
            maps['characters'] = load_alias_map(chars_csv)

        motifs_csv = os.path.join(project_dir, 'reference', 'motif-taxonomy.csv')
        if os.path.isfile(motifs_csv):
            maps['motifs'] = load_alias_map(motifs_csv)

        locations_csv = os.path.join(project_dir, 'reference', 'locations.csv')
        if os.path.isfile(locations_csv):
            maps['locations'] = load_alias_map(locations_csv)

        threads_csv = os.path.join(project_dir, 'reference', 'threads.csv')
        if os.path.isfile(threads_csv):
            maps['threads'] = load_alias_map(threads_csv)

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
