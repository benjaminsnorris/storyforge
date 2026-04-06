# storyforge-hone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `storyforge-hone`, a CSV data quality tool that absorbs `storyforge-reconcile` and adds three new domains: briefs (concretization), structural (evaluation-driven CSV fixes), and gaps (fill missing fields).

**Architecture:** New Python module `hone.py` absorbs all `reconcile.py` functions and adds new domain logic. New shell script `storyforge-hone` absorbs `storyforge-reconcile` and adds domain routing, scene filtering, coaching level support. Old `storyforge-reconcile` becomes a thin wrapper. Old `reconcile.py` re-exports for backwards compatibility.

**Tech Stack:** Python 3 (storyforge modules), Bash (script shell), pipe-delimited CSV, Anthropic API (Opus for domain passes)

---

### Task 1: Create hone.py by absorbing reconcile.py

**Files:**
- Create: `scripts/lib/python/storyforge/hone.py`
- Modify: `scripts/lib/python/storyforge/reconcile.py` (gut and re-export)

- [ ] **Step 1: Write test verifying hone.py exports reconcile functions**

Create `tests/test-hone.sh`:

```bash
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-hone.sh`

- [ ] **Step 3: Create hone.py**

Copy all content from `scripts/lib/python/storyforge/reconcile.py` into a new file `scripts/lib/python/storyforge/hone.py`. Update the module docstring:

```python
"""CSV data quality tool — registries, briefs, structural fixes, gap fill.

Domains:
- registries: Build canonical registries and normalize field values (absorbs reconcile.py)
- briefs: Concretize abstract brief language as concrete physical beats
- structural: Fix CSV fields from evaluation findings
- gaps: Fill empty fields from context

Each domain follows: detect → prompt → apply → commit.
"""
```

- [ ] **Step 4: Gut reconcile.py to re-export from hone.py**

Replace `scripts/lib/python/storyforge/reconcile.py` with:

```python
"""Backwards-compatible re-exports from storyforge.hone.

All reconciliation logic has moved to storyforge.hone.
This module re-exports public functions for existing callers.
"""

from storyforge.hone import (  # noqa: F401
    normalize_outcomes,
    reconcile_outcomes,
    build_registry_prompt,
    parse_registry_response,
    write_registry,
    apply_updates,
    apply_registry_normalization,
    reconcile_domain,
    _collect_knowledge_chain,
    _collect_physical_state_chain,
    _REGISTRY_COLUMNS,
    _DOMAIN_TO_REGISTRY,
    _DOMAIN_TARGETS,
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-hone.sh`

- [ ] **Step 6: Run full test suite to check reconcile backwards compat**

Run: `./tests/run-tests.sh`
Expected: All suites pass, including test-reconcile.sh (unchanged, now using re-exports).

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/hone.py scripts/lib/python/storyforge/reconcile.py tests/test-hone.sh
git commit -m "Add hone.py absorbing reconcile.py with backwards-compatible re-exports"
git push
```

---

### Task 2: Add abstract language detection for briefs domain

**Files:**
- Modify: `scripts/lib/python/storyforge/hone.py`
- Modify: `tests/test-hone.sh`

- [ ] **Step 1: Write test for detect_abstract_fields**

Append to `tests/test-hone.sh`:

```bash
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
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement detect_abstract_fields in hone.py**

Add at the end of `hone.py` (before any existing `if __name__` block):

