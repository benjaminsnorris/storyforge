#!/bin/bash
# test-elaborate.sh — Tests for elaboration pipeline helpers

SCENES_CSV="${FIXTURE_DIR}/reference/scenes.csv"
INTENT_CSV="${FIXTURE_DIR}/reference/scene-intent.csv"
BRIEFS_CSV="${FIXTURE_DIR}/reference/scene-briefs.csv"

PY="import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')"

# ============================================================================
# get_scene
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import get_scene
import json
scene = get_scene('act1-sc01', '${FIXTURE_DIR}/reference')
print(json.dumps(scene))
")

assert_contains "$RESULT" '"id": "act1-sc01"' "get_scene: returns id"
assert_contains "$RESULT" '"pov": "Dorren Hayle"' "get_scene: returns pov from scenes.csv"
assert_contains "$RESULT" '"function":' "get_scene: returns function from intent.csv"
assert_contains "$RESULT" '"goal":' "get_scene: returns goal from briefs.csv"
assert_contains "$RESULT" '"value_shift": "+/-"' "get_scene: returns value_shift from intent.csv"

# Scene with no brief row (act2-sc01 is status=architecture, no brief entry)
RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import get_scene
import json
scene = get_scene('act2-sc01', '${FIXTURE_DIR}/reference')
print(json.dumps(scene))
")

assert_contains "$RESULT" '"pov": "Tessa Merrin"' "get_scene: no-brief scene has structural data"
assert_contains "$RESULT" '"goal": ""' "get_scene: no-brief scene has empty brief fields"

# Nonexistent scene
RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import get_scene
scene = get_scene('nonexistent', '${FIXTURE_DIR}/reference')
print(scene)
")

assert_equals "None" "$RESULT" "get_scene: nonexistent scene returns None"

# ============================================================================
# get_scenes — column selection
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import get_scenes
import json
scenes = get_scenes('${FIXTURE_DIR}/reference', columns=['id', 'pov', 'value_shift'])
print(json.dumps(scenes))
")

assert_contains "$RESULT" '"id": "act1-sc01"' "get_scenes: returns first scene"
assert_contains "$RESULT" '"value_shift": "+/-"' "get_scenes: includes cross-file column"
assert_not_contains "$RESULT" '"goal"' "get_scenes: excludes unrequested columns"

# get_scenes — filter
RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import get_scenes
scenes = get_scenes('${FIXTURE_DIR}/reference', filters={'pov': 'Dorren Hayle'})
print(len(scenes))
")

assert_equals "3" "$RESULT" "get_scenes: filter by pov returns correct count"

# get_scenes — ordering by seq
RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import get_scenes
scenes = get_scenes('${FIXTURE_DIR}/reference', columns=['id'])
ids = [s['id'] for s in scenes]
print(' '.join(ids))
")

assert_equals "act1-sc01 act1-sc02 new-x1 act2-sc01 act2-sc02 act2-sc03" "$RESULT" "get_scenes: ordered by seq"

# ============================================================================
# get_column
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import get_column
print(' '.join(get_column('${FIXTURE_DIR}/reference', 'pov')))
")

assert_equals "Dorren Hayle Dorren Hayle Kael Maren Tessa Merrin Tessa Merrin Dorren Hayle" "$RESULT" "get_column: returns pov values in seq order"

# ============================================================================
# update_scene
# ============================================================================

TMP_REF=$(mktemp -d)
cp "${FIXTURE_DIR}/reference/scenes.csv" "${TMP_REF}/scenes.csv"
cp "${FIXTURE_DIR}/reference/scene-intent.csv" "${TMP_REF}/scene-intent.csv"
cp "${FIXTURE_DIR}/reference/scene-briefs.csv" "${TMP_REF}/scene-briefs.csv"

# Update a scenes.csv column
python3 -c "
${PY}
from storyforge.elaborate import update_scene
update_scene('act1-sc01', '${TMP_REF}', {'status': 'drafted', 'word_count': '2450'})
"

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import get_scene
scene = get_scene('act1-sc01', '${TMP_REF}')
print(scene['status'], scene['word_count'])
")

assert_equals "drafted 2450" "$RESULT" "update_scene: updates scenes.csv columns"

# Update a brief column
python3 -c "
${PY}
from storyforge.elaborate import update_scene
update_scene('act1-sc01', '${TMP_REF}', {'goal': 'Survive the audit'})
"

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import get_scene
scene = get_scene('act1-sc01', '${TMP_REF}')
print(scene['goal'])
")

assert_equals "Survive the audit" "$RESULT" "update_scene: updates briefs.csv columns"

# Update an intent column
python3 -c "
${PY}
from storyforge.elaborate import update_scene
update_scene('act1-sc01', '${TMP_REF}', {'value_shift': '-/+'})
"

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import get_scene
scene = get_scene('act1-sc01', '${TMP_REF}')
print(scene['value_shift'])
")

assert_equals "-/+" "$RESULT" "update_scene: updates intent.csv columns"

rm -rf "$TMP_REF"

