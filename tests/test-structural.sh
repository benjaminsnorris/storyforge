#!/bin/bash
# test-structural.sh — Tests for structural scoring engine

PY="import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python')"

# ============================================================================
# score_completeness
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_completeness

scenes = _read_csv_as_map('${FIXTURE_DIR}/reference/scenes.csv')
intent = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-intent.csv')
briefs = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-briefs.csv')

result = score_completeness(scenes, intent, briefs)
score = result['score']
findings = result['findings']

assert 0 <= score <= 1, f'Score out of range: {score}'
assert isinstance(findings, list)
print(f'score={score:.2f}')
print(f'findings={len(findings)}')
print('ok')
")
assert_contains "$RESULT" "ok" "score_completeness: returns score and findings"
assert_contains "$RESULT" "score=" "score_completeness: score is a float"

# ============================================================================
# score_completeness: fully-briefed scenes score higher
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.structural import score_completeness

# Two fully-specified scenes
full_scenes = {'s1': {'id': 's1'}, 's2': {'id': 's2'}}
full_intent = {
    's1': {'id': 's1', 'function': 'Hook', 'value_at_stake': 'truth', 'value_shift': '+/-', 'emotional_arc': 'calm to tense', 'mice_threads': '+inquiry:x'},
    's2': {'id': 's2', 'function': 'Climax', 'value_at_stake': 'life', 'value_shift': '-/+', 'emotional_arc': 'tense to resolved', 'mice_threads': '-inquiry:x'},
}
full_briefs = {
    's1': {'id': 's1', 'goal': 'G', 'conflict': 'C', 'outcome': 'O', 'crisis': 'Cr', 'decision': 'D',
            'knowledge_in': 'ki', 'knowledge_out': 'ko', 'key_actions': 'ka', 'key_dialogue': 'kd',
            'emotions': 'e', 'motifs': 'm', 'continuity_deps': 'cd'},
    's2': {'id': 's2', 'goal': 'G', 'conflict': 'C', 'outcome': 'O', 'crisis': 'Cr', 'decision': 'D',
            'knowledge_in': 'ki', 'knowledge_out': 'ko', 'key_actions': 'ka', 'key_dialogue': 'kd',
            'emotions': 'e', 'motifs': 'm', 'continuity_deps': 'cd'},
}
result = score_completeness(full_scenes, full_intent, full_briefs)
print(f'score={result[\"score\"]:.2f}')
print(f'findings={len(result[\"findings\"])}')
")
assert_contains "$RESULT" "score=1.00" "score_completeness: fully-briefed scenes score 1.0"
assert_contains "$RESULT" "findings=0" "score_completeness: fully-briefed scenes have no findings"

# ============================================================================
# score_completeness: empty scenes produce findings
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.structural import score_completeness

empty_scenes = {'e1': {'id': 'e1'}}
empty_intent = {'e1': {'id': 'e1'}}
empty_briefs = {'e1': {'id': 'e1'}}
result = score_completeness(empty_scenes, empty_intent, empty_briefs)
score = result['score']
findings = result['findings']

print(f'score={score:.2f}')
print(f'finding_count={len(findings)}')
# Should have at least an important finding for missing required fields
severities = [f['severity'] for f in findings]
print(f'has_important={\"important\" in severities}')
print(f'has_minor={\"minor\" in severities}')
")
assert_contains "$RESULT" "score=0.00" "score_completeness: empty scene scores 0"
assert_contains "$RESULT" "has_important=True" "score_completeness: empty scene has important finding"
assert_contains "$RESULT" "has_minor=True" "score_completeness: empty scene has minor finding for enrichment"

# ============================================================================
# score_completeness: scenes missing from intent/briefs handled gracefully
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.structural import score_completeness

scenes = {'orphan': {'id': 'orphan'}}
intent = {}
briefs = {}
result = score_completeness(scenes, intent, briefs)
print(f'score={result[\"score\"]:.2f}')
print(f'findings={len(result[\"findings\"])}')
print('ok')
")
assert_contains "$RESULT" "score=0.00" "score_completeness: orphan scene scores 0"
assert_contains "$RESULT" "ok" "score_completeness: missing intent/briefs handled gracefully"

# ============================================================================
# score_completeness: fixture data produces expected range
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_completeness

scenes = _read_csv_as_map('${FIXTURE_DIR}/reference/scenes.csv')
intent = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-intent.csv')
briefs = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-briefs.csv')