```python
# ============================================================================
# Briefs domain: abstract language detection
# ============================================================================

ABSTRACT_INDICATORS = {
    'realizes', 'recognizes', 'connects', 'crystallizes', 'deepens',
    'builds', 'grows', 'shifts', 'transforms', 'emerges', 'settles',
    'dawns', 'unfolds', 'intensifies', 'resolves', 'strengthens',
    'the realization', 'the parallel', 'the tension', 'the connection',
    'the weight of', 'the cost of', 'the truth of', 'the meaning of',
    'beginning to', 'starting to', 'learning to',
}

CONCRETE_INDICATORS = {
    'hands', 'eyes', 'door', 'walks', 'picks up', 'sets down',
    'turns', 'stops', 'reaches', 'holds', 'drops', 'pulls',
    'sits', 'stands', 'crosses', 'opens', 'closes', 'looks',
    'says', 'asks', 'watches', 'hears', 'smells', 'tastes',
    'runs', 'steps', 'grabs', 'pushes', 'carries', 'presses',
}

_CONCRETIZABLE_FIELDS = ['key_actions', 'crisis', 'decision']


def detect_abstract_fields(
    briefs_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Scan brief fields for abstract/thematic language.

    Args:
        briefs_map: dict keyed by scene ID, values are brief row dicts.
        scene_ids: Optional list of scene IDs to check. If None, check all.

    Returns:
        List of dicts: {scene_id, field, value, abstract_count, concrete_count}.
        Only returns fields where abstract_count >= 2 and abstract_count > concrete_count.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(briefs_map.keys())

    for sid in ids_to_check:
        brief = briefs_map.get(sid, {})
        for field in _CONCRETIZABLE_FIELDS:
            value = brief.get(field, '').strip()
            if not value:
                continue

            value_lower = value.lower()
            abstract_count = sum(1 for ind in ABSTRACT_INDICATORS if ind in value_lower)
            concrete_count = sum(1 for ind in CONCRETE_INDICATORS if ind in value_lower)

            if abstract_count >= 2 and abstract_count > concrete_count:
                results.append({
                    'scene_id': sid,
                    'field': field,
                    'value': value,
                    'abstract_count': abstract_count,
                    'concrete_count': concrete_count,
                })

    return results
```

- [ ] **Step 4: Run test to verify it passes**

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/hone.py tests/test-hone.sh
git commit -m "Add abstract language detection for briefs domain"
git push
```

---

### Task 3: Add concretization prompt builder and parser

**Files:**
- Modify: `scripts/lib/python/storyforge/hone.py`
- Modify: `tests/test-hone.sh`

- [ ] **Step 1: Write tests for build_concretize_prompt and parse_concretize_response**

Append to `tests/test-hone.sh`:

```bash
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
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement build_concretize_prompt**

Add to `hone.py`:

```python
def build_concretize_prompt(
    scene_id: str,
    fields: list[str],
    current_values: dict[str, str],
    voice_guide: str = '',
    character_entry: str = '',
) -> str:
    """Build prompt to rewrite abstract brief fields as concrete physical beats.

    Args:
        scene_id: The scene being concretized.
        fields: List of field names to rewrite.
        current_values: Dict of field_name -> current value.
        voice_guide: Excerpt from the voice guide (POV character's sensory palette).
        character_entry: Character bible entry for the POV character.

    Returns:
        Prompt string for Claude.
    """
    field_block = '\n'.join(
        f"**{field}:** {current_values.get(field, '')}"
        for field in fields
    )

    return f"""Rewrite these scene brief fields so every item is something the POV character physically does or perceives.

## Scene: {scene_id}

## Current Values (abstract — need rewriting)
{field_block}

## Voice Guide (POV character)
{voice_guide if voice_guide else '(not available)'}

## Character
{character_entry if character_entry else '(not available)'}

## Rules

1. Every action must be something the POV character physically does or perceives through their senses. No thematic descriptions, no narrator interpretations, no emotion names as events.
2. Replace "the realization building" with what the character DOES when they realize something (hands stop, breath catches, they set something down).
3. Replace "tension deepening" with what the character SEES or FEELS (someone's jaw tightening, the room going quiet, a hand moving to a weapon).
4. Replace "connecting X to Y" with the physical moment: what does the character look at, touch, or say when the connection happens?
5. Keep the same number of beats (semicolon-separated items). Don't add or remove story events — just rewrite HOW they're described.
6. Use the character's sensory palette from the voice guide. If they think in food metaphors, their observations should reflect that.

## Output Format

Return each field on its own labeled line, exactly like the input but rewritten:

{chr(10).join(f'{field}: [rewritten value]' for field in fields)}

No explanation. No markdown. Just the labeled lines."""


def parse_concretize_response(
    response: str, scene_id: str, fields: list[str]
) -> dict[str, str]:
    """Parse concretization response into field values.

    Returns:
        Dict mapping field_name -> rewritten value.
    """
    result = {}
    for line in response.split('\n'):
        line = line.strip()
        if not line:
            continue
        for field in fields:
            prefix = f'{field}:'
            if line.lower().startswith(prefix.lower()):
                value = line[len(prefix):].strip()
                if value:
                    result[field] = value
                break
    return result
```

