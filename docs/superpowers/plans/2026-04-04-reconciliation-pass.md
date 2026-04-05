# Reconciliation Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a post-extraction reconciliation pass that builds/updates registries using Opus and normalizes all CSV fields for cross-scene consistency.

**Architecture:** New Python module `reconcile.py` with prompt builders and response parsers per domain. New shell script `storyforge-reconcile` that orchestrates the flow. Hooks into `storyforge-extract` after each phase. Reuses existing `enrich.py` alias infrastructure for the deterministic normalization step.

**Tech Stack:** Python 3 (storyforge modules), bash (script shell), Anthropic Messages API (Opus for registry builds)

---

## File Structure

| File | Responsibility |
|------|---------------|
| Create: `scripts/lib/python/storyforge/reconcile.py` | Prompt builders, response parsers, normalization functions per domain |
| Create: `scripts/storyforge-reconcile` | Standalone shell script — orchestrates registry build + normalization per domain |
| Create: `tests/test-reconcile.sh` | Tests for reconcile.py functions (deterministic parts) |
| Modify: `scripts/storyforge-extract` | Add reconcile hooks after each extraction phase |

---

### Task 1: Outcome Normalization (deterministic, no API)

The simplest domain — no Opus call needed. Establishes the module and test patterns.

**Files:**
- Create: `scripts/lib/python/storyforge/reconcile.py`
- Create: `tests/test-reconcile.sh`

- [ ] **Step 1: Write the failing test for normalize_outcomes**

In `tests/test-reconcile.sh`:
```bash
#!/bin/bash
# test-reconcile.sh — Tests for reconciliation module

PY="import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python'"

# ============================================================================
# normalize_outcomes
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import normalize_outcomes

# Simple enums pass through
assert normalize_outcomes('yes') == 'yes'
assert normalize_outcomes('yes-but') == 'yes-but'
assert normalize_outcomes('no-and') == 'no-and'
assert normalize_outcomes('no') == 'no'

# Elaborated outcomes get stripped to enum
assert normalize_outcomes('yes-but — Hank successfully maps the full architecture') == 'yes-but'
assert normalize_outcomes('no-and — she fails to convince the council') == 'no-and'
assert normalize_outcomes('yes — clean victory') == 'yes'

# Bracketed outcomes
assert normalize_outcomes('[yes-but]') == 'yes-but'
assert normalize_outcomes('[no-and — elaboration]') == 'no-and'

# Empty or unknown pass through unchanged
assert normalize_outcomes('') == ''
assert normalize_outcomes('unknown format') == 'unknown format'

print('all passed')
")
assert_equals "all passed" "$RESULT" "normalize_outcomes: strips elaborations to enum values"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-reconcile.sh`
Expected: FAIL — module not found

- [ ] **Step 3: Write normalize_outcomes in reconcile.py**

Create `scripts/lib/python/storyforge/reconcile.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-reconcile.sh`
Expected: PASS

- [ ] **Step 5: Write test for reconcile_outcomes on CSV**

Append to `tests/test-reconcile.sh`:
```bash
# ============================================================================
# reconcile_outcomes (CSV-level)
# ============================================================================

OUTCOME_DIR="${TMPDIR}/outcome-test/reference"
mkdir -p "$OUTCOME_DIR"
cat > "${OUTCOME_DIR}/scene-briefs.csv" <<'CSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
s01|g|c|yes-but — long elaboration here|cr|d|k|k|a|d|e|m||false
s02|g|c|no-and|cr|d|k|k|a|d|e|m||false
s03|g|c|[yes]|cr|d|k|k|a|d|e|m||false
s04|g|c|yes|cr|d|k|k|a|d|e|m||false
CSV

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import reconcile_outcomes
changed = reconcile_outcomes('${OUTCOME_DIR}')
print(changed)
")
assert_equals "2" "$RESULT" "reconcile_outcomes: normalizes 2 elaborated outcomes"

# Verify the CSV was rewritten correctly
OUTCOME_CHECK=$(python3 -c "
${PY})
from storyforge.elaborate import _read_csv_as_map
m = _read_csv_as_map('${OUTCOME_DIR}/scene-briefs.csv')
print(m['s01']['outcome'])
print(m['s03']['outcome'])
")
assert_contains "$OUTCOME_CHECK" "yes-but" "reconcile_outcomes: s01 normalized to yes-but"
assert_contains "$OUTCOME_CHECK" "yes" "reconcile_outcomes: s03 normalized to yes"

rm -rf "${TMPDIR}/outcome-test"
```

