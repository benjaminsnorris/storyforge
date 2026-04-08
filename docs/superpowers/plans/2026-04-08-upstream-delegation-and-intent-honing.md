# Upstream Delegation to Hone & Intent Quality Detection

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix silent failures in revision brief/intent passes by delegating upstream CSV work to hone, adding intent quality detection to hone, and adding a validation gate to revise.

**Architecture:** Revise writes a findings file and calls `hone_briefs()` / `hone_intent()` instead of building its own broken upstream prompts. Hone gains 6 intent detectors, a new `build_evaluation_fix_prompt()`, and a `--findings` CLI flag. Revise adds a file-hash validation gate and post-fix redrafting.

**Tech Stack:** Python 3.14, pytest, Anthropic API (via `storyforge.api`)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `scripts/lib/python/storyforge/hone.py` | Modify | Add intent detectors, `detect_intent_issues()`, `hone_intent()`, `load_external_findings()`, `build_evaluation_fix_prompt()`, `build_intent_fix_prompt()`. Modify `hone_briefs()` signature. |
| `scripts/lib/python/storyforge/cmd_hone.py` | Modify | Add `--findings` flag, `_run_intent_domain()`, wire `'intent'` into domain dispatch. |
| `scripts/lib/python/storyforge/cmd_revise.py` | Modify | Replace upstream path (lines 1368-1550) with hone delegation + validation gate + redrafting. |
| `tests/test_hone_intent.py` | Create | Intent detection unit tests. |
| `tests/test_hone_findings.py` | Create | External findings loading + integration tests. |
| `tests/test_revise_upstream.py` | Create | Validation gate + delegation tests. |
| `CLAUDE.md` | Modify | Add `hone_intent`, `intent` domain to docs. |
| `.claude-plugin/plugin.json` | Modify | Bump version to 1.6.0. |

---

### Task 1: Intent Detection — Vague Function & Overlong Function

**Files:**
- Create: `tests/test_hone_intent.py`
- Modify: `scripts/lib/python/storyforge/hone.py`

- [ ] **Step 1: Write failing tests for vague function detection**

```python
# tests/test_hone_intent.py
"""Tests for intent CSV quality detection."""


class TestVagueFunction:
    def test_flags_abstract_function(self):
        from storyforge.hone import detect_vague_function
        intent_map = {
            'scene-a': {
                'id': 'scene-a',
                'function': 'She realizes the truth and connects the threads of meaning that have been building',
            },
        }
        results = detect_vague_function(intent_map)
        assert len(results) == 1
        assert results[0]['scene_id'] == 'scene-a'
        assert results[0]['field'] == 'function'
        assert results[0]['issue'] == 'vague'
        assert results[0]['abstract_count'] >= 2

    def test_passes_concrete_function(self):
        from storyforge.hone import detect_vague_function
        intent_map = {
            'scene-a': {
                'id': 'scene-a',
                'function': 'Dorren reads the dispatch and refuses to sign the decommission order',
            },
        }
        results = detect_vague_function(intent_map)
        assert len(results) == 0

    def test_skips_empty(self):
        from storyforge.hone import detect_vague_function
        intent_map = {'scene-a': {'id': 'scene-a', 'function': ''}}
        results = detect_vague_function(intent_map)
        assert len(results) == 0

    def test_respects_scene_filter(self):
        from storyforge.hone import detect_vague_function
        intent_map = {
            'scene-a': {'id': 'scene-a', 'function': 'She realizes and connects and transforms'},
            'scene-b': {'id': 'scene-b', 'function': 'He realizes and connects and transforms'},
        }
        results = detect_vague_function(intent_map, scene_ids=['scene-a'])
        assert len(results) == 1
        assert results[0]['scene_id'] == 'scene-a'


class TestOverlongFunction:
    def test_flags_overlong_function(self):
        from storyforge.hone import detect_overlong_function
        intent_map = {
            'scene-a': {
                'id': 'scene-a',
                'function': 'x ' * 250,  # 500 chars, well over 400
            },
        }
        results = detect_overlong_function(intent_map)
        assert len(results) == 1
        assert results[0]['issue'] == 'overlong'
        assert results[0]['char_count'] > 400

    def test_passes_normal_length(self):
        from storyforge.hone import detect_overlong_function
        intent_map = {
            'scene-a': {
                'id': 'scene-a',
                'function': 'Dorren reads the dispatch and refuses to sign',
            },
        }
        results = detect_overlong_function(intent_map)
        assert len(results) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_hone_intent.py -v`
Expected: FAIL — `detect_vague_function` and `detect_overlong_function` not found

- [ ] **Step 3: Implement vague function and overlong function detectors**

Add to `scripts/lib/python/storyforge/hone.py` after the briefs domain section (after the `hone_briefs` function, around line 1459):

```python
# ============================================================================
# Intent domain: vague function detection
# ============================================================================

_FUNCTION_ABSTRACT_INDICATORS = {
    'realizes', 'recognizes', 'connects', 'deepens', 'grows', 'learns',
    'bonds', 'evolves', 'processes', 'reflects', 'grapples',
    'transforms', 'emerges', 'shifts', 'develops feelings',
    'comes to understand', 'works through', 'beginning to',
}

_FUNCTION_CONCRETE_INDICATORS = {
    'says', 'asks', 'discovers', 'decides', 'refuses', 'confesses',
    'chooses', 'confronts', 'reveals', 'finds', 'witnesses', 'reads',
    'writes', 'signs', 'opens', 'closes', 'walks', 'runs', 'stops',
    'picks up', 'sets down', 'hands', 'pulls', 'pushes', 'reaches',
}

_FUNCTION_MAX_CHARS = 400


def detect_vague_function(
    intent_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect functions that use abstract/thematic language instead of testable actions.

    Returns:
        List of dicts: {scene_id, field, value, abstract_count, concrete_count, issue: 'vague'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(intent_map.keys())

    for sid in ids_to_check:
        intent = intent_map.get(sid, {})
        value = intent.get('function', '').strip()
        if not value:
            continue

        value_lower = value.lower()
        abstract_count = sum(1 for ind in _FUNCTION_ABSTRACT_INDICATORS if ind in value_lower)
        concrete_count = sum(1 for ind in _FUNCTION_CONCRETE_INDICATORS if ind in value_lower)

        if abstract_count >= 2 and abstract_count > concrete_count:
            results.append({
                'scene_id': sid,
                'field': 'function',
                'value': value,
                'abstract_count': abstract_count,
                'concrete_count': concrete_count,
                'issue': 'vague',
            })

    return results


def detect_overlong_function(
    intent_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect functions that are too long — function is a scene-level statement, not a summary.

    Returns:
        List of dicts: {scene_id, field, value, char_count, issue: 'overlong'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(intent_map.keys())

    for sid in ids_to_check:
        intent = intent_map.get(sid, {})
        value = intent.get('function', '').strip()
        if not value:
            continue

        char_count = len(value)
        if char_count > _FUNCTION_MAX_CHARS:
            results.append({
                'scene_id': sid,
                'field': 'function',
                'value': value,
                'char_count': char_count,
                'issue': 'overlong',
            })

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hone_intent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_hone_intent.py scripts/lib/python/storyforge/hone.py
git commit -m "Add intent detection: vague and overlong function detectors"
git push
```

---

### Task 2: Intent Detection — Emotional Arc Detectors

**Files:**
- Modify: `tests/test_hone_intent.py`
- Modify: `scripts/lib/python/storyforge/hone.py`

- [ ] **Step 1: Write failing tests for emotional arc detection**

Append to `tests/test_hone_intent.py`:

