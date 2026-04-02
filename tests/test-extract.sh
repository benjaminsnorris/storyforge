#!/bin/bash
# test-extract.sh — Tests for reverse elaboration extraction helpers

PY="import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')"

# ============================================================================
# parse_characterize_response
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.extract import parse_characterize_response
response = '''NARRATIVE_MODE: third-limited
POV_CHARACTERS: Dorren Hayle;Tessa Merrin
TIMELINE: linear
TIMELINE_SPAN: 3 weeks
SCENE_BREAK_STYLE: explicit-markers
ESTIMATED_SCENES: 42
MAJOR_THREADS: institutional-failure;chosen-blindness;the-anomaly
CENTRAL_CONFLICT: A cartographer must choose between institutional loyalty and truth
CAST_SIZE: 12'''
result = parse_characterize_response(response)
print(result.get('narrative_mode', ''))
print(result.get('pov_characters', ''))
print(result.get('estimated_scenes', ''))
print(result.get('major_threads', ''))
")

assert_contains "$RESULT" "third-limited" "parse_characterize: extracts narrative mode"
assert_contains "$RESULT" "Dorren Hayle;Tessa Merrin" "parse_characterize: extracts POV characters"
assert_contains "$RESULT" "42" "parse_characterize: extracts scene count"
assert_contains "$RESULT" "institutional-failure" "parse_characterize: extracts threads"

# ============================================================================
# parse_skeleton_response
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.extract import parse_skeleton_response
response = '''TITLE: The Arranged Dead
POV: Emmett Slade
LOCATION: Alkali Flat
TIMELINE_DAY: 1
TIME_OF_DAY: afternoon
DURATION: 2 hours
TARGET_WORDS: 1300
PART: 1'''
result = parse_skeleton_response(response, 'arranged-dead')
print(result.get('id', ''))
print(result.get('title', ''))
print(result.get('pov', ''))
print(result.get('timeline_day', ''))
print(result.get('part', ''))
")

assert_equals "arranged-dead" "$(echo "$RESULT" | head -1)" "parse_skeleton: preserves scene id"
assert_contains "$RESULT" "The Arranged Dead" "parse_skeleton: extracts title"
assert_contains "$RESULT" "Emmett Slade" "parse_skeleton: extracts POV"
assert_contains "$RESULT" "1" "parse_skeleton: extracts timeline day"

# ============================================================================
# parse_intent_response
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.extract import parse_intent_response
response = '''FUNCTION: Emmett reads the staged crime scene and connects the murder to a disappearance
SCENE_TYPE: action
EMOTIONAL_ARC: Professional detachment to resolved determination
VALUE_AT_STAKE: truth
VALUE_SHIFT: +/-
TURNING_POINT: revelation
THREADS: murder-investigation;land-fraud
CHARACTERS: Emmett Slade;Samuel Orcutt;Colson
ON_STAGE: Emmett Slade;Colson
MICE_THREADS: +inquiry:who-killed-orcutt
CONFIDENCE: high'''
result = parse_intent_response(response, 'arranged-dead')
print(result.get('function', ''))
print(result.get('scene_type', ''))
print(result.get('value_shift', ''))
print(result.get('threads', ''))
print(result.get('_confidence', ''))
")

assert_contains "$RESULT" "staged crime scene" "parse_intent: extracts function"
assert_contains "$RESULT" "action" "parse_intent: extracts scene type"
assert_contains "$RESULT" "+/-" "parse_intent: extracts value shift"
assert_contains "$RESULT" "murder-investigation" "parse_intent: extracts threads"
assert_contains "$RESULT" "high" "parse_intent: extracts confidence"

