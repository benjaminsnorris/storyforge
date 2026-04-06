"""CSV data quality tool — registries, briefs, structural fixes, gap fill.

Domains:
- registries: Build canonical registries and normalize field values (absorbs reconcile.py)
- briefs: Concretize abstract brief language as concrete physical beats
- structural: Fix CSV fields from evaluation findings
- gaps: Fill empty fields from context

Each domain follows: detect → prompt → apply → commit.
"""

import csv
import os
import re

from storyforge.elaborate import (
    _read_csv, _read_csv_as_map, _write_csv, _FILE_MAP, DELIMITER,
)
from storyforge.enrich import (
    load_alias_map, load_mice_registry, normalize_aliases,
    normalize_mice_threads,
)

# ============================================================================
# Outcome normalization (deterministic — no API call)
# ============================================================================

_OUTCOME_ENUM = {'yes', 'yes-but', 'no', 'no-and', 'no-but'}
_OUTCOME_RE = re.compile(
    r'^\[?(yes-but|no-and|no-but|yes|no)\b',
    re.IGNORECASE,
)


def normalize_outcomes(raw: str) -> str:
    """Extract enum value from a possibly-elaborated outcome string.

    Handles: 'yes-but — long elaboration', '[no-and]', 'yes', etc.
    Returns the raw string unchanged if no enum is recognized.
    """
    raw = raw.strip()
    if not raw:
        return raw
    m = _OUTCOME_RE.match(raw)
    if m:
        return m.group(1).lower()
    return raw


def reconcile_outcomes(ref_dir: str) -> int:
    """Normalize all outcome fields in scene-briefs.csv to enum values.

    Returns the number of rows changed.
    """
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    rows = _read_csv(briefs_path)
    if not rows:
        return 0

    changed = 0
    for row in rows:
        raw = row.get('outcome', '')
        normalized = normalize_outcomes(raw)
        if normalized != raw:
            row['outcome'] = normalized
            changed += 1

    if changed:
        _write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])
    return changed


# ============================================================================
# Registry prompt builders
# ============================================================================

def _collect_column_values(ref_dir: str, filename: str, column: str) -> list[str]:
    """Collect all non-empty values from a column across all rows."""
    path = os.path.join(ref_dir, filename)
    rows = _read_csv(path)
    values = []
    for row in rows:
        v = row.get(column, '').strip()
        if v:
            values.append(v)
    return values


def _collect_array_values(ref_dir: str, filename: str, column: str) -> list[str]:
    """Collect all unique values from a semicolon-separated column."""
    path = os.path.join(ref_dir, filename)
    rows = _read_csv(path)
    seen = set()
    values = []
    for row in rows:
        raw = row.get(column, '').strip()
        if not raw:
            continue
        for item in raw.split(';'):
            item = item.strip()
            if item and item not in seen:
                seen.add(item)
                values.append(item)
    return values


def _read_existing_registry(ref_dir: str, filename: str) -> str:
    """Read an existing registry CSV file as raw text, or empty string."""
    path = os.path.join(ref_dir, filename)
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            content = f.read().strip()
        # Only return if it has more than just a header
        lines = [l for l in content.split('\n') if l.strip()]
        if len(lines) > 1:
            return content
    return ''


def _collect_mice_timeline(ref_dir: str) -> list[tuple[str, str, str]]:
    """Collect MICE thread entries with scene context: [(scene_id, seq, entry), ...]."""
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))
    timeline = []
    for sid in sorted_ids:
        intent = intent_map.get(sid, {})
        mice = intent.get('mice_threads', '').strip()
        if not mice:
            continue
        seq = scenes_map[sid].get('seq', '0')
        for entry in mice.split(';'):
            entry = entry.strip()
            if entry:
                timeline.append((sid, seq, entry))
    return timeline


def _collect_knowledge_chain(ref_dir: str) -> list[tuple[str, str, str, str]]:
    """Collect knowledge facts in scene order: [(scene_id, seq, knowledge_in, knowledge_out), ...]."""
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))
    chain = []
    for sid in sorted_ids:
        brief = briefs_map.get(sid, {})
        k_in = brief.get('knowledge_in', '').strip()
        k_out = brief.get('knowledge_out', '').strip()
        seq = scenes_map[sid].get('seq', '0')
        if k_in or k_out:
            chain.append((sid, seq, k_in, k_out))
    return chain