- [ ] **Step 6: Run test, verify pass**

Run: `./tests/run-tests.sh tests/test-reconcile.sh`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/reconcile.py tests/test-reconcile.sh
git commit -m "Add reconcile module with outcome normalization"
git push
```

---

### Task 2: Registry Prompt Builders

Build the Opus prompts for each domain. These are pure functions (no API calls) so they're fully testable.

**Files:**
- Modify: `scripts/lib/python/storyforge/reconcile.py`
- Modify: `tests/test-reconcile.sh`

- [ ] **Step 1: Write failing test for build_registry_prompt**

Append to `tests/test-reconcile.sh`:
```bash
# ============================================================================
# build_registry_prompt — characters
# ============================================================================

PROMPT_DIR="${TMPDIR}/prompt-test/reference"
mkdir -p "$PROMPT_DIR"
cat > "${PROMPT_DIR}/scenes.csv" <<'CSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
s01|1|Scene One|1|Kael|The Hold|1|morning|1 hour|action|drafted|1000|2000
s02|2|Scene Two|1|kael|Thornwall Hold|1|afternoon|1 hour|action|drafted|1000|2000
s03|3|Scene Three|1|Sera Vasht|The Fissure|2|morning|1 hour|action|drafted|1000|2000
CSV
cat > "${PROMPT_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
s01|test|action|flat|truth|+/-|revelation|Kael;Sera|Kael|+inquiry:mystery
s02|test|action|flat|truth|+/-|revelation|kael;Bren|kael|
s03|test|action|flat|justice|+/-|revelation|Sera Vasht;Kael Davreth|Sera Vasht|-inquiry:mystery
CSV

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import build_registry_prompt
prompt = build_registry_prompt('characters', '${PROMPT_DIR}')
print('HAS_HEADER' if 'character registry' in prompt.lower() else 'NO_HEADER')
print('HAS_KAEL' if 'Kael' in prompt else 'NO_KAEL')
print('HAS_SERA' if 'Sera' in prompt else 'NO_SERA')
print('HAS_BREN' if 'Bren' in prompt else 'NO_BREN')
print('HAS_FORMAT' if 'id|name' in prompt else 'NO_FORMAT')
")
assert_contains "$RESULT" "HAS_HEADER" "build_registry_prompt: characters prompt has header"
assert_contains "$RESULT" "HAS_KAEL" "build_registry_prompt: characters prompt includes Kael"
assert_contains "$RESULT" "HAS_SERA" "build_registry_prompt: characters prompt includes Sera"
assert_contains "$RESULT" "HAS_BREN" "build_registry_prompt: characters prompt includes Bren"
assert_contains "$RESULT" "HAS_FORMAT" "build_registry_prompt: characters prompt specifies output format"

rm -rf "${TMPDIR}/prompt-test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-reconcile.sh`
Expected: FAIL — function not defined

- [ ] **Step 3: Write build_registry_prompt and parse_registry_response**

Append to `reconcile.py`:
```python
from storyforge.enrich import load_alias_map, load_mice_registry


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-reconcile.sh`
Expected: PASS

- [ ] **Step 5: Add prompt tests for locations and values**