result = score_completeness(scenes, intent, briefs)
score = result['score']

# Fixture has: 6 scenes, 6 intents (all populated), 4 brief rows (3 full, 1 empty)
# So intent fields should be mostly populated, brief fields partially
# Score should be moderate — not 0 (intent is there) and not 1 (briefs incomplete)
assert 0.3 < score < 0.9, f'Fixture score out of expected range: {score}'
print(f'score={score:.2f}')
# Should have findings for scenes missing brief data
important_findings = [f for f in result['findings'] if f['severity'] == 'important']
assert len(important_findings) > 0, 'Expected at least one important finding'
print(f'important={len(important_findings)}')
print('ok')
")
assert_contains "$RESULT" "ok" "score_completeness: fixture data in expected range"

# ============================================================================
# score_thematic_concentration
# ============================================================================

THEME_DIR="${TMPDIR}/theme-test/reference"
mkdir -p "$THEME_DIR"
cat > "${THEME_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
s01|test|action|flat|truth|+/-|revelation|A|A|
s02|test|action|flat|truth|-/+|revelation|A|A|
s03|test|action|flat|justice|+/-|action|A|A|
s04|test|action|flat|safety|-/+|revelation|A|A|
s05|test|action|flat|justice|+/-|action|A|A|
s06|test|action|flat|truth|-/+|revelation|A|A|
CSV

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_thematic_concentration
intent = _read_csv_as_map('${THEME_DIR}/scene-intent.csv')
result = score_thematic_concentration(intent)
print(f'score={result[\"score\"]:.2f}')
assert result['score'] > 0.6, f'Expected > 0.6, got {result[\"score\"]}'
print('ok')
")
assert_contains "$RESULT" "ok" "score_thematic_concentration: focused novel scores high"

# Scattered novel: 20 unique values in 20 scenes, no dominance
printf 'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n' > "${THEME_DIR}/scene-intent.csv"
for i in $(seq 1 20); do
    printf 's%02d|test|action|flat|value-%d|+/-|revelation|A|A|\n' "$i" "$i" >> "${THEME_DIR}/scene-intent.csv"
done

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_thematic_concentration
intent = _read_csv_as_map('${THEME_DIR}/scene-intent.csv')
result = score_thematic_concentration(intent)
# 20 unique values, each appearing once — no concentration at all
assert result['score'] < 0.5, f'Expected < 0.5, got {result[\"score\"]}'
print('ok')
")
assert_contains "$RESULT" "ok" "score_thematic_concentration: scattered novel scores low"
rm -rf "${TMPDIR}/theme-test"

# ============================================================================
# score_pacing
# ============================================================================

PACE_DIR="${TMPDIR}/pace-test/reference"
mkdir -p "$PACE_DIR"
cat > "${PACE_DIR}/scenes.csv" <<'CSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
s01|1|One|1|A|X|1|morning|1h|action|drafted|2000|2000
s02|2|Two|1|A|X|1|afternoon|1h|character|drafted|2000|2000
s03|3|Three|1|A|X|2|morning|1h|action|drafted|2000|2000
s04|4|Four|2|A|X|2|afternoon|1h|character|drafted|2000|2000
s05|5|Five|2|A|X|3|morning|1h|action|drafted|2000|2000
s06|6|Six|2|A|X|3|afternoon|1h|confrontation|drafted|2000|2000
s07|7|Seven|3|A|X|4|morning|1h|action|drafted|2000|2000
s08|8|Eight|3|A|X|4|afternoon|1h|character|drafted|2000|2000
CSV
cat > "${PACE_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
s01|setup|action|calm to tense|truth|+/-|revelation|A|A|
s02|process|sequel|tense to calm|truth|-/+|revelation|A|A|
s03|complicate|action|calm to shock|safety|+/-|action|A|A|
s04|react|sequel|shock to resolve|safety|-/+|revelation|A|A|
s05|escalate|action|resolve to dread|justice|-/--|action|A|A|
s06|crisis|action|dread to despair|justice|-/--|action|A|A|
s07|climax|action|despair to triumph|truth|-/+|action|A|A|
s08|resolve|sequel|triumph to peace|truth|+/+|revelation|A|A|
CSV
cat > "${PACE_DIR}/scene-briefs.csv" <<'CSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
s01|g|c|no-and|cr|d|k|k|a|d|e|m||false
s02|g|c|yes|cr|d|k|k|a|d|e|m||false
s03|g|c|no-and|cr|d|k|k|a|d|e|m||false
s04|g|c|yes-but|cr|d|k|k|a|d|e|m||false
s05|g|c|no-and|cr|d|k|k|a|d|e|m||false
s06|g|c|no|cr|d|k|k|a|d|e|m||false
s07|g|c|yes|cr|d|k|k|a|d|e|m||false
s08|g|c|yes|cr|d|k|k|a|d|e|m||false
CSV

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_pacing
scenes = _read_csv_as_map('${PACE_DIR}/scenes.csv')
intent = _read_csv_as_map('${PACE_DIR}/scene-intent.csv')
briefs = _read_csv_as_map('${PACE_DIR}/scene-briefs.csv')
result = score_pacing(scenes, intent, briefs)
print(f'score={result[\"score\"]:.2f}')
assert result['score'] > 0.4, f'Expected > 0.4, got {result[\"score\"]}'
assert isinstance(result['findings'], list)
print('ok')
")
assert_contains "$RESULT" "ok" "score_pacing: well-paced novel scores above 0.4"
rm -rf "${TMPDIR}/pace-test"

