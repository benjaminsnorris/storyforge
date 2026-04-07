# Upstream Naturalness Fix Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the loop between scoring and revision so naturalness problems route to brief rewrites when the root cause is upstream, not to endless prose polish.

**Architecture:** New `history.py` module tracks scores across cycles. Extended `detect_brief_issues()` catches conflict-free scenes. `generate_diagnosis()` adds `root_cause` attribution. `--polish --loop` reads root causes and inserts upstream fix passes before craft polish.

**Tech Stack:** Python, pipe-delimited CSV, pytest, existing Storyforge modules.

**Spec:** `docs/superpowers/specs/2026-04-07-upstream-naturalness-fix-pipeline-design.md`

**Branch:** `storyforge/upstream-naturalness-pipeline`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `scripts/lib/python/storyforge/history.py` | Create | Score history tracking, stall/regression detection |
| `tests/test_history.py` | Create | Tests for history module |
| `scripts/lib/python/storyforge/hone.py` | Modify | Add `detect_conflict_free()`, integrate into `detect_brief_issues()` |
| `tests/test_hone_conflict.py` | Create | Tests for conflict-free detection |
| `scripts/lib/python/storyforge/scoring.py` | Modify | Add `root_cause` column to `generate_diagnosis()` |
| `tests/test_scoring_rootcause.py` | Create | Tests for root cause attribution |
| `scripts/lib/python/storyforge/cmd_score.py` | Modify | Call `append_cycle()` after scoring |
| `scripts/lib/python/storyforge/cmd_hone.py` | Modify | Add score trends section to `_run_diagnose()` |
| `scripts/lib/python/storyforge/cmd_revise.py` | Modify | Upstream pass in `_run_polish_loop()` and naturalness |
| `CLAUDE.md` | Modify | Document new module, file, issue type |
| `skills/hone/SKILL.md` | Modify | Update diagnose flow |
| `skills/revise/SKILL.md` | Modify | Document upstream routing |
| `skills/forge/SKILL.md` | Modify | Update recommendation routing |

---

### Task 1: Score History Module — Core Functions

**Files:**
- Create: `scripts/lib/python/storyforge/history.py`
- Create: `tests/test_history.py`
- Reference: `scripts/lib/python/storyforge/elaborate.py:47-64` (CSV helpers)
- Reference: `tests/conftest.py:23-67` (fixtures)

- [ ] **Step 1: Write test for `append_cycle`**

Create `tests/test_history.py`:

```python
"""Tests for score history tracking."""

import csv
import os

from storyforge.history import append_cycle, HISTORY_HEADER, DELIMITER


def test_append_cycle_creates_file(tmp_path):
    """append_cycle creates score-history.csv if it doesn't exist."""
    scores_dir = tmp_path / 'scores'
    scores_dir.mkdir()

    # Write a minimal scene-scores.csv
    with open(scores_dir / 'scene-scores.csv', 'w') as f:
        f.write('id|prose_naturalness|voice_consistency\n')
        f.write('scene-a|3|4\n')
        f.write('scene-b|5|2\n')

    count = append_cycle(str(scores_dir), 1, str(tmp_path))

    history_file = tmp_path / 'working' / 'scores' / 'score-history.csv'
    assert history_file.exists()
    assert count == 4  # 2 scenes × 2 principles

    with open(history_file) as f:
        reader = csv.DictReader(f, delimiter='|')
        rows = list(reader)
    assert len(rows) == 4
    assert rows[0] == {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '3'}


def test_append_cycle_appends_to_existing(tmp_path):
    """append_cycle appends to existing score-history.csv."""
    working = tmp_path / 'working' / 'scores'
    working.mkdir(parents=True)

    # Existing history
    with open(working / 'score-history.csv', 'w') as f:
        f.write('cycle|scene_id|principle|score\n')
        f.write('1|scene-a|prose_naturalness|3\n')

    scores_dir = tmp_path / 'scores'
    scores_dir.mkdir()
    with open(scores_dir / 'scene-scores.csv', 'w') as f:
        f.write('id|prose_naturalness\n')
        f.write('scene-a|4\n')

    append_cycle(str(scores_dir), 2, str(tmp_path))

    with open(working / 'score-history.csv') as f:
        reader = csv.DictReader(f, delimiter='|')
        rows = list(reader)
    assert len(rows) == 2
    assert rows[1]['cycle'] == '2'
    assert rows[1]['score'] == '4'


def test_append_cycle_skips_non_principle_columns(tmp_path):
    """append_cycle skips id and rationale columns."""
    scores_dir = tmp_path / 'scores'
    scores_dir.mkdir()

    with open(scores_dir / 'scene-scores.csv', 'w') as f:
        f.write('id|prose_naturalness|prose_naturalness_rationale\n')
        f.write('scene-a|3|some rationale text\n')

    count = append_cycle(str(scores_dir), 1, str(tmp_path))
    assert count == 1  # Only prose_naturalness, not rationale
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_history.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'storyforge.history'`

- [ ] **Step 3: Implement `append_cycle`**

Create `scripts/lib/python/storyforge/history.py`:

```python
"""Score history tracking — cross-cycle score comparison.

Maintains working/scores/score-history.csv with per-scene, per-principle
scores across scoring cycles. Enables stall detection and regression
analysis.
"""

import csv
import os

DELIMITER = '|'
HISTORY_HEADER = ['cycle', 'scene_id', 'principle', 'score']
HISTORY_FILENAME = 'score-history.csv'

# Columns to skip when extracting principle scores from scene-scores.csv
_SKIP_SUFFIXES = ('_rationale',)
_SKIP_COLUMNS = {'id'}


def _history_path(project_dir: str) -> str:
    return os.path.join(project_dir, 'working', 'scores', HISTORY_FILENAME)


def _is_principle_column(col: str) -> bool:
    """Return True if the column holds a numeric score, not metadata."""
    if col in _SKIP_COLUMNS:
        return False
    return not any(col.endswith(s) for s in _SKIP_SUFFIXES)


def append_cycle(scores_dir: str, cycle: int, project_dir: str) -> int:
    """Read scene-scores.csv and append rows to score-history.csv.

    Args:
        scores_dir: Directory containing scene-scores.csv.
        cycle: Cycle number.
        project_dir: Project root (history file lives in working/scores/).

    Returns:
        Number of rows appended.
    """
    scores_file = os.path.join(scores_dir, 'scene-scores.csv')
    if not os.path.isfile(scores_file):
        return 0

    with open(scores_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=DELIMITER)
        score_rows = list(reader)

    if not score_rows:
        return 0

    # Identify principle columns (everything except id and *_rationale)
    all_cols = list(score_rows[0].keys())
    principles = [c for c in all_cols if _is_principle_column(c)]

    # Build history rows
    new_rows = []
    for row in score_rows:
        scene_id = row.get('id', '')
        if not scene_id:
            continue
        for principle in principles:
            score = row.get(principle, '')
            if score:
                new_rows.append({
                    'cycle': str(cycle),
                    'scene_id': scene_id,
                    'principle': principle,
                    'score': score,
                })

    if not new_rows:
        return 0

    # Write (append or create)
    history = _history_path(project_dir)
    os.makedirs(os.path.dirname(history), exist_ok=True)
    file_exists = os.path.isfile(history)

    with open(history, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_HEADER, delimiter=DELIMITER)
        if not file_exists:
            writer.writeheader()
        writer.writerows(new_rows)

    return len(new_rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_history.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/history.py tests/test_history.py
git commit -m "Add history.py with append_cycle for cross-cycle score tracking"
git push
```

---

### Task 2: Score History Module — Query and Detection Functions

**Files:**
- Modify: `scripts/lib/python/storyforge/history.py`
- Modify: `tests/test_history.py`

- [ ] **Step 1: Write tests for `get_scene_history`, `detect_stalls`, `detect_regressions`**

Append to `tests/test_history.py`:

```python
from storyforge.history import get_scene_history, detect_stalls, detect_regressions


def _write_history(path, rows):
    """Helper: write a score-history.csv from a list of (cycle, scene_id, principle, score)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('cycle|scene_id|principle|score\n')
        for cycle, sid, principle, score in rows:
            f.write(f'{cycle}|{sid}|{principle}|{score}\n')


def test_get_scene_history(tmp_path):
    history = tmp_path / 'working' / 'scores' / 'score-history.csv'
    _write_history(str(history), [
        (1, 'scene-a', 'prose_naturalness', 3),
        (2, 'scene-a', 'prose_naturalness', 3),
        (3, 'scene-a', 'prose_naturalness', 4),
        (1, 'scene-b', 'prose_naturalness', 5),
    ])

    result = get_scene_history(str(tmp_path), 'scene-a', 'prose_naturalness')
    assert result == [(1, 3.0), (2, 3.0), (3, 4.0)]


def test_get_scene_history_missing_file(tmp_path):
    result = get_scene_history(str(tmp_path), 'scene-a', 'prose_naturalness')
    assert result == []


def test_detect_stalls(tmp_path):
    history = tmp_path / 'working' / 'scores' / 'score-history.csv'
    _write_history(str(history), [
        (1, 'scene-a', 'prose_naturalness', 2),
        (2, 'scene-a', 'prose_naturalness', 2),
        (3, 'scene-a', 'prose_naturalness', 2),
        (1, 'scene-b', 'prose_naturalness', 3),
        (2, 'scene-b', 'prose_naturalness', 4),  # scene-b improved
        (1, 'scene-c', 'prose_naturalness', 3),
        (2, 'scene-c', 'prose_naturalness', 3),  # scene-c stalled at exactly max_score
    ])

    stalls = detect_stalls(str(tmp_path), 'prose_naturalness', min_cycles=2, max_score=3.0)
    stalled_ids = [s['scene_id'] for s in stalls]
    assert 'scene-a' in stalled_ids
    assert 'scene-c' in stalled_ids
    assert 'scene-b' not in stalled_ids

    scene_a = next(s for s in stalls if s['scene_id'] == 'scene-a')
    assert scene_a['cycles_stalled'] == 3


def test_detect_stalls_no_history(tmp_path):
    stalls = detect_stalls(str(tmp_path), 'prose_naturalness')
    assert stalls == []


def test_detect_regressions(tmp_path):
    history = tmp_path / 'working' / 'scores' / 'score-history.csv'
    _write_history(str(history), [
        (1, 'scene-a', 'prose_naturalness', 3),
        (2, 'scene-a', 'prose_naturalness', 2),  # regression
        (1, 'scene-b', 'prose_naturalness', 4),
        (2, 'scene-b', 'prose_naturalness', 4),  # no change
    ])

    regs = detect_regressions(str(tmp_path), 'prose_naturalness', threshold=-0.5)
    assert len(regs) == 1
    assert regs[0]['scene_id'] == 'scene-a'
    assert regs[0]['from_score'] == 3.0
    assert regs[0]['to_score'] == 2.0
    assert regs[0]['delta'] == -1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_history.py -v -k "get_scene_history or detect_stalls or detect_regressions"`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement query and detection functions**

Add to `scripts/lib/python/storyforge/history.py`:

```python
def _read_history(project_dir: str) -> list[dict[str, str]]:
    """Read score-history.csv. Returns list of row dicts."""
    path = _history_path(project_dir)
    if not os.path.isfile(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=DELIMITER)
        return [{k: (v if v is not None else '') for k, v in row.items()}
                for row in reader]


def get_scene_history(project_dir: str, scene_id: str,
                      principle: str) -> list[tuple[int, float]]:
    """Get score history for one scene+principle.

    Returns:
        List of (cycle, score) tuples sorted by cycle.
    """
    rows = _read_history(project_dir)
    result = []
    for row in rows:
        if row['scene_id'] == scene_id and row['principle'] == principle:
            try:
                result.append((int(row['cycle']), float(row['score'])))
            except (ValueError, KeyError):
                continue
    return sorted(result, key=lambda x: x[0])


def detect_stalls(project_dir: str, principle: str,
                  min_cycles: int = 2, max_score: float = 3.0) -> list[dict]:
    """Find scenes stalled on a principle.

    A scene is stalled if it scored <= max_score for >= min_cycles
    consecutive most-recent cycles without improvement.

    Returns:
        [{scene_id, scores: [(cycle, score)], cycles_stalled: int}]
    """
    rows = _read_history(project_dir)
    if not rows:
        return []

    # Group by scene
    by_scene: dict[str, list[tuple[int, float]]] = {}
    for row in rows:
        if row['principle'] != principle:
            continue
        sid = row['scene_id']
        try:
            by_scene.setdefault(sid, []).append(
                (int(row['cycle']), float(row['score']))
            )
        except (ValueError, KeyError):
            continue

    results = []
    for sid, scores in by_scene.items():
        scores.sort(key=lambda x: x[0])
        # Count consecutive low scores from the end
        stalled = 0
        for _, score in reversed(scores):
            if score <= max_score:
                stalled += 1
            else:
                break
        if stalled >= min_cycles:
            # Check no improvement in stalled window
            stalled_scores = scores[-stalled:]
            if stalled_scores[-1][1] <= stalled_scores[0][1]:
                results.append({
                    'scene_id': sid,
                    'scores': scores,
                    'cycles_stalled': stalled,
                })

    return results


def detect_regressions(project_dir: str, principle: str,
                       threshold: float = -0.5) -> list[dict]:
    """Find scenes where a principle score dropped significantly.

    Returns:
        [{scene_id, from_cycle, to_cycle, from_score, to_score, delta}]
    """
    rows = _read_history(project_dir)
    if not rows:
        return []

    # Group by scene
    by_scene: dict[str, list[tuple[int, float]]] = {}
    for row in rows:
        if row['principle'] != principle:
            continue
        sid = row['scene_id']
        try:
            by_scene.setdefault(sid, []).append(
                (int(row['cycle']), float(row['score']))
            )
        except (ValueError, KeyError):
            continue

    results = []
    for sid, scores in by_scene.items():
        scores.sort(key=lambda x: x[0])
        for i in range(1, len(scores)):
            delta = scores[i][1] - scores[i - 1][1]
            if delta <= threshold:
                results.append({
                    'scene_id': sid,
                    'from_cycle': scores[i - 1][0],
                    'to_cycle': scores[i][0],
                    'from_score': scores[i - 1][1],
                    'to_score': scores[i][1],
                    'delta': delta,
                })

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_history.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/history.py tests/test_history.py
git commit -m "Add stall and regression detection to history module"
git push
```

---

### Task 3: Integrate Score History into Scoring Pipeline

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_score.py:305-325` (after scene-scores written, before improvement cycle)

- [ ] **Step 1: Read the integration point**

Read `scripts/lib/python/storyforge/cmd_score.py` lines 300-330 to find the exact insertion point between score file writing and the improvement cycle.

- [ ] **Step 2: Add `append_cycle` call**

In `cmd_score.py`, after the cost summary (line 314) and before the improvement cycle (line 320), add:

```python
    # Append to score history for cross-cycle tracking
    from storyforge.history import append_cycle
    history_count = append_cycle(cycle_dir, cycle, project_dir)
    if history_count:
        log(f'Score history: appended {history_count} entries (cycle {cycle})')
```

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: All pass (no existing tests exercise this code path with real scoring)

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_score.py
git commit -m "Append to score history after each scoring cycle"
git push
```

---

### Task 4: Conflict-Free Brief Detection

**Files:**
- Modify: `scripts/lib/python/storyforge/hone.py:762-1023` (add detector, integrate)
- Create: `tests/test_hone_conflict.py`
- Reference: `scripts/lib/python/storyforge/hone.py:782-820` (detect_abstract_fields pattern)

- [ ] **Step 1: Write tests for conflict-free detection**

Create `tests/test_hone_conflict.py`:

```python
"""Tests for conflict-free brief detection."""

from storyforge.hone import detect_conflict_free


def test_keyword_observation_only():
    """Conflict field with observation words and no opposition."""
    briefs = {
        'scene-a': {
            'id': 'scene-a',
            'conflict': 'Zara observes how the landscape has shifted and reflects on what it means',
            'goal': 'Enter the Understory',
        },
    }
    intent = {
        'scene-a': {'id': 'scene-a', 'outcome': 'yes-but', 'value_shift': '+/-'},
    }
    issues = detect_conflict_free(briefs, intent)
    assert len(issues) == 1
    assert issues[0]['issue'] == 'conflict_free'
    assert issues[0]['reason'] in ('keyword', 'both')


def test_keyword_with_opposition():
    """Conflict field with genuine opposition words should not be flagged."""
    briefs = {
        'scene-a': {
            'id': 'scene-a',
            'conflict': 'The door refuses to open and guards block the passage',
            'goal': 'Escape',
        },
    }
    intent = {
        'scene-a': {'id': 'scene-a', 'outcome': 'no', 'value_shift': '+/-'},
    }
    issues = detect_conflict_free(briefs, intent)
    assert len(issues) == 0


def test_structural_easy_win():
    """Scene with outcome=yes and flat value_shift."""
    briefs = {
        'scene-a': {
            'id': 'scene-a',
            'conflict': 'The unfamiliar terrain challenges navigation',
            'goal': 'Cross the valley',
        },
    }
    intent = {
        'scene-a': {'id': 'scene-a', 'outcome': 'yes', 'value_shift': '+/+'},
    }
    issues = detect_conflict_free(briefs, intent)
    assert len(issues) == 1
    assert issues[0]['reason'] in ('structural', 'both')


def test_structural_not_flagged_with_real_resistance():
    """Scene with outcome=no should not be flagged structurally."""
    briefs = {
        'scene-a': {
            'id': 'scene-a',
            'conflict': 'The landscape is different',
            'goal': 'Explore',
        },
    }
    intent = {
        'scene-a': {'id': 'scene-a', 'outcome': 'no', 'value_shift': '+/-'},
    }
    issues = detect_conflict_free(briefs, intent)
    # May be flagged by keyword but not by structural
    for i in issues:
        assert i['reason'] != 'structural'


def test_empty_conflict_not_flagged():
    """Empty conflict field should not be flagged (that's a gap, not conflict-free)."""
    briefs = {
        'scene-a': {'id': 'scene-a', 'conflict': '', 'goal': 'Something'},
    }
    intent = {
        'scene-a': {'id': 'scene-a', 'outcome': 'yes', 'value_shift': '+/+'},
    }
    issues = detect_conflict_free(briefs, intent)
    assert len(issues) == 0


def test_both_keyword_and_structural():
    """Scene flagged by both methods gets reason='both'."""
    briefs = {
        'scene-a': {
            'id': 'scene-a',
            'conflict': 'Zara notices the garden has changed and contemplates the implications',
            'goal': 'Visit the garden',
        },
    }
    intent = {
        'scene-a': {'id': 'scene-a', 'outcome': 'yes', 'value_shift': '-/-'},
    }
    issues = detect_conflict_free(briefs, intent)
    assert len(issues) == 1
    assert issues[0]['reason'] == 'both'


def test_scene_filter():
    """Only check scenes in the filter list."""
    briefs = {
        'scene-a': {'id': 'scene-a', 'conflict': 'observes the world', 'goal': 'Look'},
        'scene-b': {'id': 'scene-b', 'conflict': 'observes the world', 'goal': 'Look'},
    }
    intent = {
        'scene-a': {'id': 'scene-a', 'outcome': 'yes', 'value_shift': '+/+'},
        'scene-b': {'id': 'scene-b', 'outcome': 'yes', 'value_shift': '+/+'},
    }
    issues = detect_conflict_free(briefs, intent, scene_ids=['scene-a'])
    assert all(i['scene_id'] == 'scene-a' for i in issues)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_hone_conflict.py -v`
Expected: FAIL with `ImportError: cannot import name 'detect_conflict_free'`

- [ ] **Step 3: Implement `detect_conflict_free`**

Add to `scripts/lib/python/storyforge/hone.py`, after `CONCRETE_INDICATORS` (line ~777) and before `_CONCRETIZABLE_FIELDS` (line ~779):

```python
# Conflict-quality detection indicators
OBSERVATION_INDICATORS = {
    'notices', 'observes', 'discovers', 'reflects', 'grapples with',
    'contemplates', 'realizes', 'wonders', 'considers', 'processes',
    'absorbs', 'witnesses', 'watches', 'senses', 'recognizes',
    'comes to understand', 'begins to see', 'takes in',
}

OPPOSITION_INDICATORS = {
    'refuses', 'blocks', 'demands', 'threatens', 'confronts', 'denies',
    'challenges', 'prevents', 'forbids', 'attacks', 'rejects', 'opposes',
    'locks', 'traps', 'forces', 'resists', 'fights', 'argues',
    'interrupts', 'undermines', 'betrays', 'withholds', 'hides',
}

_FLAT_SHIFTS = {'+/+', '-/-', '0/0', ''}
```

Then add the detector function after the existing `detect_verbose_fields` function and before `detect_brief_issues`:

```python
def detect_conflict_free(
    briefs_map: dict[str, dict[str, str]],
    intent_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect scenes where the conflict field lacks genuine dramatic opposition.

    Two checks:
    1. Keyword: conflict has observation words but no opposition words
    2. Structural: outcome is 'yes' AND value_shift is flat

    Args:
        briefs_map: scene-briefs.csv keyed by id.
        intent_map: scene-intent.csv keyed by id.
        scene_ids: Optional filter.

    Returns:
        List of issue dicts with issue='conflict_free'.
    """
    ids = scene_ids or list(briefs_map.keys())
    results = []

    for sid in ids:
        brief = briefs_map.get(sid)
        if not brief:
            continue
        conflict = (brief.get('conflict') or '').strip().lower()
        if not conflict:
            continue  # Empty conflict is a gap, not conflict-free

        # Keyword check
        obs_count = sum(1 for ind in OBSERVATION_INDICATORS if ind in conflict)
        opp_count = sum(1 for ind in OPPOSITION_INDICATORS if ind in conflict)
        keyword_flag = obs_count > 0 and opp_count == 0

        # Structural check
        intent = intent_map.get(sid) or {}
        outcome = (intent.get('outcome') or '').strip().lower()
        shift = (intent.get('value_shift') or '').strip()
        structural_flag = outcome == 'yes' and shift in _FLAT_SHIFTS

        if keyword_flag or structural_flag:
            if keyword_flag and structural_flag:
                reason = 'both'
            elif keyword_flag:
                reason = 'keyword'
            else:
                reason = 'structural'

            issue = {
                'scene_id': sid,
                'field': 'conflict',
                'value': brief.get('conflict', ''),
                'issue': 'conflict_free',
                'reason': reason,
                'observation_count': obs_count,
                'opposition_count': opp_count,
            }
            if structural_flag:
                issue['outcome'] = outcome
                issue['value_shift'] = shift
            results.append(issue)

    return sorted(results, key=lambda x: x['scene_id'])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hone_conflict.py -v`
Expected: 8 passed

- [ ] **Step 5: Integrate into `detect_brief_issues`**

Modify `detect_brief_issues` in `hone.py` (line ~1018-1022). The function currently takes `briefs_map` and `scenes_map` but not `intent_map`. Add `intent_map` as an optional parameter with a default of `None`:

Change the signature from:
```python
def detect_brief_issues(briefs_map: dict[str, dict[str, str]],
                        scenes_map: dict[str, dict[str, str]],
                        scene_ids: list[str] | None = None) -> list[dict]:
```
to:
```python
def detect_brief_issues(briefs_map: dict[str, dict[str, str]],
                        scenes_map: dict[str, dict[str, str]],
                        scene_ids: list[str] | None = None,
                        intent_map: dict[str, dict[str, str]] | None = None) -> list[dict]:
```

Then add to the issue composition block (after the existing three `issues.extend()` calls):

```python
    if intent_map is not None:
        issues.extend(detect_conflict_free(briefs_map, intent_map, scene_ids))
```

- [ ] **Step 6: Update callers to pass intent_map**

Search for all callers of `detect_brief_issues` and pass `intent_map` where available. The main callers are:

In `cmd_hone.py` `_run_briefs_domain` (line ~229-230):
```python
    issues = detect_brief_issues(briefs, scenes, scene_filter)
```
Change to:
```python
    intent = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    issues = detect_brief_issues(briefs, scenes, scene_filter, intent_map=intent)
```

In `cmd_hone.py` `_count_brief_issues` (line ~316-319):
```python
    briefs = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    scenes = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    issues = detect_brief_issues(briefs, scenes, scene_ids)
```
Change to:
```python
    briefs = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    scenes = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    issues = detect_brief_issues(briefs, scenes, scene_ids, intent_map=intent)
```

In `cmd_hone.py` `_run_diagnose` (line ~446):
```python
    issues = detect_brief_issues(briefs, scenes, scene_filter)
```
Change to:
```python
    issues = detect_brief_issues(briefs, scenes, scene_filter, intent_map=intent)
```

In `hone.py` `hone_briefs` (line ~1206):
```python
    all_issues = detect_brief_issues(briefs_map, scenes_map, scene_ids)
```
Change to:
```python
    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    all_issues = detect_brief_issues(briefs_map, scenes_map, scene_ids, intent_map=intent_map)
```

- [ ] **Step 7: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: All pass (existing callers use default `intent_map=None` which skips conflict-free detection, new callers pass it)

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/python/storyforge/hone.py scripts/lib/python/storyforge/cmd_hone.py tests/test_hone_conflict.py
git commit -m "Add conflict-free brief detection to hone pipeline"
git push
```

---

### Task 5: Causal Routing in Diagnosis

**Files:**
- Modify: `scripts/lib/python/storyforge/scoring.py:278-393` (generate_diagnosis)
- Create: `tests/test_scoring_rootcause.py`

- [ ] **Step 1: Write tests for root cause attribution**

Create `tests/test_scoring_rootcause.py`:

```python
"""Tests for root cause attribution in diagnosis."""

import csv
import os

from storyforge.scoring import generate_diagnosis


def _write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('|'.join(header) + '\n')
        for row in rows:
            f.write('|'.join(str(v) for v in row) + '\n')


def test_diagnosis_has_root_cause_column(tmp_path):
    """diagnosis.csv should include a root_cause column."""
    scores_dir = str(tmp_path / 'cycle')
    os.makedirs(scores_dir)

    _write_csv(os.path.join(scores_dir, 'scene-scores.csv'),
               ['id', 'prose_naturalness'],
               [['scene-a', '2'], ['scene-b', '4']])

    weights_file = str(tmp_path / 'weights.csv')
    _write_csv(weights_file, ['principle', 'weight'], [['prose_naturalness', '5']])

    generate_diagnosis(scores_dir, '', weights_file)

    diag_file = os.path.join(scores_dir, 'diagnosis.csv')
    with open(diag_file) as f:
        reader = csv.DictReader(f, delimiter='|')
        rows = list(reader)

    assert len(rows) > 0
    assert 'root_cause' in rows[0]


def test_root_cause_defaults_to_craft(tmp_path):
    """Without history or brief issues, root_cause should be 'craft'."""
    scores_dir = str(tmp_path / 'cycle')
    os.makedirs(scores_dir)

    _write_csv(os.path.join(scores_dir, 'scene-scores.csv'),
               ['id', 'prose_naturalness'],
               [['scene-a', '2']])

    weights_file = str(tmp_path / 'weights.csv')
    _write_csv(weights_file, ['principle', 'weight'], [['prose_naturalness', '5']])

    generate_diagnosis(scores_dir, '', weights_file)

    diag_file = os.path.join(scores_dir, 'diagnosis.csv')
    with open(diag_file) as f:
        reader = csv.DictReader(f, delimiter='|')
        rows = list(reader)

    for row in rows:
        assert row.get('root_cause') == 'craft'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_scoring_rootcause.py -v`
Expected: FAIL — `root_cause` not in output

- [ ] **Step 3: Add `root_cause` column to `generate_diagnosis`**

In `scripts/lib/python/storyforge/scoring.py`, modify `generate_diagnosis` (line 291):

Change the header from:
```python
    diag_header = ['principle', 'scale', 'avg_score', 'worst_items', 'delta_from_last', 'priority']
```
to:
```python
    diag_header = ['principle', 'scale', 'avg_score', 'worst_items', 'delta_from_last', 'priority', 'root_cause']
```

Then find where each `diag_rows.append(...)` call builds the row list (there should be one append per principle). Add `'craft'` as the default root_cause value at the end of each row. Search for the exact append pattern in the function and add the 7th element.

The rows are built as lists (not dicts), so each `diag_rows.append([...])` needs a 7th element. Find the append and add `'craft'` at the end.

- [ ] **Step 4: Add attribution logic**

After computing all diag_rows but before writing, add attribution. Insert before the `_write_csv(diagnosis_file, ...)` call:

```python
    # Root cause attribution: check stall history and brief quality
    # This is best-effort — only runs if data is available
    project_dir = _infer_project_dir(scores_dir)
    if project_dir:
        _attribute_root_causes(diag_rows, diag_header, project_dir)