```python
class TestFlatEmotionalArc:
    def test_flags_single_state(self):
        from storyforge.hone import detect_flat_emotional_arc
        intent_map = {
            'scene-a': {'id': 'scene-a', 'emotional_arc': 'grief'},
        }
        results = detect_flat_emotional_arc(intent_map)
        assert len(results) == 1
        assert results[0]['issue'] == 'flat'

    def test_passes_transition(self):
        from storyforge.hone import detect_flat_emotional_arc
        intent_map = {
            'scene-a': {'id': 'scene-a', 'emotional_arc': 'grief giving way to determination'},
        }
        results = detect_flat_emotional_arc(intent_map)
        assert len(results) == 0

    def test_passes_to_transition(self):
        from storyforge.hone import detect_flat_emotional_arc
        intent_map = {
            'scene-a': {'id': 'scene-a', 'emotional_arc': 'dread to cautious relief'},
        }
        results = detect_flat_emotional_arc(intent_map)
        assert len(results) == 0

    def test_skips_empty(self):
        from storyforge.hone import detect_flat_emotional_arc
        intent_map = {'scene-a': {'id': 'scene-a', 'emotional_arc': ''}}
        results = detect_flat_emotional_arc(intent_map)
        assert len(results) == 0


class TestAbstractEmotionalArc:
    def test_flags_abstract_emotions(self):
        from storyforge.hone import detect_abstract_emotional_arc
        intent_map = {
            'scene-a': {'id': 'scene-a', 'emotional_arc': 'tension giving way to resolution and growth'},
        }
        results = detect_abstract_emotional_arc(intent_map)
        assert len(results) == 1
        assert results[0]['issue'] == 'abstract_arc'

    def test_passes_grounded_emotions(self):
        from storyforge.hone import detect_abstract_emotional_arc
        intent_map = {
            'scene-a': {'id': 'scene-a', 'emotional_arc': 'dread giving way to relief'},
        }
        results = detect_abstract_emotional_arc(intent_map)
        assert len(results) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_hone_intent.py::TestFlatEmotionalArc tests/test_hone_intent.py::TestAbstractEmotionalArc -v`
Expected: FAIL — functions not found

- [ ] **Step 3: Implement emotional arc detectors**

Add to `scripts/lib/python/storyforge/hone.py` after `detect_overlong_function`:

```python
# ============================================================================
# Intent domain: emotional arc detectors
# ============================================================================

_ARC_TRANSITION_RE = re.compile(
    r'(?:giving way to|shifting to|breaking into|dissolving into'
    r'|transforming into|turning to|hardening into|softening into'
    r'|replaced by|becoming)\s',
    re.IGNORECASE,
)
# Simpler "X to Y" pattern — only matches when surrounded by word boundaries
_ARC_SIMPLE_TO_RE = re.compile(
    r'\b\w+\s+to\s+\w+', re.IGNORECASE,
)

_ARC_ABSTRACT_EMOTIONS = {
    'tension', 'emotion', 'feeling', 'turmoil', 'struggle', 'growth',
    'shift', 'realization', 'understanding', 'complexity', 'process',
    'resolution', 'development', 'transformation', 'change',
}
_ARC_GROUNDED_EMOTIONS = {
    'grief', 'joy', 'fear', 'anger', 'shame', 'relief', 'longing',
    'tenderness', 'dread', 'exhilaration', 'guilt', 'warmth', 'pride',
    'regret', 'hope', 'despair', 'horror', 'calm', 'rage', 'sorrow',
    'awe', 'disgust', 'jealousy', 'contempt', 'resignation', 'resolve',
    'unease', 'alarm', 'shock', 'determination',
}


def detect_flat_emotional_arc(
    intent_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect emotional arcs that describe a single state instead of a transition.

    Returns:
        List of dicts: {scene_id, field, value, issue: 'flat'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(intent_map.keys())

    for sid in ids_to_check:
        intent = intent_map.get(sid, {})
        value = intent.get('emotional_arc', '').strip()
        if not value:
            continue

        has_transition = bool(_ARC_TRANSITION_RE.search(value))
        has_simple_to = bool(_ARC_SIMPLE_TO_RE.search(value))

        if not has_transition and not has_simple_to:
            results.append({
                'scene_id': sid,
                'field': 'emotional_arc',
                'value': value,
                'issue': 'flat',
            })

    return results


def detect_abstract_emotional_arc(
    intent_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect emotional arcs using abstract language instead of grounded emotions.

    Returns:
        List of dicts: {scene_id, field, value, abstract_count, concrete_count,
                        issue: 'abstract_arc'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(intent_map.keys())

    for sid in ids_to_check:
        intent = intent_map.get(sid, {})
        value = intent.get('emotional_arc', '').strip()
        if not value:
            continue

        value_lower = value.lower()
        # Split into words for matching
        abstract_count = sum(1 for w in _ARC_ABSTRACT_EMOTIONS if w in value_lower)
        concrete_count = sum(1 for w in _ARC_GROUNDED_EMOTIONS if w in value_lower)

        if abstract_count >= 2 and abstract_count > concrete_count:
            results.append({
                'scene_id': sid,
                'field': 'emotional_arc',
                'value': value,
                'abstract_count': abstract_count,
                'concrete_count': concrete_count,
                'issue': 'abstract_arc',
            })

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hone_intent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_hone_intent.py scripts/lib/python/storyforge/hone.py
git commit -m "Add intent detection: flat and abstract emotional arc detectors"
git push
```

---

### Task 3: Intent Detection — On-Stage Subset & Value-Shift/Outcome Mismatch

**Files:**
- Modify: `tests/test_hone_intent.py`
- Modify: `scripts/lib/python/storyforge/hone.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_hone_intent.py`:

```python
class TestOnstageSubsetViolation:
    def test_flags_onstage_not_in_characters(self):
        from storyforge.hone import detect_onstage_subset_violation
        intent_map = {
            'scene-a': {
                'id': 'scene-a',
                'characters': 'kael;sera',
                'on_stage': 'kael;sera;bren',
            },
        }
        results = detect_onstage_subset_violation(intent_map)
        assert len(results) == 1
        assert results[0]['issue'] == 'not_subset'
        assert 'bren' in results[0]['violating']

    def test_passes_valid_subset(self):
        from storyforge.hone import detect_onstage_subset_violation
        intent_map = {
            'scene-a': {
                'id': 'scene-a',
                'characters': 'kael;sera;bren',
                'on_stage': 'kael;sera',
            },
        }
        results = detect_onstage_subset_violation(intent_map)
        assert len(results) == 0

    def test_skips_empty_onstage(self):
        from storyforge.hone import detect_onstage_subset_violation
        intent_map = {
            'scene-a': {
                'id': 'scene-a',
                'characters': 'kael;sera',
                'on_stage': '',
            },
        }
        results = detect_onstage_subset_violation(intent_map)
        assert len(results) == 0


class TestValueShiftOutcomeMismatch:
    def test_flags_yes_with_negative_shift(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent_map = {
            'scene-a': {'id': 'scene-a', 'value_shift': '+/-'},
        }
        briefs_map = {
            'scene-a': {'id': 'scene-a', 'outcome': 'yes'},
        }
        results = detect_value_shift_outcome_mismatch(intent_map, briefs_map)
        assert len(results) == 1
        assert results[0]['issue'] == 'outcome_mismatch'

    def test_flags_no_with_positive_shift(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent_map = {
            'scene-a': {'id': 'scene-a', 'value_shift': '-/+'},
        }
        briefs_map = {
            'scene-a': {'id': 'scene-a', 'outcome': 'no'},
        }
        results = detect_value_shift_outcome_mismatch(intent_map, briefs_map)
        assert len(results) == 1

    def test_passes_yes_with_positive_shift(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent_map = {
            'scene-a': {'id': 'scene-a', 'value_shift': '-/+'},
        }
        briefs_map = {
            'scene-a': {'id': 'scene-a', 'outcome': 'yes'},
        }
        results = detect_value_shift_outcome_mismatch(intent_map, briefs_map)
        assert len(results) == 0

    def test_passes_yes_but_with_any_shift(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent_map = {
            'scene-a': {'id': 'scene-a', 'value_shift': '+/-'},
        }
        briefs_map = {
            'scene-a': {'id': 'scene-a', 'outcome': 'yes-but'},
        }
        results = detect_value_shift_outcome_mismatch(intent_map, briefs_map)
        assert len(results) == 0

    def test_skips_empty_fields(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent_map = {'scene-a': {'id': 'scene-a', 'value_shift': ''}}
        briefs_map = {'scene-a': {'id': 'scene-a', 'outcome': 'yes'}}
        results = detect_value_shift_outcome_mismatch(intent_map, briefs_map)
        assert len(results) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_hone_intent.py::TestOnstageSubsetViolation tests/test_hone_intent.py::TestValueShiftOutcomeMismatch -v`
Expected: FAIL

