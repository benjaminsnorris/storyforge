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

# ============================================================================
# Briefs domain: hone_briefs integration
# ============================================================================

echo "--- briefs: hone_briefs detects and reports abstract scenes ---"

RESULT=$(python3 -c "
${PY}
import os, tempfile, shutil
from storyforge.hone import hone_briefs
from storyforge.elaborate import _read_csv, _write_csv, _FILE_MAP

# Create temp project with abstract briefs
tmpdir = tempfile.mkdtemp()
ref = os.path.join(tmpdir, 'reference')
shutil.copytree('${FIXTURE_DIR}/reference', ref)

# Inject abstract key_actions into a scene
briefs_path = os.path.join(ref, 'scene-briefs.csv')
rows = _read_csv(briefs_path)
for r in rows:
    if r['id'] == 'act1-sc01':
        r['key_actions'] = 'The realization dawns; she connects to the deeper pattern; the parallel emerges'
_write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])

# Run detection only (dry_run=True)
result = hone_briefs(ref, tmpdir, dry_run=True)
print(f'flagged={result[\"scenes_flagged\"]}')
print('ok')

shutil.rmtree(tmpdir)
" 2>/dev/null)

assert_contains "$RESULT" "flagged=1" "briefs: detects 1 abstract scene"
assert_contains "$RESULT" "ok" "briefs: hone_briefs runs in dry-run mode"

echo "--- briefs: strict coaching saves analysis ---"

RESULT=$(python3 -c "
${PY}
import os, tempfile, shutil
from storyforge.hone import hone_briefs
from storyforge.elaborate import _read_csv, _write_csv, _FILE_MAP

tmpdir = tempfile.mkdtemp()
ref = os.path.join(tmpdir, 'reference')
shutil.copytree('${FIXTURE_DIR}/reference', ref)

briefs_path = os.path.join(ref, 'scene-briefs.csv')
rows = _read_csv(briefs_path)
for r in rows:
    if r['id'] == 'act1-sc01':
        r['key_actions'] = 'The realization dawns; she connects to the deeper pattern; the parallel emerges'
_write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])

result = hone_briefs(ref, tmpdir, coaching_level='strict')
analysis_path = os.path.join(tmpdir, 'working', 'hone', 'briefs-analysis-act1-sc01.md')
exists = os.path.isfile(analysis_path)
print(f'analysis_exists={exists}')
print(f'rewritten={result[\"scenes_rewritten\"]}')
print('ok')

shutil.rmtree(tmpdir)
" 2>/dev/null)

assert_contains "$RESULT" "analysis_exists=True" "briefs: strict saves analysis file"
assert_contains "$RESULT" "rewritten=0" "briefs: strict does not rewrite"
assert_contains "$RESULT" "ok" "briefs: strict coaching runs"

# ============================================================================
# Gaps domain: detect missing fields
# ============================================================================

echo "--- gaps: detects missing required fields ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_gaps

scenes_map = {
    's1': {'id': 's1', 'status': 'briefed', 'seq': '1'},
}
briefs_map = {
    's1': {'id': 's1', 'goal': 'Do the thing', 'conflict': '', 'outcome': 'yes',
            'crisis': '', 'decision': 'decides'},
}
intent_map = {
    's1': {'id': 's1', 'function': 'Hook', 'value_at_stake': '', 'value_shift': '+/-',
            'emotional_arc': 'calm to tense'},
}

