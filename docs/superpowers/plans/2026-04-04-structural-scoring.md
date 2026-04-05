# Structural Scoring Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic structural scoring engine that reads scene CSVs and produces quantified story-quality scores across 8 dimensions, with diagnostic findings and coaching-level-adapted output.

**Architecture:** New Python module `structural.py` with pure functions per scoring dimension. Each function reads CSV maps (from elaborate.py), computes a 0-1 score, and returns findings. A top-level `structural_score()` function orchestrates all dimensions. Output integrated into `storyforge-validate --structural`. Zero API calls — all computation is deterministic over CSV data.

**Tech Stack:** Python 3 (math, statistics — stdlib only), bash test harness

---

## File Structure

| File | Responsibility |
|------|---------------|
| Create: `scripts/lib/python/storyforge/structural.py` | All 8 scoring functions + orchestrator + formatters |
| Create: `tests/test-structural.sh` | Tests for each scoring dimension |
| Modify: `scripts/storyforge-validate` | Add `--structural` flag |
| Modify: `.claude-plugin/plugin.json` | Version bump |
| Modify: `CLAUDE.md` | Document structural scoring |

---

### Task 1: Structural Completeness + Module Skeleton

The simplest dimension — counts populated fields. Establishes the module, test file, and return format that all other dimensions follow.

**Files:**
- Create: `scripts/lib/python/storyforge/structural.py`
- Create: `tests/test-structural.sh`

- [ ] **Step 1: Write failing test**

Create `tests/test-structural.sh`:
```bash
#!/bin/bash
# test-structural.sh — Tests for structural scoring engine

PY="import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python'"

# ============================================================================
# score_completeness
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_completeness

scenes = _read_csv_as_map('${FIXTURE_DIR}/reference/scenes.csv')
intent = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-intent.csv')
briefs = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-briefs.csv')

result = score_completeness(scenes, intent, briefs)
score = result['score']
findings = result['findings']

# Fixture has 6 scenes: 3 briefed with data, new-x1 has empty brief,
# 2 others have partial data
assert 0 <= score <= 1, f'Score out of range: {score}'
assert isinstance(findings, list)
print(f'score={score:.2f}')
print(f'findings={len(findings)}')
print('ok')
")
assert_contains "$RESULT" "ok" "score_completeness: returns score and findings"
assert_contains "$RESULT" "score=" "score_completeness: score is a float"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-structural.sh`
Expected: FAIL — module not found

- [ ] **Step 3: Write structural.py with score_completeness**

Create `scripts/lib/python/storyforge/structural.py`:
```python
"""Structural scoring engine — story quality from CSV data.

Deterministic, no API calls. Reads scene CSVs and produces quantified
scores across 8 dimensions with diagnostic findings.

Each score_* function returns:
    {'score': float (0-1), 'findings': [{'message': str, 'scene_id': str, ...}]}
"""

import math
import os

from storyforge.elaborate import (
    _read_csv, _read_csv_as_map, _write_csv, _FILE_MAP, DELIMITER,
)


# ============================================================================
# Dimension 8: Structural Completeness
# ============================================================================

_REQUIRED_FIELDS = [
    'function', 'value_at_stake', 'value_shift', 'emotional_arc',
    'goal', 'conflict', 'outcome', 'crisis', 'decision',
]
_ENRICHMENT_FIELDS = [
    'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
    'emotions', 'motifs', 'continuity_deps', 'mice_threads',
]


def score_completeness(scenes_map, intent_map, briefs_map):
    """Score how complete the scene data is across all three CSVs.

    Returns dict with 'score' (0-1) and 'findings' list.
    """
    if not scenes_map:
        return {'score': 0.0, 'findings': [{'message': 'No scenes found'}]}

    total_expected = 0
    total_populated = 0
    findings = []

    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    for sid in sorted_ids:
        intent = intent_map.get(sid, {})
        brief = briefs_map.get(sid, {})
        merged = {}
        merged.update(intent)
        merged.update(brief)

        # Required fields
        missing_required = []
        for field in _REQUIRED_FIELDS:
            total_expected += 1
            if merged.get(field, '').strip():
                total_populated += 1
            else:
                missing_required.append(field)

        # Enrichment fields (worth half weight)
        missing_enrichment = []
        for field in _ENRICHMENT_FIELDS:
            total_expected += 0.5
            if merged.get(field, '').strip():
                total_populated += 0.5
            else:
                missing_enrichment.append(field)

        if missing_required:
            findings.append({
                'message': f"Scene {sid} missing required fields: {', '.join(missing_required)}",
                'scene_id': sid,
                'fields': missing_required,
                'severity': 'important',
            })
        elif len(missing_enrichment) > 4:
            findings.append({
                'message': f"Scene {sid} missing {len(missing_enrichment)} enrichment fields",
                'scene_id': sid,
                'fields': missing_enrichment,
                'severity': 'minor',
            })

    score = total_populated / total_expected if total_expected > 0 else 0.0
    return {'score': round(score, 3), 'findings': findings}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-structural.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/structural.py tests/test-structural.sh
git commit -m "Add structural scoring module with completeness dimension"
git push
```

---

### Task 2: Thematic Concentration

**Files:**
- Modify: `scripts/lib/python/storyforge/structural.py`
- Modify: `tests/test-structural.sh`

- [ ] **Step 1: Write failing test**

Append to `tests/test-structural.sh`:
```bash
# ============================================================================
# score_thematic_concentration
# ============================================================================

# Focused novel: 3 values across 6 scenes
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
${PY})
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_thematic_concentration
intent = _read_csv_as_map('${THEME_DIR}/scene-intent.csv')
result = score_thematic_concentration(intent)
print(f'score={result[\"score\"]:.2f}')
# 3 values, well-distributed — should score high
assert result['score'] > 0.6, f'Expected > 0.6, got {result[\"score\"]}'
print('ok')
")
assert_contains "$RESULT" "ok" "score_thematic_concentration: focused novel scores high"

# Scattered novel: 6 unique values across 6 scenes
cat > "${THEME_DIR}/scene-intent.csv" <<'CSV'
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
s01|test|action|flat|truth|+/-|revelation|A|A|
s02|test|action|flat|justice|-/+|revelation|A|A|
s03|test|action|flat|safety|+/-|action|A|A|
s04|test|action|flat|honor|-/+|revelation|A|A|
s05|test|action|flat|love|+/-|action|A|A|
s06|test|action|flat|identity|-/+|revelation|A|A|
CSV

RESULT=$(python3 -c "
${PY})
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_thematic_concentration
intent = _read_csv_as_map('${THEME_DIR}/scene-intent.csv')
result = score_thematic_concentration(intent)
# 6 unique values in 6 scenes — scattered, should score lower
assert result['score'] < 0.5, f'Expected < 0.5, got {result[\"score\"]}'
print('ok')
")
assert_contains "$RESULT" "ok" "score_thematic_concentration: scattered novel scores low"
rm -rf "${TMPDIR}/theme-test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-structural.sh`
Expected: FAIL