```

Add a helper to infer project_dir from scores_dir (it's `working/scores/cycle-N` under project root):

```python
def _infer_project_dir(scores_dir: str) -> str:
    """Infer project root from a scores directory path.

    scores_dir is typically project_dir/working/scores/cycle-N.
    """
    path = os.path.normpath(scores_dir)
    parts = path.split(os.sep)
    # Look for 'working' in the path
    for i, part in enumerate(parts):
        if part == 'working' and i > 0:
            return os.sep.join(parts[:i])
    return ''


def _attribute_root_causes(diag_rows: list[list[str]],
                           diag_header: list[str],
                           project_dir: str) -> None:
    """Update root_cause column in diag_rows based on stall history and brief quality.

    Modifies diag_rows in place.
    """
    root_cause_idx = diag_header.index('root_cause')
    worst_items_idx = diag_header.index('worst_items')
    principle_idx = diag_header.index('principle')
    priority_idx = diag_header.index('priority')

    # Load brief quality data (lazy — only if needed)
    ref_dir = os.path.join(project_dir, 'reference')
    brief_issues = None
    stalls = None

    for row in diag_rows:
        priority = row[priority_idx]
        if priority not in ('high', 'medium'):
            continue

        principle = row[principle_idx]
        worst = row[worst_items_idx]
        if not worst:
            continue

        scene_ids = [s.strip() for s in worst.split(';') if s.strip()]

        # Check stall history
        if stalls is None:
            try:
                from storyforge.history import detect_stalls
                stalls = {s['scene_id'] for s in detect_stalls(project_dir, principle)}
            except Exception:
                stalls = set()

        # Check brief quality
        if brief_issues is None:
            try:
                from storyforge.elaborate import _read_csv_as_map
                from storyforge.hone import detect_brief_issues
                briefs = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
                scenes = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
                intent = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
                issues = detect_brief_issues(briefs, scenes, intent_map=intent)
                brief_issues = {i['scene_id'] for i in issues}
            except Exception:
                brief_issues = set()

        # Attribution: any worst-item scene with brief issues or stalls → brief
        for sid in scene_ids:
            if sid in brief_issues or sid in stalls:
                row[root_cause_idx] = 'brief'
                break
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_scoring_rootcause.py -v`
Expected: 2 passed

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/scoring.py tests/test_scoring_rootcause.py
git commit -m "Add root_cause attribution to generate_diagnosis"
git push
```

---

### Task 6: Score Trends in Diagnose Output

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_hone.py:420-526` (_run_diagnose)

- [ ] **Step 1: Read `_run_diagnose` to find insertion point**

Read `scripts/lib/python/storyforge/cmd_hone.py` lines 495-510 to find the summary section where we'll add score trends.

- [ ] **Step 2: Add score trends section**

In `_run_diagnose`, after the Prose Exemplars section (Part 4) and before the Summary section, add:

```python
    # Part 5: Score Trends (if history available)
    print('\n=== Score Trends ===\n')
    try:
        from storyforge.history import detect_stalls, detect_regressions
        nat_stalls = detect_stalls(project_dir, 'prose_naturalness')
        nat_regs = detect_regressions(project_dir, 'prose_naturalness')

        if nat_stalls:
            print(f'  Stalled on naturalness ({len(nat_stalls)} scenes):')
            for s in nat_stalls[:10]:
                scores_str = ', '.join(f'cycle {c}={int(v)}' for c, v in s['scores'][-3:])
                print(f'    {s["scene_id"]}: stuck for {s["cycles_stalled"]} cycles ({scores_str})')
        else:
            print('  No naturalness stalls detected.')

        if nat_regs:
            print(f'\n  Regressions ({len(nat_regs)} scenes):')
            for r in nat_regs[:5]:
                print(f'    {r["scene_id"]}: {r["from_score"]:.0f} → {r["to_score"]:.0f} '
                      f'(cycle {r["from_cycle"]} → {r["to_cycle"]})')

        if nat_stalls:
            print(f'\n  These scenes need upstream fixes (brief rewrite), not more prose revision.')
            print(f'  Run: storyforge revise --polish --loop')
    except ImportError:
        print('  (score history not available)')
    except Exception:
        print('  (no score history yet — run storyforge score first)')
```

- [ ] **Step 3: Update the `_count_brief_issues` return to include conflict_free count**

In `_count_brief_issues` (line ~313), add conflict_free to the return dict:

```python
    return {
        'total': len(issues),
        'scenes': len(set(i['scene_id'] for i in issues)),
        'abstract': by_type.get('abstract', 0),
        'overspecified': by_type.get('overspecified', 0),
        'verbose': by_type.get('verbose', 0),
        'conflict_free': by_type.get('conflict_free', 0),
    }
```

Update `_log_brief_counts` to include it:

```python
def _log_brief_counts(counts: dict, prefix: str = '') -> None:
    parts = []
    for key in ('abstract', 'overspecified', 'verbose', 'conflict_free'):
        if counts.get(key, 0) > 0:
            parts.append(f'{key}: {counts[key]}')
    detail = ', '.join(parts) if parts else 'none'
    log(f'{prefix}{counts["total"]} brief issues across {counts["scenes"]} scenes ({detail})')
```

- [ ] **Step 4: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_hone.py
git commit -m "Add score trends and conflict-free counts to hone diagnose"
git push
```

---

### Task 7: Upstream Pass in Polish Loop

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py:442-538` (_run_polish_loop)

- [ ] **Step 1: Read the current polish loop flow**

Read `scripts/lib/python/storyforge/cmd_revise.py` lines 479-516 to understand the iteration structure.

- [ ] **Step 2: Add upstream detection and brief rewrite logic**

In `_run_polish_loop`, after the convergence checks (line ~504) and before generating the targeted polish plan (line ~508), add upstream detection:

```python
        # Check for upstream causes before craft polish
        upstream_scenes = _detect_upstream_scenes(project_dir, diag_rows)
        if upstream_scenes:
            log(f'  Upstream issues detected in {len(upstream_scenes)} scenes — fixing briefs first')
            _fix_upstream_briefs(project_dir, upstream_scenes)
            # Re-draft affected scenes
            _redraft_scenes(project_dir, upstream_scenes)
            commit_and_push(project_dir,
                            f'Polish: upstream brief fixes for {len(upstream_scenes)} scenes',
                            ['reference/', 'scenes/', 'working/'])
