# Score-Driven Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evaluation staleness detection, a `--scores` revision mode that plans purely from scoring data, and deferred redrafting to avoid redundant scene re-drafts during upstream passes.

**Architecture:** Three independent components: (1) a staleness checker in `scoring.py` that compares eval age against manuscript changes, (2) a `--scores` plan generator in `cmd_revise.py` that reads diagnosis data, (3) a deferred-redraft mode in the pass execution loop. Each can be built and tested independently.

**Tech Stack:** Python, existing `storyforge` modules (`scoring.py`, `cmd_revise.py`, `cmd_evaluate.py`, `hone.py`), pipe-delimited CSV, git.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `scripts/lib/python/storyforge/scoring.py` | Add `check_eval_staleness()` and `is_full_llm_cycle()` |
| `scripts/lib/python/storyforge/cmd_evaluate.py` | Write word count snapshot at end of eval |
| `scripts/lib/python/storyforge/cmd_revise.py` | Add `--scores` flag + `_generate_scores_plan()`, deferred redraft logic |
| `tests/test_eval_staleness.py` | Tests for staleness detection |
| `tests/test_revise_scores.py` | Tests for `--scores` plan generation |
| `tests/test_deferred_redraft.py` | Tests for deferred redrafting |

---

### Task 1: Add `is_full_llm_cycle()` to scoring.py

A utility that checks whether a scoring cycle directory contains full LLM results (not just deterministic). Used by staleness detection to count meaningful scoring runs.

**Files:**
- Modify: `scripts/lib/python/storyforge/scoring.py`
- Create: `tests/test_eval_staleness.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_staleness.py
"""Tests for evaluation staleness detection."""

import os
import pytest


class TestIsFullLlmCycle:
    def test_deterministic_only_returns_false(self, tmp_path):
        from storyforge.scoring import is_full_llm_cycle

        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)
        # Write scores with only deterministic principles
        with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
            f.write('scene_id|principle|score\n')
            f.write('s01|avoid_passive|3.5\n')
            f.write('s01|avoid_adverbs|4.0\n')
            f.write('s01|economy_clarity|3.8\n')
            f.write('s01|prose_repetition|4.2\n')
            f.write('s01|no_weather_dreams|5.0\n')
            f.write('s01|sentence_as_thought|3.9\n')

        assert is_full_llm_cycle(cycle_dir) is False

    def test_full_llm_returns_true(self, tmp_path):
        from storyforge.scoring import is_full_llm_cycle

        cycle_dir = str(tmp_path / 'cycle-2')
        os.makedirs(cycle_dir)
        with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
            f.write('scene_id|principle|score\n')
            f.write('s01|avoid_passive|3.5\n')
            f.write('s01|prose_naturalness|2.8\n')
            f.write('s01|dialogue_authenticity|3.2\n')

        assert is_full_llm_cycle(cycle_dir) is True

    def test_missing_scores_file_returns_false(self, tmp_path):
        from storyforge.scoring import is_full_llm_cycle

        cycle_dir = str(tmp_path / 'cycle-3')
        os.makedirs(cycle_dir)
        assert is_full_llm_cycle(cycle_dir) is False

    def test_empty_scores_file_returns_false(self, tmp_path):
        from storyforge.scoring import is_full_llm_cycle

        cycle_dir = str(tmp_path / 'cycle-4')
        os.makedirs(cycle_dir)
        with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
            f.write('scene_id|principle|score\n')

        assert is_full_llm_cycle(cycle_dir) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_eval_staleness.py::TestIsFullLlmCycle -v`
Expected: FAIL — `is_full_llm_cycle` does not exist

- [ ] **Step 3: Implement `is_full_llm_cycle`**

Add at the end of `scripts/lib/python/storyforge/scoring.py` (before any `if __name__` block if present):

```python
# The 6 deterministic principles that don't require LLM calls
_DETERMINISTIC_PRINCIPLES = frozenset([
    'prose_repetition', 'avoid_passive', 'avoid_adverbs',
    'no_weather_dreams', 'sentence_as_thought', 'economy_clarity',
])


def is_full_llm_cycle(cycle_dir: str) -> bool:
    """Check if a scoring cycle contains full LLM results (not deterministic-only).

    A full LLM cycle has scores for principles beyond the 6 deterministic ones.
    """
    scores_file = os.path.join(cycle_dir, 'scene-scores.csv')
    if not os.path.isfile(scores_file):
        return False

    with open(scores_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='|')
        for row in reader:
            principle = row.get('principle', '').strip()
            if principle and principle not in _DETERMINISTIC_PRINCIPLES:
                return True
    return False
```