- [ ] **Step 3: Write score_thematic_concentration**

Append to `structural.py`:
```python
# ============================================================================
# Dimension 2: Thematic Concentration
# ============================================================================

def score_thematic_concentration(intent_map):
    """Score thematic focus using Herfindahl index on value_at_stake distribution.

    Empirical basis: Archer & Jockers (2016) — bestsellers dedicate ~30%
    of text to 1-2 dominant topics. Herfindahl index measures concentration.
    """
    values = []
    for row in intent_map.values():
        v = row.get('value_at_stake', '').strip()
        if v:
            values.append(v)

    if not values:
        return {'score': 0.0, 'findings': [{'message': 'No value_at_stake data'}]}

    # Count frequencies
    freq = {}
    for v in values:
        freq[v] = freq.get(v, 0) + 1

    n = len(values)
    distinct = len(freq)

    # Herfindahl index: sum of squared proportions (0 to 1)
    # Higher = more concentrated
    hhi = sum((count / n) ** 2 for count in freq.values())

    # Top-2 dominance (Archer/Jockers: bestsellers have ~30% in top 1-2)
    sorted_counts = sorted(freq.values(), reverse=True)
    top2_share = sum(sorted_counts[:2]) / n if len(sorted_counts) >= 2 else 1.0

    findings = []

    # Score: calibrated so that 8-15 values with clear hierarchy scores well
    # HHI of 1/8 = 0.125 (perfectly spread across 8) to 1/15 = 0.067 (across 15)
    # HHI of 0.33 = strong concentration (3 dominant values)
    # We want HHI > 0.08 and distinct count in 8-15 range
    if distinct > 20:
        findings.append({
            'message': f'{distinct} distinct values for {n} scenes — too fragmented',
            'severity': 'important',
        })
    elif distinct < 4 and n > 10:
        findings.append({
            'message': f'Only {distinct} distinct values — thematically narrow',
            'severity': 'minor',
        })

    if top2_share < 0.25:
        findings.append({
            'message': f'Top 2 values cover only {top2_share:.0%} of scenes — no dominant theme',
            'severity': 'important',
        })

    # Sorted value list for diagnosis
    sorted_vals = sorted(freq.items(), key=lambda x: -x[1])
    top_vals = sorted_vals[:5]
    findings.append({
        'message': f'Top values: {", ".join(f"{v} ({c}/{n})" for v, c in top_vals)}',
        'severity': 'info',
    })

    # Convert HHI to 0-1 score
    # Perfect: HHI ~0.15 (6-7 values, some dominant) → score 0.85
    # Good: HHI ~0.08-0.12 (8-12 values, spread) → score 0.65-0.80
    # Bad: HHI ~0.02-0.05 (20+ values, flat) → score 0.20-0.40
    # Also factor in distinct count being in the 8-15 range
    hhi_score = min(1.0, hhi / 0.15)  # Normalize: HHI 0.15+ maps to 1.0
    count_penalty = 0.0
    if distinct > 20:
        count_penalty = min(0.3, (distinct - 20) * 0.015)
    elif distinct < 5 and n > 10:
        count_penalty = 0.1

    score = max(0.0, min(1.0, hhi_score - count_penalty))

    return {'score': round(score, 3), 'findings': findings}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-structural.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/structural.py tests/test-structural.sh
git commit -m "Add thematic concentration scoring (Herfindahl index)"
git push
```

---

### Task 3: Pacing Shape + Beat Regularity

**Files:**
- Modify: `scripts/lib/python/storyforge/structural.py`
- Modify: `tests/test-structural.sh`

- [ ] **Step 1: Write failing test**

Append to `tests/test-structural.sh`:
```bash
# ============================================================================
# score_pacing
# ============================================================================

PACE_DIR="${TMPDIR}/pace-test/reference"
mkdir -p "$PACE_DIR"

# Well-paced novel: alternating tension, climax near end
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
${PY})
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_pacing
scenes = _read_csv_as_map('${PACE_DIR}/scenes.csv')
intent = _read_csv_as_map('${PACE_DIR}/scene-intent.csv')
briefs = _read_csv_as_map('${PACE_DIR}/scene-briefs.csv')
result = score_pacing(scenes, intent, briefs)
print(f'score={result[\"score\"]:.2f}')
# Alternating tension with climax at scene 7/8 — should score reasonably well
assert result['score'] > 0.4, f'Expected > 0.4, got {result[\"score\"]}'
assert isinstance(result['findings'], list)
print('ok')
")
assert_contains "$RESULT" "ok" "score_pacing: well-paced novel scores above 0.4"
rm -rf "${TMPDIR}/pace-test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-structural.sh`
Expected: FAIL

- [ ] **Step 3: Write score_pacing**