results = detect_gaps(scenes_map, intent_map, briefs_map)
fields = [r['field'] for r in results if r['scene_id'] == 's1']
assert 'conflict' in fields, f'conflict not flagged: {fields}'
assert 'crisis' in fields, f'crisis not flagged: {fields}'
print(f'gaps={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "gaps: detect_gaps runs"
assert_contains "$RESULT" "gaps=" "gaps: returns gap list"

echo "--- gaps: no gaps for complete scene ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_gaps

scenes_map = {
    's1': {'id': 's1', 'status': 'briefed', 'seq': '1'},
}
briefs_map = {
    's1': {'id': 's1', 'goal': 'Do it', 'conflict': 'Obstacle', 'outcome': 'yes',
            'crisis': 'Now or never', 'decision': 'Now'},
}
intent_map = {
    's1': {'id': 's1', 'function': 'Hook', 'value_at_stake': 'truth',
            'value_shift': '+/-', 'emotional_arc': 'calm to tense'},
}

results = detect_gaps(scenes_map, intent_map, briefs_map)
print(f'gaps={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "gaps=0" "gaps: no gaps for complete scene"
assert_contains "$RESULT" "ok" "gaps: complete scene runs"

echo "--- gaps: skips spine-status scenes ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_gaps

scenes_map = {
    's1': {'id': 's1', 'status': 'spine', 'seq': '1'},
}
briefs_map = {'s1': {'id': 's1'}}
intent_map = {'s1': {'id': 's1'}}

results = detect_gaps(scenes_map, intent_map, briefs_map)
print(f'gaps={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "gaps=0" "gaps: skips spine-status scenes"
assert_contains "$RESULT" "ok" "gaps: spine skip runs"

# ============================================================================
# Briefs domain: over-specification detection
# ============================================================================

echo "--- overspecified: flags too many beats for word count ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_overspecified

briefs = {
    's1': {'id': 's1', 'key_actions': 'a; b; c; d; e; f; g', 'emotions': 'x;y'},
}
scenes = {
    's1': {'id': 's1', 'target_words': '1500'},
}
results = detect_overspecified(briefs, scenes)
fields = [(r['field'], r['beat_count']) for r in results]
assert ('key_actions', 7) in fields, f'key_actions not flagged: {fields}'
print(f'issues={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "issues=1" "overspecified: flags 7 beats in 1500 words"
assert_contains "$RESULT" "ok" "overspecified: detection runs"

echo "--- overspecified: does not flag reasonable beat count ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_overspecified

briefs = {
    's1': {'id': 's1', 'key_actions': 'Enters room; Finds letter; Leaves', 'emotions': 'tension;calm'},
}
scenes = {
    's1': {'id': 's1', 'target_words': '2500'},
}
results = detect_overspecified(briefs, scenes)
print(f'issues={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "issues=0" "overspecified: 3 beats in 2500 words is fine"
assert_contains "$RESULT" "ok" "overspecified: clean scene runs"

echo "--- overspecified: flags excessive emotion beats ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_overspecified

briefs = {
    's1': {'id': 's1', 'key_actions': 'Does thing', 'emotions': 'competence;unease;self-doubt;resolve'},
}
scenes = {
    's1': {'id': 's1', 'target_words': '2500'},
}
results = detect_overspecified(briefs, scenes)
fields = [r['field'] for r in results]
assert 'emotions' in fields, f'emotions not flagged: {fields}'
print(f'issues={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "issues=1" "overspecified: flags 4-beat emotions"
assert_contains "$RESULT" "ok" "overspecified: emotion detection runs"

echo "--- overspecified: absolute threshold catches high beats even with high word count ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_overspecified

briefs = {
    's1': {'id': 's1', 'key_actions': 'a; b; c; d; e; f; g; h', 'emotions': 'x;y'},
}
scenes = {
    's1': {'id': 's1', 'target_words': '8000'},
}
results = detect_overspecified(briefs, scenes)
fields = [r['field'] for r in results]
assert 'key_actions' in fields, f'key_actions not flagged: {fields}'
print(f'issues={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "issues=1" "overspecified: 8 beats flagged even at 8000 words"
assert_contains "$RESULT" "ok" "overspecified: absolute threshold runs"

# ============================================================================
# Briefs domain: verbose/prose-like field detection
# ============================================================================

echo "--- verbose: flags paragraph-style decision ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_verbose_fields

briefs = {
    's1': {
        'id': 's1',
        'decision': 'They hold. Naji breaks her deal and stands with the community. The Hunter kills her — not erasure but death. She dies while every mind holds her name.',
    },
}
results = detect_verbose_fields(briefs)
fields = [r['field'] for r in results]
assert 'decision' in fields, f'decision not flagged: {fields}'
print(f'issues={len(results)}')
print(f'chars={results[0][\"char_count\"]}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "issues=1" "verbose: flags paragraph decision"
assert_contains "$RESULT" "ok" "verbose: detection runs"

echo "--- verbose: does not flag terse fields ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_verbose_fields

briefs = {
    's1': {
        'id': 's1',
        'decision': 'She goes through the door',
        'goal': 'Find the map',
        'conflict': 'Guards block the entrance',
        'crisis': 'Now or never',
        'key_actions': 'Opens door; Runs; Grabs map',
        'emotions': 'fear;relief',
    },
}
results = detect_verbose_fields(briefs)
print(f'issues={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "issues=0" "verbose: terse fields pass"
assert_contains "$RESULT" "ok" "verbose: terse detection runs"

echo "--- verbose: flags extracted key_actions with prose clauses ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_verbose_fields

briefs = {
    's1': {
        'id': 's1',
        'key_actions': 'Chopping onions; crying; Tarek working beside her silently; Suki arriving and sitting at the counter without speaking; the rhythm of the knife; the truth assembling — the isolated vanish, and Suki came here instead of being alone',
    },
}
results = detect_verbose_fields(briefs)
fields = [r['field'] for r in results]
assert 'key_actions' in fields, f'key_actions not flagged: {fields}'
print(f'issues={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "issues=1" "verbose: flags extracted prose key_actions"
assert_contains "$RESULT" "ok" "verbose: extracted data detection runs"

# ============================================================================
# Combined detection: detect_brief_issues
# ============================================================================

echo "--- combined: detect_brief_issues finds all issue types ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_brief_issues

briefs = {
    's1': {
        'id': 's1',
        'key_actions': 'The realization dawns; connecting deeper; the parallel emerging; crystallizing; the truth building; she transforms',
        'decision': 'They hold. Naji breaks her deal and stands with the community. The Hunter kills her — not erasure but death. She dies while every mind holds her name.',
        'emotions': 'hope;dread;resolve;calm',
        'crisis': 'Stay or go',
        'goal': 'Find truth',
        'conflict': 'Opposition',
    },
}
scenes = {
    's1': {'id': 's1', 'target_words': '1500'},
}
issues = detect_brief_issues(briefs, scenes)
types = set(i['issue'] for i in issues)
assert 'abstract' in types, f'abstract not found: {types}'
assert 'overspecified' in types, f'overspecified not found: {types}'
assert 'verbose' in types, f'verbose not found: {types}'
print(f'total={len(issues)}')
print(f'types={sorted(types)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "combined: detect_brief_issues runs"
assert_contains "$RESULT" "abstract" "combined: finds abstract issues"
assert_contains "$RESULT" "overspecified" "combined: finds overspecified issues"
assert_contains "$RESULT" "verbose" "combined: finds verbose issues"

echo "--- combined: broadened fields include goal and conflict ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import _CONCRETIZABLE_FIELDS
assert 'goal' in _CONCRETIZABLE_FIELDS, f'goal missing: {_CONCRETIZABLE_FIELDS}'
assert 'conflict' in _CONCRETIZABLE_FIELDS, f'conflict missing: {_CONCRETIZABLE_FIELDS}'
assert 'emotions' in _CONCRETIZABLE_FIELDS, f'emotions missing: {_CONCRETIZABLE_FIELDS}'
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "combined: _CONCRETIZABLE_FIELDS includes goal, conflict, emotions"

# ============================================================================
# Subtext field support
# ============================================================================

echo "--- subtext: included in _BRIEFS_COLS ---"

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import _BRIEFS_COLS
assert 'subtext' in _BRIEFS_COLS, f'subtext missing: {_BRIEFS_COLS}'
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "subtext: present in _BRIEFS_COLS"

echo "--- subtext: defined in schema ---"

RESULT=$(python3 -c "
${PY}
from storyforge.schema import COLUMN_SCHEMA
assert 'subtext' in COLUMN_SCHEMA, f'subtext missing from schema'
s = COLUMN_SCHEMA['subtext']
assert s['file'] == 'scene-briefs.csv', f'wrong file: {s[\"file\"]}'
assert s['type'] == 'free_text', f'wrong type: {s[\"type\"]}'
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "subtext: defined in COLUMN_SCHEMA"

echo "--- subtext: verbose detection flags long subtext ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_verbose_fields

briefs = {
    's1': {
        'id': 's1',
        'subtext': 'Zara says she is fine but her synesthesia is worsening and she knows it and everyone around her knows it too but nobody is willing to say it out loud because they are all afraid of what it means for the community and for her specifically.',
    },
}
results = detect_verbose_fields(briefs)
fields = [r['field'] for r in results]
assert 'subtext' in fields, f'subtext not flagged: {fields}'
print(f'issues={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "issues=1" "subtext: verbose detection flags long subtext"
assert_contains "$RESULT" "ok" "subtext: verbose detection runs"

echo "--- subtext: terse subtext not flagged ---"

RESULT=$(python3 -c "
${PY}
from storyforge.hone import detect_verbose_fields

briefs = {
    's1': {
        'id': 's1',
        'subtext': 'Zara says she is fine but means the opposite; show through her hands shaking',
    },
}
results = detect_verbose_fields(briefs)
fields = [r['field'] for r in results]
assert 'subtext' not in fields, f'subtext wrongly flagged: {fields}'
print(f'issues={len(results)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "issues=0" "subtext: terse subtext passes"
assert_contains "$RESULT" "ok" "subtext: terse check runs"

echo "--- subtext: extract parser handles SUBTEXT label ---"

RESULT=$(python3 -c "
${PY}
from storyforge.extract import parse_brief_parallel_response

response = '''GOAL: Find the map
CONFLICT: Guards block the way
OUTCOME: yes-but
CRISIS: Fight or sneak
DECISION: Sneaks past
KEY_ACTIONS: Opens door; Grabs map
KEY_DIALOGUE: Where is it?
EMOTIONS: tension;relief
MOTIFS: maps;darkness
SUBTEXT: She tells the guard she is lost but she knows exactly where she is; show through confident body language that contradicts her words'''

result = parse_brief_parallel_response(response, 'test-scene')
assert 'subtext' in result, f'subtext missing: {list(result.keys())}'
assert 'confident body language' in result['subtext'], f'wrong value: {result[\"subtext\"]}'
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "subtext: extract parser handles SUBTEXT label"

echo "--- subtext: extract parser filters NONE ---"

RESULT=$(python3 -c "
${PY}
from storyforge.extract import parse_brief_parallel_response

response = '''GOAL: Find the map
SUBTEXT: NONE'''

result = parse_brief_parallel_response(response, 'test-scene')
assert 'subtext' not in result, f'NONE should be filtered: {list(result.keys())}'
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "subtext: NONE value filtered in extract"

echo "--- subtext: drafting prompt includes subtext framing ---"

RESULT=$(python3 -c "
${PY}
import os, tempfile, shutil
from storyforge.elaborate import _read_csv, _write_csv, _FILE_MAP

# Create temp project with subtext
tmpdir = tempfile.mkdtemp()
ref = os.path.join(tmpdir, 'reference')
shutil.copytree('${FIXTURE_DIR}/reference', ref)

# Add subtext to act1-sc01
briefs_path = os.path.join(ref, 'scene-briefs.csv')
rows = _read_csv(briefs_path)
for r in rows:
    if r['id'] == 'act1-sc01':
        r['subtext'] = 'Dorren files as error but knows she is lying to the institution; show through the private note, not inner monologue'
_write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])

# Verify column is written and readable
rows2 = _read_csv(briefs_path)
for r in rows2:
    if r['id'] == 'act1-sc01':
        assert 'subtext' in r, f'subtext column missing after write: {list(r.keys())}'
        assert 'lying to the institution' in r['subtext'], f'wrong value: {r[\"subtext\"]}'
        print('ok')
        break

shutil.rmtree(tmpdir)
" 2>/dev/null)

assert_contains "$RESULT" "ok" "subtext: CSV round-trip preserves subtext"

# ============================================================================
# Prose exemplar validation and rhythm signatures
# ============================================================================

echo "--- exemplars: split_sentences handles prose ---"

RESULT=$(python3 -c "
${PY}
from storyforge.exemplars import split_sentences

text = 'The car horn hit me in the chest. Violet. Deep, wet violet, the color of a bruise two days old. I blinked and it was gone. The prep station was just a prep station.'
sents = split_sentences(text)
assert len(sents) >= 3, f'expected >=3, got {len(sents)}: {sents}'
print(f'count={len(sents)}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "count=" "exemplars: splits sentences"
assert_contains "$RESULT" "ok" "exemplars: split_sentences runs"

echo "--- exemplars: compute_rhythm_signature returns metrics ---"

RESULT=$(python3 -c "
${PY}
from storyforge.exemplars import compute_rhythm_signature

text = '''The car horn hit me in the chest before I heard it.
Violet. Deep, wet violet, the color of a bruise two days old, blooming across the stainless steel counter.
I blinked and it was gone.
The prep station was just a prep station again: cutting boards, mise en place, the half-sliced pile of Roma tomatoes.
Outside, the horn blared again. Lighter this time.
I went back to the tomatoes. Knife work was good for this. You could not think about colors when you had eight inches of carbon steel moving through flesh at speed.'''

sig = compute_rhythm_signature(text)
assert sig is not None, 'signature should not be None'
assert 'mean_sentence_words' in sig, f'missing key: {list(sig.keys())}'
assert 'buckets' in sig, 'missing buckets'
assert sig['sentence_count'] >= 5, f'too few sentences: {sig[\"sentence_count\"]}'
assert sig['stddev_sentence_words'] > 0, 'stddev should be positive'
print(f'sentences={sig[\"sentence_count\"]}')
print(f'mean={sig[\"mean_sentence_words\"]}')
print(f'stddev={sig[\"stddev_sentence_words\"]}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "exemplars: rhythm signature computed"
assert_contains "$RESULT" "mean=" "exemplars: has mean"
assert_contains "$RESULT" "stddev=" "exemplars: has stddev"

echo "--- exemplars: format_rhythm_for_prompt produces text ---"

RESULT=$(python3 -c "
${PY}
from storyforge.exemplars import compute_rhythm_signature, format_rhythm_for_prompt

text = 'Short. This is a medium sentence with some words. This is a much longer sentence that goes on and on and really extends the rhythm significantly beyond what you might expect from normal prose. Done.'
sig = compute_rhythm_signature(text)
if sig:
    block = format_rhythm_for_prompt(sig)
    assert 'Rhythm Target' in block, f'missing header: {block[:50]}'
    assert '%' in block, 'missing percentages'
    print('ok')
else:
    print('no_sig')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "exemplars: rhythm prompt formatted"

echo "--- exemplars: validate_exemplars flags short text ---"

RESULT=$(python3 -c "
${PY}
from storyforge.exemplars import validate_exemplars

result = validate_exemplars('Too short.')
assert not result['valid'], 'should fail'
assert any('Too short' in i for i in result['issues']), f'missing length issue: {result[\"issues\"]}'
print(f'issues={len(result[\"issues\"])}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "exemplars: validates short text"

echo "--- exemplars: validate_exemplars passes good text ---"

RESULT=$(python3 -c "
${PY}
from storyforge.exemplars import validate_exemplars

# Good exemplar with varied rhythm
text = '''The car horn hit me in the chest before I heard it.

Violet. Deep, wet violet, the color of a bruise two days old, blooming across the stainless steel counter and dripping down the ticket rail like someone had upended a paint can. I blinked and it was gone. The prep station was just a prep station again: cutting boards, mise en place, the half-sliced pile of Roma tomatoes I had been working through for the past twenty minutes.

Outside, the horn blared again. Lighter this time. Lilac around the edges.

I went back to the tomatoes. Knife work was good for this. You could not think about colors that were not there when you had eight inches of carbon steel moving through flesh at speed.

For twenty minutes we worked in parallel. I got the chicken into its marinade. The lentils went on to simmer. I started the onions for the soup, and the first sizzle of butter and diced yellow onion in the pan released a smell so correct, so exactly what this kitchen was supposed to smell like, that something in my chest unlocked a quarter-turn.

I could do this. I was doing this.

I was on the ground. My knees had hit first, I could feel the ache of impact, and my hands were flat on the tunnel floor, the stone gritty and damp under my palms. Warmth running down my upper lip. I touched my face and my fingers came away red.

My hands were shaking. My whole body was shaking.'''

result = validate_exemplars(text)
print(f'valid={result[\"valid\"]}')
print(f'issues={len(result[\"issues\"])}')
if result['issues']:
    for i in result['issues']:
        print(f'  issue: {i}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "exemplars: validation runs on good text"

echo "--- exemplars: validate_project_exemplars finds flat file ---"

RESULT=$(python3 -c "
${PY}
from storyforge.exemplars import validate_project_exemplars

result = validate_project_exemplars('${FIXTURE_DIR}')
print(f'has_any={result[\"has_any\"]}')
print(f'files={len(result[\"files\"])}')
print('ok')
" 2>/dev/null)

assert_contains "$RESULT" "ok" "exemplars: project validation runs"

echo "--- exemplars: per-POV loading prefers POV file ---"

RESULT=$(python3 -c "
${PY}
import os, tempfile, shutil

# Create temp project with per-POV exemplar
tmpdir = tempfile.mkdtemp()
ref = os.path.join(tmpdir, 'reference')
shutil.copytree('${FIXTURE_DIR}/reference', ref)

# Create per-POV exemplar directory and file
exemplars_dir = os.path.join(ref, 'exemplars')
os.makedirs(exemplars_dir, exist_ok=True)
with open(os.path.join(exemplars_dir, 'dorren-hayle.md'), 'w') as f:
    f.write('Per-POV content for Dorren.')

# Also ensure flat file exists
with open(os.path.join(ref, 'prose-exemplars.md'), 'w') as f:
    f.write('Flat file content.')

# Test loading with POV
from storyforge.prompts import _load_prose_exemplars
result = _load_prose_exemplars(tmpdir, 'Dorren Hayle')
assert 'Per-POV content' in result, f'should load per-POV: {result[:80]}'
print('per_pov=loaded')

# Test fallback without matching POV
result2 = _load_prose_exemplars(tmpdir, 'Unknown Character')
assert 'Flat file content' in result2, f'should fall back to flat: {result2[:80]}'
print('fallback=loaded')

# Test no POV at all
result3 = _load_prose_exemplars(tmpdir)
assert 'Flat file content' in result3, f'should load flat: {result3[:80]}'
print('no_pov=loaded')

print('ok')
shutil.rmtree(tmpdir)
" 2>/dev/null)

assert_contains "$RESULT" "per_pov=loaded" "exemplars: per-POV file loaded"
assert_contains "$RESULT" "fallback=loaded" "exemplars: falls back to flat file"
assert_contains "$RESULT" "no_pov=loaded" "exemplars: loads flat when no POV"
assert_contains "$RESULT" "ok" "exemplars: per-POV loading works"