# ============================================================================
# parse_brief_parallel_response
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.extract import parse_brief_parallel_response
response = '''GOAL: Determine cause of death and establish whether it is murder
CONFLICT: The crime scene has been deliberately staged to look accidental
OUTCOME: no-and
CRISIS: Report the staging and alert the territorial marshal, or investigate quietly
DECISION: Investigates quietly — keeps the staging knowledge to himself
KEY_ACTIONS: Examines body;Notes staged positioning;Finds survey equipment;Interviews Colson
KEY_DIALOGUE: The body was found like this?;Exactly like this, Sheriff
EMOTIONS: professional-calm;suspicion;recognition;quiet-resolve
MOTIFS: arranged-bodies;survey-equipment;patience'''
result = parse_brief_parallel_response(response, 'arranged-dead')
print(result.get('goal', ''))
print(result.get('outcome', ''))
print(result.get('crisis', ''))
")

assert_contains "$RESULT" "cause of death" "parse_brief: extracts goal"
assert_contains "$RESULT" "no-and" "parse_brief: extracts outcome"
assert_contains "$RESULT" "Report the staging" "parse_brief: extracts crisis"

# ============================================================================
# parse_knowledge_response
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.extract import parse_knowledge_response
response = '''KNOWLEDGE_IN: Orcutt was found dead at the alkali flat
KNOWLEDGE_OUT: Orcutt was found dead at the alkali flat;the body was deliberately staged;survey equipment was present at the scene
CONTINUITY_DEPS: discovery-at-flat
SCENE_SUMMARY: Emmett examines the staged crime scene and decides to investigate quietly'''
result = parse_knowledge_response(response, 'arranged-dead')
print(result.get('knowledge_in', ''))
print(result.get('knowledge_out', ''))
print(result.get('continuity_deps', ''))
print(result.get('_summary', ''))
")

assert_contains "$RESULT" "Orcutt was found dead" "parse_knowledge: extracts knowledge_in"
assert_contains "$RESULT" "deliberately staged" "parse_knowledge: extracts knowledge_out"
assert_contains "$RESULT" "discovery-at-flat" "parse_knowledge: extracts continuity_deps"
assert_contains "$RESULT" "examines the staged" "parse_knowledge: extracts summary"

