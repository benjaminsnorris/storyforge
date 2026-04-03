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

# Test that closure checks use pre-populated registry (issue #67)
THREAD_DIR="${TMPDIR}/thread-test/reference"
mkdir -p "$THREAD_DIR"
cat > "${THREAD_DIR}/scenes.csv" <<'CSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
s01|1|Scene One|1|Alice|Room|1|morning|1 hour|action|briefed|1000|2000
s02|2|Scene Two|1|Alice|Room|1|afternoon|1 hour|action|briefed|1000|2000
s03|3|Scene Three|1|Alice|Room|2|morning|1 hour|action|briefed|1000|2000
s04|4|Scene Four|2|Alice|Room|2|afternoon|1 hour|action|briefed|1000|2000
s05|5|Scene Five|2|Alice|Room|3|morning|1 hour|action|briefed|1000|2000
CSV
cat > "${THREAD_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
s01|test|action|flat|truth|+/-|revelation|a|Alice|Alice|+inquiry:mystery;+milieu:dungeon
s02|test|action|flat|truth|+/-|revelation|a|Alice|Alice|+event:storm
s03|test|action|flat|truth|+/-|revelation|a|Alice|Alice|-milieu:dungeon;-event:storm
s04|test|action|flat|truth|+/-|revelation|a|Alice|Alice|-inquiry:mystery
s05|test|action|flat|truth|+/-|revelation|a|Alice|Alice|
CSV
cat > "${THREAD_DIR}/scene-briefs.csv" <<'CSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
s01|g|c|o|cr|d|k|k|a|d|e|m||false
s02|g|c|o|cr|d|k|k|a|d|e|m||false
s03|g|c|o|cr|d|k|k|a|d|e|m||false
s04|g|c|o|cr|d|k|k|a|d|e|m||false
s05|g|c|o|cr|d|k|k|a|d|e|m||false
CSV

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
report = validate_structure('${THREAD_DIR}')
thread_checks = [c for c in report['checks'] if c['category'] == 'threads']
for c in thread_checks:
    print(c['check'], c['passed'], c.get('message', ''))
")

assert_not_contains "$RESULT" "was never opened" "validate_structure: closures find openings from earlier scenes (issue #67)"
assert_contains "$RESULT" "mice-nesting" "validate_structure: MICE nesting check present for cross-scene threads"

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

# Crosscut: backwards jump with POV change should be advisory, not blocking (issue #68)
CROSSCUT_DIR="${TMPDIR}/crosscut-test/reference"
mkdir -p "$CROSSCUT_DIR"
cat > "${CROSSCUT_DIR}/scenes.csv" <<'CSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
s01|1|Scene One|1|Emmett|Town|13|morning|1 hour|action|briefed|1000|2000
s02|2|Scene Two|1|Emmett|Town|14|morning|1 hour|action|briefed|1000|2000
s03|3|Scene Three|1|Lena|Station|12|morning|1 hour|action|briefed|1000|2000
s04|4|Scene Four|1|Emmett|Town|15|morning|1 hour|action|briefed|1000|2000
CSV
cat > "${CROSSCUT_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
s01|test|action|flat|truth|+/-|revelation|a|Emmett|Emmett|
s02|test|action|flat|truth|+/-|revelation|a|Emmett|Emmett|
s03|test|action|flat|truth|+/-|revelation|a|Lena|Lena|
s04|test|action|flat|truth|+/-|revelation|a|Emmett|Emmett|
CSV
cat > "${CROSSCUT_DIR}/scene-briefs.csv" <<'CSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
s01|g|c|o|cr|d|k|k|a|d|e|m||false
s02|g|c|o|cr|d|k|k|a|d|e|m||false
s03|g|c|o|cr|d|k|k|a|d|e|m||false
s04|g|c|o|cr|d|k|k|a|d|e|m||false
CSV

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
report = validate_structure('${CROSSCUT_DIR}')
timeline_checks = [c for c in report['checks'] if c['category'] == 'timeline']
for c in timeline_checks:
    print(c.get('severity', 'blocking'), c['passed'], c.get('message', ''))
")

assert_contains "$RESULT" "advisory" "validate_structure: crosscut backwards jump is advisory (issue #68)"
assert_contains "$RESULT" "crosscut" "validate_structure: crosscut message identifies POV change"
assert_not_contains "$RESULT" "blocking" "validate_structure: crosscut does not produce blocking failure"

rm -rf "${TMPDIR}/crosscut-test"

