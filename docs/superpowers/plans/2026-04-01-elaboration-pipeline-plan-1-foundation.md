# Elaboration Pipeline — Plan 1: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the three-file scene CSV data model, Python helpers, structural validation engine, and updated project templates that the rest of the elaboration pipeline depends on.

**Architecture:** New Python module `scripts/lib/python/storyforge/elaborate.py` provides the scene data helpers and validation engine. A new bash script `scripts/storyforge-validate` wraps the Python validation for CLI use. Test fixtures and bash tests verify the data model and validation. Templates are updated so new projects initialize with the three-file structure.

**Tech Stack:** Python 3 (no external deps), bash, pipe-delimited CSV

**Spec:** `docs/superpowers/specs/2026-04-01-elaboration-pipeline-design.md`

---

## File Structure

### New files
- `scripts/lib/python/storyforge/elaborate.py` — scene data helpers (get/set/query) + structural validation engine
- `scripts/storyforge-validate` — bash CLI wrapper for validation
- `tests/test-elaborate.sh` — bash tests for the Python helpers and validation
- `tests/fixtures/test-project/reference/scenes.csv` — test fixture (new format)
- `tests/fixtures/test-project/reference/scene-intent.csv` — test fixture (updated columns)
- `tests/fixtures/test-project/reference/scene-briefs.csv` — test fixture (new file)
- `templates/reference/scenes.csv` — template for init
- `templates/reference/scene-intent.csv` — template for init (updated columns)
- `templates/reference/scene-briefs.csv` — template for init (new file)

### Modified files
- `templates/storyforge.yaml` — add elaboration phase values to phase field
- `tests/fixtures/test-project/reference/scene-metadata.csv` — keep for backward compat with existing tests

---

## Task 1: Create test fixtures for the three-file CSV model

**Files:**
- Create: `tests/fixtures/test-project/reference/scenes.csv`
- Create: `tests/fixtures/test-project/reference/scene-briefs.csv`
- Modify: `tests/fixtures/test-project/reference/scene-intent.csv`

These fixtures are the foundation for all subsequent tests. They represent a small project (6 scenes) at various elaboration depths.

- [ ] **Step 1: Create scenes.csv fixture**

```
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|status|word_count|target_words
act1-sc01|1|The Finest Cartographer|1|Dorren Hayle|Pressure Cartography Office|1|morning|2 hours|briefed|0|2500
act1-sc02|2|The Missing Village|1|Dorren Hayle|Dorren's private study|1|evening|1 hour|briefed|0|3000
new-x1|3|The Archivist's Warning|1|Kael Maren|The Deep Archive|2|afternoon|30 minutes|mapped|0|1500
act2-sc01|4|Into the Blank|2|Tessa Merrin|The Uncharted Reaches|3|morning|4 hours|architecture|0|2800
act2-sc02|5|First Collapse|2|Tessa Merrin|Eastern Ridge|3|afternoon|1 hour|spine|0|2000
act2-sc03|6|The Warning Ignored|2|Dorren Hayle|Council Chamber|4|evening|2 hours|briefed|0|2200
```

Write to `tests/fixtures/test-project/reference/scenes.csv`.

- [ ] **Step 2: Update scene-intent.csv fixture with new columns**

```
id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
act1-sc01|Establishes Dorren as institutional gatekeeper who notices anomalies but chooses protocol over investigation|action|Controlled competence to buried unease|truth|+/-|revelation|institutional-failure;chosen-blindness|Dorren Hayle;Tessa Merrin;Pell|Dorren Hayle;Tessa Merrin|+inquiry:map-anomaly
act1-sc02|Dorren discovers a village has vanished from the pressure maps|sequel|Routine giving way to dread|safety|-/--|revelation|the-anomaly;maps-and-territory|Dorren Hayle|Dorren Hayle|
new-x1|Kael warns about archive inconsistencies pointing to systematic erasure|action|Scholarly calm to urgent alarm|truth|-/+|action|the-anomaly;archive-corruption|Kael Maren;Dorren Hayle|Kael Maren;Dorren Hayle|+inquiry:archive-erasure
act2-sc01|First exploration of the eastern damage reveals the subsidence is not natural|action|Professional detachment to visceral shock|safety|+/--|action|infrastructure-failure;the-subsidence|Tessa Merrin;Pell|Tessa Merrin;Pell|+milieu:uncharted-reaches
act2-sc02|The ground gives way — Tessa barely escapes as the ridge collapses|action|Determination to terror|life|-/+|action|the-subsidence|Tessa Merrin|Tessa Merrin|-milieu:uncharted-reaches
act2-sc03|Dorren presents evidence to the council; they dismiss it as procedural noise|sequel|Resolve to bitter resignation|justice|+/-|revelation|institutional-failure;chosen-blindness|Dorren Hayle;Council Members;Kael Maren|Dorren Hayle;Council Members|-inquiry:map-anomaly
```

Write to `tests/fixtures/test-project/reference/scene-intent.csv`.

- [ ] **Step 3: Create scene-briefs.csv fixture**

```
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
act1-sc01|Complete the quarterly pressure audit on schedule|Anomalous readings in eastern sector don't match any known pattern|no-and|Report the anomaly and risk protocol review, or file it as instrument error and stay on schedule|Files as instrument error but keeps a private note|Standard pressure maps are reliable; eastern sector is stable|Eastern readings don't match; has private note of anomaly|Reviews maps;Finds anomaly;Consults Tessa;Files as error;Makes private note|"The eastern readings are within acceptable variance";Dorren privately: "Acceptable is not the same as explained"|competence;unease;self-doubt;resolve|maps/cartography;acceptable-variance||false
act1-sc02|Understand the anomaly by cross-referencing historical archives|The village that should appear on the 40-year map is simply absent — no record of removal|no-and|Accept the archive is incomplete and move on, or pursue an explanation that has no institutional support|Decides to pursue quietly, outside protocol|Eastern anomaly exists; private note|A village has been erased from the maps; the erasure is systematic|Cross-references maps;Discovers missing village;Searches removal logs;Finds nothing|"It was there forty years ago. It isn't there now. There is no note."|routine;confusion;dread;determination|depth/descent;maps/cartography|act1-sc01|false
new-x1|||||||||||||||
act2-sc03|Convince the council that the eastern anomalies require investigation|Council members see the anomaly as Dorren's procedural fixation, not evidence of erasure|no|Accept the council's dismissal and work within channels, or go outside the institution entirely|Goes outside — shares findings with Kael privately after the meeting|Village erasure is systematic; archive shows inconsistencies|Council will not act; must work outside institution|Presents evidence;Council dismisses;Dorren argues;Is overruled;Meets Kael after|Council: "We appreciate your diligence, Cartographer.";Dorren to Kael: "They won't look."|resolve;frustration;bitter-resignation;quiet-defiance|governance-as-weight;blindness/seeing|act1-sc02;new-x1|false
```

