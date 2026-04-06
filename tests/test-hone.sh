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