Append to `tests/test-reconcile.sh`:
```bash
# ============================================================================
# build_registry_prompt — locations
# ============================================================================

LOC_DIR="${TMPDIR}/loc-prompt-test/reference"
mkdir -p "$LOC_DIR"
cat > "${LOC_DIR}/scenes.csv" <<'CSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
s01|1|One|1|Alice|The Hold|1|morning|1 hour|action|drafted|1000|2000
s02|2|Two|1|Alice|Thornwall Hold|1|afternoon|1 hour|action|drafted|1000|2000
s03|3|Three|1|Alice|the hold|2|morning|1 hour|action|drafted|1000|2000
CSV

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import build_registry_prompt
prompt = build_registry_prompt('locations', '${LOC_DIR}')
print('HAS_HOLD' if 'The Hold' in prompt else 'NO_HOLD')
print('HAS_THORNWALL' if 'Thornwall Hold' in prompt else 'NO_THORNWALL')
print('HAS_FORMAT' if 'id|name|aliases' in prompt else 'NO_FORMAT')
")
assert_contains "$RESULT" "HAS_HOLD" "build_registry_prompt: locations includes The Hold"
assert_contains "$RESULT" "HAS_THORNWALL" "build_registry_prompt: locations includes Thornwall Hold"
assert_contains "$RESULT" "HAS_FORMAT" "build_registry_prompt: locations specifies output format"
rm -rf "${TMPDIR}/loc-prompt-test"

# ============================================================================
# build_registry_prompt — values
# ============================================================================

VAL_DIR="${TMPDIR}/val-prompt-test/reference"
mkdir -p "$VAL_DIR"
cat > "${VAL_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
s01|test|action|flat|justice|+/-|revelation|A|A|
s02|test|action|flat|justice-specifically-restorative|+/-|revelation|A|A|
s03|test|action|flat|truth|+/-|revelation|A|A|
CSV

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import build_registry_prompt
prompt = build_registry_prompt('values', '${VAL_DIR}')
print('HAS_JUSTICE' if 'justice' in prompt else 'NO_JUSTICE')
print('HAS_COLLAPSE' if '8-15' in prompt else 'NO_COLLAPSE')
")
assert_contains "$RESULT" "HAS_JUSTICE" "build_registry_prompt: values includes justice"
assert_contains "$RESULT" "HAS_COLLAPSE" "build_registry_prompt: values mentions 8-15 core values"
rm -rf "${TMPDIR}/val-prompt-test"
```

- [ ] **Step 6: Run tests, verify pass**

Run: `./tests/run-tests.sh tests/test-reconcile.sh`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/reconcile.py tests/test-reconcile.sh
git commit -m "Add registry prompt builders for all reconciliation domains"
git push
```

---

### Task 3: Registry Response Parsers

Parse Opus responses back into registry CSVs and update lines.

**Files:**
- Modify: `scripts/lib/python/storyforge/reconcile.py`
- Modify: `tests/test-reconcile.sh`

- [ ] **Step 1: Write failing test for parse_registry_response**

Append to `tests/test-reconcile.sh`:
```bash
# ============================================================================
# parse_registry_response — simple registry (characters)
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import parse_registry_response

response = '''id|name|role|aliases
kael-davreth|Kael Davreth|protagonist|Kael;kael;Kael Davreth;Kael Bren
sera-vasht|Sera Vasht|protagonist|Sera;sera;Sera Vasht
bren-tael|Bren Tael|supporting|Bren;bren
'''

registry_rows, updates = parse_registry_response(response, 'characters')
print(f'rows={len(registry_rows)}')
print(f'id0={registry_rows[0][\"id\"]}')
print(f'updates={len(updates)}')
")
assert_contains "$RESULT" "rows=3" "parse_registry_response: parses 3 character rows"
assert_contains "$RESULT" "id0=kael-davreth" "parse_registry_response: first row ID correct"
assert_contains "$RESULT" "updates=0" "parse_registry_response: no updates for simple registry"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-reconcile.sh`
Expected: FAIL

- [ ] **Step 3: Write parse_registry_response**

Append to `reconcile.py`:
```python
# ============================================================================
# Registry response parsers
# ============================================================================

_REGISTRY_COLUMNS = {
    'characters': ['id', 'name', 'role', 'aliases'],
    'locations': ['id', 'name', 'aliases'],
    'values': ['id', 'name', 'aliases'],
    'mice-threads': ['id', 'name', 'type', 'aliases'],
    'knowledge': ['id', 'name', 'aliases', 'category', 'origin'],
}