def _collect_physical_state_chain(ref_dir: str) -> list[tuple[str, str, str, str]]:
    """Collect physical states in scene order: [(scene_id, seq, state_in, state_out), ...]."""
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))
    chain = []
    for sid in sorted_ids:
        brief = briefs_map.get(sid, {})
        ps_in = brief.get('physical_state_in', '').strip()
        ps_out = brief.get('physical_state_out', '').strip()
        seq = scenes_map[sid].get('seq', '0')
        if ps_in or ps_out:
            chain.append((sid, seq, ps_in, ps_out))
    return chain


def build_registry_prompt(domain: str, ref_dir: str,
                          context: str = '') -> str:
    """Build an Opus prompt to create/update a canonical registry.

    Args:
        domain: One of 'characters', 'locations', 'values',
                'mice-threads', 'knowledge'.
        ref_dir: Path to the reference/ directory.
        context: Optional extra context (e.g., character bible text).

    Returns:
        The prompt string for Opus.
    """
    existing = ''
    raw_values = ''

    if domain == 'characters':
        existing = _read_existing_registry(ref_dir, 'characters.csv')
        # Collect from pov, characters, on_stage
        pov_vals = _collect_column_values(ref_dir, 'scenes.csv', 'pov')
        char_vals = _collect_array_values(ref_dir, 'scene-intent.csv', 'characters')
        onstage_vals = _collect_array_values(ref_dir, 'scene-intent.csv', 'on_stage')
        all_refs = sorted(set(pov_vals + char_vals + onstage_vals))
        raw_values = '\n'.join(f'- {v}' for v in all_refs)

        return f"""Build a canonical character registry for a novel.

## All Character References Found in the Manuscript

{raw_values}

{f"## Existing Registry{chr(10)}{chr(10)}```{chr(10)}{existing}{chr(10)}```" if existing else ""}

{f"## Additional Context{chr(10)}{chr(10)}{context}" if context else ""}

## Instructions

Produce a pipe-delimited CSV with columns: id|name|role|aliases

Rules:
- id: kebab-case slug (e.g., kael-davreth)
- name: display name (e.g., Kael Davreth)
- role: protagonist, antagonist, supporting, minor, or referenced
- aliases: semicolon-separated variants found in the data (e.g., Kael;kael;Kael Davreth)
- Merge variants of the same character (Kael, kael, Kael Davreth = one entry)
- If an existing registry is provided, preserve its IDs for known characters and add new ones
- Every reference in the manuscript data must resolve to exactly one registry entry

Output ONLY the CSV (with header row). No commentary."""

    elif domain == 'locations':
        existing = _read_existing_registry(ref_dir, 'locations.csv')
        loc_vals = _collect_column_values(ref_dir, 'scenes.csv', 'location')
        all_refs = sorted(set(loc_vals))
        raw_values = '\n'.join(f'- {v}' for v in all_refs)

        return f"""Build a canonical location registry for a novel.

## All Location References Found in the Manuscript

{raw_values}

{f"## Existing Registry{chr(10)}{chr(10)}```{chr(10)}{existing}{chr(10)}```" if existing else ""}

## Instructions

Produce a pipe-delimited CSV with columns: id|name|aliases

Rules:
- id: kebab-case slug (e.g., resonance-chamber)
- name: canonical display name (e.g., Resonance Chamber)
- aliases: semicolon-separated variants found in the data
- Collapse variants of the same place (case differences, parenthetical additions, punctuation differences)
- If an existing registry is provided, preserve its IDs and add new entries
- Every reference in the manuscript data must resolve to exactly one registry entry

Output ONLY the CSV (with header row). No commentary."""

    elif domain == 'values':
        existing = _read_existing_registry(ref_dir, 'values.csv')
        val_vals = _collect_column_values(ref_dir, 'scene-intent.csv', 'value_at_stake')
        all_refs = sorted(set(val_vals))
        raw_values = '\n'.join(f'- {v}' for v in all_refs)

        return f"""Build a canonical value-at-stake registry for a novel.

## All Value-at-Stake References Found in the Manuscript

{raw_values}

{f"## Existing Registry{chr(10)}{chr(10)}```{chr(10)}{existing}{chr(10)}```" if existing else ""}

## Instructions

A novel should have 8-15 core thematic values. Collapse over-specified entries into canonical abstract values.

Produce a pipe-delimited CSV with columns: id|name|aliases

Rules:
- id: kebab-case abstract concept (e.g., justice, truth, autonomy)
- name: display name (e.g., Justice)
- aliases: semicolon-separated variants and over-specified forms from the data
- "justice-specifically-whether-institutional-forms..." and "justice-specifically-restorative-accountability..." both map to "justice"
- If an existing registry has well-defined values, preserve those IDs
- Every reference in the manuscript data must resolve to exactly one registry entry

Output ONLY the CSV (with header row). No commentary."""

    elif domain == 'mice-threads':
        existing = _read_existing_registry(ref_dir, 'mice-threads.csv')
        timeline = _collect_mice_timeline(ref_dir)
        timeline_text = '\n'.join(
            f'  Scene {sid} (seq {seq}): {entry}'
            for sid, seq, entry in timeline
        )

        return f"""Build a canonical MICE thread registry for a novel and reconcile thread opens/closes.

## MICE Thread Timeline (in scene order)

{timeline_text}

{f"## Existing Registry{chr(10)}{chr(10)}```{chr(10)}{existing}{chr(10)}```" if existing else ""}

## Instructions

### Part 1: Registry

Produce a pipe-delimited CSV with columns: id|name|type|aliases

Rules:
- id: kebab-case slug (e.g., who-killed-rowan)
- name: descriptive name (e.g., Who killed Rowan?)
- type: milieu, inquiry, character, or event
- aliases: semicolon-separated variants from the data
- Match orphaned closes to opens — if -inquiry:can-Cora-be-trusted-at-Lenas-table has no open but +inquiry:can-cora-be-trusted exists, they are the same thread
- Every +/- reference in the timeline must resolve to exactly one registry entry

### Part 2: Normalized Timeline

After the registry CSV, output a UPDATES section listing every scene whose mice_threads value should change:

UPDATE: scene_id | new_mice_threads_value

Only include scenes that need changes (orphan matches, name normalization, type corrections).

Output the registry CSV first, then a blank line, then "UPDATES" on its own line, then the update lines. No other commentary."""

    elif domain == 'knowledge':
        existing = _read_existing_registry(ref_dir, 'knowledge.csv')
        chain = _collect_knowledge_chain(ref_dir)
        chain_text = '\n'.join(
            f'  Scene {sid} (seq {seq}):\n'
            f'    IN:  {k_in or "(empty)"}\n'
            f'    OUT: {k_out or "(empty)"}'
            for sid, seq, k_in, k_out in chain
        )

        return f"""Build a canonical knowledge fact registry for a novel and normalize the knowledge chain.

## Knowledge Chain (in scene order)

{chain_text}

{f"## Existing Registry{chr(10)}{chr(10)}```{chr(10)}{existing}{chr(10)}```" if existing else ""}

## Instructions

### Part 1: Registry

Produce a pipe-delimited CSV with columns: id|name|aliases|category|origin

Rules:
- id: kebab-case slug (e.g., marcus-killed-elena)
- name: descriptive name (e.g., Marcus killed Elena)
- aliases: semicolon-separated variants of the same fact found across scenes
- category: identity, motive-intent, capability-constraint, state-change, stakes-threat, or relationship-shift
- origin: scene ID where this fact first appears in knowledge_out, or "backstory" if the fact is known before scene 1
- Merge variants: if the same fact is worded differently in different scenes, they are one registry entry
- If an existing registry is provided, preserve its IDs where possible

### Part 2: Normalized Chain

After the registry CSV, output an UPDATES section:

UPDATE: scene_id | knowledge_in | knowledge_out

Use canonical fact IDs (semicolon-separated). Only include scenes that need changes.
Backstory facts that characters know entering scene 1 should appear in scene 1's knowledge_in.

Output the registry CSV first, then a blank line, then "UPDATES" on its own line, then the update lines. No other commentary."""

    elif domain == 'physical-states':
        existing = _read_existing_registry(ref_dir, 'physical-states.csv')
        chain = _collect_physical_state_chain(ref_dir)
        chain_text = '\n'.join(
            f'  Scene {sid} (seq {seq}):\n'
            f'    IN:  {ps_in or "(empty)"}\n'
            f'    OUT: {ps_out or "(empty)"}'
            for sid, seq, ps_in, ps_out in chain
        )

        return f"""Build a canonical physical state registry for a novel and normalize the state chain.

## Physical State Chain (in scene order)

{chain_text}

{f"## Existing Registry{chr(10)}{chr(10)}```{chr(10)}{existing}{chr(10)}```" if existing else ""}

## Instructions

### Part 1: Registry

Produce a pipe-delimited CSV with columns: id|character|description|category|acquired|resolves|action_gating

Rules:
- id: kebab-case slug scoped to character (e.g., broken-arm-marcus, has-compass-elena)
- character: canonical character name
- description: concise, prose-usable description (under 20 words)
- category: injury, equipment, ability, appearance, or fatigue
- acquired: scene ID where this state first appears in physical_state_out
- resolves: scene ID where removed from physical_state_out, or "never" for permanent
- action_gating: true if this state constrains what the character can physically do, false otherwise
- Merge variants: if the same state is described differently across scenes, they are one entry
- If an existing registry is provided, preserve its IDs where possible

### Part 2: Normalized Chain

After the registry CSV, output an UPDATES section:

UPDATE: scene_id | physical_state_in | physical_state_out

Use canonical state IDs (semicolon-separated). Only include scenes that need changes.

Output the registry CSV first, then a blank line, then "UPDATES" on its own line, then the update lines. No other commentary."""

    else:
        raise ValueError(f'Unknown reconciliation domain: {domain}')