Make sure `import csv` and `import os` are present at the top of `scoring.py` (they already are).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_eval_staleness.py::TestIsFullLlmCycle -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/scoring.py tests/test_eval_staleness.py
git commit -m "Add is_full_llm_cycle to distinguish deterministic from full scoring"
git push
```

---

### Task 2: Write word count snapshot in cmd_evaluate.py

At the end of a successful evaluation, write `word-counts.csv` into the eval directory.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_evaluate.py` (insert before line 1331, the cost summary block)
- Modify: `tests/test_eval_staleness.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_eval_staleness.py`:

```python
class TestWordCountSnapshot:
    def test_write_snapshot(self, tmp_path):
        from storyforge.cmd_evaluate import _write_word_count_snapshot

        eval_dir = str(tmp_path / 'eval-20260415')
        os.makedirs(eval_dir)
        ref_dir = str(tmp_path / 'reference')
        os.makedirs(ref_dir)

        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('s01|1|First|1|Alice|drafted|2847|3000\n')
            f.write('s02|2|Second|1|Bob|drafted|3102|3000\n')

        _write_word_count_snapshot(eval_dir, str(tmp_path))

        snapshot = os.path.join(eval_dir, 'word-counts.csv')
        assert os.path.isfile(snapshot)

        with open(snapshot) as f:
            content = f.read()
        assert 'id|word_count' in content
        assert 's01|2847' in content
        assert 's02|3102' in content

    def test_write_snapshot_skips_zero_wordcount(self, tmp_path):
        from storyforge.cmd_evaluate import _write_word_count_snapshot

        eval_dir = str(tmp_path / 'eval-20260415')
        os.makedirs(eval_dir)
        ref_dir = str(tmp_path / 'reference')
        os.makedirs(ref_dir)

        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('s01|1|First|1|Alice|drafted|2847|3000\n')
            f.write('s02|2|Second|1|Bob|outline|0|3000\n')

        _write_word_count_snapshot(eval_dir, str(tmp_path))

        with open(os.path.join(eval_dir, 'word-counts.csv')) as f:
            content = f.read()
        assert 's01|2847' in content
        assert 's02' not in content  # zero word count excluded

    def test_write_snapshot_no_scenes_csv(self, tmp_path):
        from storyforge.cmd_evaluate import _write_word_count_snapshot

        eval_dir = str(tmp_path / 'eval-20260415')
        os.makedirs(eval_dir)

        # Should not raise, just skip
        _write_word_count_snapshot(eval_dir, str(tmp_path))
        assert not os.path.isfile(os.path.join(eval_dir, 'word-counts.csv'))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_eval_staleness.py::TestWordCountSnapshot -v`
Expected: FAIL — `_write_word_count_snapshot` does not exist

- [ ] **Step 3: Implement `_write_word_count_snapshot`**

Add to `scripts/lib/python/storyforge/cmd_evaluate.py` near the other helper functions (before `main()`):

```python
def _write_word_count_snapshot(eval_dir: str, project_dir: str) -> None:
    """Write word count snapshot for staleness detection."""
    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    if not os.path.isfile(scenes_csv):
        return

    from storyforge.csv_cli import get_column, list_ids
    ids = list_ids(scenes_csv)
    wc_col = get_column(scenes_csv, 'word_count')

    snapshot_path = os.path.join(eval_dir, 'word-counts.csv')
    with open(snapshot_path, 'w') as f:
        f.write('id|word_count\n')
        for scene_id, wc in zip(ids, wc_col):
            if wc and wc != '0':
                f.write(f'{scene_id}|{wc}\n')
```

- [ ] **Step 4: Wire into main()**

In `cmd_evaluate.py`, insert before line 1331 (the `# Cost summary` comment):

```python
    # Write word count snapshot for staleness detection
    _write_word_count_snapshot(eval_dir, project_dir)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_eval_staleness.py -v`