# ============================================================================
# _classify_arc_shape
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.structural import _classify_arc_shape

# All negative shifts = tragedy, 0 reversals
shape, rev, comp = _classify_arc_shape(['+/-', '+/-', '+/-'])
assert shape == 'tragedy', f'Expected tragedy, got {shape}'
assert rev == 0, f'Expected 0 reversals, got {rev}'
assert comp == False

# All positive shifts = rags-to-riches
shape, rev, comp = _classify_arc_shape(['-/+', '-/+', '-/+'])
assert shape == 'rags-to-riches', f'Expected rags-to-riches, got {shape}'
assert rev == 0

# One reversal, first half negative = man-in-a-hole
shape, rev, comp = _classify_arc_shape(['+/-', '+/-', '-/+', '-/+'])
assert shape == 'man-in-a-hole', f'Expected man-in-a-hole, got {shape}'
assert rev == 1

# One reversal, first half positive = icarus
shape, rev, comp = _classify_arc_shape(['-/+', '-/+', '+/-', '+/-'])
assert shape == 'icarus', f'Expected icarus, got {shape}'
assert rev == 1

# Two+ reversals ending positive = cinderella
shape, rev, comp = _classify_arc_shape(['+/-', '-/+', '+/-', '-/+'])
assert shape == 'cinderella', f'Expected cinderella, got {shape}'
assert rev == 3
assert comp == True

# Two+ reversals ending negative = oedipus
shape, rev, comp = _classify_arc_shape(['-/+', '+/-', '-/+', '+/-'])
assert shape == 'oedipus', f'Expected oedipus, got {shape}'
assert rev == 3

# Empty/unknown shifts = flat
shape, rev, comp = _classify_arc_shape(['', '', ''])
assert shape == 'flat', f'Expected flat, got {shape}'

print('ok')
")
assert_contains "$RESULT" "ok" "_classify_arc_shape: correctly classifies all six archetypes"

# ============================================================================
# score_arcs
# ============================================================================

