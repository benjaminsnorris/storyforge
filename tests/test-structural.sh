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