# Same-POV backwards jump should remain blocking
SAMEPOV_DIR="${TMPDIR}/samepov-test/reference"
mkdir -p "$SAMEPOV_DIR"
cat > "${SAMEPOV_DIR}/scenes.csv" <<'CSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
s01|1|Scene One|1|Alice|Room|3|morning|1 hour|action|briefed|1000|2000
s02|2|Scene Two|1|Alice|Room|1|morning|1 hour|action|briefed|1000|2000
CSV
cat > "${SAMEPOV_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
s01|test|action|flat|truth|+/-|revelation|a|Alice|Alice|
s02|test|action|flat|truth|+/-|revelation|a|Alice|Alice|
CSV
cat > "${SAMEPOV_DIR}/scene-briefs.csv" <<'CSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
s01|g|c|o|cr|d|k|k|a|d|e|m||false
s02|g|c|o|cr|d|k|k|a|d|e|m||false
CSV

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import validate_structure
report = validate_structure('${SAMEPOV_DIR}')
timeline_checks = [c for c in report['checks'] if c['category'] == 'timeline']
blocking = [c for c in timeline_checks if c.get('severity', 'blocking') == 'blocking' and not c['passed']]
print(len(blocking) > 0)
")

assert_equals "True" "$RESULT" "validate_structure: same-POV backwards jump stays blocking"

rm -rf "${TMPDIR}/samepov-test"

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

# ============================================================================
# analyze_gaps
# ============================================================================

# Create a post-extraction fixture: drafted scenes with gaps
TMP_REF=$(mktemp -d)

# scenes.csv — all drafted, but some missing time_of_day and timeline_day
cat > "${TMP_REF}/scenes.csv" <<'GAPCSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
scene-01|1|Opening|1|Alice|The Lab|1|morning|2 hours|character|drafted|2500|2500
scene-02|2|Discovery|1|Alice|The Lab||afternoon||action|drafted|3000|3000
scene-03|3|Confrontation|1|Bob|Council Room|2||1 hour|action|drafted|2000|2000
scene-04|4|Escape|2|Alice|The Tunnel|3|night|30 minutes|action|drafted|1800|1800
GAPCSV

# scene-intent.csv — some missing value_shift and action_sequel
cat > "${TMP_REF}/scene-intent.csv" <<'GAPCSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
scene-01|Establish the lab|action|calm to focused|truth|+/-|revelation|discovery|Alice;Bob|Alice|+inquiry:anomaly
scene-02|Find the anomaly||tense to shocked|safety||action|discovery;danger|Alice|Alice|
scene-03|Confront the council|sequel|resolve to anger|justice|+/-|revelation|politics|Bob;Council|Bob;Council|
scene-04|Escape the collapse|action|fear to relief|life|-/+|action|danger|Alice|Alice|-inquiry:anomaly
GAPCSV

# scene-briefs.csv — all populated (post-extraction state)
cat > "${TMP_REF}/scene-briefs.csv" <<'GAPCSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
scene-01|Set up the experiment|Equipment is faulty|yes-but|Fix equipment or start anyway|Starts anyway|Lab is funded|Lab equipment is faulty;experiment started|Checks equipment;Starts experiment|"We proceed"|calm;determination|lab-lights||false
scene-02|Investigate the anomaly|Anomaly is dangerous|no-and|Retreat or push deeper|Pushes deeper|Lab equipment is faulty;experiment started|Anomaly is real;it is spreading|Scans anomaly;Takes samples|"This shouldn't be possible"|curiosity;shock;fear|anomaly-glow|scene-01|false
scene-03|Get council to act|Council dismisses evidence|no|Accept dismissal or go rogue|Goes rogue|Anomaly is real;it is spreading|Council will not help;must act alone|Presents evidence;Council votes no|"Noted for the record"|resolve;anger;defiance|governance-weight|scene-02|false
scene-04|Escape the tunnel|Tunnel is collapsing|yes|Save samples or save self|Saves self|Council will not help;must act alone|Survived;samples lost|Runs;Dodges debris;Reaches exit|"Leave it!"|fear;relief|depth-descent|scene-03|false
GAPCSV

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import analyze_gaps
import json
gaps = analyze_gaps('${TMP_REF}')
print(json.dumps(gaps, indent=2))
")

# Should detect gap groups
assert_contains "$RESULT" '"scene-fields"' "analyze_gaps: detects scene-fields group"
assert_contains "$RESULT" '"intent-fields"' "analyze_gaps: detects intent-fields group"
assert_contains "$RESULT" '"scene-03"' "analyze_gaps: scene-03 missing time_of_day"
assert_contains "$RESULT" '"scene-02"' "analyze_gaps: scene-02 missing timeline_day"