```

- [ ] **Step 3: Implement `_detect_upstream_scenes`**

Add to `cmd_revise.py`:

```python
def _detect_upstream_scenes(project_dir: str, diag_rows: list[dict]) -> list[str]:
    """Identify scenes that need upstream fixes based on diagnosis root_cause.

    Returns list of scene IDs where root_cause is 'brief' and naturalness is low.
    """
    upstream = set()

    for row in diag_rows:
        if row.get('root_cause') != 'brief':
            continue
        worst = row.get('worst_items', '')
        if not worst:
            continue
        for sid in worst.split(';'):
            sid = sid.strip()
            if sid:
                upstream.add(sid)

    return sorted(upstream)
```

- [ ] **Step 4: Implement `_fix_upstream_briefs`**

Add to `cmd_revise.py`:

```python
def _fix_upstream_briefs(project_dir: str, scene_ids: list[str]) -> int:
    """Rewrite conflict/goal/crisis fields for scenes with upstream issues.

    Uses the API to generate briefs with genuine dramatic opposition.
    Returns number of fields rewritten.
    """
    from storyforge.elaborate import _read_csv_as_map, _write_csv, _FILE_MAP
    from storyforge.api import invoke_api
    from storyforge.common import select_model

    ref_dir = os.path.join(project_dir, 'reference')
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))

    model = select_model('synthesis')
    fields_rewritten = 0

    for sid in scene_ids:
        brief = briefs_map.get(sid)
        scene = scenes_map.get(sid, {})
        intent = intent_map.get(sid, {})
        if not brief:
            continue

        log(f'    Rewriting brief for {sid}...')

        prompt = f"""Rewrite the conflict, goal, crisis, and decision fields for this scene brief to introduce genuine dramatic opposition. The current brief describes observation or contemplation without resistance.

## Current Brief
- **Scene:** {sid} — {scene.get('title', sid)}
- **POV:** {scene.get('pov', 'unknown')}
- **Goal:** {brief.get('goal', '')}
- **Conflict:** {brief.get('conflict', '')}
- **Crisis:** {brief.get('crisis', '')}
- **Decision:** {brief.get('decision', '')}
- **Outcome:** {intent.get('outcome', '')}
- **Value at stake:** {intent.get('value_at_stake', '')}
- **Emotional arc:** {intent.get('emotional_arc', '')}

## Instructions

Rewrite these four fields so that:
1. The **conflict** describes something that actively resists the goal — a person, obstacle, or force that opposes the protagonist
2. The **goal** is a concrete dramatic question, not a procedural task
3. The **crisis** is a genuine dilemma — two bad choices or two incompatible goods
4. The **decision** is an active choice with consequences

Keep the scene's existing emotional arc and value at stake. The opposition should feel organic to the story context.

## Output Format

GOAL: [rewritten goal]
CONFLICT: [rewritten conflict]
CRISIS: [rewritten crisis]
DECISION: [rewritten decision]

No other text."""

        response = invoke_api(prompt, model, max_tokens=512,
                              label=f'upstream brief fix ({sid})')
        if not response:
            continue

        # Parse response
        for line in response.strip().split('\n'):
            line = line.strip()
            for field in ('GOAL', 'CONFLICT', 'CRISIS', 'DECISION'):
                if line.upper().startswith(f'{field}:'):
                    value = line[len(field) + 1:].strip()
                    if value:
                        brief[field.lower()] = value
                        fields_rewritten += 1

    # Write back
    if fields_rewritten > 0:
        rows = list(briefs_map.values())
        rows.sort(key=lambda r: r.get('id', ''))
        _write_csv(os.path.join(ref_dir, 'scene-briefs.csv'), rows,
                   _FILE_MAP['scene-briefs.csv'])

    log(f'    {fields_rewritten} brief fields rewritten across {len(scene_ids)} scenes')
    return fields_rewritten
```

- [ ] **Step 5: Implement `_redraft_scenes`**

Add to `cmd_revise.py`:

```python
def _redraft_scenes(project_dir: str, scene_ids: list[str]) -> int:
    """Re-draft scenes after brief rewrites using brief-aware drafting.

    Returns number of scenes re-drafted.
    """
    from storyforge.api import invoke_api
    from storyforge.common import select_model
    from storyforge.prompts import build_scene_prompt
    from storyforge.elaborate import _read_csv_as_map

    ref_dir = os.path.join(project_dir, 'reference')
    scenes_dir = os.path.join(project_dir, 'scenes')

    model = select_model('drafting')
    redrafted = 0

    for sid in scene_ids:
        scene_file = os.path.join(scenes_dir, f'{sid}.md')
        if not os.path.isfile(scene_file):
            continue

        log(f'    Re-drafting {sid}...')

        prompt = build_scene_prompt(sid, ref_dir, project_dir)
        if not prompt:
            continue

        text = invoke_api(prompt, model, max_tokens=8192,
                          label=f'upstream re-draft ({sid})')
        if text:
            with open(scene_file, 'w', encoding='utf-8') as f:
                f.write(text)
            redrafted += 1

    log(f'    {redrafted} scenes re-drafted with new briefs')
    return redrafted
```

- [ ] **Step 6: Apply same logic to `--naturalness` flow**

In `_generate_naturalness_plan` (line ~146), add a check at the top that reads diagnosis and excludes upstream scenes:

```python
def _generate_naturalness_plan(plan_file: str, project_dir: str = '') -> list[dict]:
    """Generate the 3-pass naturalness plan.

    If project_dir is provided, checks for upstream scenes and excludes them
    (they'll be handled by _fix_upstream_briefs in the main flow).
    """