Append to `structural.py`:
```python
# ============================================================================
# Dimension 3: Pacing Shape
# ============================================================================

# Tension values for value_shift patterns
_SHIFT_TENSION = {
    '-/--': 1.0,   # things getting much worse
    '+/-': 0.85,   # reversal from positive
    '-/+': 0.5,    # recovery
    '-/-': 0.7,    # continuing negative
    '+/+': 0.2,    # continuing positive
    '+/++': 0.15,  # things getting better
}

_OUTCOME_TENSION = {
    'no': 0.9,
    'no-and': 1.0,
    'no-but': 0.7,
    'yes-but': 0.5,
    'yes': 0.2,
}


def _scene_tension(intent, brief):
    """Compute a 0-1 tension score for a single scene."""
    vs = intent.get('value_shift', '').strip()
    outcome = brief.get('outcome', '').strip().lower()
    action_sequel = intent.get('action_sequel', '').strip().lower()

    t_shift = _SHIFT_TENSION.get(vs, 0.5)
    t_outcome = _OUTCOME_TENSION.get(outcome, 0.5)
    t_type = 0.7 if action_sequel == 'action' else 0.4

    return (t_shift * 0.5) + (t_outcome * 0.3) + (t_type * 0.2)


def _beat_regularity(tensions):
    """Compute regularity of tension oscillation (0-1).

    Empirical basis: Archer & Jockers (2016) — bestsellers show
    near-sinusoidal emotional oscillation. Regularity of the beat
    matters more than the specific shape.

    Measures how often consecutive scenes alternate direction
    (up→down or down→up).
    """
    if len(tensions) < 3:
        return 0.5  # Not enough data

    alternations = 0
    for i in range(1, len(tensions) - 1):
        prev_dir = tensions[i] - tensions[i - 1]
        next_dir = tensions[i + 1] - tensions[i]
        if prev_dir * next_dir < 0:  # Sign change = alternation
            alternations += 1

    max_alternations = len(tensions) - 2
    return alternations / max_alternations if max_alternations > 0 else 0.5


def score_pacing(scenes_map, intent_map, briefs_map):
    """Score pacing shape: act proportions, climax position, beat regularity.

    Empirical basis: Coyne/Brody (25/50/25 acts), Archer & Jockers
    (sinusoidal beat regularity), Reagan (compound arcs).
    """
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    if len(sorted_ids) < 4:
        return {'score': 0.0, 'findings': [{'message': 'Too few scenes to assess pacing'}]}

    # Compute per-scene tension
    tensions = []
    for sid in sorted_ids:
        intent = intent_map.get(sid, {})
        brief = briefs_map.get(sid, {})
        tensions.append(_scene_tension(intent, brief))

    n = len(tensions)
    findings = []

    # --- Act proportions (25/50/25 from part column) ---
    parts = {}
    word_totals = {}
    for sid in sorted_ids:
        part = scenes_map[sid].get('part', '').strip()
        words = int(scenes_map[sid].get('target_words', 0) or 0)
        if not words:
            words = int(scenes_map[sid].get('word_count', 0) or 0)
        if part:
            parts.setdefault(part, 0)
            parts[part] += 1
            word_totals.setdefault(part, 0)
            word_totals[part] += words

    total_words = sum(word_totals.values())
    act_score = 0.7  # Default if we can't compute
    if total_words > 0 and len(parts) >= 3:
        sorted_parts = sorted(parts.keys())
        first_part_share = word_totals.get(sorted_parts[0], 0) / total_words
        last_part_share = word_totals.get(sorted_parts[-1], 0) / total_words
        # Ideal: 0.25 for first and last parts
        first_dev = abs(first_part_share - 0.25)
        last_dev = abs(last_part_share - 0.25)
        act_score = max(0.0, 1.0 - (first_dev + last_dev) * 2)
        if first_dev > 0.10:
            findings.append({
                'message': f'Act 1 is {first_part_share:.0%} of word count (target: ~25%)',
                'severity': 'important',
            })
        if last_dev > 0.10:
            findings.append({
                'message': f'Final act is {last_part_share:.0%} of word count (target: ~25%)',
                'severity': 'important',
            })

    # --- Climax position ---
    max_tension_idx = tensions.index(max(tensions))
    climax_position = (max_tension_idx + 1) / n
    # Ideal: 85-95% of the way through
    climax_score = max(0.0, 1.0 - abs(climax_position - 0.88) * 4)
    if climax_position < 0.70:
        findings.append({
            'message': f'Climax at scene {max_tension_idx + 1}/{n} ({climax_position:.0%}) — too early, target 85-90%',
            'severity': 'important',
        })

    # --- Midpoint presence ---
    mid_idx = n // 2
    mid_window = tensions[max(0, mid_idx - 1):min(n, mid_idx + 2)]
    avg_tension = sum(tensions) / n
    mid_tension = max(mid_window)
    midpoint_score = min(1.0, mid_tension / avg_tension) if avg_tension > 0 else 0.5
    if mid_tension < avg_tension * 0.8:
        findings.append({
            'message': f'Weak midpoint — tension at seq ~{mid_idx + 1} is below average',
            'severity': 'minor',
        })

    # --- Beat regularity (Archer/Jockers) ---
    regularity = _beat_regularity(tensions)
    if regularity < 0.3:
        findings.append({
            'message': f'Beat regularity is {regularity:.2f} — long runs of same-direction shifts. Bestsellers average 0.5+',
            'severity': 'important',
        })

    # --- Escalation: second half should be higher tension than first ---
    first_half_mean = sum(tensions[:n // 2]) / (n // 2)
    second_half_mean = sum(tensions[n // 2:]) / (n - n // 2)
    escalation_score = min(1.0, 0.5 + (second_half_mean - first_half_mean) * 2)
    if second_half_mean < first_half_mean:
        findings.append({
            'message': f'Story deflates: first half tension {first_half_mean:.2f} > second half {second_half_mean:.2f}',
            'severity': 'important',
        })

    # Composite
    score = (act_score * 0.25 + climax_score * 0.25 + midpoint_score * 0.15 +
             regularity * 0.20 + escalation_score * 0.15)

    return {'score': round(score, 3), 'findings': findings}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-structural.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/structural.py tests/test-structural.sh
git commit -m "Add pacing shape scoring with beat regularity (Archer/Jockers)"
git push
```

---

### Task 4: Arc Completeness

**Files:**
- Modify: `scripts/lib/python/storyforge/structural.py`
- Modify: `tests/test-structural.sh`

- [ ] **Step 1: Write failing test**

Append to `tests/test-structural.sh`:
```bash
# ============================================================================
# score_arcs
# ============================================================================

ARC_DIR="${TMPDIR}/arc-test/reference"
mkdir -p "$ARC_DIR"

# Two POV characters: Alice has a compound arc, Bob is flat
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
${PY})
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_arcs
scenes = _read_csv_as_map('${ARC_DIR}/scenes.csv')
intent = _read_csv_as_map('${ARC_DIR}/scene-intent.csv')
result = score_arcs(scenes, intent)
print(f'score={result[\"score\"]:.2f}')
# Alice has varied values and compound arc; Bob is flat (truth only, same emotional arc)
# Alice should score higher
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-structural.sh`
Expected: FAIL

- [ ] **Step 3: Write score_arcs**