Expected: All passed

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_evaluate.py tests/test_eval_staleness.py
git commit -m "Add word count snapshot at end of evaluation for staleness detection"
git push
```

---

### Task 3: Implement `check_eval_staleness()` in scoring.py

The core staleness detection function. Compares latest eval against current state.

**Files:**
- Modify: `scripts/lib/python/storyforge/scoring.py`
- Modify: `tests/test_eval_staleness.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_eval_staleness.py`:

```python
class TestCheckEvalStaleness:
    def _setup_project(self, tmp_path, eval_date='20260408-120000',
                       snapshot_words=None, current_words=None,
                       full_cycles_after_eval=0, det_cycles_after_eval=0):
        """Build a minimal project with eval dir and scoring cycles."""
        project_dir = str(tmp_path / 'project')
        eval_base = os.path.join(project_dir, 'working', 'evaluations')
        scores_base = os.path.join(project_dir, 'working', 'scores')
        ref_dir = os.path.join(project_dir, 'reference')
        os.makedirs(eval_base)
        os.makedirs(scores_base)
        os.makedirs(ref_dir)

        # Create eval dir with optional word count snapshot
        eval_dir = os.path.join(eval_base, f'eval-{eval_date}')
        os.makedirs(eval_dir)
        with open(os.path.join(eval_dir, 'synthesis.md'), 'w') as f:
            f.write('Evaluation summary')

        if snapshot_words:
            with open(os.path.join(eval_dir, 'word-counts.csv'), 'w') as f:
                f.write('id|word_count\n')
                for sid, wc in snapshot_words.items():
                    f.write(f'{sid}|{wc}\n')

        # Create current scenes.csv
        words = current_words or snapshot_words or {'s01': 3000}
        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            for i, (sid, wc) in enumerate(words.items(), 1):
                f.write(f'{sid}|{i}|Scene {i}|1|Alice|drafted|{wc}|3000\n')

        # Create scoring cycles (deterministic-only)
        for c in range(1, det_cycles_after_eval + 1):
            cycle_dir = os.path.join(scores_base, f'cycle-{c}')
            os.makedirs(cycle_dir)
            with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
                f.write('scene_id|principle|score\n')
                f.write('s01|avoid_passive|3.5\n')

        # Create full LLM cycles (numbered after deterministic)
        offset = det_cycles_after_eval
        for c in range(1, full_cycles_after_eval + 1):
            cycle_dir = os.path.join(scores_base, f'cycle-{offset + c}')
            os.makedirs(cycle_dir)
            with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
                f.write('scene_id|principle|score\n')
                f.write('s01|avoid_passive|3.5\n')
                f.write('s01|prose_naturalness|2.8\n')

        # storyforge.yaml
        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n')

        return project_dir

    def test_no_eval_is_stale(self, tmp_path):
        from storyforge.scoring import check_eval_staleness

        project_dir = str(tmp_path / 'project')
        os.makedirs(os.path.join(project_dir, 'working', 'evaluations'))
        result = check_eval_staleness(project_dir)
        assert result['stale'] is True
        assert 'no evaluation found' in result['reasons']

    def test_fresh_eval_no_changes(self, tmp_path):
        from storyforge.scoring import check_eval_staleness

        words = {'s01': 3000, 's02': 2500}
        project_dir = self._setup_project(tmp_path,
            snapshot_words=words, current_words=words)
        result = check_eval_staleness(project_dir)
        assert result['stale'] is False
        assert result['word_delta_pct'] == 0.0
        assert result['score_runs_since'] == 0

    def test_stale_by_word_delta(self, tmp_path):
        from storyforge.scoring import check_eval_staleness

        snapshot = {'s01': 3000, 's02': 2500, 's03': 2000}  # total 7500
        current = {'s01': 4000, 's02': 3500, 's03': 2000}   # delta=2000, 26.7%
        project_dir = self._setup_project(tmp_path,
            snapshot_words=snapshot, current_words=current)
        result = check_eval_staleness(project_dir)
        assert result['stale'] is True
        assert result['word_delta_pct'] > 0.20
        assert any('word delta' in r for r in result['reasons'])

    def test_not_stale_below_word_threshold(self, tmp_path):
        from storyforge.scoring import check_eval_staleness

        snapshot = {'s01': 3000, 's02': 2500}  # total 5500
        current = {'s01': 3200, 's02': 2600}   # delta=300, 5.5%
        project_dir = self._setup_project(tmp_path,
            snapshot_words=snapshot, current_words=current)
        result = check_eval_staleness(project_dir)
        assert result['stale'] is False
        assert result['word_delta_pct'] < 0.20

    def test_stale_by_full_score_runs(self, tmp_path):
        from storyforge.scoring import check_eval_staleness

        words = {'s01': 3000}
        project_dir = self._setup_project(tmp_path,
            snapshot_words=words, current_words=words,
            full_cycles_after_eval=2)
        result = check_eval_staleness(project_dir)
        assert result['stale'] is True
        assert result['score_runs_since'] >= 2
        assert any('score runs' in r for r in result['reasons'])

    def test_deterministic_cycles_dont_count(self, tmp_path):
        from storyforge.scoring import check_eval_staleness

        words = {'s01': 3000}
        project_dir = self._setup_project(tmp_path,
            snapshot_words=words, current_words=words,
            det_cycles_after_eval=5, full_cycles_after_eval=1)
        result = check_eval_staleness(project_dir)
        assert result['stale'] is False
        assert result['score_runs_since'] == 1

    def test_no_snapshot_still_works(self, tmp_path):
        """Old evals without word-counts.csv should not crash."""
        from storyforge.scoring import check_eval_staleness

        project_dir = self._setup_project(tmp_path,
            snapshot_words=None, current_words={'s01': 3000})
        result = check_eval_staleness(project_dir)
        # Without snapshot, word delta can't be computed — defaults to 0
        assert result['word_delta_pct'] == 0.0
        assert result['stale'] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_eval_staleness.py::TestCheckEvalStaleness -v`
Expected: FAIL — `check_eval_staleness` does not exist

- [ ] **Step 3: Implement `check_eval_staleness`**

Add to `scripts/lib/python/storyforge/scoring.py` after `is_full_llm_cycle`:

```python
STALENESS_WORD_DELTA_THRESHOLD = 0.20  # 20% cumulative word delta
STALENESS_SCORE_RUNS_THRESHOLD = 2     # 2+ full LLM scoring runs


