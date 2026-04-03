#!/bin/bash
# test-schema.sh — Tests for CSV schema validation

# Tests use $FIXTURE_DIR, $PROJECT_DIR, $PLUGIN_DIR, $TMPDIR
PYTHON_DIR="${PLUGIN_DIR}/scripts/lib/python"

# ============================================================================
# Enum validation
# ============================================================================

echo "--- enum: valid values ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import _check_enum, VALID_TYPES, VALID_TIMES, VALID_ACTION_SEQUEL, VALID_OUTCOMES, VALID_STATUSES, VALID_VALUE_SHIFTS, VALID_TURNING_POINTS
print(_check_enum('character', VALID_TYPES))
print(_check_enum('morning', VALID_TIMES))
print(_check_enum('action', VALID_ACTION_SEQUEL))
print(_check_enum('yes-but', VALID_OUTCOMES))
print(_check_enum('drafted', VALID_STATUSES))
print(_check_enum('+/-', VALID_VALUE_SHIFTS))
print(_check_enum('revelation', VALID_TURNING_POINTS))
" 2>/dev/null)

assert_equals "True
True
True
True
True
True
True" "$RESULT" "enum: all valid values accepted"

echo "--- enum: invalid values ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import _check_enum, VALID_TYPES, VALID_ACTION_SEQUEL, VALID_OUTCOMES, VALID_VALUE_SHIFTS
print(_check_enum('setup', VALID_TYPES))
print(_check_enum('scene', VALID_ACTION_SEQUEL))
print(_check_enum('maybe', VALID_OUTCOMES))
print(_check_enum('positive', VALID_VALUE_SHIFTS))
" 2>/dev/null)

assert_equals "False
False
False
False" "$RESULT" "enum: invalid values rejected"

echo "--- enum: case insensitive ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import _check_enum, VALID_TYPES
print(_check_enum('CHARACTER', VALID_TYPES))
print(_check_enum('Character', VALID_TYPES))
" 2>/dev/null)

assert_equals "True
True" "$RESULT" "enum: case insensitive"

echo "--- enum: value_shift all valid patterns ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import _check_enum, VALID_VALUE_SHIFTS
for v in ['+/-', '-/+', '+/++', '-/--', '+/+', '-/-']:
    print(_check_enum(v, VALID_VALUE_SHIFTS))
" 2>/dev/null)

assert_equals "True
True
True
True
True
True" "$RESULT" "enum: all six value_shift patterns valid"

# ============================================================================
# Integer validation
# ============================================================================

echo "--- integer ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import _check_integer
print(_check_integer('42'))
print(_check_integer('0'))
print(_check_integer('-1'))
print(_check_integer('hello'))
print(_check_integer('3.5'))
print(_check_integer(''))
" 2>/dev/null)

assert_equals "True
True
True
False
False
False" "$RESULT" "integer: accepts ints, rejects non-ints"

# ============================================================================
# Boolean validation
# ============================================================================

echo "--- boolean ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import _check_boolean
print(_check_boolean('true'))
print(_check_boolean('false'))
print(_check_boolean('True'))
print(_check_boolean(''))
print(_check_boolean('yes'))
print(_check_boolean('1'))
" 2>/dev/null)

assert_equals "True
True
True
True
False
False" "$RESULT" "boolean: accepts true/false/empty, rejects others"

# ============================================================================
# Registry validation
# ============================================================================

echo "--- registry ---"

CHARACTERS_CSV="${FIXTURE_DIR}/reference/characters.csv"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import _check_registry
from storyforge.enrich import load_alias_map
amap = load_alias_map('${CHARACTERS_CSV}')
# Valid: id, name, alias — all resolve
print(_check_registry('dorren-hayle', amap, False))
print(_check_registry('Dorren Hayle', amap, False))
print(_check_registry('Dorren', amap, False))
# Invalid
print(_check_registry('Nobody', amap, False))
# Array valid
print(_check_registry('Dorren;Tessa;Pell', amap, True))
# Array with invalid entry
print(_check_registry('Dorren;Nobody;Pell', amap, True))
" 2>/dev/null)

