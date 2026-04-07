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

# ============================================================================
# write_registry
# ============================================================================

REG_DIR="${TMPDIR}/reg-write-test/reference"
mkdir -p "$REG_DIR"

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import write_registry
from storyforge.elaborate import _read_csv_as_map

rows = [
    {'id': 'kael', 'name': 'Kael Davreth', 'role': 'protagonist', 'aliases': 'Kael;kael'},
    {'id': 'sera', 'name': 'Sera Vasht', 'role': 'supporting', 'aliases': 'Sera'},
]
write_registry('${REG_DIR}', 'characters', rows)

m = _read_csv_as_map('${REG_DIR}/characters.csv')
print(f'count={len(m)}')
print(f'name={m[\"kael\"][\"name\"]}')
print(f'role={m[\"sera\"][\"role\"]}')
")
assert_contains "$RESULT" "count=2" "write_registry: writes 2 rows"
assert_contains "$RESULT" "name=Kael Davreth" "write_registry: preserves name"
assert_contains "$RESULT" "role=supporting" "write_registry: preserves role"
rm -rf "${TMPDIR}/reg-write-test"

# ============================================================================
# apply_updates — mice-threads
# ============================================================================

UPD_DIR="${TMPDIR}/upd-test/reference"
mkdir -p "$UPD_DIR"
cat > "${UPD_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
s01|test|action|flat|truth|+/-|revelation|A|A|+inquiry:old-thread
s02|test|action|flat|truth|+/-|revelation|A|A|-inquiry:old-thread
CSV

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import apply_updates
from storyforge.elaborate import _read_csv_as_map

updates = [('s01', '+inquiry:new-thread'), ('s02', '-inquiry:new-thread')]
applied = apply_updates('${UPD_DIR}', 'mice-threads', updates)
print(f'applied={applied}')

m = _read_csv_as_map('${UPD_DIR}/scene-intent.csv')
print(f'mice1={m[\"s01\"][\"mice_threads\"]}')
print(f'mice2={m[\"s02\"][\"mice_threads\"]}')
")
assert_contains "$RESULT" "applied=2" "apply_updates: mice-threads applies 2 updates"
assert_contains "$RESULT" "mice1=+inquiry:new-thread" "apply_updates: mice-threads s01 updated"
assert_contains "$RESULT" "mice2=-inquiry:new-thread" "apply_updates: mice-threads s02 updated"
rm -rf "${TMPDIR}/upd-test"

# ============================================================================
# apply_updates — knowledge
# ============================================================================

KUPD_DIR="${TMPDIR}/kupd-test/reference"
mkdir -p "$KUPD_DIR"
cat > "${KUPD_DIR}/scene-briefs.csv" <<'CSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
s01|g|c|yes|cr|d|old-in|old-out|a|d|e|m||false
s02|g|c|yes|cr|d|old-in2|old-out2|a|d|e|m||false
CSV

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import apply_updates
from storyforge.elaborate import _read_csv_as_map

updates = [('s01', 'fact-a;fact-b | fact-c'), ('s02', 'fact-d | fact-e;fact-f')]
applied = apply_updates('${KUPD_DIR}', 'knowledge', updates)
print(f'applied={applied}')

m = _read_csv_as_map('${KUPD_DIR}/scene-briefs.csv')
print(f'kin1={m[\"s01\"][\"knowledge_in\"]}')
print(f'kout1={m[\"s01\"][\"knowledge_out\"]}')
print(f'kin2={m[\"s02\"][\"knowledge_in\"]}')
")
assert_contains "$RESULT" "applied=2" "apply_updates: knowledge applies 2 updates"
assert_contains "$RESULT" "kin1=fact-a;fact-b" "apply_updates: knowledge s01 knowledge_in"
assert_contains "$RESULT" "kout1=fact-c" "apply_updates: knowledge s01 knowledge_out"
assert_contains "$RESULT" "kin2=fact-d" "apply_updates: knowledge s02 knowledge_in"
rm -rf "${TMPDIR}/kupd-test"

# ============================================================================
# apply_updates — other domains return 0
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import apply_updates
applied = apply_updates('/tmp/fake', 'characters', [('s01', 'val')])
print(f'applied={applied}')
")
assert_contains "$RESULT" "applied=0" "apply_updates: characters returns 0 (no updates)"

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

# ============================================================================
# apply_registry_normalization — locations
# ============================================================================

LNORM_DIR="${TMPDIR}/lnorm-test/reference"
mkdir -p "$LNORM_DIR"
cat > "${LNORM_DIR}/scenes.csv" <<'CSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
s01|1|One|1|A|The Hold|1|morning|1 hour|action|drafted|1000|2000
s02|2|Two|1|A|the hold|1|afternoon|1 hour|action|drafted|1000|2000
s03|3|Three|1|A|Thornwall Market|2|morning|1 hour|action|drafted|1000|2000
CSV
cat > "${LNORM_DIR}/locations.csv" <<'CSV'
id|name|aliases
the-hold|The Hold|The Hold;the hold;Hold
thornwall-market|Thornwall Market|Thornwall Market
CSV

RESULT=$(python3 -c "
${PY})
from storyforge.reconcile import apply_registry_normalization
changed = apply_registry_normalization('locations', '${LNORM_DIR}')
print(f'changed={changed}')