def check_eval_staleness(project_dir: str) -> dict:
    """Check whether the latest evaluation is stale relative to current manuscript state.

    Returns dict with keys: stale, reasons, eval_dir, eval_date,
    word_delta_pct, score_runs_since.
    """
    result = {
        'stale': False,
        'reasons': [],
        'eval_dir': None,
        'eval_date': None,
        'word_delta_pct': 0.0,
        'score_runs_since': 0,
    }

    # Find latest evaluation
    eval_base = os.path.join(project_dir, 'working', 'evaluations')
    if not os.path.isdir(eval_base):
        result['stale'] = True
        result['reasons'].append('no evaluation found')
        return result

    eval_dirs = sorted([
        d for d in os.listdir(eval_base)
        if d.startswith('eval-') and os.path.isdir(os.path.join(eval_base, d))
    ])
    if not eval_dirs:
        result['stale'] = True
        result['reasons'].append('no evaluation found')
        return result

    latest_eval = eval_dirs[-1]
    result['eval_dir'] = os.path.join(eval_base, latest_eval)
    # Extract date portion (eval-YYYYMMDD or eval-YYYYMMDD-HHMMSS)
    result['eval_date'] = latest_eval.removeprefix('eval-')[:8]

    # Count full LLM scoring runs since eval
    scores_base = os.path.join(project_dir, 'working', 'scores')
    if os.path.isdir(scores_base):
        for name in sorted(os.listdir(scores_base)):
            if not name.startswith('cycle-'):
                continue
            cycle_dir = os.path.join(scores_base, name)
            if not os.path.isdir(cycle_dir):
                continue
            if is_full_llm_cycle(cycle_dir):
                result['score_runs_since'] += 1

    if result['score_runs_since'] >= STALENESS_SCORE_RUNS_THRESHOLD:
        result['stale'] = True
        result['reasons'].append(
            f'{result["score_runs_since"]} full score runs since evaluation')

    # Compute word delta from snapshot
    snapshot_file = os.path.join(result['eval_dir'], 'word-counts.csv')
    if os.path.isfile(snapshot_file):
        snapshot = {}
        with open(snapshot_file, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='|')
            for row in reader:
                sid = row.get('id', '').strip()
                wc = row.get('word_count', '0').strip()
                if sid and wc and wc != '0':
                    snapshot[sid] = int(wc)

        # Read current word counts
        from storyforge.csv_cli import get_column, list_ids
        scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        if os.path.isfile(scenes_csv) and snapshot:
            ids = list_ids(scenes_csv)
            wc_col = get_column(scenes_csv, 'word_count')
            current = {}
            for sid, wc in zip(ids, wc_col):
                if wc and wc != '0':
                    current[sid] = int(wc)

            total_snapshot = sum(snapshot.values())
            if total_snapshot > 0:
                delta_sum = sum(
                    abs(current.get(sid, 0) - snapshot.get(sid, 0))
                    for sid in set(snapshot) | set(current)
                )
                result['word_delta_pct'] = delta_sum / total_snapshot

                if result['word_delta_pct'] >= STALENESS_WORD_DELTA_THRESHOLD:
                    result['stale'] = True
                    pct = result['word_delta_pct'] * 100
                    result['reasons'].append(f'{pct:.0f}% word delta since evaluation')

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_eval_staleness.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/scoring.py tests/test_eval_staleness.py
git commit -m "Add check_eval_staleness for detecting outdated evaluation findings"
git push
```

---

### Task 4: Add `--scores` flag and `_generate_scores_plan()` to cmd_revise.py

New plan generator that reads diagnosis data and creates upstream + craft passes.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py` (add flag to `parse_args`, add plan generator, wire into `main()`)
- Create: `tests/test_revise_scores.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_revise_scores.py
"""Tests for revise --scores mode."""

import os
import pytest


class TestScoresFlag:
    def test_parse_scores_flag(self):
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--scores'])
        assert args.scores is True

    def test_scores_default_false(self):
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--polish'])
        assert args.scores is False

    def test_scores_mutually_exclusive_with_polish(self):
        from storyforge.cmd_revise import main
        with pytest.raises(SystemExit):
            main(['--scores', '--polish'])

    def test_scores_mutually_exclusive_with_structural(self):
        from storyforge.cmd_revise import main
        with pytest.raises(SystemExit):
            main(['--scores', '--structural'])


class TestGenerateScoresPlan:
    def test_generates_brief_pass_from_diagnosis(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01;s03;s05', 'priority': 'high', 'root_cause': 'brief'},
            {'principle': 'economy_clarity', 'scale': 'scene', 'avg_score': '2.5',
             'worst_items': 's01;s02', 'priority': 'high', 'root_cause': 'brief'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows)
        assert len(rows) >= 1
        # Should have at least one brief pass
        brief_passes = [r for r in rows if r['fix_location'] == 'brief']
        assert len(brief_passes) >= 1
        # Targets should include worst scenes
        all_targets = ';'.join(r['targets'] for r in brief_passes)
        assert 's01' in all_targets

    def test_generates_craft_pass_for_craft_root_cause(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high', 'root_cause': 'craft'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows)
        craft_passes = [r for r in rows if r['fix_location'] == 'craft']
        assert len(craft_passes) >= 1

    def test_brief_passes_come_before_craft(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high', 'root_cause': 'brief'},
            {'principle': 'dialogue_authenticity', 'scale': 'scene', 'avg_score': '2.5',
             'worst_items': 's02', 'priority': 'high', 'root_cause': 'craft'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows)
        # Find first brief and first craft pass positions
        brief_idx = next(i for i, r in enumerate(rows) if r['fix_location'] == 'brief')
        craft_idx = next(i for i, r in enumerate(rows) if r['fix_location'] == 'craft')
        assert brief_idx < craft_idx

    def test_no_actionable_items_returns_empty(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '4.5',
             'worst_items': '', 'priority': 'low', 'root_cause': 'craft'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows)
        assert rows == []

    def test_scenes_ranked_by_frequency(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'p1', 'scale': 'scene', 'avg_score': '2.0',
             'worst_items': 's01;s02;s03', 'priority': 'high', 'root_cause': 'brief'},
            {'principle': 'p2', 'scale': 'scene', 'avg_score': '2.0',
             'worst_items': 's01;s03', 'priority': 'high', 'root_cause': 'brief'},
            {'principle': 'p3', 'scale': 'scene', 'avg_score': '2.0',
             'worst_items': 's01', 'priority': 'medium', 'root_cause': 'brief'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows)
        brief_passes = [r for r in rows if r['fix_location'] == 'brief']
        # s01 appears in all 3, s03 in 2, s02 in 1
        # All should be targeted but s01 should appear
        all_targets = ';'.join(r['targets'] for r in brief_passes)
        assert 's01' in all_targets

    def test_excludes_act_scale(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'genre_contract', 'scale': 'act', 'avg_score': '1.5',
             'worst_items': '', 'priority': 'high', 'root_cause': 'brief'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows)
        assert rows == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_revise_scores.py -v`