# ============================================================================
# add_scenes
# ============================================================================

TMP_REF=$(mktemp -d)
cp "${FIXTURE_DIR}/reference/scenes.csv" "${TMP_REF}/scenes.csv"
cp "${FIXTURE_DIR}/reference/scene-intent.csv" "${TMP_REF}/scene-intent.csv"
cp "${FIXTURE_DIR}/reference/scene-briefs.csv" "${TMP_REF}/scene-briefs.csv"

python3 -c "
${PY}
from storyforge.elaborate import add_scenes
add_scenes('${TMP_REF}', [
    {'id': 'new-scene', 'seq': '7', 'title': 'The New Scene', 'status': 'spine', 'function': 'Test scene'},
])
"

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import get_scene
scene = get_scene('new-scene', '${TMP_REF}')
print(scene['title'], scene['function'], scene['status'])
")

assert_equals "The New Scene Test scene spine" "$RESULT" "add_scenes: creates rows across all files"

rm -rf "$TMP_REF"

# ============================================================================
# validate_structure — identity and completeness
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
import json
report = validate_structure('${FIXTURE_DIR}/reference')
print(json.dumps(report))
")

assert_contains "$RESULT" '"passed":' "validate_structure: returns report with passed field"
assert_contains "$RESULT" '"failures":' "validate_structure: returns report with failures field"

# Identity checks should pass
PASSED=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
report = validate_structure('${FIXTURE_DIR}/reference')
identity = [c for c in report['checks'] if c['category'] == 'identity']
print(all(c['passed'] for c in identity))
")

assert_equals "True" "$PASSED" "validate_structure: fixtures pass identity checks"

# Completeness checks should pass
RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
report = validate_structure('${FIXTURE_DIR}/reference')
completeness = [c for c in report['checks'] if c['category'] == 'completeness']
print(all(c['passed'] for c in completeness))
")

assert_equals "True" "$RESULT" "validate_structure: fixtures pass completeness checks"

# Detect orphaned intent row
TMP_REF=$(mktemp -d)
cp "${FIXTURE_DIR}/reference/scenes.csv" "${TMP_REF}/scenes.csv"
cp "${FIXTURE_DIR}/reference/scene-intent.csv" "${TMP_REF}/scene-intent.csv"
cp "${FIXTURE_DIR}/reference/scene-briefs.csv" "${TMP_REF}/scene-briefs.csv"

echo "orphan-scene|Orphan function|action|calm to panic|truth|+/-|action|thread-a|Char A|Char A|" >> "${TMP_REF}/scene-intent.csv"

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
report = validate_structure('${TMP_REF}')
identity = [c for c in report['checks'] if c['category'] == 'identity' and not c['passed']]
print(len(identity) > 0)
")

assert_equals "True" "$RESULT" "validate_structure: detects orphaned intent row"

rm -rf "$TMP_REF"

# ============================================================================
# validate_structure — MICE threads
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
report = validate_structure('${FIXTURE_DIR}/reference')
thread_checks = [c for c in report['checks'] if c['category'] == 'threads']
for c in thread_checks:
    print(c['check'], c['passed'])
")

assert_contains "$RESULT" "mice-nesting True" "validate_structure: MICE threads nest correctly"

# ============================================================================
# validate_structure — timeline
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
report = validate_structure('${FIXTURE_DIR}/reference')
timeline_checks = [c for c in report['checks'] if c['category'] == 'timeline']
for c in timeline_checks:
    print(c['check'], c['passed'])
")

assert_contains "$RESULT" "timeline-order True" "validate_structure: timeline checks pass on fixtures"

# Detect backwards timeline
TMP_REF=$(mktemp -d)
cp "${FIXTURE_DIR}/reference/scenes.csv" "${TMP_REF}/scenes.csv"
cp "${FIXTURE_DIR}/reference/scene-intent.csv" "${TMP_REF}/scene-intent.csv"
cp "${FIXTURE_DIR}/reference/scene-briefs.csv" "${TMP_REF}/scene-briefs.csv"

python3 -c "
${PY}
from storyforge.elaborate import update_scene
update_scene('act1-sc02', '${TMP_REF}', {'timeline_day': '5'})
"

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
report = validate_structure('${TMP_REF}')
timeline_checks = [c for c in report['checks'] if c['category'] == 'timeline']
failed = [c for c in timeline_checks if not c['passed']]
print(len(failed) > 0)
")

assert_equals "True" "$RESULT" "validate_structure: detects backwards timeline jump"

rm -rf "$TMP_REF"

# ============================================================================
# validate_structure — knowledge flow
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
report = validate_structure('${FIXTURE_DIR}/reference')
knowledge_checks = [c for c in report['checks'] if c['category'] == 'knowledge']
passed = [c for c in knowledge_checks if c['passed']]
print(len(passed) > 0)
")

assert_equals "True" "$RESULT" "validate_structure: knowledge flow checks pass on fixtures"