- [ ] **Step 4: Run test to verify it passes**

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/hone.py tests/test-hone.sh
git commit -m "Add concretization prompt builder and parser for briefs domain"
git push
```

---

### Task 4: Add hone_briefs domain function

**Files:**
- Modify: `scripts/lib/python/storyforge/hone.py`
- Modify: `tests/test-hone.sh`

- [ ] **Step 1: Write test for hone_briefs**

Append to `tests/test-hone.sh`:

```bash
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
        r['key_actions'] = 'The realization building; connecting the anomaly to the deeper pattern; the truth crystallizing'
_write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])

# Run detection only (dry_run=True)
result = hone_briefs(ref, tmpdir, dry_run=True)
print(f'flagged={result[\"scenes_flagged\"]}')
print('ok')

shutil.rmtree(tmpdir)
" 2>/dev/null)

assert_contains "$RESULT" "flagged=1" "briefs: detects 1 abstract scene"
assert_contains "$RESULT" "ok" "briefs: hone_briefs runs in dry-run mode"
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement hone_briefs**

Add to `hone.py`:

```python
def hone_briefs(
    ref_dir: str,
    project_dir: str,
    scene_ids: list[str] | None = None,
    threshold: float = 3.5,
    model: str = '',
    log_dir: str = '',
    coaching_level: str = 'full',
    dry_run: bool = False,
) -> dict:
    """Concretize abstract brief fields as concrete physical beats.

    Args:
        ref_dir: Path to reference/ directory.
        project_dir: Path to project root.
        scene_ids: Optional list of scene IDs to check. If None, check all.
        threshold: prose_naturalness score threshold (scenes below this are flagged).
        model: Anthropic model ID for API calls.
        log_dir: Directory for API log files.
        coaching_level: full/coach/strict.
        dry_run: If True, detect but don't rewrite.

    Returns:
        Dict with scenes_flagged, scenes_rewritten, fields_rewritten.
    """
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    # Detect abstract fields
    flagged = detect_abstract_fields(briefs_map, scene_ids)

    if dry_run or not flagged:
        return {
            'scenes_flagged': len(set(f['scene_id'] for f in flagged)),
            'scenes_rewritten': 0,
            'fields_rewritten': 0,
        }

    if coaching_level == 'strict':
        # Save analysis only
        hone_dir = os.path.join(project_dir, 'working', 'hone')
        os.makedirs(hone_dir, exist_ok=True)
        for f in flagged:
            path = os.path.join(hone_dir, f'briefs-analysis-{f["scene_id"]}.md')
            with open(path, 'w') as fh:
                fh.write(f"# Brief Analysis: {f['scene_id']}\n\n")
                fh.write(f"**Field:** {f['field']}\n")
                fh.write(f"**Current:** {f['value']}\n")
                fh.write(f"**Abstract indicators:** {f['abstract_count']}\n")
                fh.write(f"**Concrete indicators:** {f['concrete_count']}\n")
        return {
            'scenes_flagged': len(set(f['scene_id'] for f in flagged)),
            'scenes_rewritten': 0,
            'fields_rewritten': 0,
        }

    # Load voice guide and character bible for prompt building
    voice_guide = ''
    voice_path = os.path.join(ref_dir, 'voice-guide.md')
    if os.path.isfile(voice_path):
        with open(voice_path, encoding='utf-8') as fh:
            voice_guide = fh.read()

    char_bible = ''
    char_path = os.path.join(ref_dir, 'character-bible.md')
    if os.path.isfile(char_path):
        with open(char_path, encoding='utf-8') as fh:
            char_bible = fh.read()

    from storyforge.api import invoke_to_file, extract_text_from_file

    # Group flagged fields by scene
    by_scene: dict[str, list[str]] = {}
    for f in flagged:
        by_scene.setdefault(f['scene_id'], []).append(f['field'])

    scenes_rewritten = 0
    fields_rewritten = 0

    for sid, fields in by_scene.items():
        current_values = {field: briefs_map[sid].get(field, '') for field in fields}

        prompt = build_concretize_prompt(
            scene_id=sid,
            fields=fields,
            current_values=current_values,
            voice_guide=voice_guide[:3000],  # Truncate to keep prompt reasonable
            character_entry=char_bible[:2000],
        )

        if coaching_level == 'coach':
            # Save proposal for author review
            hone_dir = os.path.join(project_dir, 'working', 'hone')
            os.makedirs(hone_dir, exist_ok=True)
            proposal_path = os.path.join(hone_dir, f'briefs-{sid}.md')
            with open(proposal_path, 'w') as fh:
                fh.write(f"# Brief Concretization Proposal: {sid}\n\n")
                fh.write(f"## Current\n")
                for field in fields:
                    fh.write(f"**{field}:** {current_values[field]}\n\n")
                fh.write(f"## Prompt\n\n{prompt}\n")
            # Don't call API in coach mode — author reviews and decides
            continue

        # full coaching: call API and apply
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f'hone-briefs-{sid}.json')
        invoke_to_file(prompt, model, log_file, max_tokens=2048)
        response = extract_text_from_file(log_file)

        rewrites = parse_concretize_response(response, sid, fields)
        for field, new_value in rewrites.items():
            if new_value and new_value != current_values.get(field):
                briefs_map[sid][field] = new_value
                fields_rewritten += 1

        if rewrites:
            scenes_rewritten += 1

    # Write back if any changes were made
    if fields_rewritten > 0:
        briefs_rows = list(briefs_map.values())
        # Sort by id to maintain stable order
        briefs_rows.sort(key=lambda r: r.get('id', ''))
        _write_csv(
            os.path.join(ref_dir, 'scene-briefs.csv'),
            briefs_rows,
            _FILE_MAP['scene-briefs.csv'],
        )

    return {
        'scenes_flagged': len(by_scene),
        'scenes_rewritten': scenes_rewritten,
        'fields_rewritten': fields_rewritten,
    }
```