# ============================================================================
# analyze_expansion_opportunities
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.extract import analyze_expansion_opportunities
opps = analyze_expansion_opportunities('${FIXTURE_DIR}/reference')
for o in opps:
    print(f\"{o['type']}: {o['priority']} — {o['scene_id']}\")
print(f'total: {len(opps)}')
")

assert_not_empty "$RESULT" "analyze_expansion: produces output"
assert_contains "$RESULT" "total:" "analyze_expansion: completes without error"

# ============================================================================
# build_characterize_prompt
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.extract import build_characterize_prompt
prompt = build_characterize_prompt('${FIXTURE_DIR}')
print(len(prompt))
")

assert_not_empty "$RESULT" "build_characterize: produces non-empty prompt"

# ============================================================================
# build_skeleton_prompt
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.extract import build_skeleton_prompt
prompt = build_skeleton_prompt('act1-sc01', 'Some scene prose here.', {'pov_characters': 'Alice', 'timeline': 'linear'})
print('POV' in prompt and 'TITLE' in prompt and 'LOCATION' in prompt)
")

assert_equals "True" "$RESULT" "build_skeleton: prompt contains expected field labels"

# ============================================================================
# build_intent_prompt
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.extract import build_intent_prompt
prompt = build_intent_prompt('act1-sc01', 'Scene prose.', {'major_threads': 'thread-a'}, {'title': 'Test', 'pov': 'Alice'})
print('FUNCTION' in prompt and 'VALUE_SHIFT' in prompt and 'MICE_THREADS' in prompt)
")

assert_equals "True" "$RESULT" "build_intent: prompt contains expected field labels"

# ============================================================================
# cleanup_timeline
# ============================================================================

TMP_REF=$(mktemp -d)
cp "${FIXTURE_DIR}/reference/scenes.csv" "${TMP_REF}/scenes.csv"
cp "${FIXTURE_DIR}/reference/scene-intent.csv" "${TMP_REF}/scene-intent.csv"
cp "${FIXTURE_DIR}/reference/scene-briefs.csv" "${TMP_REF}/scene-briefs.csv"

# Clear timeline_day for scene 2 to create a gap
python3 -c "
${PY}
from storyforge.elaborate import update_scene
update_scene('act1-sc02', '${TMP_REF}', {'timeline_day': ''})
"

RESULT=$(python3 -c "
${PY}
from storyforge.extract import cleanup_timeline
import json
fixes = cleanup_timeline('${TMP_REF}')
print(len(fixes))
for f in fixes:
    print(f'{f[\"scene_id\"]}: {f[\"new_value\"]}')
")

assert_contains "$RESULT" "act1-sc02" "cleanup_timeline: fills gap for act1-sc02"
assert_contains "$RESULT" "1" "cleanup_timeline: infers day 1 from adjacent scenes"

rm -rf "$TMP_REF"

# ============================================================================
# cleanup_knowledge
# ============================================================================

TMP_REF=$(mktemp -d)
cp "${FIXTURE_DIR}/reference/scenes.csv" "${TMP_REF}/scenes.csv"
cp "${FIXTURE_DIR}/reference/scene-intent.csv" "${TMP_REF}/scene-intent.csv"
cp "${FIXTURE_DIR}/reference/scene-briefs.csv" "${TMP_REF}/scene-briefs.csv"

# Introduce a knowledge wording mismatch
python3 -c "
${PY}
from storyforge.elaborate import update_scene
# act1-sc01 knowledge_out says 'Eastern readings don't match'
# Change act1-sc02 knowledge_in to use slightly different wording
update_scene('act1-sc02', '${TMP_REF}', {'knowledge_in': 'Eastern readings do not match; has private note about anomaly'})
"

RESULT=$(python3 -c "
${PY}
from storyforge.extract import cleanup_knowledge
import json
fixes = cleanup_knowledge('${TMP_REF}')
print(len(fixes))
")

# Should find and fix the wording mismatch via fuzzy matching
FIXES=$(echo "$RESULT" | head -1)
assert_not_empty "$FIXES" "cleanup_knowledge: detects wording mismatch"

rm -rf "$TMP_REF"

# ============================================================================
# cleanup_mice_threads
# ============================================================================

TMP_REF=$(mktemp -d)
cp "${FIXTURE_DIR}/reference/scenes.csv" "${TMP_REF}/scenes.csv"
cp "${FIXTURE_DIR}/reference/scene-intent.csv" "${TMP_REF}/scene-intent.csv"
cp "${FIXTURE_DIR}/reference/scene-briefs.csv" "${TMP_REF}/scene-briefs.csv"

# Add a duplicate open and a close for an unopened thread
python3 -c "
${PY}
from storyforge.elaborate import update_scene
update_scene('new-x1', '${TMP_REF}', {'mice_threads': '+inquiry:archive-erasure;+inquiry:archive-erasure;-event:nonexistent'})
"

RESULT=$(python3 -c "
${PY}
from storyforge.extract import cleanup_mice_threads
import json
fixes = cleanup_mice_threads('${TMP_REF}')
print(len(fixes))
for f in fixes:
    print(f'{f[\"scene_id\"]}: {f[\"old_value\"]} → {f[\"new_value\"]}')
")

assert_contains "$RESULT" "duplicate open" "cleanup_mice: removes duplicate open"
assert_contains "$RESULT" "unopened thread" "cleanup_mice: removes close for unopened thread"

rm -rf "$TMP_REF"

# ============================================================================
# run_cleanup (integration)
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.extract import run_cleanup
import json
result = run_cleanup('${FIXTURE_DIR}/reference')
print(f'total: {result[\"total_fixes\"]}')
print(f'timeline: {result[\"timeline\"][\"count\"]}')
print(f'knowledge: {result[\"knowledge\"][\"count\"]}')
print(f'mice: {result[\"mice_threads\"][\"count\"]}')
")

assert_contains "$RESULT" "total:" "run_cleanup: returns summary"
