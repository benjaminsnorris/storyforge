#!/bin/bash
# test-hone.sh — Tests for storyforge-hone CSV data quality tool

PYTHON_DIR="${PLUGIN_DIR}/scripts/lib/python"
PY="import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')"

# ============================================================================
# Module: hone.py exports all reconcile functions
# ============================================================================

echo "--- hone: exports reconcile functions ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import (
    build_registry_prompt,
    parse_registry_response,
    write_registry,
    apply_updates,
    apply_registry_normalization,
    reconcile_domain,
    reconcile_outcomes,
    normalize_outcomes,
    _collect_knowledge_chain,
    _collect_physical_state_chain,
)
print('ok')
" 2>/dev/null)

assert_equals "ok" "$RESULT" "hone: exports all reconcile functions"

echo "--- reconcile: backwards-compatible re-exports ---"

RESULT=$(python3 -c "
${PY}
from storyforge.reconcile import (
    build_registry_prompt,
    parse_registry_response,
    write_registry,
    apply_updates,
    reconcile_domain,
)
print('ok')
" 2>/dev/null)

assert_equals "ok" "$RESULT" "reconcile: backwards-compatible re-exports"

# ============================================================================
# Briefs domain: abstract language detection
# ============================================================================

echo "--- briefs: detects abstract key_actions ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_abstract_fields

# Abstract: thematic verbs, narrator language
abstract_row = {
    'id': 'test-scene',
    'key_actions': 'The realization building; connecting her hiding to the creatures hiding; the parallel crystallizing',
    'crisis': 'She could keep hiding or face the truth',
    'decision': 'She faces it',
    'knowledge_in': '',
    'knowledge_out': 'k01',
}
results = detect_abstract_fields({'test-scene': abstract_row})
fields = [r['field'] for r in results]
assert 'key_actions' in fields, f'key_actions not flagged: {fields}'
print(f'flagged={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "briefs: detects abstract key_actions"
assert_contains "$RESULT" "flagged=" "briefs: returns flagged fields"

echo "--- briefs: concrete key_actions not flagged ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_abstract_fields

concrete_row = {
    'id': 'test-scene',
    'key_actions': 'Naji leads her down a stairwell; the door at the bottom is painted gray; she holds the bowl and her hands shake',
    'crisis': 'Go through the door or walk away',
    'decision': 'She goes through the door',
    'knowledge_in': '',
    'knowledge_out': 'k01',
}
results = detect_abstract_fields({'test-scene': concrete_row})
print(f'flagged={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "flagged=0" "briefs: concrete actions not flagged"
assert_contains "$RESULT" "ok" "briefs: concrete detection runs"

# ============================================================================
# Briefs domain: concretize prompt and parser
# ============================================================================

echo "--- briefs: build_concretize_prompt runs ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import build_concretize_prompt

prompt = build_concretize_prompt(
    scene_id='mirror',
    fields=['key_actions'],
    current_values={'key_actions': 'The realization building; the parallel crystallizing'},
    voice_guide='Zara thinks in food metaphors. Sensory-first.',
    character_entry='Zara: 19, line cook, synesthete. Notices temperature, sound, exits, hands.',
)
has_rule = 'physically does or perceives' in prompt
has_current = 'realization building' in prompt
print('has_rule' if has_rule else 'no_rule')
print('has_current' if has_current else 'no_current')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "has_rule" "briefs: prompt includes concretization rule"
assert_contains "$RESULT" "has_current" "briefs: prompt includes current values"
assert_contains "$RESULT" "ok" "briefs: build_concretize_prompt runs"

echo "--- briefs: parse_concretize_response ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import parse_concretize_response

response = '''key_actions: Zara in the bathroom; light buzzing at copper-penny frequency; she looks at her own face and sees the careful blankness; her hands stop on the porcelain; she washes her hands and goes back to the kitchen'''

result = parse_concretize_response(response, 'mirror', ['key_actions'])
print(f\"key_actions={result.get('key_actions', 'MISSING')[:40]}\")
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "key_actions=Zara in the bathroom" "briefs: parse extracts rewritten field"
assert_contains "$RESULT" "ok" "briefs: parse runs"
