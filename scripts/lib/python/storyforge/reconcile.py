"""Post-extraction reconciliation — build registries and normalize fields.

Domains:
- characters, locations (after Phase 1)
- values, mice-threads (after Phase 2)
- knowledge, outcomes (after Phase 3)
"""

import csv
import os
import re

from storyforge.elaborate import (
    _read_csv, _read_csv_as_map, _write_csv, _FILE_MAP, DELIMITER,
)
from storyforge.enrich import load_alias_map, load_mice_registry

# ============================================================================
# Outcome normalization (deterministic — no API call)
# ============================================================================

_OUTCOME_ENUM = {'yes', 'yes-but', 'no', 'no-and'}
_OUTCOME_RE = re.compile(
    r'^\[?(yes-but|no-and|yes|no)\b',
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

    else:
        raise ValueError(f'Unknown reconciliation domain: {domain}')