- [ ] **Step 4: Run test to verify it passes**

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/hone.py tests/test-hone.sh
git commit -m "Add hone_briefs domain function with coaching level support"
git push
```

---

### Task 5: Add gap detection and structural fix functions

**Files:**
- Modify: `scripts/lib/python/storyforge/hone.py`
- Modify: `tests/test-hone.sh`

- [ ] **Step 1: Write tests for detect_gaps**

Append to `tests/test-hone.sh`:

```bash
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
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement detect_gaps**

Add to `hone.py`:

```python
# ============================================================================
# Gaps domain: detect missing fields
# ============================================================================

# Required fields by status level (from elaborate.py _REQUIRED_BY_STATUS)
_GAPS_REQUIRED = {
    'briefed': [
        'function', 'value_at_stake', 'value_shift', 'emotional_arc',
        'goal', 'conflict', 'outcome', 'crisis', 'decision',
    ],
    'drafted': [
        'function', 'value_at_stake', 'value_shift', 'emotional_arc',
        'goal', 'conflict', 'outcome', 'crisis', 'decision',
    ],
}


def detect_gaps(
    scenes_map: dict[str, dict],
    intent_map: dict[str, dict],
    briefs_map: dict[str, dict],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Scan for empty required fields given each scene's status.

    Returns:
        List of dicts: {scene_id, field, status, file}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(scenes_map.keys())

    for sid in ids_to_check:
        scene = scenes_map.get(sid, {})
        status = scene.get('status', 'spine')
        required = _GAPS_REQUIRED.get(status, [])
        if not required:
            continue

        # Merge all data for this scene
        merged = dict(scene)
        if sid in intent_map:
            merged.update({k: v for k, v in intent_map[sid].items() if k != 'id'})
        if sid in briefs_map:
            merged.update({k: v for k, v in briefs_map[sid].items() if k != 'id'})

        for field in required:
            if not merged.get(field, '').strip():
                # Determine which file owns this field
                file = 'scene-briefs.csv'
                if field in ('function', 'value_at_stake', 'value_shift', 'emotional_arc'):
                    file = 'scene-intent.csv'
                results.append({
                    'scene_id': sid,
                    'field': field,
                    'status': status,
                    'file': file,
                })

    return results
```