assert_equals "[]
[]
[]
['Nobody']
[]
['Nobody']" "$RESULT" "registry: accepts ids/names/aliases, rejects unknowns"

echo "--- registry: empty map skips ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import _check_registry
print(_check_registry('anything', {}, False))
" 2>/dev/null)

assert_equals "[]" "$RESULT" "registry: empty map returns no errors"

# ============================================================================
# validate_schema — end-to-end on fixtures
# ============================================================================

echo "--- validate_schema: fixtures ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.schema import validate_schema
report = validate_schema('${FIXTURE_DIR}/reference', '${FIXTURE_DIR}')
print(json.dumps(report))
" 2>/dev/null)

# Should have some passed and some failed (fixtures have full names in some fields,
# and locations like 'Eastern Ridge' not in locations.csv)
PASSED=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r['passed'])")
FAILED=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r['failed'])")
SKIPPED=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r['skipped'])")

assert_not_empty "$PASSED" "validate_schema: has passed count"
assert_not_empty "$FAILED" "validate_schema: has failed count"
assert_not_empty "$SKIPPED" "validate_schema: has skipped count"

# Passed should be > 0 (many valid cells)
RESULT=$(python3 -c "print(int('${PASSED}') > 0)")
assert_equals "True" "$RESULT" "validate_schema: some cells pass"

echo "--- validate_schema: without project_dir skips registry ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.schema import validate_schema
report = validate_schema('${FIXTURE_DIR}/reference')
# Without project_dir, registry columns are skipped
errors = [e for e in report['errors'] if e['constraint'] == 'registry']
print(len(errors))
" 2>/dev/null)

assert_equals "0" "$RESULT" "validate_schema: no registry errors without project_dir"

echo "--- validate_schema: catches bad enum ---"

# Create a temp project with a bad type value
SCHEMA_TMP="${TMPDIR}/schema-test"
mkdir -p "${SCHEMA_TMP}/reference"

echo "id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words" > "${SCHEMA_TMP}/reference/scenes.csv"
echo "sc-1|1|Test|1||||||setup|drafted|1000|1000" >> "${SCHEMA_TMP}/reference/scenes.csv"

echo "id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads" > "${SCHEMA_TMP}/reference/scene-intent.csv"
echo "sc-1|test||||||||||" >> "${SCHEMA_TMP}/reference/scene-intent.csv"

echo "id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow" > "${SCHEMA_TMP}/reference/scene-briefs.csv"
echo "sc-1|||||||||||||" >> "${SCHEMA_TMP}/reference/scene-briefs.csv"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.schema import validate_schema
report = validate_schema('${SCHEMA_TMP}/reference')
enum_errors = [e for e in report['errors'] if e['constraint'] == 'enum']
print(len(enum_errors))
if enum_errors:
    print(enum_errors[0]['column'])
    print(enum_errors[0]['value'])
" 2>/dev/null)

assert_equals "1
type
setup" "$RESULT" "validate_schema: catches invalid enum value"

echo "--- validate_schema: catches bad integer ---"

echo "id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words" > "${SCHEMA_TMP}/reference/scenes.csv"
echo "sc-1|one|Test|||||||||1000|" >> "${SCHEMA_TMP}/reference/scenes.csv"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.schema import validate_schema
report = validate_schema('${SCHEMA_TMP}/reference')
int_errors = [e for e in report['errors'] if e['constraint'] == 'integer']
print(len(int_errors))
if int_errors:
    print(int_errors[0]['column'])
" 2>/dev/null)

assert_equals "1
seq" "$RESULT" "validate_schema: catches non-integer seq"

rm -rf "$SCHEMA_TMP"

# ============================================================================
# MICE thread validation
# ============================================================================

echo "--- mice: normalization ---"