ARC_DIR="${TMPDIR}/arc-test/reference"
mkdir -p "$ARC_DIR"
cat > "${ARC_DIR}/scenes.csv" <<'CSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
s01|1|One|1|alice|X|1|morning|1h|action|drafted|2000|2000
s02|2|Two|1|alice|X|1|afternoon|1h|character|drafted|2000|2000
s03|3|Three|1|bob|X|2|morning|1h|action|drafted|2000|2000
s04|4|Four|2|alice|X|2|afternoon|1h|action|drafted|2000|2000
s05|5|Five|2|bob|X|3|morning|1h|action|drafted|2000|2000
s06|6|Six|2|alice|X|3|afternoon|1h|action|drafted|2000|2000
s07|7|Seven|3|bob|X|4|morning|1h|action|drafted|2000|2000
s08|8|Eight|3|alice|X|4|afternoon|1h|action|drafted|2000|2000
CSV
cat > "${ARC_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
s01|setup|action|calm to tense|truth|+/-|revelation|alice|alice|
s02|react|sequel|tense to hope|justice|-/+|revelation|alice|alice|
s03|investigate|action|neutral to neutral|truth|+/-|revelation|bob|bob|
s04|escalate|action|hope to despair|safety|+/-|action|alice|alice|
s05|continue|action|neutral to neutral|truth|+/-|revelation|bob|bob|
s06|reverse|action|despair to resolve|trust|-/+|action|alice|alice|
s07|continue|action|neutral to neutral|truth|+/-|revelation|bob|bob|
s08|triumph|action|resolve to peace|truth|-/+|revelation|alice|alice|
CSV

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_arcs
scenes = _read_csv_as_map('${ARC_DIR}/scenes.csv')
intent = _read_csv_as_map('${ARC_DIR}/scene-intent.csv')
result = score_arcs(scenes, intent)
print(f'score={result[\"score\"]:.2f}')
alice_arc = [c for c in result.get('character_arcs', []) if c['character'] == 'alice']
bob_arc = [c for c in result.get('character_arcs', []) if c['character'] == 'bob']
if alice_arc and bob_arc:
    assert alice_arc[0]['arc_score'] > bob_arc[0]['arc_score'], 'Alice should score higher than Bob'
    print('alice_beats_bob=true')
print('ok')
")
assert_contains "$RESULT" "ok" "score_arcs: returns valid result"
assert_contains "$RESULT" "alice_beats_bob=true" "score_arcs: varied arc beats flat arc"
rm -rf "${TMPDIR}/arc-test"

# ============================================================================
# score_character_presence
# ============================================================================

CHAR_DIR="${TMPDIR}/char-test/reference"
mkdir -p "$CHAR_DIR"
cat > "${CHAR_DIR}/scenes.csv" <<'CSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
s01|1|One|1|alice|X|1|morning|1h|action|drafted|2000|2000
s02|2|Two|1|alice|X|1|afternoon|1h|action|drafted|2000|2000
s03|3|Three|1|alice|X|2|morning|1h|action|drafted|2000|2000
s04|4|Four|2|alice|X|2|afternoon|1h|action|drafted|2000|2000
s05|5|Five|2|alice|X|3|morning|1h|action|drafted|2000|2000
s06|6|Six|3|alice|X|3|afternoon|1h|action|drafted|2000|2000
CSV
cat > "${CHAR_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
s01|test|action|flat|truth|+/-|revelation|alice;bob;villain|alice;bob|
s02|test|action|flat|truth|+/-|revelation|alice;bob|alice|
s03|test|action|flat|truth|+/-|revelation|alice;villain|alice;villain|
s04|test|action|flat|truth|+/-|revelation|alice|alice|
s05|test|action|flat|truth|+/-|revelation|alice;bob|alice;bob|
s06|test|action|flat|truth|+/-|revelation|alice;villain|alice;villain|
CSV
cat > "${CHAR_DIR}/characters.csv" <<'CSV'
id|name|role|aliases
alice|Alice|protagonist|
bob|Bob|supporting|
villain|Villain|antagonist|
CSV

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_character_presence
scenes = _read_csv_as_map('${CHAR_DIR}/scenes.csv')
intent = _read_csv_as_map('${CHAR_DIR}/scene-intent.csv')
result = score_character_presence(scenes, intent, '${CHAR_DIR}')
assert 0 <= result['score'] <= 1
print('ok')
")
assert_contains "$RESULT" "ok" "score_character_presence: returns valid score"
rm -rf "${TMPDIR}/char-test"

# ============================================================================
# score_character_presence: fixture data
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_character_presence
scenes = _read_csv_as_map('${FIXTURE_DIR}/reference/scenes.csv')
intent = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-intent.csv')
result = score_character_presence(scenes, intent, '${FIXTURE_DIR}/reference')
assert 0 <= result['score'] <= 1
assert isinstance(result['findings'], list)
print(f'score={result[\"score\"]:.2f}')
print('ok')
")
assert_contains "$RESULT" "ok" "score_character_presence: fixture data returns valid score"

# ============================================================================
# score_function_variety
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_function_variety
intent = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-intent.csv')
briefs = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-briefs.csv')
result = score_function_variety(intent, briefs)
assert 0 <= result['score'] <= 1
assert isinstance(result['findings'], list)
print('ok')
")
assert_contains "$RESULT" "ok" "score_function_variety: returns valid score on fixtures"