Expected: FAIL — `_generate_scores_plan` and `args.scores` don't exist

- [ ] **Step 3: Add `--scores` flag to `parse_args`**

In `cmd_revise.py`, in `parse_args()`, after the `--polish` argument (line ~62), add:

```python
    parser.add_argument('--scores', action='store_true',
                        help='Auto-generate revision plan from scoring diagnosis (upstream + craft)')
```

- [ ] **Step 4: Update the mutual exclusivity check in `main()`**

In `main()`, find the mode count check (line ~1456):

```python
    mode_count = sum([args.structural, args.polish, args.naturalness])
```

Change to:

```python
    mode_count = sum([args.structural, args.polish, args.naturalness, args.scores])
```

- [ ] **Step 5: Implement `_generate_scores_plan`**

Insert after `_generate_structural_plan` (~line 450) in `cmd_revise.py`:

```python
def _generate_scores_plan(plan_file: str, diag_rows: list[dict]) -> list[dict]:
    """Generate a revision plan from scoring diagnosis data.

    Creates upstream (brief) passes for brief-root-cause items and
    targeted craft passes for craft-root-cause items. Returns empty list
    if no actionable items.
    """
    from collections import Counter

    # Filter to actionable scene-level items
    actionable = [r for r in diag_rows
                  if r.get('scale') == 'scene'
                  and r.get('priority') in ('high', 'medium')
                  and r.get('worst_items')]

    if not actionable:
        return []

    # Separate by root cause
    brief_items = [r for r in actionable if r.get('root_cause') == 'brief']
    craft_items = [r for r in actionable if r.get('root_cause') != 'brief']

    rows = []
    pass_num = 0

    # Brief passes: rank scenes by frequency across principles
    if brief_items:
        scene_freq = Counter()
        scene_principles = {}
        for item in brief_items:
            for sid in item['worst_items'].split(';'):
                sid = sid.strip()
                if sid:
                    scene_freq[sid] += 1
                    scene_principles.setdefault(sid, []).append(
                        item['principle'].replace('_', ' '))

        # Sort by frequency (chronic underperformers first)
        ranked = [sid for sid, _ in scene_freq.most_common()]

        # Build guidance from principles
        principle_names = sorted(set(
            item['principle'].replace('_', ' ') for item in brief_items))
        guidance = (
            'Score-driven upstream fixes. Weak principles: '
            + ', '.join(principle_names)
            + '. Scenes ranked by frequency of appearance across weak principles.'
            + ' Fix abstract, overspecified, or verbose brief fields.'
        )

        pass_num += 1
        rows.append({
            'pass': str(pass_num),
            'name': 'score-driven-briefs',
            'purpose': f'Fix briefs for {len(ranked)} scenes with brief-root-cause issues across {len(brief_items)} principles',
            'scope': 'scene-level',
            'targets': ';'.join(ranked),
            'guidance': guidance,
            'protection': 'voice-quality',
            'findings': 'scores',
            'status': 'pending',
            'model_tier': 'sonnet',
            'fix_location': 'brief',
        })

    # Craft pass: targeted polish for craft-root-cause items
    if craft_items:
        craft_scenes = set()
        craft_principles = []
        for item in craft_items:
            craft_principles.append(
                f'{item["principle"].replace("_", " ")} (avg {item.get("avg_score", "?")})')
            for sid in item['worst_items'].split(';'):
                sid = sid.strip()
                if sid:
                    craft_scenes.add(sid)

        guidance = (
            'Score-driven craft polish. Target principles:\n'
            + '\n'.join(f'  - {p}' for p in craft_principles)
            + '\nFollow the voice guide strictly. Preserve plot, character, and continuity.'
        )

        pass_num += 1
        rows.append({
            'pass': str(pass_num),
            'name': 'score-driven-craft',
            'purpose': f'Craft polish targeting {len(craft_items)} weak principles',
            'scope': 'scene-level',
            'targets': ';'.join(sorted(craft_scenes)),
            'guidance': guidance,
            'protection': 'voice-quality',
            'findings': 'scores',
            'status': 'pending',
            'model_tier': 'opus',
            'fix_location': 'craft',
        })

    if rows:
        _create_versioned_plan(plan_file, rows)
        log(f'Generated score-driven plan: {len(rows)} passes')

    return rows
```

