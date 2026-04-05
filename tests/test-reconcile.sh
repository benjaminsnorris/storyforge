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

# ============================================================================
# parse_registry_response — simple characters registry
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

# ============================================================================
# parse_registry_response — MICE threads with UPDATES
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
