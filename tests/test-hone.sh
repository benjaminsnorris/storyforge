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