Append to `structural.py`:
```python
# ============================================================================
# Dimension 1: Arc Completeness
# ============================================================================

def _classify_arc_shape(shifts):
    """Classify a sequence of value_shift into one of Reagan's 6 archetypes.

    Maps +/- to valence: positive (+/+, +/++, -/+) vs negative (+/-, -/--, -/-).
    Then classifies the overall trajectory.

    Returns (shape_name, reversal_count, is_compound).
    """
    if not shifts:
        return ('unknown', 0, False)

    # Map each shift to a valence direction
    positive_shifts = {'-/+', '+/+', '+/++'}
    negative_shifts = {'+/-', '-/--', '-/-'}

    valences = []
    for s in shifts:
        s = s.strip()
        if s in positive_shifts:
            valences.append(1)
        elif s in negative_shifts:
            valences.append(-1)
        else:
            valences.append(0)

    # Count reversals (sign changes)
    reversals = 0
    for i in range(1, len(valences)):
        if valences[i] != 0 and valences[i - 1] != 0 and valences[i] != valences[i - 1]:
            reversals += 1

    # Classify shape from trajectory
    pos_count = valences.count(1)
    neg_count = valences.count(-1)

    # Simple trajectory
    if not valences:
        shape = 'unknown'
    elif reversals == 0:
        shape = 'rags-to-riches' if pos_count > neg_count else 'tragedy'
    elif reversals == 1:
        # One reversal: man-in-a-hole or icarus
        first_half = valences[:len(valences) // 2]
        first_neg = first_half.count(-1) > first_half.count(1)
        shape = 'man-in-a-hole' if first_neg else 'icarus'
    elif reversals >= 2:
        # Compound: cinderella (rise-fall-rise) or oedipus (fall-rise-fall)
        if valences[0] >= 0 and valences[-1] >= 0:
            shape = 'cinderella'
        elif valences[0] <= 0 and valences[-1] <= 0:
            shape = 'oedipus'
        else:
            shape = 'cinderella' if valences[-1] > 0 else 'oedipus'

    is_compound = reversals >= 2

    return (shape, reversals, is_compound)


def score_arcs(scenes_map, intent_map):
    """Score arc completeness for each POV character.

    Empirical basis: Reagan et al. (2016) — compound arcs with more
    reversals correlate with popularity. McKee — every scene must shift a value.

    Returns dict with 'score', 'findings', and 'character_arcs' list.
    """
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    # Group scenes by POV character
    pov_scenes = {}
    for sid in sorted_ids:
        pov = scenes_map[sid].get('pov', '').strip()
        if pov:
            pov_scenes.setdefault(pov, []).append(sid)

    if not pov_scenes:
        return {'score': 0.0, 'findings': [{'message': 'No POV data'}], 'character_arcs': []}

    character_arcs = []
    findings = []
    total_weighted_score = 0.0
    total_weight = 0.0

    for character, scene_ids in pov_scenes.items():
        intents = [intent_map.get(sid, {}) for sid in scene_ids]

        # Value variety
        values = set()
        shifts = []
        emotional_arcs = []
        for intent in intents:
            v = intent.get('value_at_stake', '').strip()
            if v:
                values.add(v)
            vs = intent.get('value_shift', '').strip()
            if vs:
                shifts.append(vs)
            ea = intent.get('emotional_arc', '').strip()
            if ea:
                emotional_arcs.append(ea)

        value_count = len(values)
        scene_count = len(scene_ids)

        # Arc shape
        shape, reversals, is_compound = _classify_arc_shape(shifts)

        # Value variety score (target: 3-6 distinct values per character)
        if scene_count <= 3:
            variety_score = 0.7  # Too few scenes to judge
        elif value_count <= 1:
            variety_score = 0.1
        elif value_count <= 2:
            variety_score = 0.4
        elif value_count <= 6:
            variety_score = 0.9
        elif value_count <= 10:
            variety_score = 0.7
        else:
            variety_score = 0.5

        # Reversal score (more reversals = better, up to a point)
        # Reagan: compound arcs outperform simple ones
        if scene_count < 4:
            reversal_score = 0.5
        elif reversals == 0:
            reversal_score = 0.2
        elif reversals == 1:
            reversal_score = 0.5
        elif reversals == 2:
            reversal_score = 0.8
        elif reversals <= 4:
            reversal_score = 0.9
        else:
            reversal_score = max(0.5, 0.9 - (reversals - 4) * 0.1)

        # Transformation signal: first vs last emotional_arc
        transform_score = 0.5
        if len(emotional_arcs) >= 2:
            first_words = set(emotional_arcs[0].lower().split()[:4])
            last_words = set(emotional_arcs[-1].lower().split()[:4])
            overlap = len(first_words & last_words)
            if overlap <= 1:
                transform_score = 0.9  # Very different = transformation
            elif overlap >= 3:
                transform_score = 0.2  # Very similar = stasis

        # Composite per character
        arc_score = (variety_score * 0.3 + reversal_score * 0.4 + transform_score * 0.3)

        character_arcs.append({
            'character': character,
            'scene_count': scene_count,
            'value_count': value_count,
            'shape': shape,
            'reversals': reversals,
            'is_compound': is_compound,
            'arc_score': round(arc_score, 3),
        })

        # Findings
        if value_count <= 1 and scene_count > 5:
            findings.append({
                'message': f"{character}'s arc uses only '{list(values)[0] if values else '?'}' across {scene_count} scenes — thematic monotony",
                'scene_id': '',
                'severity': 'important',
            })
        if reversals == 0 and scene_count > 5:
            findings.append({
                'message': f"{character}'s arc is a simple {shape} with no reversals — consider adding a turn",
                'severity': 'minor',
            })
        if is_compound:
            findings.append({
                'message': f"{character}'s arc is a compound {shape} with {reversals} reversals — empirically strong",
                'severity': 'info',
            })

        # Weight by scene count
        total_weighted_score += arc_score * scene_count
        total_weight += scene_count

    overall_score = total_weighted_score / total_weight if total_weight > 0 else 0.0

    return {
        'score': round(overall_score, 3),
        'findings': findings,
        'character_arcs': character_arcs,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-structural.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/structural.py tests/test-structural.sh
git commit -m "Add arc completeness scoring with Reagan shape classification"
git push
```

---

### Task 5: Character Presence + Scene Function Variety + MICE Health + Knowledge Chain