- [ ] **Step 6: Wire `--scores` into `main()`**

In `main()`, after the `--polish` plan generation block (line ~1490) and before `elif os.path.isfile(csv_plan_file)`, add:

```python
    elif args.scores:
        log('Scores mode -- generating revision plan from diagnosis data...')
        diag_file = os.path.join(project_dir, 'working', 'scores', 'latest', 'diagnosis.csv')
        if not os.path.isfile(diag_file):
            log(f'ERROR: No diagnosis found at {diag_file}')
            log('Run: storyforge score first')
            sys.exit(1)
        diag_rows = _read_diagnosis(os.path.dirname(diag_file))
        plan_rows = _generate_scores_plan(csv_plan_file, diag_rows)
        if not plan_rows:
            log('No actionable items in diagnosis — nothing to revise')
            sys.exit(0)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_revise_scores.py -v`
Expected: All passed

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py tests/test_revise_scores.py
git commit -m "Add --scores flag for score-driven revision planning"
git push
```

---

### Task 5: Implement deferred redrafting

Change the pass execution loop to batch redrafts after all upstream passes complete.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py` (the main pass loop in `main()`, lines ~1682-1825)
- Create: `tests/test_deferred_redraft.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_deferred_redraft.py
"""Tests for deferred redrafting in revision pass execution."""

import os
import pytest


class TestDeferredRedraft:
    def test_collect_upstream_scenes(self):
        """_collect_upstream_scenes should gather all scenes from upstream passes."""
        from storyforge.cmd_revise import _collect_upstream_scenes

        plan_rows = [
            {'pass': '1', 'name': 'brief-fix-1', 'fix_location': 'brief',
             'targets': 's01;s02;s03', 'status': 'pending'},
            {'pass': '2', 'name': 'intent-fix', 'fix_location': 'intent',
             'targets': 's02;s04', 'status': 'pending'},
            {'pass': '3', 'name': 'craft-polish', 'fix_location': 'craft',
             'targets': 's01;s05', 'status': 'pending'},
        ]

        scenes, count = _collect_upstream_scenes(plan_rows)
        # Only brief + intent passes, not craft
        assert scenes == {'s01', 's02', 's03', 's04'}
        assert count == 2  # 2 upstream passes

    def test_no_upstream_passes_returns_empty(self):
        from storyforge.cmd_revise import _collect_upstream_scenes

        plan_rows = [
            {'pass': '1', 'name': 'craft', 'fix_location': 'craft',
             'targets': 's01', 'status': 'pending'},
        ]

        scenes, count = _collect_upstream_scenes(plan_rows)
        assert scenes == set()
        assert count == 0

    def test_skips_completed_passes(self):
        from storyforge.cmd_revise import _collect_upstream_scenes

        plan_rows = [
            {'pass': '1', 'name': 'brief-1', 'fix_location': 'brief',
             'targets': 's01', 'status': 'completed'},
            {'pass': '2', 'name': 'brief-2', 'fix_location': 'brief',
             'targets': 's02', 'status': 'pending'},
        ]

        scenes, count = _collect_upstream_scenes(plan_rows)
        assert scenes == {'s02'}
        assert count == 1

    def test_single_upstream_pass_still_defers(self):
        """Even with one upstream pass, redraft should be deferred (consistent behavior)."""
        from storyforge.cmd_revise import _collect_upstream_scenes

        plan_rows = [
            {'pass': '1', 'name': 'brief-fix', 'fix_location': 'brief',
             'targets': 's01;s02', 'status': 'pending'},
            {'pass': '2', 'name': 'craft', 'fix_location': 'craft',
             'targets': '', 'status': 'pending'},
        ]

        scenes, count = _collect_upstream_scenes(plan_rows)
        assert scenes == {'s01', 's02'}
        assert count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_deferred_redraft.py -v`