# ============================================================================
# score_mice_health
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_mice_health
scenes = _read_csv_as_map('${FIXTURE_DIR}/reference/scenes.csv')
intent = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-intent.csv')
result = score_mice_health(scenes, intent)
assert 0 <= result['score'] <= 1
print(f'score={result[\"score\"]:.2f}')
print('ok')
")
assert_contains "$RESULT" "ok" "score_mice_health: returns valid score on fixtures"

# ============================================================================
# score_knowledge_chain
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_knowledge_chain
scenes = _read_csv_as_map('${FIXTURE_DIR}/reference/scenes.csv')
briefs = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-briefs.csv')
result = score_knowledge_chain(scenes, briefs)
assert 0 <= result['score'] <= 1
assert isinstance(result['findings'], list)
print('ok')
")
assert_contains "$RESULT" "ok" "score_knowledge_chain: returns valid score on fixtures"

# ============================================================================
# structural_score (full orchestrator)
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.structural import structural_score

report = structural_score('${FIXTURE_DIR}/reference')
assert 'overall_score' in report, 'Missing overall_score'
assert 'dimensions' in report, 'Missing dimensions'
assert len(report['dimensions']) == 8, f'Expected 8 dimensions, got {len(report[\"dimensions\"])}'

names = [d['name'] for d in report['dimensions']]
for expected in ['arc_completeness', 'thematic_concentration', 'pacing_shape',
                 'character_presence', 'mice_health', 'knowledge_chain',
                 'function_variety', 'completeness']:
    assert expected in names, f'Missing dimension: {expected}'

print(f'overall={report[\"overall_score\"]:.2f}')
print(f'dims={len(report[\"dimensions\"])}')
print('ok')
")
assert_contains "$RESULT" "dims=8" "structural_score: returns all 8 dimensions"
assert_contains "$RESULT" "ok" "structural_score: orchestrator runs on fixtures"

# ============================================================================
# format_scorecard
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.structural import structural_score, format_scorecard

report = structural_score('${FIXTURE_DIR}/reference')
card = format_scorecard(report)
assert 'Structural Score' in card
assert 'Arc Completeness' in card
assert 'Pacing Shape' in card
print('ok')
")
assert_contains "$RESULT" "ok" "format_scorecard: produces readable output"

# ============================================================================
# format_diagnosis
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.structural import structural_score, format_diagnosis

report = structural_score('${FIXTURE_DIR}/reference')
full = format_diagnosis(report, 'full')
coach = format_diagnosis(report, 'coach')
strict = format_diagnosis(report, 'strict')
assert isinstance(full, str)
assert isinstance(coach, str)
assert isinstance(strict, str)
print('ok')
")
assert_contains "$RESULT" "ok" "format_diagnosis: all coaching levels produce output"

# format_diagnosis content checks
DIAG_DIR="${TMPDIR}/diag-test/reference"
mkdir -p "$DIAG_DIR"
cat > "${DIAG_DIR}/scenes.csv" <<'CSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
s01|1|One|1|alice|X|1|morning|1h|action|drafted|2000|2000
s02|2|Two|1|alice|X|1|afternoon|1h|action|drafted|2000|2000
s03|3|Three|1|alice|X|2|morning|1h|action|drafted|2000|2000
s04|4|Four|1|alice|X|2|afternoon|1h|action|drafted|2000|2000
s05|5|Five|1|alice|X|3|morning|1h|action|drafted|2000|2000
s06|6|Six|1|alice|X|3|afternoon|1h|action|drafted|2000|2000
CSV
cat > "${DIAG_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
s01|test|action|calm|truth|+/-|revelation|alice|alice|
s02|test|action|calm|truth|+/-|revelation|alice|alice|
s03|test|action|calm|truth|+/-|revelation|alice|alice|
s04|test|action|calm|truth|+/-|revelation|alice|alice|
s05|test|action|calm|truth|+/-|revelation|alice|alice|
s06|test|action|calm|truth|+/-|revelation|alice|alice|
CSV
cat > "${DIAG_DIR}/scene-briefs.csv" <<'CSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
s01|g|c|yes-but|cr|d|||a|d|e|m||false
s02|g|c|yes-but|cr|d|||a|d|e|m||false
s03|g|c|yes-but|cr|d|||a|d|e|m||false
s04|g|c|yes-but|cr|d|||a|d|e|m||false
s05|g|c|yes-but|cr|d|||a|d|e|m||false
s06|g|c|yes-but|cr|d|||a|d|e|m||false
CSV

