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
    print(f\"{c['check']}: {'PASS' if c['passed'] else 'FAIL'}\")
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
found = any('nonexistent-state' in c.get('message', '') for c in phys_fails)
print('found_unknown' if found else 'not_found')

shutil.rmtree(tmpdir)
" 2>/dev/null)

assert_equals "found_unknown" "$RESULT" "validate: unknown physical state in physical_state_in is flagged"

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