def parse_registry_response(
    response: str, domain: str,
) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    """Parse an Opus registry-build response.

    Returns:
        (registry_rows, updates)
        registry_rows: list of dicts with the domain's columns
        updates: list of (scene_id, new_value) for MICE/knowledge UPDATE lines
    """
    columns = _REGISTRY_COLUMNS.get(domain)
    if not columns:
        raise ValueError(f'Unknown domain: {domain}')

    lines = response.strip().split('\n')
    registry_rows: list[dict[str, str]] = []
    updates: list[tuple[str, str]] = []
    in_updates = False
    header_seen = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Detect UPDATES section
        if line.upper() == 'UPDATES':
            in_updates = True
            continue

        if in_updates:
            # Parse UPDATE: scene_id | value  or  UPDATE: scene_id | val1 | val2
            if line.upper().startswith('UPDATE:'):
                parts = line[7:].split('|')
                parts = [p.strip() for p in parts]
                if len(parts) >= 2:
                    scene_id = parts[0]
                    # For knowledge: parts[1] = knowledge_in, parts[2] = knowledge_out
                    # For mice-threads: parts[1] = new mice_threads value
                    value = '|'.join(parts[1:])
                    updates.append((scene_id, value))
            continue

        # Parse registry CSV rows
        if '|' in line:
            parts = line.split('|')
            # Skip header row
            if not header_seen and parts[0].strip().lower() == 'id':
                header_seen = True
                continue
            # Build row dict
            row = {}
            for i, col in enumerate(columns):
                row[col] = parts[i].strip() if i < len(parts) else ''
            if row.get('id'):
                registry_rows.append(row)

    return registry_rows, updates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-reconcile.sh`
Expected: PASS

- [ ] **Step 5: Write test for MICE response with UPDATES section**

Append to `tests/test-reconcile.sh`:
```bash
# ============================================================================
# parse_registry_response — mice-threads with updates
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import parse_registry_response

response = '''id|name|type|aliases
who-killed-rowan|Who killed Rowan?|inquiry|who-killed-rowan;can-Cora-be-trusted-at-Lenas-table
cora-transformation|Cora's transformation|character|cora-dunning;Cora-as-pilgrim

UPDATES
UPDATE: lenas-porch | -character:cora-transformation
UPDATE: field-book | -character:cora-transformation;+inquiry:who-killed-rowan
'''

registry_rows, updates = parse_registry_response(response, 'mice-threads')
print(f'rows={len(registry_rows)}')
print(f'updates={len(updates)}')
print(f'u0_scene={updates[0][0]}')
print(f'type0={registry_rows[0][\"type\"]}')
")
assert_contains "$RESULT" "rows=2" "parse_registry_response: mice-threads parses 2 rows"
assert_contains "$RESULT" "updates=2" "parse_registry_response: mice-threads has 2 updates"
assert_contains "$RESULT" "u0_scene=lenas-porch" "parse_registry_response: first update scene ID"
assert_contains "$RESULT" "type0=inquiry" "parse_registry_response: first row type"
```

- [ ] **Step 6: Run tests, verify pass**

Run: `./tests/run-tests.sh tests/test-reconcile.sh`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/reconcile.py tests/test-reconcile.sh
git commit -m "Add registry response parsers for reconciliation"
git push
```

---

### Task 4: Reconcile Functions (per domain)

Wire together: build prompt → call API → parse response → write registry → normalize CSV fields. These are the main entry points called by the shell script.

**Files:**
- Modify: `scripts/lib/python/storyforge/reconcile.py`
- Modify: `tests/test-reconcile.sh`

- [ ] **Step 1: Write test for reconcile_domain (deterministic normalization part)**