# ============================================================================
# Registry response parsing
# ============================================================================

_REGISTRY_COLUMNS = {
    'characters': ['id', 'name', 'role', 'aliases'],
    'locations': ['id', 'name', 'aliases'],
    'values': ['id', 'name', 'aliases'],
    'mice-threads': ['id', 'name', 'type', 'aliases'],
    'knowledge': ['id', 'name', 'aliases', 'category', 'origin'],
    'physical-states': ['id', 'character', 'description', 'category', 'acquired', 'resolves', 'action_gating'],
}


def parse_registry_response(
    response: str, domain: str
) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    """Parse an Opus registry-build response.

    Returns:
        (registry_rows, updates) where registry_rows is a list of dicts
        keyed by the domain's columns, and updates is a list of
        (scene_id, value_string) tuples from UPDATE lines.
    """
    if domain not in _REGISTRY_COLUMNS:
        raise ValueError(f'Unknown reconciliation domain: {domain}')

    columns = _REGISTRY_COLUMNS[domain]
    rows: list[dict[str, str]] = []
    updates: list[tuple[str, str]] = []
    in_updates = False
    header_seen = False

    for line in response.split('\n'):
        line = line.strip()
        if not line:
            continue

        # Check for UPDATES section marker
        if line.upper() == 'UPDATES':
            in_updates = True
            continue

        if in_updates:
            if not line.startswith('UPDATE:'):
                continue
            payload = line[len('UPDATE:'):].strip()
            parts = payload.split('|', 1)
            if len(parts) < 2:
                continue
            scene_id = parts[0].strip()
            value = parts[1].strip()
            if scene_id:
                updates.append((scene_id, value))
        else:
            # Registry CSV parsing
            fields = [f.strip() for f in line.split('|')]
            # Skip header row
            if not header_seen and len(fields) > 0 and fields[0] == 'id':
                header_seen = True
                continue
            # Map fields to column names
            if len(fields) < len(columns):
                continue
            row = {}
            for i, col in enumerate(columns):
                row[col] = fields[i] if i < len(fields) else ''
            if not row.get('id'):
                continue
            rows.append(row)

    return rows, updates


