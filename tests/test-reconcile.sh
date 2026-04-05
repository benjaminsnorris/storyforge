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