We can't test the Opus call in unit tests, but we can test the normalization that happens after the registry is written. Append to `tests/test-reconcile.sh`:
```bash
# ============================================================================
# apply_registry_normalization — characters
# ============================================================================

NORM_DIR="${TMPDIR}/norm-test/reference"
mkdir -p "$NORM_DIR"
cat > "${NORM_DIR}/scenes.csv" <<'CSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
s01|1|One|1|Kael|The Hold|1|morning|1 hour|action|drafted|1000|2000
s02|2|Two|1|kael|Thornwall|1|afternoon|1 hour|action|drafted|1000|2000
s03|3|Three|1|Sera Vasht|The Fissure|2|morning|1 hour|action|drafted|1000|2000
CSV
cat > "${NORM_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
s01|test|action|flat|truth|+/-|revelation|Kael;Sera|Kael|
s02|test|action|flat|truth|+/-|revelation|kael;Bren|kael|
s03|test|action|flat|justice|+/-|revelation|Sera Vasht;Kael Davreth|Sera Vasht|
CSV
# Write a character registry
cat > "${NORM_DIR}/characters.csv" <<'CSV'
id|name|role|aliases
kael|Kael Davreth|protagonist|Kael;kael;Kael Davreth
sera|Sera Vasht|protagonist|Sera;sera;Sera Vasht
bren|Bren Tael|supporting|Bren;bren
CSV

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import apply_registry_normalization
changed = apply_registry_normalization('characters', '${NORM_DIR}')
print(f'changed={changed}')

from storyforge.elaborate import _read_csv_as_map
scenes = _read_csv_as_map('${NORM_DIR}/scenes.csv')
intent = _read_csv_as_map('${NORM_DIR}/scene-intent.csv')
print(f'pov1={scenes[\"s01\"][\"pov\"]}')
print(f'pov2={scenes[\"s02\"][\"pov\"]}')
print(f'pov3={scenes[\"s03\"][\"pov\"]}')
print(f'chars3={intent[\"s03\"][\"characters\"]}')
")
assert_contains "$RESULT" "pov1=kael" "apply_registry_normalization: Kael normalized to kael"
assert_contains "$RESULT" "pov2=kael" "apply_registry_normalization: kael stays kael"
assert_contains "$RESULT" "pov3=sera" "apply_registry_normalization: Sera Vasht normalized to sera"
assert_contains "$RESULT" "chars3=sera;kael" "apply_registry_normalization: characters normalized"
rm -rf "${TMPDIR}/norm-test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-reconcile.sh`
Expected: FAIL

- [ ] **Step 3: Write apply_registry_normalization and reconcile_domain**

