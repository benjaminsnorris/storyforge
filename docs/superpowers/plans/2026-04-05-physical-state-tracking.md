# Physical State Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add physical state tracking for characters across scenes, following the existing knowledge chain pattern with carry-forward columns on scene-briefs.csv backed by a canonical registry.

**Architecture:** Two new columns (`physical_state_in`, `physical_state_out`) on scene-briefs.csv with semicolon-separated state IDs normalized against `reference/physical-states.csv`. Validation, scoring, prompt integration, extraction, and reconciliation all mirror the knowledge chain's existing patterns.

**Tech Stack:** Python 3 (storyforge modules), Bash (test runner), pipe-delimited CSV

---

### Task 1: Add test fixtures

**Files:**
- Modify: `tests/fixtures/test-project/reference/physical-states.csv` (create)
- Modify: `tests/fixtures/test-project/reference/scene-briefs.csv`

- [ ] **Step 1: Create the physical-states.csv fixture**

Create `tests/fixtures/test-project/reference/physical-states.csv`:

```
id|character|description|category|acquired|resolves|action_gating
sprained-ankle-tessa|Tessa Merrin|right ankle sprained during ridge collapse|injury|act2-sc02|never|true
archive-key-dorren|Dorren Hayle|holds the restricted archive key|equipment|act1-sc02|never|true
exhaustion-tessa|Tessa Merrin|physically exhausted from 4-hour eastern trek|fatigue|act2-sc01|act2-sc03|false
scar-left-hand-kael|Kael Maren|old scar across left palm from archive incident|appearance|new-x1|never|false
```

- [ ] **Step 2: Add physical_state_in and physical_state_out columns to scene-briefs.csv fixture**

The current fixture header is:

```
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
```

Add `physical_state_in|physical_state_out` after `has_overflow`. Update each row:

- `act1-sc01`: `||` (no states)
- `act1-sc02`: `|archive-key-dorren` (Dorren acquires the key)
- `new-x1`: `||` (empty — mapped status, no briefs data populated)
- `act2-sc03`: `archive-key-dorren;exhaustion-tessa|archive-key-dorren` (Tessa's exhaustion resolves)

The full updated file content:

```
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow|physical_state_in|physical_state_out
act1-sc01|Complete the quarterly pressure audit on schedule|Anomalous readings in eastern sector don't match any known pattern|no-and|Report the anomaly and risk protocol review, or file it as instrument error and stay on schedule|Files as instrument error but keeps a private note||map-anomaly-exists|Reviews maps;Finds anomaly;Consults Tessa;Files as error;Makes private note|"The eastern readings are within acceptable variance";Dorren privately: "Acceptable is not the same as explained"|competence;unease;self-doubt;resolve|maps/cartography;acceptable-variance||false||
act1-sc02|Understand the anomaly by cross-referencing historical archives|The village that should appear on the 40-year map is simply absent — no record of removal|no-and|Accept the archive is incomplete and move on, or pursue an explanation that has no institutional support|Decides to pursue quietly, outside protocol|map-anomaly-exists|village-vanished;archive-erasure|Cross-references maps;Discovers missing village;Searches removal logs;Finds nothing|"It was there forty years ago. It isn't there now. There is no note."|routine;confusion;dread;determination|depth/descent;maps/cartography|act1-sc01|false||archive-key-dorren
new-x1|||||||||||||||
act2-sc03|Convince the council that the eastern anomalies require investigation|Council members see the anomaly as Dorren's procedural fixation, not evidence of erasure|no|Accept the council's dismissal and work within channels, or go outside the institution entirely|Goes outside — shares findings with Kael privately after the meeting|village-vanished;archive-erasure|council-dismisses-evidence|Presents evidence;Council dismisses;Dorren argues;Is overruled;Meets Kael after|Council: "We appreciate your diligence, Cartographer.";Dorren to Kael: "They won't look."|resolve;frustration;bitter-resignation;quiet-defiance|governance-as-weight;blindness/seeing|act1-sc02;new-x1|false|archive-key-dorren;exhaustion-tessa|archive-key-dorren
```

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/test-project/reference/physical-states.csv tests/fixtures/test-project/reference/scene-briefs.csv
git commit -m "Add physical state tracking test fixtures"
git push
```

---

### Task 2: Add column definitions to elaborate.py and schema.py

**Files:**
- Modify: `scripts/lib/python/storyforge/elaborate.py:29-33`
- Modify: `scripts/lib/python/storyforge/schema.py:18-39,59-221`

- [ ] **Step 1: Write test for the new enum and schema entries**

Create `tests/test-physical-state.sh`:

```bash
#!/bin/bash
# test-physical-state.sh — Tests for physical state tracking

PYTHON_DIR="${PLUGIN_DIR}/scripts/lib/python"
PY="import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')"

# ============================================================================
# Enum: valid physical state categories
# ============================================================================

echo "--- enum: valid physical state categories ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import _check_enum, VALID_PHYSICAL_STATE_CATEGORIES
for v in ['injury', 'equipment', 'ability', 'appearance', 'fatigue']:
    print(_check_enum(v, VALID_PHYSICAL_STATE_CATEGORIES))
" 2>/dev/null)

assert_equals "True
True
True
True
True" "$RESULT" "enum: all valid physical state categories accepted"

echo "--- enum: invalid physical state categories ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import _check_enum, VALID_PHYSICAL_STATE_CATEGORIES
print(_check_enum('emotional', VALID_PHYSICAL_STATE_CATEGORIES))
print(_check_enum('weather', VALID_PHYSICAL_STATE_CATEGORIES))
" 2>/dev/null)

assert_equals "False
False" "$RESULT" "enum: invalid physical state categories rejected"

# ============================================================================
# Schema: physical_state_in and physical_state_out are defined
# ============================================================================

echo "--- schema: physical state columns defined ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import COLUMN_SCHEMA
psi = COLUMN_SCHEMA.get('physical_state_in')
pso = COLUMN_SCHEMA.get('physical_state_out')
assert psi is not None, 'physical_state_in not in schema'
assert pso is not None, 'physical_state_out not in schema'
assert psi['type'] == 'registry'
assert psi['registry'] == 'physical-states.csv'
assert psi['array'] == True
assert psi['file'] == 'scene-briefs.csv'
assert pso['type'] == 'registry'
assert pso['registry'] == 'physical-states.csv'
assert pso['array'] == True
print('ok')
" 2>/dev/null)

assert_equals "ok" "$RESULT" "schema: physical_state_in and physical_state_out defined correctly"

# ============================================================================
# Schema: physical-states.csv registry columns defined
# ============================================================================

echo "--- schema: physical-states.csv columns defined ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import COLUMN_SCHEMA
cat = COLUMN_SCHEMA.get('physical_states_category')
ag = COLUMN_SCHEMA.get('physical_states_action_gating')
assert cat is not None, 'physical_states_category not in schema'
assert cat['type'] == 'enum'
assert ag is not None, 'physical_states_action_gating not in schema'
assert ag['type'] == 'boolean'
print('ok')
" 2>/dev/null)

assert_equals "ok" "$RESULT" "schema: physical-states.csv registry columns defined"

# ============================================================================
# Column list: _BRIEFS_COLS includes physical state columns
# ============================================================================

echo "--- elaborate: _BRIEFS_COLS includes physical state columns ---"

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _BRIEFS_COLS
assert 'physical_state_in' in _BRIEFS_COLS, 'physical_state_in not in _BRIEFS_COLS'
assert 'physical_state_out' in _BRIEFS_COLS, 'physical_state_out not in _BRIEFS_COLS'
print('ok')
" 2>/dev/null)

assert_equals "ok" "$RESULT" "elaborate: _BRIEFS_COLS includes physical state columns"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: Multiple FAILs — enum not defined, schema entries missing, columns not in `_BRIEFS_COLS`.

- [ ] **Step 3: Add VALID_PHYSICAL_STATE_CATEGORIES enum to schema.py**

In `scripts/lib/python/storyforge/schema.py`, after line 39 (`VALID_TURNING_POINTS`), add:

```python
VALID_PHYSICAL_STATE_CATEGORIES = frozenset({
    'injury', 'equipment', 'ability', 'appearance', 'fatigue',
})
```

- [ ] **Step 4: Add physical state column entries to COLUMN_SCHEMA in schema.py**

In `scripts/lib/python/storyforge/schema.py`, after the `has_overflow` entry (line 220) and before the closing `}` of `COLUMN_SCHEMA`, add:

```python
    'physical_state_in': {
        'type': 'registry', 'registry': 'physical-states.csv', 'array': True,
        'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'Physical state IDs active when scene begins. Normalized against reference/physical-states.csv.',
    },
    'physical_state_out': {
        'type': 'registry', 'registry': 'physical-states.csv', 'array': True,
        'file': 'scene-briefs.csv', 'stage': 'brief',
        'description': 'Physical state IDs active when scene ends. Includes physical_state_in plus new, minus resolved.',
    },
    # physical-states.csv registry columns
    'physical_states_character': {
        'type': 'registry', 'registry': 'characters.csv', 'array': False,
        'file': 'physical-states.csv', 'stage': 'brief',
        'description': 'Character this physical state belongs to.',
    },
    'physical_states_category': {
        'type': 'enum', 'values': VALID_PHYSICAL_STATE_CATEGORIES,
        'file': 'physical-states.csv', 'stage': 'brief',
        'description': 'State category: injury, equipment, ability, appearance, fatigue.',
    },
    'physical_states_acquired': {
        'type': 'scene_ids', 'file': 'physical-states.csv', 'stage': 'brief',
        'description': 'Scene where this state is acquired.',
    },
    'physical_states_resolves': {
        'type': 'free_text', 'file': 'physical-states.csv', 'stage': 'brief',
        'description': 'Scene ID where resolved, or "never" for permanent.',
    },
    'physical_states_action_gating': {
        'type': 'boolean', 'file': 'physical-states.csv', 'stage': 'brief',
        'description': 'Whether this state constrains character capability.',
    },
```

- [ ] **Step 5: Add physical state columns to _BRIEFS_COLS in elaborate.py**

In `scripts/lib/python/storyforge/elaborate.py`, change `_BRIEFS_COLS` (lines 29-33) from:

```python
_BRIEFS_COLS = [
    'id', 'goal', 'conflict', 'outcome', 'crisis', 'decision',
    'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
    'emotions', 'motifs', 'continuity_deps', 'has_overflow',
]
```

to:

```python
_BRIEFS_COLS = [
    'id', 'goal', 'conflict', 'outcome', 'crisis', 'decision',
    'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
    'emotions', 'motifs', 'continuity_deps', 'has_overflow',
    'physical_state_in', 'physical_state_out',
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: All PASS.

- [ ] **Step 7: Run full test suite to check for regressions**

Run: `./tests/run-tests.sh`
Expected: All existing suites still pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/python/storyforge/schema.py scripts/lib/python/storyforge/elaborate.py tests/test-physical-state.sh
git commit -m "Add physical state schema definitions and column list"
git push
```

---

### Task 3: Add structural validation for physical state flow

**Files:**
- Modify: `scripts/lib/python/storyforge/elaborate.py:576-608,754-758`
- Modify: `tests/test-physical-state.sh`

- [ ] **Step 1: Add validation tests to test-physical-state.sh**

Append to `tests/test-physical-state.sh`:

```bash
# ============================================================================
# Validation: _validate_physical_states
# ============================================================================

echo "--- validate: physical state flow — consistent ---"

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure

result = validate_structure('${FIXTURE_DIR}/reference')
phys_checks = [c for c in result['checks'] if c['category'] == 'physical_state']
# Fixture has consistent state flow, so should pass
for c in phys_checks:
    print(f\"{c['check_type']}: {'PASS' if c['passed'] else 'FAIL'}\")
if not phys_checks:
    print('no physical_state checks found')
else:
    print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "validate: physical state checks run on fixtures"
assert_not_contains "$RESULT" "FAIL" "validate: fixture physical state flow is consistent"

echo "--- validate: unknown state flagged ---"

RESULT=$(python3 -c "
${PY}
import os, tempfile, shutil
from storyforge.elaborate import _read_csv, _write_csv, _FILE_MAP, validate_structure

# Copy fixtures to temp dir
tmpdir = tempfile.mkdtemp()
ref = os.path.join(tmpdir, 'reference')
shutil.copytree('${FIXTURE_DIR}/reference', ref)

# Inject an unknown state into physical_state_in
briefs_path = os.path.join(ref, 'scene-briefs.csv')
rows = _read_csv(briefs_path)
for r in rows:
    if r['id'] == 'act1-sc01':
        r['physical_state_in'] = 'nonexistent-state'
_write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])

result = validate_structure(ref)
phys_fails = [c for c in result['checks'] if c['category'] == 'physical_state' and not c['passed']]
found = any('nonexistent-state' in c.get('detail', '') for c in phys_fails)
print('found_unknown' if found else 'not_found')

shutil.rmtree(tmpdir)
" 2>/dev/null)

assert_equals "found_unknown" "$RESULT" "validate: unknown physical state in physical_state_in is flagged"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: The new validation tests fail — `no physical_state checks found` and `not_found`.

- [ ] **Step 3: Implement _validate_physical_states in elaborate.py**

In `scripts/lib/python/storyforge/elaborate.py`, after the `_validate_knowledge` function (after line 607), add:

```python
def _validate_physical_states(scenes_map, briefs_map, checks):
    """Check physical state flow: physical_state_in must come from prior scenes' physical_state_out."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    available_states = set()

    for sid in sorted_ids:
        brief = briefs_map.get(sid, {})
        state_in = brief.get('physical_state_in', '').strip()

        if state_in:
            states_in = {s.strip() for s in state_in.split(';') if s.strip()}
            unknown = states_in - available_states
            if unknown:
                checks.append(_check(
                    'physical_state', 'state-availability', False,
                    f"Scene {sid} references physical states not established by prior scenes: "
                    f"{sorted(unknown)}",
                    scene_id=sid,
                    severity='advisory',
                ))

        state_out = brief.get('physical_state_out', '').strip()
        if state_out:
            for state_id in state_out.split(';'):
                state_id = state_id.strip()
                if state_id:
                    available_states.add(state_id)

    if not any(c['category'] == 'physical_state' and not c['passed'] for c in checks):
        checks.append(_check('physical_state', 'state-availability', True,
                             'Physical state flow is consistent'))
```

- [ ] **Step 4: Wire _validate_physical_states into validate_structure**

In `scripts/lib/python/storyforge/elaborate.py`, in the `validate_structure` function, after line 758 (`_validate_pacing(scenes_map, intent_map, checks)`), add:

```python
    _validate_physical_states(scenes_map, briefs_map, checks)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: All PASS.

- [ ] **Step 6: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All suites pass. Existing `validate_structure` tests still pass (physical state checks are additive).

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/elaborate.py tests/test-physical-state.sh
git commit -m "Add physical state flow validation"
git push
```

---

### Task 4: Add granularity validation for physical states

**Files:**
- Modify: `scripts/lib/python/storyforge/schema.py:490-562`
- Modify: `tests/test-physical-state.sh`

- [ ] **Step 1: Add granularity validation tests**

Append to `tests/test-physical-state.sh`:

```bash
# ============================================================================
# Granularity validation
# ============================================================================

echo "--- granularity: clean fixture passes ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import validate_physical_state_granularity
result = validate_physical_state_granularity('${FIXTURE_DIR}/reference')
print(f\"total_states={result['total_states']}\")
print(f\"warnings={len(result['warnings'])}\")
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "granularity: fixture passes"
assert_contains "$RESULT" "total_states=4" "granularity: counts 4 states in fixture"
assert_contains "$RESULT" "warnings=0" "granularity: no warnings on clean fixture"

echo "--- granularity: long description flagged ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import os, tempfile, shutil
from storyforge.schema import validate_physical_state_granularity
from storyforge.elaborate import _read_csv, _write_csv

tmpdir = tempfile.mkdtemp()
ref = os.path.join(tmpdir, 'reference')
shutil.copytree('${FIXTURE_DIR}/reference', ref)

# Add a state with a very long description (>20 words)
path = os.path.join(ref, 'physical-states.csv')
rows = _read_csv(path)
rows.append({
    'id': 'verbose-state',
    'character': 'Dorren Hayle',
    'description': 'a really quite extraordinarily long and overly detailed description of a minor bruise on the left side of the upper right forearm near the elbow joint area',
    'category': 'injury',
    'acquired': 'act1-sc01',
    'resolves': 'never',
    'action_gating': 'false',
})
_write_csv(path, rows, ['id', 'character', 'description', 'category', 'acquired', 'resolves', 'action_gating'])

result = validate_physical_state_granularity(ref)
has_long = any(w['type'] == 'long_description' for w in result['warnings'])
print('found_long' if has_long else 'not_found')

shutil.rmtree(tmpdir)
" 2>/dev/null)

assert_equals "found_long" "$RESULT" "granularity: long description flagged"

echo "--- granularity: too many new states flagged ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import os, tempfile, shutil
from storyforge.schema import validate_physical_state_granularity
from storyforge.elaborate import _read_csv, _write_csv, _FILE_MAP

tmpdir = tempfile.mkdtemp()
ref = os.path.join(tmpdir, 'reference')
shutil.copytree('${FIXTURE_DIR}/reference', ref)

# Give act1-sc01 4+ new states in physical_state_out (0 in state_in)
briefs_path = os.path.join(ref, 'scene-briefs.csv')
rows = _read_csv(briefs_path)
for r in rows:
    if r['id'] == 'act1-sc01':
        r['physical_state_out'] = 'a;b;c;d'
_write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])

result = validate_physical_state_granularity(ref)
has_many = any(w['type'] == 'too_many_new_states' for w in result['warnings'])
print('found_many' if has_many else 'not_found')

shutil.rmtree(tmpdir)
" 2>/dev/null)

assert_equals "found_many" "$RESULT" "granularity: too many new states in one scene flagged"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: The new granularity tests fail — `validate_physical_state_granularity` not defined.

- [ ] **Step 3: Implement validate_physical_state_granularity in schema.py**

In `scripts/lib/python/storyforge/schema.py`, after `validate_knowledge_granularity` (after line 562), add:

```python
MAX_STATE_DESCRIPTION_WORDS = 20
MAX_NEW_STATES_PER_SCENE = 3


def validate_physical_state_granularity(ref_dir: str, project_dir: str | None = None) -> dict:
    """Check physical states for over-granularity.

    Registry-level: flag descriptions longer than MAX_STATE_DESCRIPTION_WORDS.
    Scene-level: flag scenes with more than MAX_NEW_STATES_PER_SCENE new states.

    Returns:
        Dict with total_states, total_scenes, warnings.
    """
    warnings: list[dict] = []

    # --- Registry-level checks ---
    states_path = os.path.join(ref_dir, 'physical-states.csv')
    total_states = 0
    if os.path.isfile(states_path):
        for row in _read_csv(states_path):
            total_states += 1
            desc = row.get('description', '').strip()
            if not desc:
                continue
            word_count = len(desc.split())
            if word_count > MAX_STATE_DESCRIPTION_WORDS:
                warnings.append({
                    'type': 'long_description',
                    'id': row.get('id', '?'),
                    'description': desc,
                    'word_count': word_count,
                })

    # --- Scene-level checks ---
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    total_scenes = 0
    if os.path.isfile(briefs_path):
        for row in _read_csv(briefs_path):
            total_scenes += 1
            ps_in_raw = row.get('physical_state_in', '').strip()
            ps_out_raw = row.get('physical_state_out', '').strip()

            ps_in = {e.strip() for e in ps_in_raw.split(';') if e.strip()} if ps_in_raw else set()
            ps_out = {e.strip() for e in ps_out_raw.split(';') if e.strip()} if ps_out_raw else set()

            new_states = sorted(ps_out - ps_in)

            if len(new_states) > MAX_NEW_STATES_PER_SCENE:
                warnings.append({
                    'type': 'too_many_new_states',
                    'scene_id': row.get('id', '?'),
                    'new_state_count': len(new_states),
                    'states': new_states,
                })

    return {
        'total_states': total_states,
        'total_scenes': total_scenes,
        'warnings': warnings,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/schema.py tests/test-physical-state.sh
git commit -m "Add physical state granularity validation"
git push
```

---

### Task 5: Add structural scoring for physical state chain

**Files:**
- Modify: `scripts/lib/python/storyforge/structural.py:53-56,1229-1260,1293-1301`
- Modify: `tests/test-physical-state.sh`

- [ ] **Step 1: Add scoring tests**

Append to `tests/test-physical-state.sh`:

```bash
# ============================================================================
# Structural scoring: score_physical_state_chain
# ============================================================================

echo "--- scoring: returns valid score on fixtures ---"

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_physical_state_chain

scenes = _read_csv_as_map('${FIXTURE_DIR}/reference/scenes.csv')
briefs = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-briefs.csv')

result = score_physical_state_chain(scenes, briefs, '${FIXTURE_DIR}/reference')
score = result['score']
findings = result['findings']

assert 0 <= score <= 1, f'Score out of range: {score}'
assert isinstance(findings, list)
print(f'score={score:.2f}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "scoring: score_physical_state_chain returns valid score"

echo "--- scoring: empty states returns zero ---"

RESULT=$(python3 -c "
${PY}
from storyforge.structural import score_physical_state_chain

scenes = {'s1': {'id': 's1', 'seq': '1'}, 's2': {'id': 's2', 'seq': '2'}}
briefs = {'s1': {'id': 's1'}, 's2': {'id': 's2'}}

result = score_physical_state_chain(scenes, briefs, '/nonexistent')
print(f'score={result[\"score\"]:.2f}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "score=0.00" "scoring: no states returns 0.0"
assert_contains "$RESULT" "ok" "scoring: empty case runs without error"

echo "--- scoring: included in structural_score ---"

RESULT=$(python3 -c "
${PY}
from storyforge.structural import structural_score

result = structural_score('${FIXTURE_DIR}/reference')
dims = {d['name'] for d in result['dimensions']}
assert 'physical_state' in dims, f'physical_state not in dimensions: {dims}'
print('ok')
" 2>/dev/null)

assert_equals "ok" "$RESULT" "scoring: physical_state dimension in structural_score"

echo "--- scoring: ENRICHMENT_FIELDS includes physical state ---"

RESULT=$(python3 -c "
${PY}
from storyforge.structural import ENRICHMENT_FIELDS
assert 'physical_state_in' in ENRICHMENT_FIELDS
assert 'physical_state_out' in ENRICHMENT_FIELDS
print('ok')
" 2>/dev/null)

assert_equals "ok" "$RESULT" "scoring: ENRICHMENT_FIELDS includes physical state columns"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: Fails — `score_physical_state_chain` not defined, `physical_state` not in dimensions.

- [ ] **Step 3: Add physical state columns to ENRICHMENT_FIELDS**

In `scripts/lib/python/storyforge/structural.py`, change `ENRICHMENT_FIELDS` (lines 53-56) from:

```python
ENRICHMENT_FIELDS = [
    'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
    'emotions', 'motifs', 'continuity_deps', 'mice_threads',
]
```

to:

```python
ENRICHMENT_FIELDS = [
    'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
    'emotions', 'motifs', 'continuity_deps', 'mice_threads',
    'physical_state_in', 'physical_state_out',
]
```

- [ ] **Step 4: Implement score_physical_state_chain**

In `scripts/lib/python/storyforge/structural.py`, after `score_knowledge_chain` (after line 1104), add:

```python
# ---------------------------------------------------------------------------
# Physical State Chain
# ---------------------------------------------------------------------------

def score_physical_state_chain(scenes_map, briefs_map, ref_dir=''):
    """Score physical state tracking — coverage, persistence, density.

    Args:
        scenes_map: dict from _read_csv_as_map on scenes.csv
        briefs_map: dict from _read_csv_as_map on scene-briefs.csv
        ref_dir: path to reference dir (for physical-states.csv registry)

    Returns:
        {'score': float 0-1, 'findings': [...]}
    """
    findings = []

    def _seq(item):
        try:
            return int(item[1].get('seq', 0))
        except (ValueError, TypeError):
            return 0

    ordered = sorted(scenes_map.items(), key=_seq)
    scene_ids = [sid for sid, _ in ordered]
    n = len(scene_ids)

    if n == 0:
        return {'score': 0.0, 'findings': [{'message': 'No scenes found', 'severity': 'important', 'fix_location': 'brief'}]}

    # --- 1. Coverage (40%) ---
    has_psi = 0
    has_pso = 0
    all_states = {}  # state_id -> list of scene indices

    for idx, sid in enumerate(scene_ids):
        brief = briefs_map.get(sid, {})
        psi = brief.get('physical_state_in', '').strip()
        pso = brief.get('physical_state_out', '').strip()
        if psi:
            has_psi += 1
            for state in psi.split(';'):
                state = state.strip()
                if state:
                    all_states.setdefault(state, []).append(idx)
        if pso:
            has_pso += 1
            for state in pso.split(';'):
                state = state.strip()
                if state:
                    all_states.setdefault(state, []).append(idx)

    total_states = len(all_states)

    # If no states at all, score 0 with no findings (it's optional)
    if total_states == 0:
        return {'score': 0.0, 'findings': []}

    coverage_in = has_psi / n if n > 0 else 0.0
    coverage_out = has_pso / n if n > 0 else 0.0
    coverage = (coverage_in + coverage_out) / 2.0

    if coverage < 0.2:
        findings.append({
            'message': f"Low physical state coverage: {has_psi}/{n} scenes have physical_state_in, {has_pso}/{n} have physical_state_out",
            'severity': 'important',
            'fix_location': 'brief',
        })

    # --- 2. Persistence (35%) ---
    # Check: states that appear in multiple scenes should form contiguous ranges
    persistent_states = {s: idxs for s, idxs in all_states.items() if len(idxs) >= 2}
    persistence = 1.0
    if persistent_states:
        contiguous_count = 0
        for state_id, indices in persistent_states.items():
            min_idx = min(indices)
            max_idx = max(indices)
            expected_span = max_idx - min_idx + 1
            # Check if state appears in all scenes in its range
            actual_span = len(set(indices))
            if actual_span >= expected_span * 0.7:  # 70% threshold
                contiguous_count += 1
        persistence = contiguous_count / len(persistent_states) if persistent_states else 1.0

    # --- 3. Density (25%) ---
    density = min(1.0, total_states / (n * 0.3)) if n > 0 else 0.0

    # Composite
    score = coverage * 0.4 + persistence * 0.35 + density * 0.25
    score = max(0.0, min(1.0, score))

    return {'score': score, 'findings': findings}
```

- [ ] **Step 5: Add physical_state to orchestrator constants**

In `scripts/lib/python/storyforge/structural.py`, add `'physical_state'` to the three orchestrator dicts:

In `_DEFAULT_WEIGHTS` (after `'completeness': 0.3,`):
```python
    'physical_state': 0.3,
```

In `_DIMENSION_LABELS` (after `'completeness': 'Structural Completeness',`):
```python
    'physical_state': 'Physical State Chain',
```

In `_DIMENSION_TARGETS` (after `'completeness': 0.80,`):
```python
    'physical_state': 0.50,
```

- [ ] **Step 6: Wire into structural_score orchestrator**

In `scripts/lib/python/storyforge/structural.py`, in the `structural_score` function, after line 1301 (`'function_variety': score_function_variety(intent_map, briefs_map),`), add:

```python
        'physical_state': score_physical_state_chain(scenes_map, briefs_map, ref_dir),
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: All PASS.

- [ ] **Step 8: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All suites pass. Existing structural scoring tests still pass (new dimension is additive; existing scores may shift slightly due to weight redistribution, but relative ordering stays the same).

- [ ] **Step 9: Commit**

```bash
git add scripts/lib/python/storyforge/structural.py tests/test-physical-state.sh
git commit -m "Add physical state chain structural scoring"
git push
```

---

### Task 6: Add physical state to drafting prompts

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts.py:940-1024`
- Modify: `tests/test-physical-state.sh`

- [ ] **Step 1: Add prompt integration tests**

Append to `tests/test-physical-state.sh`:

```bash
# ============================================================================
# Drafting prompts: physical state in scene prompt
# ============================================================================

echo "--- prompts: physical state block appears in drafting prompt ---"

RESULT=$(python3 -c "
${PY}
from storyforge.prompts import build_scene_prompt_from_briefs
prompt = build_scene_prompt_from_briefs('act2-sc03', '${FIXTURE_DIR}', '${PLUGIN_DIR}')
has_header = 'Active Physical States' in prompt
has_state = 'archive-key-dorren' in prompt or 'archive key' in prompt.lower()
print('has_header' if has_header else 'no_header')
print('has_state' if has_state else 'no_state')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "has_header" "prompts: physical state section header present"
assert_contains "$RESULT" "has_state" "prompts: state ID or description appears in prompt"
assert_contains "$RESULT" "ok" "prompts: build_scene_prompt_from_briefs runs without error"

echo "--- prompts: no physical state block when no states ---"

RESULT=$(python3 -c "
${PY}
from storyforge.prompts import build_scene_prompt_from_briefs
prompt = build_scene_prompt_from_briefs('act1-sc01', '${FIXTURE_DIR}', '${PLUGIN_DIR}')
has_header = 'Active Physical States' in prompt
print('has_header' if has_header else 'no_header')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "no_header" "prompts: no physical state section when no states active"
assert_contains "$RESULT" "ok" "prompts: empty state case runs without error"

echo "--- prompts: dependency scenes show physical_state_out ---"

RESULT=$(python3 -c "
${PY}
from storyforge.prompts import build_scene_prompt_from_briefs
prompt = build_scene_prompt_from_briefs('act2-sc03', '${FIXTURE_DIR}', '${PLUGIN_DIR}', dep_scenes=['act1-sc02'])
has_dep_state = 'physical_state_out' in prompt
print('has_dep_state' if has_dep_state else 'no_dep_state')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "has_dep_state" "prompts: dependency scenes include physical_state_out"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: Fails — no "Active Physical States" header, no physical_state_out in dep summary.

- [ ] **Step 3: Add physical state block to drafting prompt**

In `scripts/lib/python/storyforge/prompts.py`, in `build_scene_prompt_from_briefs`, after the character bible block (around line 980) and before the craft principles block (line 982), add the physical state section:

```python
    # Physical state context
    state_block = ''
    state_in = scene.get('physical_state_in', '').strip()
    if state_in:
        state_ids = [s.strip() for s in state_in.split(';') if s.strip()]
        # Try to load registry for descriptions
        states_registry = {}
        states_path = os.path.join(ref_dir, 'physical-states.csv')
        if os.path.isfile(states_path):
            from .elaborate import _read_csv_as_map
            states_registry = _read_csv_as_map(states_path)

        state_lines = []
        for sid in state_ids:
            entry = states_registry.get(sid, {})
            char = entry.get('character', '')
            desc = entry.get('description', sid)
            gating = entry.get('action_gating', 'false').lower() == 'true'
            line = f"- **{char}**: {desc}" if char else f"- {desc}"
            if gating:
                line += " *(action-gating)*"
            state_lines.append(line)

        state_block = (
            "## Active Physical States\n\n"
            "Characters entering this scene carry these states:\n\n"
            + '\n'.join(state_lines)
        )
```

- [ ] **Step 4: Add physical_state_out to dependency scene summary**

In `scripts/lib/python/storyforge/prompts.py`, in the dependency context block (around line 956-959), change the `dep_summary` to include physical_state_out:

From:
```python
                dep_summary = (
                    f"**{dep_id}** — {dep.get('function', '')}\n"
                    f"  outcome: {dep.get('outcome', '')}\n"
                    f"  knowledge_out: {dep.get('knowledge_out', '')}\n"
                    f"  emotional_arc: {dep.get('emotional_arc', '')}"
                )
```

To:
```python
                dep_summary = (
                    f"**{dep_id}** — {dep.get('function', '')}\n"
                    f"  outcome: {dep.get('outcome', '')}\n"
                    f"  knowledge_out: {dep.get('knowledge_out', '')}\n"
                    f"  physical_state_out: {dep.get('physical_state_out', '')}\n"
                    f"  emotional_arc: {dep.get('emotional_arc', '')}"
                )
```

- [ ] **Step 5: Include state_block in the final prompt assembly**

In `scripts/lib/python/storyforge/prompts.py`, in the return f-string (around line 1053-1068), add `{state_block}` between `{dep_block}` and `{voice_guide}`. Change:

```python
    return f"""You are drafting a scene for "{title}" ({genre}).

## Scene Brief: {scene_id}

{scene_block}

{dep_block}

{voice_guide}

{char_block}

{craft_block}

{task_block}
"""
```

to:

```python
    return f"""You are drafting a scene for "{title}" ({genre}).

## Scene Brief: {scene_id}

{scene_block}

{dep_block}

{state_block}

{voice_guide}

{char_block}

{craft_block}

{task_block}
"""
```

- [ ] **Step 6: Add physical state constraint to task block**

In `scripts/lib/python/storyforge/prompts.py`, in the coaching_level == 'full' task block (around line 1015-1020), after the line about knowledge_out, add:

```python
- Acknowledge all action-gating physical states — characters cannot use injured limbs, don't have lost equipment
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: All PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/python/storyforge/prompts.py tests/test-physical-state.sh
git commit -m "Add physical state context to drafting prompts"
git push
```

---

### Task 7: Add physical state to elaboration briefs prompt

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts_elaborate.py:401-442`
- Modify: `tests/test-physical-state.sh`

- [ ] **Step 1: Add elaboration prompt test**

Append to `tests/test-physical-state.sh`:

```bash
# ============================================================================
# Elaboration: briefs prompt includes physical state instructions
# ============================================================================

echo "--- elaborate: briefs prompt includes physical state instructions ---"

RESULT=$(python3 -c "
${PY}
from storyforge.prompts_elaborate import build_briefs_prompt
prompt = build_briefs_prompt('${FIXTURE_DIR}', '${PLUGIN_DIR}')
has_psi = 'physical_state_in' in prompt
has_pso = 'physical_state_out' in prompt
has_header = 'physical_state_in|physical_state_out' in prompt
print('has_instructions' if (has_psi and has_pso) else 'missing_instructions')
print('has_header' if has_header else 'missing_header')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "has_instructions" "elaborate: briefs prompt has physical state field instructions"
assert_contains "$RESULT" "has_header" "elaborate: briefs CSV header includes physical state columns"
assert_contains "$RESULT" "ok" "elaborate: build_briefs_prompt runs without error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: Fails — `missing_instructions` and `missing_header`.

- [ ] **Step 3: Add physical state field instructions to briefs prompt**

In `scripts/lib/python/storyforge/prompts_elaborate.py`, in `build_briefs_prompt`, after the `knowledge_out` instruction (line 411), add:

```
- **physical_state_in**: Semicolon-separated state IDs that on-stage characters carry INTO this scene. Use EXACT IDs from prior scenes' physical_state_out. Only track states that affect capability, appearance, or equipment — injuries, items gained/lost, abilities changed, visible changes, fatigue. Not temporary emotions or scene-local conditions.
- **physical_state_out**: physical_state_in plus 0-2 NEW states acquired during this scene, minus any states that resolve during this scene.
```

- [ ] **Step 4: Add physical state columns to CSV header in output format**

In `scripts/lib/python/storyforge/prompts_elaborate.py`, change the briefs-csv header (line 422) from:

```
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
```

to:

```
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow|physical_state_in|physical_state_out
```

- [ ] **Step 5: Add physical state rules**

In `scripts/lib/python/storyforge/prompts_elaborate.py`, in the Rules section (after line 437), add:

```
- physical_state_in must reference IDs established in prior scenes' physical_state_out
- Target 0-2 state changes per scene. A full novel should have 15-40 total state entries.
- States persist until explicitly resolved — do not silently drop them
- continuity_deps should also list scenes whose physical_state_out this scene needs
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_elaborate.py tests/test-physical-state.sh
git commit -m "Add physical state to elaboration briefs prompt"
git push
```

---

### Task 8: Add physical state fix prompt

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts_elaborate.py:646-709`
- Modify: `tests/test-physical-state.sh`

- [ ] **Step 1: Add fix prompt test**

Append to `tests/test-physical-state.sh`:

```bash
# ============================================================================
# Fix prompt: physical state
# ============================================================================

echo "--- fix prompt: builds without error ---"

RESULT=$(python3 -c "
${PY}
from storyforge.prompts_elaborate import build_physical_state_fix_prompt
prompt = build_physical_state_fix_prompt(
    'act2-sc03',
    '${FIXTURE_DIR}',
    '${FIXTURE_DIR}/scenes',
    {'archive-key-dorren', 'exhaustion-tessa', 'sprained-ankle-tessa'},
)
has_available = 'archive-key-dorren' in prompt
has_format = 'physical_state_in|physical_state_out' in prompt
print('has_available' if has_available else 'no_available')
print('has_format' if has_format else 'no_format')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "has_available" "fix prompt: shows available states"
assert_contains "$RESULT" "has_format" "fix prompt: specifies output format"
assert_contains "$RESULT" "ok" "fix prompt: builds without error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: Fails — `build_physical_state_fix_prompt` not defined.

- [ ] **Step 3: Implement build_physical_state_fix_prompt**

In `scripts/lib/python/storyforge/prompts_elaborate.py`, after `build_knowledge_fix_prompt` (after line 709), add:

```python
def build_physical_state_fix_prompt(
    scene_id: str,
    project_dir: str,
    scenes_dir: str,
    available_states: set,
) -> str:
    """Build a prompt to fix physical_state_in/physical_state_out for one scene.

    Args:
        scene_id: The scene to fix.
        project_dir: Path to the book project.
        scenes_dir: Path to the scenes/ directory with prose files.
        available_states: Set of exact state IDs from all prior scenes' physical_state_out.

    Returns:
        Prompt string for Claude.
    """
    from .elaborate import get_scene

    ref_dir = os.path.join(project_dir, 'reference')
    scene_data = get_scene(scene_id, ref_dir)

    # Read prose excerpt
    prose_path = os.path.join(scenes_dir, f'{scene_id}.md')
    prose = _read_file(prose_path)
    if prose:
        words = prose.split()
        if len(words) > 500:
            prose = ' '.join(words[:500]) + '\n[... truncated ...]'

    current_psi = scene_data.get('physical_state_in', '') if scene_data else ''
    current_pso = scene_data.get('physical_state_out', '') if scene_data else ''

    on_stage = scene_data.get('on_stage', '') if scene_data else ''

    sorted_states = sorted(available_states) if available_states else ['(none yet — no prior physical states established)']

    return f"""You are fixing the physical state chain for a scene in a novel. The physical_state_in field must use EXACT IDs from prior scenes' physical_state_out.

## Scene: {scene_id}
## On-stage characters: {on_stage}

### Prose Excerpt
{prose if prose else '(no prose available)'}

### Current Values (may have mismatches)
- physical_state_in: {current_psi}
- physical_state_out: {current_pso}

### Available Physical States (exact IDs from all prior scenes' physical_state_out)
{chr(10).join(f'- {s}' for s in sorted_states)}

## Instructions

1. Rewrite physical_state_in using ONLY state IDs from the available list above that are relevant to on-stage characters in this scene.
2. Rewrite physical_state_out as: the corrected physical_state_in PLUS any new states acquired during this scene, MINUS any states that resolve during this scene.
3. Only track states that affect what characters can do, how they look, or what they have.

## Output Format

Respond with ONLY a pipe-delimited CSV row. The header is:

id|physical_state_in|physical_state_out

Provide exactly one data row. Semicolon-separate multiple values within a field.
No explanation. No markdown fencing. Just the header line and the data line.
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_elaborate.py tests/test-physical-state.sh
git commit -m "Add physical state fix prompt for chain repair"
git push
```

---

### Task 9: Add physical state extraction (Phase 3c)

**Files:**
- Modify: `scripts/lib/python/storyforge/extract.py:355-428`
- Modify: `tests/test-physical-state.sh`

- [ ] **Step 1: Add extraction tests**

Append to `tests/test-physical-state.sh`:

```bash
# ============================================================================
# Extraction: Phase 3c physical state
# ============================================================================

echo "--- extract: build_physical_state_prompt runs ---"

RESULT=$(python3 -c "
${PY}
from storyforge.extract import build_physical_state_prompt

prompt = build_physical_state_prompt(
    scene_id='act1-sc01',
    scene_text='Dorren reviewed the maps carefully.',
    skeleton={'pov': 'Dorren Hayle', 'on_stage': 'Dorren Hayle;Tessa Merrin'},
    prior_states={},
    prior_scene_summaries=[],
)
has_instructions = 'PHYSICAL_STATE_IN' in prompt
has_categories = 'injury' in prompt and 'equipment' in prompt
print('has_instructions' if has_instructions else 'no_instructions')
print('has_categories' if has_categories else 'no_categories')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "has_instructions" "extract: prompt has output labels"
assert_contains "$RESULT" "has_categories" "extract: prompt lists categories"
assert_contains "$RESULT" "ok" "extract: build_physical_state_prompt runs"

echo "--- extract: parse_physical_state_response ---"

RESULT=$(python3 -c "
${PY}
from storyforge.extract import parse_physical_state_response

response = '''PHYSICAL_STATE_IN: archive-key-dorren
PHYSICAL_STATE_OUT: archive-key-dorren;sprained-ankle-tessa
NEW_STATES: sprained-ankle-tessa|Tessa Merrin|right ankle sprained|injury|true
RESOLVED_STATES: '''

result = parse_physical_state_response(response, 'act2-sc02')
print(f\"id={result['id']}\")
print(f\"psi={result.get('physical_state_in', '')}\")
print(f\"pso={result.get('physical_state_out', '')}\")
print(f\"new={len(result.get('_new_states', []))}\")
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "id=act2-sc02" "extract: parse sets scene id"
assert_contains "$RESULT" "psi=archive-key-dorren" "extract: parse extracts physical_state_in"
assert_contains "$RESULT" "pso=archive-key-dorren;sprained-ankle-tessa" "extract: parse extracts physical_state_out"
assert_contains "$RESULT" "new=1" "extract: parse extracts new states"
assert_contains "$RESULT" "ok" "extract: parse runs without error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: Fails — functions not defined.

- [ ] **Step 3: Implement build_physical_state_prompt and parse_physical_state_response**

In `scripts/lib/python/storyforge/extract.py`, after `parse_knowledge_response` (after line 428), add:

```python
# ============================================================================
# Phase 3c: Physical state chain (sequential)
# ============================================================================

def build_physical_state_prompt(scene_id: str, scene_text: str,
                                skeleton: dict[str, str],
                                prior_states: dict[str, set],
                                prior_scene_summaries: list[str],
                                registries_text: str = '') -> str:
    """Build prompt for Phase 3c: extract physical_state_in, physical_state_out.
    Must be called sequentially."""
    on_stage = skeleton.get('on_stage', skeleton.get('pov', 'unknown'))
    prior_context = '\n'.join(prior_scene_summaries[-10:]) if prior_scene_summaries else '(first scene)'

    # Format prior states per character
    if prior_states:
        state_lines = []
        for char, states in sorted(prior_states.items()):
            state_lines.append(f"  {char}: {'; '.join(sorted(states))}")
        prior_states_text = '\n'.join(state_lines)
    else:
        prior_states_text = '(no prior physical states established)'

    registries_section = f'\n{registries_text}\n' if registries_text else ''

    return f"""Track the physical state of characters through this scene.

## On-stage characters: {on_stage}

## Active physical states entering this scene:
{prior_states_text}

## Recent prior scenes (for context):
{prior_context}

## Scene: {scene_id}
{scene_text}
{registries_section}
## Instructions

Extract physical state changes for on-stage characters. Only track states that affect what characters can do, how they look, or what they have.

Categories: injury, equipment, ability, appearance, fatigue.

Litmus test: Would a drafter who knows about this state write a *different scene* than one who doesn't? If removing the state wouldn't change the prose, don't track it.

Too granular (don't): "Character frowns", "Hair is windblown", "Feels cold"
Right level: "Left arm broken, splinted", "Carrying the stolen compass", "Exhausted after 36 hours awake"

Output each field on its own labeled line:

PHYSICAL_STATE_IN: [semicolon-separated state IDs active at START — carry forward from prior states for on-stage characters only]
PHYSICAL_STATE_OUT: [semicolon-separated state IDs active at END — state_in plus new states acquired, minus states resolved]
NEW_STATES: [one per line if any: id|character|description|category|action_gating — use kebab-case IDs]
RESOLVED_STATES: [semicolon-separated state IDs that resolve during this scene, or empty if none]

IMPORTANT: Use EXACT state IDs for carry-forward. New states need new IDs in kebab-case (e.g., broken-arm-marcus, has-compass-elena)."""


def parse_physical_state_response(response: str, scene_id: str) -> dict:
    """Parse Phase 3c response.

    Returns:
        Dict with keys: id, physical_state_in, physical_state_out,
        _new_states (list of dicts), _resolved (list of IDs).
    """
    result = {'id': scene_id, '_new_states': [], '_resolved': []}
    label_map = {
        'PHYSICAL_STATE_IN': 'physical_state_in',
        'PHYSICAL_STATE_OUT': 'physical_state_out',
    }

    lines = response.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = re.match(r'^([A-Z_]+):\s*(.*)', line)
        if match:
            label = match.group(1)
            value = match.group(2).strip()
            if label in label_map and value:
                result[label_map[label]] = value
            elif label == 'NEW_STATES':
                # First new state may be on this line
                if value:
                    parts = value.split('|')
                    if len(parts) >= 4:
                        result['_new_states'].append({
                            'id': parts[0].strip(),
                            'character': parts[1].strip(),
                            'description': parts[2].strip(),
                            'category': parts[3].strip(),
                            'action_gating': parts[4].strip() if len(parts) > 4 else 'false',
                        })
                # Check subsequent lines for more new states
                i += 1
                while i < len(lines):
                    nline = lines[i].strip()
                    if not nline or re.match(r'^[A-Z_]+:', nline):
                        break
                    nparts = nline.split('|')
                    if len(nparts) >= 4:
                        result['_new_states'].append({
                            'id': nparts[0].strip(),
                            'character': nparts[1].strip(),
                            'description': nparts[2].strip(),
                            'category': nparts[3].strip(),
                            'action_gating': nparts[4].strip() if len(nparts) > 4 else 'false',
                        })
                    i += 1
                continue
            elif label == 'RESOLVED_STATES' and value:
                result['_resolved'] = [s.strip() for s in value.split(';') if s.strip()]
        i += 1

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/extract.py tests/test-physical-state.sh
git commit -m "Add physical state extraction (Phase 3c)"
git push
```

---

### Task 10: Add physical state reconciliation domain

**Files:**
- Modify: `scripts/lib/python/storyforge/reconcile.py:137-151,302-347,354-360,427-453,480-531`
- Modify: `tests/test-physical-state.sh`

- [ ] **Step 1: Add reconciliation tests**

Append to `tests/test-physical-state.sh`:

```bash
# ============================================================================
# Reconciliation: physical-states domain
# ============================================================================

echo "--- reconcile: collect physical state chain ---"

RESULT=$(python3 -c "
${PY}
from storyforge.reconcile import _collect_physical_state_chain

chain = _collect_physical_state_chain('${FIXTURE_DIR}/reference')
print(f'entries={len(chain)}')
for sid, seq, psi, pso in chain:
    print(f'{sid}: in={psi} out={pso}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "reconcile: _collect_physical_state_chain runs"
assert_contains "$RESULT" "entries=" "reconcile: returns chain entries"

echo "--- reconcile: build_registry_prompt for physical-states ---"

RESULT=$(python3 -c "
${PY}
from storyforge.reconcile import build_registry_prompt

prompt = build_registry_prompt('physical-states', '${FIXTURE_DIR}/reference')
has_chain = 'IN:' in prompt and 'OUT:' in prompt
has_instructions = 'id|character|description|category' in prompt
print('has_chain' if has_chain else 'no_chain')
print('has_instructions' if has_instructions else 'no_instructions')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "has_chain" "reconcile: prompt includes state chain"
assert_contains "$RESULT" "has_instructions" "reconcile: prompt specifies registry format"
assert_contains "$RESULT" "ok" "reconcile: build_registry_prompt runs for physical-states"

echo "--- reconcile: parse_registry_response for physical-states ---"

RESULT=$(python3 -c "
${PY}
from storyforge.reconcile import parse_registry_response

response = '''id|character|description|category|acquired|resolves|action_gating
broken-arm|Marcus|left arm broken|injury|scene-5|scene-12|true

UPDATES
UPDATE: scene-5 | |broken-arm
UPDATE: scene-6 | broken-arm|broken-arm'''

rows, updates = parse_registry_response(response, 'physical-states')
print(f'rows={len(rows)}')
print(f'updates={len(updates)}')
if rows:
    print(f'first_id={rows[0][\"id\"]}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "rows=1" "reconcile: parses registry rows"
assert_contains "$RESULT" "updates=2" "reconcile: parses update lines"
assert_contains "$RESULT" "first_id=broken-arm" "reconcile: registry row has correct id"
assert_contains "$RESULT" "ok" "reconcile: parse_registry_response works for physical-states"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: Fails — functions not defined for physical-states domain.

- [ ] **Step 3: Add _collect_physical_state_chain to reconcile.py**

In `scripts/lib/python/storyforge/reconcile.py`, after `_collect_knowledge_chain` (after line 151), add:

```python
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
```

- [ ] **Step 4: Add physical-states case to build_registry_prompt**

In `scripts/lib/python/storyforge/reconcile.py`, in `build_registry_prompt`, before the `else: raise ValueError` line (line 346), add:

```python
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
```

- [ ] **Step 5: Add physical-states to _REGISTRY_COLUMNS**

In `scripts/lib/python/storyforge/reconcile.py`, in `_REGISTRY_COLUMNS` (around line 354-360), add:

```python
    'physical-states': ['id', 'character', 'description', 'category', 'acquired', 'resolves', 'action_gating'],
```

- [ ] **Step 6: Add physical-states to _DOMAIN_TO_REGISTRY**

In `scripts/lib/python/storyforge/reconcile.py`, in `_DOMAIN_TO_REGISTRY` (around line 427-433), add:

```python
    'physical-states': 'physical-states.csv',
```

- [ ] **Step 7: Add physical-states to _DOMAIN_TARGETS**

In `scripts/lib/python/storyforge/reconcile.py`, in `_DOMAIN_TARGETS` (around line 436-453), add:

```python
    'physical-states': [
        ('scene-briefs.csv', ['physical_state_in', 'physical_state_out']),
    ],
```

- [ ] **Step 8: Add physical-states case to apply_updates**

In `scripts/lib/python/storyforge/reconcile.py`, in `apply_updates`, before `# Other domains have no update lines` (line 530), add:

```python
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
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: All PASS.

- [ ] **Step 10: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All suites pass.

- [ ] **Step 11: Commit**

```bash
git add scripts/lib/python/storyforge/reconcile.py tests/test-physical-state.sh
git commit -m "Add physical-states reconciliation domain"
git push
```

---

### Task 11: Add physical state cleanup (fuzzy matching)

**Files:**
- Modify: `scripts/lib/python/storyforge/extract.py:593-667`
- Modify: `tests/test-physical-state.sh`

- [ ] **Step 1: Add cleanup test**

Append to `tests/test-physical-state.sh`:

```bash
# ============================================================================
# Cleanup: physical state fuzzy matching
# ============================================================================

echo "--- cleanup: normalizes physical state wording ---"

RESULT=$(python3 -c "
${PY}
import os, tempfile, shutil
from storyforge.extract import cleanup_physical_states
from storyforge.elaborate import _read_csv, _write_csv, _read_csv_as_map, _FILE_MAP

tmpdir = tempfile.mkdtemp()
ref = os.path.join(tmpdir, 'reference')
shutil.copytree('${FIXTURE_DIR}/reference', ref)

# Inject a slightly-wrong state ID in physical_state_in
briefs_path = os.path.join(ref, 'scene-briefs.csv')
rows = _read_csv(briefs_path)
for r in rows:
    if r['id'] == 'act2-sc03':
        # 'archive-key-doren' is a typo of 'archive-key-dorren'
        r['physical_state_in'] = 'archive-key-doren;exhaustion-tessa'
_write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])

fixes = cleanup_physical_states(ref)
print(f'fixes={len(fixes)}')
if fixes:
    print(f'fixed_field={fixes[0][\"field\"]}')

# Verify the fix was written
briefs = _read_csv_as_map(briefs_path)
fixed_val = briefs['act2-sc03'].get('physical_state_in', '')
has_correct = 'archive-key-dorren' in fixed_val
print('corrected' if has_correct else 'not_corrected')
print('ok')

shutil.rmtree(tmpdir)
" 2>/dev/null)

assert_contains "$RESULT" "fixes=1" "cleanup: found 1 fix"
assert_contains "$RESULT" "corrected" "cleanup: wrote corrected value"
assert_contains "$RESULT" "ok" "cleanup: runs without error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: Fails — `cleanup_physical_states` not defined.

- [ ] **Step 3: Implement cleanup_physical_states**

In `scripts/lib/python/storyforge/extract.py`, after `cleanup_knowledge` (after line 667), add:

```python
def cleanup_physical_states(ref_dir: str) -> list[dict]:
    """Normalize physical state IDs so physical_state_in matches prior physical_state_out.

    Uses fuzzy matching: if a physical_state_in ID is >70% similar to a
    physical_state_out ID from a prior scene, replace it with the exact ID.

    Returns a list of fixes applied.
    """
    from .elaborate import _read_csv_as_map, _write_csv, _FILE_MAP

    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda s: int(scenes_map[s].get('seq', 0)))

    fixes = []
    state_pool = set()

    for sid in sorted_ids:
        brief = briefs_map.get(sid, {})
        state_in = brief.get('physical_state_in', '').strip()

        if state_in and state_pool:
            states_in = [s.strip() for s in state_in.split(';') if s.strip()]
            new_states = []
            changed = False

            for state in states_in:
                if state in state_pool:
                    new_states.append(state)
                    continue

                best_match = None
                best_score = 0.0
                state_lower = state.lower()
                for pool_state in state_pool:
                    score = _similarity(state_lower, pool_state.lower())
                    if score > best_score:
                        best_score = score
                        best_match = pool_state

                if best_match and best_score >= 0.7:
                    new_states.append(best_match)
                    changed = True
                else:
                    new_states.append(state)

            if changed:
                old_val = state_in
                new_val = ';'.join(new_states)
                briefs_map[sid]['physical_state_in'] = new_val
                fixes.append({
                    'scene_id': sid,
                    'field': 'physical_state_in',
                    'old_value': old_val[:80] + '...' if len(old_val) > 80 else old_val,
                    'new_value': new_val[:80] + '...' if len(new_val) > 80 else new_val,
                })

        state_out = brief.get('physical_state_out', '').strip()
        if state_out:
            for state in state_out.split(';'):
                state = state.strip()
                if state:
                    state_pool.add(state)

    if fixes:
        ordered = sorted(briefs_map.values(), key=lambda r: r.get('id', ''))
        _write_csv(os.path.join(ref_dir, 'scene-briefs.csv'), ordered, _FILE_MAP['scene-briefs.csv'])

    return fixes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tests/run-tests.sh tests/test-physical-state.sh`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/extract.py tests/test-physical-state.sh
git commit -m "Add physical state cleanup with fuzzy matching"
git push
```

---

### Task 12: Bump version and final verification

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All suites pass, including the new `test-physical-state.sh`.

- [ ] **Step 2: Bump version**

In `.claude-plugin/plugin.json`, change version from `"0.62.0"` to `"0.63.0"` (minor bump for new feature).

- [ ] **Step 3: Commit and push**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 0.63.0 — add physical state tracking"
git push
```