from storyforge.elaborate import _read_csv_as_map
scenes = _read_csv_as_map('${LNORM_DIR}/scenes.csv')
print(f'loc1={scenes[\"s01\"][\"location\"]}')
print(f'loc2={scenes[\"s02\"][\"location\"]}')
print(f'loc3={scenes[\"s03\"][\"location\"]}')
")
assert_contains "$RESULT" "loc1=the-hold" "apply_registry_normalization: The Hold → the-hold"
assert_contains "$RESULT" "loc2=the-hold" "apply_registry_normalization: the hold → the-hold"
assert_contains "$RESULT" "loc3=thornwall-market" "apply_registry_normalization: Thornwall Market → thornwall-market"
rm -rf "${TMPDIR}/lnorm-test"

# ============================================================================
# MICE thread normalization: bare +name format with type injection
# ============================================================================

echo "--- mice: normalize bare +name using registry type ---"

RESULT=$(python3 -c "
${PY})
from storyforge.enrich import normalize_mice_threads, load_mice_registry

# Build a mock registry in a temp file
import tempfile, os
tmpdir = tempfile.mkdtemp()
reg_path = os.path.join(tmpdir, 'mice-threads.csv')
with open(reg_path, 'w') as f:
    f.write('id|name|type|aliases\n')
    f.write('understory|The Understory|milieu|hidden world\n')
    f.write('vanishings|The Vanishings|inquiry|disappearances\n')
    f.write('zara-identity|Zara Identity|character|\n')

alias_map, type_map = load_mice_registry(reg_path)

# Bare +name should get type injected
result = normalize_mice_threads('+understory', alias_map, type_map)
print(f'bare_open={result}')

# Bare -name should get type injected
result = normalize_mice_threads('-vanishings', alias_map, type_map)
print(f'bare_close={result}')

# Bare name without +/- should get type injected
result = normalize_mice_threads('zara-identity', alias_map, type_map)
print(f'bare_mention={result}')

# Multiple bare entries
result = normalize_mice_threads('+understory;-vanishings;zara-identity', alias_map, type_map)
print(f'multi={result}')

import shutil; shutil.rmtree(tmpdir)
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "bare_open=+understory" "mice: bare +name stays bare"
assert_contains "$RESULT" "bare_close=-vanishings" "mice: bare -name stays bare"
assert_contains "$RESULT" "bare_mention=zara-identity" "mice: bare mention stays bare"
assert_contains "$RESULT" "multi=+understory;-vanishings;zara-identity" "mice: multiple bare entries normalized"
assert_contains "$RESULT" "ok" "mice: bare normalization runs"

echo "--- mice: existing +type:name preserved ---"

RESULT=$(python3 -c "
${PY})
from storyforge.enrich import normalize_mice_threads, load_mice_registry
import tempfile, os
tmpdir = tempfile.mkdtemp()
reg_path = os.path.join(tmpdir, 'mice-threads.csv')
with open(reg_path, 'w') as f:
    f.write('id|name|type|aliases\n')
    f.write('understory|The Understory|milieu|\n')
alias_map, type_map = load_mice_registry(reg_path)

# Already has type — should be preserved
result = normalize_mice_threads('+milieu:understory', alias_map, type_map)
print(f'typed={result}')

# Wrong type — should be corrected from registry
result = normalize_mice_threads('+inquiry:understory', alias_map, type_map)
print(f'corrected={result}')

import shutil; shutil.rmtree(tmpdir)
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "typed=+understory" "mice: typed input normalized to bare"
assert_contains "$RESULT" "corrected=+understory" "mice: wrong type stripped to bare"
assert_contains "$RESULT" "ok" "mice: typed normalization runs"

echo "--- mice: alias resolution works with bare names ---"

RESULT=$(python3 -c "
${PY})
from storyforge.enrich import normalize_mice_threads, load_mice_registry
import tempfile, os
tmpdir = tempfile.mkdtemp()
reg_path = os.path.join(tmpdir, 'mice-threads.csv')
with open(reg_path, 'w') as f:
    f.write('id|name|type|aliases\n')
    f.write('understory|The Understory|milieu|hidden world;the magical chicago\n')
alias_map, type_map = load_mice_registry(reg_path)

# Alias should resolve to canonical id with type
result = normalize_mice_threads('+hidden world', alias_map, type_map)
print(f'alias={result}')

import shutil; shutil.rmtree(tmpdir)
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "alias=+understory" "mice: alias resolves to bare canonical name"
assert_contains "$RESULT" "ok" "mice: alias resolution runs"

echo "--- mice: normalizer outputs bare +name format ---"

RESULT=$(python3 -c "
${PY})
from storyforge.enrich import normalize_mice_threads, load_mice_registry
import tempfile, os
tmpdir = tempfile.mkdtemp()
reg_path = os.path.join(tmpdir, 'mice-threads.csv')
with open(reg_path, 'w') as f:
    f.write('id|name|type|aliases\n')
    f.write('understory|The Understory|milieu|\n')
alias_map, type_map = load_mice_registry(reg_path)

# Typed input should output bare
result = normalize_mice_threads('+milieu:understory', alias_map, type_map)
print(f'stripped={result}')

# Bare input should stay bare
result = normalize_mice_threads('+understory', alias_map, type_map)
print(f'bare={result}')

import shutil; shutil.rmtree(tmpdir)
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "stripped=+understory" "mice: normalizer strips type prefix"
assert_contains "$RESULT" "bare=+understory" "mice: normalizer keeps bare format"
assert_contains "$RESULT" "ok" "mice: bare output runs"