Append to `reconcile.py`:
```python
from storyforge.enrich import (
    load_alias_map, load_mice_registry, normalize_aliases,
    normalize_mice_threads as _normalize_mice_field,
)


# ============================================================================
# Registry normalization (deterministic — applied after registry is built)
# ============================================================================

_DOMAIN_TO_REGISTRY = {
    'characters': 'characters.csv',
    'locations': 'locations.csv',
    'values': 'values.csv',
    'mice-threads': 'mice-threads.csv',
    'knowledge': 'knowledge.csv',
}

# Which CSV files and columns each domain normalizes
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
}


def apply_registry_normalization(domain: str, ref_dir: str) -> int:
    """Normalize CSV fields against the domain's registry.

    Loads the registry, builds an alias map, and normalizes all
    target columns in the relevant CSV files.

    Returns total number of field values changed.
    """
    registry_file = _DOMAIN_TO_REGISTRY.get(domain)
    if not registry_file:
        return 0

    registry_path = os.path.join(ref_dir, registry_file)

    # Load alias map
    if domain == 'mice-threads':
        alias_map, types_map = load_mice_registry(registry_path)
    else:
        alias_map = load_alias_map(registry_path)
        types_map = None

    if not alias_map:
        return 0

    targets = _DOMAIN_TARGETS.get(domain, [])
    total_changed = 0

    for csv_filename, columns in targets:
        csv_path = os.path.join(ref_dir, csv_filename)
        rows = _read_csv(csv_path)
        if not rows:
            continue

        changed = False
        for row in rows:
            for col in columns:
                old_val = row.get(col, '')
                if not old_val.strip():
                    continue

                if domain == 'mice-threads' and col == 'mice_threads':
                    new_val = _normalize_mice_field(old_val, alias_map, types_map or {})
                else:
                    new_val = normalize_aliases(alias_map, old_val)

                if new_val != old_val:
                    row[col] = new_val
                    total_changed += 1
                    changed = True

        if changed:
            _write_csv(csv_path, rows, _FILE_MAP[csv_filename])

    return total_changed


def write_registry(ref_dir: str, domain: str,
                   rows: list[dict[str, str]]) -> None:
    """Write registry rows to the domain's CSV file."""
    registry_file = _DOMAIN_TO_REGISTRY.get(domain)
    if not registry_file:
        return
    columns = _REGISTRY_COLUMNS[domain]
    path = os.path.join(ref_dir, registry_file)
    _write_csv(path, rows, columns)


def apply_updates(ref_dir: str, domain: str,
                  updates: list[tuple[str, str]]) -> int:
    """Apply UPDATE lines from the Opus response to scene CSVs.

    Returns number of updates applied.
    """
    if not updates:
        return 0

    if domain == 'mice-threads':
        intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
        applied = 0
        for scene_id, new_val in updates:
            if scene_id in intent_map:
                intent_map[scene_id]['mice_threads'] = new_val
                applied += 1
        if applied:
            ordered = sorted(intent_map.values(),
                             key=lambda r: r.get('id', ''))
            _write_csv(os.path.join(ref_dir, 'scene-intent.csv'),
                       ordered, _FILE_MAP['scene-intent.csv'])
        return applied

    elif domain == 'knowledge':
        briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
        applied = 0
        for scene_id, new_val in updates:
            if scene_id in briefs_map:
                parts = new_val.split('|')
                if len(parts) >= 2:
                    briefs_map[scene_id]['knowledge_in'] = parts[0].strip()
                    briefs_map[scene_id]['knowledge_out'] = parts[1].strip()
                    applied += 1
        if applied:
            ordered = sorted(briefs_map.values(),
                             key=lambda r: r.get('id', ''))
            _write_csv(os.path.join(ref_dir, 'scene-briefs.csv'),
                       ordered, _FILE_MAP['scene-briefs.csv'])
        return applied

    return 0


def reconcile_domain(domain: str, ref_dir: str, model: str,
                     log_dir: str, context: str = '') -> dict:
    """Full reconciliation for one domain: prompt → API → parse → write → normalize.

    Args:
        domain: The reconciliation domain.
        ref_dir: Path to reference/ directory.
        model: Model ID for Opus.
        log_dir: Directory for API log files.
        context: Optional extra context for the prompt.

    Returns:
        Dict with keys: registry_entries, updates_applied, fields_normalized.
    """
    from storyforge.api import invoke_to_file, extract_text_from_file

    # Outcomes are deterministic — no API call
    if domain == 'outcomes':
        changed = reconcile_outcomes(ref_dir)
        return {
            'registry_entries': 0,
            'updates_applied': 0,
            'fields_normalized': changed,
        }

    prompt = build_registry_prompt(domain, ref_dir, context=context)

    log_file = os.path.join(log_dir, f'reconcile-{domain}.json')
    invoke_to_file(prompt, model, log_file, max_tokens=8192)
    response = extract_text_from_file(log_file)

    registry_rows, updates = parse_registry_response(response, domain)

    # Write registry
    write_registry(ref_dir, domain, registry_rows)

    # Apply direct updates (MICE thread rewrites, knowledge chain fixes)
    updates_applied = apply_updates(ref_dir, domain, updates)

    # Normalize all fields against the new registry
    fields_normalized = apply_registry_normalization(domain, ref_dir)

    return {
        'registry_entries': len(registry_rows),
        'updates_applied': updates_applied,
        'fields_normalized': fields_normalized,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-reconcile.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/reconcile.py tests/test-reconcile.sh
git commit -m "Add reconcile_domain with registry normalization and update application"
git push
```

---

### Task 5: Shell Script `storyforge-reconcile`

**Files:**
- Create: `scripts/storyforge-reconcile`

- [ ] **Step 1: Write the script**