- [ ] **Step 3: Implement on-stage subset and value-shift/outcome detectors**

Add to `scripts/lib/python/storyforge/hone.py` after the emotional arc detectors:

```python
# ============================================================================
# Intent domain: on-stage subset validation
# ============================================================================

def detect_onstage_subset_violation(
    intent_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect scenes where on_stage contains characters not in the characters field.

    Returns:
        List of dicts: {scene_id, field, value, violating, issue: 'not_subset'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(intent_map.keys())

    for sid in ids_to_check:
        intent = intent_map.get(sid, {})
        characters_raw = intent.get('characters', '').strip()
        on_stage_raw = intent.get('on_stage', '').strip()
        if not on_stage_raw:
            continue

        characters = {c.strip().lower() for c in characters_raw.split(';') if c.strip()}
        on_stage = {c.strip().lower() for c in on_stage_raw.split(';') if c.strip()}
        violating = sorted(on_stage - characters)

        if violating:
            results.append({
                'scene_id': sid,
                'field': 'on_stage',
                'value': on_stage_raw,
                'violating': violating,
                'issue': 'not_subset',
            })

    return results


# ============================================================================
# Intent domain: value-shift / outcome mismatch
# ============================================================================

# Shift endings that indicate positive movement for the character.
_POSITIVE_SHIFT_ENDINGS = {'/+', '/++'}
# Shift endings that indicate negative movement.
_NEGATIVE_SHIFT_ENDINGS = {'/-', '/--'}


def detect_value_shift_outcome_mismatch(
    intent_map: dict[str, dict[str, str]],
    briefs_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect scenes where value_shift polarity contradicts the outcome.

    Rules:
    - outcome='yes' → shift should end positive (/+ or /++)
    - outcome='no' → shift should end negative (/- or /--)
    - outcome='yes-but' or 'no-and' → any shift is plausible (mixed results)

    Returns:
        List of dicts: {scene_id, field, value, value_shift, outcome,
                        issue: 'outcome_mismatch'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(intent_map.keys())

    for sid in ids_to_check:
        intent = intent_map.get(sid, {})
        brief = briefs_map.get(sid, {})
        value_shift = intent.get('value_shift', '').strip()
        outcome = brief.get('outcome', '').strip().lower()

        if not value_shift or not outcome:
            continue

        # yes-but and no-and are inherently mixed — no mismatch possible
        if outcome in ('yes-but', 'no-and'):
            continue

        mismatch = False
        if outcome == 'yes':
            # Won — expect positive ending
            mismatch = any(value_shift.endswith(e) for e in _NEGATIVE_SHIFT_ENDINGS)
        elif outcome == 'no':
            # Lost — expect negative ending
            mismatch = any(value_shift.endswith(e) for e in _POSITIVE_SHIFT_ENDINGS)

        if mismatch:
            results.append({
                'scene_id': sid,
                'field': 'value_shift',
                'value': value_shift,
                'value_shift': value_shift,
                'outcome': outcome,
                'issue': 'outcome_mismatch',
            })

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hone_intent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_hone_intent.py scripts/lib/python/storyforge/hone.py
git commit -m "Add intent detection: on-stage subset and value-shift/outcome mismatch"
git push
```

---

### Task 4: Combined Intent Detection & Intent Fix Prompts

**Files:**
- Modify: `tests/test_hone_intent.py`
- Modify: `scripts/lib/python/storyforge/hone.py`

- [ ] **Step 1: Write failing tests for combined detector and prompts**

Append to `tests/test_hone_intent.py`:

```python
class TestDetectIntentIssues:
    def test_combines_all_detectors(self):
        from storyforge.hone import detect_intent_issues
        intent_map = {
            'scene-a': {
                'id': 'scene-a',
                'function': 'She realizes and connects and transforms through growth',
                'emotional_arc': 'tension',
                'characters': 'kael;sera',
                'on_stage': 'kael;sera;bren',
                'value_shift': '+/-',
            },
        }
        briefs_map = {
            'scene-a': {'id': 'scene-a', 'outcome': 'yes'},
        }
        scenes_map = {'scene-a': {'id': 'scene-a'}}
        results = detect_intent_issues(intent_map, scenes_map, briefs_map)
        issues = {r['issue'] for r in results}
        assert 'vague' in issues
        assert 'flat' in issues
        assert 'not_subset' in issues
        assert 'outcome_mismatch' in issues

    def test_respects_scene_filter(self):
        from storyforge.hone import detect_intent_issues
        intent_map = {
            'scene-a': {
                'id': 'scene-a',
                'function': 'She realizes and connects and transforms',
                'emotional_arc': '',
                'characters': '',
                'on_stage': '',
                'value_shift': '',
            },
            'scene-b': {
                'id': 'scene-b',
                'function': 'He realizes and connects and transforms',
                'emotional_arc': '',
                'characters': '',
                'on_stage': '',
                'value_shift': '',
            },
        }
        briefs_map = {}
        scenes_map = {'scene-a': {'id': 'scene-a'}, 'scene-b': {'id': 'scene-b'}}
        results = detect_intent_issues(intent_map, scenes_map, briefs_map, scene_ids=['scene-a'])
        scene_ids = {r['scene_id'] for r in results}
        assert 'scene-b' not in scene_ids


class TestBuildIntentFixPrompt:
    def test_includes_fields_and_scene_id(self):
        from storyforge.hone import build_intent_fix_prompt
        prompt = build_intent_fix_prompt(
            scene_id='test-scene',
            fields=['function', 'emotional_arc'],
            current_values={
                'function': 'She realizes the truth',
                'emotional_arc': 'tension',
            },
            issues=[
                {'field': 'function', 'issue': 'vague'},
                {'field': 'emotional_arc', 'issue': 'flat'},
            ],
        )
        assert 'test-scene' in prompt
        assert 'function' in prompt
        assert 'emotional_arc' in prompt
        assert 'She realizes the truth' in prompt
        assert 'vague' in prompt or 'testable' in prompt.lower()

    def test_output_format_contains_field_labels(self):
        from storyforge.hone import build_intent_fix_prompt
        prompt = build_intent_fix_prompt(
            scene_id='test-scene',
            fields=['function'],
            current_values={'function': 'She realizes things'},
            issues=[{'field': 'function', 'issue': 'vague'}],
        )
        assert 'function:' in prompt.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_hone_intent.py::TestDetectIntentIssues tests/test_hone_intent.py::TestBuildIntentFixPrompt -v`
Expected: FAIL

- [ ] **Step 3: Implement `detect_intent_issues()` and `build_intent_fix_prompt()`**

Add to `scripts/lib/python/storyforge/hone.py` after the individual detectors:

```python
# ============================================================================
# Intent domain: combined detection
# ============================================================================

def detect_intent_issues(
    intent_map: dict[str, dict[str, str]],
    scenes_map: dict[str, dict[str, str]],
    briefs_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Run all intent quality detectors and return combined results.

    Args:
        intent_map: dict keyed by scene ID.
        scenes_map: dict keyed by scene ID.
        briefs_map: dict keyed by scene ID (needed for outcome cross-check).
        scene_ids: Optional scope.

    Returns:
        Combined list of all issue dicts, sorted by scene_id then field.
    """
    issues = []
    issues.extend(detect_vague_function(intent_map, scene_ids))
    issues.extend(detect_overlong_function(intent_map, scene_ids))
    issues.extend(detect_flat_emotional_arc(intent_map, scene_ids))
    issues.extend(detect_abstract_emotional_arc(intent_map, scene_ids))
    issues.extend(detect_onstage_subset_violation(intent_map, scene_ids))
    issues.extend(detect_value_shift_outcome_mismatch(intent_map, briefs_map, scene_ids))
    issues.sort(key=lambda d: (d['scene_id'], d.get('field', ''), d['issue']))
    return issues


# ============================================================================
# Intent domain: fix prompt builder
# ============================================================================

_ISSUE_FIX_INSTRUCTIONS = {
    'vague': 'Rewrite as a testable statement — what the character physically does or decides. Use concrete action verbs (reads, signs, refuses, confronts).',
    'overlong': 'Compress to 1-3 sentences. State why this scene exists, not what happens beat by beat.',
    'flat': 'Rewrite as a transition: "X giving way to Y" where X and Y are grounded emotions the reader can track.',
    'abstract_arc': 'Replace abstract emotion words (tension, growth, shift, resolution) with grounded ones (dread, relief, shame, pride, longing).',
}


def build_intent_fix_prompt(
    scene_id: str,
    fields: list[str],
    current_values: dict[str, str],
    issues: list[dict],
    voice_guide: str = '',
) -> str:
    """Build prompt to fix intent quality issues for a scene.

    Args:
        scene_id: The scene being fixed.
        fields: List of field names to rewrite.
        current_values: Dict of field_name -> current value.
        issues: List of issue dicts for this scene.
        voice_guide: Optional excerpt from voice guide.

    Returns:
        Prompt string for Claude.
    """
    issue_block = []
    for issue in issues:
        field = issue['field']
        issue_type = issue['issue']
        instruction = _ISSUE_FIX_INSTRUCTIONS.get(issue_type, f'Fix the {issue_type} issue.')
        issue_block.append(f'**{field}** — {issue_type}: {instruction}')

    field_block = '\n'.join(
        f'**{field}:** {current_values.get(field, "")}'
        for field in fields
    )

    field_output = '\n'.join(f'{field}: [rewritten value]' for field in fields)

    return f"""Rewrite these scene-intent fields to fix the identified quality issues.

## Scene: {scene_id}

## Issues to Fix
{chr(10).join(issue_block)}

## Current Values
{field_block}

{f"## Voice Guide{chr(10)}{voice_guide[:3000]}" if voice_guide else ""}

## Rules

1. Preserve the narrative content — fix HOW it's expressed, not WHAT happens.
2. Function must be testable: after reading the scene, you can verify whether this happened.
3. Emotional arc must be a transition with grounded emotion words, not abstractions.
4. Keep values concise — function: 1-3 sentences; emotional_arc: one "X giving way to Y" phrase.

## Output Format

Return each field on its own labeled line:

{field_output}

No explanation. No markdown. Just the labeled lines."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hone_intent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_hone_intent.py scripts/lib/python/storyforge/hone.py
git commit -m "Add combined intent detection and intent fix prompt builder"
git push
```

---

### Task 5: External Findings Loader

**Files:**
- Create: `tests/test_hone_findings.py`
- Modify: `scripts/lib/python/storyforge/hone.py`

- [ ] **Step 1: Write failing tests for findings loader**

```python
# tests/test_hone_findings.py
"""Tests for external findings loading and integration with hone."""

import os


class TestLoadExternalFindings:
    def test_parses_findings_csv(self, tmp_path):
        from storyforge.hone import load_external_findings
        f = tmp_path / 'findings.csv'
        f.write_text(
            'scene_id|target_file|fields|guidance\n'
            'scene-a|scene-briefs.csv|goal;conflict|Fix hallucinated characters\n'
            'scene-b|scene-intent.csv|function|Function is too vague\n'
        )
        results = load_external_findings(str(f))
        assert len(results) == 3  # scene-a has 2 fields, scene-b has 1
        # scene-a goal
        r0 = [r for r in results if r['scene_id'] == 'scene-a' and r['field'] == 'goal'][0]
        assert r0['issue'] == 'evaluation'
        assert r0['guidance'] == 'Fix hallucinated characters'
        assert r0['target_file'] == 'scene-briefs.csv'
        # scene-a conflict
        r1 = [r for r in results if r['scene_id'] == 'scene-a' and r['field'] == 'conflict'][0]
        assert r1['issue'] == 'evaluation'
        # scene-b function
        r2 = [r for r in results if r['scene_id'] == 'scene-b'][0]
        assert r2['target_file'] == 'scene-intent.csv'

    def test_empty_fields_means_all_fields(self, tmp_path):
        from storyforge.hone import load_external_findings
        f = tmp_path / 'findings.csv'
        f.write_text(
            'scene_id|target_file|fields|guidance\n'
            'scene-a|scene-briefs.csv||General fix needed\n'
        )
        results = load_external_findings(str(f))
        # Empty fields → single issue with field='' (hone will detect which fields need work)
        assert len(results) == 1
        assert results[0]['field'] == ''
        assert results[0]['guidance'] == 'General fix needed'

    def test_missing_file_returns_empty(self):
        from storyforge.hone import load_external_findings
        results = load_external_findings('/nonexistent/file.csv')
        assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_hone_findings.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `load_external_findings()`**

Add to `scripts/lib/python/storyforge/hone.py` before the `hone_briefs` function:

```python
# ============================================================================
# External findings loader
# ============================================================================

def load_external_findings(findings_file: str) -> list[dict]:
    """Load external findings from a revision plan findings file.

    The file is pipe-delimited CSV with columns:
        scene_id|target_file|fields|guidance

    When 'fields' contains semicolon-separated field names, one issue dict
    is created per field. When 'fields' is empty, a single issue with
    field='' is created (hone will detect which fields need work).

    Returns:
        List of issue dicts: {scene_id, field, target_file, guidance,
                              issue: 'evaluation'}.
    """
    if not os.path.isfile(findings_file):
        return []

    results = []
    with open(findings_file) as f:
        reader = csv.DictReader(f, delimiter='|')
        for row in reader:
            sid = row.get('scene_id', '').strip()
            target_file = row.get('target_file', '').strip()
            fields_raw = row.get('fields', '').strip()
            guidance = row.get('guidance', '').strip()

            if not sid:
                continue

            if fields_raw:
                for field in fields_raw.split(';'):
                    field = field.strip()
                    if field:
                        results.append({
                            'scene_id': sid,
                            'field': field,
                            'target_file': target_file,
                            'guidance': guidance,
                            'issue': 'evaluation',
                        })
            else:
                results.append({
                    'scene_id': sid,
                    'field': '',
                    'target_file': target_file,
                    'guidance': guidance,
                    'issue': 'evaluation',
                })

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hone_findings.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_hone_findings.py scripts/lib/python/storyforge/hone.py
git commit -m "Add external findings loader for hone"
git push
```

---

### Task 6: Evaluation Fix Prompt & Modify `hone_briefs()` for Findings

**Files:**
- Modify: `tests/test_hone_findings.py`
- Modify: `scripts/lib/python/storyforge/hone.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_hone_findings.py`:

```python
class TestBuildEvaluationFixPrompt:
    def test_includes_guidance_and_fields(self):
        from storyforge.hone import build_evaluation_fix_prompt
        prompt = build_evaluation_fix_prompt(
            scene_id='test-scene',
            fields=['goal', 'conflict'],
            current_values={'goal': 'old goal', 'conflict': 'old conflict'},
            guidance='Fix hallucinated characters Voss and Dren',
        )
        assert 'test-scene' in prompt
        assert 'goal' in prompt
        assert 'conflict' in prompt
        assert 'old goal' in prompt
        assert 'Voss' in prompt or 'hallucinated' in prompt.lower()

    def test_output_format(self):
        from storyforge.hone import build_evaluation_fix_prompt
        prompt = build_evaluation_fix_prompt(
            scene_id='s1',
            fields=['goal'],
            current_values={'goal': 'x'},
            guidance='fix it',
        )
        assert 'goal:' in prompt.lower()


class TestHoneBriefsWithFindings:
    def test_signature_accepts_findings_file(self):
        """Verify hone_briefs accepts the findings_file parameter."""
        import inspect
        from storyforge.hone import hone_briefs
        sig = inspect.signature(hone_briefs)
        assert 'findings_file' in sig.parameters
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_hone_findings.py::TestBuildEvaluationFixPrompt tests/test_hone_findings.py::TestHoneBriefsWithFindings -v`
Expected: FAIL

- [ ] **Step 3: Implement `build_evaluation_fix_prompt()` and modify `hone_briefs()` signature**

Add `build_evaluation_fix_prompt` to `scripts/lib/python/storyforge/hone.py` near the other prompt builders:

```python
# ============================================================================
# Evaluation-driven fix prompt (shared by briefs and intent)
# ============================================================================