Write to `tests/fixtures/test-project/reference/scene-briefs.csv`. Note: `new-x1` has empty brief columns (status `mapped`, not yet briefed). `act2-sc01` and `act2-sc02` have no brief rows (status `architecture` and `spine`).

- [ ] **Step 4: Commit fixtures**

```bash
git add tests/fixtures/test-project/reference/scenes.csv tests/fixtures/test-project/reference/scene-intent.csv tests/fixtures/test-project/reference/scene-briefs.csv
git commit -m "Add test fixtures for three-file scene CSV model"
```

---

## Task 2: Build scene data helpers — `elaborate.py` core read functions

**Files:**
- Create: `scripts/lib/python/storyforge/elaborate.py`
- Create: `tests/test-elaborate.sh`

- [ ] **Step 1: Write failing tests for `get_scene` and `get_scenes`**

Add to `tests/test-elaborate.sh`:

```bash
#!/bin/bash
# test-elaborate.sh — Tests for elaboration pipeline helpers

SCENES_CSV="${FIXTURE_DIR}/reference/scenes.csv"
INTENT_CSV="${FIXTURE_DIR}/reference/scene-intent.csv"
BRIEFS_CSV="${FIXTURE_DIR}/reference/scene-briefs.csv"

ELABORATE_PY="${PLUGIN_DIR}/scripts/lib/python/storyforge/elaborate.py"

# Helper to invoke elaborate.py functions
elab() {
    python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import $1
" 2>&1
}

# ============================================================================
# get_scene
# ============================================================================

RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import get_scene
import json
scene = get_scene('act1-sc01', '${FIXTURE_DIR}/reference')
print(json.dumps(scene))
")

assert_contains "$RESULT" '"id": "act1-sc01"' "get_scene: returns id"
assert_contains "$RESULT" '"pov": "Dorren Hayle"' "get_scene: returns pov from scenes.csv"
assert_contains "$RESULT" '"function":' "get_scene: returns function from intent.csv"
assert_contains "$RESULT" '"goal":' "get_scene: returns goal from briefs.csv"
assert_contains "$RESULT" '"value_shift": "+/-"' "get_scene: returns value_shift from intent.csv"

# Scene with no brief row
RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import get_scene
import json
scene = get_scene('act2-sc01', '${FIXTURE_DIR}/reference')
print(json.dumps(scene))
")

assert_contains "$RESULT" '"pov": "Tessa Merrin"' "get_scene: no-brief scene has structural data"
assert_contains "$RESULT" '"goal": ""' "get_scene: no-brief scene has empty brief fields"

# Nonexistent scene
RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import get_scene
scene = get_scene('nonexistent', '${FIXTURE_DIR}/reference')
print(scene)
" 2>&1)

assert_contains "$RESULT" "None" "get_scene: nonexistent scene returns None"

# ============================================================================
# get_scenes with column selection
# ============================================================================

RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import get_scenes
import json
scenes = get_scenes('${FIXTURE_DIR}/reference', columns=['id', 'pov', 'value_shift'])
print(json.dumps(scenes))
")

assert_contains "$RESULT" '"id": "act1-sc01"' "get_scenes: returns first scene"
assert_contains "$RESULT" '"value_shift": "+/-"' "get_scenes: includes cross-file column"
assert_not_contains "$RESULT" '"goal"' "get_scenes: excludes unrequested columns"

# get_scenes with filter
RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import get_scenes
import json
scenes = get_scenes('${FIXTURE_DIR}/reference', filters={'pov': 'Dorren Hayle'})
print(len(scenes))
")

assert_equals "3" "$RESULT" "get_scenes: filter by pov returns correct count"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./tests/run-tests.sh tests/test-elaborate.sh
```

Expected: FAIL — `elaborate.py` doesn't exist yet or doesn't have the functions.

- [ ] **Step 3: Write `elaborate.py` with core read functions**

Create `scripts/lib/python/storyforge/elaborate.py`:

```python
"""Elaboration pipeline helpers — scene data access and structural validation.

Provides a unified interface over the three-file scene CSV model:
  - reference/scenes.csv       (structural identity and position)
  - reference/scene-intent.csv (purpose, dynamics, tracking)
  - reference/scene-briefs.csv (drafting contract)

All files are pipe-delimited with 'id' as the join key.
"""

import csv
import os
from typing import Any


DELIMITER = '|'

# Column-to-file mapping (which file owns which columns)
_SCENES_COLS = [
    'id', 'seq', 'title', 'part', 'pov', 'location',
    'timeline_day', 'time_of_day', 'duration', 'status',
    'word_count', 'target_words',
]
_INTENT_COLS = [
    'id', 'function', 'scene_type', 'emotional_arc', 'value_at_stake',
    'value_shift', 'turning_point', 'threads', 'characters', 'on_stage',
    'mice_threads',
]
_BRIEFS_COLS = [
    'id', 'goal', 'conflict', 'outcome', 'crisis', 'decision',
    'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
    'emotions', 'motifs', 'continuity_deps', 'has_overflow',
]

_FILE_MAP = {
    'scenes.csv': _SCENES_COLS,
    'scene-intent.csv': _INTENT_COLS,
    'scene-briefs.csv': _BRIEFS_COLS,
}


# ============================================================================
# CSV I/O
# ============================================================================

def _read_csv(path: str) -> list[dict[str, str]]:
    """Read a pipe-delimited CSV into a list of dicts."""
    if not os.path.exists(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=DELIMITER)
        return list(reader)


def _read_csv_as_map(path: str) -> dict[str, dict[str, str]]:
    """Read a pipe-delimited CSV into a dict keyed by 'id'."""
    rows = _read_csv(path)
    return {row['id']: row for row in rows if 'id' in row}


def _write_csv(path: str, rows: list[dict[str, str]], columns: list[str]) -> None:
    """Write rows to a pipe-delimited CSV with the given column order."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f, fieldnames=columns, delimiter=DELIMITER,
            extrasaction='ignore',
        )
        writer.writeheader()
        writer.writerows(rows)


def _file_for_column(col: str) -> str | None:
    """Return the CSV filename that owns the given column."""
    for filename, cols in _FILE_MAP.items():
        if col in cols:
            return filename
    return None


# ============================================================================
# Read helpers
# ============================================================================

def get_scene(scene_id: str, ref_dir: str) -> dict[str, str] | None:
    """Return all columns for a scene, merged across all three files.

    Args:
        scene_id: The scene's id value.
        ref_dir: Path to the reference/ directory containing the CSV files.

    Returns:
        A dict with all columns, or None if the scene doesn't exist in scenes.csv.
    """
    scenes = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    if scene_id not in scenes:
        return None

    row = dict(scenes[scene_id])

    # Merge intent columns
    intents = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    if scene_id in intents:
        for k, v in intents[scene_id].items():
            if k != 'id':
                row[k] = v
    else:
        # Fill missing intent columns with empty strings
        for col in _INTENT_COLS:
            if col != 'id':
                row.setdefault(col, '')

    # Merge brief columns
    briefs = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    if scene_id in briefs:
        for k, v in briefs[scene_id].items():
            if k != 'id':
                row[k] = v
    else:
        for col in _BRIEFS_COLS:
            if col != 'id':
                row.setdefault(col, '')

    return row


def get_scenes(
    ref_dir: str,
    columns: list[str] | None = None,
    filters: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Query scenes with optional column selection and filtering.

    Args:
        ref_dir: Path to the reference/ directory.
        columns: If provided, only include these columns in each result dict.
        filters: If provided, only include scenes where each key==value matches.

    Returns:
        A list of dicts, one per matching scene, sorted by seq.
    """
    # Read all scenes to get the ID list and seq ordering
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    results = []
    # Sort by seq
    sorted_ids = sorted(scenes_map.keys(), key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    for sid in sorted_ids:
        row = dict(scenes_map[sid])
        if sid in intent_map:
            for k, v in intent_map[sid].items():
                if k != 'id':
                    row[k] = v
        else:
            for col in _INTENT_COLS:
                if col != 'id':
                    row.setdefault(col, '')
        if sid in briefs_map:
            for k, v in briefs_map[sid].items():
                if k != 'id':
                    row[k] = v
        else:
            for col in _BRIEFS_COLS:
                if col != 'id':
                    row.setdefault(col, '')

        # Apply filters
        if filters:
            if not all(row.get(k) == v for k, v in filters.items()):
                continue

        # Apply column selection
        if columns:
            row = {k: row[k] for k in columns if k in row}

        results.append(row)

    return results


def get_column(ref_dir: str, column: str) -> list[str]:
    """Return one column's values across all scenes, sorted by seq.

    Args:
        ref_dir: Path to the reference/ directory.
        column: The column name to extract.

    Returns:
        A list of string values, one per scene, in seq order.
    """
    scenes = get_scenes(ref_dir, columns=['id', column])
    return [s.get(column, '') for s in scenes]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./tests/run-tests.sh tests/test-elaborate.sh
```

Expected: All assertions PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/elaborate.py tests/test-elaborate.sh
git commit -m "Add scene data helpers: get_scene, get_scenes, get_column"
```

---

## Task 3: Build scene data helpers — write functions

**Files:**
- Modify: `scripts/lib/python/storyforge/elaborate.py`
- Modify: `tests/test-elaborate.sh`

- [ ] **Step 1: Write failing tests for `update_scene` and `add_scenes`**

Append to `tests/test-elaborate.sh`:

```bash
# ============================================================================
# update_scene
# ============================================================================

# Work on a copy to avoid mutating fixtures
TMP_REF=$(mktemp -d)
cp "${FIXTURE_DIR}/reference/scenes.csv" "${TMP_REF}/scenes.csv"
cp "${FIXTURE_DIR}/reference/scene-intent.csv" "${TMP_REF}/scene-intent.csv"
cp "${FIXTURE_DIR}/reference/scene-briefs.csv" "${TMP_REF}/scene-briefs.csv"

python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import update_scene
update_scene('act1-sc01', '${TMP_REF}', {'status': 'drafted', 'word_count': '2450'})
"

RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import get_scene
import json
scene = get_scene('act1-sc01', '${TMP_REF}')
print(scene['status'], scene['word_count'])
")

assert_equals "drafted 2450" "$RESULT" "update_scene: updates scenes.csv columns"

# Update a brief column
python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import update_scene
update_scene('act1-sc01', '${TMP_REF}', {'goal': 'Survive the audit'})
"

RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import get_scene
scene = get_scene('act1-sc01', '${TMP_REF}')
print(scene['goal'])
")

assert_equals "Survive the audit" "$RESULT" "update_scene: updates briefs.csv columns"

# Update an intent column
python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import update_scene
update_scene('act1-sc01', '${TMP_REF}', {'value_shift': '-/+'})
"

RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import get_scene
scene = get_scene('act1-sc01', '${TMP_REF}')
print(scene['value_shift'])
")

assert_equals "-/+" "$RESULT" "update_scene: updates intent.csv columns"

# ============================================================================
# add_scenes
# ============================================================================

python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import add_scenes
add_scenes('${TMP_REF}', [
    {'id': 'new-scene', 'seq': '7', 'title': 'The New Scene', 'status': 'spine', 'function': 'Test scene'},
])
"

RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import get_scene
import json
scene = get_scene('new-scene', '${TMP_REF}')
print(scene['title'], scene['function'], scene['status'])
")

assert_equals "The New Scene Test scene spine" "$RESULT" "add_scenes: creates rows across all files"

rm -rf "$TMP_REF"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./tests/run-tests.sh tests/test-elaborate.sh
```

Expected: FAIL — `update_scene` and `add_scenes` not yet defined.

- [ ] **Step 3: Implement write functions in `elaborate.py`**

Append to `scripts/lib/python/storyforge/elaborate.py`:

```python
# ============================================================================
# Write helpers
# ============================================================================

def update_scene(scene_id: str, ref_dir: str, updates: dict[str, str]) -> None:
    """Update specific columns for a scene, writing to the correct file(s).

    Args:
        scene_id: The scene's id value.
        ref_dir: Path to the reference/ directory.
        updates: Dict of column_name -> new_value.
    """
    # Group updates by file
    file_updates: dict[str, dict[str, str]] = {}
    for col, val in updates.items():
        filename = _file_for_column(col)
        if filename is None:
            continue
        file_updates.setdefault(filename, {})[col] = val

    for filename, cols_to_update in file_updates.items():
        path = os.path.join(ref_dir, filename)
        rows = _read_csv(path)
        col_order = _FILE_MAP[filename]

        found = False
        for row in rows:
            if row.get('id') == scene_id:
                row.update(cols_to_update)
                found = True
                break

        if not found:
            # Create a new row with just the id and updated columns
            new_row = {c: '' for c in col_order}
            new_row['id'] = scene_id
            new_row.update(cols_to_update)
            rows.append(new_row)

        _write_csv(path, rows, col_order)


def add_scenes(ref_dir: str, scenes: list[dict[str, str]]) -> None:
    """Add new scene rows across all three files.

    Each scene dict can contain columns from any file. Columns are routed
    to the appropriate file. Missing columns are filled with empty strings.

    Args:
        ref_dir: Path to the reference/ directory.
        scenes: List of dicts, each with at minimum 'id' and 'seq'.
    """
    for filename, col_order in _FILE_MAP.items():
        path = os.path.join(ref_dir, filename)
        existing = _read_csv(path)

        for scene in scenes:
            new_row = {c: '' for c in col_order}
            new_row['id'] = scene['id']
            for col in col_order:
                if col in scene:
                    new_row[col] = scene[col]
            existing.append(new_row)

        _write_csv(path, existing, col_order)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./tests/run-tests.sh tests/test-elaborate.sh
```

Expected: All assertions PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/elaborate.py tests/test-elaborate.sh
git commit -m "Add scene write helpers: update_scene, add_scenes"
```

---

## Task 4: Build structural validation — identity and completeness checks

**Files:**
- Modify: `scripts/lib/python/storyforge/elaborate.py`
- Modify: `tests/test-elaborate.sh`

- [ ] **Step 1: Write failing tests for identity and completeness validation**

Append to `tests/test-elaborate.sh`:

```bash
# ============================================================================
# validate_structure — identity and completeness
# ============================================================================

RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import validate_structure
import json
report = validate_structure('${FIXTURE_DIR}/reference')
print(json.dumps(report))
")

assert_contains "$RESULT" '"passed":' "validate_structure: returns report with passed field"
assert_contains "$RESULT" '"failures":' "validate_structure: returns report with failures field"

# Fixtures should pass identity checks (all intent/brief IDs exist in scenes)
PASSED=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import validate_structure
report = validate_structure('${FIXTURE_DIR}/reference')
identity = [c for c in report['checks'] if c['category'] == 'identity']
print(all(c['passed'] for c in identity))
")

assert_equals "True" "$PASSED" "validate_structure: fixtures pass identity checks"

# Completeness: mapped scene (new-x1) should have location populated
# But it does in our fixture, so check that spine-status scene (act2-sc02)
# doesn't need location
RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import validate_structure
report = validate_structure('${FIXTURE_DIR}/reference')
completeness = [c for c in report['checks'] if c['category'] == 'completeness']
print(all(c['passed'] for c in completeness))
")

assert_equals "True" "$RESULT" "validate_structure: fixtures pass completeness checks"

# Test with orphaned intent row
TMP_REF=$(mktemp -d)
cp "${FIXTURE_DIR}/reference/scenes.csv" "${TMP_REF}/scenes.csv"
cp "${FIXTURE_DIR}/reference/scene-intent.csv" "${TMP_REF}/scene-intent.csv"
cp "${FIXTURE_DIR}/reference/scene-briefs.csv" "${TMP_REF}/scene-briefs.csv"

# Add an intent row with no matching scenes row
echo "orphan-scene|Orphan function|action|calm to panic|truth|+/-|action|thread-a|Char A|Char A|" >> "${TMP_REF}/scene-intent.csv"

RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import validate_structure
import json
report = validate_structure('${TMP_REF}')
identity = [c for c in report['checks'] if c['category'] == 'identity']
orphan_check = [c for c in identity if 'orphan' in c.get('check', '').lower() or 'orphan' in c.get('message', '').lower()]
print(len(orphan_check) > 0 and not orphan_check[0]['passed'])
")

assert_equals "True" "$RESULT" "validate_structure: detects orphaned intent row"

rm -rf "$TMP_REF"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./tests/run-tests.sh tests/test-elaborate.sh
```

Expected: FAIL — `validate_structure` not defined.

- [ ] **Step 3: Implement `validate_structure`**

Append to `scripts/lib/python/storyforge/elaborate.py`:

```python
# ============================================================================
# Structural validation
# ============================================================================

# Required columns per status level
_REQUIRED_BY_STATUS = {
    'spine': ['id', 'seq', 'title', 'function'],
    'architecture': ['id', 'seq', 'title', 'part', 'pov', 'function',
                      'scene_type', 'emotional_arc', 'value_at_stake',
                      'value_shift', 'turning_point', 'threads'],
    'mapped': ['id', 'seq', 'title', 'part', 'pov', 'location',
               'timeline_day', 'time_of_day', 'function', 'scene_type',
               'emotional_arc', 'value_at_stake', 'value_shift',
               'turning_point', 'threads', 'characters', 'on_stage'],
    'briefed': ['id', 'seq', 'title', 'part', 'pov', 'location',
                'timeline_day', 'time_of_day', 'function', 'scene_type',
                'emotional_arc', 'value_at_stake', 'value_shift',
                'turning_point', 'threads', 'characters', 'on_stage',
                'goal', 'conflict', 'outcome'],
    'drafted': ['id', 'seq', 'title', 'part', 'pov', 'location',
                'timeline_day', 'time_of_day', 'function', 'scene_type',
                'emotional_arc', 'value_at_stake', 'value_shift',
                'turning_point', 'threads', 'characters', 'on_stage',
                'goal', 'conflict', 'outcome'],
    'polished': ['id', 'seq', 'title', 'part', 'pov', 'location',
                 'timeline_day', 'time_of_day', 'function', 'scene_type',
                 'emotional_arc', 'value_at_stake', 'value_shift',
                 'turning_point', 'threads', 'characters', 'on_stage',
                 'goal', 'conflict', 'outcome'],
}

# Status ordering for comparison
_STATUS_ORDER = ['spine', 'architecture', 'mapped', 'briefed', 'drafted', 'polished']


def _check(category: str, check: str, passed: bool, message: str,
           severity: str = 'blocking', scene_id: str = '') -> dict:
    """Build a single check result."""
    result = {
        'category': category,
        'check': check,
        'passed': passed,
        'message': message,
        'severity': severity,
    }
    if scene_id:
        result['scene_id'] = scene_id
    return result


def validate_structure(ref_dir: str) -> dict:
    """Run all structural validation checks against the scene CSVs.

    Returns:
        A dict with 'passed' (bool), 'checks' (list of check results),
        and 'failures' (list of failed checks only).
    """
    checks: list[dict] = []

    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    scene_ids = set(scenes_map.keys())
    intent_ids = set(intent_map.keys())
    briefs_ids = set(briefs_map.keys())

    # --- Identity: no orphaned rows ---
    orphaned_intent = intent_ids - scene_ids
    checks.append(_check(
        'identity', 'orphaned-intent-rows',
        len(orphaned_intent) == 0,
        f"Intent rows with no matching scene: {sorted(orphaned_intent)}" if orphaned_intent
        else "All intent rows have matching scenes",
    ))

    orphaned_briefs = briefs_ids - scene_ids
    checks.append(_check(
        'identity', 'orphaned-brief-rows',
        len(orphaned_briefs) == 0,
        f"Brief rows with no matching scene: {sorted(orphaned_briefs)}" if orphaned_briefs
        else "All brief rows have matching scenes",
    ))

    # --- Completeness: required columns for status ---
    for sid, scene in scenes_map.items():
        status = scene.get('status', 'spine')
        if status not in _REQUIRED_BY_STATUS:
            continue

        required = _REQUIRED_BY_STATUS[status]
        # Merge all data for this scene
        merged = dict(scene)
        if sid in intent_map:
            merged.update({k: v for k, v in intent_map[sid].items() if k != 'id'})
        if sid in briefs_map:
            merged.update({k: v for k, v in briefs_map[sid].items() if k != 'id'})

        missing = [col for col in required if not merged.get(col, '').strip()]
        checks.append(_check(
            'completeness', f'required-columns-{sid}',
            len(missing) == 0,
            f"Scene {sid} (status={status}) missing required columns: {missing}" if missing
            else f"Scene {sid} has all required columns for status={status}",
            scene_id=sid,
        ))

    failures = [c for c in checks if not c['passed']]
    return {
        'passed': len(failures) == 0,
        'checks': checks,
        'failures': failures,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./tests/run-tests.sh tests/test-elaborate.sh
```

Expected: All assertions PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/elaborate.py tests/test-elaborate.sh
git commit -m "Add structural validation: identity and completeness checks"
```

---

## Task 5: Build structural validation — thread, timeline, and knowledge checks

**Files:**
- Modify: `scripts/lib/python/storyforge/elaborate.py`
- Modify: `tests/test-elaborate.sh`

- [ ] **Step 1: Write failing tests for thread and knowledge validation**

Append to `tests/test-elaborate.sh`:

```bash
# ============================================================================
# validate_structure — thread management
# ============================================================================

# Fixtures have MICE threads that open and close properly
RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import validate_structure
report = validate_structure('${FIXTURE_DIR}/reference')
thread_checks = [c for c in report['checks'] if c['category'] == 'threads']
# Print check names and pass status
for c in thread_checks:
    print(c['check'], c['passed'])
")

assert_contains "$RESULT" "mice-nesting True" "validate_structure: MICE threads nest correctly"

# ============================================================================
# validate_structure — knowledge flow
# ============================================================================

# act1-sc02 depends on act1-sc01 (continuity_deps). The knowledge_in of
# act1-sc02 should be a subset of knowledge available from prior scenes.
RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import validate_structure
report = validate_structure('${FIXTURE_DIR}/reference')
knowledge_checks = [c for c in report['checks'] if c['category'] == 'knowledge']
for c in knowledge_checks:
    print(c['check'], c['passed'])
")

assert_contains "$RESULT" "True" "validate_structure: knowledge flow checks pass on fixtures"

# ============================================================================
# validate_structure — timeline consistency
# ============================================================================

RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import validate_structure
report = validate_structure('${FIXTURE_DIR}/reference')
timeline_checks = [c for c in report['checks'] if c['category'] == 'timeline']
for c in timeline_checks:
    print(c['check'], c['passed'])
")

assert_contains "$RESULT" "True" "validate_structure: timeline checks pass on fixtures"

# Test with backwards timeline
TMP_REF=$(mktemp -d)
cp "${FIXTURE_DIR}/reference/scenes.csv" "${TMP_REF}/scenes.csv"
cp "${FIXTURE_DIR}/reference/scene-intent.csv" "${TMP_REF}/scene-intent.csv"
cp "${FIXTURE_DIR}/reference/scene-briefs.csv" "${TMP_REF}/scene-briefs.csv"