Create `scripts/storyforge-reconcile`:
```bash
#!/bin/bash
# storyforge-reconcile — Build registries and normalize CSV fields
#
# Usage:
#   ./storyforge reconcile                      # All domains
#   ./storyforge reconcile --domain characters   # One domain
#   ./storyforge reconcile --phase 1             # Phase 1 domains
#   ./storyforge reconcile --dry-run             # Show prompts only
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/lib"
PYTHON_LIB="${SCRIPT_DIR}/lib/python"

source "${LIB_DIR}/common.sh"
detect_project_root

LOG_DIR="${PROJECT_DIR}/working/logs"
mkdir -p "$LOG_DIR"

# ============================================================================
# Arguments
# ============================================================================

DOMAIN=""
PHASE=""
DRY_RUN=false

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  --domain NAME     Run one domain (characters, locations, values, mice-threads, knowledge, outcomes)
  --phase N         Run domains for extraction phase (1=characters+locations, 2=values+mice-threads, 3=knowledge+outcomes)
  --dry-run         Print prompts without calling API
  -h, --help        Show this help
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)   DOMAIN="${2:?ERROR: --domain requires a value}"; shift 2 ;;
        --phase)    PHASE="${2:?ERROR: --phase requires a value}"; shift 2 ;;
        --dry-run)  DRY_RUN=true; shift ;;
        -h|--help)  usage ;;
        -*)         echo "ERROR: Unknown option: $1" >&2; usage ;;
        *)          shift ;;
    esac
done

if [[ "$DRY_RUN" != true && -z "${ANTHROPIC_API_KEY:-}" ]]; then
    log "ERROR: ANTHROPIC_API_KEY not set. Required for reconciliation."
    exit 1
fi

# ============================================================================
# Build domain list
# ============================================================================

PHASE1_DOMAINS=(characters locations)
PHASE2_DOMAINS=(values mice-threads)
PHASE3_DOMAINS=(knowledge outcomes)

DOMAINS=()
if [[ -n "$DOMAIN" ]]; then
    DOMAINS=("$DOMAIN")
elif [[ -n "$PHASE" ]]; then
    case "$PHASE" in
        1) DOMAINS=("${PHASE1_DOMAINS[@]}") ;;
        2) DOMAINS=("${PHASE2_DOMAINS[@]}") ;;
        3) DOMAINS=("${PHASE3_DOMAINS[@]}") ;;
        *) log "ERROR: --phase must be 1, 2, or 3"; exit 1 ;;
    esac
else
    DOMAINS=(characters locations values mice-threads knowledge outcomes)
fi

# ============================================================================
# Project info
# ============================================================================

PROJECT_TITLE=$(read_yaml_field "project.title" 2>/dev/null || echo "Untitled")
REF_DIR="${PROJECT_DIR}/reference"
MODEL=$(select_model "synthesis")  # Opus for registry builds

log "============================================"
log "Storyforge Reconcile"
log "Project: ${PROJECT_TITLE}"
log "Domains: ${DOMAINS[*]}"
log "Model: ${MODEL}"
log "============================================"

# ============================================================================
# Context: character bible if available
# ============================================================================

CHAR_CONTEXT=""
CHAR_BIBLE="${PROJECT_DIR}/reference/character-bible.md"
if [[ -f "$CHAR_BIBLE" ]]; then
    CHAR_CONTEXT=$(cat "$CHAR_BIBLE")
fi

# ============================================================================
# Reconcile each domain
# ============================================================================

for CURRENT_DOMAIN in "${DOMAINS[@]}"; do
    log ""
    log "--- Reconciling: ${CURRENT_DOMAIN} ---"

    if [[ "$DRY_RUN" == true ]]; then
        # Print prompt only
        if [[ "$CURRENT_DOMAIN" == "outcomes" ]]; then
            log "  (deterministic — no API call needed)"
        else
            CONTEXT_ARG=""
            [[ "$CURRENT_DOMAIN" == "characters" && -n "$CHAR_CONTEXT" ]] && CONTEXT_ARG="has_context"

            PYTHONPATH="$PYTHON_LIB" python3 -c "
import sys; sys.path.insert(0, '${PYTHON_LIB}')
from storyforge.reconcile import build_registry_prompt
context = open('${CHAR_BIBLE}').read() if '${CONTEXT_ARG}' == 'has_context' else ''
prompt = build_registry_prompt('${CURRENT_DOMAIN}', '${REF_DIR}', context=context)
print(f'===== Prompt for ${CURRENT_DOMAIN} ({len(prompt)} chars) =====')
print(prompt[:500])
print('...')
"
        fi
        continue
    fi

    # Build context arg for characters
    CONTEXT=""
    [[ "$CURRENT_DOMAIN" == "characters" && -n "$CHAR_CONTEXT" ]] && CONTEXT="$CHAR_CONTEXT"

    RESULT=$(PYTHONPATH="$PYTHON_LIB" python3 -c "
import sys, json, os; sys.path.insert(0, '${PYTHON_LIB}')
from storyforge.reconcile import reconcile_domain

result = reconcile_domain(
    '${CURRENT_DOMAIN}',
    '${REF_DIR}',
    '${MODEL}',
    '${LOG_DIR}',
    context=open('${CHAR_BIBLE}').read() if '${CURRENT_DOMAIN}' == 'characters' and os.path.isfile('${CHAR_BIBLE}') else '',
)
print(json.dumps(result))
")

    ENTRIES=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('registry_entries', 0))")
    UPDATES=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('updates_applied', 0))")
    NORMALIZED=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('fields_normalized', 0))")

    log "  Registry: ${ENTRIES} entries"
    log "  Updates: ${UPDATES} applied"
    log "  Normalized: ${NORMALIZED} field values"

    # Commit this domain's changes
    (cd "$PROJECT_DIR" && git add reference/ working/logs/ && \
        git commit -m "Reconcile: ${CURRENT_DOMAIN} — ${ENTRIES} entries, ${NORMALIZED} normalizations" && \
        git push) 2>/dev/null || true
done

log ""
log "============================================"
log "Reconciliation complete"
log "============================================"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/storyforge-reconcile
```