# ============================================================================
# Domain-to-file mapping
# ============================================================================

_DOMAIN_TO_REGISTRY = {
    'characters': 'characters.csv',
    'locations': 'locations.csv',
    'values': 'values.csv',
    'mice-threads': 'mice-threads.csv',
    'knowledge': 'knowledge.csv',
    'physical-states': 'physical-states.csv',
}

# Which CSV columns to normalize per domain
_DOMAIN_TARGETS = {
    'characters': [
        ('scenes.csv', ['pov']),
        ('scene-intent.csv', ['characters', 'on_stage']),
    ],
    'locations': [
        ('scenes.csv', ['location']),
    ],
    'values': [
        ('scene-intent.csv', ['value_at_stake']),
    ],
    'mice-threads': [
        ('scene-intent.csv', ['mice_threads']),
    ],
    'knowledge': [
        ('scene-briefs.csv', ['knowledge_in', 'knowledge_out']),
    ],
    'physical-states': [
        ('scene-briefs.csv', ['physical_state_in', 'physical_state_out']),
    ],
}


# ============================================================================
# Registry writing
# ============================================================================

def write_registry(ref_dir: str, domain: str, rows: list[dict[str, str]]) -> None:
    """Write registry rows to the domain's CSV file.

    Args:
        ref_dir: Path to the reference/ directory.
        domain: One of the keys in _DOMAIN_TO_REGISTRY.
        rows: List of dicts keyed by the domain's columns.
    """
    if domain not in _DOMAIN_TO_REGISTRY:
        raise ValueError(f'Unknown reconciliation domain: {domain}')
    filename = _DOMAIN_TO_REGISTRY[domain]
    columns = _REGISTRY_COLUMNS[domain]
    path = os.path.join(ref_dir, filename)
    _write_csv(path, rows, columns)