Expected: FAIL — `_collect_upstream_scenes` does not exist

- [ ] **Step 3: Implement `_collect_upstream_scenes`**

Add to `cmd_revise.py` after `_count_passes` (~line 200):

```python
def _collect_upstream_scenes(plan_rows: list[dict]) -> tuple[set[str], int]:
    """Scan plan for pending upstream passes and collect all target scenes.

    Returns (scene_ids, upstream_pass_count). Used to defer redrafting
    until all upstream CSV fixes are complete.
    """
    scenes = set()
    count = 0
    for row in plan_rows:
        if row.get('fix_location') not in ('brief', 'intent'):
            continue
        if row.get('status') == 'completed':
            continue
        count += 1
        targets = row.get('targets', '')
        for sid in targets.split(';'):
            sid = sid.strip()
            if sid:
                scenes.add(sid)
    return scenes, count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_deferred_redraft.py -v`
Expected: 4 passed

- [ ] **Step 5: Modify the main pass loop to defer redrafts**

In the main pass loop in `main()`, the hone delegation block (lines ~1752-1825) currently calls `_redraft_from_briefs` at line 1804. We need to:

1. **Before the main pass loop** (~line 1682), add lookahead:

```python
    # Check for deferred redrafting (multiple upstream passes)
    deferred_scenes, upstream_count = _collect_upstream_scenes(plan_rows)
    defer_redraft = upstream_count >= 1 and len(deferred_scenes) > 0
    if defer_redraft:
        log(f'Deferred redrafting enabled: {upstream_count} upstream passes, '
            f'{len(deferred_scenes)} scenes will be redrafted after all CSV fixes')
    redraft_needed = set()  # Track scenes that actually changed
```