- [ ] **Step 4: Run test to verify it passes**

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/hone.py tests/test-hone.sh
git commit -m "Add gap detection for gaps domain"
git push
```

---

### Task 6: Create storyforge-hone shell script

**Files:**
- Create: `scripts/storyforge-hone`
- Modify: `scripts/storyforge-reconcile` (become wrapper)

- [ ] **Step 1: Create storyforge-hone script**

Create `scripts/storyforge-hone`:

```bash
#!/bin/bash
# storyforge-hone — CSV data quality tool
#
# Domains:
#   registries   Build canonical registries, normalize field values
#   briefs       Concretize abstract brief language as concrete physical beats
#   structural   Fix CSV fields from evaluation findings
#   gaps         Fill empty required fields from context
#
# Usage:
#   ./storyforge hone                              # Run all domains
#   ./storyforge hone --domain briefs              # Run one domain
#   ./storyforge hone --domain registries --phase 1  # Registry sub-domains for extraction phase
#   ./storyforge hone --scenes ID,ID               # Scope to specific scenes
#   ./storyforge hone --dry-run                    # Show what would change
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/lib"
PYTHON_LIB="${SCRIPT_DIR}/lib/python"

source "${LIB_DIR}/common.sh"
detect_project_root

LOG_DIR="${PROJECT_DIR}/working/logs"
mkdir -p "$LOG_DIR"

# ============================================================================
# Arguments
# ============================================================================

DOMAINS_ARG=""
PHASE=""
SCENES_ARG=""
ACT_ARG=""
THRESHOLD="3.5"
DRY_RUN=false
COACHING_LEVEL=""

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

CSV data quality tool — improve scene CSV data across four domains.

Domains:
  registries    Build canonical registries, normalize field values
  briefs        Concretize abstract brief language as concrete physical beats
  structural    Fix CSV fields from evaluation findings
  gaps          Fill empty required fields from context

Options:
  --domain NAME[,NAME]  Run specific domains (comma-separated)
  --phase N             Run registry sub-domains for extraction phase (1/2/3)
  --scenes ID,ID        Scope to specific scenes
  --act N               Scope to scenes in part/act N
  --threshold N         prose_naturalness threshold for briefs domain (default: 3.5)
  --coaching LEVEL      Override coaching level (full/coach/strict)
  --dry-run             Show what would change without modifying files
  -h, --help            Show this help
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)     DOMAINS_ARG="${2:?ERROR: --domain requires a value}"; shift 2 ;;
        --phase)      PHASE="${2:?ERROR: --phase requires a value}"; shift 2 ;;
        --scenes)     SCENES_ARG="${2:?ERROR: --scenes requires comma-separated IDs}"; shift 2 ;;
        --act|--part) ACT_ARG="${2:?ERROR: $1 requires a value}"; shift 2 ;;
        --threshold)  THRESHOLD="${2:?ERROR: --threshold requires a value}"; shift 2 ;;
        --coaching)   COACHING_LEVEL="${2:?ERROR: --coaching requires full/coach/strict}"; shift 2 ;;
        --dry-run)    DRY_RUN=true; shift ;;
        -h|--help)    usage ;;
        -*)           echo "ERROR: Unknown option: $1" >&2; usage ;;
        *)            shift ;;
    esac
done

# Resolve coaching level
if [[ -z "$COACHING_LEVEL" ]]; then
    COACHING_LEVEL=$(get_coaching_level)
fi

# ============================================================================
# Build domain list
# ============================================================================