The remaining four dimensions. Grouped because each is simpler than arcs/pacing and follows the same pattern.

**Files:**
- Modify: `scripts/lib/python/storyforge/structural.py`
- Modify: `tests/test-structural.sh`

- [ ] **Step 1: Write failing tests for all four dimensions**

Append to `tests/test-structural.sh`:
```bash
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
${PY})
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_character_presence
scenes = _read_csv_as_map('${CHAR_DIR}/scenes.csv')
intent = _read_csv_as_map('${CHAR_DIR}/scene-intent.csv')
result = score_character_presence(scenes, intent, '${CHAR_DIR}')
assert 0 <= result['score'] <= 1
# villain is mentioned in 3 scenes, on_stage in 2 — ratio check should work
print('ok')
")
assert_contains "$RESULT" "ok" "score_character_presence: returns valid score"
rm -rf "${TMPDIR}/char-test"

# ============================================================================
# score_function_variety
# ============================================================================

RESULT=$(python3 -c "
${PY})
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
${PY})
from storyforge.elaborate import _read_csv_as_map
from storyforge.structural import score_mice_health
scenes = _read_csv_as_map('${FIXTURE_DIR}/reference/scenes.csv')
intent = _read_csv_as_map('${FIXTURE_DIR}/reference/scene-intent.csv')
result = score_mice_health(scenes, intent)
assert 0 <= result['score'] <= 1
# Fixture has 3 threads, all properly opened and closed
print(f'score={result[\"score\"]:.2f}')
print('ok')
")
assert_contains "$RESULT" "ok" "score_mice_health: returns valid score on fixtures"

# ============================================================================
# score_knowledge_chain
# ============================================================================

RESULT=$(python3 -c "
${PY})
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-structural.sh`
Expected: FAIL

- [ ] **Step 3: Write all four scoring functions**