# ============================================================================
# Update application
# ============================================================================

def apply_updates(
    ref_dir: str, domain: str, updates: list[tuple[str, str]]
) -> int:
    """Apply UPDATE lines from Opus response to scene CSVs.

    Args:
        ref_dir: Path to the reference/ directory.
        domain: The reconciliation domain.
        updates: List of (scene_id, value_string) tuples.

    Returns:
        Number of updates successfully applied.
    """
    if not updates:
        return 0

    if domain == 'mice-threads':
        intent_path = os.path.join(ref_dir, 'scene-intent.csv')
        rows = _read_csv(intent_path)
        if not rows:
            return 0
        row_map = {r['id']: r for r in rows if 'id' in r}
        applied = 0
        for scene_id, value in updates:
            if scene_id in row_map:
                row_map[scene_id]['mice_threads'] = value
                applied += 1
        if applied:
            _write_csv(intent_path, rows, _FILE_MAP['scene-intent.csv'])
        return applied

    elif domain == 'knowledge':
        briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
        rows = _read_csv(briefs_path)
        if not rows:
            return 0
        row_map = {r['id']: r for r in rows if 'id' in r}
        applied = 0
        for scene_id, value in updates:
            if scene_id not in row_map:
                continue
            parts = value.split('|', 1)
            if len(parts) == 2:
                row_map[scene_id]['knowledge_in'] = parts[0].strip()
                row_map[scene_id]['knowledge_out'] = parts[1].strip()
                applied += 1
        if applied:
            _write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])
        return applied

    elif domain == 'physical-states':
        briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
        rows = _read_csv(briefs_path)
        if not rows:
            return 0
        row_map = {r['id']: r for r in rows if 'id' in r}
        applied = 0
        for scene_id, value in updates:
            if scene_id not in row_map:
                continue
            parts = value.split('|', 1)
            if len(parts) == 2:
                row_map[scene_id]['physical_state_in'] = parts[0].strip()
                row_map[scene_id]['physical_state_out'] = parts[1].strip()
                applied += 1
        if applied:
            _write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])
        return applied

    # Other domains have no update lines
    return 0


# ============================================================================
# Registry normalization
# ============================================================================

def apply_registry_normalization(
    domain: str, ref_dir: str
) -> int:
    """Load the domain's registry and normalize all target CSV columns.

    Args:
        domain: The reconciliation domain.
        ref_dir: Path to the reference/ directory.

    Returns:
        Total number of individual field values changed.
    """
    if domain not in _DOMAIN_TO_REGISTRY:
        raise ValueError(f'Unknown reconciliation domain: {domain}')

    registry_path = os.path.join(ref_dir, _DOMAIN_TO_REGISTRY[domain])

    # Load alias map (and type map for MICE)
    if domain == 'mice-threads':
        alias_map, type_map = load_mice_registry(registry_path)
    else:
        alias_map = load_alias_map(registry_path)
        type_map = None

    if not alias_map:
        return 0

    targets = _DOMAIN_TARGETS.get(domain, [])
    total_changed = 0

    for filename, columns in targets:
        path = os.path.join(ref_dir, filename)
        rows = _read_csv(path)
        if not rows:
            continue

        file_changed = 0
        for row in rows:
            for col in columns:
                old_val = row.get(col, '')
                if not old_val:
                    continue

                if domain == 'mice-threads' and col == 'mice_threads':
                    new_val = normalize_mice_threads(old_val, alias_map, type_map)
                else:
                    new_val = normalize_aliases(alias_map, old_val)

                if new_val != old_val:
                    row[col] = new_val
                    file_changed += 1

        if file_changed:
            _write_csv(path, rows, _FILE_MAP[filename])
            total_changed += file_changed

    return total_changed