- [ ] **Step 3: Commit**

```bash
git add scripts/storyforge-reconcile
git commit -m "Add storyforge-reconcile shell script"
git push
```

---

### Task 6: Hook into storyforge-extract

**Files:**
- Modify: `scripts/storyforge-extract`

- [ ] **Step 1: Add reconcile hooks after each phase**

In `scripts/storyforge-extract`, after Phase 1's commit (line ~370, after `update_pr_task "Phase 1"...`), add:
```bash
        # Reconcile characters and locations against Phase 1 data
        log ""
        log "--- Reconciling Phase 1 registries ---"
        "${SCRIPT_DIR}/storyforge-reconcile" --phase 1
```

After Phase 2's commit (line ~459, after `update_pr_task "Phase 2"...`), add:
```bash
        # Reconcile values and MICE threads against Phase 2 data
        log ""
        log "--- Reconciling Phase 2 registries ---"
        "${SCRIPT_DIR}/storyforge-reconcile" --phase 2
```

After Phase 3b's commit (line ~671, after `update_pr_task "Phase 3"...`), add:
```bash
        # Reconcile knowledge and outcomes against Phase 3 data
        log ""
        log "--- Reconciling Phase 3 registries ---"
        "${SCRIPT_DIR}/storyforge-reconcile" --phase 3
```

- [ ] **Step 2: Verify dry-run doesn't trigger reconcile**

The reconcile calls are inside the `else` block (not dry-run), so they only run during actual extraction. Verify by checking the script structure.

- [ ] **Step 3: Commit**

```bash
git add scripts/storyforge-extract
git commit -m "Hook reconciliation into extract pipeline after each phase"
git push
```

---

### Task 7: Version Bump and CLAUDE.md Update

**Files:**
- Modify: `.claude-plugin/plugin.json`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Bump version to 0.57.0**

In `.claude-plugin/plugin.json`, change version to `"0.57.0"` (new feature).

- [ ] **Step 2: Add reconcile to CLAUDE.md script table**

In the Scripts table in `CLAUDE.md`, add:
```
| `storyforge-reconcile` | Build registries (Opus) and normalize CSV fields for cross-scene consistency |
```

- [ ] **Step 3: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All tests pass (existing + new reconcile tests)

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/plugin.json CLAUDE.md
git commit -m "Bump version to 0.57.0 — add reconciliation pass"
git push
```