Append to `structural.py`:
```python
# ============================================================================
# Dimension 4: Character Presence
# ============================================================================

def score_character_presence(scenes_map, intent_map, ref_dir):
    """Score whether characters earn their screentime.

    Checks POV balance, antagonist visibility, presence gaps,
    and mention-vs-onstage ratio.
    """
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))
    n = len(sorted_ids)

    if n == 0:
        return {'score': 0.0, 'findings': [{'message': 'No scenes'}]}

    # Load character roles if registry exists
    char_roles = {}
    chars_path = os.path.join(ref_dir, 'characters.csv')
    if os.path.isfile(chars_path):
        char_rows = _read_csv(chars_path)
        for row in char_rows:
            cid = row.get('id', '').strip()
            role = row.get('role', '').strip()
            if cid:
                char_roles[cid] = role

    # Count POV scenes, on_stage, and mentions per character
    pov_counts = {}
    onstage_counts = {}
    mention_counts = {}
    last_seen = {}  # character -> last seq index where on_stage

    for idx, sid in enumerate(sorted_ids):
        pov = scenes_map[sid].get('pov', '').strip()
        if pov:
            pov_counts[pov] = pov_counts.get(pov, 0) + 1

        intent = intent_map.get(sid, {})
        for c in intent.get('on_stage', '').split(';'):
            c = c.strip()
            if c:
                onstage_counts[c] = onstage_counts.get(c, 0) + 1
                last_seen[c] = idx
        for c in intent.get('characters', '').split(';'):
            c = c.strip()
            if c:
                mention_counts[c] = mention_counts.get(c, 0) + 1

    findings = []
    subscores = []

    # POV balance: each POV character should have >= 15% of scenes
    pov_characters = set(pov_counts.keys())
    for char, count in pov_counts.items():
        share = count / n
        if share < 0.10 and count > 1:
            findings.append({
                'message': f'{char} narrates only {count}/{n} scenes ({share:.0%}) — limited perspective',
                'severity': 'minor',
            })
    pov_balance = 1.0 - (max(pov_counts.values()) / n - 1.0 / len(pov_counts)) if len(pov_counts) > 1 else 0.5
    subscores.append(min(1.0, max(0.0, pov_balance + 0.3)))

    # Antagonist visibility
    antagonists = [c for c, r in char_roles.items() if r == 'antagonist']
    antag_score = 0.7  # Default if no registry
    for antag in antagonists:
        onstage = onstage_counts.get(antag, 0)
        share = onstage / n
        if share < 0.08:
            findings.append({
                'message': f'{antag} (antagonist) on-stage in only {onstage}/{n} scenes ({share:.0%}) — feels distant',
                'severity': 'important',
            })
            antag_score = min(antag_score, share / 0.10)
    subscores.append(antag_score)

    # Presence gaps: longest absence for important characters
    gap_score = 1.0
    all_chars = set(list(pov_counts.keys()) + antagonists)
    for char in all_chars:
        appearances = []
        for idx, sid in enumerate(sorted_ids):
            intent = intent_map.get(sid, {})
            onstage = intent.get('on_stage', '')
            if char in onstage.split(';') or scenes_map[sid].get('pov', '').strip() == char:
                appearances.append(idx)
        if len(appearances) >= 2:
            max_gap = max(appearances[i + 1] - appearances[i] for i in range(len(appearances) - 1))
            gap_ratio = max_gap / n
            if gap_ratio > 0.20:
                findings.append({
                    'message': f'{char} absent for {max_gap} consecutive scenes ({gap_ratio:.0%} of novel)',
                    'severity': 'important' if gap_ratio > 0.25 else 'minor',
                })
                gap_score = min(gap_score, max(0.0, 1.0 - (gap_ratio - 0.15) * 4))
    subscores.append(gap_score)

    # Mention-to-onstage ratio
    ratio_score = 1.0
    for char in all_chars:
        mentioned = mention_counts.get(char, 0)
        onstage = onstage_counts.get(char, 0)
        if mentioned > 5 and onstage > 0 and onstage / mentioned < 0.3:
            findings.append({
                'message': f'{char} mentioned in {mentioned} scenes but on-stage in only {onstage} — told not shown',
                'severity': 'minor',
            })
            ratio_score = min(ratio_score, 0.6)
    subscores.append(ratio_score)

    score = sum(subscores) / len(subscores)
    return {'score': round(score, 3), 'findings': findings}


# ============================================================================
# Dimension 5: MICE Thread Health
# ============================================================================

def score_mice_health(scenes_map, intent_map):
    """Score MICE thread effectiveness beyond nesting validity.

    Checks lifespan, dormancy, resolution positioning, close ratio,
    and type balance.
    """
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))
    n = len(sorted_ids)
    id_to_idx = {sid: i for i, sid in enumerate(sorted_ids)}

    if n == 0:
        return {'score': 0.0, 'findings': [{'message': 'No scenes'}]}

    # Parse all thread events
    thread_open = {}   # name -> seq index
    thread_close = {}  # name -> seq index
    thread_type = {}   # name -> type
    thread_mentions = {}  # name -> list of seq indices

    for idx, sid in enumerate(sorted_ids):
        intent = intent_map.get(sid, {})
        mice = intent.get('mice_threads', '').strip()
        if not mice:
            continue
        for entry in mice.split(';'):
            entry = entry.strip()
            if not entry:
                continue
            if entry.startswith('+'):
                name = entry[1:]
                thread_open[name] = idx
                ttype = name.split(':')[0] if ':' in name else ''
                thread_type[name] = ttype
                thread_mentions.setdefault(name, []).append(idx)
            elif entry.startswith('-'):
                name = entry[1:]
                thread_close[name] = idx
                if name not in thread_type:
                    ttype = name.split(':')[0] if ':' in name else ''
                    thread_type[name] = ttype
                thread_mentions.setdefault(name, []).append(idx)

    all_threads = set(list(thread_open.keys()) + list(thread_close.keys()))
    if not all_threads:
        return {'score': 0.5, 'findings': [{'message': 'No MICE threads found'}]}

    findings = []

    # Close ratio
    opened = len(thread_open)
    closed = len([t for t in thread_open if t in thread_close])
    close_ratio = closed / opened if opened > 0 else 0.0
    if close_ratio < 0.5:
        findings.append({
            'message': f'Only {closed}/{opened} threads close ({close_ratio:.0%}) — too many loose ends',
            'severity': 'important',
        })

    # Dormancy: longest gap between mentions for each thread
    dormant_count = 0
    for name, mentions in thread_mentions.items():
        if len(mentions) >= 2:
            max_gap = max(mentions[i + 1] - mentions[i] for i in range(len(mentions) - 1))
            if max_gap > 10:
                dormant_count += 1
                if max_gap > 15:
                    short_name = name.split(':')[1] if ':' in name else name
                    findings.append({
                        'message': f"Thread '{short_name}' dormant for {max_gap} scenes — reader may forget",
                        'severity': 'minor',
                    })

    dormancy_score = max(0.0, 1.0 - dormant_count / max(len(all_threads), 1) * 2)

    # Type balance
    types = {}
    for t in thread_type.values():
        if t:
            types[t] = types.get(t, 0) + 1
    type_count = len(types)
    type_balance = min(1.0, type_count / 3)  # 3+ types is healthy
    if type_count <= 1 and len(all_threads) > 5:
        dominant = max(types, key=types.get) if types else 'unknown'
        findings.append({
            'message': f'Only {dominant} threads — needs more MICE type variety',
            'severity': 'important',
        })

    # Resolution positioning: major threads should close in final 30%
    late_closes = 0
    for name in thread_close:
        if thread_close[name] >= n * 0.7:
            late_closes += 1
    resolution_score = late_closes / max(closed, 1) if closed > 0 else 0.5

    score = (close_ratio * 0.35 + dormancy_score * 0.25 +
             type_balance * 0.20 + resolution_score * 0.20)

    return {'score': round(score, 3), 'findings': findings}


# ============================================================================
# Dimension 6: Knowledge Chain Integrity
# ============================================================================

def score_knowledge_chain(scenes_map, briefs_map):
    """Score knowledge flow: coverage, utilization, dramatic irony potential."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))
    n = len(sorted_ids)

    if n == 0:
        return {'score': 0.0, 'findings': [{'message': 'No scenes'}]}

    # Collect facts
    scenes_with_kin = 0
    scenes_with_kout = 0
    all_facts_in = set()
    all_facts_out = set()
    fact_usage = {}  # fact -> count of scenes it appears in

    for sid in sorted_ids:
        brief = briefs_map.get(sid, {})
        k_in = brief.get('knowledge_in', '').strip()
        k_out = brief.get('knowledge_out', '').strip()

        if k_in:
            scenes_with_kin += 1
            for f in k_in.split(';'):
                f = f.strip()
                if f:
                    all_facts_in.add(f)
                    fact_usage[f] = fact_usage.get(f, 0) + 1
        if k_out:
            scenes_with_kout += 1
            for f in k_out.split(';'):
                f = f.strip()
                if f:
                    all_facts_out.add(f)
                    fact_usage[f] = fact_usage.get(f, 0) + 1

    findings = []

    # Coverage
    coverage_in = scenes_with_kin / n if n > 0 else 0
    coverage_out = scenes_with_kout / n if n > 0 else 0
    coverage = (coverage_in + coverage_out) / 2

    if coverage_out < 0.5:
        findings.append({
            'message': f'Only {scenes_with_kout}/{n} scenes have knowledge_out ({coverage_out:.0%}) — many scenes teach nothing new',
            'severity': 'important',
        })

    # Fact utilization: facts appearing in 2+ scenes
    multi_use = sum(1 for c in fact_usage.values() if c >= 2)
    total_facts = len(fact_usage)
    utilization = multi_use / total_facts if total_facts > 0 else 0
    if utilization < 0.3 and total_facts > 10:
        findings.append({
            'message': f'Only {multi_use}/{total_facts} facts appear in 2+ scenes — most facts are mentioned once and forgotten',
            'severity': 'minor',
        })

    # Backstory check: how many facts in scene 1's knowledge_in?
    if sorted_ids:
        first_brief = briefs_map.get(sorted_ids[0], {})
        first_kin = first_brief.get('knowledge_in', '').strip()
        if first_kin:
            backstory_count = len([f for f in first_kin.split(';') if f.strip()])
            if backstory_count > 5:
                findings.append({
                    'message': f'Scene 1 requires {backstory_count} backstory facts — heavy assumed context',
                    'severity': 'minor',
                })

    score = (coverage * 0.4 + utilization * 0.35 +
             min(1.0, total_facts / max(n * 0.5, 1)) * 0.25)

    return {'score': round(min(1.0, score), 3), 'findings': findings}


# ============================================================================
# Dimension 7: Scene Function Variety
# ============================================================================

def score_function_variety(intent_map, briefs_map):
    """Score whether scenes do varied things: type mix, outcome variety, turning point variety."""
    if not intent_map:
        return {'score': 0.0, 'findings': [{'message': 'No intent data'}]}

    findings = []
    n = len(intent_map)

    # Action/sequel distribution
    action_count = sum(1 for r in intent_map.values()
                       if r.get('action_sequel', '').strip().lower() == 'action')
    sequel_count = sum(1 for r in intent_map.values()
                       if r.get('action_sequel', '').strip().lower() == 'sequel')
    total_typed = action_count + sequel_count
    if total_typed > 0:
        action_ratio = action_count / total_typed
        # Ideal: 40-60% action
        if action_ratio < 0.25 or action_ratio > 0.75:
            dominant = 'action' if action_ratio > 0.5 else 'sequel'
            findings.append({
                'message': f'{action_count} action / {sequel_count} sequel — heavily skewed toward {dominant}',
                'severity': 'minor',
            })
        type_balance = 1.0 - abs(action_ratio - 0.5) * 2
    else:
        type_balance = 0.5

    # Outcome variety (entropy)
    outcomes = {}
    for row in briefs_map.values():
        o = row.get('outcome', '').strip().lower()
        if o:
            outcomes[o] = outcomes.get(o, 0) + 1
    total_outcomes = sum(outcomes.values())
    if total_outcomes > 0 and len(outcomes) > 1:
        # Shannon entropy normalized to 0-1
        entropy = -sum((c / total_outcomes) * math.log2(c / total_outcomes)
                       for c in outcomes.values())
        max_entropy = math.log2(len(outcomes))
        outcome_variety = entropy / max_entropy if max_entropy > 0 else 0
        # Check for dominant outcome
        max_outcome = max(outcomes, key=outcomes.get)
        max_share = outcomes[max_outcome] / total_outcomes
        if max_share > 0.60:
            findings.append({
                'message': f'{outcomes[max_outcome]}/{total_outcomes} outcomes are {max_outcome} ({max_share:.0%}) — predictable pattern',
                'severity': 'important',
            })
    else:
        outcome_variety = 0.5

    # Turning point variety
    tp_counts = {}
    for row in intent_map.values():
        tp = row.get('turning_point', '').strip().lower()
        if tp:
            tp_counts[tp] = tp_counts.get(tp, 0) + 1
    total_tp = sum(tp_counts.values())
    if total_tp > 0 and len(tp_counts) > 1:
        max_tp = max(tp_counts, key=tp_counts.get)
        tp_share = tp_counts[max_tp] / total_tp
        tp_variety = 1.0 - tp_share
        if tp_share > 0.75:
            findings.append({
                'message': f'{tp_counts[max_tp]}/{total_tp} turning points are {max_tp} ({tp_share:.0%}) — needs more variety',
                'severity': 'minor',
            })
    else:
        tp_variety = 0.5

    score = (type_balance * 0.35 + outcome_variety * 0.35 + tp_variety * 0.30)

    return {'score': round(score, 3), 'findings': findings}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-structural.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/structural.py tests/test-structural.sh
git commit -m "Add character presence, MICE health, knowledge chain, and function variety scoring"
git push
```