python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import update_scene
# Set scene 2 to day 5, but scene 3 is on day 2 — backwards jump
update_scene('act1-sc02', '${TMP_REF}', {'timeline_day': '5'})
"

RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import validate_structure
report = validate_structure('${TMP_REF}')
timeline_checks = [c for c in report['checks'] if c['category'] == 'timeline']
failed = [c for c in timeline_checks if not c['passed']]
print(len(failed) > 0)
")

assert_equals "True" "$RESULT" "validate_structure: detects backwards timeline jump"

rm -rf "$TMP_REF"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./tests/run-tests.sh tests/test-elaborate.sh
```

Expected: FAIL — thread, knowledge, and timeline checks not yet implemented.

- [ ] **Step 3: Add thread, timeline, and knowledge validation to `validate_structure`**

Add these check functions to `elaborate.py` and call them from `validate_structure`:

```python
def _validate_threads(scenes_map, intent_map, checks):
    """Check thread management: MICE nesting, dormancy, resolution."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    # MICE thread nesting — FILO order
    open_threads = []  # stack of (thread_name, scene_id)
    for sid in sorted_ids:
        intent = intent_map.get(sid, {})
        mice = intent.get('mice_threads', '').strip()
        if not mice:
            continue
        for entry in mice.split(';'):
            entry = entry.strip()
            if not entry:
                continue
            if entry.startswith('+'):
                thread_name = entry[1:]
                open_threads.append((thread_name, sid))
            elif entry.startswith('-'):
                thread_name = entry[1:]
                # Check FILO: the most recently opened thread should match
                if open_threads and open_threads[-1][0] == thread_name:
                    open_threads.pop()
                elif any(t[0] == thread_name for t in open_threads):
                    # Thread exists but not at top — FILO violation
                    checks.append(_check(
                        'threads', 'mice-nesting', False,
                        f"MICE nesting violation: closing '{thread_name}' in {sid} "
                        f"but '{open_threads[-1][0]}' (opened in {open_threads[-1][1]}) "
                        f"should close first",
                        scene_id=sid,
                    ))
                    # Remove it anyway to continue checking
                    open_threads = [(t, s) for t, s in open_threads if t != thread_name]
                else:
                    checks.append(_check(
                        'threads', 'mice-nesting', False,
                        f"Closing MICE thread '{thread_name}' in {sid} but it was never opened",
                        scene_id=sid,
                    ))

    # If no FILO violations were recorded, add a passing check
    if not any(c['check'] == 'mice-nesting' and not c['passed'] for c in checks):
        checks.append(_check('threads', 'mice-nesting', True, 'MICE threads nest correctly'))

    # Unclosed threads
    if open_threads:
        unclosed = [f"{name} (opened in {sid})" for name, sid in open_threads]
        checks.append(_check(
            'threads', 'unclosed-mice-threads', False,
            f"Unclosed MICE threads: {unclosed}",
            severity='advisory',
        ))


def _validate_timeline(scenes_map, checks):
    """Check timeline consistency: no backwards jumps without markers."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    prev_day = None
    prev_id = None
    for sid in sorted_ids:
        day_str = scenes_map[sid].get('timeline_day', '').strip()
        if not day_str:
            continue
        try:
            day = int(day_str)
        except ValueError:
            continue  # Non-numeric timeline markers are allowed

        if prev_day is not None and day < prev_day:
            checks.append(_check(
                'timeline', 'timeline-order', False,
                f"Scene {sid} (day {day}) comes after {prev_id} (day {prev_day}) — backwards jump",
                scene_id=sid,
            ))

        prev_day = day
        prev_id = sid

    if not any(c['check'] == 'timeline-order' and not c['passed'] for c in checks):
        checks.append(_check('timeline', 'timeline-order', True, 'Timeline order is consistent'))