# ============================================================================
# Full domain reconciliation
# ============================================================================

def reconcile_domain(
    domain: str, ref_dir: str, model: str, log_dir: str,
    context: str = ''
) -> dict:
    """Run full reconciliation for one domain.

    Args:
        domain: One of 'characters', 'locations', 'values',
                'mice-threads', 'knowledge', or 'outcomes'.
        ref_dir: Path to the reference/ directory.
        model: Anthropic model ID for the API call.
        log_dir: Directory for API log files.
        context: Optional extra context for the prompt.

    Returns:
        Dict with keys: registry_entries, updates_applied, fields_normalized.
    """
    # Outcomes are deterministic — no API call needed
    if domain == 'outcomes':
        changed = reconcile_outcomes(ref_dir)
        return {
            'registry_entries': 0,
            'updates_applied': 0,
            'fields_normalized': changed,
        }

    from storyforge.api import invoke_to_file, extract_text_from_file

    # Build prompt
    prompt = build_registry_prompt(domain, ref_dir, context=context)

    # Call API
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'reconcile-{domain}.json')
    invoke_to_file(prompt, model, log_file, max_tokens=4096)

    # Extract and parse response
    response = extract_text_from_file(log_file)
    registry_rows, updates = parse_registry_response(response, domain)

    # Write registry
    write_registry(ref_dir, domain, registry_rows)

    # Apply updates
    updates_applied = apply_updates(ref_dir, domain, updates)

    # Normalize fields
    fields_normalized = apply_registry_normalization(domain, ref_dir)

    return {
        'registry_entries': len(registry_rows),
        'updates_applied': updates_applied,
        'fields_normalized': fields_normalized,
    }


# ============================================================================
# Briefs domain: abstract language detection
# ============================================================================

ABSTRACT_INDICATORS = {
    'realizes', 'recognizes', 'connects', 'crystallizes', 'deepens',
    'builds', 'grows', 'shifts', 'transforms', 'emerges', 'settles',
    'dawns', 'unfolds', 'intensifies', 'resolves', 'strengthens',
    'the realization', 'the parallel', 'the tension', 'the connection',
    'the weight of', 'the cost of', 'the truth of', 'the meaning of',
    'beginning to', 'starting to', 'learning to',
}

CONCRETE_INDICATORS = {
    'hands', 'eyes', 'door', 'walks', 'picks up', 'sets down',
    'turns', 'stops', 'reaches', 'holds', 'drops', 'pulls',
    'sits', 'stands', 'crosses', 'opens', 'closes', 'looks',
    'says', 'asks', 'watches', 'hears', 'smells', 'tastes',
    'runs', 'steps', 'grabs', 'pushes', 'carries', 'presses',
}

_CONCRETIZABLE_FIELDS = ['key_actions', 'crisis', 'decision']