# ============================================================================
# validate_structure — pacing
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
report = validate_structure('${FIXTURE_DIR}/reference')
pacing_checks = [c for c in report['checks'] if c['category'] == 'pacing']
passed = all(c['passed'] for c in pacing_checks)
print(passed)
")

assert_equals "True" "$RESULT" "validate_structure: pacing checks pass on fixtures"

# Detect flat polarity stretch
TMP_REF=$(mktemp -d)
cp "${FIXTURE_DIR}/reference/scenes.csv" "${TMP_REF}/scenes.csv"
cp "${FIXTURE_DIR}/reference/scene-intent.csv" "${TMP_REF}/scene-intent.csv"
cp "${FIXTURE_DIR}/reference/scene-briefs.csv" "${TMP_REF}/scene-briefs.csv"

python3 -c "
${PY}
from storyforge.elaborate import update_scene
for sid in ['act1-sc01', 'act1-sc02', 'new-x1', 'act2-sc01']:
    update_scene(sid, '${TMP_REF}', {'value_shift': '+/+'})
"

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
report = validate_structure('${TMP_REF}')
pacing = [c for c in report['checks'] if c['category'] == 'pacing']
failed = [c for c in pacing if not c['passed']]
print(len(failed) > 0)
")

assert_equals "True" "$RESULT" "validate_structure: detects flat polarity stretch"

rm -rf "$TMP_REF"

# ============================================================================
# compute_drafting_waves
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import compute_drafting_waves
import json
waves = compute_drafting_waves('${FIXTURE_DIR}/reference')
print(json.dumps(waves))
")

# act1-sc01 has no deps → wave 1
# act1-sc02 depends on act1-sc01 → wave 2
# act2-sc03 depends on act1-sc02 and new-x1 → wave 2 or 3
assert_contains "$RESULT" "act1-sc01" "compute_waves: act1-sc01 appears in waves"
assert_contains "$RESULT" "act2-sc03" "compute_waves: act2-sc03 appears in waves"

WAVE_COUNT=$(python3 -c "
${PY}
from storyforge.elaborate import compute_drafting_waves
waves = compute_drafting_waves('${FIXTURE_DIR}/reference')
print(len(waves))
")

assert_not_empty "$WAVE_COUNT" "compute_waves: returns non-empty waves"

# First wave should contain scenes with no deps
WAVE1=$(python3 -c "
${PY}
from storyforge.elaborate import compute_drafting_waves
waves = compute_drafting_waves('${FIXTURE_DIR}/reference')
print(' '.join(waves[0]) if waves else '')
")

assert_contains "$WAVE1" "act1-sc01" "compute_waves: wave 1 contains act1-sc01 (no deps)"

# ============================================================================
# score_structure
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import score_structure
import json
scores = score_structure('${FIXTURE_DIR}/reference')
for s in scores:
    print(f\"{s['scene_id']}: {s['score']} issues={len(s['issues'])}\")
")

# Fully briefed scenes should score high
assert_contains "$RESULT" "act1-sc01: 5" "score_structure: fully briefed scene scores 5"
# Scene with no brief (act2-sc01) should score 0
assert_contains "$RESULT" "act2-sc01: 0" "score_structure: unbriefed scene scores 0"
# new-x1 has empty brief fields → should score 0
assert_contains "$RESULT" "new-x1: 0" "score_structure: empty brief scene scores 0"

# ============================================================================
# build_scene_prompt_from_briefs (via CLI)
# ============================================================================

RESULT=$(PYTHONPATH="${PLUGIN_DIR}/scripts/lib/python" python3 -m storyforge.prompts build-from-briefs \
    "act1-sc01" "${FIXTURE_DIR}" \
    --plugin-dir "${PLUGIN_DIR}" \
    --coaching full 2>&1)

assert_contains "$RESULT" "Dorren Hayle" "build_from_briefs: includes POV character"
assert_contains "$RESULT" "goal" "build_from_briefs: includes brief goal"
assert_contains "$RESULT" "Write the complete prose" "build_from_briefs: full mode asks for prose"

# Coach mode
RESULT=$(PYTHONPATH="${PLUGIN_DIR}/scripts/lib/python" python3 -m storyforge.prompts build-from-briefs \
    "act1-sc01" "${FIXTURE_DIR}" \
    --plugin-dir "${PLUGIN_DIR}" \
    --coaching coach 2>&1)

assert_contains "$RESULT" "writing guide" "build_from_briefs: coach mode asks for guide"
assert_not_contains "$RESULT" "Write the complete prose" "build_from_briefs: coach mode does not ask for prose"

# With deps
RESULT=$(PYTHONPATH="${PLUGIN_DIR}/scripts/lib/python" python3 -m storyforge.prompts build-from-briefs \
    "act1-sc02" "${FIXTURE_DIR}" \
    --plugin-dir "${PLUGIN_DIR}" \
    --coaching full \
    --deps "act1-sc01" 2>&1)

assert_contains "$RESULT" "Dependency Scenes" "build_from_briefs: includes dep context"
assert_contains "$RESULT" "act1-sc01" "build_from_briefs: dep scene ID referenced"