def build_evaluation_fix_prompt(
    scene_id: str,
    fields: list[str],
    current_values: dict[str, str],
    guidance: str,
    voice_guide: str = '',
    character_entry: str = '',
) -> str:
    """Build prompt to fix fields based on evaluation findings.

    This is used when revision passes delegate to hone with specific
    guidance from evaluation (e.g., 'fix hallucinated characters').

    Args:
        scene_id: The scene being fixed.
        fields: List of field names to rewrite.
        current_values: Dict of field_name -> current value.
        guidance: Evaluation guidance text describing what to fix.
        voice_guide: Optional excerpt from voice guide.
        character_entry: Optional character bible entry.

    Returns:
        Prompt string for Claude.
    """
    field_block = '\n'.join(
        f'**{field}:** {current_values.get(field, "")}'
        for field in fields
    )

    field_output = '\n'.join(f'{field}: [rewritten value]' for field in fields)

    return f"""Rewrite these scene data fields to address evaluation findings.

## Scene: {scene_id}

## Evaluation Guidance
{guidance}

## Current Values
{field_block}

{f"## Voice Guide{chr(10)}{voice_guide[:3000]}" if voice_guide else ""}
{f"## Character{chr(10)}{character_entry[:2000]}" if character_entry else ""}

## Rules

1. Address the evaluation guidance directly — this is the primary objective.
2. Every action must be something the POV character physically does or perceives.
3. Do not invent characters, locations, or events not established in the novel.
4. Keep fields concise: beat lists use semicolons, short phrases preferred.
5. Preserve all values you are not fixing.

## Output Format

Return each field on its own labeled line:

{field_output}

No explanation. No markdown. Just the labeled lines."""
```

Modify `hone_briefs()` in `scripts/lib/python/storyforge/hone.py` to accept and process `findings_file`:

Change the function signature (around line 1292) from:

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
```

to:

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
    findings_file: str | None = None,
) -> dict:
```

After the line `all_issues = detect_brief_issues(briefs_map, scenes_map, scene_ids, intent_map=intent_map)` (around line 1323), add:

```python
    # Merge external findings if provided
    if findings_file:
        external = load_external_findings(findings_file)
        external_briefs = [e for e in external if e.get('target_file', '') == 'scene-briefs.csv']
        # External findings with specific fields take priority
        existing_keys = {(i['scene_id'], i['field']) for i in all_issues}
        for ext in external_briefs:
            if ext['field'] and (ext['scene_id'], ext['field']) not in existing_keys:
                all_issues.append(ext)
            elif ext['field']:
                # Replace detected issue with external (has guidance)
                all_issues = [i for i in all_issues
                              if not (i['scene_id'] == ext['scene_id'] and i['field'] == ext['field'])]
                all_issues.append(ext)
            elif not ext['field']:
                # Empty field = general guidance, add as-is
                all_issues.append(ext)
```

After the trim handling block (around line 1427), add handling for evaluation issues:

```python
        # Handle evaluation issues (from external findings)
        eval_issues = [i for i in issues if i['issue'] == 'evaluation']
        if eval_issues and coaching_level == 'full':
            eval_fields = list(set(i['field'] for i in eval_issues if i['field']))
            if not eval_fields:
                # Empty field = all brief fields for this scene
                eval_fields = [f for f in briefs_map[sid].keys() if f != 'id' and briefs_map[sid].get(f, '')]
            current_values = {f: briefs_map[sid].get(f, '') for f in eval_fields}
            guidance = '; '.join(i.get('guidance', '') for i in eval_issues if i.get('guidance'))

            prompt = build_evaluation_fix_prompt(
                scene_id=sid,
                fields=eval_fields,
                current_values=current_values,
                guidance=guidance,
                voice_guide=voice_guide[:3000],
                character_entry=char_bible[:2000],
            )

            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f'hone-eval-{sid}.json')
            invoke_to_file(prompt, model, log_file, max_tokens=2048,
                           label=f'hone eval {idx}/{total_scenes} ({sid})')
            response = extract_text_from_file(log_file)

            rewrites = parse_concretize_response(response, sid, eval_fields)
            for field, new_value in rewrites.items():
                if new_value and new_value != current_values.get(field):
                    briefs_map[sid][field] = new_value
                    fields_rewritten += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hone_findings.py -v`
Expected: All PASS

- [ ] **Step 5: Run full hone test suite**

Run: `python3 -m pytest tests/test_hone.py tests/test_hone_conflict.py tests/test_hone_findings.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_hone_findings.py scripts/lib/python/storyforge/hone.py
git commit -m "Add evaluation fix prompt, wire findings into hone_briefs"
git push
```

---

### Task 7: `hone_intent()` Function

**Files:**
- Modify: `tests/test_hone_intent.py`
- Modify: `scripts/lib/python/storyforge/hone.py`

- [ ] **Step 1: Write failing tests for `hone_intent()`**

Append to `tests/test_hone_intent.py`:

```python
import inspect


class TestHoneIntentSignature:
    def test_accepts_expected_params(self):
        from storyforge.hone import hone_intent
        sig = inspect.signature(hone_intent)
        params = list(sig.parameters.keys())
        assert 'ref_dir' in params
        assert 'project_dir' in params
        assert 'scene_ids' in params
        assert 'findings_file' in params
        assert 'model' in params
        assert 'log_dir' in params
        assert 'coaching_level' in params
        assert 'dry_run' in params

    def test_returns_result_dict(self):
        from storyforge.hone import hone_intent
        # Dry run with no data — should return zeroed stats
        result = hone_intent(
            ref_dir='/nonexistent',
            project_dir='/nonexistent',
            dry_run=True,
        )
        assert 'scenes_flagged' in result
        assert 'scenes_rewritten' in result
        assert 'fields_rewritten' in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_hone_intent.py::TestHoneIntentSignature -v`
Expected: FAIL

- [ ] **Step 3: Implement `hone_intent()`**

Add to `scripts/lib/python/storyforge/hone.py` after `detect_intent_issues`:

```python
# ============================================================================
# Intent domain: hone_intent
# ============================================================================