ALL_DOMAINS=(registries gaps structural briefs)
PHASE1_REGISTRY_DOMAINS=(characters locations)
PHASE2_REGISTRY_DOMAINS=(values mice-threads)
PHASE3_REGISTRY_DOMAINS=(knowledge outcomes physical-states)

DOMAINS=()
if [[ -n "$DOMAINS_ARG" ]]; then
    IFS=',' read -ra DOMAINS <<< "$DOMAINS_ARG"
elif [[ -n "$PHASE" ]]; then
    # Phase mode is registry-only (backwards compat with storyforge-reconcile --phase)
    case "$PHASE" in
        1) DOMAINS=("${PHASE1_REGISTRY_DOMAINS[@]}") ;;
        2) DOMAINS=("${PHASE2_REGISTRY_DOMAINS[@]}") ;;
        3) DOMAINS=("${PHASE3_REGISTRY_DOMAINS[@]}") ;;
        *) log "ERROR: --phase must be 1, 2, or 3"; exit 1 ;;
    esac
else
    DOMAINS=("${ALL_DOMAINS[@]}")
fi

if [[ "$DRY_RUN" != true && -z "${ANTHROPIC_API_KEY:-}" ]]; then
    # Check if any domain needs API (registries/briefs/gaps do, not outcomes)
    needs_api=false
    for d in "${DOMAINS[@]}"; do
        case "$d" in
            outcomes) ;;
            *) needs_api=true ;;
        esac
    done
    if [[ "$needs_api" == true && "$COACHING_LEVEL" != "strict" ]]; then
        log "ERROR: ANTHROPIC_API_KEY not set. Required for hone domains."
        exit 1
    fi
fi

# ============================================================================
# Project info
# ============================================================================

PROJECT_TITLE=$(read_yaml_field "project.title" 2>/dev/null || echo "Untitled")
REF_DIR="${PROJECT_DIR}/reference"
MODEL=$(select_model "synthesis")

log "============================================"
log "Storyforge Hone"
log "Project: ${PROJECT_TITLE}"
log "Domains: ${DOMAINS[*]}"
log "Coaching: ${COACHING_LEVEL}"
[[ -n "$SCENES_ARG" ]] && log "Scenes: ${SCENES_ARG}"
log "Model: ${MODEL}"
log "============================================"

# ============================================================================
# Scene filter (if --scenes or --act provided)
# ============================================================================

SCENE_FILTER=""
if [[ -n "$SCENES_ARG" ]]; then
    SCENE_FILTER="$SCENES_ARG"
elif [[ -n "$ACT_ARG" ]]; then
    SCENE_FILTER=$(PYTHONPATH="$PYTHON_LIB" python3 -c "
import sys; sys.path.insert(0, '${PYTHON_LIB}')
from storyforge.elaborate import _read_csv
rows = _read_csv('${REF_DIR}/scenes.csv')
ids = [r['id'] for r in rows if r.get('part', '') == '${ACT_ARG}']
print(','.join(ids))
")
fi

# ============================================================================
# Run domains
# ============================================================================

CHAR_BIBLE="${PROJECT_DIR}/reference/character-bible.md"

for CURRENT_DOMAIN in "${DOMAINS[@]}"; do
    log ""
    log "--- Hone: ${CURRENT_DOMAIN} ---"

    # Registry sub-domains go through the existing reconcile_domain path
    case "$CURRENT_DOMAIN" in
        characters|locations|values|mice-threads|knowledge|outcomes|physical-states)
            # This is a registry domain — use existing reconcile logic
            if [[ "$DRY_RUN" == true ]]; then
                if [[ "$CURRENT_DOMAIN" == "outcomes" ]]; then
                    log "  (deterministic — no API call needed)"
                else
                    PYTHONPATH="$PYTHON_LIB" python3 -c "
import sys, os; sys.path.insert(0, '${PYTHON_LIB}')
from storyforge.hone import build_registry_prompt
context = ''
if '${CURRENT_DOMAIN}' == 'characters' and os.path.isfile('${CHAR_BIBLE}'):
    context = open('${CHAR_BIBLE}', encoding='utf-8').read()