def detect_abstract_fields(
    briefs_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Scan brief fields for abstract/thematic language.

    Args:
        briefs_map: dict keyed by scene ID, values are brief row dicts.
        scene_ids: Optional list of scene IDs to check. If None, check all.

    Returns:
        List of dicts: {scene_id, field, value, abstract_count, concrete_count}.
        Only returns fields where abstract_count >= 2 and abstract_count > concrete_count.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(briefs_map.keys())

    for sid in ids_to_check:
        brief = briefs_map.get(sid, {})
        for field in _CONCRETIZABLE_FIELDS:
            value = brief.get(field, '').strip()
            if not value:
                continue

            value_lower = value.lower()
            abstract_count = sum(1 for ind in ABSTRACT_INDICATORS if ind in value_lower)
            concrete_count = sum(1 for ind in CONCRETE_INDICATORS if ind in value_lower)

            if abstract_count >= 2 and abstract_count > concrete_count:
                results.append({
                    'scene_id': sid,
                    'field': field,
                    'value': value,
                    'abstract_count': abstract_count,
                    'concrete_count': concrete_count,
                })

    return results


# ============================================================================
# Briefs domain: concretization prompt builder and parser
# ============================================================================

def build_concretize_prompt(
    scene_id: str,
    fields: list[str],
    current_values: dict[str, str],
    voice_guide: str = '',
    character_entry: str = '',
) -> str:
    """Build prompt to rewrite abstract brief fields as concrete physical beats.

    Args:
        scene_id: The scene being concretized.
        fields: List of field names to rewrite.
        current_values: Dict of field_name -> current value.
        voice_guide: Excerpt from the voice guide (POV character's sensory palette).
        character_entry: Character bible entry for the POV character.

    Returns:
        Prompt string for Claude.
    """
    field_block = '\n'.join(
        f"**{field}:** {current_values.get(field, '')}"
        for field in fields
    )

    field_output = '\n'.join(f'{field}: [rewritten value]' for field in fields)

    return f"""Rewrite these scene brief fields so every item is something the POV character physically does or perceives.

## Scene: {scene_id}

## Current Values (abstract — need rewriting)
{field_block}

## Voice Guide (POV character)
{voice_guide if voice_guide else '(not available)'}

## Character
{character_entry if character_entry else '(not available)'}

## Rules

1. Every action must be something the POV character physically does or perceives through their senses. No thematic descriptions, no narrator interpretations, no emotion names as events.
2. Replace "the realization building" with what the character DOES when they realize something (hands stop, breath catches, they set something down).
3. Replace "tension deepening" with what the character SEES or FEELS (someone's jaw tightening, the room going quiet, a hand moving to a weapon).
4. Replace "connecting X to Y" with the physical moment: what does the character look at, touch, or say when the connection happens?
5. Keep the same number of beats (semicolon-separated items). Don't add or remove story events — just rewrite HOW they're described.
6. Use the character's sensory palette from the voice guide. If they think in food metaphors, their observations should reflect that.

## Output Format

Return each field on its own labeled line, exactly like the input but rewritten:

{field_output}

No explanation. No markdown. Just the labeled lines."""


def parse_concretize_response(
    response: str, scene_id: str, fields: list[str]
) -> dict[str, str]:
    """Parse concretization response into field values.

    Returns:
        Dict mapping field_name -> rewritten value.
    """
    result = {}
    for line in response.split('\n'):
        line = line.strip()
        if not line:
            continue
        for field in fields:
            prefix = f'{field}:'
            if line.lower().startswith(prefix.lower()):
                value = line[len(prefix):].strip()
                if value:
                    result[field] = value
                break
    return result


# ============================================================================
# Briefs domain: hone_briefs
# ============================================================================

def hone_briefs(
    ref_dir: str,
    project_dir: str,
    scene_ids: list[str] | None = None,
    threshold: float = 3.5,
    model: str = '',
    log_dir: str = '',
    coaching_level: str = 'full',
    dry_run: bool = False,
) -> dict:
    """Concretize abstract brief fields as concrete physical beats.

    Args:
        ref_dir: Path to reference/ directory.
        project_dir: Path to project root.
        scene_ids: Optional list of scene IDs to check. If None, check all.
        threshold: prose_naturalness score threshold (scenes below this are flagged).
        model: Anthropic model ID for API calls.
        log_dir: Directory for API log files.
        coaching_level: full/coach/strict.
        dry_run: If True, detect but don't rewrite.

    Returns:
        Dict with scenes_flagged, scenes_rewritten, fields_rewritten.
    """
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    # Detect abstract fields
    flagged = detect_abstract_fields(briefs_map, scene_ids)

    if dry_run or not flagged:
        return {
            'scenes_flagged': len(set(f['scene_id'] for f in flagged)),
            'scenes_rewritten': 0,
            'fields_rewritten': 0,
        }

    if coaching_level == 'strict':
        # Save analysis only
        hone_dir = os.path.join(project_dir, 'working', 'hone')
        os.makedirs(hone_dir, exist_ok=True)
        for f in flagged:
            path = os.path.join(hone_dir, f'briefs-analysis-{f["scene_id"]}.md')
            with open(path, 'w') as fh:
                fh.write(f"# Brief Analysis: {f['scene_id']}\n\n")
                fh.write(f"**Field:** {f['field']}\n")
                fh.write(f"**Current:** {f['value']}\n")
                fh.write(f"**Abstract indicators:** {f['abstract_count']}\n")
                fh.write(f"**Concrete indicators:** {f['concrete_count']}\n")
        return {
            'scenes_flagged': len(set(f['scene_id'] for f in flagged)),
            'scenes_rewritten': 0,
            'fields_rewritten': 0,
        }

    # Load voice guide and character bible for prompt building
    voice_guide = ''
    voice_path = os.path.join(ref_dir, 'voice-guide.md')
    if os.path.isfile(voice_path):
        with open(voice_path, encoding='utf-8') as fh:
            voice_guide = fh.read()

    char_bible = ''
    char_path = os.path.join(ref_dir, 'character-bible.md')
    if os.path.isfile(char_path):
        with open(char_path, encoding='utf-8') as fh:
            char_bible = fh.read()

    from storyforge.api import invoke_to_file, extract_text_from_file

    # Group flagged fields by scene
    by_scene: dict[str, list[str]] = {}
    for f in flagged:
        by_scene.setdefault(f['scene_id'], []).append(f['field'])

    scenes_rewritten = 0
    fields_rewritten = 0

    for sid, fields in by_scene.items():
        current_values = {field: briefs_map[sid].get(field, '') for field in fields}

        prompt = build_concretize_prompt(
            scene_id=sid,
            fields=fields,
            current_values=current_values,
            voice_guide=voice_guide[:3000],
            character_entry=char_bible[:2000],
        )

        if coaching_level == 'coach':
            # Save proposal for author review
            hone_dir = os.path.join(project_dir, 'working', 'hone')
            os.makedirs(hone_dir, exist_ok=True)
            proposal_path = os.path.join(hone_dir, f'briefs-{sid}.md')
            with open(proposal_path, 'w') as fh:
                fh.write(f"# Brief Concretization Proposal: {sid}\n\n")
                fh.write(f"## Current\n")
                for field in fields:
                    fh.write(f"**{field}:** {current_values[field]}\n\n")
                fh.write(f"## Prompt\n\n{prompt}\n")
            continue

        # full coaching: call API and apply
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f'hone-briefs-{sid}.json')
        invoke_to_file(prompt, model, log_file, max_tokens=2048)
        response = extract_text_from_file(log_file)

        rewrites = parse_concretize_response(response, sid, fields)
        for field, new_value in rewrites.items():
            if new_value and new_value != current_values.get(field):
                briefs_map[sid][field] = new_value
                fields_rewritten += 1

        if rewrites:
            scenes_rewritten += 1

    # Write back if any changes were made
    if fields_rewritten > 0:
        briefs_rows = list(briefs_map.values())
        briefs_rows.sort(key=lambda r: r.get('id', ''))
        _write_csv(
            os.path.join(ref_dir, 'scene-briefs.csv'),
            briefs_rows,
            _FILE_MAP['scene-briefs.csv'],
        )

    return {
        'scenes_flagged': len(by_scene),
        'scenes_rewritten': scenes_rewritten,
        'fields_rewritten': fields_rewritten,
    }