def _validate_knowledge(scenes_map, briefs_map, checks):
    """Check knowledge flow: knowledge_in should be available from prior scenes."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    # Build cumulative knowledge pool
    available_knowledge = set()
    for sid in sorted_ids:
        brief = briefs_map.get(sid, {})
        knowledge_in = brief.get('knowledge_in', '').strip()

        if knowledge_in:
            # Each fact in knowledge_in should either be in available_knowledge
            # or be a starting-state fact (first scene has no prior knowledge)
            facts_in = {f.strip() for f in knowledge_in.split(';') if f.strip()}
            # For the first scene, all knowledge_in is starting state
            if available_knowledge:
                unknown = facts_in - available_knowledge
                if unknown:
                    checks.append(_check(
                        'knowledge', 'knowledge-availability', False,
                        f"Scene {sid} requires knowledge not established by prior scenes: "
                        f"{sorted(unknown)}",
                        scene_id=sid,
                        severity='advisory',
                    ))

        # Add this scene's knowledge_out to the pool
        knowledge_out = brief.get('knowledge_out', '').strip()
        if knowledge_out:
            for fact in knowledge_out.split(';'):
                fact = fact.strip()
                if fact:
                    available_knowledge.add(fact)

    if not any(c['category'] == 'knowledge' and not c['passed'] for c in checks):
        checks.append(_check('knowledge', 'knowledge-availability', True,
                             'Knowledge flow is consistent'))
```

Then update `validate_structure` to call these:

```python
    # Add after the completeness checks, before building the return dict:
    _validate_threads(scenes_map, intent_map, checks)
    _validate_timeline(scenes_map, checks)
    _validate_knowledge(scenes_map, briefs_map, checks)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./tests/run-tests.sh tests/test-elaborate.sh
```

Expected: All assertions PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/elaborate.py tests/test-elaborate.sh
git commit -m "Add structural validation: threads, timeline, and knowledge checks"
```

---

## Task 6: Build structural validation — pacing and scoring checks

**Files:**
- Modify: `scripts/lib/python/storyforge/elaborate.py`
- Modify: `tests/test-elaborate.sh`

- [ ] **Step 1: Write failing tests for pacing validation**

Append to `tests/test-elaborate.sh`:

```bash
# ============================================================================
# validate_structure — pacing checks
# ============================================================================

# Fixtures have varied scene_types and value_shifts — should pass
RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import validate_structure
report = validate_structure('${FIXTURE_DIR}/reference')
pacing_checks = [c for c in report['checks'] if c['category'] == 'pacing']
for c in pacing_checks:
    print(c['check'], c['passed'])
")

assert_contains "$RESULT" "True" "validate_structure: pacing checks pass on fixtures"

# Test with flat polarity stretch
TMP_REF=$(mktemp -d)
cp "${FIXTURE_DIR}/reference/scenes.csv" "${TMP_REF}/scenes.csv"
cp "${FIXTURE_DIR}/reference/scene-intent.csv" "${TMP_REF}/scene-intent.csv"
cp "${FIXTURE_DIR}/reference/scene-briefs.csv" "${TMP_REF}/scene-briefs.csv"

# Make 4 consecutive scenes all have +/- value shift (same polarity pattern)
python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import update_scene
for sid in ['act1-sc01', 'act1-sc02', 'new-x1', 'act2-sc01']:
    update_scene(sid, '${TMP_REF}', {'value_shift': '+/+', 'scene_type': 'action'})
"

RESULT=$(python3 -c "
import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')
from storyforge.elaborate import validate_structure
report = validate_structure('${TMP_REF}')
pacing = [c for c in report['checks'] if c['category'] == 'pacing']
failed = [c for c in pacing if not c['passed']]
print(len(failed) > 0)
")

assert_equals "True" "$RESULT" "validate_structure: detects flat polarity stretch"

rm -rf "$TMP_REF"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./tests/run-tests.sh tests/test-elaborate.sh
```

Expected: FAIL — pacing checks not implemented.

- [ ] **Step 3: Implement pacing validation**

Add to `elaborate.py`:

```python
def _validate_pacing(scenes_map, intent_map, checks):
    """Check pacing: polarity stretches, scene type rhythm, turning point variety."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    # Only check scenes that have intent data (architecture+ status)
    scene_types = []
    value_shifts = []
    turning_points = []

    for sid in sorted_ids:
        intent = intent_map.get(sid, {})
        st = intent.get('scene_type', '').strip()
        vs = intent.get('value_shift', '').strip()
        tp = intent.get('turning_point', '').strip()
        if st:
            scene_types.append((sid, st))
        if vs:
            value_shifts.append((sid, vs))
        if tp:
            turning_points.append((sid, tp))

    # Flat polarity: 3+ scenes with no net change (e.g., +/+, +/+, +/+)
    flat_threshold = 3
    flat_stretches = []
    run_start = 0
    for i in range(1, len(value_shifts)):
        sid, vs = value_shifts[i]
        # "Flat" means the value doesn't change: +/+, -/-
        parts = vs.split('/')
        is_flat = len(parts) == 2 and parts[0].strip() == parts[1].strip()
        prev_parts = value_shifts[i-1][1].split('/')
        prev_flat = len(prev_parts) == 2 and prev_parts[0].strip() == prev_parts[1].strip()

        if is_flat and prev_flat:
            continue  # Still in a flat stretch
        elif is_flat:
            run_start = i
        else:
            if i - run_start >= flat_threshold:
                stretch_ids = [value_shifts[j][0] for j in range(run_start, i)]
                flat_stretches.append(stretch_ids)
            run_start = i

    # Check final stretch
    if len(value_shifts) - run_start >= flat_threshold:
        last_flat = all(
            (lambda p: len(p) == 2 and p[0].strip() == p[1].strip())(
                value_shifts[j][1].split('/')
            )
            for j in range(run_start, len(value_shifts))
        )
        if last_flat:
            stretch_ids = [value_shifts[j][0] for j in range(run_start, len(value_shifts))]
            flat_stretches.append(stretch_ids)

    if flat_stretches:
        for stretch in flat_stretches:
            checks.append(_check(
                'pacing', 'flat-polarity', False,
                f"Flat polarity stretch ({len(stretch)} scenes): {stretch}",
                severity='advisory',
            ))
    else:
        checks.append(_check('pacing', 'flat-polarity', True, 'No flat polarity stretches'))

    # Scene type rhythm: no 4+ consecutive same type
    type_threshold = 4
    if len(scene_types) >= type_threshold:
        for i in range(len(scene_types) - type_threshold + 1):
            window = scene_types[i:i + type_threshold]
            if all(t[1] == window[0][1] for t in window):
                ids = [t[0] for t in window]
                checks.append(_check(
                    'pacing', 'scene-type-rhythm', False,
                    f"{type_threshold}+ consecutive '{window[0][1]}' scenes: {ids}",
                    severity='advisory',
                ))
                break
        else:
            checks.append(_check('pacing', 'scene-type-rhythm', True,
                                 'Scene type rhythm is varied'))
    else:
        checks.append(_check('pacing', 'scene-type-rhythm', True,
                             'Not enough scenes to check rhythm'))

    # Turning point variety: no 4+ consecutive same type
    if len(turning_points) >= type_threshold:
        for i in range(len(turning_points) - type_threshold + 1):
            window = turning_points[i:i + type_threshold]
            if all(t[1] == window[0][1] for t in window):
                ids = [t[0] for t in window]
                checks.append(_check(
                    'pacing', 'turning-point-variety', False,
                    f"{type_threshold}+ consecutive '{window[0][1]}' turning points: {ids}",
                    severity='advisory',
                ))
                break
        else:
            checks.append(_check('pacing', 'turning-point-variety', True,
                                 'Turning point types are varied'))
    else:
        checks.append(_check('pacing', 'turning-point-variety', True,
                             'Not enough scenes to check turning point variety'))
```

Add to `validate_structure`, after the knowledge check call:

```python
    _validate_pacing(scenes_map, intent_map, checks)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./tests/run-tests.sh tests/test-elaborate.sh