prompt = build_registry_prompt('${CURRENT_DOMAIN}', '${REF_DIR}', context=context)
print(f'Prompt for ${CURRENT_DOMAIN} ({len(prompt)} chars)')
"
                fi
                continue
            fi

            RESULT=$(PYTHONPATH="$PYTHON_LIB" python3 -c "
import sys, json, os; sys.path.insert(0, '${PYTHON_LIB}')
from storyforge.hone import reconcile_domain
context = ''
if '${CURRENT_DOMAIN}' == 'characters' and os.path.isfile('${CHAR_BIBLE}'):
    context = open('${CHAR_BIBLE}', encoding='utf-8').read()
result = reconcile_domain('${CURRENT_DOMAIN}', '${REF_DIR}', '${MODEL}', '${LOG_DIR}', context=context)
print(json.dumps(result))
")

            ENTRIES=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('registry_entries', 0))")
            NORMALIZED=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('fields_normalized', 0))")
            log "  Registry: ${ENTRIES} entries, ${NORMALIZED} normalizations"

            (cd "$PROJECT_DIR" && git add reference/ working/logs/ && \
                git commit -m "Hone: registries/${CURRENT_DOMAIN} — ${ENTRIES} entries, ${NORMALIZED} normalizations" && \
                git push) 2>/dev/null || true
            ;;

        registries)
            # Meta-domain: run all registry sub-domains
            for sub in characters locations values mice-threads knowledge outcomes physical-states; do
                log "  --- registries/${sub} ---"
                if [[ "$DRY_RUN" == true ]]; then
                    log "    (dry-run)"
                    continue
                fi

                RESULT=$(PYTHONPATH="$PYTHON_LIB" python3 -c "
import sys, json, os; sys.path.insert(0, '${PYTHON_LIB}')
from storyforge.hone import reconcile_domain
context = ''
if '${sub}' == 'characters' and os.path.isfile('${CHAR_BIBLE}'):
    context = open('${CHAR_BIBLE}', encoding='utf-8').read()
result = reconcile_domain('${sub}', '${REF_DIR}', '${MODEL}', '${LOG_DIR}', context=context)
print(json.dumps(result))
")

                ENTRIES=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('registry_entries', 0))")
                NORMALIZED=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('fields_normalized', 0))")
                log "    ${ENTRIES} entries, ${NORMALIZED} normalizations"

                (cd "$PROJECT_DIR" && git add reference/ working/logs/ && \
                    git commit -m "Hone: registries/${sub} — ${ENTRIES} entries, ${NORMALIZED} normalizations" && \
                    git push) 2>/dev/null || true
            done
            ;;

        briefs)
            SCENE_FLAG=""
            [[ -n "$SCENE_FILTER" ]] && SCENE_FLAG="scene_ids='${SCENE_FILTER}'.split(',')"

            RESULT=$(PYTHONPATH="$PYTHON_LIB" python3 -c "
import sys, json; sys.path.insert(0, '${PYTHON_LIB}')
from storyforge.hone import hone_briefs
result = hone_briefs(
    '${REF_DIR}', '${PROJECT_DIR}',
    scene_ids=${SCENE_FLAG:-None},
    threshold=${THRESHOLD},
    model='${MODEL}',
    log_dir='${LOG_DIR}',
    coaching_level='${COACHING_LEVEL}',
    dry_run=${DRY_RUN^},
)
print(json.dumps(result))
")

            FLAGGED=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('scenes_flagged', 0))")
            REWRITTEN=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('scenes_rewritten', 0))")
            FIELDS=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('fields_rewritten', 0))")

            log "  Flagged: ${FLAGGED} scenes with abstract briefs"
            log "  Rewritten: ${REWRITTEN} scenes, ${FIELDS} fields"

            if [[ "$DRY_RUN" != true && "$REWRITTEN" -gt 0 ]]; then
                (cd "$PROJECT_DIR" && git add reference/ working/ && \
                    git commit -m "Hone: briefs — ${REWRITTEN} scenes concretized (${FIELDS} fields)" && \
                    git push) 2>/dev/null || true
            fi
            ;;

        gaps)
            SCENE_FLAG=""
            [[ -n "$SCENE_FILTER" ]] && SCENE_FLAG="scene_ids='${SCENE_FILTER}'.split(',')"

            RESULT=$(PYTHONPATH="$PYTHON_LIB" python3 -c "
import sys, json; sys.path.insert(0, '${PYTHON_LIB}')
from storyforge.elaborate import _read_csv_as_map
from storyforge.hone import detect_gaps
scenes = _read_csv_as_map('${REF_DIR}/scenes.csv')
intent = _read_csv_as_map('${REF_DIR}/scene-intent.csv')
briefs = _read_csv_as_map('${REF_DIR}/scene-briefs.csv')
gaps = detect_gaps(scenes, intent, briefs, ${SCENE_FLAG:-None})
print(json.dumps({'gaps': len(gaps), 'scenes': len(set(g['scene_id'] for g in gaps))}))
")

            GAPS=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('gaps', 0))")
            SCENES=$(echo "$RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('scenes', 0))")
            log "  Gaps found: ${GAPS} empty fields across ${SCENES} scenes"

            if [[ "$DRY_RUN" == true || "$GAPS" == "0" ]]; then
                continue
            fi

            log "  (gap filling requires storyforge-elaborate --gap-fill — run manually)"
            ;;

        structural)
            log "  (structural CSV fixes route through evaluation findings — run after storyforge-evaluate)"
            ;;

        *)
            log "WARNING: Unknown domain: ${CURRENT_DOMAIN}"
            ;;
    esac