# ============================================================================
# Gaps domain: detect missing fields
# ============================================================================

_GAPS_REQUIRED = {
    'briefed': [
        'function', 'value_at_stake', 'value_shift', 'emotional_arc',
        'goal', 'conflict', 'outcome', 'crisis', 'decision',
    ],
    'drafted': [
        'function', 'value_at_stake', 'value_shift', 'emotional_arc',
        'goal', 'conflict', 'outcome', 'crisis', 'decision',
    ],
}


def detect_gaps(
    scenes_map: dict[str, dict],
    intent_map: dict[str, dict],
    briefs_map: dict[str, dict],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Scan for empty required fields given each scene's status.

    Returns:
        List of dicts: {scene_id, field, status, file}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(scenes_map.keys())

    for sid in ids_to_check:
        scene = scenes_map.get(sid, {})
        status = scene.get('status', 'spine')
        required = _GAPS_REQUIRED.get(status, [])
        if not required:
            continue

        # Merge all data for this scene
        merged = dict(scene)
        if sid in intent_map:
            merged.update({k: v for k, v in intent_map[sid].items() if k != 'id'})
        if sid in briefs_map:
            merged.update({k: v for k, v in briefs_map[sid].items() if k != 'id'})

        for field in required:
            if not merged.get(field, '').strip():
                # Determine which file owns this field
                file = 'scene-briefs.csv'
                if field in ('function', 'value_at_stake', 'value_shift', 'emotional_arc'):
                    file = 'scene-intent.csv'
                results.append({
                    'scene_id': sid,
                    'field': field,
                    'status': status,
                    'file': file,
                })

    return results