# Should include total counts
TOTAL=$(python3 -c "
${PY}
from storyforge.elaborate import analyze_gaps
gaps = analyze_gaps('${TMP_REF}')
print(gaps['total_gaps'])
")

assert_equals "4" "$TOTAL" "analyze_gaps: total_gaps count is exact (scene-02: timeline_day+action_sequel+value_shift, scene-03: time_of_day)"

# Should not flag scenes with no gaps
assert_not_contains "$RESULT" '"scene-01": {' "analyze_gaps: scene-01 has no completeness gaps"

# Should return empty structural list for this fixture
STRUCTURAL=$(python3 -c "
${PY}
from storyforge.elaborate import analyze_gaps
gaps = analyze_gaps('${TMP_REF}')
print(len(gaps['structural']))
")

assert_equals "0" "$STRUCTURAL" "analyze_gaps: no structural issues in clean fixture"

rm -rf "$TMP_REF"

# ============================================================================
# build_gap_fill_prompt
# ============================================================================

TMP_REF=$(mktemp -d)
TMP_SCENES="${TMP_REF}/scenes"
mkdir -p "${TMP_SCENES}"
mkdir -p "${TMP_REF}/reference"

# Create a scene file
cat > "${TMP_SCENES}/scene-03.md" <<'PROSE'
Bob strode into the council chamber. The long table gleamed under the gas lamps.
"We have evidence," he said, laying the maps flat. "The eastern ridge is failing."
The council members exchanged glances. No one spoke for a long moment.
PROSE

# Create minimal CSVs
cat > "${TMP_REF}/reference/scenes.csv" <<'GAPCSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
scene-03|3|Confrontation|1|Bob|Council Room|2|evening|1 hour||drafted|2000|2000
GAPCSV

cat > "${TMP_REF}/reference/scene-intent.csv" <<'GAPCSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
scene-03|Confront the council|sequel|resolve to anger|justice|+/-|revelation|politics|Bob;Council|Bob;Council|
GAPCSV

cat > "${TMP_REF}/reference/scene-briefs.csv" <<'GAPCSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
scene-03|Get council to act|Council dismisses|no|Accept or go rogue|Goes rogue|Evidence exists|Council will not help|Presents evidence|"Noted"|resolve;anger|governance|scene-02|false
GAPCSV

RESULT=$(python3 -c "
${PY}
from storyforge.prompts_elaborate import build_gap_fill_prompt
prompt = build_gap_fill_prompt(
    scene_id='scene-03',
    gap_group='scene-fields',
    missing_fields=['type'],
    project_dir='${TMP_REF}',
    scenes_dir='${TMP_SCENES}',
)
print(prompt)
")

assert_contains "$RESULT" "scene-03" "build_gap_fill_prompt: includes scene ID"
assert_contains "$RESULT" "type" "build_gap_fill_prompt: asks for missing field"
assert_contains "$RESULT" "Bob" "build_gap_fill_prompt: includes prose excerpt"
assert_contains "$RESULT" "council chamber" "build_gap_fill_prompt: includes scene prose"

rm -rf "$TMP_REF"

# ============================================================================
# build_knowledge_fix_prompt
# ============================================================================

TMP_REF=$(mktemp -d)
TMP_SCENES="${TMP_REF}/scenes"
mkdir -p "${TMP_SCENES}" "${TMP_REF}/reference"

cat > "${TMP_SCENES}/scene-02.md" <<'PROSE'
Alice ran the scanner across the anomaly. The readings confirmed what she feared.
"This shouldn't be possible," she whispered. The anomaly was real, and spreading.
PROSE

cat > "${TMP_REF}/reference/scenes.csv" <<'GAPCSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
scene-01|1|Opening|1|Alice|The Lab|1|morning|2 hours|character|drafted|2500|2500
scene-02|2|Discovery|1|Alice|The Lab|1|afternoon|1 hour|action|drafted|3000|3000
GAPCSV

cat > "${TMP_REF}/reference/scene-intent.csv" <<'GAPCSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
scene-01|Establish the lab|action|calm to focused|truth|+/-|revelation|discovery|Alice|Alice|
scene-02|Find the anomaly|action|tense to shocked|safety|-/+|action|discovery|Alice|Alice|
GAPCSV

cat > "${TMP_REF}/reference/scene-briefs.csv" <<'GAPCSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
scene-01|Set up experiment|Equipment faulty|yes-but|Fix or start|Starts anyway||Lab equipment is faulty;experiment started|Checks equipment|"We proceed"|calm|lights||false
scene-02|Investigate anomaly|Dangerous|no-and|Retreat or push|Pushes deeper|Equipment is broken;experiment began|Anomaly is real;it is spreading|Scans anomaly|"Impossible"|shock|glow|scene-01|false
GAPCSV

RESULT=$(python3 -c "
${PY}
from storyforge.prompts_elaborate import build_knowledge_fix_prompt

prior_knowledge = {'Lab equipment is faulty', 'experiment started'}
prompt = build_knowledge_fix_prompt(
    scene_id='scene-02',
    project_dir='${TMP_REF}',
    scenes_dir='${TMP_SCENES}',
    available_knowledge=prior_knowledge,
)
print(prompt)
")

assert_contains "$RESULT" "scene-02" "build_knowledge_fix_prompt: includes scene ID"
assert_contains "$RESULT" "Lab equipment is faulty" "build_knowledge_fix_prompt: includes available knowledge"
assert_contains "$RESULT" "knowledge_in" "build_knowledge_fix_prompt: asks for knowledge_in"

rm -rf "$TMP_REF"