```

Expected: All assertions PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/elaborate.py tests/test-elaborate.sh
git commit -m "Add structural validation: pacing and scoring checks"
```

---

## Task 7: Build the `storyforge-validate` CLI script

**Files:**
- Create: `scripts/storyforge-validate`

- [ ] **Step 1: Create the bash CLI wrapper**

```bash
#!/bin/bash
# storyforge-validate — Run structural validation on scene CSVs
#
# Usage:
#   ./storyforge validate                  # Validate current project
#   ./storyforge validate --json           # Output as JSON
#   ./storyforge validate --quiet          # Exit code only (0=pass, 1=fail)
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

detect_project_root

# Parse args
JSON_OUTPUT=false
QUIET=false
for arg in "$@"; do
    case "$arg" in
        --json)   JSON_OUTPUT=true ;;
        --quiet)  QUIET=true ;;
        -h|--help)
            echo "Usage: storyforge validate [--json] [--quiet]"
            echo "  --json   Output results as JSON"
            echo "  --quiet  Exit code only (0=pass, 1=fail)"
            exit 0
            ;;
    esac
done

PYTHON_LIB="${SCRIPT_DIR}/lib/python"
REF_DIR="${PROJECT_DIR}/reference"

if [[ ! -f "${REF_DIR}/scenes.csv" ]]; then
    echo "Error: No scenes.csv found in ${REF_DIR}. Is this an elaboration pipeline project?"
    exit 1
fi

RESULT=$(python3 -c "
import sys, json
sys.path.insert(0, '${PYTHON_LIB}')
from storyforge.elaborate import validate_structure
report = validate_structure('${REF_DIR}')
print(json.dumps(report, indent=2))
")

if [[ "$JSON_OUTPUT" == true ]]; then
    echo "$RESULT"
elif [[ "$QUIET" == true ]]; then
    # Silent — exit code only
    :
else
    # Human-readable output
    PASSED=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r['passed'])")
    FAILURES=$(echo "$RESULT" | python3 -c "
import sys, json
r = json.load(sys.stdin)
for f in r['failures']:
    severity = f.get('severity', 'blocking')
    scene = f.get('scene_id', '')
    prefix = f'  [{severity}]'
    if scene:
        prefix += f' {scene}:'
    print(f\"{prefix} {f['message']}\")
")
    TOTAL=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(len(r['checks']))")
    FAIL_COUNT=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(len(r['failures']))")

    if [[ "$PASSED" == "True" ]]; then
        log "Validation passed (${TOTAL} checks, 0 failures)"
    else
        log "Validation failed (${TOTAL} checks, ${FAIL_COUNT} failure(s)):"
        echo "$FAILURES"
    fi
fi

# Exit code
PASSED=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r['passed'])")
if [[ "$PASSED" == "True" ]]; then
    exit 0
else
    exit 1
fi
```

Write to `scripts/storyforge-validate`.

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/storyforge-validate
```

- [ ] **Step 3: Test manually against fixture**

```bash
PROJECT_DIR=tests/fixtures/test-project ./scripts/storyforge-validate
```

Expected: "Validation passed" message with exit code 0.

```bash
PROJECT_DIR=tests/fixtures/test-project ./scripts/storyforge-validate --json | python3 -m json.tool | head -20
```

Expected: Well-formed JSON output.

- [ ] **Step 4: Commit**

```bash
git add scripts/storyforge-validate
git commit -m "Add storyforge-validate CLI script"
```

---

## Task 8: Update project templates for three-file model

**Files:**
- Create: `templates/reference/scenes.csv`
- Create: `templates/reference/scene-briefs.csv`
- Modify: `templates/reference/scene-intent.csv`
- Modify: `templates/storyforge.yaml`

- [ ] **Step 1: Create template CSV files**

`templates/reference/scenes.csv`:
```
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|status|word_count|target_words
```

`templates/reference/scene-intent.csv` (replace existing):
```
id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
```

`templates/reference/scene-briefs.csv`:
```
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
```

- [ ] **Step 2: Update storyforge.yaml template phase values**

Read the current template and add the new elaboration phases. The `phase` field should accept: `spine`, `architecture`, `scene-map`, `briefs`, `drafting`, `evaluation`, `revision`, `review`, `polish`, `complete`, `production`. These supplement the existing values.

Add a comment in the template documenting the elaboration pipeline phases:

```yaml
# Phase tracks overall project progress.
# Elaboration pipeline: spine → architecture → scene-map → briefs → drafting → evaluation → polish → production
# Legacy pipeline: development → scene-design → drafting → evaluation → revision → review → complete → production
phase: spine
```

- [ ] **Step 3: Verify template files exist and are well-formed**

```bash
head -1 templates/reference/scenes.csv
head -1 templates/reference/scene-intent.csv
head -1 templates/reference/scene-briefs.csv
```

Expected: Header rows with pipe delimiters.

- [ ] **Step 4: Commit**

```bash
git add templates/reference/scenes.csv templates/reference/scene-intent.csv templates/reference/scene-briefs.csv templates/storyforge.yaml
git commit -m "Update templates for three-file scene CSV model"
```

---

## Task 9: Version bump and final test run

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Run the full test suite**

```bash
./tests/run-tests.sh
```

Expected: All existing tests pass. New `test-elaborate.sh` tests pass. No regressions in existing `test-csv.sh`, `test-scene-filter.sh`, etc.

- [ ] **Step 2: Bump version**

Bump patch version in `.claude-plugin/plugin.json` (e.g., `0.39.7` → `0.40.0` since this is a new feature).

- [ ] **Step 3: Commit and push**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 0.40.0"
git push
```

---

## What's Next

This plan builds the foundation. The remaining plans (to be written separately) are:

- **Plan 2: Elaboration** — The elaborate script and skill, spine/architecture/map/briefs stages, PR workflow
- **Plan 3: Drafting & Evaluation** — Modified write script (parallel waves), modified evaluate (finding categorization), polish script, scoring additions
- **Plan 4: Skill Updates & Migration** — Updated skills (scenes, develop, recommend, plan-revision), migration tooling