---

### Task 6: Orchestrator + Formatters

Wire all 8 dimensions together with a top-level `structural_score()` function and output formatters.

**Files:**
- Modify: `scripts/lib/python/storyforge/structural.py`
- Modify: `tests/test-structural.sh`

- [ ] **Step 1: Write failing test**

Append to `tests/test-structural.sh`:
```bash
# ============================================================================
# structural_score (full orchestrator)
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.structural import structural_score

report = structural_score('${FIXTURE_DIR}/reference')
assert 'overall_score' in report, 'Missing overall_score'
assert 'dimensions' in report, 'Missing dimensions'
assert len(report['dimensions']) == 8, f'Expected 8 dimensions, got {len(report[\"dimensions\"])}'

# Check all dimension names are present
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
${PY})
from storyforge.structural import structural_score, format_scorecard

report = structural_score('${FIXTURE_DIR}/reference')
card = format_scorecard(report)
assert 'Structural Score' in card
assert 'Arc Completeness' in card
assert 'Pacing Shape' in card
print('ok')
")
assert_contains "$RESULT" "ok" "format_scorecard: produces readable output"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-structural.sh`
Expected: FAIL

- [ ] **Step 3: Write structural_score and formatters**

Append to `structural.py`:
```python
# ============================================================================
# Orchestrator
# ============================================================================

_DEFAULT_WEIGHTS = {
    'arc_completeness': 1.0,
    'thematic_concentration': 0.8,
    'pacing_shape': 1.0,
    'character_presence': 0.7,
    'mice_health': 0.6,
    'knowledge_chain': 0.5,
    'function_variety': 0.7,
    'completeness': 0.3,
}

_DIMENSION_LABELS = {
    'arc_completeness': 'Arc Completeness',
    'thematic_concentration': 'Thematic Concentration',
    'pacing_shape': 'Pacing Shape',
    'character_presence': 'Character Presence',
    'mice_health': 'MICE Thread Health',
    'knowledge_chain': 'Knowledge Chain',
    'function_variety': 'Scene Function Variety',
    'completeness': 'Structural Completeness',
}

_DIMENSION_TARGETS = {
    'arc_completeness': 0.80,
    'thematic_concentration': 0.60,
    'pacing_shape': 0.75,
    'character_presence': 0.70,
    'mice_health': 0.60,
    'knowledge_chain': 0.60,
    'function_variety': 0.65,
    'completeness': 0.80,
}


def structural_score(ref_dir, weights=None):
    """Run all 8 structural scoring dimensions.

    Args:
        ref_dir: Path to the reference/ directory.
        weights: Optional dict of dimension_name -> weight. Defaults to _DEFAULT_WEIGHTS.

    Returns dict with 'overall_score', 'dimensions' list, and 'top_findings'.
    """
    if weights is None:
        weights = _DEFAULT_WEIGHTS

    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    results = {}
    results['arc_completeness'] = score_arcs(scenes_map, intent_map)
    results['thematic_concentration'] = score_thematic_concentration(intent_map)
    results['pacing_shape'] = score_pacing(scenes_map, intent_map, briefs_map)
    results['character_presence'] = score_character_presence(scenes_map, intent_map, ref_dir)
    results['mice_health'] = score_mice_health(scenes_map, intent_map)
    results['knowledge_chain'] = score_knowledge_chain(scenes_map, briefs_map)
    results['function_variety'] = score_function_variety(intent_map, briefs_map)
    results['completeness'] = score_completeness(scenes_map, intent_map, briefs_map)

    # Build dimensions list
    dimensions = []
    weighted_sum = 0.0
    weight_sum = 0.0

    for name in _DEFAULT_WEIGHTS:
        result = results[name]
        w = weights.get(name, _DEFAULT_WEIGHTS[name])
        dimensions.append({
            'name': name,
            'label': _DIMENSION_LABELS[name],
            'score': result['score'],
            'weight': w,
            'target': _DIMENSION_TARGETS[name],
            'findings': result.get('findings', []),
        })
        weighted_sum += result['score'] * w
        weight_sum += w

    overall_score = weighted_sum / weight_sum if weight_sum > 0 else 0.0

    # Top findings: all important findings sorted by dimension weight
    top_findings = []
    for dim in dimensions:
        for finding in dim['findings']:
            if finding.get('severity') in ('important',):
                top_findings.append({
                    'dimension': dim['label'],
                    'dimension_score': dim['score'],
                    'message': finding['message'],
                })

    return {
        'overall_score': round(overall_score, 3),
        'dimensions': dimensions,
        'top_findings': top_findings,
    }


# ============================================================================
# Formatters
# ============================================================================

def format_scorecard(report):
    """Format a structural score report as a terminal-printable score card."""
    lines = []
    lines.append(f'Structural Score: {report["overall_score"]:.2f} / 1.00')
    lines.append('')

    for dim in report['dimensions']:
        bar_full = int(dim['score'] * 10)
        bar_empty = 10 - bar_full
        bar = '\u2588' * bar_full + '\u2591' * bar_empty
        target = f'(target: {dim["target"]:.2f}+)'
        label = dim['label'].ljust(24)
        lines.append(f'  {label}{dim["score"]:.2f}  {bar}  {target}')

    return '\n'.join(lines)


def format_diagnosis(report, coaching_level='full'):
    """Format diagnostic findings adapted to coaching level.

    coaching_level: 'full', 'coach', or 'strict'
    """
    lines = []

    if not report['top_findings']:
        lines.append('No significant structural issues found.')
        return '\n'.join(lines)

    if coaching_level == 'strict':
        lines.append('## Data')
        lines.append('')
        for dim in report['dimensions']:
            if dim['score'] < dim['target']:
                finding_msgs = [f['message'] for f in dim['findings']
                                if f.get('severity') in ('important',)]
                detail = '; '.join(finding_msgs[:2]) if finding_msgs else ''
                lines.append(f'{dim["label"]}: {dim["score"]:.2f} ({detail})')
    elif coaching_level == 'coach':
        lines.append('## Questions to Consider')
        lines.append('')
        for i, finding in enumerate(report['top_findings'][:5], 1):
            lines.append(f'{i}. **{finding["dimension"]}: {finding["dimension_score"]:.2f}**')
            lines.append(f'   - {finding["message"]}')
            lines.append('')
    else:
        lines.append('## Top Findings')
        lines.append('')
        for i, finding in enumerate(report['top_findings'][:5], 1):
            lines.append(f'{i}. **{finding["dimension"]}: {finding["dimension_score"]:.2f}** — {finding["message"]}')

    return '\n'.join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-structural.sh`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/structural.py tests/test-structural.sh