MICE_CSV="${FIXTURE_DIR}/reference/mice-threads.csv"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_mice_registry, normalize_mice_threads
alias_map, type_map = load_mice_registry('${MICE_CSV}')
# Alias resolves to canonical id
print(normalize_mice_threads('+inquiry:the map anomaly', alias_map, type_map))
# Type gets corrected from registry
print(normalize_mice_threads('+milieu:map-anomaly', alias_map, type_map))
# Multiple entries
print(normalize_mice_threads('+inquiry:the map anomaly;-milieu:the reaches', alias_map, type_map))
# Unknown name passes through
print(normalize_mice_threads('+event:unknown-thing', alias_map, type_map))
" 2>/dev/null)

assert_equals "+inquiry:map-anomaly
+inquiry:map-anomaly
+inquiry:map-anomaly;-milieu:uncharted-reaches
+event:unknown-thing" "$RESULT" "mice: normalization resolves aliases and corrects types"

echo "--- mice: schema validation ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.schema import _check_mice
from storyforge.enrich import load_mice_registry
alias_map, type_map = load_mice_registry('${MICE_CSV}')
# Valid entry
print(len(_check_mice('+inquiry:map-anomaly', alias_map, type_map)))
# Bad format
print(len(_check_mice('no-prefix:name', alias_map, type_map)))
# Bad type
print(len(_check_mice('+quest:map-anomaly', alias_map, type_map)))
# Unknown name
print(len(_check_mice('+inquiry:unknown-thread', alias_map, type_map)))
# Wrong type
print(len(_check_mice('+milieu:map-anomaly', alias_map, type_map)))
" 2>/dev/null)

assert_equals "0
1
1
1
1" "$RESULT" "mice: schema catches format, type, name, and type-mismatch errors"

echo "--- mice: empty and missing registry ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_mice_registry, normalize_mice_threads
# Missing file
alias_map, type_map = load_mice_registry('/nonexistent/mice-threads.csv')
print(len(alias_map))
# Normalization with empty map passes through
print(normalize_mice_threads('+inquiry:something', alias_map, type_map))
" 2>/dev/null)

assert_equals "0
+inquiry:something" "$RESULT" "mice: missing registry returns empty, normalization passes through"

# ============================================================================
# continuity_deps validation (scene ID cross-reference)
# ============================================================================

echo "--- scene_ids: valid deps ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.schema import validate_schema
report = validate_schema('${FIXTURE_DIR}/reference', '${FIXTURE_DIR}')
dep_errors = [e for e in report['errors'] if e['constraint'] == 'scene_ids']
print(len(dep_errors))
" 2>/dev/null)

assert_equals "0" "$RESULT" "scene_ids: fixture deps all resolve"

echo "--- scene_ids: catches bad dep ---"

DEPS_TMP="${TMPDIR}/deps-test"
mkdir -p "${DEPS_TMP}/reference"

echo "id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words" > "${DEPS_TMP}/reference/scenes.csv"
echo "sc-1|1|Test|||||||||1000|" >> "${DEPS_TMP}/reference/scenes.csv"
echo "sc-2|2|Test2|||||||||1000|" >> "${DEPS_TMP}/reference/scenes.csv"

echo "id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads" > "${DEPS_TMP}/reference/scene-intent.csv"
echo "sc-1||||||||||" >> "${DEPS_TMP}/reference/scene-intent.csv"
echo "sc-2||||||||||" >> "${DEPS_TMP}/reference/scene-intent.csv"

echo "id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow" > "${DEPS_TMP}/reference/scene-briefs.csv"
echo "sc-1||||||||||||sc-2|" >> "${DEPS_TMP}/reference/scene-briefs.csv"
echo "sc-2||||||||||||sc-1;nonexistent-scene|" >> "${DEPS_TMP}/reference/scene-briefs.csv"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.schema import validate_schema
report = validate_schema('${DEPS_TMP}/reference')
dep_errors = [e for e in report['errors'] if e['constraint'] == 'scene_ids']
print(len(dep_errors))
if dep_errors:
    print(dep_errors[0]['unresolved'][0])
" 2>/dev/null)

assert_equals "1
nonexistent-scene" "$RESULT" "scene_ids: catches nonexistent scene in deps"

rm -rf "$DEPS_TMP"
