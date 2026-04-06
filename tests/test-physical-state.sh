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