def hone_intent(
    ref_dir: str,
    project_dir: str,
    scene_ids: list[str] | None = None,
    model: str = '',
    log_dir: str = '',
    coaching_level: str = 'full',
    dry_run: bool = False,
    findings_file: str | None = None,
) -> dict:
    """Fix intent quality issues: vague functions, flat arcs, subset violations.

    Args:
        ref_dir: Path to reference/ directory.
        project_dir: Path to project root.
        scene_ids: Optional list of scene IDs to check. If None, check all.
        model: Anthropic model ID for API calls.
        log_dir: Directory for API log files.
        coaching_level: full/coach/strict.
        dry_run: If True, detect but don't rewrite.
        findings_file: Optional path to external findings CSV.

    Returns:
        Dict with scenes_flagged, scenes_rewritten, fields_rewritten.
    """
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')
    if not os.path.isfile(intent_path):
        return {'scenes_flagged': 0, 'scenes_rewritten': 0, 'fields_rewritten': 0}

    intent_map = _read_csv_as_map(intent_path)
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    scenes_map = _read_csv_as_map(scenes_path) if os.path.isfile(scenes_path) else {}
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    briefs_map = _read_csv_as_map(briefs_path) if os.path.isfile(briefs_path) else {}

    all_issues = detect_intent_issues(intent_map, scenes_map, briefs_map, scene_ids)

    # Merge external findings if provided
    if findings_file:
        external = load_external_findings(findings_file)
        external_intent = [e for e in external if e.get('target_file', '') == 'scene-intent.csv']
        existing_keys = {(i['scene_id'], i['field']) for i in all_issues}
        for ext in external_intent:
            if ext['field'] and (ext['scene_id'], ext['field']) not in existing_keys:
                all_issues.append(ext)
            elif ext['field']:
                all_issues = [i for i in all_issues
                              if not (i['scene_id'] == ext['scene_id'] and i['field'] == ext['field'])]
                all_issues.append(ext)
            elif not ext['field']:
                all_issues.append(ext)

    if dry_run or not all_issues:
        return {
            'scenes_flagged': len(set(i['scene_id'] for i in all_issues)),
            'scenes_rewritten': 0,
            'fields_rewritten': 0,
        }

    # Fix deterministic issues first (no API needed)
    deterministic_fixed = 0
    for issue in all_issues:
        if issue['issue'] == 'not_subset':
            sid = issue['scene_id']
            characters = {c.strip().lower() for c in intent_map[sid].get('characters', '').split(';') if c.strip()}
            on_stage = [c.strip() for c in intent_map[sid].get('on_stage', '').split(';') if c.strip()]
            fixed = [c for c in on_stage if c.lower() in characters]
            intent_map[sid]['on_stage'] = ';'.join(fixed)
            deterministic_fixed += 1

    # Group API-fixable issues by scene
    api_issues = [i for i in all_issues if i['issue'] not in ('not_subset',)]
    by_scene: dict[str, list[dict]] = {}
    for issue in api_issues:
        by_scene.setdefault(issue['scene_id'], []).append(issue)

    if coaching_level == 'strict':
        hone_dir = os.path.join(project_dir, 'working', 'hone')
        os.makedirs(hone_dir, exist_ok=True)
        for sid, issues in by_scene.items():
            path = os.path.join(hone_dir, f'intent-analysis-{sid}.md')
            with open(path, 'w') as fh:
                for i in issues:
                    fh.write(f"**{i.get('field', 'general')}:** {i['issue']}\n")
                    if 'value' in i:
                        fh.write(f"  Current: {i['value'][:200]}\n")
        return {
            'scenes_flagged': len(set(i['scene_id'] for i in all_issues)),
            'scenes_rewritten': 0,
            'fields_rewritten': deterministic_fixed,
        }

    # Load voice guide for prompt building
    voice_guide = ''
    voice_path = os.path.join(ref_dir, 'voice-guide.md')
    if os.path.isfile(voice_path):
        with open(voice_path, encoding='utf-8') as fh:
            voice_guide = fh.read()

    from storyforge.api import invoke_to_file, extract_text_from_file

    scenes_rewritten = 0
    fields_rewritten = deterministic_fixed
    total_scenes = len(by_scene)

    for idx, (sid, issues) in enumerate(by_scene.items(), 1):
        issue_types = sorted(set(i['issue'] for i in issues))
        log(f'  [{idx}/{total_scenes}] {sid} ({", ".join(issue_types)})')

        # Separate evaluation issues from detected issues
        eval_issues = [i for i in issues if i['issue'] == 'evaluation']
        detected_issues = [i for i in issues if i['issue'] != 'evaluation']

        # Handle detected quality issues
        if detected_issues and coaching_level == 'full':
            det_fields = list(set(i['field'] for i in detected_issues))
            current_values = {f: intent_map[sid].get(f, '') for f in det_fields}

            prompt = build_intent_fix_prompt(
                scene_id=sid,
                fields=det_fields,
                current_values=current_values,
                issues=detected_issues,
                voice_guide=voice_guide[:3000],
            )

            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f'hone-intent-{sid}.json')
            invoke_to_file(prompt, model, log_file, max_tokens=2048,
                           label=f'hone intent {idx}/{total_scenes} ({sid})')
            response = extract_text_from_file(log_file)

            rewrites = parse_concretize_response(response, sid, det_fields)
            for field, new_value in rewrites.items():
                if new_value and new_value != current_values.get(field):
                    intent_map[sid][field] = new_value
                    fields_rewritten += 1

        # Handle evaluation-driven issues
        if eval_issues and coaching_level == 'full':
            eval_fields = list(set(i['field'] for i in eval_issues if i['field']))
            if not eval_fields:
                eval_fields = [f for f in intent_map[sid].keys() if f != 'id' and intent_map[sid].get(f, '')]
            current_values = {f: intent_map[sid].get(f, '') for f in eval_fields}
            guidance = '; '.join(i.get('guidance', '') for i in eval_issues if i.get('guidance'))

            prompt = build_evaluation_fix_prompt(
                scene_id=sid,
                fields=eval_fields,
                current_values=current_values,
                guidance=guidance,
                voice_guide=voice_guide[:3000],
            )

            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f'hone-intent-eval-{sid}.json')
            invoke_to_file(prompt, model, log_file, max_tokens=2048,
                           label=f'hone intent eval {idx}/{total_scenes} ({sid})')
            response = extract_text_from_file(log_file)

            rewrites = parse_concretize_response(response, sid, eval_fields)
            for field, new_value in rewrites.items():
                if new_value and new_value != current_values.get(field):
                    intent_map[sid][field] = new_value
                    fields_rewritten += 1

        # Coach mode proposals
        if coaching_level == 'coach':
            hone_dir = os.path.join(project_dir, 'working', 'hone')
            os.makedirs(hone_dir, exist_ok=True)
            path = os.path.join(hone_dir, f'intent-{sid}.md')
            with open(path, 'w') as fh:
                fh.write(f"# Intent Quality Proposals: {sid}\n\n")
                for issue in issues:
                    fh.write(f"## {issue.get('field', 'general')} — {issue['issue']}\n")
                    if 'value' in issue:
                        fh.write(f"**Current:** {issue['value'][:300]}\n\n")
            continue

        scenes_rewritten += 1

    # Write back if any changes were made
    if fields_rewritten > 0:
        intent_rows = list(intent_map.values())
        intent_rows.sort(key=lambda r: r.get('id', ''))
        _write_csv(
            os.path.join(ref_dir, 'scene-intent.csv'),
            intent_rows,
            _FILE_MAP['scene-intent.csv'],
        )

    return {
        'scenes_flagged': len(set(i['scene_id'] for i in all_issues)),
        'scenes_rewritten': scenes_rewritten,
        'fields_rewritten': fields_rewritten,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hone_intent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_hone_intent.py scripts/lib/python/storyforge/hone.py
git commit -m "Add hone_intent() with findings support and quality fixing"
git push
```

---

### Task 8: Wire Intent Domain into `cmd_hone.py`

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_hone.py`

- [ ] **Step 1: Write failing test for --findings flag and intent domain**

Create file `tests/test_cmd_hone_intent.py`:

```python
# tests/test_cmd_hone_intent.py
"""Tests for hone CLI intent domain and --findings flag."""


class TestHoneParseArgs:
    def test_findings_flag(self):
        from storyforge.cmd_hone import parse_args
        args = parse_args(['--findings', '/tmp/findings.csv'])
        assert args.findings == '/tmp/findings.csv'

    def test_findings_default_none(self):
        from storyforge.cmd_hone import parse_args
        args = parse_args([])
        assert args.findings is None

    def test_intent_domain(self):
        from storyforge.cmd_hone import parse_args
        args = parse_args(['--domain', 'intent'])
        assert args.domain == 'intent'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cmd_hone_intent.py -v`
Expected: FAIL — `args.findings` attribute error

- [ ] **Step 3: Add --findings flag, intent domain, and _run_intent_domain**

In `scripts/lib/python/storyforge/cmd_hone.py`:

Add to `parse_args()` after the `--max-loops` argument (around line 60):

```python
    parser.add_argument('--findings', metavar='FILE', default=None,
                        help='External findings file (from evaluation/revision)')
```

Update `ALL_DOMAINS` (line 30) to include intent:

```python
ALL_DOMAINS = ['registries', 'gaps', 'structural', 'briefs', 'intent']
```

Add `_run_intent_domain` function after `_run_briefs_domain` (around line 285):

```python
def _run_intent_domain(ref_dir: str, project_dir: str, log_dir: str,
                       model: str, coaching: str, scene_filter: list[str] | None,
                       dry_run: bool, findings_file: str | None = None) -> None:
    from storyforge.elaborate import _read_csv_as_map
    from storyforge.hone import detect_intent_issues, hone_intent

    intent_path = os.path.join(ref_dir, 'scene-intent.csv')
    if not os.path.isfile(intent_path):
        log('  No scene-intent.csv found — skipping')
        return

    intent = _read_csv_as_map(intent_path)
    scenes = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    briefs = _read_csv_as_map(briefs_path) if os.path.isfile(briefs_path) else {}

    issues = detect_intent_issues(intent, scenes, briefs, scene_filter)

    by_type: dict[str, list] = {}
    for i in issues:
        by_type.setdefault(i['issue'], []).append(i)

    total = len(issues)
    affected = len(set(i['scene_id'] for i in issues))
    log(f'  Issues found: {total} across {affected} scenes')
    for issue_type, items in sorted(by_type.items()):
        log(f'    {issue_type}: {len(items)}')

    if dry_run:
        for i in issues:
            log(f"  {i['scene_id']}.{i.get('field', '?')}: {i['issue']}")
        return

    if total == 0 and not findings_file:
        log('  No intent quality issues found')
        return

    result = hone_intent(
        ref_dir, project_dir,
        scene_ids=scene_filter,
        model=model,
        log_dir=log_dir,
        coaching_level=coaching,
        dry_run=False,
        findings_file=findings_file,
    )

    rewritten = result.get('scenes_rewritten', 0)
    fields = result.get('fields_rewritten', 0)
    log(f'  Rewritten: {rewritten} scenes, {fields} fields')

    if rewritten > 0 or fields > 0:
        commit_and_push(project_dir,
                        f'Hone: intent — {rewritten} scenes fixed ({fields} fields)',
                        ['reference/', 'working/'])
```

Update `_run_domain` to handle `'intent'` (add after the `elif domain == 'gaps':` block):

```python
    elif domain == 'intent':
        findings = getattr(args, 'findings', None) if 'args' in dir() else None
        _run_intent_domain(ref_dir, project_dir, log_dir, model, coaching,
                           scene_filter, dry_run, findings)
```

Actually, `_run_domain` doesn't have access to `args`. We need to thread `findings_file` through. Change `_run_domain` signature and all its callers:

Change `_run_domain` signature from:

```python
def _run_domain(domain: str, ref_dir: str, project_dir: str, log_dir: str,
                model: str, coaching: str, scene_filter: list[str] | None,
                threshold: float, dry_run: bool) -> None:
```

to:

```python
def _run_domain(domain: str, ref_dir: str, project_dir: str, log_dir: str,
                model: str, coaching: str, scene_filter: list[str] | None,
                threshold: float, dry_run: bool,
                findings_file: str | None = None) -> None:
```

Add to the dispatch in `_run_domain`:

```python
    elif domain == 'intent':
        _run_intent_domain(ref_dir, project_dir, log_dir, model, coaching,
                           scene_filter, dry_run, findings_file)
```

Thread `findings_file` through the call in `main()` (around line 142):

```python
    for domain in domains:
        log(f'\n--- Hone: {domain} ---')
        _run_domain(domain, ref_dir, project_dir, log_dir, model, coaching,
                    scene_filter, args.threshold, args.dry_run,
                    findings_file=args.findings)
```

Also pass it to `_run_briefs_domain` — update that function signature too:

Change `_run_briefs_domain` signature to accept `findings_file: str | None = None` and pass it through to `hone_briefs()`.

And update the `_run_domain` dispatch for briefs:

```python
    elif domain == 'briefs':
        _run_briefs_domain(ref_dir, project_dir, log_dir, model, coaching,
                           scene_filter, threshold, dry_run, findings_file)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cmd_hone_intent.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite to check nothing broke**

Run: `python3 -m pytest tests/ -v 2>&1 | tail -20`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add tests/test_cmd_hone_intent.py scripts/lib/python/storyforge/cmd_hone.py
git commit -m "Wire intent domain and --findings flag into hone CLI"
git push
```

---

### Task 9: Revise — Validation Gate & Hone Delegation

**Files:**
- Create: `tests/test_revise_upstream.py`
- Modify: `scripts/lib/python/storyforge/cmd_revise.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_revise_upstream.py
"""Tests for revise upstream delegation and validation gate."""

import hashlib
import os


class TestFileHash:
    def test_consistent_hash(self, tmp_path):
        from storyforge.cmd_revise import _file_hash
        f = tmp_path / 'test.csv'
        f.write_text('id|goal\nscene-a|something\n')
        h1 = _file_hash(str(f))
        h2 = _file_hash(str(f))
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_detects_change(self, tmp_path):
        from storyforge.cmd_revise import _file_hash
        f = tmp_path / 'test.csv'
        f.write_text('id|goal\nscene-a|old\n')
        h1 = _file_hash(str(f))
        f.write_text('id|goal\nscene-a|new\n')
        h2 = _file_hash(str(f))
        assert h1 != h2

    def test_missing_file(self):
        from storyforge.cmd_revise import _file_hash
        assert _file_hash('/nonexistent/file.csv') == ''


class TestWriteHoneFindings:
    def test_writes_correct_format(self, tmp_path):
        from storyforge.cmd_revise import _write_hone_findings
        path = str(tmp_path / 'findings.csv')
        _write_hone_findings(path, 'brief', 'scene-a;scene-b', 'Fix the briefs')

        with open(path) as f:
            content = f.read()
        assert 'scene_id|target_file|fields|guidance' in content
        assert 'scene-a|scene-briefs.csv||Fix the briefs' in content
        assert 'scene-b|scene-briefs.csv||Fix the briefs' in content

    def test_intent_target_file(self, tmp_path):
        from storyforge.cmd_revise import _write_hone_findings
        path = str(tmp_path / 'findings.csv')
        _write_hone_findings(path, 'intent', 'scene-a', 'Fix intent')

        with open(path) as f:
            content = f.read()
        assert 'scene-intent.csv' in content

    def test_empty_targets(self, tmp_path):
        from storyforge.cmd_revise import _write_hone_findings
        path = str(tmp_path / 'findings.csv')
        _write_hone_findings(path, 'brief', '', 'General fix')

        with open(path) as f:
            lines = f.read().strip().split('\n')
        # Only header, no data rows
        assert len(lines) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_revise_upstream.py -v`
Expected: FAIL

- [ ] **Step 3: Add `_file_hash()` and `_write_hone_findings()` to `cmd_revise.py`**

Add `import hashlib` to the imports at the top of `cmd_revise.py` (around line 17).

Add the two functions after the versioned plan functions (around line 140, after `_create_versioned_plan`):

```python
# ============================================================================
# Upstream delegation helpers
# ============================================================================

def _file_hash(path):
    """SHA-256 of file contents, or empty string if file doesn't exist."""
    if not os.path.isfile(path):
        return ''
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _write_hone_findings(path, fix_location, targets, guidance):
    """Write a findings file for hone from revision plan pass data."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    target_file = 'scene-briefs.csv' if fix_location == 'brief' else 'scene-intent.csv'
    scene_ids = [t.strip() for t in targets.split(';') if t.strip()] if targets else []
    with open(path, 'w') as f:
        f.write('scene_id|target_file|fields|guidance\n')
        for sid in scene_ids:
            f.write(f'{sid}|{target_file}||{guidance}\n')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_revise_upstream.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_revise_upstream.py scripts/lib/python/storyforge/cmd_revise.py
git commit -m "Add validation gate helpers: _file_hash, _write_hone_findings"
git push
```

---

### Task 10: Revise — Replace Upstream Path with Hone Delegation

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py`

This is the core change: replacing lines 1368-1550 in the execution loop.

- [ ] **Step 1: Replace the upstream branch in the execution loop**

In `scripts/lib/python/storyforge/cmd_revise.py`, find the block starting with:

```python
        if fix_location in ('brief', 'intent', 'structural', 'registry'):
            # Upstream revision prompt -- built inline via Python
```

and ending with the closing of the `try:` block around line 1550:

```python
                        log(f'  WARNING: Failed to apply upstream changes: {e}')
```

Replace that entire `if fix_location in ('brief', 'intent', 'structural', 'registry'):` branch (keeping the `else:` branch for craft passes) with:

```python
        if fix_location in ('brief', 'intent'):
            # Delegate to hone for upstream CSV fixes
            findings_path = os.path.join(
                project_dir, 'working', 'plans',
                f'hone-findings-{pass_name}.csv')
            _write_hone_findings(findings_path, fix_location, targets, guidance)

            target_csv = os.path.join(
                project_dir, 'reference',
                'scene-briefs.csv' if fix_location == 'brief' else 'scene-intent.csv')
            old_hash = _file_hash(target_csv)

            ref_dir = os.path.join(project_dir, 'reference')
            target_scenes = [t.strip() for t in targets.split(';') if t.strip()] if targets else None

            from storyforge.hone import hone_briefs, hone_intent
            hone_fn = hone_briefs if fix_location == 'brief' else hone_intent
            result = hone_fn(
                ref_dir=ref_dir,
                project_dir=project_dir,
                scene_ids=target_scenes,
                model=pass_model,
                log_dir=log_dir,
                coaching_level=effective_coaching,
                findings_file=findings_path,
            )

            new_hash = _file_hash(target_csv)
            if old_hash == new_hash:
                log(f'  FAILED: Pass "{pass_name}" produced no changes to {os.path.basename(target_csv)}')
                _update_pass_field(plan_rows, pass_num, 'status', 'failed', csv_plan_file)
                end_time = time.time()
                duration = int(end_time - start_time)
                minutes, secs = duration // 60, duration % 60
                log(f'  Time: {minutes}m{secs}s')
                continue

            fields_changed = result.get('fields_rewritten', 0)
            scenes_changed = result.get('scenes_rewritten', 0)
            log(f'  Upstream: {scenes_changed} scenes, {fields_changed} fields rewritten')

            # Redraft affected scenes in full coaching mode
            if effective_coaching == 'full' and targets:
                affected = [t.strip() for t in targets.split(';') if t.strip()]
                _redraft_from_briefs(project_dir, affected, pass_model, log_dir)

        elif fix_location in ('structural', 'registry'):
            # Structural/registry passes keep the existing inline approach
            # (these modify scenes.csv positioning, not content quality)
            from storyforge.elaborate import get_scenes
            ref_dir = os.path.join(project_dir, 'reference')
            scenes = get_scenes(ref_dir)

            target_ids = [t.strip() for t in targets.split(';') if t.strip()] if targets else [s['id'] for s in scenes]
            scene_data = [s for s in scenes if s['id'] in target_ids]

            data_block = []
            for s in scene_data:
                data_block.append(f"Scene: {s.get('id', '')} (seq {s.get('seq', '')}, POV: {s.get('pov', '')})")
                for k, v in s.items():
                    if k not in ('id', 'seq', 'pov') and v:
                        data_block.append(f'  {k}: {str(v)[:120]}')
                data_block.append('')

            csv_type_map = {
                'structural': 'scenes-csv',
            }

            prompt = f'''You are performing an upstream revision on scene data for a novel.

## Pass: {pass_name}
## Purpose: {pass_purpose}
## Fix Location: {fix_location}

## Guidance
{guidance or 'No specific guidance provided.'}

## Protection
{protection or 'No protection constraints.'}

## Current Scene Data

{chr(10).join(data_block)}

## Instructions

Revise the scenes.csv data to address the purpose above.

Output your changes as pipe-delimited CSV rows in a fenced block:

```{csv_type_map.get(fix_location, 'scenes-csv')}
(header row with id as first column)
(one row per scene that needs changes)
```

Rules:
- The first column must be named 'id' (not 'scene_id')
- Only modify scenes listed in the targets
- Preserve all values you are not changing
- Output the full row for each modified scene
'''
```

Note: the structural/registry branch is kept but with a fix: the prompt now explicitly tells Claude to use `id` as the first column name.

- [ ] **Step 2: Remove the old upstream response processing code**

The old code for processing upstream responses (the `if fix_location in ('brief', 'intent', 'structural', 'registry'):` block in the response processing section around line 1496) should also be updated. Since structural/registry passes still use the old approach, keep that processing but remove the brief/intent paths from it.

Find the response processing block:

```python
            if exit_code == 0:
                if fix_location in ('brief', 'intent', 'structural', 'registry'):
```

The brief/intent code path is now handled above (before the API call), so the execution only reaches the response processing for structural/registry and craft passes. Update the condition:

```python
            if exit_code == 0:
                if fix_location in ('structural', 'registry'):
```

- [ ] **Step 3: Add `_redraft_from_briefs()`**

Add after `_write_hone_findings` in `cmd_revise.py`:

```python
def _redraft_from_briefs(project_dir, scene_ids, model, log_dir):
    """Re-draft scenes from their updated briefs."""
    from storyforge.cmd_write import _build_prompt, _extract_scene_from_response
    from storyforge.api import invoke_to_file
    from storyforge.git import commit_and_push

    log(f'  Redrafting {len(scene_ids)} scenes from updated briefs...')
    scenes_dir = os.path.join(project_dir, 'scenes')

    for i, sid in enumerate(scene_ids, 1):
        log(f'    [{i}/{len(scene_ids)}] Redrafting: {sid}')
        prompt = _build_prompt(sid, project_dir, 'full', use_briefs=True)
        if not prompt:
            log(f'    WARNING: Could not build prompt for {sid}, skipping')
            continue
        log_file = os.path.join(log_dir, f'redraft-{sid}.json')
        invoke_to_file(prompt, model, log_file, max_tokens=16384,
                       label=f'redraft {sid}')
        scene_file = os.path.join(scenes_dir, f'{sid}.md')
        _extract_scene_from_response(log_file, scene_file)

    commit_and_push(
        project_dir,
        f'Revision: redraft {len(scene_ids)} scenes from corrected briefs',
        ['scenes/', 'reference/', 'working/'])
```

- [ ] **Step 4: Verify the execution flow is correct**

The execution loop in `main()` now has this structure for each pass:

1. Build prompt:
   - `fix_location in ('brief', 'intent')` → delegate to hone (no API call in revise)
   - `fix_location in ('structural', 'registry')` → inline prompt (existing code, fixed)
   - else (craft) → `revision.py` build-prompt (existing code)

2. For brief/intent: hone handles everything, then validation gate + redraft. Skip the API invocation and response processing.

3. For structural/registry and craft: existing API invocation + response processing.

The key is that for brief/intent, we need to `continue` to the next pass after the delegation block (since the hone call handles the API work). The flow should be:

```
if fix_location in ('brief', 'intent'):
    ... delegate to hone ...
    ... validation gate ...
    ... redraft if needed ...
    # fall through to end_time / commit / mark completed
elif fix_location in ('structural', 'registry'):
    prompt = ...  # build inline prompt
    # fall through to API invocation below
else:
    prompt = ...  # revision.py build-prompt
    # fall through to API invocation below

# Dry-run check (only for structural/registry/craft)
if fix_location not in ('brief', 'intent'):
    if args.dry_run:
        ...
        continue

    # API invocation
    ...
    # Response processing
    ...
```

Make sure to restructure the execution loop so that brief/intent passes skip the API invocation, dry-run printing, and response processing sections (those are handled entirely within the hone delegation block).

- [ ] **Step 5: Run the revise tests**

Run: `python3 -m pytest tests/test_revise_loop.py tests/test_revise_upstream.py -v`
Expected: All PASS

- [ ] **Step 6: Run the full test suite**

Run: `python3 -m pytest tests/ -v 2>&1 | tail -20`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py
git commit -m "Replace upstream revision path with hone delegation and validation gate"
git push
```

---

### Task 11: Update CLAUDE.md, Bump Version, Final Tests

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md`, update the hone command table entry (under `### Commands`):

Change:

```
| `storyforge hone` | `cmd_hone.py` | CSV data quality — registries, briefs, gaps. `--diagnose` for read-only. `--loop` for autonomous convergence. |
```

to:

```
| `storyforge hone` | `cmd_hone.py` | CSV data quality — registries, briefs, intent, gaps. `--diagnose` for read-only. `--loop` for autonomous convergence. `--findings FILE` for evaluation-driven fixes. |
```

In the shared modules table (under `### Domain modules`), update the hone.py entry:

Change:

```
| `hone.py` | CSV data quality: registries, abstract/overspecified/verbose detection, gaps |
```

to:

```
| `hone.py` | CSV data quality: registries, brief detection (abstract/overspecified/verbose), intent detection (vague/overlong/flat/abstract arc/subset/mismatch), evaluation findings, gaps |
```

In the **Skills** table, update the hone entry:

Change:

```
| `hone` | CSV data quality — registries, brief concretization, structural fixes, gap detection. `--diagnose` for read-only assessment. |
```

to:

```
| `hone` | CSV data quality — registries, brief concretization, intent quality, evaluation-driven fixes, gap detection. `--diagnose` for read-only assessment. |
```

Add `hone_intent` to the **hone.py** shared module functions list in the `### Shared Modules — USE THEM` section (if there's a hone entry there).

- [ ] **Step 2: Bump version to 1.6.0**

In `.claude-plugin/plugin.json`, change:

```json
"version": "1.5.1"
```

to:

```json
"version": "1.6.0"
```

- [ ] **Step 3: Run the full test suite one last time**

Run: `python3 -m pytest tests/ -v 2>&1 | tail -30`
Expected: All PASS, no regressions

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md .claude-plugin/plugin.json
git commit -m "Bump version to 1.6.0"
git push
```