```

The `--naturalness` flow in main should call `_detect_upstream_scenes` before the naturalness plan, similar to the polish loop. Add to the naturalness execution path (find where `_generate_naturalness_plan` is called):

```python
    # Check for upstream causes first
    if diag_rows:
        upstream_scenes = _detect_upstream_scenes(project_dir, diag_rows)
        if upstream_scenes:
            log(f'Upstream issues in {len(upstream_scenes)} scenes — fixing briefs')
            _fix_upstream_briefs(project_dir, upstream_scenes)
            _redraft_scenes(project_dir, upstream_scenes)
            commit_and_push(project_dir,
                            f'Naturalness: upstream brief fixes',
                            ['reference/', 'scenes/', 'working/'])
```

- [ ] **Step 7: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py
git commit -m "Add upstream brief fix pass to polish loop and naturalness"
git push
```

---

### Task 8: Documentation Updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `skills/hone/SKILL.md`
- Modify: `skills/revise/SKILL.md`
- Modify: `skills/forge/SKILL.md`

- [ ] **Step 1: Update CLAUDE.md shared modules**

In the `### Shared Modules — USE THEM` section (after the `csv_cli.py` block around line 83), add:

```markdown
**history.py:**
- `append_cycle(scores_dir, cycle, project_dir)` — append scene scores to history
- `get_scene_history(project_dir, scene_id, principle)` — returns [(cycle, score)]
- `detect_stalls(project_dir, principle, min_cycles, max_score)` — scenes stuck on a principle
- `detect_regressions(project_dir, principle, threshold)` — scenes where score dropped
```

- [ ] **Step 2: Update CLAUDE.md key CSV files**

In the `### Key CSV Files` section (around line 178-181), add to the Shared files:

```markdown
- `working/scores/score-history.csv` — per-scene, per-principle scores across cycles (cycle, scene_id, principle, score)
```

- [ ] **Step 3: Update hone skill**

In `skills/hone/SKILL.md`, in the diagnose flow section, add after the existing domain recommendations:

```markdown
**Score trends (when history data exists):**

9. **Naturalness stalls detected** → Scenes stuck at low naturalness for 2+ cycles need upstream fixes (brief rewrite), not more prose revision. The `--polish --loop` command now auto-detects this and fixes briefs first. Explain this to the author: "These scenes have been through multiple polish passes without improvement. The problem is in the brief, not the prose — the brief doesn't have real conflict. I'll fix the briefs and re-draft."

10. **Regressions detected** → A scene's naturalness score dropped after revision. Flag it: "Scene X regressed from 3 to 2 after the last polish pass — the revision made it worse. This usually means the AI regenerated the same patterns. The brief needs to change so the re-draft produces fundamentally different prose."
```

Also add `conflict_free` to the brief quality issues list:

```markdown
**Conflict-free scenes** — the conflict field describes observation or contemplation rather than genuine opposition:
- "observes how the landscape has shifted" instead of "the locked door blocks the only exit"
- "reflects on the weight of memory" instead of "the deadline forces a choice between loyalty and truth"

Detected by keyword analysis (observation vs. opposition words) and structural cross-reference (outcome=yes with flat value_shift). Fix by rewriting the conflict, goal, crisis, and decision fields to introduce real dramatic opposition.
```

- [ ] **Step 4: Update revise skill**

In `skills/revise/SKILL.md`, add a section about upstream routing:

```markdown
### Upstream Fix Routing (automatic in --polish --loop)

When `--polish --loop` detects that a scene's naturalness is stalled because of a conflict-free or abstract brief, it automatically:

1. **Rewrites the brief** — conflict, goal, crisis, and decision fields get genuine dramatic opposition
2. **Re-drafts the scene** — fresh draft using the new brief, so the prose reflects real conflict
3. **Then polishes** — normal craft polish on the re-drafted scene

This means the author doesn't need to manually identify upstream causes. The loop handles:
- Iteration 1: Fix briefs + re-draft stalled scenes, polish all
- Iteration 2: Score, polish remaining craft issues
- Iteration 3: Score, converged

The `--naturalness` mode also checks for upstream causes before running its 3-pass craft plan.

If naturalness isn't improving after 2 polish passes, the system automatically tries brief rewrites. No manual intervention needed.
```

- [ ] **Step 5: Update forge skill**

In `skills/forge/SKILL.md`, find the section about recommending revision approaches and add:

```markdown
**When naturalness is stalled:** If score history shows naturalness stuck for 2+ cycles, do NOT recommend another `--polish` or `--naturalness` pass. Instead explain: "These scenes have been polished multiple times without improvement. The problem is upstream — the briefs lack real dramatic conflict. Running `--polish --loop` will now detect this automatically and fix the briefs before polishing." Check `hone --diagnose` for the Score Trends section to see which scenes are stalled.
```

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md skills/hone/SKILL.md skills/revise/SKILL.md skills/forge/SKILL.md
git commit -m "Update docs: history module, conflict-free detection, upstream routing"
git push
```

---

### Task 9: Version Bump and Final Verification

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Bump minor version**

In `.claude-plugin/plugin.json`, change:
```json
"version": "1.2.2"
```
to:
```json
"version": "1.3.0"
```
(Minor bump for new feature)

- [ ] **Step 2: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 3: Test on unicorn-tail**

Run diagnose on unicorn-tail to verify the new features work end-to-end:

```bash
cd ~/Developer/unicorn-tail && PYTHONPATH=~/Developer/storyforge/scripts/lib/python python3 -m storyforge hone --diagnose
```

Verify:
- Score Trends section appears (may say "no score history yet" if no history file exists)
- Brief Quality section shows `conflict_free` issues if any exist
- No crashes

- [ ] **Step 4: Commit and push**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 1.3.0"
git push
```

- [ ] **Step 5: Update PR**

Update PR #127 description to mark implementation tasks as complete. Remove draft status:

```bash
gh pr ready 127
```