git commit -m "Add structural scoring orchestrator with scorecard and diagnosis formatters"
git push
```

---

### Task 7: Integrate into storyforge-validate

**Files:**
- Modify: `scripts/storyforge-validate`

- [ ] **Step 1: Add --structural flag and output**

In `scripts/storyforge-validate`, add `--structural` to the arg parser and the validation call.

Add to the args section (around line 20):
```bash
STRUCTURAL=false
```

Add to the case statement:
```bash
        --structural) STRUCTURAL=true ;;
```

Update the help text:
```bash
            echo "Usage: storyforge validate [--no-schema] [--structural] [--json] [--quiet]"
            echo "  --no-schema    Skip schema validation"
            echo "  --structural   Include structural scoring (story quality from CSVs)"
```

In the Python validation block (around line 44), add the structural scoring import and call:

After the existing `knowledge = ...` block, add:
```python
structural_scores = None
if '${STRUCTURAL}' == 'true':
    from storyforge.structural import structural_score
    structural_scores = structural_score(ref_dir)
```

Update the JSON output to include structural_scores:
```python
print(json.dumps({'structural': structural, 'schema': schema, 'knowledge': knowledge, 'scores': structural_scores}))
```

Add a display section in the human-readable output block (after the knowledge granularity section):
```python
scores = combined.get('scores')
if scores is not None:
    print()
    print('--- Structural scoring ---')
    print(f'  Overall: {scores["overall_score"]:.2f} / 1.00')
    print()
    for dim in scores['dimensions']:
        bar_full = int(dim['score'] * 10)
        bar = chr(9608) * bar_full + chr(9617) * (10 - bar_full)
        status = 'OK' if dim['score'] >= dim['target'] else 'LOW'
        print(f'  {dim["label"]:24s} {dim["score"]:.2f}  {bar}  {"" if status == "OK" else "(below target)"}')
    if scores['top_findings']:
        print()
        print('  Top findings:')
        for f in scores['top_findings'][:5]:
            print(f'    {f["dimension"]}: {f["message"]}')
```

- [ ] **Step 2: Run the full test suite**

Run: `./tests/run-tests.sh`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add scripts/storyforge-validate
git commit -m "Add --structural flag to validate for story-quality scoring"
git push
```

---

### Task 8: Version Bump + CLAUDE.md

**Files:**
- Modify: `.claude-plugin/plugin.json`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Bump version to 0.58.0**

In `.claude-plugin/plugin.json`, change version to `"0.58.0"`.

- [ ] **Step 2: Update CLAUDE.md**

Add to the Python modules table:
```
| `structural.py` | Structural scoring engine — story quality from CSV data (8 dimensions, deterministic) |
```

- [ ] **Step 3: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/plugin.json CLAUDE.md
git commit -m "Bump version to 0.58.0 — add structural scoring engine"
git push
```