2. **In the hone delegation block**, replace the redraft call at line 1801-1804:

Replace:
```python
            # Redraft affected scenes in full coaching mode
            if effective_coaching == 'full' and targets:
                affected = [t.strip() for t in targets.split(';') if t.strip()]
                _redraft_from_briefs(project_dir, affected, pass_model, log_dir)
```

With:
```python
            # Track or execute redraft
            if effective_coaching == 'full' and targets:
                affected = [t.strip() for t in targets.split(';') if t.strip()]
                if defer_redraft:
                    redraft_needed.update(affected)
                    log(f'  Deferred redraft for {len(affected)} scenes (will batch after all upstream passes)')
                else:
                    _redraft_from_briefs(project_dir, affected, pass_model, log_dir)
```

3. **After the main pass loop ends** (after the `for pass_num in range(...)` loop), add batch redraft:

```python
    # Batch redraft deferred scenes
    if defer_redraft and redraft_needed:
        log(f'\n=== Batch Redraft: {len(redraft_needed)} scenes ===')
        pass_model = select_revision_model('redraft', 'redraft from corrected briefs')
        _redraft_from_briefs(project_dir, sorted(redraft_needed), pass_model, log_dir)
```

- [ ] **Step 6: Run deferred redraft tests**

Run: `python3 -m pytest tests/test_deferred_redraft.py -v`
Expected: All passed

- [ ] **Step 7: Run full test suite**

Run: `python3 -m pytest tests/ --tb=short`
Expected: No regressions

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py tests/test_deferred_redraft.py
git commit -m "Add deferred redrafting to batch scene re-drafts after all upstream passes"
git push
```

---

### Task 6: Update revise skill for staleness awareness

Modify the SKILL.md to call staleness detection and adjust recommendations.

**Files:**
- Modify: `skills/revise/SKILL.md`

- [ ] **Step 1: Read current skill**

Read `skills/revise/SKILL.md` to understand the current structure — specifically the "Read Project State" and "Determine Mode" sections.

- [ ] **Step 2: Add staleness check to "Read Project State"**

In the section where the skill reads project state (scores, evaluations), add a staleness check step:

```markdown
### Staleness Check

Run the staleness check to determine how to weight evaluation findings:

```bash
python3 -c "
from storyforge.scoring import check_eval_staleness
import json, sys
result = check_eval_staleness('PROJECT_DIR')
print(json.dumps(result, indent=2))
"
```

**If `stale: true`:** The evaluation findings are historical context only. Do NOT use them to generate specific scene targets or structural recommendations. Base all revision planning on current scores (diagnosis.csv). Present a staleness notice to the author.

**If `stale: false`:** Evaluation findings are current and actionable. Use them alongside scores as today.

**If `eval_dir: null`:** No evaluation exists. Use scores only.
```

- [ ] **Step 3: Update "Determine Mode" with score-driven option**

Add the stale-eval option set to the mode determination section. When eval is stale, the primary options become:

```markdown
#### When Evaluation Is Stale

> **Note:** The evaluation from {eval_date} has been superseded by significant changes ({reasons}). Recommendations below are based on current scores. Evaluation findings are shown as historical context below.

1. **Score-driven revision** (`storyforge revise --scores`) — Upstream brief fixes + targeted craft polish based on current diagnosis. **Recommended.**
2. **Polish loop** (`storyforge revise --polish --loop`) — Craft-only convergence from current scores.
3. **Re-evaluate first** — Run `storyforge evaluate` before planning revision.
4. **Use evaluation anyway** — Treat stale evaluation findings as still actionable (author override).
```

- [ ] **Step 4: Add `--scores` to the script delegation section**

In the script delegation section where option A/B is offered, add the `--scores` command:

```markdown
> **Option A: Run it here**
> I'll launch the command in this conversation.
>
> **Option B: Run it yourself**
> ```bash
> cd [project_dir] && [plugin_path]/storyforge revise --scores
> ```
```

- [ ] **Step 5: Commit**

```bash
git add skills/revise/SKILL.md
git commit -m "Update revise skill with staleness detection and score-driven mode"
git push
```

---

### Task 7: Version bump

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Bump patch version**

Change `"version": "1.15.1"` to `"version": "1.16.0"` (minor bump — new feature).

- [ ] **Step 2: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 1.16.0"
git push
```