done

log ""
log "============================================"
log "Hone complete"
log "============================================"
```

- [ ] **Step 2: Make script executable**

```bash
chmod +x scripts/storyforge-hone
```

- [ ] **Step 3: Convert storyforge-reconcile to wrapper**

Replace `scripts/storyforge-reconcile` with:

```bash
#!/bin/bash
# storyforge-reconcile — Backwards-compatible wrapper for storyforge-hone
#
# All reconciliation logic has moved to storyforge-hone.
# This script translates reconcile arguments to hone arguments.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Translate --domain to registry sub-domain pass-through
# (storyforge-hone handles individual registry domains directly)
exec "${SCRIPT_DIR}/storyforge-hone" "$@"
```

- [ ] **Step 4: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All suites pass. test-reconcile.sh still works through the backwards-compatible Python re-exports.

- [ ] **Step 5: Commit**

```bash
git add scripts/storyforge-hone scripts/storyforge-reconcile tests/test-hone.sh
git commit -m "Add storyforge-hone script, convert storyforge-reconcile to wrapper"
git push
```

---

### Task 7: Update CLAUDE.md and integration points

**Files:**
- Modify: `CLAUDE.md`
- Modify: `scripts/storyforge-extract` (call hone instead of reconcile)

- [ ] **Step 1: Update CLAUDE.md script table**

In `CLAUDE.md`, in the Scripts table, add `storyforge-hone` and update `storyforge-reconcile`:

Change the `storyforge-reconcile` row to:
```
| `storyforge-reconcile` | Backwards-compatible wrapper for `storyforge-hone --domain registries` |
```

Add new row:
```
| `storyforge-hone` | CSV data quality tool — registries, briefs concretization, structural fixes, gap detection |
```

- [ ] **Step 2: Update storyforge-extract to call hone**

In `scripts/storyforge-extract`, find lines that call `storyforge-reconcile --phase N` and change to `storyforge-hone --domain registries --phase N`:

Search for `storyforge-reconcile` in the file and replace with `storyforge-hone --domain registries`.

- [ ] **Step 3: Run full test suite**

Run: `./tests/run-tests.sh`

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md scripts/storyforge-extract
git commit -m "Update CLAUDE.md and storyforge-extract to use storyforge-hone"
git push
```

---

### Task 8: Version bump and final verification

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Run full test suite**

Run: `./tests/run-tests.sh`

- [ ] **Step 2: Bump version to 0.64.0**

In `.claude-plugin/plugin.json`, change version to `"0.64.0"`.

- [ ] **Step 3: Commit and push**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 0.64.0 — add storyforge-hone CSV data quality tool"
git push
```