RESULT=$(python3 -c "
${PY}
from storyforge.structural import structural_score, format_diagnosis
report = structural_score('${DIAG_DIR}')
full = format_diagnosis(report, 'full')
coach = format_diagnosis(report, 'coach')
strict = format_diagnosis(report, 'strict')

# Full should have craft explanations and prescriptions
has_why = 'Why this matters' in full
has_what = 'What to do' in full
# Coach should have questions
has_questions = '?' in coach
# Strict should have only data
has_data = 'Structural Data' in strict
no_explanation_in_strict = 'Why this matters' not in strict

print(f'full_why={has_why}')
print(f'full_what={has_what}')
print(f'coach_questions={has_questions}')
print(f'strict_data={has_data}')
print(f'strict_no_explain={no_explanation_in_strict}')
print('ok')
" 2>&1)
assert_contains "$RESULT" "full_why=True" "format_diagnosis: full mode has craft explanations"
assert_contains "$RESULT" "full_what=True" "format_diagnosis: full mode has prescriptions"
assert_contains "$RESULT" "coach_questions=True" "format_diagnosis: coach mode has questions"
assert_contains "$RESULT" "strict_data=True" "format_diagnosis: strict mode has data header"
assert_contains "$RESULT" "strict_no_explain=True" "format_diagnosis: strict mode has no explanations"
rm -rf "${TMPDIR}/diag-test"

# ============================================================================
# save_structural_scores + load_previous_scores
# ============================================================================

SAVE_DIR="${TMPDIR}/save-test"
mkdir -p "$SAVE_DIR"

RESULT=$(python3 -c "
${PY}
from storyforge.structural import structural_score, save_structural_scores, load_previous_scores

# First run — no previous scores
prev = load_previous_scores('${SAVE_DIR}')
assert prev is None, 'Expected None for first run'

# Generate scores from fixtures
report = structural_score('${FIXTURE_DIR}/reference')

# Save
path = save_structural_scores(report, '${SAVE_DIR}')
assert path is not None

# Load back
prev = load_previous_scores('${SAVE_DIR}')
assert prev is not None
assert 'arc_completeness' in prev
assert 'overall' in prev
assert abs(prev['overall'] - report['overall_score']) < 0.001

print(f'saved={path is not None}')
print(f'loaded={prev is not None}')
print(f'dims={len([k for k in prev if k != \"overall\"])}')
print('ok')
")
assert_contains "$RESULT" "ok" "save/load structural scores: roundtrip works"
assert_contains "$RESULT" "dims=8" "save/load structural scores: all 8 dimensions persisted"

# Second run — should have previous scores
RESULT=$(python3 -c "
${PY}
from storyforge.structural import structural_score, save_structural_scores, load_previous_scores, format_scorecard

prev = load_previous_scores('${SAVE_DIR}')
assert prev is not None, 'Expected previous scores'

report = structural_score('${FIXTURE_DIR}/reference')
card = format_scorecard(report, previous=prev)
assert 'no change' in card or '▲' in card or '▼' in card, f'Expected deltas in scorecard'
print('ok')
")
assert_contains "$RESULT" "ok" "format_scorecard: shows deltas with previous scores"

rm -rf "$SAVE_DIR"

# ============================================================================
# fix_location in findings
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.structural import structural_score

report = structural_score('${FIXTURE_DIR}/reference')
for dim in report['dimensions']:
    for f in dim['findings']:
        assert 'fix_location' in f, f'Missing fix_location in {dim[\"name\"]}: {f[\"message\"]}'
        assert f['fix_location'] in ('structural', 'intent', 'brief', 'registry'), \
            f'Bad fix_location \"{f[\"fix_location\"]}\" in {dim[\"name\"]}: {f[\"message\"]}'
print('ok')
")
assert_contains "$RESULT" "ok" "fix_location: all findings have valid fix_location"

# ============================================================================
# generate_structural_proposals
# ============================================================================

PROP_DIR="${TMPDIR}/proposal-test"
mkdir -p "${PROP_DIR}/reference" "${PROP_DIR}/working/scores"

# Create fixtures that will score below target
cat > "${PROP_DIR}/reference/scenes.csv" <<'CSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
s01|1|One|1|alice|X|1|morning|1h|action|drafted|2000|2000
s02|2|Two|1|alice|X|1|afternoon|1h|action|drafted|2000|2000
s03|3|Three|1|alice|X|2|morning|1h|action|drafted|2000|2000
s04|4|Four|1|alice|X|2|afternoon|1h|action|drafted|2000|2000
CSV
cat > "${PROP_DIR}/reference/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
s01|test|action|calm|truth|+/-|revelation|alice|alice|
s02|test|action|calm|truth|+/-|revelation|alice|alice|
s03|test|action|calm|truth|+/-|revelation|alice|alice|
s04|test|action|calm|truth|+/-|revelation|alice|alice|
CSV
cat > "${PROP_DIR}/reference/scene-briefs.csv" <<'CSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
s01|g|c|yes-but|cr|d|||a|d|e|m||false
s02|g|c|yes-but|cr|d|||a|d|e|m||false
s03|g|c|yes-but|cr|d|||a|d|e|m||false
s04|g|c|yes-but|cr|d|||a|d|e|m||false
CSV

RESULT=$(python3 -c "
${PY}
from storyforge.structural import structural_score, generate_structural_proposals
import os

report = structural_score('${PROP_DIR}/reference')
path = generate_structural_proposals(report, '${PROP_DIR}/working/scores')
assert path is not None
assert os.path.isfile(path)

# Read back proposals
with open(path) as f:
    lines = [l.strip() for l in f if l.strip()]
header = lines[0]
rows = lines[1:]
print(f'proposals={len(rows)}')
assert 'id|dimension|fix_location' in header
assert len(rows) >= 1, f'Expected at least 1 proposal, got {len(rows)}'
# Check fix_location is populated
for row in rows:
    fields = row.split('|')
    assert fields[2] in ('structural', 'intent', 'brief', 'registry'), f'Bad fix_location: {fields[2]}'
print('fix_locations_valid=true')
print('ok')
")
assert_contains "$RESULT" "ok" "generate_structural_proposals: creates proposals CSV"
assert_contains "$RESULT" "fix_locations_valid=true" "generate_structural_proposals: all fix_locations valid"
rm -rf "${PROP_DIR}"

# ============================================================================
# generate_structural_proposals: no proposals when all above target
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.structural import generate_structural_proposals

# Fake report where all dimensions are above target
report = {
    'overall_score': 0.90,
    'dimensions': [
        {'name': 'completeness', 'score': 0.95, 'target': 0.80, 'findings': []},
        {'name': 'thematic_concentration', 'score': 0.85, 'target': 0.60, 'findings': []},
        {'name': 'pacing_shape', 'score': 0.80, 'target': 0.75, 'findings': []},
        {'name': 'arc_completeness', 'score': 0.90, 'target': 0.80, 'findings': []},
        {'name': 'character_presence', 'score': 0.85, 'target': 0.70, 'findings': []},
        {'name': 'mice_health', 'score': 0.75, 'target': 0.60, 'findings': []},
        {'name': 'knowledge_chain', 'score': 0.70, 'target': 0.60, 'findings': []},
        {'name': 'function_variety', 'score': 0.80, 'target': 0.65, 'findings': []},
    ],
}
path = generate_structural_proposals(report, '${TMPDIR}/no-proposals')
assert path is None, f'Expected None when all above target, got {path}'
print('ok')
")
assert_contains "$RESULT" "ok" "generate_structural_proposals: returns None when all above target"

# ============================================================================
# print_score_delta: formats before/after comparison
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.structural import print_score_delta

pre = {
    'arc_completeness': {'score': 0.80, 'target': 0.80},
    'thematic_concentration': {'score': 0.30, 'target': 0.60},
    'pacing_shape': {'score': 0.62, 'target': 0.75},
}
post = {
    'arc_completeness': {'score': 0.85, 'target': 0.80},
    'thematic_concentration': {'score': 0.50, 'target': 0.60},
    'pacing_shape': {'score': 0.62, 'target': 0.75},
}

output = print_score_delta(pre, post)
print(output)
")
assert_contains "$RESULT" "arc_completeness" "print_score_delta: includes dimension names"
assert_contains "$RESULT" "+0.05" "print_score_delta: shows positive delta"
assert_contains "$RESULT" "+0.20" "print_score_delta: shows thematic improvement"
assert_contains "$RESULT" "0.00" "print_score_delta: shows no-change"
